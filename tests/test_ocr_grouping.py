from line_mac_reader.ocr import group_words_into_lines


def _data(words):
    """words: list of (text, conf, block, par, line, left, top, w, h)"""
    keys = ("text", "conf", "block_num", "par_num", "line_num",
            "left", "top", "width", "height")
    return {k: [w[i] for w in words] for i, k in enumerate(keys)}


def test_groups_words_by_line():
    data = _data([
        ("明天", 95, 1, 1, 1, 10, 5, 40, 20),
        ("開會", 90, 1, 1, 1, 55, 5, 40, 20),
        ("好的", 88, 1, 1, 2, 10, 30, 40, 20),
    ])
    lines = group_words_into_lines(data, scale=1.0)
    assert [l.text for l in lines] == ["明天 開會", "好的"]
    assert abs(lines[0].confidence - 0.925) < 1e-9
    assert lines[0].bbox == (10, 5, 85, 20)


def test_skips_empty_and_negative_conf():
    data = _data([
        ("", 95, 1, 1, 1, 0, 0, 10, 10),
        ("hi", -1, 1, 1, 1, 0, 0, 10, 10),
        ("ok", 80, 1, 1, 2, 0, 20, 10, 10),
    ])
    lines = group_words_into_lines(data, scale=1.0)
    assert [l.text for l in lines] == ["ok"]


def test_bbox_scaled_back_to_original_pixels():
    data = _data([("字", 90, 1, 1, 1, 100, 50, 60, 40)])
    lines = group_words_into_lines(data, scale=2.0)
    assert lines[0].bbox == (50, 25, 30, 20)


def test_lines_sorted_top_to_bottom():
    data = _data([
        ("下面", 90, 2, 1, 1, 10, 100, 40, 20),
        ("上面", 90, 1, 1, 1, 10, 10, 40, 20),
    ])
    lines = group_words_into_lines(data, scale=1.0)
    assert [l.text for l in lines] == ["上面", "下面"]
