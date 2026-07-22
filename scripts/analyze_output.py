#!/usr/bin/env python3
"""分析 output JSON：這次抓了哪些對話、哪些建議加入 filters.exclude_chats。

用法：
    python scripts/analyze_output.py                          # 分析 output/ 最新一份
    python scripts/analyze_output.py output/20260712_*.json   # 指定檔案（可多個，合併分析）
    python scripts/analyze_output.py --config config.yaml     # 讀取現有 filter 一併比對

多個檔案會合併統計（同名對話累加），適合把幾天的 run 一起看。
純讀取、不改任何狀態。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from line_mac_reader.analyze import analyze_run, render_report  # noqa: E402
from line_mac_reader.config import load_config  # noqa: E402


def find_latest(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def merge_runs(paths: list[Path]) -> dict:
    """Concatenate chats from several runs; same-name chats merge."""
    by_name: dict[str, dict] = {}
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        for chat in data.get("chats", []):
            name = chat.get("chat_name", "?")
            if name in by_name:
                by_name[name]["messages"].extend(chat.get("messages", []))
                by_name[name]["error"] = by_name[name]["error"] or chat.get("error")
            else:
                by_name[name] = dict(chat)
    return {"chats": list(by_name.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="output JSON 檔（省略 = output/ 最新）")
    ap.add_argument("--config", default=None,
                    help="config.yaml（讀取現有 exclude_chats 一併比對）")
    args = ap.parse_args()

    cfg = load_config(args.config) if args.config else load_config(None)
    existing = tuple(cfg.filters.exclude_chats)

    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        latest = find_latest(Path(cfg.output_dir))
        if latest is None:
            print(f"錯誤：{cfg.output_dir}/ 裡沒有 JSON 檔", file=sys.stderr)
            return 1
        paths = [latest]

    for p in paths:
        if not p.exists():
            print(f"錯誤：找不到 {p}", file=sys.stderr)
            return 1
    print(f"分析 {len(paths)} 份輸出：{', '.join(p.name for p in paths)}")
    if existing:
        print(f"現有 filter：{len(existing)} 條")

    buckets = analyze_run(merge_runs(paths), existing)
    print()
    print(render_report(buckets, existing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
