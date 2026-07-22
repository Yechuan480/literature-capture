"""Path helpers: sanitize titles, resolve PDFs safely, manage paper folders."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import Settings, get_settings

ILLEGAL_FS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MULTI_UNDERSCORE = re.compile(r"_+")
WHITESPACE = re.compile(r"\s+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_display_title(title: str) -> str:
    s = WHITESPACE.sub(" ", (title or "").strip())
    s = s.strip(" .")
    return s


def make_paper_slug(title: str, max_len: int = 100) -> str:
    s = unicodedata.normalize("NFKC", title or "")
    s = WHITESPACE.sub(" ", s).strip()
    s = ILLEGAL_FS.sub("_", s)
    s = s.replace(" ", "_")
    s = MULTI_UNDERSCORE.sub("_", s)
    s = s.strip("._ ")
    if not s:
        s = "untitled"
    if len(s) > max_len:
        s = s[:max_len].rstrip("._ ")
    return s or "untitled"


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_pdf_path(filename: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if not filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    # Basename only: reject path separators (not bare ".." inside a name like "foo..pdf")
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if filename != Path(filename).name:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    # Prefer dedicated pdfs/ folder; fall back to literature_root for legacy layouts
    candidates = [
        (settings.pdfs_root / filename).resolve(),
        (settings.literature_root / filename).resolve(),
    ]
    path: Path | None = None
    for cand in candidates:
        if not is_under(cand, settings.literature_root):
            continue
        if cand.is_file():
            path = cand
            break
    if path is None:
        raise HTTPException(status_code=404, detail="PDF 不存在")
    return path


def capture_stats_by_source_pdf(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Map source_pdf filename → {count, pending_extract, paper_slug, no_tables, title}."""
    settings = settings or get_settings()
    out: dict[str, dict[str, Any]] = {}
    root = settings.captures_root
    if not root.is_dir():
        return out
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta = load_meta(child)
        if not meta:
            continue
        src = meta.get("source_pdf")
        if not src:
            continue
        slug = meta.get("paper_slug") or child.name
        # Prefer actual PNG count; fall back to table_counter
        png_n = len(list(child.glob(f"{slug}-table*.png")))
        count = png_n if png_n else int(meta.get("table_counter") or 0)
        caps = list_captures(child, meta) if png_n else []
        pending = sum(1 for c in caps if not c.get("extracted"))
        prev = out.get(src)
        si = meta.get("si") if isinstance(meta.get("si"), dict) else {}
        si_status = str(si.get("status") or "idle")
        si_files = si.get("files") if isinstance(si.get("files"), list) else []
        if prev is None or count >= int(prev.get("count") or 0):
            out[src] = {
                "count": count,
                "pending_extract": pending,
                "paper_slug": slug,
                "no_tables": bool(meta.get("no_tables")),
                "title": meta.get("title") or "",
                "doi": meta.get("doi") or None,
                "si_status": si_status,
                "si_file_count": len(si_files),
            }
    return out


def list_pending_extracts(settings: Settings | None = None) -> dict[str, Any]:
    """
    All unextracted marked screenshots across papers (for global queue / batch).
    Returns {total, papers: [{paper_slug, title, source_pdf, pending, items: [...]}]}.
    """
    settings = settings or get_settings()
    root = settings.captures_root
    papers: list[dict[str, Any]] = []
    total = 0
    if not root.is_dir():
        return {"total": 0, "papers": [], "items": []}
    flat: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        meta = load_meta(child)
        if not meta:
            continue
        caps = list_captures(child, meta)
        pending_items = [c for c in caps if not c.get("extracted")]
        if not pending_items:
            continue
        slug = meta.get("paper_slug") or child.name
        title = meta.get("title") or ""
        src = meta.get("source_pdf") or ""
        paper_items = []
        for c in pending_items:
            item = {
                "paper_slug": slug,
                "title": title,
                "source_pdf": src,
                "table_id": int(c["table_id"]),
                "stem": c.get("stem"),
                "page": c.get("page"),
                "png_name": c.get("png_name"),
            }
            paper_items.append(item)
            flat.append(item)
        n = len(paper_items)
        total += n
        papers.append(
            {
                "paper_slug": slug,
                "title": title,
                "source_pdf": src,
                "pending": n,
                "items": paper_items,
            }
        )
    return {"total": total, "papers": papers, "items": flat}


