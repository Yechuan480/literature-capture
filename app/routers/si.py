"""SI (supplementary information) discovery + download API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import get_settings
from app.models.schemas import SiRunRequest
from app.paths import get_paper_dir, load_meta, safe_pdf_path, safe_si_file
from app.services.si.pipeline import enqueue_si_run, status_for

router = APIRouter(prefix="/api/si", tags=["si"])


@router.get("/status")
def si_status(
    filename: str | None = Query(None, description="PDF 文件名"),
    slug: str | None = Query(None, description="paper_slug"),
):
    if not filename and not slug:
        raise HTTPException(status_code=400, detail="需要 filename 或 slug")
    if filename:
        safe_pdf_path(filename)
    try:
        return status_for(filename=filename, slug=slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/run")
def si_run(body: SiRunRequest):
    safe_pdf_path(body.filename)
    try:
        return enqueue_si_run(
            filename=body.filename,
            title=body.title,
            doi=body.doi,
            url=body.url,
            force=bool(body.force),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/file/{slug}/{name}")
def si_file(slug: str, name: str):
    settings = get_settings()
    paper_dir = get_paper_dir(slug, settings)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="会话不存在")
    path = safe_si_file(paper_dir, name)
    media = "application/octet-stream"
    lower = name.lower()
    if lower.endswith(".pdf"):
        media = "application/pdf"
    elif lower.endswith(".zip"):
        media = "application/zip"
    elif lower.endswith(".xlsx"):
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif lower.endswith(".csv"):
        media = "text/csv"
    elif lower.endswith((".html", ".htm")):
        media = "text/html"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        content_disposition_type="inline",
    )
