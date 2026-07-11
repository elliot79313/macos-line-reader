from line_mac_reader.ocr import OcrLine, merge_retry, retry_crop_box


def test_crop_box_padded_and_clamped():
    # line at (10, 20, 200, 40) in a 500x300 image; margin = 40*0.35+4 = 18
    assert retry_crop_box((10, 20, 200, 40), 500, 300) == (0, 2, 228, 78)


def test_crop_box_clamps_to_image_edges():
    x1, y1, x2, y2 = retry_crop_box((480, 280, 100, 40), 500, 300)
    assert (x2, y2) == (500, 300)
    assert x1 >= 0 and y1 >= 0


def test_merge_retry_adopts_better_result():
    orig = OcrLine("腎中凰", (0, 0, 100, 20), 0.55)
    retried = [OcrLine("腎中風", (0, 0, 200, 40), 0.92)]
    merged = merge_retry(orig, retried)
    assert merged.text == "腎中風"
    assert merged.confidence == 0.92
    assert merged.bbox == (0, 0, 100, 20)  # keeps full-image coordinates


def test_merge_retry_keeps_original_when_not_better():
    orig = OcrLine("好的", (0, 0, 100, 20), 0.75)
    retried = [OcrLine("好白勺", (0, 0, 200, 40), 0.60)]
    assert merge_retry(orig, retried) is orig


def test_merge_retry_keeps_original_when_retry_empty():
    orig = OcrLine("好的", (0, 0, 100, 20), 0.4)
    assert merge_retry(orig, []) is orig
    assert merge_retry(orig, [OcrLine("  ", (0, 0, 1, 1), 0.99)]) is orig


def test_merge_retry_joins_multiple_lines():
    orig = OcrLine("x", (0, 0, 100, 20), 0.3)
    retried = [OcrLine("週五一直都是", (0, 0, 100, 20), 0.9),
               OcrLine("團隊例會比較多", (0, 22, 100, 20), 0.9)]
    merged = merge_retry(orig, retried)
    assert merged.text == "週五一直都是 團隊例會比較多"
