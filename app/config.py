"""Application configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = APP_ROOT / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


@lru_cache(maxsize=1)
def get_settings() -> "Settings":
    load_dotenv(APP_ROOT / ".env")
    raw = _load_yaml(DEFAULT_CONFIG_PATH)

    lit = os.getenv("LITERATURE_ROOT") or raw.get("literature_root")
    if lit:
        literature_root = Path(lit).expanduser().resolve()
    else:
        literature_root = (APP_ROOT / "..").resolve()

    ocr = raw.get("ocr") or {}
    ai = raw.get("ai") or {}
    server = raw.get("server") or {}

    ai_enabled = os.getenv("LITERATURE_AI_ENABLED", str(ai.get("enabled", False))).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    pdfs_subdir = str(raw.get("pdfs_subdir") or "pdfs").strip().strip("/\\") or "pdfs"
    pdfs_root = (literature_root / pdfs_subdir).resolve()

    return Settings(
        app_root=APP_ROOT,
        literature_root=literature_root,
        pdfs_root=pdfs_root,
        captures_root=literature_root / "_captures",
        ocr_engine=str(ocr.get("engine", "auto")),
        ocr_lang=str(ocr.get("lang", "eng+chi_sim")),
        upscale_min_side=int(ocr.get("upscale_min_side", 1000)),
        ai_enabled=ai_enabled,
        ai_base_url=str(ai.get("base_url", "https://api.openai.com/v1")),
        ai_model=str(ai.get("model", "gpt-4o")),
        ai_api_key=os.getenv("LITERATURE_AI_API_KEY", ""),
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8765)),
    )


class Settings:
    def __init__(
        self,
        *,
        app_root: Path,
        literature_root: Path,
        pdfs_root: Path,
        captures_root: Path,
        ocr_engine: str,
        ocr_lang: str,
        upscale_min_side: int,
        ai_enabled: bool,
        ai_base_url: str,
        ai_model: str,
        ai_api_key: str,
        host: str,
        port: int,
    ) -> None:
        self.app_root = app_root
        self.literature_root = literature_root
        self.pdfs_root = pdfs_root
        self.captures_root = captures_root
        self.ocr_engine = ocr_engine
        self.ocr_lang = ocr_lang
        self.upscale_min_side = upscale_min_side
        self.ai_enabled = ai_enabled
        self.ai_base_url = ai_base_url
        self.ai_model = ai_model
        self.ai_api_key = ai_api_key
        self.host = host
        self.port = port

    def ensure_dirs(self) -> None:
        self.captures_root.mkdir(parents=True, exist_ok=True)
        self.pdfs_root.mkdir(parents=True, exist_ok=True)
