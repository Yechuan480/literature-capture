"""Runtime AI settings: load/save local JSON, merge with env/config defaults."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import APP_ROOT, get_settings

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None

SETTINGS_DIR = APP_ROOT / "data"
SETTINGS_PATH = SETTINGS_DIR / "ai_settings.json"


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": bool(s.ai_enabled),
        "base_url": s.ai_base_url or "https://api.openai.com/v1",
        "model": s.ai_model or "gpt-4o",
        "api_key": s.ai_api_key or "",
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


def load_ai_settings(*, force: bool = False) -> dict[str, Any]:
    """Merged AI config: defaults ← local file. Env key only used as default seed."""
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not force:
            return dict(_CACHE)
        merged = _defaults()
        file_data = _read_file()
        for key in ("enabled", "base_url", "model", "api_key"):
            if key in file_data and file_data[key] is not None:
                if key == "enabled":
                    merged[key] = bool(file_data[key])
                else:
                    merged[key] = str(file_data[key]).strip()
        _CACHE = dict(merged)
        return dict(merged)


def save_ai_settings(
    *,
    enabled: bool | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_key: bool = False,
) -> dict[str, Any]:
    """Persist AI settings. Empty/placeholder api_key keeps the existing key unless clear_key."""
    global _CACHE
    current = load_ai_settings(force=True)
    if enabled is not None:
        current["enabled"] = bool(enabled)
    if base_url is not None:
        # Host-only URLs miss /v1 and hit the provider SPA (HTML 200 → JSON decode error).
        from app.services.ai_client import normalize_base_url

        current["base_url"] = normalize_base_url(
            (base_url or "").strip() or "https://api.openai.com/v1"
        )
    if model is not None:
        current["model"] = (model or "").strip() or "gpt-4o"
    if clear_key:
        current["api_key"] = ""
    elif api_key is not None:
        key = api_key.strip()
        # Ignore masked placeholders from UI
        if key and not _looks_masked(key):
            current["api_key"] = key

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        _CACHE = dict(current)
    return dict(current)


def _looks_masked(key: str) -> bool:
    if not key:
        return True
    if "•" in key or "*" in key and key.count("*") >= 4:
        return True
    if key.lower() in ("unchanged", "(unchanged)", "keep", "保持不变"):
        return True
    return False


def mask_api_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * min(12, len(key) - 8)}{key[-4:]}"


def public_ai_status() -> dict[str, Any]:
    cfg = load_ai_settings()
    key = cfg.get("api_key") or ""
    ready = bool(cfg.get("enabled") and key)
    return {
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "api_key_set": bool(key),
        "api_key_masked": mask_api_key(key),
        "ready": ready,
        "settings_path": str(SETTINGS_PATH),
    }


def ai_ready() -> bool:
    cfg = load_ai_settings()
    return bool(cfg.get("enabled") and (cfg.get("api_key") or "").strip())
