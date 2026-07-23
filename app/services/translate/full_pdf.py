"""Full-PDF translation → reflowed zh-CN PDF via fpdf2."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.paths import safe_pdf_path, utc_now_iso
from app.services import library_store as lib
from app.services.translate import jobs as tr_jobs
from app.services.translate.text import translate_text

_FONT_CANDIDATES = [
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
]


def _find_font() -> Path | None:
    for p in _FONT_CANDIDATES:
        if p.is_file():
            return p
    return None


def translated_name(filename: str) -> str:
    stem = Path(filename).stem
    return f"{stem}.zh-CN.pdf"


def translated_path(filename: str) -> Path:
    settings = get_settings()
    # Store next to originals under pdfs/
    return (settings.pdfs_root / translated_name(filename)).resolve()


def extract_pages_text(pdf_path: Path) -> list[str]:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in pdf.pages:
            t = (p.extract_text() or "").strip()
            pages.append(t)
    return pages


def write_zh_pdf(pages_zh: list[str], out_path: Path, *, title: str = "") -> None:
    from fpdf import FPDF

    font_path = _find_font()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    if font_path:
        # ttc may need uni=True; fpdf2 add_font
        try:
            pdf.add_font("zh", "", str(font_path))
            font_name = "zh"
        except Exception:
            font_name = "Helvetica"
    else:
        font_name = "Helvetica"

    if title:
        pdf.add_page()
        pdf.set_font(font_name, size=14)
        pdf.multi_cell(0, 8, title)
        pdf.ln(4)
        pdf.set_font(font_name, size=10)
        pdf.multi_cell(0, 6, f"（机译 zh-CN · {utc_now_iso()}）")

    for i, text in enumerate(pages_zh, start=1):
        pdf.add_page()
        pdf.set_font(font_name, size=9)
        header = f"— 第 {i} 页 / {len(pages_zh)} —"
        pdf.multi_cell(0, 5, header)
        pdf.ln(2)
        body = text or "（本页无可提取文本）"
        # fpdf multi_cell struggles with some control chars
        body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", body)
        pdf.set_font(font_name, size=11)
        try:
            pdf.multi_cell(0, 6, body)
        except Exception:
            # fallback strip non-latin if font missing
            pdf.set_font("Helvetica", size=11)
            pdf.multi_cell(0, 6, body.encode("latin-1", errors="replace").decode("latin-1"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


def run_full_translate(job_id: str, payload: dict[str, Any]) -> None:
    filename = payload["filename"]
    force = bool(payload.get("force"))
    path = safe_pdf_path(filename)
    out = translated_path(filename)

    if out.is_file() and not force:
        tr_jobs.update_job(
            job_id,
            status="done",
            progress="done",
            message="已存在译稿",
            result_path=str(out),
            result_name=out.name,
        )
        try:
            lib.patch_item(filename, {"translated_pdf": out.name})
        except Exception:
            pass
        return

    tr_jobs.update_job(job_id, progress="extract", message="提取原文…")
    pages = extract_pages_text(path)
    if not any(pages):
        raise RuntimeError("全文无可提取文本（可能是扫描件）")

    translated: list[str] = []
    total = len(pages)
    for i, page_text in enumerate(pages, start=1):
        tr_jobs.update_job(
            job_id,
            progress=f"page {i}/{total}",
            message=f"翻译第 {i}/{total} 页…",
        )
        if not (page_text or "").strip():
            translated.append("")
            continue
        res = translate_text(page_text, context=f"{filename} p.{i}/{total}")
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"第 {i} 页翻译失败")
        translated.append(res.get("translation") or "")

    tr_jobs.update_job(job_id, progress="write", message="写入译稿 PDF…")
    title = Path(filename).stem
    try:
        item = lib.get_item(filename, sync=False)
        if item and item.get("title"):
            title = item["title"]
    except Exception:
        pass
    write_zh_pdf(translated, out, title=f"{title}（中文译稿）")

    try:
        lib.patch_item(filename, {"translated_pdf": out.name})
    except Exception:
        pass

    tr_jobs.update_job(
        job_id,
        status="done",
        progress="done",
        message="完成",
        result_path=str(out),
        result_name=out.name,
    )


def enqueue_full_translate(filename: str, *, force: bool = False) -> dict[str, Any]:
    safe_pdf_path(filename)  # validate
    key = f"pdf:{filename}"
    if not force:
        existing = tr_jobs.job_for_key(key)
        if existing and existing.get("status") in ("queued", "running"):
            return existing
        out = translated_path(filename)
        if out.is_file():
            return {
                "id": "cached",
                "key": key,
                "filename": filename,
                "status": "done",
                "progress": "done",
                "message": "已存在译稿",
                "error": None,
                "result_path": str(out),
                "result_name": out.name,
            }
    return tr_jobs.start_job(
        key,
        run_full_translate,
        {"filename": filename, "force": force},
    )
