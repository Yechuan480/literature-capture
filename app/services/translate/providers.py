"""Multi-provider text translation: AI / Google / Baidu / CNKI."""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.services.ai_settings import ai_ready, load_ai_settings
from app.services.translate.settings import (
    PROVIDER_LABELS,
    load_translate_settings,
)
from app.services.translate.text import translate_text as ai_translate_text

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def translate_with_provider(
    text: str,
    *,
    provider: str | None = None,
    context: str = "",
) -> dict[str, Any]:
    """Translate to zh-CN via selected provider.

    Returns {ok, translation, error, model, provider}.
    """
    text = (text or "").strip()
    if not text:
        return {
            "ok": False,
            "translation": "",
            "error": "无文本可翻译",
            "model": None,
            "provider": provider or "ai",
        }

    cfg = load_translate_settings()
    p = (provider or cfg.get("provider") or "ai").strip().lower()
    if p not in PROVIDER_LABELS:
        p = "ai"

    if p == "ai":
        if not ai_ready():
            return {
                "ok": False,
                "translation": "",
                "error": "AI 未配置：请在设置中启用并填写 API Key",
                "model": None,
                "provider": "ai",
            }
        r = ai_translate_text(text, context=context)
        return {
            "ok": bool(r.get("ok")),
            "translation": r.get("translation") or "",
            "error": r.get("error"),
            "model": r.get("model"),
            "provider": "ai",
        }

    if p == "google":
        return _google_translate(text)

    if p == "baidu":
        return _baidu_translate(text, cfg)

    if p == "cnki":
        return _cnki_translate(text, cfg)

    return {
        "ok": False,
        "translation": "",
        "error": f"未知引擎: {p}",
        "model": None,
        "provider": p,
    }


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    n = 0
    for para in text.replace("\r\n", "\n").split("\n"):
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


def _google_translate(text: str) -> dict[str, Any]:
    """Unofficial Google Translate endpoint (no key). Best-effort; may rate-limit."""
    chunks = _chunk_text(text, 1800)
    out: list[str] = []
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": _UA}, follow_redirects=True) as client:
            for ch in chunks:
                url = (
                    "https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl=auto&tl=zh-CN&dt=t&q={quote(ch)}"
                )
                res = client.get(url)
                if res.status_code != 200:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": f"Google 翻译 HTTP {res.status_code}",
                        "model": "google-gtx",
                        "provider": "google",
                    }
                data = res.json()
                # [[ [translated, original, ...], ...], ...]
                segs = []
                if isinstance(data, list) and data and isinstance(data[0], list):
                    for item in data[0]:
                        if isinstance(item, list) and item and isinstance(item[0], str):
                            segs.append(item[0])
                piece = "".join(segs).strip()
                if not piece:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": "Google 翻译返回空结果",
                        "model": "google-gtx",
                        "provider": "google",
                    }
                out.append(piece)
        return {
            "ok": True,
            "translation": "\n".join(out).strip(),
            "error": None,
            "model": "google-gtx",
            "provider": "google",
        }
    except Exception as e:
        return {
            "ok": False,
            "translation": "\n".join(out),
            "error": f"Google 翻译失败: {e}",
            "model": "google-gtx",
            "provider": "google",
        }


