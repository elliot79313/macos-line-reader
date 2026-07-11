from line_mac_reader.chatlist import fuzzy_dup, names_match, usable_rows


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


def test_fuzzy_dup_catches_ocr_variants():
    """Real cases from a --all run: the same chat's title OCR'd four ways."""
    seen = {"legacytaiwan里程."}
    assert fuzzy_dup("Legacy Taiwan里程，", seen)
    assert fuzzy_dup("-egacy |aiwan里桯入", seen)
    assert fuzzy_dup("止光診所", {"正光診所"})
    assert fuzzy_dup("2026 台復新創會晚！", {"2026台復新創會晚"})


def test_fuzzy_dup_keeps_distinct_chats():
    seen = {"正光診所", "王小明"}
    assert not fuzzy_dup("無齡診所4+2R", seen)
    assert not fuzzy_dup("陳大文", seen)
    assert not fuzzy_dup("茶敘", {"老朋友茶敘聚會群"})
    # similar personal names must NEVER merge — losing a chat is worse
    # than an occasional duplicate entry
    assert not fuzzy_dup("王大明", {"王小明"})


def test_fuzzy_dup_known_limit_heavy_garble():
    """Documented limitation: a majority-misread title is unrecognizable
    (similarity 0.56) and stays below the threshold on purpose."""
    assert not fuzzy_dup("我的旅遊吃喝玩樂省", {"戎的旅避吃喝玩槊宜"})
