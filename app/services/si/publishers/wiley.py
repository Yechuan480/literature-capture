"""Wiley Online Library SI discovery from public article HTML."""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.services.si.publishers.html_util import (
    extract_hrefs,
    fetch_html,
    host_matches,
    link_item,
    publisher_blob,
    resolve_landing,
)

SI_RE = re.compile(
    r"(downloadSupplement|suppl_file|/doi/suppl/|/action/downloadSupplement|"
    r"supporting[\s_-]?information|supplementary|/asset/supinfo/|"
    r"onlinelibrary\.wiley\.com/.+\.(pdf|zip|xlsx|docx))",
    re.I,
)
MAIN_RE = re.compile(r"/doi/pdfdirect/|/doi/pdf/|/epdf/|/pdfdirect/", re.I)


class WileyAdapter:
    name = "wiley"

    def match(self, url: str, doi: str, publisher: str) -> bool:
        blob = publisher_blob(publisher, url, doi)
        if any(x in blob for x in ("wiley", "blackwell", "maps", "meteoritics")):
            # maps publisher often Wiley
            if "wiley" in blob or "blackwell" in blob:
                return True
        if url and host_matches(
            url, "wiley.com", "onlinelibrary.wiley.com", "doi.wiley.com"
        ):
            return True
        if doi and doi.lower().startswith(
            ("10.1002/", "10.1111/", "10.1029/")  # AGU also Wiley sometimes
        ):
            # 10.1029 is AGU — often Wiley Online
            return doi.lower().startswith(("10.1002/", "10.1111/"))
        return "wiley" in blob

    def discover(self, client: Any, doi: str, landing_url: str) -> list[dict[str, Any]]:
        settings: Settings | None = getattr(client, "settings", None)
        final = resolve_landing(doi, landing_url, settings=settings) or landing_url
        pages: list[str] = []
        if final:
            pages.append(final)
        if doi:
            pages.extend(
                [
                    f"https://doi.org/{doi}",
                    f"https://onlinelibrary.wiley.com/doi/{doi}",
                    f"https://onlinelibrary.wiley.com/doi/full/{doi}",
                    f"https://onlinelibrary.wiley.com/doi/abs/{doi}",
                    f"https://onlinelibrary.wiley.com/doi/suppl/{doi}",
                ]
            )

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in pages:
            abs_url, html, _code = fetch_html(page, settings=settings)
            if not html:
                # still try known supplement endpoint patterns without HTML
                continue
            base = abs_url or page
            for href in extract_hrefs(html, base):
                if not _is_wiley_si(href):
                    continue
                key = href.split("#")[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                out.append(link_item(href, source="wiley:html"))
            if out:
                break
        return out


def _is_wiley_si(url: str) -> bool:
    u = url or ""
    if MAIN_RE.search(u) and not SI_RE.search(u):
        return False
    if SI_RE.search(u):
        return True
    if re.search(r"\.(pdf|zip|xlsx|csv|docx)(\?|$)", u, re.I) and re.search(
        r"(suppl|supporting|appendix)", u, re.I
    ):
        return True
    return False
