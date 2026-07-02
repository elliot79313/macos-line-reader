"""Retina coordinate conversion — SOW M1 requires these tested."""

from line_mac_reader.models import Rect
from line_mac_reader.screen import Scaler


def test_retina_point_roundtrip():
    s = Scaler(scale=2.0)
    assert s.to_physical_point(100, 50) == (200, 100)
    assert s.to_logical_point(200, 100) == (100, 50)


def test_non_retina_identity():
    s = Scaler(scale=1.0)
    assert s.to_physical_point(123, 456) == (123, 456)
    assert s.to_logical_rect(Rect(1, 2, 3, 4)) == Rect(1, 2, 3, 4)


def test_rect_conversion():
    s = Scaler(scale=2.0)
    phys = s.to_physical_rect(Rect(10, 20, 30, 40))
    assert (phys.x, phys.y, phys.width, phys.height) == (20, 40, 60, 80)
    back = s.to_logical_rect(phys)
    assert (back.x, back.y, back.width, back.height) == (10, 20, 30, 40)


def test_fractional_scale_rounds():
    s = Scaler(scale=1.5)
    # round() uses banker's rounding: 4.5 -> 4
    assert s.to_physical_point(3, 3) == (4, 4)
    assert s.to_physical_point(2, 2) == (3, 3)


def test_rect_center_and_offset():
    r = Rect(10, 20, 100, 50)
    assert r.center == (60, 45)
    moved = r.offset(5, -5)
    assert (moved.x, moved.y) == (15, 15)
