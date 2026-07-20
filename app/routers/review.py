"""Human QA queue: compare PNG vs extracted table, pass/fail, re-extract strategies."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.paths import (
    get_paper_dir,
    is_under,
    list_captures,
    list_review_queue,
    load_capture_matrix,
    load_meta,
    save_meta,
    set_table_review,
    utc_now_iso,
)
from app.services.ai_settings import ai_ready
from app.services.extract_table import (
    dataframe_preview,
    extract_table,
    save_table_exports,
)

router = APIRouter(prefix="/api/review", tags=["review"])

STRATEGIES = {
    "auto": {"label": "自动（当前默认引擎）", "force_engine": None, "use_ai": False},
    "tesseract": {
        "label": "Tesseract + img2table",
        "force_engine": "img2table_tesseract",
        "use_ai": False,
    },
    "rapidocr": {"label": "RapidOCR 粗网格", "force_engine": "rapidocr", "use_ai": False},
    "ai": {"label": "仅 AI 视觉", "force_engine": "ai", "use_ai": True},
    "tesseract_ai": {
        "label": "Tesseract + AI 增强",
        "force_engine": "img2table_tesseract",
        "use_ai": True,
    },
    "rapidocr_ai": {
        "label": "RapidOCR + AI 增强",
        "force_engine": "rapidocr",
        "use_ai": True,
    },
}


class ReviewVerdict(BaseModel):
    status: str = Field(..., description="passed | failed | pending")
    note: str = ""


def _item_detail(paper_dir, meta: dict, table_id: int) -> dict:
    caps = list_captures(paper_dir, meta)
    item = next((c for c in caps if int(c["table_id"]) == int(table_id)), None)
    if not item:
        raise HTTPException(status_code=404, detail="表格截图不存在")
    csv_path = paper_dir / f"{item['stem']}.csv"
    matrix = load_capture_matrix(csv_path)
    slug = meta.get("paper_slug") or paper_dir.name
    rows = len(matrix) if matrix else 0
    cols = max((len(r) for r in matrix), default=0) if matrix else 0
    return {
        **item,
        "paper_slug": slug,
        "title": meta.get("title") or "",
        "source_pdf": meta.get("source_pdf") or "",
        "folder": str(paper_dir),
        "matrix": matrix,
        "preview": matrix[:40],
        "rows": rows,
        "cols": cols,
        "png_url": f"/api/review/file/{slug}/{table_id}/png",
        "csv_url": f"/api/review/file/{slug}/{table_id}/csv",
        "xlsx_url": f"/api/review/file/{slug}/{table_id}/xlsx",
        "ai_ready": ai_ready(),
        "strategies": [
            {"id": k, "label": v["label"], "needs_ai": bool(v["use_ai"] or k == "ai")}
            for k, v in STRATEGIES.items()
        ],
    }


@router.get("/queue")
def review_queue():
    return list_review_queue()


@router.get("/next")
def review_next(after_slug: str | None = None, after_table_id: int | None = None):
    """Return next queue item (failed first, then pending). Optionally skip current."""
    data = list_review_queue()
    queue = data["queue"]
    if not queue:
        return {"item": None, "stats": data["stats"], "remaining": 0}

    start = 0
    if after_slug and after_table_id is not None:
        for i, q in enumerate(queue):
            if q.get("paper_slug") == after_slug and int(q.get("table_id") or 0) == int(
                after_table_id
            ):
                start = i + 1
                break

    pick = queue[start] if start < len(queue) else queue[0]
    paper_dir = get_paper_dir(pick["paper_slug"])
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta 缺失")
    detail = _item_detail(paper_dir, meta, int(pick["table_id"]))
    return {
        "item": detail,
        "stats": data["stats"],
        "remaining": len(queue),
        "index": start if start < len(queue) else 0,
    }


@router.get("/item/{slug}/{table_id}")
def review_item(slug: str, table_id: int):
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta 缺失")
    return _item_detail(paper_dir, meta, table_id)


@router.post("/item/{slug}/{table_id}/verdict")
def review_verdict(slug: str, table_id: int, body: ReviewVerdict):
    status = (body.status or "").lower().strip()
    if status not in ("passed", "failed", "pending"):
        raise HTTPException(status_code=400, detail="status 必须是 passed/failed/pending")
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta 缺失")

    # Ensure capture exists
    caps = list_captures(paper_dir, meta)
    if not any(int(c["table_id"]) == int(table_id) for c in caps):
        raise HTTPException(status_code=404, detail="表格不存在")

    set_table_review(
        meta,
        table_id,
        status=status,
        note=body.note or "",
        append_history={
            "action": "verdict",
            "status": status,
            "note": body.note or "",
            "at": utc_now_iso(),
        },
    )
    save_meta(paper_dir, meta)

    data = list_review_queue()
    # Find next open item after this one
    next_item = None
    queue = data["queue"]
    for i, q in enumerate(queue):
        if q.get("paper_slug") == slug and int(q.get("table_id") or 0) == int(table_id):
            # still in queue (e.g. failed) — take following
            if i + 1 < len(queue):
                next_item = queue[i + 1]
            elif queue:
                next_item = queue[0] if queue[0] is not q else (queue[1] if len(queue) > 1 else None)
            break
    else:
        next_item = queue[0] if queue else None

    next_detail = None
    if next_item:
        try:
            ndir = get_paper_dir(next_item["paper_slug"])
            nmeta = load_meta(ndir)
            if nmeta:
                next_detail = _item_detail(ndir, nmeta, int(next_item["table_id"]))
        except HTTPException:
            next_detail = None

    return {
        "ok": True,
        "status": status,
        "paper_slug": slug,
        "table_id": table_id,
        "stats": data["stats"],
        "remaining": len(queue),
        "next": next_detail,
    }


@router.post("/item/{slug}/{table_id}/reextract")
def review_reextract(
    slug: str,
    table_id: int,
    strategy: str = Query("auto", description="auto|tesseract|rapidocr|ai|tesseract_ai|rapidocr_ai"),
):
    strategy = (strategy or "auto").lower().strip()
    if strategy not in STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"未知策略: {strategy}，可选: {', '.join(STRATEGIES)}",
        )
    conf = STRATEGIES[strategy]
    if conf["use_ai"] or strategy == "ai":
        if not ai_ready():
            raise HTTPException(status_code=400, detail="AI 未启用或未配置 Key，请先在主页 AI 设置中配置")

    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta 缺失")

    stem = f"{meta['paper_slug']}-table{int(table_id)}"
    png_path = paper_dir / f"{stem}.png"
    csv_path = paper_dir / f"{stem}.csv"
    xlsx_path = paper_dir / f"{stem}.xlsx"
    if not png_path.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")

    result = extract_table(
        png_path,
        use_ai=bool(conf["use_ai"]),
        force_engine=conf["force_engine"],
    )
    df = result["dataframe"]
    save_table_exports(df, csv_path, xlsx_path)

    # Re-extracted tables re-enter the queue as pending for re-check
    set_table_review(
        meta,
        table_id,
        status="pending",
        engine=result.get("engine"),
        strategy=strategy,
        append_history={
            "action": "reextract",
            "strategy": strategy,
            "engine": result.get("engine"),
            "rows": result.get("rows"),
            "cols": result.get("cols"),
            "warnings": (result.get("warnings") or [])[:8],
            "at": utc_now_iso(),
        },
    )

    # Update captures log entry if present
    logs = list(meta.get("captures") or [])
    updated = False
    for c in logs:
        if isinstance(c, dict) and int(c.get("table_id") or -1) == int(table_id):
            c["engine"] = result.get("engine")
            c["warnings"] = result.get("warnings")
            c["strategy"] = strategy
            c["reextracted_at"] = utc_now_iso()
            updated = True
            break
    if not updated:
        logs.append(
            {
                "table_id": int(table_id),
                "engine": result.get("engine"),
                "warnings": result.get("warnings"),
                "strategy": strategy,
                "reextracted_at": utc_now_iso(),
            }
        )
    meta["captures"] = logs[-80:]
    save_meta(paper_dir, meta)

    detail = _item_detail(paper_dir, meta, table_id)
    detail.update(
        {
            "engine": result.get("engine"),
            "warnings": result.get("warnings"),
            "rows": result.get("rows"),
            "cols": result.get("cols"),
            "preview": dataframe_preview(df),
            "strategy_used": strategy,
        }
    )
    return detail


@router.get("/file/{slug}/{table_id}/{kind}")
def review_file(slug: str, table_id: int, kind: str):
    kind = kind.lower()
    if kind not in ("png", "csv", "xlsx"):
        raise HTTPException(status_code=400, detail="kind 须为 png/csv/xlsx")
    paper_dir = get_paper_dir(slug)
    meta = load_meta(paper_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="meta 缺失")
    stem = f"{meta['paper_slug']}-table{int(table_id)}"
    path = paper_dir / f"{stem}.{kind}"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not is_under(path, paper_dir):
        raise HTTPException(status_code=400, detail="路径越界")
    media = {
        "png": "image/png",
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[kind]
    return FileResponse(path, media_type=media, filename=path.name)
