"""CLI entry point and run orchestration."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, load_config
from .models import ChatResult, UnreadChat

log = logging.getLogger("line_mac_reader")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="line-mac-reader",
        description="Read unread LINE messages on macOS via UI automation + OCR.",
    )
    p.add_argument("--config", default=None,
                   help="Path to config.yaml (default: built-in defaults)")
    p.add_argument("--fallback-hours", type=int, default=None,
                   help="Rolling window for chats without a last-read record "
                        "(default from config: 48)")
    p.add_argument("--only", default=None,
                   help="Only process chats whose name contains this substring")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--chat", action="append", metavar="NAME",
                       help="Open this chat via LINE's search box and read it, "
                            "unread or not. Repeatable: --chat A --chat B")
    scope.add_argument("--all", action="store_true", dest="all_chats",
                       help="Read every chat row currently visible in the "
                            "list, not just unread ones")
    p.add_argument("--dry-run", action="store_true",
                   help="Read but do not update last-read state")
    p.add_argument("--reset", action="store_true",
                   help="Clear all last-read state and exit")
    p.add_argument("--out", default=None,
                   help="Output directory (default from config: output/)")
    p.add_argument("--debug", action="store_true",
                   help="Save step-by-step screenshots and raw OCR to debug/")
    return p


def make_debug_saver(cfg: Config, run_stamp: str, enabled: bool):
    if not enabled:
        return None
    debug_dir = Path(cfg.debug_dir) / run_stamp

    def save(name: str, img) -> None:
        import cv2

        debug_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80]
        cv2.imwrite(str(debug_dir / f"{safe}.png"), img)

    return save


def process_chat(chat: UnreadChat, cfg: Config, screen, window_rect,
                 state, now: datetime, fallback_hours: int,
                 debug_save, chat_list) -> ChatResult:
    import pyautogui

    from .reader import ChatReader

    last_read = state.get_last_read(chat.chat_key)
    if last_read is not None:
        read_from, source = last_read, "last_read"
    else:
        read_from, source = now - timedelta(hours=fallback_hours), "fallback_48h"

    result = ChatResult(
        chat_name=chat.chat_name,
        chat_type="unknown",  # direct vs group is not reliably detectable yet
        read_from=read_from,
        read_from_source=source,
        read_to=now,
    )
    if chat.click_point is not None:
        pyautogui.click(*chat.click_point)
        time.sleep(cfg.timing.chat_open_wait)
    elif not chat_list.open_chat_by_search(chat.chat_name):
        raise RuntimeError(
            f"搜尋開啟對話失敗（開啟的標題與「{chat.chat_name}」不符）")

    reader = ChatReader(cfg, screen, window_rect, debug_save=debug_save)
    result.messages = reader.read_chat(chat.chat_name, cutoff=read_from)
    return result


def to_json(run_at: datetime, results: list[ChatResult]) -> dict:
    return {
        "run_at": run_at.isoformat(timespec="seconds"),
        "chats": [
            {
                "chat_name": r.chat_name,
                "chat_type": r.chat_type,
                "read_from": r.read_from.isoformat(timespec="seconds"),
                "read_from_source": r.read_from_source,
                "read_to": r.read_to.isoformat(timespec="seconds"),
                "error": r.error,
                "messages": [
                    {
                        "sender": m.sender,
                        "timestamp_est": (
                            m.timestamp_est.isoformat(timespec="seconds")
                            if m.timestamp_est else None
                        ),
                        "timestamp_confidence": m.timestamp_confidence,
                        "text": m.text,
                        "kind": m.kind,
                        "ocr_confidence": m.ocr_confidence,
                    }
                    for m in r.messages
                ],
            }
            for r in results
        ],
    }


def print_summary(results: list[ChatResult], low_conf_threshold: float) -> None:
    print("\n===== 未讀訊息摘要 =====")
    if not results:
        print("沒有偵測到未讀對話。")
        return
    for r in results:
        header = (f"\n【{r.chat_name}】 "
                  f"{r.read_from:%Y-%m-%d %H:%M} → {r.read_to:%Y-%m-%d %H:%M} "
                  f"({'上次讀取' if r.read_from_source == 'last_read' else '近48小時'})")
        print(header)
        if r.error:
            print(f"  ⚠ 讀取失敗：{r.error}")
            continue
        print(f"  共 {len(r.messages)} 則訊息")
        for m in r.messages:
            ts = f"{m.timestamp_est:%m-%d %H:%M}" if m.timestamp_est else "??-?? ??:??"
            flags = ""
            if m.timestamp_confidence == "low":
                flags += " [時間推估]"
            if m.ocr_confidence < low_conf_threshold:
                flags += " [OCR低信心]"
            print(f"  {ts} {m.sender}: {m.text}{flags}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    if args.out:
        cfg.output_dir = args.out
    fallback_hours = args.fallback_hours or cfg.fallback_hours

    from .state import StateStore

    state = StateStore(cfg.state_db)
    if args.reset:
        state.reset()
        print("已清空所有對話的 last_read 狀態。")
        return 0

    # --- environment self-checks ------------------------------------------
    from .ocr import check_tesseract
    from .permissions import check_permissions

    problems = check_permissions()
    tess_err = check_tesseract(cfg.ocr)
    if tess_err:
        problems.append(tess_err)
    if problems:
        for p in problems:
            print(f"錯誤：{p}\n", file=sys.stderr)
        return 1

    # --- bring up LINE ------------------------------------------------------
    from .chatlist import ChatList
    from .line_controller import LineController, LineNotFoundError
    from .screen import Screen
    from .utils_time import tzinfo_for

    tz = tzinfo_for(cfg.timezone)
    now = datetime.now(tz)
    run_stamp = now.strftime("%Y%m%d_%H%M%S")
    debug_save = make_debug_saver(cfg, run_stamp, args.debug)

    try:
        window_rect = LineController(cfg).launch_and_focus()
    except LineNotFoundError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    screen = Screen()
    log.info("LINE window at %s, display scale %.1f",
             window_rect, screen.scaler.scale)

    # --- decide which chats to read ------------------------------------------
    chat_list = ChatList(cfg, screen, window_rect)
    if args.chat:
        # Explicit chats, opened via the search box — unread state irrelevant.
        chats = [UnreadChat(chat_name=n, row_index=i, click_point=None)
                 for i, n in enumerate(args.chat)]
    elif args.all_chats:
        chats = chat_list.scan_visible_rows(debug_save=debug_save)
    else:
        chats = chat_list.scan_unread(debug_save=debug_save)
    if args.only and not args.chat:
        chats = [c for c in chats if args.only in c.chat_name]
        log.info("--only %r matched %d chat(s)", args.only, len(chats))

    # --- read each chat (one failure must not abort the run) ----------------
    results: list[ChatResult] = []
    for chat in chats:
        try:
            results.append(process_chat(
                chat, cfg, screen, window_rect, state, now,
                fallback_hours, debug_save, chat_list,
            ))
        except Exception as exc:  # noqa: BLE001 — per-chat fault isolation
            log.exception("Failed reading chat %r", chat.chat_name)
            results.append(ChatResult(
                chat_name=chat.chat_name, chat_type="unknown",
                read_from=now - timedelta(hours=fallback_hours),
                read_from_source="fallback_48h", read_to=now,
                error=str(exc),
            ))

    # --- output & state update ----------------------------------------------
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_stamp}.json"
    out_path.write_text(
        json.dumps(to_json(now, results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not args.dry_run:
        for r in results:
            if r.error is None:
                state.set_last_read(r.chat_name.strip(), now)
    state.close()

    print_summary(results, cfg.ocr.min_confidence)
    print(f"\nJSON 已輸出：{out_path}")
    if args.dry_run:
        print("(dry-run：未更新 last_read 狀態)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
