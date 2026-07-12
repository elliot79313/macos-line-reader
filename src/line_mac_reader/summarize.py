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
    return [
        {"role": "system", "content": cfg.system_prompt},
        {"role": "user", "content": "\n\n".join(transcripts)},
    ]


def strip_reasoning(text: str) -> str:
    return _RE_THINK.sub("", text).strip()


def call_llm(cfg: LlmConfig, messages: list[dict]) -> str:
    """POST to {base_url}/chat/completions; raises RuntimeError on failure."""
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"連不上本地 LLM（{url}）：{exc}。"
            "Ollama 是否在跑？（ollama serve / ollama pull "
            f"{cfg.model}）") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"本地 LLM 回應格式異常：{data}") from exc
    return strip_reasoning(content)


def summarize_results(cfg: LlmConfig, results: list[ChatResult]) -> str | None:
    """Return the work-item summary, or None when there is nothing to feed."""
    messages = build_messages(results, cfg)
    if not messages[1]["content"].strip():
        log.info("No readable chats to summarize")
        return None
    log.info("Summarizing %d chat(s) with local model %s",
             sum(1 for r in results if r.messages and not r.error), cfg.model)
    return call_llm(cfg, messages)
