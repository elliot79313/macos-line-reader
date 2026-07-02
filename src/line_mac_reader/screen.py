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

        phys = self.scaler.to_physical_rect(region)
        with mss.mss() as sct:
            raw = sct.grab({
                # mss accepts logical coords on macOS and returns physical
                # pixels; pass logical and verify the returned size.
                "left": region.x, "top": region.y,
                "width": region.width, "height": region.height,
            })
            img = np.asarray(raw)[:, :, :3]  # BGRA -> BGR
        # Sanity check: if mss returned logical-sized pixels (non-Retina),
        # phys equals region and this still passes.
        if img.shape[1] not in (phys.width, region.width):
            raise RuntimeError(
                f"Unexpected capture width {img.shape[1]} for region "
                f"{region.width} (physical {phys.width}); "
                "check display scaling configuration"
            )
        return img

    def save_debug(self, img, path: str | Path) -> None:
        import cv2

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), img)

    def image_scale(self, img, region: Rect) -> float:
        """Actual pixels-per-point of a captured image (1.0 or 2.0 typically)."""
        return img.shape[1] / region.width
