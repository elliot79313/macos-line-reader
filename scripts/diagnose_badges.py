#!/usr/bin/env python3
"""Badge-detection diagnostic (SOW M2).

Captures the chat-list region, runs badge detection with the current config,
and writes annotated images so thresholds and regions can be calibrated:

    python scripts/diagnose_badges.py --config config.yaml
    python scripts/diagnose_badges.py --config config.yaml --sample 120,340

Outputs into debug/diagnose_<timestamp>/:
    chatlist.png        raw capture of the configured chat_list region
    mask.png            the HSV badge mask (white = matched)
    annotated.png       capture with badge boxes (green) and row bands (blue)
    fullwindow.png      the whole LINE window, with the chat_list /
                        messages / chat_title regions outlined

--sample X,Y prints the HSV value at that point of the chat-list capture
(physical px, as seen in chatlist.png) — point it at a badge to derive
hsv_lower/hsv_upper.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from line_mac_reader.chatlist import find_badges, usable_rows  # noqa: E402
from line_mac_reader.config import load_config  # noqa: E402
from line_mac_reader.line_controller import LineController  # noqa: E402
from line_mac_reader.permissions import check_permissions  # noqa: E402
from line_mac_reader.screen import Screen  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--sample", default=None, metavar="X,Y",
                    help="Print HSV at this pixel of the chat-list capture")
    args = ap.parse_args()

    import cv2
    import numpy as np

    problems = check_permissions()
    if problems:
        for p in problems:
            print(f"錯誤:{p}\n", file=sys.stderr)
        return 1

    cfg = load_config(args.config)
    window_rect = LineController(cfg).launch_and_focus()
    screen = Screen()

    out_dir = Path(cfg.debug_dir) / f"diagnose_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Full window with regions outlined — verify region coordinates first.
    full = screen.capture(window_rect)
    ppp = screen.image_scale(full, window_rect)
    annotated_full = full.copy()
    for name, region, color in (
        ("chat_list", cfg.regions.chat_list, (0, 0, 255)),
        ("messages", cfg.regions.messages, (255, 0, 0)),
        ("chat_title", cfg.regions.chat_title, (0, 255, 255)),
        ("search_box", cfg.regions.search_box, (255, 0, 255)),
    ):
        p1 = (int(region.x * ppp), int(region.y * ppp))
        p2 = (int((region.x + region.width) * ppp),
              int((region.y + region.height) * ppp))
        cv2.rectangle(annotated_full, p1, p2, color, 2)
        cv2.putText(annotated_full, name, (p1[0] + 4, p1[1] + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.imwrite(str(out_dir / "fullwindow.png"), annotated_full)

    # Chat-list capture + badge mask + detections.
    region = cfg.regions.chat_list.offset(window_rect.x, window_rect.y)
    img = screen.capture(region)
    cv2.imwrite(str(out_dir / "chatlist.png"), img)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    if args.sample:
        x, y = (int(v) for v in args.sample.split(","))
        print(f"HSV at ({x},{y}) = {hsv[y, x].tolist()}   "
              f"(BGR = {img[y, x].tolist()})")

    mask = cv2.inRange(hsv, np.array(cfg.badge.hsv_lower, np.uint8),
                       np.array(cfg.badge.hsv_upper, np.uint8))
    cv2.imwrite(str(out_dir / "mask.png"), mask)

    px_per_pt = screen.image_scale(img, region)
    cut = usable_rows(img.shape[0], cfg.regions.list_bottom_exclude, px_per_pt)
    boxes = find_badges(img[:cut, :], cfg)
    row_h = int(cfg.regions.row_height * px_per_pt)
    annotated = img.copy()
    # Red hatch = AD keep-out strip (regions.list_bottom_exclude): rows and
    # badges below this line are never clicked.
    cv2.rectangle(annotated, (0, cut), (img.shape[1] - 1, img.shape[0] - 1),
                  (0, 0, 255), 3)
    cv2.putText(annotated, "AD keep-out", (8, min(cut + 30, img.shape[0] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    for (x, y, w, h) in boxes:
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cy = y + h // 2
        top = max(0, cy - row_h // 2)
        cv2.rectangle(annotated, (0, top), (img.shape[1] - 1, top + row_h),
                      (255, 0, 0), 1)
        # Crosshair at the exact point main.py would click for this row —
        # if this cross is not on the right person, calibrate regions.
        cx = img.shape[1] // 2
        cv2.drawMarker(annotated, (cx, cy), (0, 255, 255),
                       cv2.MARKER_CROSS, 40, 3)
    cv2.imwrite(str(out_dir / "annotated.png"), annotated)

    print(f"偵測到 {len(boxes)} 個未讀 badge。")
    for b in boxes:
        print(f"  bbox={b}")
    print(f"診斷圖已輸出到 {out_dir}/")
    print("校正流程:先看 fullwindow.png 確認區域框,再看 mask.png / "
          "annotated.png 調整 badge.hsv_lower/hsv_upper 與面積門檻。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
