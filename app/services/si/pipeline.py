"""End-to-end SI discovery + download for one paper."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.paths import (
    ensure_paper_session,
    ensure_si_meta,
    load_meta,
    safe_pdf_path,
    save_meta,
    utc_now_iso,
)
from app.services.si.candidates import filter_candidates
from app.services.si.doi_extract import extract_dois, normalize_doi
from app.services.si.download import download_candidate
from app.services.si.jobs import start_job, update_job
from app.services.si.publishers import discover_publisher_links
from app.services.si.resolve import resolve_doi

_meta_locks: dict[str, threading.Lock] = {}
_meta_locks_guard = threading.Lock()


def _slug_lock(slug: str) -> threading.Lock:
    with _meta_locks_guard:
        if slug not in _meta_locks:
            _meta_locks[slug] = threading.Lock()
        return _meta_locks[slug]


def _save(paper_dir: Path, meta: dict[str, Any]) -> None:
    meta["updated_at"] = utc_now_iso()
    save_meta(paper_dir, meta)


def _set_status(
    paper_dir: Path,
    meta: dict[str, Any],
    status: str,
    message: str = "",
    **si_fields: Any,
) -> None:
    ensure_si_meta(meta)
    meta["si"]["status"] = status
    if message:
        meta["si"]["message"] = message
    for k, v in si_fields.items():
        meta["si"][k] = v
    _save(paper_dir, meta)


def run_si_worker(job_id: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    filename = payload["filename"]
    title = payload.get("title")
    force = bool(payload.get("force"))
    override_doi = payload.get("doi")
    override_url = payload.get("url")

    paper_dir, meta = ensure_paper_session(filename, title, settings)
    slug = meta.get("paper_slug") or paper_dir.name
    lock = _slug_lock(slug)

    with lock:
        meta = load_meta(paper_dir) or meta
        ensure_si_meta(meta)
        meta["si"]["job_id"] = job_id
        meta["si"]["started_at"] = utc_now_iso()
        meta["si"]["finished_at"] = None
        meta["si"]["errors"] = []
        if force:
            # keep existing files; re-resolve
            pass
        _set_status(paper_dir, meta, "running", "提取 DOI…", job_id=job_id)
        update_job(job_id, progress="doi", status="running")

    try:
        pdf_path = safe_pdf_path(filename, settings)
        doi = None
        doi_source = None

        if override_doi:
            doi = normalize_doi(override_doi)
            doi_source = "manual"
        elif meta.get("doi") and not force:
            doi = normalize_doi(str(meta["doi"]))
            doi_source = meta.get("doi_source") or "meta"
        if not doi:
            extracted = extract_dois(pdf_path)
            doi = extracted.get("doi")
            doi_source = extracted.get("doi_source")

        with lock:
            meta = load_meta(paper_dir) or meta
            if doi:
                meta["doi"] = doi
                meta["doi_source"] = doi_source
                meta["url"] = meta.get("url") or f"https://doi.org/{doi}"
                if not meta.get("url_source"):
                    meta["url_source"] = "doi_org"
            if override_url:
                meta["url"] = override_url.strip()
                meta["url_source"] = "manual"
            _set_status(
                paper_dir,
                meta,
                "running",
                f"解析 Crossref… DOI={doi or '无'}",
                job_id=job_id,
            )

        if not doi and not override_url:
            with lock:
                meta = load_meta(paper_dir) or meta
                _set_status(
                    paper_dir,
                    meta,
                    "failed",
                    "未找到 DOI，请在界面填写 DOI 或文章页 URL 后重试",
                    finished_at=utc_now_iso(),
                    job_id=job_id,
                )
            update_job(job_id, status="done", progress="failed_no_doi")
            return

        raw_links: list[dict[str, Any]] = []
        resolved_title = None
        publisher = None
        container = None
        landing = meta.get("url")

        if doi:
            update_job(job_id, progress="crossref")
            try:
                resolved = resolve_doi(doi, settings)
                resolved_title = resolved.get("title")
                publisher = resolved.get("publisher")
                container = resolved.get("container_title")
                landing = resolved.get("landing_url") or landing
                raw_links.extend(resolved.get("raw_links") or [])
            except Exception as e:
                with lock:
                    meta = load_meta(paper_dir) or meta
                    ensure_si_meta(meta)
                    meta["si"]["errors"].append(
                        {"stage": "crossref", "url": None, "code": None, "detail": str(e)}
                    )
                    _set_status(
                        paper_dir,
                        meta,
                        "running",
                        f"Crossref 失败: {e}；继续尝试其他来源…",
                        job_id=job_id,
                    )

        if override_url:
            raw_links.append(
                {
                    "url": override_url.strip(),
                    "content_type": None,
                    "intended": "manual",
                    "source": "manual",
                }
            )

        # Phase 2 publisher hooks (no-op in P1)
        try:
            pub_links = discover_publisher_links(
                doi=doi,
                landing_url=landing,
                publisher=publisher,
                settings=settings,
            )
            raw_links.extend(pub_links or [])
        except Exception:
            pass

        max_files = int(settings.si_max_files_per_paper or 15)
        candidates = filter_candidates(raw_links, max_files=max_files)
        selected = [c for c in candidates if c.get("selected")]

        with lock:
            meta = load_meta(paper_dir) or meta
            ensure_si_meta(meta)
            if resolved_title:
                meta["si"]["resolved_title"] = resolved_title
            if publisher:
                meta["si"]["publisher"] = publisher
            if container:
                meta["si"]["container_title"] = container
            if landing and not meta.get("url"):
                meta["url"] = landing
                meta["url_source"] = meta.get("url_source") or "crossref"
            meta["si"]["candidates"] = candidates
            meta["si"]["stats"] = {
                "candidates": len(candidates),
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
            }
            _set_status(
                paper_dir,
                meta,
                "running",
                f"找到 {len(selected)} 个 SI 候选，开始下载…",
                job_id=job_id,
            )

        if not selected:
            with lock:
                meta = load_meta(paper_dir) or meta
                _set_status(
                    paper_dir,
                    meta,
                    "no_si",
                    "已解析文献，但未找到可下载的开放补充材料链接（可手动填 SI URL 重试）",
                    finished_at=utc_now_iso(),
                    job_id=job_id,
                )
            update_job(job_id, status="done", progress="no_si")
            return

        existing_urls = set()
        with lock:
            meta = load_meta(paper_dir) or meta
            for f in meta.get("si", {}).get("files") or []:
                u = (f.get("source_url") or "").split("#")[0].rstrip("/")
                if u:
                    existing_urls.add(u)

        downloaded = 0
        failed = 0
        skipped = 0
        paywalled_n = 0
        files_acc: list[dict[str, Any]] = []
        with lock:
            meta = load_meta(paper_dir) or meta
            files_acc = list((meta.get("si") or {}).get("files") or [])

        for i, cand in enumerate(selected, start=1):
            update_job(job_id, progress=f"download {i}/{len(selected)}")
            result = download_candidate(
                paper_dir,
                cand,
                index=i,
                settings=settings,
                existing_urls=existing_urls,
            )
            with lock:
                meta = load_meta(paper_dir) or meta
                ensure_si_meta(meta)
                if result.get("skipped"):
                    skipped += 1
                elif result.get("error"):
                    failed += 1
                    if result.get("paywalled"):
                        paywalled_n += 1
                    meta["si"]["errors"].append(
                        {
                            "stage": "download",
                            "url": result.get("url"),
                            "code": result.get("code"),
                            "detail": result.get("detail"),
                        }
                    )
                else:
                    downloaded += 1
                    files_acc.append(result)
                    existing_urls.add((result.get("source_url") or "").split("#")[0].rstrip("/"))
                    meta["si"]["files"] = files_acc
                meta["si"]["stats"] = {
                    "candidates": len(candidates),
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "failed": failed,
                }
                _set_status(
                    paper_dir,
                    meta,
                    "running",
                    f"下载进度 {i}/{len(selected)}（成功 {downloaded}，失败 {failed}）",
                    job_id=job_id,
                )

        # Final status
        with lock:
            meta = load_meta(paper_dir) or meta
            ensure_si_meta(meta)
            meta["si"]["files"] = files_acc
            meta["si"]["finished_at"] = utc_now_iso()
            if downloaded > 0 and failed == 0:
                status, msg = "ok", f"已下载 {downloaded} 个补充材料文件"
            elif downloaded > 0:
                status, msg = "partial", f"部分成功：下载 {downloaded}，失败 {failed}"
            elif paywalled_n > 0 and paywalled_n == failed:
                status, msg = "paywalled", "疑似付费墙或需登录，未能下载开放 SI"
            else:
                status, msg = "failed", f"下载失败（{failed}），请检查 DOI 或手动提供 SI 链接"
            _set_status(paper_dir, meta, status, msg, job_id=job_id)
        update_job(job_id, status="done", progress=status)

    except Exception as e:
        with lock:
            meta = load_meta(paper_dir) or meta
            ensure_si_meta(meta)
            meta["si"]["errors"].append(
                {"stage": "pipeline", "url": None, "code": None, "detail": str(e)}
            )
            _set_status(
                paper_dir,
                meta,
                "failed",
                f"SI 任务异常: {e}",
                finished_at=utc_now_iso(),
                job_id=job_id,
            )
        update_job(job_id, status="error", error=str(e), progress="error")
        raise


def enqueue_si_run(
    *,
    filename: str,
    title: str | None = None,
    doi: str | None = None,
    url: str | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.si_enabled:
        paper_dir, meta = ensure_paper_session(filename, title, settings)
        ensure_si_meta(meta)
        meta["si"]["status"] = "disabled"
        meta["si"]["message"] = "SI 功能已在配置中关闭"
        save_meta(paper_dir, meta)
        return {
            "job_id": None,
            "paper_slug": meta.get("paper_slug"),
            "si_status": "disabled",
            "message": meta["si"]["message"],
        }

    paper_dir, meta = ensure_paper_session(filename, title, settings)
    ensure_si_meta(meta)

    if doi:
        nd = normalize_doi(doi)
        if nd:
            meta["doi"] = nd
            meta["doi_source"] = "manual"
            meta["url"] = meta.get("url") or f"https://doi.org/{nd}"
            meta["url_source"] = meta.get("url_source") or "doi_org"
    if url:
        meta["url"] = url.strip()
        meta["url_source"] = "manual"
        save_meta(paper_dir, meta)

    st = meta["si"].get("status")
    files = meta["si"].get("files") or []
    if not force and st in ("queued", "running"):
        from app.services.si.jobs import job_for_pdf

        j = job_for_pdf(filename)
        return {
            "job_id": (j or {}).get("id") or meta["si"].get("job_id"),
            "paper_slug": meta.get("paper_slug"),
            "si_status": st,
            "message": "任务进行中",
        }
    if not force and st == "ok" and files:
        return {
            "job_id": None,
            "paper_slug": meta.get("paper_slug"),
            "si_status": "ok",
            "message": "已有 SI 文件，使用 force=true 可重跑",
        }

    meta["si"]["status"] = "queued"
    meta["si"]["message"] = "已加入队列"
    meta["si"]["started_at"] = utc_now_iso()
    save_meta(paper_dir, meta)

    job = start_job(
        filename,
        run_si_worker,
        {
            "filename": filename,
            "title": title or meta.get("title"),
            "doi": doi,
            "url": url,
            "force": force,
        },
    )
    meta["si"]["job_id"] = job["id"]
    save_meta(paper_dir, meta)
    return {
        "job_id": job["id"],
        "paper_slug": meta.get("paper_slug"),
        "si_status": "queued",
        "message": "已排队",
    }


def status_for(
    *,
    filename: str | None = None,
    slug: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    from app.paths import get_paper_dir
    from app.services.si.jobs import get_job, job_for_pdf

    settings = settings or get_settings()
    paper_dir = None
    meta = None
    if slug:
        paper_dir = get_paper_dir(slug, settings)
        meta = load_meta(paper_dir)
        filename = (meta or {}).get("source_pdf") or filename
    elif filename:
        paper_dir, meta = ensure_paper_session(filename, None, settings)
    else:
        raise ValueError("filename or slug required")

    meta = meta or {}
    ensure_si_meta(meta)
    job = job_for_pdf(filename) if filename else None
    if not job and meta["si"].get("job_id"):
        job = get_job(str(meta["si"]["job_id"]))

    return {
        "filename": filename or meta.get("source_pdf"),
        "paper_slug": meta.get("paper_slug"),
        "title": meta.get("title"),
        "doi": meta.get("doi"),
        "doi_source": meta.get("doi_source"),
        "url": meta.get("url"),
        "si": meta.get("si"),
        "files": (meta.get("si") or {}).get("files") or [],
        "job": job,
    }
