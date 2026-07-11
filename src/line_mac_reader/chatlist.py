"""Unread-chat detection in the sidebar list (highest-risk module).

Strategy: color-mask the unread-count badge (LINE green by default) inside the
configured chat_list region, contour-filter by size/aspect, then OCR the row
around each badge to get the chat name. Calibrate thresholds with
scripts/diagnose_badges.py before first use.
"""

from __future__ import annotations

import logging
import subprocess
import time

from .config import Config
from .models import Rect, UnreadChat
from .ocr import ocr
from .screen import Screen

log = logging.getLogger(__name__)


def find_badges(img, cfg: Config) -> list[tuple[int, int, int, int]]:
    """Return badge bounding boxes (x, y, w, h) in the image's own pixels.

    Pure image-in/boxes-out so the diagnostic script can reuse it.
    """
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array(cfg.badge.hsv_lower, dtype=np.uint8),
        np.array(cfg.badge.hsv_upper, dtype=np.uint8),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if not (cfg.badge.min_area <= area <= cfg.badge.max_area):
            continue
        aspect = w / h if h else 0
        if not (cfg.badge.min_aspect <= aspect <= cfg.badge.max_aspect):
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[1])
    return boxes


def usable_rows(img_height_px: int, exclude_pt: int, px_per_pt: float) -> int:
    """Pixel row where the clickable chat list ends: everything below is the
    AD-banner keep-out strip (pure, testable)."""
    return max(0, img_height_px - round(exclude_pt * px_per_pt))


def is_excluded(name: str, patterns: tuple[str, ...]) -> bool:
    """Blocklist check for unread/--all scans (whitespace/case-insensitive
    substring), used to skip business/official accounts."""
    n = "".join(name.split()).lower()
    return any(p and "".join(p.split()).lower() in n for p in patterns)


def fuzzy_dup(name: str, seen, threshold: float = 0.7) -> bool:
    """Is `name` an OCR variant of an already-processed chat name?

    Titles OCR slightly differently on each open (「正光診所」/「止光診所」,
    four spellings of "Legacy Taiwan里程…"), so duplicate detection uses
    similarity, not equality. `seen` holds normalized names.

    The threshold is deliberately conservative: merging two genuinely
    different chats loses data, an occasional duplicate entry does not.
    Heavily garbled titles (most characters misread) can still slip through
    as duplicates — that is a title-OCR quality problem, not a dedup one.
    """
    from difflib import SequenceMatcher

    n = "".join(name.split()).lower()
    return any(SequenceMatcher(None, n, s).ratio() >= threshold for s in seen)


def names_match(a: str, b: str) -> bool:
    """Fuzzy chat-name comparison: whitespace-insensitive containment either
    way, so OCR truncation (「王小明的旅遊…」) still matches."""
    na = "".join(a.split()).lower()
    nb = "".join(b.split()).lower()
    return bool(na) and bool(nb) and (na in nb or nb in na)


