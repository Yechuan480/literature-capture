"""Translate helpers: chunk text via AI client."""

from __future__ import annotations

from typing import Any

from app.services.ai_client import chat_complete
from app.services.ai_settings import load_ai_settings

TARGET_LANG = "zh-CN"
TARGET_LABEL = "简体中文"


def translate_text(text: str, *, context: str = "") -> dict[str, Any]:
    """Translate free text to zh-CN. Returns {ok, translation, error, model}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "translation": "", "error": "无文本可翻译", "model": None}

    cfg = load_ai_settings()
    sys = (
        f"你是专业学术翻译。将用户给出的文本翻译成{TARGET_LABEL}（{TARGET_LANG}）。"
        "保留专业术语、数字、单位、化学式、基因名等；不要添加解释或前言。"
        "只输出译文正文。"
    )
    if context:
        sys += f"\n上下文：{context[:500]}"

    # chunk long text
    chunks = _chunk(text, max_chars=3500)
    parts: list[str] = []
    model = None
    for i, ch in enumerate(chunks):
        prompt = ch if len(chunks) == 1 else f"[第{i+1}/{len(chunks)}段]\n{ch}"
        result = chat_complete(
            [
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
            timeout=90.0,
            cfg=cfg,
        )
        model = result.get("model")
        if not result.get("ok"):
            return {
                "ok": False,
                "translation": "\n".join(parts),
                "error": result.get("error") or "翻译失败",
                "model": model,
            }
        parts.append((result.get("content") or "").strip())
    return {
        "ok": True,
        "translation": "\n".join(parts).strip(),
        "error": None,
        "model": model,
    }


def _chunk(text: str, max_chars: int = 3500) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    n = 0
    for para in text.split("\n"):
        if n + len(para) + 1 > max_chars and buf:
            parts.append("\n".join(buf))
            buf = [para]
            n = len(para)
        else:
            buf.append(para)
            n += len(para) + 1
    if buf:
        parts.append("\n".join(buf))
    return parts or [text]
