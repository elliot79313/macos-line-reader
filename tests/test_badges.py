"""Badge detection on synthetic chat-list images (requires cv2)."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from line_mac_reader.chatlist import find_badges  # noqa: E402
from line_mac_reader.config import Config  # noqa: E402

LINE_GREEN = (85, 199, 6)  # BGR of #06C755


def _list_image(width=560, height=800):
    """Dark-mode chat list background."""
    img = np.full((height, width, 3), 40, dtype=np.uint8)
    return img


def _draw_blob(img, x, y, w, h):
    img[y:y + h, x:x + w] = LINE_GREEN


def test_right_edge_badge_detected():
    img = _list_image()
    _draw_blob(img, x=500, y=300, w=36, h=24)  # unread pill at the right edge
    boxes = find_badges(img, Config())
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert abs(x - 500) <= 2 and abs(y - 300) <= 2


def test_green_avatar_logo_ignored():
    """Green logos on avatars (left column) must not count as badges —
    this exact false positive put crosshairs on rows with no unread."""
    img = _list_image()
    _draw_blob(img, x=60, y=300, w=28, h=28)   # avatar-corner logo (left)
    _draw_blob(img, x=500, y=500, w=36, h=24)  # real badge (right)
    boxes = find_badges(img, Config())
    assert len(boxes) == 1
    assert boxes[0][1] == 500 or abs(boxes[0][1] - 500) <= 2


def test_oversized_green_area_ignored():
    img = _list_image()
    _draw_blob(img, x=460, y=200, w=90, h=90)  # too big (e.g. green sticker)
    assert find_badges(img, Config()) == []