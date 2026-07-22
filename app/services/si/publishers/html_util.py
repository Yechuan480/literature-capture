"""Shared HTML fetch + link extraction for publisher adapters."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse, unquote

from app.config import Settings, get_settings
from app.services.si.http_util import request

HREF_RE = re.compile(
    r"""(?:href|data-url|data-doi|data-document-url)\s*=\s*["']([^"']+)["']""",
    re.I,
)
# Also catch bare SI CDN paths in scripts/JSON
URL_IN_TEXT_RE = re.compile(
    r"""https?://[^\s"'<>\\]+(?:mmc\d*|moesm|suppl|supporting|appendix|/esm/|e-?component)[^\s"'<>\\]*""",
    re.I,
)
MAX_HTML_BYTES = 2_500_000


def absolutize(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "data:")):
        return None
    try:
        return urljoin(base, href)
    except Exception:
        return None


def fetch_html(
    url: str,
    *,
    settings: Settings | None = None,
    accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
) -> tuple[str | None, str | None, int | None]:
    """
    GET page body as text. Returns (final_url, html_text, status_code).
    On failure returns (None, None, code_or_None).
    """
    settings = settings or get_settings()
    try:
        r = request(
            "GET",
            url,
            settings=settings,
            headers={
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    except Exception:
        return None, None, None
    if r.status_code >= 400:
        return str(r.url), None, r.status_code
    ct = (r.headers.get("content-type") or "").lower()
    # Some SI endpoints return binary; caller may still want URL from redirects
    body = r.content[:MAX_HTML_BYTES]
    if "pdf" in ct or "zip" in ct or "octet-stream" in ct:
        return str(r.url), None, r.status_code
    try:
        text = body.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        text = body.decode("utf-8", errors="replace")
    return str(r.url), text, r.status_code


def resolve_landing(
    doi: str | None,
    landing_url: str | None,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Prefer landing_url; else follow https://doi.org/{doi}."""
    settings = settings or get_settings()
    if landing_url and landing_url.startswith("http"):
        # If already a publisher host, use as-is; doi.org still OK (redirects)
        final, _, code = fetch_html(landing_url, settings=settings)
        if final and code and code < 400:
            return final
        if landing_url and "doi.org" not in landing_url:
            return landing_url
    if doi:
        final, _, code = fetch_html(f"https://doi.org/{doi}", settings=settings)
        if final:
            return final
        return f"https://doi.org/{doi}"
    return landing_url


def extract_hrefs(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for m in HREF_RE.finditer(html or ""):
        abs_u = absolutize(base_url, m.group(1))
        if not abs_u:
            continue
        key = abs_u.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        urls.append(abs_u)
    for m in URL_IN_TEXT_RE.finditer(html or ""):
        u = m.group(0).rstrip(").,;]'\"\\")
        u = unquote(u) if "%" in u[:20] else u
        key = u.split("#")[0].rstrip("/")
        if key in seen:
            continue
        if not key.startswith("http"):
            continue
        seen.add(key)
        urls.append(u)
    return urls


def link_item(
    url: str,
    *,
    source: str,
    content_type: str | None = None,
    intended: str = "supplementary",
) -> dict[str, Any]:
    return {
        "url": url,
        "content_type": content_type,
        "intended": intended,
        "source": source,
    }


def host_matches(url: str, *needles: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(n in host for n in needles)


def publisher_blob(publisher: str | None, url: str | None, doi: str | None) -> str:
    parts = [publisher or "", url or "", doi or ""]
    return " ".join(parts).lower()
