"""Scholar alert email → 今日待读 → OA PDF."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.scholar import fetch_pdf, inbox as inbox_store
from app.services.scholar.email_settings import (
    load_email_settings,
    public_email_status,
    save_email_settings,
)
from app.services.scholar.imap_client import test_connection

router = APIRouter(prefix="/api/scholar", tags=["scholar"])


class EmailSettingsUpdate(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = Field(
        default=None,
        description="应用专用密码；留空保持不变；clear_password 清空",
    )
    folder: str | None = None
    ssl: bool | None = None
    sender_filter: str | None = None
    clear_password: bool = False


class DecideBody(BaseModel):
    ids: list[str] = Field(default_factory=list)
    action: str  # keep | dismiss
    day: str | None = None


class FetchBody(BaseModel):
    ids: list[str] | None = None
    day: str | None = None


class RefreshBody(BaseModel):
    force: bool = False
    days: int = 1


@router.get("/settings")
def get_settings():
    return public_email_status()


@router.put("/settings")
def put_settings(body: EmailSettingsUpdate):
    save_email_settings(
        enabled=body.enabled,
        host=body.host,
        port=body.port,
        user=body.user,
        password=body.password,
        folder=body.folder,
        ssl=body.ssl,
        sender_filter=body.sender_filter,
        clear_password=body.clear_password,
    )
    return public_email_status()


@router.post("/settings/test")
def post_settings_test():
    status = public_email_status()
    result = test_connection()
    return {**status, "test": result}


@router.get("/inbox/today")
def inbox_today(day: str | None = None):
    data = inbox_store.get_day(day)
    pending = sum(1 for it in data["items"] if it.get("status") == "pending")
    return {**data, "pending_count": pending}


@router.post("/inbox/refresh")
def inbox_refresh(body: RefreshBody | None = None):
    body = body or RefreshBody()
    try:
        data = inbox_store.refresh_inbox(days=body.days, force=body.force)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"刷新失败：{e}") from e
    pending = sum(1 for it in data["items"] if it.get("status") == "pending")
    return {**data, "pending_count": pending}


@router.post("/inbox/decide")
def inbox_decide(body: DecideBody):
    if not body.ids:
        raise HTTPException(status_code=400, detail="请选择条目")
    try:
        data = inbox_store.decide_items(ids=body.ids, action=body.action, day=body.day)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return data


@router.post("/inbox/fetch-pdfs")
def inbox_fetch(body: FetchBody | None = None):
    body = body or FetchBody()
    # ensure selected are marked kept
    if body.ids:
        inbox_store.decide_items(ids=body.ids, action="keep", day=body.day)
    job = fetch_pdf.start_fetch_jobs(body.ids, day=body.day)
    return job


@router.get("/inbox/fetch-jobs/{job_id}")
def fetch_job(job_id: str):
    j = fetch_pdf.get_fetch_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return j
