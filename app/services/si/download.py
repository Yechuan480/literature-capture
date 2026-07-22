"""Download SI candidate files into paper_dir/si/."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import Settings, get_settings
from app.paths import si_dir, utc_now_iso
from app.services.si.http_util import request

ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
LOGIN_MARKERS = re.compile(
    r"(sign[\s-]?in|log[\s-]?in|purchase|subscribe|access[\s-]?denied|"
    r"cloudflare|captcha|create[\s-]?account|institutional[\s-]?login)",
    re.I,
)


def _safe_name(name: str, max_len: int = 120) -> str:
    s = ILLEGAL.sub("_", (name or "file").strip()) or "file"
    s = re.sub(r"_+", "_", s).strip("._ ")
    if len(s) > max_len:
        stem, dot, ext = s.rpartition(".")
        if dot and len(ext) <= 8:
            s = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            s = s[:max_len]
    return s or "file"


def filename_from_response(url: str, headers: dict[str, str], kind: str) -> str:
    cd = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m:
        return _safe_name(unquote(m.group(1).strip()))
    path = unquote(urlparse(url).path)
    base = Path(path).name
    if base and base not in ("", "/", "."):
        return _safe_name(base)
    ext = {
        "si_pdf": ".pdf",
        "si_zip": ".zip",
        "si_xlsx": ".xlsx",
        "si_csv": ".csv",
        "si_html": ".html",
        "si_doc": ".docx",
    }.get(kind, ".bin")
    return _safe_name(f"si{ext}")


def looks_like_html_login(content_type: str | None, head: bytes) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct or head.lstrip()[:1] in (b"<", b"\xef"):
        try:
            text = head[:8000].decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        if "<html" in text.lower() or "<!doctype" in text.lower():
            if LOGIN_MARKERS.search(text):
                return True
            # Generic HTML without SI binary → reject as paywall/page
            return True
    return False


def download_candidate(
    paper_dir: Path,
    cand: dict[str, Any],
    *,
    index: int,
    settings: Settings | None = None,
    existing_urls: set[str] | None = None,
) -> dict[str, Any]:
    """
    Download one candidate. Returns file record or error dict.
    """
    settings = settings or get_settings()
    url = cand["url"]
    if existing_urls and url.split("#")[0].rstrip("/") in existing_urls:
        return {
            "skipped": True,
            "url": url,
            "detail": "already_downloaded",
        }

    max_bytes = int(settings.si_max_file_mb * 1024 * 1024)
    try:
        r = request("GET", url, settings=settings)
    except Exception as e:
        return {"error": True, "url": url, "code": None, "detail": str(e), "paywalled": False}

    if r.status_code in (401, 403):
        return {
            "error": True,
            "url": url,
            "code": r.status_code,
            "detail": "forbidden_or_paywall",
            "paywalled": True,
        }
    if r.status_code >= 400:
        return {
            "error": True,
            "url": url,
            "code": r.status_code,
            "detail": f"http_{r.status_code}",
            "paywalled": False,
        }

    ct = r.headers.get("content-type")
    body = r.content
    if looks_like_html_login(ct, body[:12000]):
        return {
            "error": True,
            "url": url,
            "code": r.status_code,
            "detail": "html_or_login_page",
            "paywalled": True,
        }
    if len(body) > max_bytes:
        return {
            "error": True,
            "url": url,
            "code": r.status_code,
            "detail": f"file_too_large_{len(body)}",
            "paywalled": False,
        }
    if len(body) < 32:
        return {
            "error": True,
            "url": url,
            "code": r.status_code,
            "detail": "empty_body",
            "paywalled": False,
        }

    kind = cand.get("kind") or "unknown"
    name = filename_from_response(str(r.url), dict(r.headers), kind)
    name = f"{index:02d}_{name}"
    dest_dir = si_dir(paper_dir)
    dest = dest_dir / name
    n = 2
    while dest.exists():
        stem = Path(name).stem
        suf = Path(name).suffix
        dest = dest_dir / f"{stem}_{n}{suf}"
        n += 1
        if n > 100:
            return {"error": True, "url": url, "detail": "name_collision", "paywalled": False}

    dest.write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    return {
        "name": dest.name,
        "relpath": f"si/{dest.name}",
        "bytes": len(body),
        "content_type": ct,
        "source_url": url,
        "kind": kind,
        "sha256": sha,
        "downloaded_at": utc_now_iso(),
    }
