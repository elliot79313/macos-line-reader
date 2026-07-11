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


def test_crop_padded_width_removes_mss_padding():
    """mss pads macOS captures to a 16px-multiple width; those columns are
    real screen content RIGHT of the region and must be trimmed, otherwise
    width-based scale maps clicks too high."""
    import numpy as np

    from line_mac_reader.screen import crop_padded_width

    region = Rect(0, 0, 280, 690)  # 2x => 560x1380, mss pads width to 576
    img = np.zeros((1380, 576, 3), dtype=np.uint8)
    cropped = crop_padded_width(img, region)
    assert cropped.shape[1] == 560
    assert cropped.shape[0] == 1380


def test_crop_padded_width_noop_when_exact():
    import numpy as np

    from line_mac_reader.screen import crop_padded_width

    region = Rect(0, 0, 280, 690)
    img = np.zeros((1380, 560, 3), dtype=np.uint8)
    assert crop_padded_width(img, region).shape == (1380, 560, 3)


def test_image_scale_uses_height_not_padded_width():
    """Regression: with a padded 576px-wide capture of a 280pt region, the
    old width-based scale was 576/280=2.057 and every y->logical conversion
    landed too high. Height-based scale stays exactly 2.0."""
    import numpy as np

    from line_mac_reader.screen import Screen

    region = Rect(0, 0, 280, 690)
    img = np.zeros((1380, 576, 3), dtype=np.uint8)  # NOT cropped on purpose
    screen = Screen(scaler=Scaler(scale=2.0))
    assert screen.image_scale(img, region) == 2.0
    # badge at physical y=1100 must map back to logical 550, not 535
    assert round(1100 / screen.image_scale(img, region)) == 550
