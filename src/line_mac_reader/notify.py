"""Slack Incoming Webhook digest.

Turns a run's ChatResults into a morning-review message: per chat, action-item
candidates (lines containing digest.action_keywords) float to the top, then
the message log. Sent via plain urllib — no extra dependency, no data goes
anywhere except the webhook the user configured.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime

from .models import ChatResult, Message

log = logging.getLogger(__name__)

SLACK_TEXT_LIMIT = 35000  # keep well under Slack's ~40k per-message cap


def _fmt_time(m: Message) -> str:
    if m.timestamp_est is None:
        return "??:??"
    mark = "~" if m.timestamp_confidence == "low" else ""
    return f"{mark}{m.timestamp_est:%m/%d %H:%M}"


def _is_action(m: Message, keywords: tuple[str, ...]) -> bool:
    return m.kind == "text" and any(k in m.text for k in keywords)


def build_chat_section(r: ChatResult, keywords: tuple[str, ...],
                       max_messages: int) -> str | None:
    """One chat's digest block, or None when there is nothing to say."""
    if r.error:
        return f"*【{r.chat_name}】* ⚠ 讀取失敗：{r.error}"
    if not r.messages:
        return None

    lines = [f"*【{r.chat_name}】* {len(r.messages)} 則"
             f"（{r.read_from:%m/%d %H:%M} → {r.read_to:%m/%d %H:%M}）"]

    actions = [m for m in r.messages if _is_action(m, keywords)]
    if actions:
        lines.append("✅ *待辦候選*")
        for m in actions:
            lines.append(f"> • {_fmt_time(m)} {m.sender}: "
                         f"{' '.join(m.text.split())}")

    shown = r.messages[-max_messages:]
    skipped = len(r.messages) - len(shown)
    if skipped:
        lines.append(f"_（省略較早的 {skipped} 則，完整內容見 output JSON）_")
    for m in shown:
        lines.append(f"• {_fmt_time(m)} {m.sender}: {' '.join(m.text.split())}")
    return "\n".join(lines)


def build_digest(results: list[ChatResult], run_at: datetime,
                 keywords: tuple[str, ...], max_messages: int) -> list[str]:
    """Digest as a list of Slack messages (split on chat boundaries when the
    total would exceed Slack's size limit). Empty list = nothing to send."""
    sections = [s for r in results
                if (s := build_chat_section(r, keywords, max_messages))]
    if not sections:
        return []

    total_msgs = sum(len(r.messages) for r in results if not r.error)
    header = (f"☀️ *LINE 每日摘要* {run_at:%Y-%m-%d %H:%M}"
              f"（{len(sections)} 個對話、{total_msgs} 則訊息）")

    chunks: list[str] = []
    current = header
    for s in sections:
        candidate = f"{current}\n\n{s}"
        if len(candidate) > SLACK_TEXT_LIMIT and current:
            chunks.append(current)
            current = s
        else:
            current = candidate
    chunks.append(current)
    return chunks


def send_slack(webhook_url: str, text: str, retries: int = 2) -> None:
    """POST one message to an Incoming Webhook; raises on persistent failure."""
    payload = json.dumps({"text": text}).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                webhook_url, data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return
                last_err = RuntimeError(f"Slack returned HTTP {resp.status}")
        except (urllib.error.URLError, OSError) as exc:
            last_err = exc
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Slack webhook 傳送失敗：{last_err}")


def send_digest(webhook_url: str, results: list[ChatResult],
                run_at: datetime, keywords: tuple[str, ...],
                max_messages: int) -> int:
    """Build and send the digest; returns the number of Slack posts made."""
    chunks = build_digest(results, run_at, keywords, max_messages)
    if not chunks:
        log.info("Digest empty — nothing sent to Slack")
        return 0
    for chunk in chunks:
        send_slack(webhook_url, chunk)
    return len(chunks)