def _merge_rows(boxes: list[tuple[int, int, int, int]], row_height_px: int
                ) -> list[tuple[int, int, int, int]]:
    """Collapse multiple badge fragments that fall within the same list row."""
    merged: list[tuple[int, int, int, int]] = []
    for b in boxes:
        if merged and abs((b[1] + b[3] // 2) - (merged[-1][1] + merged[-1][3] // 2)) < row_height_px // 2:
            continue
        merged.append(b)
    return merged


class ChatList:
    def __init__(self, cfg: Config, screen: Screen, window_rect: Rect):
        self.cfg = cfg
        self.screen = screen
        self.window_rect = window_rect

    def region_on_screen(self) -> Rect:
        r = self.cfg.regions.chat_list
        return r.offset(self.window_rect.x, self.window_rect.y)

    def scan_unread(self, debug_save=None) -> list[UnreadChat]:
        """Detect unread rows currently visible in the chat list.

        Scrolling the list itself is not done in v1: keep the list at the top
        (LINE sorts unread/newest first, so unread rows are normally visible).
        """
        region = self.region_on_screen()
        img = self.screen.capture(region)
        px_per_pt = self.screen.image_scale(img, region)
        img = img[:usable_rows(img.shape[0],
                               self.cfg.regions.list_bottom_exclude,
                               px_per_pt), :]

        badges = find_badges(img, self.cfg)
        row_h_px = int(self.cfg.regions.row_height * px_per_pt)
        badges = _merge_rows(badges, row_h_px)
        log.info("Detected %d unread badge(s)", len(badges))

        chats: list[UnreadChat] = []
        for idx, (bx, by, bw, bh) in enumerate(badges):
            badge_cy = by + bh // 2
            row_top = max(0, badge_cy - row_h_px // 2)
            row = img[row_top:row_top + row_h_px, :]

            name, conf = self._ocr_row_name(row, exclude_from_x=bx)
            if debug_save is not None:
                debug_save(f"row_{idx}_{name or 'unknown'}", row)

            # Click point: middle of the row, in logical screen coordinates.
            click_x = region.x + region.width // 2
            click_y = region.y + round(badge_cy / px_per_pt)
            chats.append(UnreadChat(
                chat_name=name or f"<unreadable row {idx}>",
                row_index=idx,
                click_point=(click_x, click_y),
                badge_bbox=(
                    round(bx / px_per_pt), round(by / px_per_pt),
                    round(bw / px_per_pt), round(bh / px_per_pt),
                ),
                name_ocr_confidence=conf,
            ))
        return chats

    def scan_visible_rows(self, debug_save=None) -> list[UnreadChat]:
        """Enumerate ALL rows currently visible in the chat list (--all mode).

        Rows are taken on a fixed grid of regions.row_height; rows whose name
        OCR comes back empty are skipped. The list itself is not scrolled.
        """
        region = self.region_on_screen()
        img = self.screen.capture(region)
        px_per_pt = self.screen.image_scale(img, region)
        img = img[:usable_rows(img.shape[0],
                               self.cfg.regions.list_bottom_exclude,
                               px_per_pt), :]
        row_h_px = int(self.cfg.regions.row_height * px_per_pt)

        chats: list[UnreadChat] = []
        for idx in range(img.shape[0] // row_h_px):
            top = idx * row_h_px
            row = img[top:top + row_h_px, :]
            # Cut before the right-hand column (HH:MM + badge) so it doesn't
            # pollute the name.
            name, conf = self._ocr_row_name(
                row, exclude_from_x=int(row.shape[1] * 0.72))
            if debug_save is not None:
                debug_save(f"allrow_{idx}_{name or 'empty'}", row)
            if not name:
                continue
            chats.append(UnreadChat(
                chat_name=name,
                row_index=idx,
                click_point=(
                    region.x + region.width // 2,
                    region.y + round((top + row_h_px // 2) / px_per_pt),
                ),
                name_ocr_confidence=conf,
            ))
        log.info("Enumerated %d visible chat row(s)", len(chats))
        return chats

    def _list_hash(self) -> str:
        import hashlib

        img = self.screen.capture(self.region_on_screen())
        return hashlib.sha1(img.tobytes()).hexdigest()

    def _scroll_list(self, dy_pt: int) -> None:
        import pyautogui

        from .screen import scroll_vertical

        pyautogui.moveTo(*self.region_on_screen().center)
        scroll_vertical(dy_pt, mode=self.cfg.scroll.mode,
                        wheel_step=self.cfg.scroll.step)
        time.sleep(self.cfg.timing.scroll_wait)

    def scroll_list_to_top(self, max_iter: int = 15) -> None:
        """Reset the chat list to its top before a paged scan."""
        region = self.region_on_screen()
        prev = self._list_hash()
        for _ in range(max_iter):
            self._scroll_list(region.height * 2)
            cur = self._list_hash()
            if cur == prev:
                return
            prev = cur

    def scroll_list_down(self) -> bool:
        """Advance the chat list by ~one page; False when already at the
        bottom (screen no longer changes)."""
        region = self.region_on_screen()
        before = self._list_hash()
        self._scroll_list(-int(region.height * self.cfg.scroll.page_fraction))
        return self._list_hash() != before

    def open_chat_by_search(self, name: str) -> bool:
        """Open a chat via LINE's search box (--chat mode); works regardless
        of unread state. Returns False if the opened chat's title doesn't
        match `name` (so the caller can avoid reading the wrong chat)."""
        import pyautogui

        sb = self.cfg.regions.search_box.offset(
            self.window_rect.x, self.window_rect.y)
        pyautogui.click(*sb.center)
        time.sleep(self.cfg.timing.click_wait)
        # Clear any previous query, then paste (typewrite can't produce CJK).
        pyautogui.hotkey("command", "a")
        pyautogui.press("backspace")
        subprocess.run(["pbcopy"], input=name.encode("utf-8"), check=True)
        pyautogui.hotkey("command", "v")
        time.sleep(self.cfg.timing.search_wait)

        # Search results include section headers (好友/群組/聊天…), so the
        # first row is NOT necessarily the chat. OCR the result list and
        # click the line that matches the requested name.
        region = self.region_on_screen()
        click_y = self._find_result_y(name, region)
        if click_y is None:
            log.warning("No OCR match for %r in search results; "
                        "falling back to the first row", name)
            click_y = region.y + self.cfg.regions.row_height // 2
        pyautogui.click(region.x + region.width // 2, click_y)
        time.sleep(self.cfg.timing.chat_open_wait)
        return self.verify_open_chat(name)

    def _find_result_y(self, name: str, region: Rect) -> int | None:
        """OCR the search-result list; return the logical screen y of the
        first line matching `name`, or None."""
        img = self.screen.capture(region)
        px_per_pt = self.screen.image_scale(img, region)
        for line in ocr(img, self.cfg.ocr, extra_words=(name,)):
            if names_match(name, line.text):
                cy = line.bbox[1] + line.bbox[3] / 2
                return region.y + round(cy / px_per_pt)
        return None

    def read_title(self, hint: str = "") -> str:
        """OCR the open chat's title bar — the ground truth for identity.

        Row-name OCR from the list is unreliable (a misaligned row grid
        happily returns the previous row's preview text), so callers should
        prefer this as the canonical chat name once a chat is open.
        """
        title_region = self.cfg.regions.chat_title.offset(
            self.window_rect.x, self.window_rect.y)
        extra = (hint,) if hint else ()
        lines = ocr(self.screen.capture(title_region), self.cfg.ocr,
                    extra_words=extra)
        return " ".join(l.text for l in lines).strip()

    def verify_open_chat(self, name: str) -> bool:
        """OCR the open chat's title bar and fuzzily compare with `name`.

        Lenient on purpose: if the title can't be OCR'd at all we proceed
        with a warning rather than fail (title fonts OCR poorly at times).
        """
        title = self.read_title(hint=name)
        if not title:
            log.warning("Could not OCR chat title; assuming %r opened", name)
            return True
        if names_match(name, title):
            return True
        log.error("Opened chat title %r does not match requested %r", title, name)
        return False

    def _ocr_row_name(self, row_img, exclude_from_x: int) -> tuple[str, float]:
        """OCR a chat-list row crop; the name is the top-most text line.

        The crop stops before the badge/time column so unread counts and
        HH:MM don't pollute the name.
        """
        cut = max(exclude_from_x - 4, row_img.shape[1] // 2)
        crop = row_img[:, :cut]
        lines = ocr(crop, self.cfg.ocr)
        if not lines:
            return "", 0.0
        first = lines[0]  # rows show name on top, preview text below
        return first.text.strip(), first.confidence
