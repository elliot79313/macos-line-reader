"""Read one open chat: scroll up, screenshot, OCR, rebuild timestamps, dedup.

Flow (SOW §6.4):
1. The chat opens at the bottom (newest). Determine the cutoff time.
2. Capture the messages region, segment it into per-bubble blocks, OCR each.
3. Scroll up and repeat until a message older than cutoff appears, the top of
   the chat is reached (screen stops changing), or max_scrolls hits.
4. Merge overlapping captures by message keys, resolve HH:MM against date
   separators (top-to-bottom), and return messages oldest-first.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .models import Message, Rect
from .ocr import OcrLine, ocr
from .screen import Screen
from .utils_time import DateContext, parse_date_separator, parse_time_of_day, tzinfo_for

log = logging.getLogger(__name__)

ME = "me"
_RE_TRAILING_TIME = re.compile(
    r"\s*(?:(?:上午|下午|午前|午後)\s*)?\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?\s*$"
)
_KIND_MARKERS = {
    "貼圖": "sticker",
    "照片": "image",
    "圖片": "image",
    "相簿": "image",
    "影片": "image",
    "檔案": "unknown",
}


@dataclass
class ParsedItem:
    """One transcript row: either a date separator or a message candidate."""

    kind: str  # "separator" | "message" | "media"
    text: str
    sender: str = ""
    time_of_day: tuple[int, int] | None = None
    ocr_confidence: float = 0.0
    y: int = 0  # top of the block within its capture (physical px)

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.sender}|{' '.join(self.text.split())}"


# --------------------------------------------------------------------------
# Segmentation (pure numpy — unit-testable)
# --------------------------------------------------------------------------

def row_activity(gray, background_tolerance: int = 18):
    """Boolean per-row mask: does this pixel row contain non-background content?"""
    import numpy as np

    bg = np.median(gray)
    diff = np.abs(gray.astype(np.int16) - int(bg)) > background_tolerance
    return diff.mean(axis=1) > 0.01


def segment_bands(active, min_gap: int = 8, min_height: int = 10
                  ) -> list[tuple[int, int]]:
    """Split a row-activity mask into (top, bottom) content bands.

    Gaps shorter than min_gap merge adjacent bands (lines within one bubble);
    bands shorter than min_height are dropped as noise.
    """
    bands: list[tuple[int, int]] = []
    start = None
    last_active = -1
    gap = 0
    for i, a in enumerate(active):
        if a:
            if start is None:
                start = i
            last_active = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                end = last_active + 1
                if end - start >= min_height:
                    bands.append((start, end))
                start, gap = None, 0
    if start is not None:
        end = last_active + 1
        if end - start >= min_height:
            bands.append((start, end))
    return bands


def block_side(gray_block, background_tolerance: int = 18) -> str:
    """'left' (incoming) or 'right' (outgoing) by horizontal center of mass."""
    import numpy as np

    bg = np.median(gray_block)
    mask = np.abs(gray_block.astype(np.int16) - int(bg)) > background_tolerance
    cols = mask.mean(axis=0)
    total = cols.sum()
    if total == 0:
        return "left"
    centroid = (cols * np.arange(len(cols))).sum() / total
    return "right" if centroid > len(cols) * 0.55 else "left"


# --------------------------------------------------------------------------
# Parsing one captured screen
# --------------------------------------------------------------------------

def parse_block(lines: list[OcrLine], side: str, chat_name: str,
                today, block_top: int) -> ParsedItem | None:
    """Turn the OCR lines of one segmented block into a ParsedItem."""
    if not lines:
        return None
    joined = " ".join(l.text for l in lines).strip()
    if not joined:
        return None

    # Date separator: a single short centered line that parses as a date.
    if len(lines) <= 2 and parse_date_separator(joined, today) is not None:
        return ParsedItem(kind="separator", text=joined, y=block_top,
                          ocr_confidence=_avg_conf(lines))

    time_of_day = None
    text_lines: list[str] = []
    sender = ME if side == "right" else chat_name
    for i, line in enumerate(lines):
        t = line.text.strip()
        tod = parse_time_of_day(t)
        if tod and _RE_TRAILING_TIME.fullmatch(t):
            time_of_day = time_of_day or tod  # standalone time label
            continue
        if tod and _RE_TRAILING_TIME.search(t):
            time_of_day = time_of_day or tod
            t = _RE_TRAILING_TIME.sub("", t).strip()
        # Group-chat heuristic: a short first line on an incoming bubble with
        # more lines below is likely the sender's display name.
        if i == 0 and side == "left" and len(lines) > 1 and 0 < len(t) <= 24 \
                and not parse_time_of_day(t) and t not in _KIND_MARKERS:
            sender = t
            continue
        if t:
            text_lines.append(t)

    text = "\n".join(text_lines).strip()
    if not text and time_of_day is None:
        return None
    marker = text.replace("[", "").replace("]", "").strip()
    if marker in _KIND_MARKERS:
        text = f"[{marker}]"
    elif not text:
        text = "[無文字內容]"
    return ParsedItem(kind="message", text=text, sender=sender,
                      time_of_day=time_of_day, y=block_top,
                      ocr_confidence=_avg_conf(lines))


def _avg_conf(lines: list[OcrLine]) -> float:
    return sum(l.confidence for l in lines) / len(lines) if lines else 0.0


# --------------------------------------------------------------------------
# Merging overlapping captures
# --------------------------------------------------------------------------

def merge_transcripts(upper: list[ParsedItem], lower: list[ParsedItem]
                      ) -> list[ParsedItem]:
    """Merge two top-to-bottom item lists where `upper` was captured after
    scrolling up, so upper's bottom overlaps lower's top."""
    max_overlap = min(len(upper), len(lower))
    for k in range(max_overlap, 0, -1):
        if [i.key for i in upper[-k:]] == [i.key for i in lower[:k]]:
            return upper + lower[k:]
    return upper + lower


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------

class ChatReader:
    def __init__(self, cfg: Config, screen: Screen, window_rect: Rect,
                 debug_save=None):
        self.cfg = cfg
        self.screen = screen
        self.window_rect = window_rect
        self.debug_save = debug_save
        self.tz = tzinfo_for(cfg.timezone)

    def _messages_region(self) -> Rect:
        return self.cfg.regions.messages.offset(self.window_rect.x, self.window_rect.y)

    def read_chat(self, chat_name: str, cutoff: datetime) -> list[Message]:
        """Read messages newer than `cutoff` from the currently open chat."""
        import pyautogui

        region = self._messages_region()
        today = datetime.now(self.tz).date()
        transcript: list[ParsedItem] = []
        prev_hash: str | None = None
        stalls = 0

        for scroll_i in range(self.cfg.scroll.max_scrolls + 1):
            img = self.screen.capture(region)
            if self.debug_save:
                self.debug_save(f"{chat_name}_scroll{scroll_i}", img)

            digest = hashlib.sha1(img.tobytes()).hexdigest()
            if digest == prev_hash:
                stalls += 1
                if stalls >= self.cfg.scroll.stall_limit:
                    log.info("[%s] screen stopped changing — top of chat", chat_name)
                    break
            else:
                stalls = 0
            prev_hash = digest

            items = self.parse_screen(img, chat_name, today)
            transcript = merge_transcripts(items, transcript)

            if self._reached_cutoff(transcript, cutoff, today):
                log.info("[%s] reached cutoff after %d scroll(s)", chat_name, scroll_i)
                break

            pyautogui.moveTo(*region.center)
            pyautogui.scroll(self.cfg.scroll.step)  # positive = scroll up
            time.sleep(self.cfg.timing.scroll_wait)

        return self._finalize(transcript, cutoff, today, chat_name)

    def parse_screen(self, img, chat_name: str, today) -> list[ParsedItem]:
        """Segment a messages-region capture into blocks and parse each."""
        import cv2

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        px_per_pt = self.screen.image_scale(img, self._messages_region())
        active = row_activity(gray)
        bands = segment_bands(
            active,
            min_gap=int(8 * px_per_pt),
            min_height=int(10 * px_per_pt),
        )

        items: list[ParsedItem] = []
        for top, bottom in bands:
            block = img[top:bottom, :]
            side = block_side(gray[top:bottom, :])
            lines = ocr(block, self.cfg.ocr)
            item = parse_block(lines, side, chat_name, today, block_top=top)
            if item:
                items.append(item)
        return items

    def _reached_cutoff(self, transcript: list[ParsedItem], cutoff: datetime,
                        today) -> bool:
        """True once the transcript's earliest dated message is at/before cutoff."""
        ctx = DateContext(self.tz, today)
        for item in transcript:
            if item.kind == "separator":
                ctx.feed_separator(item.text)
                continue
            if item.time_of_day and ctx.current is not None:
                ts, _ = ctx.resolve(*item.time_of_day)
                return ts <= cutoff
            return False  # earliest visible message not confidently dated yet
        return False

    def _finalize(self, transcript: list[ParsedItem], cutoff: datetime,
                  today, chat_name: str) -> list[Message]:
        """Resolve timestamps top-to-bottom and keep messages after cutoff.

        Cutoff comparison is lenient: messages whose timestamp could not be
        confidently determined are kept (flagged low) — better to over-read
        than to miss messages; dedup upstream handles overlap.
        """
        ctx = DateContext(self.tz, today)
        out: list[Message] = []
        seen: set[tuple] = set()
        last_time: tuple[int, int] | None = None
        for item in transcript:
            if item.kind == "separator":
                ctx.feed_separator(item.text)
                last_time = None
                continue
            ts: datetime | None = None
            confidence = "low"
            tod = item.time_of_day or last_time
            if tod:
                ts, confidence = ctx.resolve(*tod)
                if item.time_of_day is None and confidence == "high":
                    confidence = "low"  # borrowed time from a neighbor
                last_time = item.time_of_day or last_time
            if ts is not None and confidence == "high" and ts <= cutoff:
                continue
            msg = Message(
                sender=item.sender or chat_name,
                text=item.text,
                timestamp_est=ts,
                timestamp_confidence=confidence,
                kind=item.kind if item.kind != "message" else _kind_of(item.text),
                ocr_confidence=round(item.ocr_confidence, 3),
            )
            k = (msg.sender, msg.text, ts.isoformat() if ts else None)
            if k in seen:
                continue
            seen.add(k)
            out.append(msg)
        return out  # transcript is already oldest-first (top-to-bottom)


def _kind_of(text: str) -> str:
    stripped = text.strip("[]").strip()
    return _KIND_MARKERS.get(stripped, "text" if text != "[無文字內容]" else "unknown")
