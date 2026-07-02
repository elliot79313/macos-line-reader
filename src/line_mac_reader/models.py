"""Core dataclasses shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Rect:
    """Rectangle in logical (point) coordinates: x/y is the top-left corner."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def offset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.width, self.height)


@dataclass
class UnreadChat:
    """A chat-list row detected as having unread messages."""

    chat_name: str
    row_index: int
    click_point: tuple[int, int]  # logical screen coordinates
    badge_bbox: tuple[int, int, int, int] | None = None  # x, y, w, h (logical)
    name_ocr_confidence: float = 0.0

    @property
    def chat_key(self) -> str:
        """State key. Chat names may collide or be truncated; see README caveats."""
        return self.chat_name.strip()


@dataclass
class Message:
    sender: str
    text: str
    timestamp_est: datetime | None
    timestamp_confidence: str = "low"  # "high" | "low"
    kind: str = "text"  # text | image | sticker | unknown
    ocr_confidence: float = 0.0

    def dedup_key(self) -> tuple[str, str]:
        """Key for merging overlapping screenshots: sender + normalized text."""
        return (self.sender, " ".join(self.text.split()))


@dataclass
class ChatResult:
    chat_name: str
    chat_type: str  # "direct" | "group" | "unknown"
    read_from: datetime
    read_from_source: str  # "last_read" | "fallback_48h"
    read_to: datetime
    messages: list[Message] = field(default_factory=list)
    error: str | None = None
