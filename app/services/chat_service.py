"""Chat assistant: multi-turn complete + light disk history."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from app.config import APP_ROOT
from app.paths import utc_now_iso
from app.services.ai_client import chat_complete
from app.services.ai_settings import ai_ready, load_ai_settings
from app.services.library_store import get_item

_LOCK = threading.Lock()
CHAT_DIR = APP_ROOT / "data" / "chat"
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

SYSTEM_PROMPT = (
    "你是本地文献阅读器中的研究助手（Claude/兼容模型）。"
    "用简洁中文回答；涉及论文时优先基于用户提供的标题/上下文，"
    "不要编造未给出的数据或引用。若信息不足请说明。"
)


def _scope_name(scope: str | None) -> str:
    s = (scope or "global").strip() or "global"
    # filename scopes may contain spaces — hash-ish sanitize
    s = s.replace("/", "_").replace("\\", "_").replace(" ", "_")
    if not _SAFE_SCOPE.match(s):
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120] or "global"
    return s


def history_path(scope: str | None) -> Path:
    return CHAT_DIR / f"{_scope_name(scope)}.jsonl"


def load_history(scope: str | None = None, *, limit: int = 40) -> list[dict[str, Any]]:
    path = history_path(scope)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("role") in ("user", "assistant", "system"):
                    rows.append(obj)
    except OSError:
        return []
    if limit and len(rows) > limit:
        return rows[-limit:]
    return rows


def append_history(scope: str | None, role: str, content: str) -> None:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    path = history_path(scope)
    row = {
        "role": role,
        "content": content,
        "ts": utc_now_iso(),
    }
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def clear_history(scope: str | None = None) -> None:
    path = history_path(scope)
    with _LOCK:
        if path.is_file():
            path.unlink()


def _paper_context(paper_filename: str | None) -> str:
    if not paper_filename:
        return ""
    try:
        item = get_item(paper_filename, sync=False)
    except Exception:
        item = None
    if not item:
        return f"当前打开的 PDF 文件名：{paper_filename}"
    parts = [f"当前文献文件：{item.get('filename')}"]
    if item.get("title"):
        parts.append(f"标题：{item['title']}")
    if item.get("doi"):
        parts.append(f"DOI：{item['doi']}")
    if item.get("status"):
        parts.append(f"阅读状态：{item['status']}")
    if item.get("notes"):
        notes = str(item["notes"])[:500]
        parts.append(f"用户笔记：{notes}")
    return "\n".join(parts)


def chat(
    messages: list[dict[str, str]],
    *,
    paper_filename: str | None = None,
    scope: str | None = None,
    temperature: float = 0.4,
    persist: bool = True,
) -> dict[str, Any]:
    """
    messages: list of {role, content} (user/assistant), last should be user.
    scope defaults to paper filename or 'global'.
    """
    if not ai_ready():
        return {"ok": False, "reply": None, "error": "AI 未配置或未启用", "model": None}

    cleaned: list[dict[str, str]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip()
        content = str(m.get("content") or "").strip()
        if role not in ("user", "assistant", "system") or not content:
            continue
        cleaned.append({"role": role, "content": content[:12000]})
    if not cleaned:
        return {"ok": False, "reply": None, "error": "消息为空", "model": None}

    sc = scope or paper_filename or "global"
    ctx = _paper_context(paper_filename)
    system = SYSTEM_PROMPT
    if ctx:
        system = SYSTEM_PROMPT + "\n\n" + ctx

    api_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    # Keep last N turns from client (already includes history client-side)
    api_messages.extend(cleaned[-20:])

    cfg = load_ai_settings()
    result = chat_complete(
        api_messages,
        temperature=temperature,
        max_tokens=4096,
        timeout=90.0,
        cfg=cfg,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "reply": None,
            "error": result.get("error") or "调用失败",
            "model": result.get("model"),
        }

    reply = (result.get("content") or "").strip()
    if persist:
        # persist last user + assistant
        last_user = next(
            (m["content"] for m in reversed(cleaned) if m["role"] == "user"),
            None,
        )
        if last_user:
            append_history(sc, "user", last_user)
        if reply:
            append_history(sc, "assistant", reply)

    return {
        "ok": True,
        "reply": reply,
        "error": None,
        "model": result.get("model"),
        "scope": _scope_name(sc),
    }
