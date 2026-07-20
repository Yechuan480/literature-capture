"""Capture upload, table extraction, re-extract."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.paths import (
    allocate_paper_dir,
    get_paper_dir,
    list_captures,
    load_meta,
    next_table_paths,
    safe_pdf_path,
    save_meta,
    utc_now_iso,
)
from app.services.extract_table import (
    dataframe_preview,
    extract_table,
    save_table_exports,
)

router = APIRouter(prefix="/api", tags=["capture"])

MAX_IMAGE_BYTES = 20 * 1024 * 1024


@router.post("/capture")
async def capture_table(
    image: UploadFile = File(...),
    filename: str = Form(...),
    title: str = Form(...),
    page: int = Form(1),
    use_ai: bool = Form(False),
):
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

    result = extract_table(png_path, use_ai=use_ai)
    df = result["dataframe"]
    save_table_exports(df, csv_path, xlsx_path)

    meta["table_counter"] = n
    # Capturing a table implies the paper is not "no tables"
    meta["no_tables"] = False
    meta["updated_at"] = utc_now_iso()
    last = meta.get("captures") or []
    last.append(
        {
            "table_id": n,
            "page": page,
            "engine": result["engine"],
            "warnings": result["warnings"],
            "at": utc_now_iso(),
        }
    )
    meta["captures"] = last[-50:]
    # New captures enter the human review queue as pending
    from app.paths import set_table_review

    set_table_review(
        meta,
        n,
        status="pending",
        engine=result.get("engine"),
        strategy=result.get("strategy") or ("ai" if use_ai else "auto"),
        append_history={
            "action": "capture",
            "engine": result.get("engine"),
            "at": utc_now_iso(),
        },
    )
    save_meta(paper_dir, meta)

    return {
        "table_id": n,
        "paper_slug": meta["paper_slug"],
        "title": meta["title"],
        "folder": str(paper_dir),
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
        "page": page,
    }


@router.post("/capture/{slug}/{table_id}/reextract")
def reextract(slug: str, table_id: int, use_ai: bool = False):
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta.json 不存在")

    stem = f"{meta['paper_slug']}-table{table_id}"
    png_path = paper_dir / f"{stem}.png"
    csv_path = paper_dir / f"{stem}.csv"
    xlsx_path = paper_dir / f"{stem}.xlsx"
    if not png_path.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")

    result = extract_table(png_path, use_ai=use_ai)
    df = result["dataframe"]
    save_table_exports(df, csv_path, xlsx_path)

    meta["updated_at"] = utc_now_iso()
    from app.paths import set_table_review

    set_table_review(
        meta,
        table_id,
        status="pending",
        engine=result.get("engine"),
        strategy=result.get("strategy") or ("ai" if use_ai else "auto"),
        append_history={
            "action": "reextract",
            "engine": result.get("engine"),
            "at": utc_now_iso(),
        },
    )
    save_meta(paper_dir, meta)

    return {
        "table_id": table_id,
        "paper_slug": meta["paper_slug"],
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
        "captures": list_captures(paper_dir, meta),
        "review_status": "pending",
    }
