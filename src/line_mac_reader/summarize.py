"""Work-item summarization via a LOCAL LLM (--summarize).

Speaks the OpenAI-compatible chat-completions protocol over plain urllib,
which covers Ollama (http://localhost:11434/v1), LM Studio
(http://localhost:1234/v1) and llama.cpp's server with one code path.
Everything stays on-machine: transcripts go to localhost and nowhere else.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from .config import LlmConfig
from .models import ChatResult

log = logging.getLogger(__name__)

# Reasoning models (qwen3 etc.) may emit a think block before the answer.
_RE_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def chat_to_text(r: ChatResult, max_chars: int) -> str:
    """One chat's transcript as plain text for the prompt; long chats keep
    their NEWEST messages (the tail is what tomorrow's follow-ups need)."""
    lines = [f"### 對話：{r.chat_name}"]
    for m in r.messages:
        ts = f"{m.timestamp_est:%m/%d %H:%M}" if m.timestamp_est else "??:??"
        who = "我" if m.sender == "me" else m.sender
        lines.append(f"[{ts}] {who}: {' '.join(m.text.split())}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = lines[0] + "\n（前段省略）\n" + text[-max_chars:]
    return text


def build_messages(results: list[ChatResult], cfg: LlmConfig) -> list[dict]:
    transcripts = [chat_to_text(r, cfg.max_chars_per_chat)
                   for r in results if r.messages and not r.error]
    system = cfg.system_prompt
    if not cfg.think:
        # qwen3 & friends: this soft switch disables the <think> phase. Models
        # that don't recognize it just see a harmless trailing token.
        system += "\n/no_think"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(transcripts)},
    ]


def strip_reasoning(text: str) -> str:
    return _RE_THINK.sub("", text).strip()


def iter_stream_content(resp):
    """Yield content pieces from an OpenAI-style SSE stream (pure generator,
    testable with any line-iterable)."""
    for raw in resp:
        line = raw.decode("utf-8").strip() if isinstance(raw, bytes) else raw.strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = obj.get("choices") or [{}]
        piece = (choices[0].get("delta") or {}).get("content")
        if piece:
            yield piece


def call_llm(cfg: LlmConfig, messages: list[dict]) -> str:
    """POST to {base_url}/chat/completions and stream the reply.

    Streaming matters: a non-streamed request holds the socket idle for the
    WHOLE generation, so the read timeout must cover cold model-load plus the
    entire answer — which is exactly what timed out. Streaming makes the
    timeout a per-chunk stall guard instead, so long generations succeed as
    long as tokens keep arriving. Raises RuntimeError on any failure so the
    caller can degrade gracefully.
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    pieces: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            pieces.extend(iter_stream_content(resp))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"連不上或逾時（本地 LLM {url}）：{exc}。"
            f"請確認 Ollama 在跑且模型已載入（ollama run {cfg.model} 先暖機），"
            "或在 config 調高 llm.timeout。") from exc
    if not pieces:
        raise RuntimeError("本地 LLM 沒有回傳任何內容（模型是否存在？）")
    return strip_reasoning("".join(pieces))


def summarize_results(cfg: LlmConfig, results: list[ChatResult]) -> str | None:
    """Return the work-item summary, or None when there is nothing to feed."""
    messages = build_messages(results, cfg)
    if not messages[1]["content"].strip():
        log.info("No readable chats to summarize")
        return None
    log.info("Summarizing %d chat(s) with local model %s",
             sum(1 for r in results if r.messages and not r.error), cfg.model)
    return call_llm(cfg, messages)
