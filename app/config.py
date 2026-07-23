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
    si = raw.get("si") or {}

    ai_enabled = _env_bool(
        "LITERATURE_AI_ENABLED",
        str(ai.get("enabled", False)).lower() in ("1", "true", "yes", "on"),
    )

    pdfs_subdir = str(raw.get("pdfs_subdir") or "pdfs").strip().strip("/\\") or "pdfs"
    pdfs_root = (literature_root / pdfs_subdir).resolve()

    paddle_enabled = _env_bool(
        "LITERATURE_PADDLE_ENABLED",
        str(paddle.get("enabled", False)).lower() in ("1", "true", "yes", "on"),
    )

    si_enabled = _env_bool(
        "LITERATURE_SI_ENABLED",
        str(si.get("enabled", True)).lower() in ("1", "true", "yes", "on"),
    )
    si_auto = _env_bool(
        "LITERATURE_SI_AUTO_ON_OPEN",
        str(si.get("auto_on_open", True)).lower() in ("1", "true", "yes", "on"),
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
        si_enabled=si_enabled,
        si_auto_on_open=si_auto,
        si_user_agent=str(
            si.get("user_agent")
            or "literature-capture/1.3 (local research tool; +https://github.com/Yechuan480/literature-capture)"
        ),
        si_request_timeout_s=float(si.get("request_timeout_s") or 30),
        si_max_file_mb=float(si.get("max_file_mb") or 80),
        si_min_interval_ms=int(si.get("min_interval_ms") or 800),
        si_max_concurrent_jobs=int(si.get("max_concurrent_jobs") or 2),
        si_max_files_per_paper=int(si.get("max_files_per_paper") or 15),
        si_crossref_mailto=str(
            os.getenv("LITERATURE_SI_CROSSREF_MAILTO")
            or si.get("crossref_mailto")
            or ""
        ).strip(),
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
        paddle_enabled: bool = False,
        paddle_device: str = "cpu",
        paddle_detect_model: str = "PicoDet_layout_1x_table",
        paddle_recognize_pipeline: str = "table_recognition_v2",
        paddle_detect_dpi: int = 150,
        paddle_min_score: float = 0.4,
        paddle_max_detect_pages: int = 0,
        si_enabled: bool = True,
        si_auto_on_open: bool = True,
        si_user_agent: str = "literature-capture/1.3",
        si_request_timeout_s: float = 30.0,
        si_max_file_mb: float = 80.0,
        si_min_interval_ms: int = 800,
        si_max_concurrent_jobs: int = 2,
        si_max_files_per_paper: int = 15,
        si_crossref_mailto: str = "",
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
        self.si_enabled = si_enabled
        self.si_auto_on_open = si_auto_on_open
        self.si_user_agent = si_user_agent
        self.si_request_timeout_s = si_request_timeout_s
        self.si_max_file_mb = si_max_file_mb
        self.si_min_interval_ms = si_min_interval_ms
        self.si_max_concurrent_jobs = si_max_concurrent_jobs
        self.si_max_files_per_paper = si_max_files_per_paper
        self.si_crossref_mailto = si_crossref_mailto

    def ensure_dirs(self) -> None:
        self.captures_root.mkdir(parents=True, exist_ok=True)
        self.pdfs_root.mkdir(parents=True, exist_ok=True)
