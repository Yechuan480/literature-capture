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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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
    paddle = raw.get("paddle") or {}

    ai_enabled = _env_bool(
        "LITERATURE_AI_ENABLED",
        str(ai.get("enabled", False)).lower() in ("1", "true", "yes", "on"),
    )

    pdfs_subdir = str(raw.get("pdfs_subdir") or "pdfs").strip().strip("/\\") or "pdfs"
    pdfs_root = (literature_root / pdfs_subdir).resolve()

    paddle_enabled = _env_bool(
        "LITERATURE_PADDLE_ENABLED",
        str(paddle.get("enabled", True)).lower() in ("1", "true", "yes", "on"),
    )

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
        paddle_enabled=paddle_enabled,
        paddle_device=str(paddle.get("device") or "cpu"),
        paddle_detect_model=str(
            paddle.get("detect_model") or "PicoDet_layout_1x_table"
        ),
        paddle_recognize_pipeline=str(
            paddle.get("recognize_pipeline") or "table_recognition_v2"
        ),
        paddle_detect_dpi=int(paddle.get("detect_dpi") or 150),
        paddle_min_score=float(paddle.get("min_score") or 0.4),
        paddle_max_detect_pages=int(paddle.get("max_detect_pages") or 0),
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
        paddle_enabled: bool = True,
        paddle_device: str = "cpu",
        paddle_detect_model: str = "PicoDet_layout_1x_table",
        paddle_recognize_pipeline: str = "table_recognition_v2",
        paddle_detect_dpi: int = 150,
        paddle_min_score: float = 0.4,
        paddle_max_detect_pages: int = 0,
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
        self.paddle_enabled = paddle_enabled
        self.paddle_device = paddle_device
        self.paddle_detect_model = paddle_detect_model
        self.paddle_recognize_pipeline = paddle_recognize_pipeline
        self.paddle_detect_dpi = paddle_detect_dpi
        self.paddle_min_score = paddle_min_score
        self.paddle_max_detect_pages = paddle_max_detect_pages

    def ensure_dirs(self) -> None:
        self.captures_root.mkdir(parents=True, exist_ok=True)
        self.pdfs_root.mkdir(parents=True, exist_ok=True)
