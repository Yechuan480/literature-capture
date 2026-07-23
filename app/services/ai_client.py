"""OpenAI-compatible chat/completions HTTP client (shared by vision, chat, translate)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.services.ai_settings import load_ai_settings

# Cloudflare (error 1010) blocks bare Python-urllib UA on many API gateways.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 literature-capture/1.0"
)


def api_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": _UA,
        "Accept": "application/json",
    }


# Back-compat aliases used by older imports
_api_headers = api_headers


def normalize_base_url(base_url: str) -> str:
    """OpenAI-compatible root ending in /v1 (not the full chat path)."""
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return "https://api.openai.com/v1"
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)].rstrip("/")
            break
    try:
        from urllib.parse import urlparse

        p = urlparse(u)
        path = (p.path or "").rstrip("/")
        if p.scheme and p.netloc and path in ("", "/"):
            u = f"{p.scheme}://{p.netloc}/v1"
    except Exception:
        pass
    return u


_normalize_base_url = normalize_base_url


def read_json_response(raw: bytes, *, content_type: str | None = None) -> dict[str, Any]:
    text = (raw or b"").decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("空响应（检查 Base URL 是否带 /v1）")
    ct = (content_type or "").lower()
    if "html" in ct or text[:1] == "<" or text.lower().startswith("<!doctype"):
        raise ValueError(
            "收到 HTML 而非 JSON：Base URL 多半少了 /v1"
            "（正确示例：https://api.openai.com/v1 或 https://你的中转/v1）"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        preview = text[:120].replace("\n", " ")
        raise ValueError(f"响应不是 JSON: {e}; 预览: {preview}") from e
    if not isinstance(data, dict):
        raise ValueError(f"响应 JSON 类型异常: {type(data).__name__}")
    return data


_read_json_response = read_json_response


def chat_complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    POST {base}/chat/completions.
    Returns {ok, content, model, base_url, error?, raw?}.
    """
    cfg = cfg or load_ai_settings()
    if not cfg.get("enabled"):
        return {"ok": False, "content": None, "error": "AI 未启用", "model": cfg.get("model")}
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {
            "ok": False,
            "content": None,
            "error": "未配置 API Key",
            "model": cfg.get("model"),
        }
    base_url = normalize_base_url(cfg.get("base_url") or "https://api.openai.com/v1")
    use_model = (model or cfg.get("model") or "gpt-4o").strip()
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=api_headers(api_key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = read_json_response(
                resp.read(), content_type=resp.headers.get("content-type")
            )
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            # some multimodal replies return content parts
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            content = "".join(parts)
        return {
            "ok": True,
            "content": content if isinstance(content, str) else str(content),
            "model": use_model,
            "base_url": base_url,
            "error": None,
            "raw": body,
        }
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        hint = ""
        if e.code == 403 and "1010" in detail:
            hint = "（Cloudflare 1010：网关拦请求；可换 Base URL/代理）"
        elif e.code == 404:
            hint = f"（请确认 Base URL 为 OpenAI 兼容根路径，当前: {base_url}）"
        return {
            "ok": False,
            "content": None,
            "error": f"API HTTP {e.code}: {detail}{hint}",
            "model": use_model,
            "base_url": base_url,
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "content": None,
            "error": f"网络错误: {e.reason}",
            "model": use_model,
            "base_url": base_url,
        }
    except Exception as e:
        return {
            "ok": False,
            "content": None,
            "error": f"{type(e).__name__}: {e}",
            "model": use_model,
            "base_url": base_url,
        }
