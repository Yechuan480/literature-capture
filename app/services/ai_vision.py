"""Optional AI vision table extraction (OpenAI-compatible chat/completions)."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.services.ai_settings import load_ai_settings

# Cloudflare (error 1010) blocks bare Python-urllib UA on many API gateways.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 literature-capture/1.0"
)


def _api_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": _UA,
        "Accept": "application/json",
    }


def extract_table_ai(
    image_path: Path,
    settings: Any = None,  # kept for call-site compatibility; ignored in favor of runtime cfg
) -> list[list[str]] | None:
    """Call vision API for structured table JSON. Returns None if disabled or failed."""
    result = extract_table_ai_detailed(image_path)
    return result.get("matrix")


def extract_table_ai_detailed(image_path: Path) -> dict[str, Any]:
    """
    Returns {ok, matrix, error, model, usage_note}.
    matrix is list[list[str]] on success.
    """
    cfg = load_ai_settings()
    if not cfg.get("enabled"):
        return {"ok": False, "matrix": None, "error": "AI 未启用", "model": cfg.get("model")}
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "matrix": None, "error": "未配置 API Key", "model": cfg.get("model")}

    base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (cfg.get("model") or "gpt-4o").strip()

    try:
        with image_path.open("rb") as f:
            raw = f.read()
        if not raw:
            return {"ok": False, "matrix": None, "error": "图片为空", "model": model}
        if len(raw) > 15 * 1024 * 1024:
            return {"ok": False, "matrix": None, "error": "图片过大（>15MB）", "model": model}
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png"
        if image_path.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract scientific tables from images. "
                        "Respond with ONLY a JSON 2D array of strings "
                        "(array of rows; each row is an array of cell texts). "
                        "Preserve visual reading order, merge multi-line cells with space, "
                        "keep numbers and units as shown. No markdown fences, no commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract every cell of the main table in this image as a JSON "
                                "2D string array. Empty cells as \"\"."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 4096,
        }
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=_api_headers(api_key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        matrix = _parse_matrix(content)
        if not matrix:
            return {
                "ok": False,
                "matrix": None,
                "error": "AI 返回无法解析为表格矩阵",
                "model": model,
                "raw_preview": (content or "")[:400],
            }
        return {"ok": True, "matrix": matrix, "error": None, "model": model}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        return {
            "ok": False,
            "matrix": None,
            "error": f"API HTTP {e.code}: {detail}",
            "model": model,
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "matrix": None,
            "error": f"网络错误: {e.reason}",
            "model": model,
        }
    except Exception as e:
        return {"ok": False, "matrix": None, "error": f"{type(e).__name__}: {e}", "model": model}


def test_ai_connection() -> dict[str, Any]:
    """Lightweight text-only call to verify key / endpoint / model."""
    cfg = load_ai_settings()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "AI 未启用"}
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "未配置 API Key"}
    base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (cfg.get("model") or "gpt-4o").strip()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=_api_headers(api_key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return {"ok": True, "model": model, "reply": (content or "").strip()[:80]}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        hint = ""
        if e.code == 403 and "1010" in detail:
            hint = "（Cloudflare 1010：网关按浏览器指纹拦请求；已带 UA，若仍失败请换 Base URL/代理或检查 IP 是否被封）"
        return {
            "ok": False,
            "error": f"HTTP {e.code}: {detail}{hint}",
            "model": model,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "model": model}


def _parse_matrix(content: str) -> list[list[str]] | None:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, list) or not data:
        return None
    rows: list[list[str]] = []
    for row in data:
        if isinstance(row, list):
            rows.append(["" if c is None else str(c).strip() for c in row])
        else:
            rows.append([str(row).strip()])
    return rows or None
