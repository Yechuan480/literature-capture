"""ACS Publications SI discovery (best-effort; many pages return 403 to bots)."""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.services.si.http_util import request
from app.services.si.publishers.html_util import (
    extract_hrefs,
    fetch_html,
    host_matches,
    link_item,
    publisher_blob,
    resolve_landing,
)

SI_RE = re.compile(
    r"(/doi/suppl/|/suppl_file/|supporting[\s_-]?info|supplementary|"
    r"acs.org/.+\.(pdf|html|zip|xlsx)|/doi/pdf/.*supp|/doi/suppl/)",
    re.I,
)
MAIN_RE = re.compile(r"/doi/pdf/|/doi/pdfdirect/", re.I)


class ACSAdapter:
    name = "acs"

    def match(self, url: str, doi: str, publisher: str) -> bool:
        blob = publisher_blob(publisher, url, doi)
        if "american chemical society" in blob or "acs publications" in blob:
            return True
        if url and host_matches(url, "pubs.acs.org", "acs.org"):
            return True
        if doi and doi.lower().startswith("10.1021/"):
            return True
        return False

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
                    f"https://pubs.acs.org/doi/{doi}",
                    f"https://pubs.acs.org/doi/full/{doi}",
                    f"https://pubs.acs.org/doi/abs/{doi}",
                    f"https://pubs.acs.org/doi/suppl/{doi}",
                    f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/index.html",
                ]
            )

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in pages:
            abs_url, html, code = fetch_html(page, settings=settings)
            if code in (401, 403):
                continue
            if not html:
                continue
            base = abs_url or page
            for href in extract_hrefs(html, base):
                if not _is_acs_si(href):
                    continue
                key = href.split("#")[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                out.append(link_item(href, source="acs:html"))
            if out:
                break

        # Heuristic SI PDF probes when HTML blocked (some SI PDFs are open)
        if doi and not out:
            stem = doi.split("/")[-1]
            guesses = [
                f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{stem}_si_001.pdf",
                f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{stem}.pdf",
                f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/si.pdf",
            ]
            for g in guesses:
                if _probe_pdf(g, settings=settings):
                    out.append(
                        link_item(g, source="acs:probe", content_type="application/pdf")
                    )
        return out


def _probe_pdf(url: str, *, settings: Settings | None) -> bool:
    try:
        r = request("GET", url, settings=settings, headers={"Range": "bytes=0-8"})
    except Exception:
        return False
    return r.status_code in (200, 206) and r.content.startswith(b"%PDF")


def _is_acs_si(url: str) -> bool:
    u = url or ""
    if MAIN_RE.search(u) and not re.search(r"suppl|supporting", u, re.I):
        return False
    if SI_RE.search(u):
        return True
    if re.search(r"\.(pdf|zip|xlsx|csv|html)(\?|$)", u, re.I) and re.search(
        r"(suppl|supporting|appendix)", u, re.I
    ):
        return True
    return False
