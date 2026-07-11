"""Read one open chat: fast capture scroll, then batch OCR + layout parsing.

Two phases (v2 — replaces the OCR-inside-the-scroll-loop design):

1. CAPTURE: scroll up quickly, saving raw screenshots. No OCR between
   scrolls except a cheap cutoff probe every Nth screen, so scrolling runs
   at UI-repaint speed. Stops at the cutoff probe, when the screen stops
   changing (top of chat), or at max_scrolls.
2. PARSE: OCR each captured screen ONCE (whole image — Vision returns every
   text line with its bounding box), then reconstruct the transcript from
   layout:
     - "已讀" read-receipts are dropped
     - standalone 「上午/下午 H:MM」/「HH:MM」 lines become time labels,
       attached to the vertically nearest bubble
     - short centered lines that parse as dates (「昨天」「今天」「2026年7月1日」)
       become date separators
     - remaining lines group into bubbles by side (left/incoming vs
       right/outgoing) and vertical gaps
   Overlapping captures merge by message keys; timestamps resolve
   top-to-bottom against the date-separator context.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median

from .config import Config, LayoutConfig
from .models import Message, Rect
from .ocr import OcrLine, ocr
from .screen import Screen
from .utils_time import DateContext, parse_date_separator, parse_time_of_day, tzinfo_for

log = logging.getLogger(__name__)

ME = "me"
_RE_TIME_ONLY = re.compile(
    r"(?:(?:上午|下午|午前|午後)\s*)?\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?"
)
_RE_TRAILING_TIME = re.compile(
    r"\s*(?:(?:上午|下午|午前|午後)\s*)?\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?\s*$"
)
_READ_RECEIPTS = {"已讀", "已读", "既読", "Read"}
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
    """One transcript row: either a date separator or a message."""

    kind: str  # "separator" | "message"
    text: str
    sender: str = ""
    time_of_day: tuple[int, int] | None = None
    ocr_confidence: float = 0.0
    y: int = 0  # top of the block within its capture (physical px)

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.sender}|{' '.join(self.text.split())}"


# ---------------------------------------------------------------------------
# Layout parsing (pure functions — unit-testable with synthetic OcrLines)
# ---------------------------------------------------------------------------

@dataclass
class _TimeLabel:
    tod: tuple[int, int]
    y_center: float


@dataclass
class _Bubble:
    side: str  # "left" | "right"
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def top(self) -> int:
        return min(l.bbox[1] for l in self.lines)

    @property
    def bottom(self) -> int:
        return max(l.bbox[1] + l.bbox[3] for l in self.lines)


def _strip_receipt(text: str) -> str:
    t = text.strip()
    for r in _READ_RECEIPTS:
        if t == r:
            return ""
        if t.startswith(r + " ") or t.startswith(r):
            candidate = t[len(r):].strip()
            # Only strip when what remains is a bare time label
            # (Vision sometimes merges 「已讀」 with the adjacent time).
            if not candidate or _RE_TIME_ONLY.fullmatch(candidate):
                return candidate
    return t


def _is_separator(line: OcrLine, width: int, today: date, cfg: LayoutConfig) -> bool:
    text = line.text.strip()
    if len(text) > cfg.separator_max_chars:
        return False
    if parse_date_separator(text, today) is None:
        return False
    lo, hi = cfg.separator_center_band
    center = (line.bbox[0] + line.bbox[2] / 2) / width
    return lo <= center <= hi


def parse_layout(lines: list[OcrLine], width: int, chat_name: str,
                 today: date, cfg: LayoutConfig, px_per_pt: float = 1.0
                 ) -> list[ParsedItem]:
    """Reconstruct transcript items from one whole-screen OCR result."""
    gap_px = cfg.bubble_gap * px_per_pt
    separators: list[ParsedItem] = []
    time_labels: list[_TimeLabel] = []
    text_lines: list[OcrLine] = []

    for raw in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        text = _strip_receipt(raw.text)
        if not text:
            continue
        if _RE_TIME_ONLY.fullmatch(text):
            tod = parse_time_of_day(text)
            if tod:
                time_labels.append(_TimeLabel(tod, raw.bbox[1] + raw.bbox[3] / 2))
            continue
        if _is_separator(raw, width, today, cfg):
            separators.append(ParsedItem(
                kind="separator", text=text, y=raw.bbox[1],
                ocr_confidence=raw.confidence))
            continue
        text_lines.append(OcrLine(text, raw.bbox, raw.confidence))

    # Group text lines into bubbles by side + vertical adjacency.
    bubbles: list[_Bubble] = []
    for line in text_lines:
        side = "left" if line.bbox[0] < cfg.side_ratio * width else "right"
        if (bubbles and bubbles[-1].side == side
                and line.bbox[1] - bubbles[-1].bottom <= gap_px):
            bubbles[-1].lines.append(line)
        else:
            bubbles.append(_Bubble(side=side, lines=[line]))

    items = separators + [
        _bubble_to_item(b, chat_name, time_labels, gap_px) for b in bubbles
    ]
    items = [i for i in items if i is not None]
    items.sort(key=lambda i: i.y)
    return items


def _bubble_to_item(bubble: _Bubble, chat_name: str,
                    time_labels: list[_TimeLabel], gap_px: float
                    ) -> ParsedItem | None:
    sender = ME if bubble.side == "right" else chat_name
    lines = bubble.lines
    time_of_day: tuple[int, int] | None = None

    # Group-chat sender heuristic: the sender label above an incoming bubble
    # renders in a smaller font — only reassign when the first line is both
    # short AND noticeably smaller than the rest (avoids eating a real first
    # line like 「早安」 in direct chats).
    if bubble.side == "left" and len(lines) >= 2:
        first, rest = lines[0], lines[1:]
        rest_h = median(l.bbox[3] for l in rest)
        if (0 < len(first.text) <= 24 and first.bbox[3] < 0.85 * rest_h
                and first.text not in _KIND_MARKERS):
            sender = first.text
            lines = rest

    texts: list[str] = []
    for line in lines:
        t = line.text
        m = _RE_TRAILING_TIME.search(t)
        if m and len(t) > len(m.group(0).strip()):
            tod = parse_time_of_day(m.group(0))
            if tod:
                time_of_day = time_of_day or tod
                t = _RE_TRAILING_TIME.sub("", t).strip()
        if t:
            texts.append(t)
    if not texts:
        return None

    # Attach the vertically nearest standalone time label.
    if time_of_day is None:
        best, best_dist = None, gap_px * 2
        for label in time_labels:
            if bubble.top - gap_px <= label.y_center <= bubble.bottom + gap_px:
                dist = abs(label.y_center - bubble.bottom)
                if dist < best_dist:
                    best, best_dist = label, dist
        if best is not None:
            time_of_day = best.tod

    text = "\n".join(texts).strip()
    marker = text.replace("[", "").replace("]", "").strip()
    if marker in _KIND_MARKERS:
        text = f"[{marker}]"
    return ParsedItem(
        kind="message", text=text, sender=sender, time_of_day=time_of_day,
        y=bubble.top,
        ocr_confidence=sum(l.confidence for l in bubble.lines) / len(bubble.lines),
    )


# ---------------------------------------------------------------------------
# Merging overlapping captures
# ---------------------------------------------------------------------------

def merge_transcripts(upper: list[ParsedItem], lower: list[ParsedItem]
                      ) -> list[ParsedItem]:
    """Merge two top-to-bottom item lists where `upper` was captured after
    scrolling up, so upper's bottom overlaps lower's top."""
    max_overlap = min(len(upper), len(lower))
    for k in range(max_overlap, 0, -1):
        if [i.key for i in upper[-k:]] == [i.key for i in lower[:k]]:
            return upper + lower[k:]
    return upper + lower


# ---------------------------------------------------------------------------
# Cutoff detection
# ---------------------------------------------------------------------------

def items_reach_cutoff(items: list[ParsedItem], cutoff: datetime,
                       tz, today: date) -> bool:
    """True when this (partial) transcript already extends past the cutoff.

    Two triggers, walking top-to-bottom:
    - a date separator at/before the cutoff's date: everything above it is
      from an even earlier day, so capture can stop;
    - a message whose resolved timestamp is <= cutoff.
    """
    ctx = DateContext(tz, today)
    for item in items:
        if item.kind == "separator":
            d = parse_date_separator(item.text, today)
            if d is not None and d <= cutoff.date():
                return True
            ctx.feed_separator(item.text)
            continue
        if item.time_of_day and ctx.current is not None:
            ts, _ = ctx.resolve(*item.time_of_day)
            if ts <= cutoff:
                return True
    return False


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------

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

        # --- phase 1: fast capture ------------------------------------------
        screens: list = []
        parsed_cache: dict[int, list[ParsedItem]] = {}
        prev_hash: str | None = None
        stalls = 0
        check_every = max(1, self.cfg.scroll.cutoff_check_every)

        # Scroll events land at the cursor position; park it once instead of
        # a moveTo (plus pyautogui pause) on every iteration.
        pyautogui.moveTo(*region.center)

        for i in range(self.cfg.scroll.max_scrolls + 1):
            img = self.screen.capture(region)
            digest = hashlib.sha1(img.tobytes()).hexdigest()
            if digest == prev_hash:
                stalls += 1
                if stalls >= self.cfg.scroll.stall_limit:
                    log.info("[%s] screen stopped changing — top of chat", chat_name)
                    break
            else:
                stalls = 0
                screens.append(img)
                if self.debug_save:
                    self.debug_save(f"{chat_name}_scroll{len(screens) - 1}", img)
                if (len(screens) - 1) % check_every == 0:
                    idx = len(screens) - 1
                    parsed_cache[idx] = self.parse_screen(img, chat_name, today)
                    if items_reach_cutoff(parsed_cache[idx], cutoff, self.tz, today):
                        log.info("[%s] cutoff visible after %d screen(s)",
                                 chat_name, len(screens))
                        break
            prev_hash = digest
            self._scroll_up(region)
            time.sleep(self.cfg.timing.scroll_wait)

        # --- phase 2: batch OCR + merge --------------------------------------
        transcript: list[ParsedItem] = []
        for idx, img in enumerate(screens):
            items = parsed_cache.get(idx)
            if items is None:
                items = self.parse_screen(img, chat_name, today)
            transcript = merge_transcripts(items, transcript)

        return self._finalize(transcript, cutoff, today, chat_name)

    def _scroll_up(self, region: Rect) -> None:
        """One upward scroll step.

        "pixel" mode posts a native pixel-unit scroll event covering
        page_fraction of the region per step — an order of magnitude fewer
        iterations than wheel clicks. "wheel" mode is the pyautogui fallback.
        """
        if self.cfg.scroll.mode == "pixel":
            try:
                import Quartz

                dy = int(region.height * self.cfg.scroll.page_fraction)
                ev = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitPixel, 1, dy)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
                return
            except ImportError:
                log.warning("Quartz unavailable; falling back to wheel scroll")
        import pyautogui

        pyautogui.scroll(self.cfg.scroll.step)  # positive = scroll up

    def parse_screen(self, img, chat_name: str, today: date) -> list[ParsedItem]:
        """One whole-image OCR pass, then layout reconstruction."""
        lines = ocr(img, self.cfg.ocr)
        px_per_pt = self.screen.image_scale(img, self._messages_region())
        return parse_layout(lines, img.shape[1], chat_name, today,
                            self.cfg.layout, px_per_pt=px_per_pt)

    def _finalize(self, transcript: list[ParsedItem], cutoff: datetime,
                  today: date, chat_name: str) -> list[Message]:
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
                kind=_kind_of(item.text),
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
    return _KIND_MARKERS.get(stripped, "text")
