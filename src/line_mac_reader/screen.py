"""Screenshots and Retina coordinate conversion.

Two coordinate systems are in play:
- LOGICAL (point) coordinates: what pyautogui clicks and what macOS reports
  for window positions.
- PHYSICAL (pixel) coordinates: what mss screenshots contain. On Retina
  displays physical = logical * scale (usually 2).

ALL conversion goes through Scaler so it can be unit-tested; nothing else in
the codebase may multiply by a scale factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Rect


@dataclass(frozen=True)
class Scaler:
    """Converts between logical (point) and physical (pixel) coordinates."""

    scale: float  # physical / logical, e.g. 2.0 on Retina

    def to_physical_point(self, x: float, y: float) -> tuple[int, int]:
        return (round(x * self.scale), round(y * self.scale))

    def to_logical_point(self, x: float, y: float) -> tuple[int, int]:
        return (round(x / self.scale), round(y / self.scale))

    def to_physical_rect(self, r: Rect) -> Rect:
        return Rect(
            round(r.x * self.scale),
            round(r.y * self.scale),
            round(r.width * self.scale),
            round(r.height * self.scale),
        )

    def to_logical_rect(self, r: Rect) -> Rect:
        return Rect(
            round(r.x / self.scale),
            round(r.y / self.scale),
            round(r.width / self.scale),
            round(r.height / self.scale),
        )


def detect_scaler() -> Scaler:
    """Compute physical/logical ratio from the primary monitor.

    mss reports physical pixels; pyautogui.size() reports logical points.
    """
    import mss
    import pyautogui

    with mss.mss() as sct:
        mon = sct.monitors[1]  # primary monitor
        physical_w = mon["width"]
    logical_w = pyautogui.size().width
    if logical_w <= 0:
        raise RuntimeError("pyautogui reported a zero-width screen")
    return Scaler(scale=physical_w / logical_w)


class Screen:
    """Capture helper. All public APIs take LOGICAL rects and return numpy
    BGR images in PHYSICAL resolution (best quality for OCR)."""

    def __init__(self, scaler: Scaler | None = None):
        self.scaler = scaler or detect_scaler()

    def capture(self, region: Rect):
        """Capture a logical-coordinate region; returns a BGR numpy array."""
        import mss
        import numpy as np

        with mss.mss() as sct:
            raw = sct.grab({
                # mss accepts logical coords on macOS and returns physical
                # pixels; pass logical here, and let image_scale() derive the
                # actual pixels-per-point from what came back.
                "left": region.x, "top": region.y,
                "width": region.width, "height": region.height,
            })
            img = np.asarray(raw)[:, :, :3]  # BGRA -> BGR
        img = crop_padded_width(img, region)
        actual = img.shape[0] / region.height
        if not 0.5 <= actual <= 4.0:
            raise RuntimeError(
                f"Capture height {img.shape[0]} for a {region.height}pt region "
                f"(scale {actual:.2f}) — check display configuration"
            )
        return img

    def image_scale(self, img, region: Rect) -> float:
        """Actual pixels-per-point of a captured image.

        Derived from HEIGHT: on macOS, mss pads the capture width to a
        multiple of 16 px, so width-based ratios overestimate the scale and
        every y->logical conversion lands too high (worse further down the
        screen). Height is never padded.
        """
        return img.shape[0] / region.height

    def save_debug(self, img, path: str | Path) -> None:
        import cv2

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), img)


def crop_padded_width(img, region: Rect):
    """Trim the columns mss pads onto macOS captures.

    mss rounds the capture width up to a multiple of 16 px, so the image can
    contain extra screen content to the RIGHT of the requested region (e.g.
    message bubbles leaking into a chat-list capture, producing phantom
    badges). The pixels-per-point is taken from the height, which is exact.
    """
    scale = img.shape[0] / region.height
    expected_w = round(region.width * scale)
    if img.shape[1] > expected_w:
        return img[:, :expected_w]
    return img
