"""Layout-parser tests. Coordinates mimic real LINE desktop dark-mode
captures (2000px-wide messages region, px_per_pt=2)."""

from datetime import date, datetime

from line_mac_reader.config import LayoutConfig
from line_mac_reader.ocr import OcrLine
from line_mac_reader.reader import (
    ParsedItem,
    items_reach_cutoff,
    merge_transcripts,
    parse_layout,
)
from line_mac_reader.utils_time import tzinfo_for

TODAY = date(2026, 7, 11)
TZ = tzinfo_for("Asia/Taipei")
WIDTH = 2000
CFG = LayoutConfig()


def L(text, x, y, w=300, h=34, conf=0.95):
    return OcrLine(text=text, bbox=(x, y, w, h), confidence=conf)


def parse(lines):
    return parse_layout(lines, WIDTH, "何美雲-媽媽", TODAY, CFG, px_per_pt=2.0)


def test_screenshot_like_transcript():
    """Reproduces the structure of a real capture: outgoing bubble with
    已讀+time labels, a multi-line incoming bubble with standalone time."""
    items = parse([
        L("已讀", 1815, 205, w=60),
        L("上午 8:47", 1760, 240, w=110),
        L("早安", 1880, 210, w=80),
        L("早安", 130, 320, w=80),
        L("若是明天下班前", 130, 360),
        L("颱風還沒很大", 130, 400),
        L("你要不要考慮先回家", 130, 440),
        L("免得星期六", 130, 500),
        L("你沒有飯可以吃", 130, 540),
        L("上午 8:57", 380, 545, w=110),
        L("明天停止上班上課喔", 130, 640),
        L("下午 8:40", 380, 645, w=110),
    ])
    msgs = [i for i in items if i.kind == "message"]
    assert [m.sender for m in msgs] == ["me", "何美雲-媽媽", "何美雲-媽媽"]
    assert msgs[0].text == "早安"
    assert msgs[0].time_of_day == (8, 47)
    assert msgs[1].text.splitlines()[0] == "早安"
    assert "你沒有飯可以吃" in msgs[1].text
    assert msgs[1].time_of_day == (8, 57)
    assert msgs[2].text == "明天停止上班上課喔"
    assert msgs[2].time_of_day == (20, 40)


def test_read_receipt_dropped_even_when_merged_with_time():
    items = parse([
        L("已讀 上午 9:11", 1700, 100, w=180),
        L("目前在一般病房", 1780, 105, w=220),
    ])
    assert len(items) == 1
    assert items[0].text == "目前在一般病房"
    assert items[0].sender == "me"
    assert items[0].time_of_day == (9, 11)


def test_centered_relative_date_is_separator():
    items = parse([
        L("昨天", 965, 330, w=70),
        L("早安", 1880, 400, w=80),
        L("上午 8:29", 1760, 405, w=110),
    ])
    assert items[0].kind == "separator"
    assert items[0].text == "昨天"
    assert items[1].kind == "message"


def test_left_aligned_text_containing_date_word_is_not_separator():
    items = parse([L("Alex 郭毅驊剛好昨天腎中風住院", 1580, 100, w=380)])
    assert len(items) == 1
    assert items[0].kind == "message"


def test_bubble_split_on_side_change():
    items = parse([
        L("嗯", 1920, 100, w=40),
        L("喔", 130, 140, w=40),
    ])
    assert [i.sender for i in items] == ["me", "何美雲-媽媽"]


def test_bubble_split_on_large_gap():
    items = parse([
        L("第一句", 130, 100),
        L("第二句", 130, 138),   # gap 4px <= 36 → same bubble
        L("另一則訊息", 130, 300),  # big gap → new bubble
    ])
    assert len(items) == 2
    assert items[0].text == "第一句\n第二句"


def test_group_sender_by_smaller_font():
    items = parse([
        L("陳大文", 130, 100, w=90, h=24),   # smaller label above the bubble
        L("大家明天見", 130, 130, h=34),
    ])
    assert len(items) == 1
    assert items[0].sender == "陳大文"
    assert items[0].text == "大家明天見"


def test_direct_chat_short_first_line_not_eaten_as_sender():
    # Same font height => 「早安」 stays part of the message.
    items = parse([
        L("早安", 130, 100, w=80, h=34),
        L("颱風要來了", 130, 140, h=34),
    ])
    assert items[0].sender == "何美雲-媽媽"
    assert items[0].text.startswith("早安")


def test_trailing_time_inside_text_line():
    items = parse([L("好的沒問題 14:05", 130, 100, w=340)])
    assert items[0].text == "好的沒問題"
    assert items[0].time_of_day == (14, 5)


def test_sticker_marker():
    items = parse([L("貼圖", 130, 100, w=70)])
    assert items[0].text == "[貼圖]"


# --- cutoff detection ---------------------------------------------------------

def _sep(text, y=0):
    return ParsedItem(kind="separator", text=text, y=y)


def _msg(text, tod=None, y=0, sender="a"):
    return ParsedItem(kind="message", text=text, sender=sender,
                      time_of_day=tod, y=y)


def test_cutoff_by_old_separator():
    cutoff = datetime(2026, 7, 11, 12, 0, tzinfo=TZ)
    # 「昨天」 => 7/10 <= cutoff date → everything above is even older
    assert items_reach_cutoff([_sep("昨天"), _msg("x", (9, 5))], cutoff, TZ, TODAY)


def test_cutoff_by_resolved_message_time():
    cutoff = datetime(2026, 7, 11, 12, 0, tzinfo=TZ)
    items = [_sep("2026年7月12日"), _msg("morning", (9, 0))]
    # separator date is after cutoff date, but 7/12 09:00 > cutoff → not reached
    assert not items_reach_cutoff(items, cutoff, TZ, TODAY)
    items2 = [_sep("今天"), _msg("morning", (9, 0))]  # 7/11 09:00 <= cutoff
    assert items_reach_cutoff(items2, cutoff, TZ, TODAY)


def test_cutoff_not_reached_without_dates():
    cutoff = datetime(2026, 7, 11, 12, 0, tzinfo=TZ)
    assert not items_reach_cutoff([_msg("x", (9, 0))], cutoff, TZ, TODAY)


# --- overlap merging -----------------------------------------------------------

def test_merge_transcripts_overlap():
    lower = [_msg("m3"), _msg("m4"), _msg("m5")]
    upper = [_msg("m1"), _msg("m2"), _msg("m3"), _msg("m4")]
    merged = merge_transcripts(upper, lower)
    assert [i.text for i in merged] == ["m1", "m2", "m3", "m4", "m5"]


def test_merge_transcripts_no_overlap():
    merged = merge_transcripts([_msg("a")], [_msg("b")])
    assert [i.text for i in merged] == ["a", "b"]


def test_merge_transcripts_full_overlap():
    items = [_msg("x"), _msg("y")]
    merged = merge_transcripts(items, list(items))
    assert [i.text for i in merged] == ["x", "y"]


def test_merge_respects_sender_in_key():
    lower = [_msg("hi", sender="a")]
    upper = [_msg("hi", sender="b")]
    merged = merge_transcripts(upper, lower)
    assert len(merged) == 2  # same text, different sender: not a duplicate
