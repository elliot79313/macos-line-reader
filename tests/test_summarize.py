from datetime import datetime

from line_mac_reader.config import LlmConfig
from line_mac_reader.models import ChatResult, Message
from line_mac_reader.summarize import (
    build_messages,
    chat_to_text,
    iter_stream_content,
    strip_reasoning,
)
from line_mac_reader.utils_time import tzinfo_for

TZ = tzinfo_for("Asia/Taipei")


def _result(name="客戶A", messages=(), error=None):
    return ChatResult(
        chat_name=name, chat_type="unknown",
        read_from=datetime(2026, 7, 11, 8, 30, tzinfo=TZ),
        read_from_source="last_read",
        read_to=datetime(2026, 7, 12, 8, 30, tzinfo=TZ),
        messages=list(messages), error=error,
    )


def _msg(text, sender="客戶A"):
    return Message(sender=sender, text=text,
                   timestamp_est=datetime(2026, 7, 11, 14, 20, tzinfo=TZ),
                   timestamp_confidence="high")


def test_chat_to_text_format():
    r = _result(messages=[_msg("合約下週一前要回簽"), _msg("好的", sender="me")])
    text = chat_to_text(r, max_chars=6000)
    assert text.startswith("### 對話：客戶A")
    assert "[07/11 14:20] 客戶A: 合約下週一前要回簽" in text
    assert "[07/11 14:20] 我: 好的" in text


def test_chat_to_text_truncates_keeping_tail():
    msgs = [_msg(f"訊息{i}" + "字" * 50) for i in range(100)]
    text = chat_to_text(_result(messages=msgs), max_chars=500)
    assert len(text) < 700
    assert "（前段省略）" in text
    assert "訊息99" in text     # newest messages survive
    assert "訊息10字" not in text


def test_build_messages_skips_errors_and_empty():
    results = [
        _result(name="客戶A", messages=[_msg("報價請確認")]),
        _result(name="壞掉", messages=[_msg("x")], error="標題不符"),
        _result(name="空的", messages=[]),
    ]
    messages = build_messages(results, LlmConfig())
    assert messages[0]["role"] == "system"
    assert "客戶A" in messages[1]["content"]
    assert "壞掉" not in messages[1]["content"]
    assert "空的" not in messages[1]["content"]


def test_no_think_appended_by_default():
    messages = build_messages([_result(messages=[_msg("hi")])], LlmConfig())
    assert messages[0]["content"].rstrip().endswith("/no_think")


def test_think_enabled_omits_directive():
    messages = build_messages([_result(messages=[_msg("hi")])],
                              LlmConfig(think=True))
    assert "/no_think" not in messages[0]["content"]


def test_strip_reasoning_removes_think_block():
    raw = "<think>讓我想想這些訊息…</think>1. *今日待辦*：回簽合約"
    assert strip_reasoning(raw) == "1. *今日待辦*：回簽合約"
    assert strip_reasoning("沒有思考塊") == "沒有思考塊"


def test_iter_stream_content_assembles_deltas():
    lines = [
        'data: {"choices":[{"delta":{"content":"今日"}}]}',
        'data: {"choices":[{"delta":{"content":"待辦"}}]}',
        "",  # SSE blank separator lines are ignored
        'data: {"choices":[{"delta":{"content":"：回簽"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"不該出現"}}]}',
    ]
    assert "".join(iter_stream_content(lines)) == "今日待辦：回簽"


def test_iter_stream_content_skips_malformed_lines():
    lines = ["garbage", 'data: {bad json', 'data: {"choices":[{"delta":{}}]}',
             'data: {"choices":[{"delta":{"content":"OK"}}]}']
    assert "".join(iter_stream_content(lines)) == "OK"
