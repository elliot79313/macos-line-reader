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
    """Screen regions, relative to the window's top-left, in logical pixels."""

    chat_list: Rect = field(default_factory=lambda: Rect(70, 90, 280, 690))
    messages: Rect = field(default_factory=lambda: Rect(360, 90, 730, 620))
    chat_title: Rect = field(default_factory=lambda: Rect(360, 30, 500, 50))
    search_box: Rect = field(default_factory=lambda: Rect(80, 52, 250, 30))
    row_height: int = 68  # approximate chat-list row height


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


@dataclass
class OcrConfig:
    lang: str = "chi_tra+jpn+eng"
    psm: int = 6
    upscale: float = 2.5
    binarize: bool = True
    invert_dark_background: bool = True
    min_confidence: float = 0.5  # below this, messages are flagged for review
    tesseract_cmd: str | None = None  # override tesseract binary path


@dataclass
class TimingConfig:
    app_launch_wait: float = 3.0
    chat_open_wait: float = 1.2
    scroll_wait: float = 0.7
    click_wait: float = 0.4
    search_wait: float = 1.0  # after typing into the search box


@dataclass
class ScrollConfig:
    step: int = 12           # pyautogui scroll units per scroll-up
    max_scrolls: int = 60    # hard stop per chat, safety net
    stall_limit: int = 3     # consecutive identical screens => top of chat


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
    timing: TimingConfig = field(default_factory=TimingConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)


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
    if "badge" in data:
        b = data["badge"]
        for name in ("hsv_lower", "hsv_upper"):
            if name in b:
                setattr(cfg.badge, name, tuple(int(x) for x in b[name]))
        for name in ("min_area", "max_area", "min_aspect", "max_aspect"):
            if name in b:
                setattr(cfg.badge, name, b[name])
    for section, obj in (("ocr", cfg.ocr), ("timing", cfg.timing), ("scroll", cfg.scroll)):
        if section in data:
            for k, v in data[section].items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
    return cfg
