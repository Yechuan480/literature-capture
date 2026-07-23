"""OA-only PDF fetch for Scholar inbox items (no paywall bypass)."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from app.config import get_settings
from app.paths import utc_now_iso
from app.services import library_store as lib
from app.services.scholar import inbox as inbox_store
from app.services.si.download import looks_like_html_login
from app.services.si.http_util import request

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_executor: ThreadPoolExecutor | None = None
_exec_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _exec_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sch")
        return _executor


def _safe_filename(title: str, doi: str | None = None) -> str:
    base = (title or "paper").strip()
    base = _ILLEGAL.sub("_", base)
    base = re.sub(r"\s+", " ", base).strip(" ._")[:80] or "paper"
    if doi:
        d = doi.replace("/", "_")
        base = f"{base}_{d}"[:100]
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    return base


def _is_pdf_bytes(body: bytes, ct: str | None) -> bool:
    if body[:5] == b"%PDF-":
        return True
    c = (ct or "").lower()
    return "application/pdf" in c or "application/x-pdf" in c


def _try_download(url: str, dest: Path) -> dict[str, Any]:
    """Download URL if it is a real PDF. Never follows login HTML as success."""
    if not url or not url.startswith("http"):
        return {"ok": False, "status": "no_pdf", "error": "无有效链接"}
    try:
        r = request("GET", url)
    except Exception as e:
        return {"ok": False, "status": "failed", "error": str(e)}

    if r.status_code in (401, 403):
        return {"ok": False, "status": "paywalled", "error": f"HTTP {r.status_code}"}
    if r.status_code >= 400:
        return {"ok": False, "status": "failed", "error": f"HTTP {r.status_code}"}

    ct = r.headers.get("content-type")
    body = r.content or b""
    if looks_like_html_login(ct, body[:12000]):
        return {"ok": False, "status": "paywalled", "error": "html_or_login_page"}
    if not _is_pdf_bytes(body, ct):
        return {"ok": False, "status": "no_pdf", "error": f"非 PDF（{ct or 'unknown'}）"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    # avoid overwrite
    out = dest
    if out.is_file():
        stem = out.stem
        for n in range(2, 50):
            cand = out.with_name(f"{stem}_{n}.pdf")
            if not cand.is_file():
                out = cand
                break
    out.write_bytes(body)
    return {"ok": True, "status": "fetched", "path": str(out), "filename": out.name}


def _unpaywall_pdf(doi: str) -> str | None:
    """Best-effort Unpaywall OA location (no API key required for low volume mailto)."""
    doi = (doi or "").strip()
    if not doi:
        return None
    settings = get_settings()
    mail = (getattr(settings, "si_crossref_mailto", None) or "literature-capture@local").strip()
    url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(mail)}"
    try:
        r = request("GET", url, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            return None
        data = r.json()
        loc = data.get("best_oa_location") or {}
        pdf = loc.get("url_for_pdf") or loc.get("url")
        if pdf and str(pdf).startswith("http"):
            return str(pdf)
        # any oa location with pdf
        for loc in data.get("oa_locations") or []:
            pdf = loc.get("url_for_pdf")
            if pdf and str(pdf).startswith("http"):
                return str(pdf)
    except Exception:
        return None
    return None


def _candidate_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for k in ("pdf_link", "link"):
        u = item.get(k)
        if u and str(u).startswith("http"):
            urls.append(str(u))
    doi = item.get("doi")
    if doi:
        urls.append(f"https://doi.org/{doi}")
        oa = _unpaywall_pdf(str(doi))
        if oa:
            urls.insert(0, oa)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        key = u.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def fetch_one(item: dict[str, Any], *, day: str | None = None) -> dict[str, Any]:
    """Try OA PDF for one inbox item; save under pdfs/."""
    iid = item.get("id") or ""
    inbox_store.patch_item(iid, {"status": "fetching", "error": None}, day=day)
    settings = get_settings()
    pdfs_root: Path = settings.pdfs_root
    fname = _safe_filename(item.get("title") or "paper", item.get("doi"))
    dest = pdfs_root / fname

    last_err = "no_pdf"
    last_status = "no_pdf"
    for url in _candidate_urls(item):
        # skip pure landing pages that we know aren't direct PDF unless doi.org/unpaywall
        host = urlparse(url).netloc.lower()
        if "scholar.google." in host and ".pdf" not in url.lower():
            continue
        result = _try_download(url, dest)
        if result.get("ok"):
            filename = result["filename"]
            inbox_store.patch_item(
                iid,
                {
                    "status": "fetched",
                    "filename": filename,
                    "error": None,
                    "fetched_at": utc_now_iso(),
                    "source_url": url,
                },
                day=day,
            )
            try:
                lib.sync_from_disk()
                cols = lib.list_collections()
                today_col = next((c for c in cols if c.get("name") == "今日导入"), None)
                if not today_col:
                    try:
                        today_col = lib.create_collection("今日导入")
                    except ValueError:
                        cols = lib.list_collections()
                        today_col = next(
                            (c for c in cols if c.get("name") == "今日导入"), None
                        )
                col_id = (today_col or {}).get("id")
                item_lib = lib.get_item(filename, sync=False) or {}
                cids = list(item_lib.get("collection_ids") or [])
                if col_id and col_id not in cids:
                    cids.append(col_id)
                patch: dict[str, Any] = {
                    "status": "unread",
                    "collection_ids": cids,
                }
                if item.get("title"):
                    patch["title_override"] = item["title"]
                lib.patch_item(filename, patch)
            except Exception:
                pass
            return {"ok": True, "id": iid, "filename": filename, "status": "fetched"}
        last_status = result.get("status") or "failed"
        last_err = result.get("error") or last_status

    inbox_store.patch_item(
        iid,
        {"status": last_status, "error": last_err, "filename": None},
        day=day,
    )
    return {"ok": False, "id": iid, "status": last_status, "error": last_err}


def start_fetch_jobs(ids: list[str] | None = None, *, day: str | None = None) -> dict[str, Any]:
    """Enqueue fetch for kept items (or explicit ids)."""
    day = day or None
    data = inbox_store.get_day(day)
    items = data["items"]
    if ids:
        idset = set(ids)
        targets = [it for it in items if it.get("id") in idset]
    else:
        targets = [
            it
            for it in items
            if it.get("status") in ("kept", "failed", "no_pdf", "paywalled")
            and not it.get("filename")
        ]
    job_id = utc_now_iso()
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "total": len(targets),
            "done": 0,
            "results": [],
        }

    def _run() -> None:
        results = []
        for it in targets:
            try:
                r = fetch_one(it, day=day)
            except Exception as e:
                r = {"ok": False, "id": it.get("id"), "error": str(e), "status": "failed"}
                try:
                    inbox_store.patch_item(
                        it.get("id") or "",
                        {"status": "failed", "error": str(e)},
                        day=day,
                    )
                except Exception:
                    pass
            results.append(r)
            with _jobs_lock:
                j = _jobs.get(job_id)
                if j:
                    j["done"] = len(results)
                    j["results"] = list(results)
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j:
                j["status"] = "done"
                j["results"] = results

    if targets:
        _pool().submit(_run)
    else:
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
    return {"job_id": job_id, "queued": len(targets)}


def get_fetch_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None
