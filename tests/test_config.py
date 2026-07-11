import pytest

from line_mac_reader.config import Config, load_config
from line_mac_reader.models import Rect


def test_defaults():
    cfg = load_config(None)
    assert cfg.timezone == "Asia/Taipei"
    assert cfg.fallback_hours == 48
    assert cfg.ocr.lang == "chi_tra+jpn+eng"
    assert isinstance(cfg.regions.chat_list, Rect)
    assert isinstance(cfg.regions.search_box, Rect)
    assert cfg.timing.search_wait == 1.0
    assert cfg.scroll.max_list_pages == 8


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_partial_override(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "fallback_hours: 24\n"
        "badge:\n"
        "  hsv_lower: [0, 100, 100]\n"
        "ocr:\n"
        "  psm: 7\n"
        "regions:\n"
        "  chat_list: {x: 1, y: 2, width: 3, height: 4}\n"
        "  row_height: 70\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.fallback_hours == 24
    assert cfg.badge.hsv_lower == (0, 100, 100)
    assert cfg.badge.hsv_upper == (85, 255, 255)  # untouched default
    assert cfg.ocr.psm == 7
    assert cfg.ocr.lang == "chi_tra+jpn+eng"  # untouched default
    assert cfg.regions.chat_list == Rect(1, 2, 3, 4)
    assert cfg.regions.row_height == 70


def test_example_config_loads_and_matches_defaults():
    """config.example.yaml must stay parseable and aligned with code defaults."""
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    cfg = load_config(example)
    default = Config()
    assert cfg.timezone == default.timezone
    assert cfg.fallback_hours == default.fallback_hours
    assert cfg.badge.hsv_lower == default.badge.hsv_lower
    assert cfg.ocr.psm == default.ocr.psm
