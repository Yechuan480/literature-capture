"""Fallback: scrape any landing HTML for SI-looking download links."""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.services.si.publishers.html_util import (
    extract_hrefs,
    fetch_html,
    link_item,
    resolve_landing,
)

SI_HINT = re.compile(
    r"(supplement|suppl(?:ementary)?|supporting[\s_-]?info|supporting[\s_-]?information|"
    r"/esm/|moesm|mmc\d*|appendix|additional[\s_-]?file|si[_-]?file|edata|"
    r"downloadSupplement|suppl_file|e-?component)",
    re.I,
)
FILE_EXT = re.compile(r"\.(pdf|zip|xlsx?|csv|docx?|pptx?|txt)(\?|$)", re.I)
MAIN_HINT = re.compile(
    r"(full[\s_-]?text|/pdfft|/pdfdirect/|main\.pdf|/content/pdf/[^/]+\.pdf$)",
    re.I,
)


class GenericLandingAdapter:
    """Always eligible as last-resort when a landing URL exists."""

    name = "generic"

    def match(self, url: str, doi: str, publisher: str) -> bool:
        return bool(url or doi)

    def discover(self, client: Any, doi: str, landing_url: str) -> list[dict[str, Any]]:
        settings: Settings | None = getattr(client, "settings", None)
        final = resolve_landing(doi, landing_url, settings=settings) or landing_url
        if not final:
            return []
        abs_url, html, _code = fetch_html(final, settings=settings)
        if not html:
            return []
        base = abs_url or final
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for href in extract_hrefs(html, base):
            if not _looks_si(href):
                continue
            key = href.split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            out.append(link_item(href, source="generic:html"))
        return out


def _looks_si(url: str) -> bool:
    u = url or ""
    if MAIN_HINT.search(u) and not SI_HINT.search(u):
        return False
    if SI_HINT.search(u) and (FILE_EXT.search(u) or "download" in u.lower() or "suppl" in u.lower()):
        return True
    if FILE_EXT.search(u) and SI_HINT.search(u):
        return True
    return False
