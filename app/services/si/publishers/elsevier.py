"""Elsevier / ScienceDirect SI discovery from public article HTML + CDN probes."""

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

ELS_SI = re.compile(
    r"(mmc\d*|e-?component|appendix|suppl|supporting|"
    r"ars\.els-cdn\.com|sciencedirect\.com/.*/article/.*\.(pdf|zip|xlsx|csv|docx))",
    re.I,
)
ELS_MAIN = re.compile(r"pdfft|/main\.pdf|pii/[^/]+/pdfft", re.I)
PII_RE = re.compile(r"(?:/pii/|PII:|1-s2\.0-)([A-Z0-9]{10,})", re.I)


class ElsevierAdapter:
    name = "elsevier"

    def match(self, url: str, doi: str, publisher: str) -> bool:
        blob = publisher_blob(publisher, url, doi)
        if any(
            x in blob
            for x in (
                "elsevier",
                "sciencedirect",
                "cell press",
                "academic press",
            )
        ):
            return True
        if url and host_matches(
            url,
            "sciencedirect.com",
            "elsevier.com",
            "cell.com",
            "linkinghub.elsevier.com",
        ):
            return True
        if doi and doi.lower().startswith(("10.1016/", "10.1006/", "10.1053/")):
            return True
        return False

    def discover(self, client: Any, doi: str, landing_url: str) -> list[dict[str, Any]]:
        settings: Settings | None = getattr(client, "settings", None)
        final = resolve_landing(doi, landing_url, settings=settings) or landing_url
        if not final:
            return []

        pages = [final]
        if doi:
            pages.append(f"https://doi.org/{doi}")

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        pii = _pii_from_doi_or_url(doi, final)

        for page in pages:
            if not page:
                continue
            abs_url, html, _code = fetch_html(page, settings=settings)
            base = abs_url or page
            if not pii:
                pii = _pii_from_doi_or_url(doi, base) or _pii_from_html(html or "")
            if pii and abs_url and "sciencedirect.com" not in (abs_url or ""):
                # try SD article page once we know PII
                pages.append(f"https://www.sciencedirect.com/science/article/pii/{pii}")
            if html:
                for href in extract_hrefs(html, base):
                    if not _is_elsevier_si(href):
                        continue
                    key = href.split("#")[0].rstrip("/")
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(link_item(href, source="elsevier:html"))

        if pii:
            # Probe open CDN paths; only keep URLs that actually exist
            consecutive_miss = 0
            any_hit = False
            for i in range(1, 16):
                hit_this = False
                for ext, ctype in (
                    ("pdf", "application/pdf"),
                    ("zip", "application/zip"),
                    ("xlsx", None),
                    ("docx", None),
                ):
                    guess = (
                        f"https://ars.els-cdn.com/content/image/"
                        f"1-s2.0-{pii}-mmc{i}.{ext}"
                    )
                    key = guess.rstrip("/")
                    if key in seen:
                        hit_this = True
                        continue
                    if not _url_exists(guess, settings=settings):
                        continue
                    hit_this = True
                    any_hit = True
                    seen.add(key)
                    out.append(
                        link_item(
                            guess,
                            source="elsevier:cdn_probe",
                            content_type=ctype,
                        )
                    )
                if hit_this:
                    consecutive_miss = 0
                else:
                    consecutive_miss += 1
                    if any_hit and consecutive_miss >= 2:
                        break
                    if not any_hit and consecutive_miss >= 3:
                        break

        return out


def _pii_from_doi_or_url(doi: str | None, url: str | None) -> str | None:
    if url:
        m = PII_RE.search(url)
        if m:
            return m.group(1)
    return None


def _pii_from_html(html: str) -> str | None:
    if not html:
        return None
    m = re.search(r'"pii"\s*:\s*"([A-Z0-9]+)"', html, re.I)
    if m:
        return m.group(1)
    m = PII_RE.search(html)
    return m.group(1) if m else None


def _url_exists(url: str, *, settings: Settings | None) -> bool:
    try:
        r = request(
            "GET",
            url,
            settings=settings,
            headers={"Range": "bytes=0-256"},
        )
    except Exception:
        return False
    if r.status_code not in (200, 206):
        return False
    ct = (r.headers.get("content-type") or "").lower()
    body = r.content[:400]
    if "xml" in ct and (
        b"Error" in body or b"<Error" in body or b"NoSuchKey" in body or len(body) < 400
    ):
        return False
    if "html" in ct and b"not found" in body.lower():
        return False
    # Require recognizable binary magic for common SI types
    lower = url.lower()
    if lower.endswith(".pdf"):
        return body.startswith(b"%PDF")
    if lower.endswith((".xlsx", ".docx", ".zip")):
        return body.startswith(b"PK")
    if lower.endswith(".csv"):
        return len(body) > 0 and b"<" not in body[:1]
    return len(body) >= 32


def _is_elsevier_si(url: str) -> bool:
    u = url or ""
    if ELS_MAIN.search(u) and not re.search(r"mmc\d*", u, re.I):
        return False
    if ELS_SI.search(u):
        return True
    if re.search(r"\.(pdf|zip|xlsx|csv|docx)(\?|$)", u, re.I) and re.search(
        r"(suppl|supporting|appendix|mmc)", u, re.I
    ):
        return True
    return False
