"""Table region detection API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.paths import safe_pdf_path
from app.services.detect_tables import detect_tables_in_pdf
from app.services.paddle_runtime import detect_ready, paddle_status

router = APIRouter(prefix="/api/detect", tags=["detect"])


class DetectTablesRequest(BaseModel):
    filename: str
    pages: list[int] | None = Field(
        default=None, description="1-based page numbers; null = all pages"
    )
    min_score: float | None = None
    dpi: int | None = None


@router.post("/tables")
def detect_tables(body: DetectTablesRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.paddle_enabled:
        raise HTTPException(
            status_code=503,
            detail="Paddle 检测已关闭（config paddle.enabled=false）",
        )
    if not detect_ready(settings):
        st = paddle_status(settings)
        raise HTTPException(
            status_code=503,
            detail=st.get("paddle_error")
            or "Paddle 检测模型不可用，请安装 paddlepaddle 与 paddlex[ocr]",
        )
    try:
        pdf_path = safe_pdf_path(body.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        result = detect_tables_in_pdf(
            pdf_path,
            pages=body.pages,
            dpi=body.dpi,
            min_score=body.min_score,
            settings=settings,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检测失败: {e}") from e

    return result


@router.get("/status")
def detect_status() -> dict[str, Any]:
    settings = get_settings()
    return paddle_status(settings)
