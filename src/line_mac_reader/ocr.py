"""OCR facade: image in -> [(text, bbox, confidence), ...] out.

Engine: Tesseract via pytesseract (langs chi_tra+jpn+eng). Preprocessing and
psm/lang live in OcrConfig so the engine can be swapped without touching
callers. Chat bubbles must be cropped to single blocks BEFORE calling ocr()
— feeding a whole screen produces cross-bubble garbage for chi_tra.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import OcrConfig


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]  # x, y, w, h in the INPUT image's pixels
    confidence: float  # 0.0 - 1.0


def preprocess(img, cfg: OcrConfig):
    """Upscale + grayscale + (optional) Otsu binarization.

    Tesseract's chi_tra accuracy on small anti-aliased chat text is poor
    without this. Returns a single-channel image and the scale factor applied
    (so bboxes can be mapped back).
    """
    import cv2

    scale = float(cfg.upscale)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if cfg.invert_dark_background and gray.mean() < 110:
        gray = 255 - gray
    if cfg.binarize:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray, scale


def ocr(img, cfg: OcrConfig) -> list[OcrLine]:
    """Run OCR on an image (BGR or grayscale numpy array).

    Returns one OcrLine per text line, with bboxes in the ORIGINAL image's
    pixel coordinates and confidence normalized to 0-1.
    """
    import pytesseract

    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd

    prepared, scale = preprocess(img, cfg)
    data = pytesseract.image_to_data(
        prepared,
        lang=cfg.lang,
        config=f"--psm {cfg.psm}",
        output_type=pytesseract.Output.DICT,
    )
    return group_words_into_lines(data, scale)


def group_words_into_lines(data: dict, scale: float) -> list[OcrLine]:
    """Group pytesseract word output into lines, averaging confidence.

    Pure function (no tesseract dependency) so it is unit-testable.
    """
    lines: dict[tuple[int, int, int], list[int]] = {}
    n = len(data["text"])
    for i in range(n):
        word = (data["text"][i] or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    out: list[OcrLine] = []
    for key in sorted(lines):
        idxs = lines[key]
        words = [data["text"][i].strip() for i in idxs]
        confs = [float(data["conf"][i]) for i in idxs]
        xs = [data["left"][i] for i in idxs]
        ys = [data["top"][i] for i in idxs]
        x2s = [data["left"][i] + data["width"][i] for i in idxs]
        y2s = [data["top"][i] + data["height"][i] for i in idxs]
        bbox = (
            round(min(xs) / scale),
            round(min(ys) / scale),
            round((max(x2s) - min(xs)) / scale),
            round((max(y2s) - min(ys)) / scale),
        )
        out.append(OcrLine(
            text=" ".join(words),
            bbox=bbox,
            confidence=(sum(confs) / len(confs)) / 100.0,
        ))
    out.sort(key=lambda l: l.bbox[1])
    return out


def check_tesseract(cfg: OcrConfig) -> str | None:
    """Return an error message if tesseract or required languages are missing."""
    import pytesseract

    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return ("tesseract not found. Install with `brew install tesseract "
                "tesseract-lang`, or set ocr.tesseract_cmd in config.")
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return None  # can't enumerate languages; let OCR itself fail loudly
    needed = set(cfg.lang.split("+"))
    missing = needed - available
    if missing:
        return (f"tesseract language data missing: {', '.join(sorted(missing))}. "
                "Install with `brew install tesseract-lang`.")
    return None
