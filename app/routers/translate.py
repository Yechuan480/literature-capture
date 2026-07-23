"""PDF translation API: region + full document + provider settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.paths import safe_pdf_path
from app.services.translate import jobs as tr_jobs
from app.services.translate.full_pdf import (
    enqueue_full_translate,
    translated_name,
    translated_path,
)
from app.services.translate.region import translate_region
from app.services.translate.providers import test_baidu_connection
from app.services.translate.settings import (
    public_translate_status,
    save_translate_settings,
)

router = APIRouter(prefix="/api/translate", tags=["translate"])


class RegionRequest(BaseModel):
    filename: str
    page: int = Field(..., ge=1)
    rect: dict[str, float]  # x,y,w,h in CSS px relative to canvas
    canvas: dict[str, float]  # w,h of rendered page CSS
    image_b64: str | None = None  # optional PNG for vision fallback
    rotation: int = 0  # page rotation shown in viewer: 0|90|180|270
    provider: str | None = None  # ai|google|baidu|cnki
    prefer_vision: bool = False  # AI only: translate crop image first


class FullRequest(BaseModel):
    filename: str
    force: bool = False
    provider: str | None = None


class TranslateSettingsUpdate(BaseModel):
    provider: str | None = None
    baidu_app_id: str | None = None
    baidu_secret: str | None = Field(
        default=None,
        description="留空表示保持；clear_baidu_secret=true 则清空",
    )
    clear_baidu_secret: bool = False
    cnki_token: str | None = Field(
        default=None,
        description="可选；留空保持；clear_cnki_token=true 则清空",
    )
    clear_cnki_token: bool = False


class BaiduTestBody(BaseModel):
    baidu_app_id: str | None = None
    baidu_secret: str | None = Field(
        default=None,
        description="可选；不填则用已保存密钥",
    )


@router.get("/settings")
def get_translate_settings():
    return public_translate_status()


@router.put("/settings")
def put_translate_settings(body: TranslateSettingsUpdate):
    save_translate_settings(
        provider=body.provider,
        baidu_app_id=body.baidu_app_id,
        baidu_secret=body.baidu_secret,
        clear_baidu_secret=body.clear_baidu_secret,
        cnki_token=body.cnki_token,
        clear_cnki_token=body.clear_cnki_token,
    )
    return public_translate_status()


@router.post("/settings/test-baidu")
def post_test_baidu(body: BaiduTestBody | None = None):
    """Probe Baidu translate API with saved or form credentials."""
    body = body or BaiduTestBody()
    result = test_baidu_connection(
        app_id=body.baidu_app_id,
        secret=body.baidu_secret,
    )
    status = public_translate_status()
    return {**status, "test": result}


@router.post("/region")
def post_region(body: RegionRequest):
    try:
        safe_pdf_path(body.filename)
    except HTTPException:
        raise
    result = translate_region(
        filename=body.filename,
        page=body.page,
        rect=body.rect,
        canvas=body.canvas,
        image_b64=body.image_b64,
        rotation=int(body.rotation or 0),
        provider=body.provider,
        prefer_vision=bool(body.prefer_vision),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "翻译失败")
    return result


@router.post("/pdf")
def post_full_pdf(body: FullRequest):
    try:
        job = enqueue_full_translate(
            body.filename, force=body.force, provider=body.provider
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id == "cached":
        raise HTTPException(status_code=404, detail="cached 请直接打开译稿")
    job = tr_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/status")
def translate_status(filename: str):
    """Check if translated PDF exists + active job."""
    try:
        safe_pdf_path(filename)
    except HTTPException:
        raise
    out = translated_path(filename)
    key = f"pdf:{filename}"
    job = tr_jobs.job_for_key(key)
    return {
        "filename": filename,
        "translated_name": translated_name(filename),
        "exists": out.is_file(),
        "job": job,
    }


@router.get("/file/{filename}")
def get_translated_file(filename: str):
    """Serve translated PDF by original or .zh-CN name."""
    # Accept either original.pdf or original.zh-CN.pdf
    name = filename
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="非法文件名")
    if name.endswith(".zh-CN.pdf"):
        path = translated_path(name.replace(".zh-CN.pdf", ".pdf"))
        # if user passed already translated name under pdfs
        from app.config import get_settings

        alt = (get_settings().pdfs_root / name).resolve()
        if alt.is_file():
            path = alt
        elif not path.is_file():
            # try as sibling of original stem
            path = alt
    else:
        path = translated_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="译稿不存在")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )
