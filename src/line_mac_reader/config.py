"""Configuration loading.

All tunables (coordinates, color thresholds, waits, OCR parameters) live in a
YAML file so that a LINE UI update only requires re-calibrating the config,
never editing code. See config.example.yaml for documentation of every field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Rect


@dataclass
class WindowConfig:
    """Where the LINE main window is pinned (logical/point coordinates)."""

    move_window: bool = True
    x: int = 0
    y: int = 25
    width: int = 1100
    height: int = 800

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)


@dataclass
class RegionsConfig:
    """Screen regions, relative to the window's top-left, in logical pixels.

    Defaults measured against LINE desktop (2026) pinned at 1100x800:
    the sidebar (including its time/badge column) runs to x~420, the tab
    bar occupies y<75, the chat title bar sits at y~75-113, and the
    message transcript starts below it.
    """

    chat_list: Rect = field(default_factory=lambda: Rect(70, 90, 350, 690))
    messages: Rect = field(default_factory=lambda: Rect(425, 115, 660, 570))
    chat_title: Rect = field(default_factory=lambda: Rect(425, 75, 550, 38))
    search_box: Rect = field(default_factory=lambda: Rect(80, 52, 250, 30))
    row_height: int = 68  # approximate chat-list row height
    # LINE shows an AD banner at the BOTTOM of the chat list; never treat
    # that strip as a row (clicking it opens a browser). Logical px.
    list_bottom_exclude: int = 110


@dataclass
class BadgeConfig:
    """HSV mask for the unread-count badge. Calibrate with scripts/diagnose_badges.py.

    Defaults target LINE's green badge (#06C755-ish). OpenCV HSV ranges:
    H 0-179, S 0-255, V 0-255.
    """

    hsv_lower: tuple[int, int, int] = (55, 120, 120)
    hsv_upper: tuple[int, int, int] = (85, 255, 255)
    min_area: int = 40      # physical px^2, reject noise
    max_area: int = 2500    # physical px^2, reject large green UI elements
    min_aspect: float = 0.6  # w/h of badge contour bounding box
    max_aspect: float = 3.0
    # Unread badges sit at the RIGHT edge of a row; green blobs further left
    # are avatar logos (ALLinAI's Q, LINE禮物's gift box) — never badges.
    min_x_ratio: float = 0.6


@dataclass
class OcrConfig:
    engine: str = "vision"  # "vision" (Apple Vision, recommended) | "tesseract"
    vision_languages: tuple[str, ...] = ("zh-Hant", "ja", "en")
    custom_words: tuple[str, ...] = ()  # names/jargon to bias Vision toward
    retry_below: float = 0.8   # re-OCR lines below this confidence (0 = off)
    retry_upscale: float = 2.0  # upscale factor for the per-line retry crop
    min_confidence: float = 0.5  # below this, messages are flagged for review
    # tesseract-only parameters:
    lang: str = "chi_tra+jpn+eng"
    psm: int = 6
    upscale: float = 2.5
    binarize: bool = True
    invert_dark_background: bool = True
    tesseract_cmd: str | None = None  # override tesseract binary path


@dataclass
class LayoutConfig:
    """Thresholds for parsing a whole-screen OCR result into bubbles.

    Values calibrated against LINE desktop dark mode; all ratios are relative
    to the messages-region width, gaps in logical px.
    """

    side_ratio: float = 0.40       # line left-edge < this*width => incoming
    bubble_gap: int = 18           # vertical gap larger than this splits bubbles
    separator_max_chars: int = 14  # date separators are short
    separator_center_band: tuple[float, float] = (0.25, 0.75)


@dataclass
class TimingConfig:
    app_launch_wait: float = 3.0
    chat_open_wait: float = 1.0
    scroll_wait: float = 0.3    # LINE repaint wait between scroll and capture
    click_wait: float = 0.3
    search_wait: float = 1.0    # after typing into the search box
    pyautogui_pause: float = 0.05  # pyautogui's built-in pause per action


@dataclass
class ScrollConfig:
    mode: str = "pixel"       # "pixel": native CGEvent, ~a page per step (fast)
                              # "wheel": pyautogui wheel clicks (slow, fallback)
    page_fraction: float = 0.75  # pixel mode: scroll this much of the region
                                 # height per step; <1 keeps overlap for merging
    step: int = 12            # wheel mode: pyautogui scroll units per step
    max_scrolls: int = 60     # hard stop per chat, safety net
    stall_limit: int = 3      # consecutive identical screens => top of chat
    cutoff_check_every: int = 3  # OCR every Nth screen during capture to test cutoff
    max_list_pages: int = 8   # chat-LIST pages to walk in unread/--all scans


@dataclass
class SlackConfig:
    webhook_url: str | None = None  # Slack Incoming Webhook
    max_messages_per_chat: int = 30  # digest truncates long chats past this


@dataclass
class FiltersConfig:
    """Chats to skip in unread/--all scans (NOT in explicit --chat).

    Substring match, whitespace/case-insensitive — one entry like 「官方」
    covers every official-account name containing it.
    """

    exclude_chats: tuple[str, ...] = ()


@dataclass
class DigestConfig:
    """Morning-digest shaping: messages containing any of these keywords are
    surfaced as action-item candidates at the top of each chat section."""

    action_keywords: tuple[str, ...] = (
        "請", "麻煩", "記得", "需要", "確認", "回覆", "報價",
        "合約", "簽", "截止", "付款", "會議", "約",
    )


@dataclass
class Config:
    timezone: str = "Asia/Taipei"
    fallback_hours: int = 48
    output_dir: str = "output"
    debug_dir: str = "debug"
    state_db: str = "state.sqlite3"
    window: WindowConfig = field(default_factory=WindowConfig)
    regions: RegionsConfig = field(default_factory=RegionsConfig)
    badge: BadgeConfig = field(default_factory=BadgeConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)


def _rect_from(d: dict[str, Any]) -> Rect:
    return Rect(int(d["x"]), int(d["y"]), int(d["width"]), int(d["height"]))


def load_config(path: str | Path | None) -> Config:
    """Load YAML config; missing file or missing keys fall back to defaults."""
    cfg = Config()
    if path is None:
        return cfg
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    for key in ("timezone", "fallback_hours", "output_dir", "debug_dir", "state_db"):
        if key in data:
            setattr(cfg, key, data[key])

    if "window" in data:
        for k, v in data["window"].items():
            setattr(cfg.window, k, v)
    if "regions" in data:
        r = data["regions"]
        for name in ("chat_list", "messages", "chat_title", "search_box"):
            if name in r:
                setattr(cfg.regions, name, _rect_from(r[name]))
        if "row_height" in r:
            cfg.regions.row_height = int(r["row_height"])
        if "list_bottom_exclude" in r:
            cfg.regions.list_bottom_exclude = int(r["list_bottom_exclude"])
    if "badge" in data:
        b = data["badge"]
        for name in ("hsv_lower", "hsv_upper"):
            if name in b:
                setattr(cfg.badge, name, tuple(int(x) for x in b[name]))
        for name in ("min_area", "max_area", "min_aspect", "max_aspect",
                     "min_x_ratio"):
            if name in b:
                setattr(cfg.badge, name, b[name])
    for section, obj in (("ocr", cfg.ocr), ("layout", cfg.layout),
                         ("timing", cfg.timing), ("scroll", cfg.scroll),
                         ("slack", cfg.slack), ("filters", cfg.filters),
                         ("digest", cfg.digest)):
        if section in data:
            for k, v in data[section].items():
                if hasattr(obj, k):
                    setattr(obj, k, tuple(v) if isinstance(v, list) else v)
    return cfg
