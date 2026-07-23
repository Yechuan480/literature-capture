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


_BAIDU_ERR_HINTS = {
    "52001": "请求超时，请重试",
    "52002": "系统错误，请稍后重试",
    "52003": "未授权用户：检查 App ID 是否开通通用翻译",
    "54000": "必填参数为空",
    "54001": "签名错误：核对 App ID 与密钥",
    "54003": "访问频率受限",
    "54004": "账户余额不足",
    "54005": "长 query 请求频繁，请降低频率",
    "58000": "客户端 IP 非法：在控制台绑定本机出口 IP",
    "58001": "译文语言方向不支持",
    "58002": "服务当前已关闭：控制台开启通用翻译",
    "90107": "认证未通过或未生效",
}


def _baidu_error_message(code: Any, msg: Any) -> str:
    code_s = str(code or "").strip()
    base = f"百度翻译错误 {code_s}"
    if msg:
        base += f": {msg}"
    hint = _BAIDU_ERR_HINTS.get(code_s)
    if hint:
        base += f"（{hint}）"
    return base


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
                try:
                    data = res.json()
                except Exception:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": f"百度翻译 HTTP {res.status_code}，响应非 JSON",
                        "model": "baidu",
                        "provider": "baidu",
                    }
                if "error_code" in data:
                    return {
                        "ok": False,
                        "translation": "\n".join(out),
                        "error": _baidu_error_message(
                            data.get("error_code"), data.get("error_msg")
                        ),
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


def test_baidu_connection(
    *,
    app_id: str | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    """
    Probe Baidu VIP translate with a short phrase.
    Optional app_id/secret override saved settings (for test-before-save).
    """
    cfg = load_translate_settings(force=True)
    probe = dict(cfg)
    if app_id is not None and str(app_id).strip():
        probe["baidu_app_id"] = str(app_id).strip()
    if secret is not None and str(secret).strip() and not (
        "•" in secret or (secret.count("*") >= 4)
    ):
        probe["baidu_secret"] = str(secret).strip()

    aid = (probe.get("baidu_app_id") or "").strip()
    sec = (probe.get("baidu_secret") or "").strip()
    if not aid or not sec:
        return {
            "ok": False,
            "message": "请先填写百度 App ID 与密钥并保存（或在测试前输入密钥）",
            "translation": "",
        }

    sample = "Hello, literature reader."
    r = _baidu_translate(sample, probe)
    if r.get("ok"):
        zh = (r.get("translation") or "").strip()
        return {
            "ok": True,
            "message": f"连接成功 · {sample} → {zh}",
            "translation": zh,
            "provider": "baidu",
        }
    return {
        "ok": False,
        "message": r.get("error") or "百度翻译测试失败",
        "translation": r.get("translation") or "",
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
