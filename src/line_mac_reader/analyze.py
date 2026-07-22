"""Post-run analysis of output JSON: what was captured, what belongs in
filters.exclude_chats.

Heuristics (all signals are surfaced in the report, not hidden):
- 官方/行銷推播: you never reply AND marketing/notification vocabulary is
  dense, or the name itself looks institutional (銀行/診所/官方/Pay…).
- 資訊/新聞推播群: link-heavy one-way traffic.
- 大型資訊群: high message volume with near-zero participation from you.
- 保留: anything you actively participate in, or low-volume personal chats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Vocabulary that marks broadcast/marketing/notification content (tune freely).
MARKETING_WORDS = (
    "優惠", "折扣", "點數", "貼圖", "限量", "活動", "報名", "下載期限",
    "立即", "滿額", "禮包", "中獎", "週年", "下單", "免費", "上架",
    "交易成功", "出帳", "繳費", "訂單", "通知", "客服", "會員獨享",
    "好康", "抽獎", "折價券", "神券", "%", "停班", "停課", "防災",
    "新聞", "快訊",
)
INSTITUTION_NAME_HINTS = (
    "銀行", "診所", "官方", "政府", "市政府", "STORE", "Store", "Pay",
    "保險", "證券", "信託", "酒店", "飯店", "電信", "禮物", "錢包",
    "客服", "中心", "計畫", "總處", "行政院", "聯名卡", "小舖", "免稅店",
    "溫泉",
    # common TW brand OAs — brand names carry no institutional suffix
    "必勝客", "麥當勞", "肯德基", "星巴克", "7-ELEVEN", "全家", "全聯",
    "蝦皮", "momo", "Uber", "foodpanda", "PChome", "IKEA", "UNIQLO",
)


@dataclass
class ChatStats:
    name: str
    total: int = 0
    me_count: int = 0
    url_count: int = 0
    marketing_hits: int = 0
    senders: set = field(default_factory=set)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    error: str | None = None

    @property
    def me_ratio(self) -> float:
        return self.me_count / self.total if self.total else 0.0

    @property
    def url_ratio(self) -> float:
        return self.url_count / self.total if self.total else 0.0

    @property
    def msgs_per_day(self) -> float:
        if not self.total or not self.first_ts or not self.last_ts:
            return float(self.total)
        days = max((self.last_ts - self.first_ts).total_seconds() / 86400, 0.5)
        return self.total / days


def analyze_chat(chat: dict) -> ChatStats:
    s = ChatStats(name=chat.get("chat_name", "?"), error=chat.get("error"))
    for m in chat.get("messages", []):
        s.total += 1
        sender = m.get("sender", "")
        s.senders.add(sender)
        if sender == "me":
            s.me_count += 1
        text = m.get("text", "")
        if "http" in text:
            s.url_count += 1
        s.marketing_hits += sum(1 for w in MARKETING_WORDS if w in text)
        ts = m.get("timestamp_est")
        if ts:
            try:
                t = datetime.fromisoformat(ts)
            except ValueError:
                continue
            s.first_ts = t if s.first_ts is None or t < s.first_ts else s.first_ts
            s.last_ts = t if s.last_ts is None or t > s.last_ts else s.last_ts
    return s


def classify(s: ChatStats) -> tuple[str, list[str]]:
    """Return (verdict, reasons) from a transparent multi-signal score.

    Verdicts: exclude (score>=4) / review (2..3) / keep (<2).
    Note: me_ratio alone is unreliable — official-account promo cards are
    wide and their fragments get misattributed to "me" by layout parsing —
    so participation only carries weight in combination with other signals.
    """
    reasons: list[str] = []
    score = 0
    density = s.marketing_hits / s.total if s.total else 0.0
    name_hit = any(h in s.name for h in INSTITUTION_NAME_HINTS)
    one_way = s.me_count == 0 and s.total >= 5

    if name_hit:
        score += 2
        reasons.append("名稱含機構/品牌/推播字樣 (+2)")
    if density >= 0.30:
        score += 3
        reasons.append(f"行銷/通知用語密集（{density:.2f}/則）(+3)")
    elif density >= 0.15:
        score += 1
        reasons.append(f"行銷/通知用語偏多（{density:.2f}/則）(+1)")
    if s.url_ratio >= 0.4 and s.total >= 30:
        score += 4
        reasons.append(f"連結佔 {s.url_ratio:.0%} 且量大——新聞/資訊推播 (+4)")
    elif s.url_ratio >= 0.4 and s.total >= 10:
        score += 3
        reasons.append(f"連結佔 {s.url_ratio:.0%}——新聞/資訊推播 (+3)")
    if s.msgs_per_day >= 80 and s.me_ratio < 0.05:
        score += 3
        reasons.append(f"大型資訊群（{s.msgs_per_day:.0f} 則/日、"
                       f"你的參與 {s.me_ratio:.0%}）(+3)")
    if one_way:
        score += 2
        reasons.append("單向推播（你完全沒回覆）(+2)")
    if name_hit and (one_way or density >= 0.08):
        score += 2
        reasons.append("機構名稱＋推播行為的組合 (+2)")

    if score >= 4:
        return "exclude", reasons
    if score >= 2:
        return "review", reasons
    if s.me_ratio >= 0.15:
        return "keep", [f"你有實際參與（{s.me_ratio:.0%} 的訊息是你發的）"]
    return "keep", ["雙向往來或低量對話"]


def analyze_run(data: dict, exclude_patterns: tuple[str, ...] = ()
                ) -> dict[str, list[tuple[ChatStats, list[str]]]]:
    """Bucket every chat in a run's JSON into exclude/review/keep/errors,
    plus 'already' for chats the current filter should have caught."""
    from .chatlist import is_excluded

    buckets: dict[str, list] = {
        "exclude": [], "review": [], "keep": [], "errors": [], "already": [],
    }
    for chat in data.get("chats", []):
        s = analyze_chat(chat)
        if s.error:
            buckets["errors"].append((s, [s.error]))
            continue
        if is_excluded(s.name, exclude_patterns):
            buckets["already"].append(
                (s, ["已在 filter 中，但這次執行仍讀到（執行時尚未套用？）"]))
            continue
        verdict, reasons = classify(s)
        buckets[verdict].append((s, reasons))
    return buckets


def _fmt_range(s: ChatStats) -> str:
    if not s.first_ts or not s.last_ts:
        return "—"
    return f"{s.first_ts:%m/%d %H:%M}~{s.last_ts:%m/%d %H:%M}"


def _shortest_unique_pattern(name: str) -> str:
    """Filter entries are substring matches; the full name always works."""
    return re.sub(r"\s+", " ", name).strip()


def render_report(buckets: dict, existing_filter: tuple[str, ...]) -> str:
    lines: list[str] = []
    total = sum(len(v) for v in buckets.values())
    lines.append(f"===== 本次共讀到 {total} 個對話 =====")

    def section(title, items, with_reason=True):
        lines.append("")
        lines.append(f"--- {title}（{len(items)}）---")
        for s, reasons in sorted(items, key=lambda x: -x[0].total):
            lines.append(f"  {s.name}｜{s.total} 則｜我方 {s.me_ratio:.0%}｜"
                         f"{_fmt_range(s)}")
            if with_reason:
                for r in reasons:
                    lines.append(f"      ↳ {r}")

    if buckets["exclude"]:
        section("🚫 建議加入 filter", buckets["exclude"])
    if buckets["review"]:
        section("🤔 邊緣案例（請人工判斷）", buckets["review"])
    if buckets["keep"]:
        section("✅ 建議保留", buckets["keep"], with_reason=False)
    if buckets["already"]:
        section("⚠️ 應被 filter 擋掉卻出現", buckets["already"])
    if buckets["errors"]:
        section("❌ 讀取失敗", buckets["errors"])

    if buckets["exclude"]:
        additions = [_shortest_unique_pattern(s.name)
                     for s, _ in buckets["exclude"]]
        merged = list(existing_filter) + [a for a in additions
                                          if a not in existing_filter]
        lines.append("")
        lines.append("===== 可直接貼進 config.yaml =====")
        lines.append("filters:")
        lines.append("  exclude_chats: [")
        for i, p in enumerate(merged):
            comma = "," if i < len(merged) - 1 else ""
            lines.append(f"    {p}{comma}")
        lines.append("  ]")
    return "\n".join(lines)
