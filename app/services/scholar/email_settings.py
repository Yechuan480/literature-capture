"""IMAP / Scholar email settings (local JSON, never commit)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import APP_ROOT

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None

SETTINGS_DIR = APP_ROOT / "data"
SETTINGS_PATH = SETTINGS_DIR / "email_settings.json"


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "host": "imap.gmail.com",
        "port": 993,
        "user": "",
        "password": "",
        "folder": "INBOX",
        "ssl": True,
        "sender_filter": "scholaralerts@google.com",
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


def load_email_settings(*, force: bool = False) -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not force:
            return dict(_CACHE)
        merged = _defaults()
        file_data = _read_file()
        for key in (
            "enabled",
            "host",
            "port",
            "user",
            "password",
            "folder",
            "ssl",
            "sender_filter",
        ):
            if key not in file_data or file_data[key] is None:
                continue
            if key == "enabled" or key == "ssl":
                merged[key] = bool(file_data[key])
            elif key == "port":
                try:
                    merged[key] = int(file_data[key])
                except (TypeError, ValueError):
                    pass
            else:
                merged[key] = str(file_data[key]).strip()
        _CACHE = dict(merged)
        return dict(merged)


def _looks_masked(val: str) -> bool:
    if not val:
        return True
    if "•" in val or ("*" in val and val.count("*") >= 4):
        return True
    if val.lower() in ("unchanged", "(unchanged)", "keep", "保持不变"):
        return True
    return False


def save_email_settings(
    *,
    enabled: bool | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    folder: str | None = None,
    ssl: bool | None = None,
    sender_filter: str | None = None,
    clear_password: bool = False,
) -> dict[str, Any]:
    global _CACHE
    current = load_email_settings(force=True)
    if enabled is not None:
        current["enabled"] = bool(enabled)
    if host is not None:
        current["host"] = (host or "").strip() or "imap.gmail.com"
    if port is not None:
        try:
            current["port"] = int(port)
        except (TypeError, ValueError):
            current["port"] = 993
    if user is not None:
        current["user"] = (user or "").strip()
    if folder is not None:
        current["folder"] = (folder or "").strip() or "INBOX"
    if ssl is not None:
        current["ssl"] = bool(ssl)
    if sender_filter is not None:
        current["sender_filter"] = (sender_filter or "").strip()
    if clear_password:
        current["password"] = ""
    elif password is not None:
        pw = password.strip()
        if pw and not _looks_masked(pw):
            current["password"] = pw

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        _CACHE = dict(current)
    return dict(current)


def mask_password(pw: str) -> str:
    pw = (pw or "").strip()
    if not pw:
        return ""
    if len(pw) <= 4:
        return "•" * len(pw)
    return f"{'•' * min(10, len(pw) - 2)}{pw[-2:]}"


def public_email_status() -> dict[str, Any]:
    cfg = load_email_settings()
    pw = cfg.get("password") or ""
    user = cfg.get("user") or ""
    ready = bool(cfg.get("enabled") and user and pw)
    return {
        "enabled": bool(cfg.get("enabled")),
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or 993),
        "user": user,
        "password_set": bool(pw),
        "password_masked": mask_password(pw),
        "folder": cfg.get("folder") or "INBOX",
        "ssl": bool(cfg.get("ssl", True)),
        "sender_filter": cfg.get("sender_filter") or "",
        "ready": ready,
        "settings_path": str(SETTINGS_PATH),
    }


def email_ready() -> bool:
    cfg = load_email_settings()
    return bool(
        cfg.get("enabled")
        and (cfg.get("user") or "").strip()
        and (cfg.get("password") or "").strip()
    )
