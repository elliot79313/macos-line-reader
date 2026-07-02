"""Unread-chat detection in the sidebar list (highest-risk module).

Strategy: color-mask the unread-count badge (LINE green by default) inside the
configured chat_list region, contour-filter by size/aspect, then OCR the row
around each badge to get the chat name. Calibrate thresholds with
scripts/diagnose_badges.py before first use.
"""

from __future__ import annotations

import logging

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
