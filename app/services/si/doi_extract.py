"""Extract DOI candidates from PDF metadata, first pages, and filename."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any

# Standard DOI pattern; strip trailing punctuation after match
DOI_RE = re.compile(
    r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b",
    re.IGNORECASE,
)
TRAIL_PUNCT = re.compile(r"[.,;:)\]]+$")


def normalize_doi(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.I)
    s = re.sub(r"^doi:\s*", "", s, flags=re.I)
    s = urllib.parse.unquote(s)
    s = TRAIL_PUNCT.sub("", s)
    s = s.strip().rstrip(".")
    m = DOI_RE.search(s)
    if not m:
        return None
    doi = m.group(1)
    # Common trailing junk from PDFs
    doi = TRAIL_PUNCT.sub("", doi)
    if len(doi) < 8:
        return None
    return doi


def _find_dois_in_text(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in DOI_RE.finditer(text):
        d = normalize_doi(m.group(1))
        if d and d.lower() not in seen:
            seen.add(d.lower())
            found.append(d)
    return found


def _from_filename(name: str) -> list[str]:
    raw = urllib.parse.unquote(name or "")
    # doi_10.1016_j.gca.2005.01.003 → 10.1016/j.gca.2005.01.003
    soft = raw.replace("_", "/").replace("%2F", "/").replace("%2f", "/")
    # Only first slash after 10.xxxx should stay; reconstruct common Elsevier pattern
    out = _find_dois_in_text(raw) + _find_dois_in_text(soft)
    # Pattern: doi_10.1016_j.xxx.yyyy.mm.nnn
    m = re.search(r"doi[_:]?(10\.\d{4,9})[_/](.+?)(?:\.pdf)?$", raw, re.I)
    if m:
        cand = normalize_doi(f"{m.group(1)}/{m.group(2).replace('_', '.')}")
        if cand:
            out.append(cand)
        cand2 = normalize_doi(f"{m.group(1)}/{m.group(2).replace('_', '/')}")
        if cand2:
            out.append(cand2)
    # dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for d in out:
        k = d.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def _from_metadata(pdf_path: Path) -> list[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        meta = reader.metadata
        chunks: list[str] = []
        if meta:
            for key in ("/doi", "/DOI", "doi", "DOI"):
                try:
                    val = meta.get(key) if hasattr(meta, "get") else getattr(meta, key, None)
                except Exception:
                    val = None
                if val:
                    chunks.append(str(val))
            for attr in ("subject", "keywords", "title", "creator"):
                try:
                    val = getattr(meta, attr, None) or (
                        meta.get(f"/{attr.capitalize()}") if hasattr(meta, "get") else None
                    )
                except Exception:
                    val = None
                if val:
                    chunks.append(str(val))
        # Also scan info dict
        try:
            if reader.metadata:
                for v in dict(reader.metadata).values():
                    if v:
                        chunks.append(str(v))
        except Exception:
            pass
        return _find_dois_in_text("\n".join(chunks))
    except Exception:
        return []


def _from_pages(pdf_path: Path, max_pages: int = 2) -> list[str]:
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                t = page.extract_text() or ""
                text += "\n" + t
    except Exception:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            for i, page in enumerate(reader.pages[:max_pages]):
                text += "\n" + (page.extract_text() or "")
        except Exception:
            return []
    return _find_dois_in_text(text)


def extract_dois(pdf_path: Path) -> dict[str, Any]:
    """
    Return {
      doi: best | None,
      doi_source: str | None,
      candidates: [{doi, source}, ...]
    }
    """
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(dois: list[str], source: str) -> None:
        for d in dois:
            k = d.lower()
            if k in seen:
                continue
            seen.add(k)
            candidates.append({"doi": d, "source": source})

    add(_from_metadata(pdf_path), "pdf_metadata")
    add(_from_pages(pdf_path, 2), "pdf_text")
    add(_from_filename(pdf_path.name), "filename")

    best = candidates[0] if candidates else None
    return {
        "doi": best["doi"] if best else None,
        "doi_source": best["source"] if best else None,
        "candidates": candidates,
    }
