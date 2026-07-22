"""Springer / Nature / BMC SI discovery from public article HTML."""

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

SI_PATH = re.compile(
    r"(/esm/|moesm|mediaobjects|supplement|suppl|supporting|/static-content\.springer|"
    r"assets\.pubpub|article-assets|/doi/pdf/.*[Ss]upp|/articles/.+/MOESM|"
    r"additional[\s_-]?files?|/download/suppl|/content/pdf/.*[Ee][Ss][Mm])",
    re.I,
)
MAIN_PDF = re.compile(
    r"/content/pdf/[^/]+\.pdf$|/articles/[^/]+\.pdf$|fulltext\.pdf|main\.pdf",
    re.I,
)


class SpringerNatureAdapter:
    name = "springer_nature"

    def match(self, url: str, doi: str, publisher: str) -> bool:
        blob = publisher_blob(publisher, url, doi)
        keys = (
            "springer",
            "nature",
            "biomed central",
            "bmc",
            "palgrave",
            "scientific reports",
            "nature publishing",
        )
        if any(k in blob for k in keys):
            return True
        if url and host_matches(
            url,
            "springer.com",
            "springeropen.com",
            "nature.com",
            "biomedcentral.com",
            "link.springer.com",
            "static-content.springer.com",
        ):
            return True
        if doi and doi.lower().startswith(
            ("10.1007/", "10.1038/", "10.1186/", "10.1039/")  # 10.1039 is RSC, skip
        ):
            # 10.1039 is RSC not Springer — exclude
            if doi.lower().startswith("10.1039/"):
                return False
            return doi.lower().startswith(("10.1007/", "10.1038/", "10.1186/"))
        return False

    def discover(self, client: Any, doi: str, landing_url: str) -> list[dict[str, Any]]:
        settings: Settings | None = getattr(client, "settings", None)
        final = resolve_landing(doi, landing_url, settings=settings) or landing_url
        pages = []
        if final:
            pages.append(final)
        if doi:
            d = doi
            pages.extend(
                [
                    f"https://doi.org/{d}",
                    f"https://link.springer.com/article/{d}",
                    f"https://www.nature.com/articles/{d.split('/')[-1]}",
                ]
            )
            # Nature article code form
            if d.lower().startswith("10.1038/"):
                code = d.split("/", 1)[-1]
                pages.append(f"https://www.nature.com/articles/{code}")
                pages.append(f"https://www.nature.com/articles/{code}/figures/1")

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in pages:
            abs_url, html, _code = fetch_html(page, settings=settings)
            if not html:
                continue
            base = abs_url or page
            for href in extract_hrefs(html, base):
                if not _is_sn_si(href):
                    continue
                key = href.split("#")[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                out.append(link_item(href, source="springer_nature:html"))
            if out:
                break
        return out


def _is_sn_si(url: str) -> bool:
    u = url or ""
    if SI_PATH.search(u):
        # reject obvious main article pdf without SI markers
        if MAIN_PDF.search(u) and not re.search(
            r"(moesm|esm|suppl|supporting|mediaobjects)", u, re.I
        ):
            return False
        return True
    if re.search(r"\.(pdf|zip|xlsx|csv|docx|pptx)(\?|$)", u, re.I) and re.search(
        r"(suppl|supporting|appendix|moesm|/esm/)", u, re.I
    ):
        return True
    return False
