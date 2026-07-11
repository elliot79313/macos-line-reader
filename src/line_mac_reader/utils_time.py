"""Timestamp reconstruction.

LINE desktop shows only `HH:MM` (or `上午/下午 h:mm`) next to each message;
the date comes from separator rows such as 「2026年7月1日」,「昨天」,「今天」,
"Yesterday", "Today". While scrolling we keep a "current date context" and
rebuild full timestamps. When the date cannot be determined the message is
tagged timestamp_confidence="low" — cutoff comparison is deliberately lenient
(read too much rather than too little; dedup cleans up the overlap).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# --- date separator patterns -------------------------------------------------

# 2026年7月1日 / 2026年07月01日, optional weekday suffix e.g.（週二）(Tue)
_RE_CJK_FULL = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 7月1日 (no year — assume current year, roll back one year if in the future)
_RE_CJK_MD = re.compile(r"(?<!年)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 2026/07/01 or 2026-07-01
_RE_YMD = re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")
_RELATIVE = {
    "今天": 0, "今日": 0, "today": 0,
    "昨天": 1, "昨日": 1, "yesterday": 1,
    "前天": 2,
}

# --- time-of-day patterns ----------------------------------------------------

# 24h "14:05" or 12h with CJK meridiem 「上午10:05」「下午 3:15」
_RE_HHMM = re.compile(r"(?:(上午|下午|午前|午後|AM|PM|am|pm)\s*)?(\d{1,2}):(\d{2})(?:\s*(AM|PM|am|pm))?")

_PM_MARKERS = {"下午", "午後", "PM", "pm"}
_AM_MARKERS = {"上午", "午前", "AM", "am"}


def tzinfo_for(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def parse_date_separator(text: str, today: date) -> date | None:
    """Parse a date-separator row. Returns None if the text is not one."""
    cleaned = text.strip()
    if not cleaned:
        return None
    m = _RE_CJK_FULL.search(cleaned)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        # A transcript separator can never be in the future — a future date
        # is promo text (「7月29日開跑！」) misread as a separator.
        return d if d <= today else None
    m = _RE_YMD.search(cleaned)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        return d if d <= today else None
    m = _RE_CJK_MD.search(cleaned)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        # a month/day separator can never be in the future
        return d if d <= today else d.replace(year=today.year - 1)
    lowered = cleaned.lower()
    for word, days_ago in _RELATIVE.items():
        if word in lowered or word in cleaned:
            return today - timedelta(days=days_ago)
    return None


def parse_time_of_day(text: str) -> tuple[int, int] | None:
    """Extract (hour, minute) from a message-adjacent time label."""
    m = _RE_HHMM.search(text)
    if not m:
        return None
    meridiem = m.group(1) or m.group(4)
    hour, minute = int(m.group(2)), int(m.group(3))
    if minute > 59:
        return None
    if meridiem in _PM_MARKERS and hour < 12:
        hour += 12
    elif meridiem in _AM_MARKERS and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return hour, minute


def combine(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


class DateContext:
    """Tracks the current date while walking a transcript top-to-bottom.

    Separators apply to all messages *below* them (until the next separator).
    Messages seen before any separator have an unknown date: we estimate with
    `assumed_date` (defaults to today) and report low confidence.
    """

    def __init__(self, tz: ZoneInfo, today: date | None = None):
        self.tz = tz
        self.today = today or datetime.now(tz).date()
        self.current: date | None = None

    def feed_separator(self, text: str) -> bool:
        d = parse_date_separator(text, self.today)
        if d is not None:
            self.current = d
            return True
        return False

    def resolve(self, hour: int, minute: int, assumed_date: date | None = None
                ) -> tuple[datetime, str]:
        """Return (timestamp, confidence) for an HH:MM within current context."""
        if self.current is not None:
            return combine(self.current, hour, minute, self.tz), "high"
        day = assumed_date or self.today
        return combine(day, hour, minute, self.tz), "low"
