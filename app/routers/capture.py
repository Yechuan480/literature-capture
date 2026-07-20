"""Capture upload (save PNG only), batch/single extract, re-extract."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.paths import (
    allocate_paper_dir,
    get_paper_dir,
    list_captures,
    load_meta,
    next_table_paths,
    safe_pdf_path,
    save_meta,
    set_table_review,
    utc_now_iso,
)
from app.services.extract_table import (
    dataframe_preview,
    extract_table,
    save_table_exports,
)

router = APIRouter(prefix="/api", tags=["capture"])

MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _run_extract_one(
    paper_dir,
    meta: dict,
    table_id: int,
    *,
    use_ai: bool = False,
    force_engine: str | None = None,
    action: str = "extract",
) -> dict:
    """Extract one table PNG → CSV/XLSX; update meta; return result dict."""
    slug = meta["paper_slug"]
    stem = f"{slug}-table{int(table_id)}"
    png_path = paper_dir / f"{stem}.png"
    csv_path = paper_dir / f"{stem}.csv"
    xlsx_path = paper_dir / f"{stem}.xlsx"
    if not png_path.is_file():
        raise HTTPException(status_code=404, detail=f"截图不存在: {stem}.png")

    result = extract_table(png_path, use_ai=use_ai, force_engine=force_engine)
    df = result["dataframe"]
    save_table_exports(df, csv_path, xlsx_path)

    meta["updated_at"] = utc_now_iso()
    # Update captures log entry
    caps = list(meta.get("captures") or [])
    found = False
    for c in caps:
        if isinstance(c, dict) and int(c.get("table_id") or 0) == int(table_id):
            c["extracted"] = True
            c["engine"] = result.get("engine")
            c["warnings"] = result.get("warnings") or []
            c["extracted_at"] = utc_now_iso()
            found = True
            break
    if not found:
        caps.append(
            {
                "table_id": int(table_id),
                "extracted": True,
                "engine": result.get("engine"),
                "warnings": result.get("warnings") or [],
                "at": utc_now_iso(),
                "extracted_at": utc_now_iso(),
            }
        )
    meta["captures"] = caps[-50:]

    strategy = result.get("strategy") or ("ai" if use_ai else (force_engine or "auto"))
    set_table_review(
        meta,
        int(table_id),
        status="pending",
        engine=result.get("engine"),
        strategy=strategy,
        append_history={
            "action": action,
            "engine": result.get("engine"),
            "at": utc_now_iso(),
        },
    )

    return {
        "table_id": int(table_id),
        "paper_slug": slug,
        "paths": {
            "png": str(png_path),
            "csv": str(csv_path),
            "xlsx": str(xlsx_path),
        },
        "names": {
            "png": png_path.name,
            "csv": csv_path.name,
            "xlsx": xlsx_path.name,
        },
        "engine": result["engine"],
        "warnings": result["warnings"],
        "rows": result["rows"],
        "cols": result["cols"],
        "preview": dataframe_preview(df),
        "extracted": True,
        "review_status": "pending",
    }


@router.post("/capture")
async def capture_table(
    image: UploadFile = File(...),
    filename: str = Form(...),
    title: str = Form(...),
    page: int = Form(1),
    use_ai: bool = Form(False),  # kept for API compat; ignored (extract is deferred)
):
    """
    Save a region screenshot only — no table extraction.
    Use POST /api/capture/{slug}/extract-batch (or single extract) later.
    """
    del use_ai  # deferred extract; AI option applies at extract time
    safe_pdf_path(filename)
    if image.content_type and image.content_type not in (
        "image/png",
        "image/jpeg",
        "image/jpg",
        "application/octet-stream",
    ):
        raise HTTPException(status_code=400, detail="请上传 PNG/JPEG 截图")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="空图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片过大（上限 20MB）")

    paper_dir, meta = allocate_paper_dir(title, filename)
    n, png_path, csv_path, xlsx_path = next_table_paths(paper_dir, meta)

    png_path.write_bytes(data)

    meta["table_counter"] = n
    meta["no_tables"] = False
    meta["updated_at"] = utc_now_iso()
    last = meta.get("captures") or []
    last.append(
        {
            "table_id": n,
            "page": page,
            "extracted": False,
            "engine": None,
            "warnings": [],
            "at": utc_now_iso(),
        }
    )
    meta["captures"] = last[-50:]
    # Do NOT enter review queue until content is extracted
    save_meta(paper_dir, meta)

    return {
        "table_id": n,
        "paper_slug": meta["paper_slug"],
        "title": meta["title"],
        "folder": str(paper_dir),
        "paths": {
            "png": str(png_path),
            "csv": None,
            "xlsx": None,
        },
        "names": {
            "png": png_path.name,
            "csv": None,
            "xlsx": None,
        },
        "engine": None,
        "warnings": [],
        "rows": 0,
        "cols": 0,
        "preview": [],
        "page": page,
        "extracted": False,
        "capture_count": n,
    }


@router.post("/capture/{slug}/{table_id}/extract")
def extract_one(
    slug: str,
    table_id: int,
    use_ai: bool = Query(False),
    force_engine: str | None = Query(None),
):
    """Extract table content for one saved screenshot."""
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta.json 不存在")

    out = _run_extract_one(
        paper_dir,
        meta,
        table_id,
        use_ai=use_ai,
        force_engine=force_engine,
        action="extract",
    )
    save_meta(paper_dir, meta)
    out["captures"] = list_captures(paper_dir, meta)
    return out


@router.post("/capture/{slug}/extract-batch")
def extract_batch(
    slug: str,
    use_ai: bool = Query(False),
    force_engine: str | None = Query(None),
    only_pending: bool = Query(True, description="仅提取尚未有 CSV/XLSX 的截图"),
):
    """
    Batch-extract all (or pending) marked table regions for a paper.
    """
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta.json 不存在")

    caps = list_captures(paper_dir, meta)
    targets = []
    for c in caps:
        if only_pending and c.get("extracted"):
            continue
        targets.append(int(c["table_id"]))

    results: list[dict] = []
    errors: list[dict] = []
    for tid in targets:
        try:
            results.append(
                _run_extract_one(
                    paper_dir,
                    meta,
                    tid,
                    use_ai=use_ai,
                    force_engine=force_engine,
                    action="batch_extract",
                )
            )
        except HTTPException as e:
            errors.append({"table_id": tid, "error": e.detail})
        except Exception as e:
            errors.append({"table_id": tid, "error": str(e)})

    save_meta(paper_dir, meta)
    return {
        "paper_slug": meta["paper_slug"],
        "title": meta.get("title") or "",
        "requested": len(targets),
        "ok": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "captures": list_captures(paper_dir, meta),
        "use_ai": use_ai,
        "force_engine": force_engine,
    }


@router.post("/capture/{slug}/{table_id}/reextract")
def reextract(slug: str, table_id: int, use_ai: bool = False):
    """Re-run extraction on an existing PNG (must already have been extracted, or first extract)."""
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta.json 不存在")

    out = _run_extract_one(
        paper_dir,
        meta,
        table_id,
        use_ai=use_ai,
        force_engine=None,
        action="reextract",
    )
    save_meta(paper_dir, meta)
    out["captures"] = list_captures(paper_dir, meta)
    return out
