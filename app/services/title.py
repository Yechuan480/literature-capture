"""Title extraction: PDF metadata → first page → filename."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from app.paths import clean_display_title

GARBAGE_TITLES = {
    "",
    "untitled",
    "title",
    "document",
    "microsoft word",
    "microsoft word - document",
}

SKIP_LINE_PREFIXES = (
    "abstract",
    "keywords",
    "key words",
    "doi:",
    "doi ",
    "http://",
    "https://",
    "www.",
    "received",
    "accepted",
    "available online",
    "contents lists",
    "©",
    "copyright",
)

# Zotero-ish: "Author 等 - 2018 - Title..." or "Author et al. - 2018 - Title"
ZOTERO_PREFIX = re.compile(
    r"^.*?(?:等|et\s+al\.?)\s*[-–—]\s*\d{4}\s*[-–—]\s*",
    re.IGNORECASE,
)
# Fallback: "Something - 2018 - Title"
YEAR_PREFIX = re.compile(r"^.*?\s[-–—]\s*(?:19|20)\d{2}\s[-–—]\s*")
TRAILING_NOISE = re.compile(r"(?:\s*[-–—,]\s*(?:co-?)?\d+)+$", re.IGNORECASE)
MULTI_SPACE = re.compile(r"\s+")


def _is_garbage_title(title: str, filename_stem: str = "") -> bool:
    t = clean_display_title(title)
    if len(t) < 5:
        return True
    low = t.lower()
    if low in GARBAGE_TITLES:
        return True
    if filename_stem and low == filename_stem.lower():
        return True
    # Mostly punctuation / digits
    letters = sum(ch.isalpha() for ch in t)
    if letters < max(3, len(t) // 5):
        return True
    return False


def _from_metadata(pdf_path: Path) -> str | None:
    try:
        reader = PdfReader(str(pdf_path))
        meta = reader.metadata
        if not meta:
            return None
        title = meta.title or getattr(meta, "/Title", None)
        if not title:
            return None
        title = clean_display_title(str(title))
        if _is_garbage_title(title, pdf_path.stem):
            return None
        return title
    except Exception:
        return None


def _looks_like_title_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) < 8 or len(s) > 300:
        return False
    low = s.lower()
    for p in SKIP_LINE_PREFIXES:
        if low.startswith(p):
            return False
    # Glued PDF extract (few spaces relative to length) is usually body/abstract
    spaces = s.count(" ")
    if len(s) > 40 and spaces < max(2, len(s) // 25):
        return False
    # Journal headers often ALL CAPS short-ish
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.9 and len(s) < 40:
        return False
    # Author lines often have commas + emails or superscripts
    if s.count(",") >= 3 and len(s) < 120:
        return False
    if "@" in s:
        return False
    # Affiliation / institute
    if re.search(r"\b(institut|university|universit|department|germany|uk)\b", low):
        return False
    # Author-ish: Name Namea,b  or  Name Name¨ller
    if re.search(r"[a-z]\d[,a-z]|\w{2,}¨", s) and len(s) < 100 and spaces <= 6:
        return False
    return True


def _from_first_page(pdf_path: Path) -> str | None:
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        try:
            reader = PdfReader(str(pdf_path))
            if not reader.pages:
                return None
            text = reader.pages[0].extract_text() or ""
        except Exception:
            return None

    if not text.strip():
        return None

    lines = [MULTI_SPACE.sub(" ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    # Stop before abstract / body
    stop_at = len(lines)
    for i, ln in enumerate(lines[:50]):
        if ln.strip().lower() in {"abstract", "introduction", "keywords", "key words"}:
            stop_at = i
            break
    lines = lines[:stop_at]

    # Drop common publisher chrome
    chrome = (
        "sciencedirect",
        "elsevier",
        "springer",
        "nature ",
        " wiley",
        "geochimica",
        "cosmochimica",
        "journal of",
        "contents lists",
        "available online",
        "www.elsevier",
        "www.sciencedirect",
    )
    filtered: list[str] = []
    for ln in lines[:40]:
        low = ln.lower()
        if any(c in low for c in chrome) and len(ln) < 120:
            continue
        if re.match(r"^(vol\.|volume|pp\.|pages?|article|no\.)\b", low):
            continue
        # journal + volume glued: GeochimicaetCosmochimicaActa239(2018)17–48
        if re.search(r"\d{4}\)\s*\d", ln) and len(ln) < 100:
            continue
        if re.search(r"(?:19|20)\d{2}\s*;\s*\d", ln) and len(ln) < 100:
            continue
        if re.match(r"^received\b", low):
            continue
        filtered.append(ln)

    candidates: list[str] = []
    for ln in filtered[:25]:
        if _looks_like_title_line(ln):
            candidates.append(ln)
            if len(candidates) >= 5:
                break

    if not candidates:
        return None

    # Prefer early multi-line title: take first candidate and join following short lines
    # that look like title continuations (before authors)
    title = candidates[0]
    for nxt in candidates[1:]:
        if title.endswith((".", "?", "!")):
            break
        if len(nxt) > 120:
            break
        # Author block: capitalized surnames + commas / et al. (not title subtitles)
        words = nxt.replace(",", " ").split()
        cap_ratio = (
            sum(1 for w in words if w[:1].isupper()) / len(words) if words else 0
        )
        if nxt.count(",") >= 2 and cap_ratio > 0.6 and len(nxt) < 140:
            break
        if re.search(r"\bet\s+al\b", nxt.lower()) and "," in nxt:
            break
        # Continuation often starts lowercase or with colon mid-phrase
        title = f"{title} {nxt}"
        if len(title) > 220:
            break

    title = clean_display_title(title)
    if title and title[0].islower():
        return None
    if _is_garbage_title(title, pdf_path.stem):
        return None
    return title


def _from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem
    s = stem
    m = ZOTERO_PREFIX.match(s)
    if m:
        s = s[m.end() :]
    else:
        m2 = YEAR_PREFIX.match(s)
        if m2:
            s = s[m2.end() :]
    # Zotero truncation suffix like ", co-1" / " -1"
    s = re.sub(r",\s*co-\d+$", "", s, flags=re.IGNORECASE)
    s = TRAILING_NOISE.sub("", s)
    s = s.replace("..", ".")
    s = clean_display_title(s)
    return s or stem


def extract_title(pdf_path: Path) -> dict:
    """Return {title, source, candidates}."""
    candidates: list[dict[str, str]] = []

    meta_title = _from_metadata(pdf_path)
    if meta_title:
        candidates.append({"source": "metadata", "title": meta_title})

    page_title = _from_first_page(pdf_path)
    if page_title:
        candidates.append({"source": "first_page", "title": page_title})

    file_title = _from_filename(pdf_path)
    candidates.append({"source": "filename", "title": file_title})

    # Preference: metadata → first_page → filename
    for source in ("metadata", "first_page", "filename"):
        for c in candidates:
            if c["source"] == source:
                return {
                    "title": c["title"],
                    "source": source,
                    "candidates": candidates,
                }

    return {"title": file_title, "source": "filename", "candidates": candidates}
