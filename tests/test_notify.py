from datetime import datetime

from line_mac_reader.chatlist import is_excluded
from line_mac_reader.models import ChatResult, Message
from line_mac_reader.notify import build_chat_section, build_digest
from line_mac_reader.utils_time import tzinfo_for

TZ = tzinfo_for("Asia/Taipei")
RUN_AT = datetime(2026, 7, 12, 8, 30, tzinfo=TZ)
KEYWORDS = ("請", "合約", "報價")


def _msg(text, sender="客戶A", hh=10, conf="high"):
    return Message(sender=sender, text=text,
                   timestamp_est=datetime(2026, 7, 11, hh, 0, tzinfo=TZ),
                   timestamp_confidence=conf)


def _result(name="客戶A", messages=(), error=None):
    return ChatResult(
        chat_name=name, chat_type="unknown",
        read_from=datetime(2026, 7, 11, 8, 30, tzinfo=TZ),
        read_from_source="last_read", read_to=RUN_AT,
        messages=list(messages), error=error,
    )


def test_section_surfaces_action_items():
    r = _result(messages=[_msg("合約下週一前要回簽"), _msg("好的沒問題")])
    section = build_chat_section(r, KEYWORDS, max_messages=30)
    assert "待辦候選" in section
    assert section.count("合約下週一前要回簽") == 2  # once in actions, once in log
    assert "好的沒問題" in section


def test_section_no_actions_when_no_keyword():
    r = _result(messages=[_msg("好的沒問題")])
    assert "待辦候選" not in build_chat_section(r, KEYWORDS, 30)


def test_section_truncates_long_chats():
    r = _result(messages=[_msg(f"訊息{i}") for i in range(40)])
    section = build_chat_section(r, KEYWORDS, max_messages=30)
    assert "省略較早的 10 則" in section
    assert "訊息39" in section
    assert "訊息5\n" not in section


def test_section_none_for_empty_chat():
    assert build_chat_section(_result(messages=[]), KEYWORDS, 30) is None


def test_section_reports_errors():
    section = build_chat_section(_result(error="標題不符"), KEYWORDS, 30)
    assert "讀取失敗" in section


def test_digest_empty_when_nothing_to_say():
    assert build_digest([_result(messages=[])], RUN_AT, KEYWORDS, 30) == []


def test_digest_single_chunk_with_header():
    chunks = build_digest([_result(messages=[_msg("hi")])], RUN_AT, KEYWORDS, 30)
    assert len(chunks) == 1
    assert chunks[0].startswith("☀️ *LINE 每日摘要* 2026-07-12 08:30")


def test_digest_splits_when_over_limit():
    big = [_result(name=f"客戶{i}",
                   messages=[_msg("字" * 400, hh=9) for _ in range(30)])
           for i in range(5)]
    chunks = build_digest(big, RUN_AT, KEYWORDS, 30)
    assert len(chunks) > 1
    assert all(len(c) <= 35000 + 13000 for c in chunks)  # section-boundary split


def test_low_confidence_time_marked():
    r = _result(messages=[_msg("開會", conf="low")])
    assert "~07/11" in build_chat_section(r, KEYWORDS, 30)


# --- official-account exclusion --------------------------------------------

def test_exclude_substring_case_and_space_insensitive():
    patterns = ("官方", "line pay")
    assert is_excluded("某某銀行官方帳號", patterns)
    assert is_excluded("LINE Pay", patterns)
    assert not is_excluded("王小明", patterns)


def test_exclude_empty_patterns_matches_nothing():
    assert not is_excluded("王小明", ())
    assert not is_excluded("王小明", ("",))
