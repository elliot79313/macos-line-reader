from datetime import date, datetime

from line_mac_reader.utils_time import (
    DateContext,
    parse_date_separator,
    parse_time_of_day,
    tzinfo_for,
)

TODAY = date(2026, 7, 2)
TZ = tzinfo_for("Asia/Taipei")


def test_full_cjk_date():
    assert parse_date_separator("2026年7月1日", TODAY) == date(2026, 7, 1)
    assert parse_date_separator("2026年07月01日（週三）", TODAY) == date(2026, 7, 1)


def test_month_day_only_assumes_recent_year():
    assert parse_date_separator("7月1日", TODAY) == date(2026, 7, 1)
    # A future month/day must roll back to the previous year.
    assert parse_date_separator("12月25日", TODAY) == date(2025, 12, 25)


def test_relative_dates():
    assert parse_date_separator("今天", TODAY) == date(2026, 7, 2)
    assert parse_date_separator("昨天", TODAY) == date(2026, 7, 1)
    assert parse_date_separator("Yesterday", TODAY) == date(2026, 7, 1)


def test_numeric_date():
    assert parse_date_separator("2026/07/01", TODAY) == date(2026, 7, 1)
    assert parse_date_separator("2026-7-1", TODAY) == date(2026, 7, 1)


def test_not_a_date():
    assert parse_date_separator("明天的會議改到下午三點", TODAY) is None
    assert parse_date_separator("", TODAY) is None
    assert parse_date_separator("10:05", TODAY) is None


def test_invalid_date_rejected():
    assert parse_date_separator("2026年13月40日", TODAY) is None


def test_time_24h():
    assert parse_time_of_day("14:05") == (14, 5)
    assert parse_time_of_day("好的 14:05") == (14, 5)


def test_time_cjk_meridiem():
    assert parse_time_of_day("上午10:05") == (10, 5)
    assert parse_time_of_day("下午 3:15") == (15, 15)
    assert parse_time_of_day("上午12:30") == (0, 30)  # 12 AM -> 00
    assert parse_time_of_day("下午12:30") == (12, 30)


def test_time_english_meridiem():
    assert parse_time_of_day("3:15 PM") == (15, 15)


def test_time_invalid():
    assert parse_time_of_day("no time here") is None
    assert parse_time_of_day("25:99") is None


def test_date_context_high_confidence_after_separator():
    ctx = DateContext(TZ, TODAY)
    assert ctx.feed_separator("2026年7月1日")
    ts, conf = ctx.resolve(10, 5)
    assert ts == datetime(2026, 7, 1, 10, 5, tzinfo=TZ)
    assert conf == "high"


def test_date_context_low_confidence_without_separator():
    ctx = DateContext(TZ, TODAY)
    ts, conf = ctx.resolve(10, 5)
    assert conf == "low"
    assert ts.date() == TODAY


def test_date_context_ignores_non_separator():
    ctx = DateContext(TZ, TODAY)
    assert not ctx.feed_separator("這不是日期")
    assert ctx.current is None
