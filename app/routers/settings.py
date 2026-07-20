"""User-facing settings (AI API configuration)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.ai_settings import load_ai_settings, public_ai_status, save_ai_settings
from app.services.ai_vision import test_ai_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AiSettingsUpdate(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(
        default=None,
        description="留空或提交掩码表示保持原 Key；clear_key=true 则清空",
    )
    clear_key: bool = False


@router.get("/ai")
def get_ai_settings():
    return public_ai_status()


@router.put("/ai")
def put_ai_settings(body: AiSettingsUpdate):
    save_ai_settings(
        enabled=body.enabled,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
        clear_key=body.clear_key,
    )
    return public_ai_status()


@router.post("/ai/test")
def post_ai_test():
    """Test connectivity with currently saved settings."""
    status = public_ai_status()
    result = test_ai_connection()
    return {**status, "test": result}
