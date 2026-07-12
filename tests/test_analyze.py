from line_mac_reader.analyze import analyze_chat, analyze_run, classify, render_report


def _chat(name, messages, error=None):
    return {"chat_name": name, "error": error, "messages": messages}


def _msg(text, sender="對方", ts="2026-07-11T10:00:00+08:00"):
    return {"sender": sender, "text": text, "timestamp_est": ts,
            "timestamp_confidence": "high", "kind": "text", "ocr_confidence": 0.9}


def test_marketing_broadcast_excluded():
    chat = _chat("必勝客", [
        _msg("【隱藏神券】2個大比薩+可樂只要$388! 限量優惠"),
        _msg("週年慶滿額禮包，立即下單"),
        _msg("會員獨享折價券來囉"),
    ])
    verdict, reasons = classify(analyze_chat(chat))
    assert verdict == "exclude"
    assert any("行銷/通知用語" in r for r in reasons)
    assert any("品牌" in r for r in reasons)  # 必勝客 hits the brand list


def test_bank_notifications_excluded():
    chat = _chat("國泰世華銀行", [_msg("交易成功 $8,000 出帳通知")] * 5)
    verdict, _ = classify(analyze_chat(chat))
    assert verdict == "exclude"


def test_news_feed_group_excluded():
    msgs = [_msg(f"新聞標題 https://udn.com/{i}") for i in range(20)]
    verdict, reasons = classify(analyze_chat(_chat("某輿情群", msgs)))
    assert verdict == "exclude"
    assert any("新聞/資訊推播" in r for r in reasons)


def test_mega_group_low_participation_excluded():
    msgs = [_msg(f"分享{i}", ts="2026-07-11T10:00:00+08:00") for i in range(200)]
    verdict, reasons = classify(analyze_chat(_chat("超大群", msgs)))
    assert verdict == "exclude"
    assert any("大型資訊群" in r for r in reasons)


def test_active_conversation_kept():
    msgs = [_msg("報價單請確認"), _msg("好的，下午回你", sender="me"),
            _msg("合約也麻煩了"), _msg("收到", sender="me")]
    verdict, reasons = classify(analyze_chat(_chat("客戶A", msgs)))
    assert verdict == "keep"
    assert any("實際參與" in r for r in reasons)


def test_quiet_personal_chat_kept():
    verdict, _ = classify(analyze_chat(_chat("王小明", [_msg("生日快樂！")])))
    # 名稱無機構字樣、無行銷內容 → 保留（一則「生日快樂」不是推播）
    assert verdict == "keep"


def test_institution_name_without_content_is_review():
    chat = _chat("某某銀行", [_msg("您好"), _msg("通知您一下")])
    verdict, _ = classify(analyze_chat(chat))
    assert verdict in ("review", "exclude")  # 名稱可疑，至少要標記


def test_analyze_run_buckets_and_already_filtered():
    data = {"chats": [
        _chat("必勝客", [_msg("限量優惠 立即下單 折價券")] * 3),
        _chat("客戶A", [_msg("報價"), _msg("OK", sender="me")]),
        _chat("LINE禮物", [_msg("免費貼圖")]),
        _chat("壞掉的", [], error="標題不符"),
    ]}
    buckets = analyze_run(data, exclude_patterns=("LINE禮物",))
    names = {k: [s.name for s, _ in v] for k, v in buckets.items()}
    assert "必勝客" in names["exclude"]
    assert "客戶A" in names["keep"]
    assert "LINE禮物" in names["already"]
    assert "壞掉的" in names["errors"]


def test_render_report_contains_yaml_block():
    data = {"chats": [_chat("必勝客", [_msg("限量優惠 立即下單 折價券")] * 3)]}
    buckets = analyze_run(data, ("既有項目",))
    report = render_report(buckets, ("既有項目",))
    assert "建議加入 filter" in report
    assert "exclude_chats: [" in report
    assert "必勝客" in report
    assert "既有項目," in report  # 合併既有清單
