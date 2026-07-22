"""Classify and filter SI / table download candidates."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

SI_KEYWORDS = re.compile(
    r"(supplement|suppl(?:ementary)?|supporting[\s_-]?info|supporting[\s_-]?information|"
    r"\bsi\b|/si/|si\.|esi|/esm/|\besm\b|moesm|edata|mmc\d*|appendix|electronic[\s_-]?annex|"
    r"additional[\s_-]?file|table[\s_-]?s\d|tables?[\s_-]?s\d|mediaobjects)",
    re.I,
)
TABLE_EXT = re.compile(r"\.(xlsx?|csv|tsv|ods)(\?|$)", re.I)
ZIP_EXT = re.compile(r"\.(zip|tar\.gz|tgz|7z)(\?|$)", re.I)
PDF_EXT = re.compile(r"\.pdf(\?|$)", re.I)
MAIN_PDF_HINT = re.compile(
    r"(full[\s_-]?text|main[\s_-]?pdf|/pdf/main|article\.pdf|/pdfdirect/|/pdfft/)",
    re.I,
)


def classify_kind(url: str, content_type: str | None = None) -> str:
    u = unquote(url or "")
    ct = (content_type or "").lower()
    if TABLE_EXT.search(u) or "spreadsheet" in ct or "excel" in ct or "csv" in ct:
        return "si_xlsx" if "csv" not in ct and not u.lower().endswith(".csv") else "si_csv"
    if ZIP_EXT.search(u) or "zip" in ct or "compressed" in ct:
        return "si_zip"
    if PDF_EXT.search(u) or "pdf" in ct:
        if SI_KEYWORDS.search(u):
            return "si_pdf"
        return "main_pdf"
    if SI_KEYWORDS.search(u):
        return "si_html"
    return "unknown"


def looks_like_si(url: str, content_type: str | None = None, intended: str | None = None) -> bool:
    u = unquote(url or "")
    if SI_KEYWORDS.search(u):
        return True
    if intended and (
        SI_KEYWORDS.search(intended)
        or str(intended).lower() in ("manual", "si", "supplementary", "supporting")
    ):
        return True
    kind = classify_kind(u, content_type)
    if kind in ("si_xlsx", "si_csv", "si_zip", "si_pdf"):
        return True
    ct = (content_type or "").lower()
    if any(x in ct for x in ("spreadsheet", "excel", "csv", "zip")):
        return True
    return False


def is_rejected_main_pdf(url: str, content_type: str | None = None) -> bool:
    u = unquote(url or "")
    kind = classify_kind(u, content_type)
    if kind != "main_pdf":
        return False
    if SI_KEYWORDS.search(u):
        return False
    if MAIN_PDF_HINT.search(u):
        return True
    # Ambiguous single PDF without SI keywords → treat as main, reject for SI pipeline
    return True


def filter_candidates(raw: list[dict[str, Any]], *, max_files: int = 15) -> list[dict[str, Any]]:
    """
    raw items: {url, content_type?, intended?, source}
    Returns selected candidates with kind/selected/skip_reason.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        url = (item.get("url") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        # Normalize for dedupe (strip fragment)
        key = url.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        ct = item.get("content_type")
        intended = item.get("intended")
        kind = classify_kind(url, ct)
        selected = False
        skip_reason = None
        if is_rejected_main_pdf(url, ct) and not looks_like_si(url, ct, intended):
            skip_reason = "main_article_pdf"
            kind = "main_pdf"
        elif looks_like_si(url, ct, intended):
            if kind == "main_pdf":
                kind = "si_pdf"
            selected = True
        elif kind in ("si_xlsx", "si_csv", "si_zip"):
            selected = True
        else:
            skip_reason = "not_si"
        out.append(
            {
                "url": url,
                "kind": kind,
                "source": item.get("source") or "unknown",
                "content_type": ct,
                "selected": selected,
                "skip_reason": skip_reason,
            }
        )

    # Prefer table/zip over ambiguous
    def rank(c: dict[str, Any]) -> tuple:
        order = {"si_xlsx": 0, "si_csv": 1, "si_zip": 2, "si_pdf": 3, "si_html": 4}
        return (0 if c.get("selected") else 1, order.get(c.get("kind") or "", 9), c.get("url") or "")

    out.sort(key=rank)
    selected_n = 0
    for c in out:
        if c.get("selected"):
            selected_n += 1
            if selected_n > max_files:
                c["selected"] = False
                c["skip_reason"] = "over_limit"
    return out


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""
