"""OCR facade: image in -> [(text, bbox, confidence), ...] out.

Two engines behind one interface:
- "vision" (default): Apple's Vision framework (VNRecognizeTextRequest).
  Far more accurate on Traditional Chinese chat text than Tesseract, fast,
  on-device, and needs no preprocessing — it returns per-line text with
  bounding boxes, so the reader can parse layout from a single whole-screen
  pass.
- "tesseract": kept as a fallback. Needs upscale/Otsu preprocessing and
  works best on small cropped blocks.

Engine choice and all parameters live in OcrConfig; callers never know which
engine ran.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import OcrConfig


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]  # x, y, w, h in the INPUT image's pixels
    confidence: float  # 0.0 - 1.0


def ocr(img, cfg: OcrConfig) -> list[OcrLine]:
    """Run OCR on an image (BGR or grayscale numpy array).

    Returns one OcrLine per text line, bboxes in the input image's pixels,
    confidence normalized to 0-1, sorted top-to-bottom.
    """
    if cfg.engine == "vision":
        return _ocr_vision(img, cfg)
    return _ocr_tesseract(img, cfg)


def check_engine(cfg: OcrConfig) -> str | None:
    """Return an error message if the configured OCR engine is unusable."""
    if cfg.engine == "vision":
        try:
            import Vision  # noqa: F401
        except ImportError:
            return ("ocr.engine=vision 需要 pyobjc-framework-Vision："
                    "pip install pyobjc-framework-Vision，"
                    "或在 config 將 ocr.engine 改為 tesseract。")
        return None
    if cfg.engine == "tesseract":
        return check_tesseract(cfg)
    return f"未知的 ocr.engine: {cfg.engine!r}（可用：vision | tesseract）"


# ---------------------------------------------------------------------------
# Apple Vision engine
# ---------------------------------------------------------------------------

def _ocr_vision(img, cfg: OcrConfig) -> list[OcrLine]:
    import cv2
    import Vision
    from Foundation import NSData

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("could not encode image for Vision OCR")
    data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    request.setRecognitionLanguages_(list(cfg.vision_languages))

    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise RuntimeError(f"Vision OCR failed: {error}")

    h, w = img.shape[:2]
    lines: list[OcrLine] = []
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        cand = candidates[0]
        text = str(cand.string()).strip()
        if not text:
            continue
        bb = obs.boundingBox()  # normalized, origin at BOTTOM-left
        x = bb.origin.x * w
        y = (1.0 - bb.origin.y - bb.size.height) * h
        lines.append(OcrLine(
            text=text,
            bbox=(round(x), round(y),
                  round(bb.size.width * w), round(bb.size.height * h)),
            confidence=float(cand.confidence()),
        ))
    lines.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    return lines


# ---------------------------------------------------------------------------
# Tesseract engine (fallback)
# ---------------------------------------------------------------------------

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


def _ocr_tesseract(img, cfg: OcrConfig) -> list[OcrLine]:
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
