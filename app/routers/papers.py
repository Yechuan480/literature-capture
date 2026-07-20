"""Paper listing, title detection, session management, PDF streaming."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import get_settings
from app.models.schemas import (
    PaperDeleteRequest,
    PaperDeleteResponse,
    PaperItem,
    PaperStatusRequest,
    PaperStatusResponse,
    SessionRequest,
    SessionResponse,
    TitleResponse,
    CaptureListResponse,
)
from app.paths import (
    allocate_paper_dir,
    delete_paper,
    get_paper_dir,
    list_captures,
    list_pdfs,
    load_meta,
    safe_pdf_path,
    set_no_tables,
)
from app.services.title import extract_title

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers", response_model=list[PaperItem])
def get_papers():
    return list_pdfs()


@router.get("/papers/title", response_model=TitleResponse)
def get_paper_title(filename: str = Query(..., description="PDF 文件名")):
    path = safe_pdf_path(filename)
    result = extract_title(path)
    return TitleResponse(
        filename=filename,
        title=result["title"],
        source=result["source"],
        candidates=result.get("candidates") or [],
    )


@router.post("/papers/session", response_model=SessionResponse)
def create_session(body: SessionRequest):
    safe_pdf_path(body.filename)  # validate exists
    paper_dir, meta = allocate_paper_dir(body.title, body.filename)
    return SessionResponse(
        filename=body.filename,
        title=meta["title"],
        paper_slug=meta["paper_slug"],
        folder=str(paper_dir),
        table_counter=int(meta.get("table_counter", 0)),
        no_tables=bool(meta.get("no_tables")),
    )


@router.post("/papers/status", response_model=PaperStatusResponse)
def update_paper_status(body: PaperStatusRequest):
    """Mark paper as no-tables / clear the mark."""
    title = (body.title or "").strip()
    if not title:
        # Fall back to extracted title so marking works without prior confirm
        path = safe_pdf_path(body.filename)
        title = extract_title(path)["title"]
    meta = set_no_tables(body.filename, title, body.no_tables)
    slug = meta["paper_slug"]
    paper_dir = get_paper_dir(slug)
    captures = list_captures(paper_dir, meta)
    return PaperStatusResponse(
        filename=body.filename,
        title=meta["title"],
        paper_slug=slug,
        folder=str(paper_dir),
        no_tables=bool(meta.get("no_tables")),
        capture_count=len(captures),
    )


@router.post("/papers/delete", response_model=PaperDeleteResponse)
def remove_paper(body: PaperDeleteRequest):
    """Delete a PDF (and its _captures folder by default). Irreversible."""
    result = delete_paper(body.filename, delete_captures=body.delete_captures)
    return PaperDeleteResponse(**result)


@router.get("/papers/{slug}/captures", response_model=CaptureListResponse)
def get_captures(slug: str):
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta.json 不存在")
    return CaptureListResponse(
        paper_slug=meta["paper_slug"],
        title=meta.get("title", ""),
        folder=str(paper_dir),
        captures=list_captures(paper_dir, meta),
    )


@router.get("/pdf/{filename}")
def get_pdf(filename: str):
    path = safe_pdf_path(filename)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )
