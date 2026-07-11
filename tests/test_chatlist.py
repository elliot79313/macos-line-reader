from line_mac_reader.chatlist import names_match, usable_rows


def test_exact_match():
    assert names_match("王小明", "王小明")


def test_truncated_ocr_name_matches():
    assert names_match("王小明的旅遊團", "王小明的旅遊")
    assert names_match("王小明", "王小明 的旅遊團")  # whitespace-insensitive


def test_case_insensitive():
    assert names_match("Alex Kuo", "alex kuo")


def test_no_match():
    assert not names_match("王小明", "陳大文")


def test_empty_never_matches():
    assert not names_match("", "王小明")
    assert not names_match("王小明", "")


def test_usable_rows_trims_ad_strip():
    # 1380px-tall capture at 2x with a 110pt keep-out => cut at 1160
    assert usable_rows(1380, 110, 2.0) == 1160


def test_usable_rows_zero_exclude_keeps_all():
    assert usable_rows(1380, 0, 2.0) == 1380


def test_usable_rows_never_negative():
    assert usable_rows(100, 110, 2.0) == 0
