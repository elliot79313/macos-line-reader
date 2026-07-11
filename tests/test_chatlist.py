from line_mac_reader.chatlist import names_match


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