def _paper_sort_key(item: dict[str, Any]) -> tuple:
    """Unprocessed first, then no-tables, then completed captures; alpha within group."""
    count = int(item.get("capture_count") or 0)
    no_tables = bool(item.get("no_tables"))
    if count > 0:
        group = 2
    elif no_tables:
        group = 1
    else:
        group = 0
    name = (item.get("filename") or "").lower()
    return (group, name)


def list_pdfs(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    stats = capture_stats_by_source_pdf(settings)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    roots: list[Path] = []
    if settings.pdfs_root.is_dir():
        roots.append(settings.pdfs_root)
    # Legacy: also list root-level PDFs not yet moved into pdfs/
    if settings.literature_root.is_dir() and settings.literature_root != settings.pdfs_root:
        roots.append(settings.literature_root)

    for root in roots:
        for p in root.glob("*.pdf"):
            if not p.is_file() or p.name in seen:
                continue
            # Skip PDFs accidentally sitting under _captures or literature-capture
            if root == settings.literature_root and p.parent != settings.literature_root:
                continue
            seen.add(p.name)
            stat = p.stat()
            st = stats.get(p.name) or {}
            items.append(
                {
                    "filename": p.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "capture_count": int(st.get("count") or 0),
                    "pending_extract": int(st.get("pending_extract") or 0),
                    "paper_slug": st.get("paper_slug"),
                    "no_tables": bool(st.get("no_tables")),
                    "title": (st.get("title") or "") or None,
                    "doi": st.get("doi") or None,
                    "si_status": st.get("si_status") or None,
                    "si_file_count": int(st.get("si_file_count") or 0),
                }
            )

    items.sort(key=_paper_sort_key)
    return items


def meta_path(paper_dir: Path) -> Path:
    return paper_dir / "meta.json"


def load_meta(paper_dir: Path) -> dict[str, Any] | None:
    path = meta_path(paper_dir)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(paper_dir: Path, meta: dict[str, Any]) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    path = meta_path(paper_dir)
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def allocate_paper_dir(
    title: str,
    source_pdf: str,
    settings: Settings | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create or reuse a paper capture folder; lock slug after first capture."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    title = clean_display_title(title)
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    # Reuse existing folder for same source PDF if present
    for child in sorted(settings.captures_root.iterdir()) if settings.captures_root.is_dir() else []:
        if not child.is_dir():
            continue
        meta = load_meta(child)
        if meta and meta.get("source_pdf") == source_pdf:
            meta["title"] = title
            meta["updated_at"] = utc_now_iso()
            # Keep existing slug for stable naming after first capture
            save_meta(child, meta)
            return child, meta

    base_slug = make_paper_slug(title)
    slug = base_slug
    n = 2
    while True:
        paper_dir = settings.captures_root / slug
        if not paper_dir.exists():
            break
        meta = load_meta(paper_dir)
        if meta and meta.get("source_pdf") == source_pdf:
            meta["title"] = title
            meta["updated_at"] = utc_now_iso()
            save_meta(paper_dir, meta)
            return paper_dir, meta
        slug = f"{base_slug}_{n}"
        n += 1
        if n > 1000:
            raise HTTPException(status_code=500, detail="无法分配唯一文件夹名")

    meta = {
        "source_pdf": source_pdf,
        "title": title,
        "paper_slug": slug,
        "table_counter": 0,
        "no_tables": False,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    save_meta(paper_dir, meta)
    return paper_dir, meta


def set_no_tables(
    filename: str,
    title: str,
    no_tables: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Mark or unmark a paper as having no extractable tables."""
    settings = settings or get_settings()
    safe_pdf_path(filename, settings)
    paper_dir, meta = allocate_paper_dir(title, filename, settings)
    meta["no_tables"] = bool(no_tables)
    meta["updated_at"] = utc_now_iso()
    save_meta(paper_dir, meta)
    return meta


def find_capture_dirs_for_pdf(
    filename: str,
    settings: Settings | None = None,
) -> list[Path]:
    """Return _captures subdirs whose meta.source_pdf matches this PDF name."""
    settings = settings or get_settings()
    root = settings.captures_root
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta = load_meta(child)
        if meta and meta.get("source_pdf") == filename:
            found.append(child)
    return found


def default_si_meta() -> dict[str, Any]:
    return {
        "status": "idle",
        "message": "",
        "started_at": None,
        "finished_at": None,
        "job_id": None,
        "resolved_title": None,
        "publisher": None,
        "container_title": None,
        "candidates": [],
        "files": [],
        "errors": [],
        "stats": {"candidates": 0, "downloaded": 0, "skipped": 0, "failed": 0},
    }


def ensure_si_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Ensure meta has si block; mutates and returns meta."""
    if not isinstance(meta.get("si"), dict):
        meta["si"] = default_si_meta()
    else:
        base = default_si_meta()
        for k, v in base.items():
            meta["si"].setdefault(k, v)
    return meta


def ensure_paper_session(
    filename: str,
    title: str | None = None,
    settings: Settings | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Create or reuse _captures folder for PDF without requiring prior UI title confirm.
    Prefer existing meta by source_pdf; else allocate with provided/extracted title.
    """
    settings = settings or get_settings()
    safe_pdf_path(filename, settings)
    existing = find_capture_dirs_for_pdf(filename, settings)
    if existing:
        # Prefer newest by updated_at
        def _key(p: Path) -> str:
            m = load_meta(p) or {}
            return str(m.get("updated_at") or m.get("created_at") or "")

        paper_dir = sorted(existing, key=_key, reverse=True)[0]
        meta = load_meta(paper_dir) or {}
        ensure_si_meta(meta)
        if title and title.strip():
            t = clean_display_title(title)
            if t and t != meta.get("title"):
                # Only update display title; keep slug stable
                meta["title"] = t
                meta["updated_at"] = utc_now_iso()
                save_meta(paper_dir, meta)
        else:
            save_meta(paper_dir, meta)
        return paper_dir, meta

    if not title or not str(title).strip():
        from app.services.title import extract_title

        title = extract_title(safe_pdf_path(filename, settings))["title"]
    paper_dir, meta = allocate_paper_dir(title, filename, settings)
    ensure_si_meta(meta)
    save_meta(paper_dir, meta)
    return paper_dir, meta


def si_dir(paper_dir: Path) -> Path:
    d = paper_dir / "si"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_si_file(paper_dir: Path, name: str) -> Path:
    """Resolve a basename under paper_dir/si with path-traversal guard."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if name != Path(name).name:
        raise HTTPException(status_code=400, detail="非法文件名")
    root = (paper_dir / "si").resolve()
    path = (root / name).resolve()
    if not is_under(path, root):
        raise HTTPException(status_code=400, detail="非法路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return path


def delete_paper(
    filename: str,
    *,
    delete_captures: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Delete a PDF from pdfs/ (or literature root) and optionally its capture folders.
    Path-safe: only unlinks under literature_root / captures_root.
    """
    import shutil

    settings = settings or get_settings()
    pdf_path = safe_pdf_path(filename, settings)
    if not is_under(pdf_path, settings.literature_root):
        raise HTTPException(status_code=400, detail="路径越界")

    removed_captures: list[str] = []
    if delete_captures:
        for paper_dir in find_capture_dirs_for_pdf(filename, settings):
            resolved = paper_dir.resolve()
            if not is_under(resolved, settings.captures_root):
                continue
            if resolved.is_dir():
                shutil.rmtree(resolved)
                removed_captures.append(str(resolved))

    pdf_path.unlink()
    return {
        "filename": filename,
        "deleted_pdf": str(pdf_path),
        "deleted_captures": removed_captures,
    }


def get_paper_dir(slug: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if not slug or slug != Path(slug).name or ".." in slug:
        raise HTTPException(status_code=400, detail="非法 slug")
    paper_dir = (settings.captures_root / slug).resolve()
    if not is_under(paper_dir, settings.captures_root):
        raise HTTPException(status_code=400, detail="路径越界")
    if not paper_dir.is_dir():
        raise HTTPException(status_code=404, detail="文献文件夹不存在")
    return paper_dir


def next_table_paths(paper_dir: Path, meta: dict[str, Any]) -> tuple[int, Path, Path, Path]:
    n = int(meta.get("table_counter", 0)) + 1
    slug = meta["paper_slug"]
    stem = f"{slug}-table{n}"
    png = paper_dir / f"{stem}.png"
    csv_path = paper_dir / f"{stem}.csv"
    xlsx = paper_dir / f"{stem}.xlsx"
    return n, png, csv_path, xlsx


def _reviews_map(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    raw = meta.get("reviews") or {}
    return raw if isinstance(raw, dict) else {}


def get_table_review(meta: dict[str, Any] | None, table_id: int) -> dict[str, Any]:
    """Normalized review record for a table. Default status: pending."""
    key = str(int(table_id))
    rec = _reviews_map(meta).get(key) or {}
    if not isinstance(rec, dict):
        rec = {}
    status = rec.get("status") or "pending"
    if status not in ("pending", "passed", "failed"):
        status = "pending"
    return {
        "status": status,
        "note": rec.get("note") or "",
        "reviewed_at": rec.get("reviewed_at"),
        "engine": rec.get("engine"),
        "strategy": rec.get("strategy"),
        "history": rec.get("history") if isinstance(rec.get("history"), list) else [],
    }


def set_table_review(
    meta: dict[str, Any],
    table_id: int,
    *,
    status: str,
    note: str | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    append_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in ("pending", "passed", "failed"):
        raise HTTPException(status_code=400, detail="非法校对状态")
    reviews = dict(_reviews_map(meta))
    key = str(int(table_id))
    prev = dict(reviews.get(key) or {}) if isinstance(reviews.get(key), dict) else {}
    history = list(prev.get("history") or []) if isinstance(prev.get("history"), list) else []
    if append_history:
        history.append(append_history)
        history = history[-20:]
    rec = {
        **prev,
        "status": status,
        "note": (note if note is not None else prev.get("note")) or "",
        "reviewed_at": utc_now_iso() if status != "pending" else prev.get("reviewed_at"),
        "engine": engine if engine is not None else prev.get("engine"),
        "strategy": strategy if strategy is not None else prev.get("strategy"),
        "history": history,
    }
    if status == "pending" and append_history is None:
        # re-queue without wiping history
        rec["reviewed_at"] = None
    reviews[key] = rec
    meta["reviews"] = reviews
    meta["updated_at"] = utc_now_iso()
    return rec


def capture_paths(paper_dir: Path, meta: dict[str, Any], table_id: int) -> dict[str, Path]:
    slug = meta.get("paper_slug", paper_dir.name)
    stem = f"{slug}-table{int(table_id)}"
    return {
        "stem": Path(stem),  # not a real path; keep name via .name hack avoided
        "png": paper_dir / f"{stem}.png",
        "csv": paper_dir / f"{stem}.csv",
        "xlsx": paper_dir / f"{stem}.xlsx",
    }


def is_capture_extracted(
    paper_dir: Path,
    meta: dict[str, Any],
    table_id: int,
    *,
    log: dict[str, Any] | None = None,
) -> bool:
    """True when CSV/XLSX exist or meta marks extracted=true."""
    slug = meta.get("paper_slug", paper_dir.name)
    stem = f"{slug}-table{int(table_id)}"
    if (paper_dir / f"{stem}.csv").is_file() or (paper_dir / f"{stem}.xlsx").is_file():
        return True
    if log is None:
        for c in meta.get("captures") or []:
            if isinstance(c, dict) and int(c.get("table_id") or 0) == int(table_id):
                log = c
                break
    if isinstance(log, dict) and log.get("extracted") is True:
        return True
    return False


def list_captures(paper_dir: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    slug = meta.get("paper_slug", paper_dir.name)
    items: list[dict[str, Any]] = []
    cap_logs = {
        int(c["table_id"]): c
        for c in (meta.get("captures") or [])
        if isinstance(c, dict) and c.get("table_id") is not None
    }
    for png in sorted(paper_dir.glob(f"{slug}-table*.png"), key=lambda p: p.name):
        m = re.search(r"-table(\d+)\.png$", png.name)
        if not m:
            continue
        n = int(m.group(1))
        stem = f"{slug}-table{n}"
        csv_path = paper_dir / f"{stem}.csv"
        xlsx = paper_dir / f"{stem}.xlsx"
        review = get_table_review(meta, n)
        log = cap_logs.get(n) or {}
        extracted = is_capture_extracted(paper_dir, meta, n, log=log)
        # Unextracted screenshots are not in the review queue yet
        review_status = review["status"] if extracted else "unextracted"
        items.append(
            {
                "table_id": n,
                "stem": stem,
                "png": str(png),
                "csv": str(csv_path) if csv_path.is_file() else None,
                "xlsx": str(xlsx) if xlsx.is_file() else None,
                "png_name": png.name,
                "csv_name": csv_path.name if csv_path.is_file() else None,
                "xlsx_name": xlsx.name if xlsx.is_file() else None,
                "page": log.get("page"),
                "engine": review.get("engine") or log.get("engine"),
                "warnings": log.get("warnings") or [],
                "extracted": extracted,
                "review_status": review_status,
                "review_note": review.get("note") or "",
                "reviewed_at": review.get("reviewed_at"),
                "strategy": review.get("strategy"),
            }
        )
    return items


def paper_review_summary(captures: list[dict[str, Any]]) -> dict[str, Any]:
    # Only extracted tables enter review accounting
    extracted = [c for c in captures if c.get("extracted")]
    total = len(extracted)
    passed = sum(1 for c in extracted if c.get("review_status") == "passed")
    failed = sum(1 for c in extracted if c.get("review_status") == "failed")
    pending = total - passed - failed
    all_passed = total > 0 and pending == 0 and failed == 0
    unextracted = len(captures) - total
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "all_passed": all_passed,
        "unextracted": unextracted,
        "marked": len(captures),
    }


def list_review_queue(settings: Settings | None = None) -> dict[str, Any]:
    """
    Queue of captures needing human review.
    Skip papers where every capture is passed (all_passed).
    Within remaining papers, only include non-passed tables (pending + failed).
    """
    settings = settings or get_settings()
    root = settings.captures_root
    papers_out: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    stats = {"papers": 0, "papers_done": 0, "tables": 0, "passed": 0, "failed": 0, "pending": 0}

    if not root.is_dir():
        return {"stats": stats, "papers": [], "queue": []}

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        meta = load_meta(child)
        if not meta:
            continue
        # skip pure session placeholders with no tables / no_tables mark
        if meta.get("no_tables") and not list(child.glob(f"{meta.get('paper_slug', child.name)}-table*.png")):
            continue
        caps = list_captures(child, meta)
        if not caps:
            continue
        extracted_caps = [c for c in caps if c.get("extracted")]
        # Papers with only unextracted PNGs are not in the review workflow yet
        if not extracted_caps:
            continue
        summary = {
            "total": len(extracted_caps),
            "passed": sum(1 for c in extracted_caps if c.get("review_status") == "passed"),
            "failed": sum(1 for c in extracted_caps if c.get("review_status") == "failed"),
            "pending": 0,
            "all_passed": False,
            "unextracted": len(caps) - len(extracted_caps),
            "marked": len(caps),
        }
        summary["pending"] = summary["total"] - summary["passed"] - summary["failed"]
        summary["all_passed"] = (
            summary["total"] > 0 and summary["pending"] == 0 and summary["failed"] == 0
        )

        stats["papers"] += 1
        stats["tables"] += summary["total"]
        stats["passed"] += summary["passed"]
        stats["failed"] += summary["failed"]
        stats["pending"] += summary["pending"]
        if summary["all_passed"]:
            stats["papers_done"] += 1
            papers_out.append(
                {
                    "paper_slug": meta.get("paper_slug") or child.name,
                    "title": meta.get("title") or "",
                    "source_pdf": meta.get("source_pdf") or "",
                    "folder": str(child),
                    **summary,
                    "hidden": True,
                }
            )
            continue

        paper_info = {
            "paper_slug": meta.get("paper_slug") or child.name,
            "title": meta.get("title") or "",
            "source_pdf": meta.get("source_pdf") or "",
            "folder": str(child),
            **summary,
            "hidden": False,
        }
        papers_out.append(paper_info)

        for c in extracted_caps:
            if c.get("review_status") == "passed":
                continue
            queue.append(
                {
                    **c,
                    "paper_slug": paper_info["paper_slug"],
                    "title": paper_info["title"],
                    "source_pdf": paper_info["source_pdf"],
                    "folder": paper_info["folder"],
                    # Prefer failed first so user re-checks re-extracted ones, then pending
                    "_sort": 0 if c.get("review_status") == "failed" else 1,
                }
            )

    queue.sort(
        key=lambda x: (
            x.get("_sort", 1),
            (x.get("title") or "").lower(),
            int(x.get("table_id") or 0),
        )
    )
    for q in queue:
        q.pop("_sort", None)

    return {"stats": stats, "papers": papers_out, "queue": queue}


def load_capture_matrix(csv_path: Path, max_rows: int = 200) -> list[list[str]]:
    if not csv_path.is_file():
        return []
    try:
        import pandas as pd

        df = pd.read_csv(csv_path, header=None, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        head = df.head(max_rows)
        return [[("" if v is None else str(v)) for v in row] for row in head.values.tolist()]
    except Exception:
        try:
            import csv

            rows: list[list[str]] = []
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                for i, row in enumerate(csv.reader(f)):
                    if i >= max_rows:
                        break
                    rows.append([str(c) for c in row])
            return rows
        except Exception:
            return []
