"""Translate provider preference + optional Baidu keys (local JSON)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import APP_ROOT

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None

SETTINGS_DIR = APP_ROOT / "data"
SETTINGS_PATH = SETTINGS_DIR / "translate_settings.json"

PROVIDERS = ("ai", "google", "baidu", "cnki")
PROVIDER_LABELS = {
    "ai": "AI 翻译",
    "google": "Google 翻译",
    "baidu": "百度翻译",
    "cnki": "CNKI 翻译",
}


def _defaults() -> dict[str, Any]:
    return {
        "provider": "ai",
        "baidu_app_id": "",
        "baidu_secret": "",
        "cnki_token": "",
    }


def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_translate_settings(*, force: bool = False) -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not force:
            return dict(_CACHE)
        merged = _defaults()
        file_data = _read_file()
        for key in ("provider", "baidu_app_id", "baidu_secret", "cnki_token"):
            if key in file_data and file_data[key] is not None:
                merged[key] = str(file_data[key]).strip()
        if merged["provider"] not in PROVIDERS:
            merged["provider"] = "ai"
        _CACHE = dict(merged)
        return dict(merged)


def save_translate_settings(
    *,
    provider: str | None = None,
    baidu_app_id: str | None = None,
    baidu_secret: str | None = None,
    clear_baidu_secret: bool = False,
    cnki_token: str | None = None,
    clear_cnki_token: bool = False,
) -> dict[str, Any]:
    global _CACHE
    current = load_translate_settings(force=True)
    if provider is not None:
        p = (provider or "ai").strip().lower()
        current["provider"] = p if p in PROVIDERS else "ai"
    if baidu_app_id is not None:
        current["baidu_app_id"] = (baidu_app_id or "").strip()
    if clear_baidu_secret:
        current["baidu_secret"] = ""
    elif baidu_secret is not None:
        s = baidu_secret.strip()
        if s and not _looks_masked(s):
            current["baidu_secret"] = s
    if clear_cnki_token:
        current["cnki_token"] = ""
    elif cnki_token is not None:
        t = cnki_token.strip()
        if t and not _looks_masked(t):
            current["cnki_token"] = t

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        _CACHE = dict(current)
    return dict(current)


def _looks_masked(key: str) -> bool:
    if not key:
        return True
    if "•" in key:
        return True
    if "*" in key and key.count("*") >= 4:
        return True
    return False


def public_translate_status() -> dict[str, Any]:
    cfg = load_translate_settings()
    return {
        "provider": cfg["provider"],
        "providers": [
            {
                "id": p,
                "label": PROVIDER_LABELS[p],
                "needs_key": p in ("ai", "baidu", "cnki"),
            }
            for p in PROVIDERS
        ],
        "baidu_app_id": cfg.get("baidu_app_id") or "",
        "baidu_secret_set": bool(cfg.get("baidu_secret")),
        "cnki_token_set": bool(cfg.get("cnki_token")),
    }