def _baidu_translate(text: str, cfg: dict[str, Any]) -> dict[str, Any]:
    app_id = (cfg.get("baidu_app_id") or "").strip()
    secret = (cfg.get("baidu_secret") or "").strip()
    if not app_id or not secret:
        return {
            "ok": False,
            "translation": "",
            "error": "百度翻译未配置：请在设置填写 App ID 与密钥（开放平台通用翻译 API）",
            "model": "baidu",
            "provider": "baidu",
        }

    chunks = _chunk_text(text, 1800)
    out: list[str] = []
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": _UA}) as client:
            for ch in chunks:
                salt = str(random.randint(10000, 99999))
                sign_src = f"{app_id}{ch}{salt}{secret}"
                sign = hashlib.md5(sign_src.encode("utf-8")).hexdigest()
                res = client.post(
                    "https://fanyi-api.baidu.com/api/trans/vip/translate",
                    data={
                        "q": ch,
                        "from": "auto",
                        "to": "zh",
                        "appid": app_id,
                        "salt": salt,
                        "sign": sign,
                    },
                )
                data = res.json()
                if "error_code" in data:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": f"百度翻译错误 {data.get('error_code')}: {data.get('error_msg')}",
                        "model": "baidu",
                        "provider": "baidu",
                    }
                trans = data.get("trans_result") or []
                piece = "\n".join(
                    (t.get("dst") or "") for t in trans if isinstance(t, dict)
                ).strip()
                if not piece:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": "百度翻译返回空结果",
                        "model": "baidu",
                        "provider": "baidu",
                    }
                out.append(piece)
        return {
            "ok": True,
            "translation": "\n".join(out).strip(),
            "error": None,
            "model": "baidu",
            "provider": "baidu",
        }
    except Exception as e:
        return {
            "ok": False,
            "translation": "\n".join(out),
            "error": f"百度翻译失败: {e}",
            "model": "baidu",
            "provider": "baidu",
        }


def _cnki_translate(text: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Best-effort CNKI academic translate.

    Official CNKI 翻译 requires login / product entitlement. We try the public
    `dict.cnki.net` endpoint when available; otherwise return a clear error.
    Optional cnki_token may be used as Bearer if provided.
    """
    token = (cfg.get("cnki_token") or "").strip()
    chunks = _chunk_text(text, 1200)
    out: list[str] = []
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://dict.cnki.net",
        "Referer": "https://dict.cnki.net/index",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["token"] = token

    # Known public-ish endpoints (may change)
    endpoints = [
        (
            "POST",
            "https://dict.cnki.net/fanyiapi/translate",
            lambda q: {"keywords": q, "transType": "2"},  # 2 ≈ en→zh
        ),
        (
            "POST",
            "https://dict.cnki.net/new-translate/api/translate",
            lambda q: {"text": q, "from": "en", "to": "zh"},
        ),
    ]

    try:
        with httpx.Client(timeout=35.0, headers=headers, follow_redirects=True) as client:
            for ch in chunks:
                piece = ""
                last_err = ""
                for method, url, body_fn in endpoints:
                    try:
                        if method == "POST":
                            res = client.post(url, json=body_fn(ch))
                        else:
                            res = client.get(url, params=body_fn(ch))
                        if res.status_code >= 400:
                            last_err = f"HTTP {res.status_code}"
                            continue
                        ct = res.headers.get("content-type", "")
                        if "json" not in ct and not res.text.strip().startswith(("{", "[")):
                            last_err = "非 JSON 响应（可能需登录）"
                            continue
                        data = res.json()
                        piece = _extract_cnki_text(data)
                        if piece:
                            break
                        last_err = "空结果"
                    except Exception as e:
                        last_err = str(e)
                if not piece:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": (
                            "CNKI 翻译不可用："
                            f"{last_err or '接口未开放'}。"
                            "知网翻译通常需账号/权限；可改用 Google / 百度 / AI，"
                            "或在设置中填写可用的 CNKI token 后重试。"
                        ),
                        "model": "cnki",
                        "provider": "cnki",
                    }
                out.append(piece)
        return {
            "ok": True,
            "translation": "\n".join(out).strip(),
            "error": None,
            "model": "cnki",
            "provider": "cnki",
        }
    except Exception as e:
        return {
            "ok": False,
            "translation": "\n".join(out),
            "error": f"CNKI 翻译失败: {e}",
            "model": "cnki",
            "provider": "cnki",
        }


def _extract_cnki_text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        parts = [_extract_cnki_text(x) for x in data]
        return "\n".join(p for p in parts if p).strip()
    if isinstance(data, dict):
        for key in (
            "translateResult",
            "translation",
            "dst",
            "result",
            "data",
            "content",
            "trans_text",
            "zh",
            "text",
        ):
            if key in data:
                got = _extract_cnki_text(data[key])
                if got:
                    return got
        # nested common pattern: data.words / data.list
        for key in ("words", "list", "items", "results"):
            if key in data:
                got = _extract_cnki_text(data[key])
                if got:
                    return got
    return ""
