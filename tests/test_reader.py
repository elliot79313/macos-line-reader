from datetime import date

import numpy as np

from line_mac_reader.ocr import OcrLine
from line_mac_reader.reader import (
    ParsedItem,
    block_side,
    merge_transcripts,
    parse_block,
    row_activity,
    segment_bands,
)

TODAY = date(2026, 7, 2)


def _line(text, x=10, y=0, conf=0.9):
    return OcrLine(text=text, bbox=(x, y, 100, 20), confidence=conf)


# --- segmentation -----------------------------------------------------------

def test_segment_bands_splits_on_gaps():
    active = [False] * 5 + [True] * 20 + [False] * 20 + [True] * 15 + [False] * 5
    bands = segment_bands(active, min_gap=8, min_height=10)
    assert bands == [(5, 25), (45, 60)]


def test_segment_bands_merges_small_gaps():
    # a 3-row gap inside one bubble must not split it
    active = [True] * 12 + [False] * 3 + [True] * 12
    bands = segment_bands(active, min_gap=8, min_height=10)
    assert bands == [(0, 27)]


def test_segment_bands_drops_noise():
    active = [False] * 10 + [True] * 3 + [False] * 20
    assert segment_bands(active, min_gap=8, min_height=10) == []


def test_row_activity_flags_content_rows():
    img = np.full((20, 50), 240, dtype=np.uint8)  # light background
    img[5:10, 10:40] = 20  # dark "text"
    active = row_activity(img)
    assert active[7]
    assert not active[15]


def test_block_side():
    img = np.full((20, 100), 240, dtype=np.uint8)
    img[:, 70:95] = 20
    assert block_side(img) == "right"
    img2 = np.full((20, 100), 240, dtype=np.uint8)
    img2[:, 5:30] = 20
    assert block_side(img2) == "left"


# --- block parsing ------------------------------------------------------------

def test_parse_block_separator():
    item = parse_block([_line("2026年7月1日")], "left", "王小明", TODAY, 0)
    assert item.kind == "separator"


def test_parse_block_message_with_inline_time():
    item = parse_block([_line("明天的會議改到下午三點 14:05")],
                       "left", "王小明", TODAY, 0)
    assert item.kind == "message"
    assert item.text == "明天的會議改到下午三點"
    assert item.time_of_day == (14, 5)
    assert item.sender == "王小明"


def test_parse_block_standalone_time_line():
    item = parse_block([_line("好的沒問題"), _line("上午10:05", y=25)],
                       "right", "王小明", TODAY, 0)
    assert item.text == "好的沒問題"
    assert item.time_of_day == (10, 5)
    assert item.sender == "me"


def test_parse_block_group_sender_heuristic():
    item = parse_block(
        [_line("陳大文"), _line("大家明天見", y=25), _line("下午3:00", y=50)],
        "left", "同學會群組", TODAY, 0)
    assert item.sender == "陳大文"
    assert item.text == "大家明天見"
    assert item.time_of_day == (15, 0)


def test_parse_block_empty_returns_none():
    assert parse_block([], "left", "x", TODAY, 0) is None
    assert parse_block([_line("   ")], "left", "x", TODAY, 0) is None


def test_parse_block_sticker_marker():
    item = parse_block([_line("貼圖"), _line("10:05", y=25)], "left", "王小明",
                       TODAY, 0)
    assert item.kind == "message"
    assert item.text == "[貼圖]"


# --- overlap merging -----------------------------------------------------------

def _msg(text, sender="a"):
    return ParsedItem(kind="message", text=text, sender=sender)


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
