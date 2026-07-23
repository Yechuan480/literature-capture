"""Parse Google Scholar alert HTML/plain into paper candidates."""

from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# Scholar alert link patterns (fragile; fail soft)
_HREF_RE = re.compile(
    r'href=["\'](https?://[^"\']+)["\']',
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = _TAG_RE.sub(" ", t)
    t = unescape(t)
    return _WS_RE.sub(" ", t).strip()


def _unwrap_google_url(url: str) -> str:
    """Unwrap scholar.google.com/url?url= or google.com/url?q=."""
    try:
        u = urlparse(url)
        qs = parse_qs(u.query)
        for key in ("url", "q", "u"):
            if key in qs and qs[key]:
                return unquote(qs[key][0])
        return url
    except Exception:
        return url


def _looks_paper_link(url: str) -> bool:
    low = url.lower()
    if any(
        x in low
        for x in (
            "accounts.google",
            "support.google",
            "scholar.google.com/scholar_alerts",
            "scholar.google.com/scholar_settings",
            "scholar.google.com/citations",
            "mailto:",
            "javascript:",
            "unsubscribe",
        )
    ):
        return False
    if "scholar.google." in low and "/scholar?" in low:
        return True
    # publisher / doi / pdf
    if any(
        x in low
        for x in (
            "doi.org/",
            "/doi/",
            ".pdf",
            "arxiv.org",
            "biorxiv.org",
            "medrxiv.org",
            "ssrn.com",
            "researchgate",
            "nature.com",
            "sciencedirect",
            "springer",
            "wiley",
            "acs.org",
            "rsc.org",
            "ieee.org",
            "mdpi.com",
            "plos.org",
            "frontiersin",
            "tandfonline",
            "oup.com",
            "nih.gov",
            "pubmed",
        )
    ):
        return True
    return "http" in low


def _extract_doi(text: str) -> str | None:
    m = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    if not m:
        return None
    doi = m.group(0).rstrip(").,;]")
    return doi


def _item_id(title: str, link: str) -> str:
    raw = f"{title.strip().lower()}|{link.split('?')[0]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def parse_alert_body(body: str, *, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Extract paper-like entries from a Scholar alert message body.
    Returns list of {id, title, authors, abstract, link, pdf_link, doi, source_subject}.
    """
    meta = meta or {}
    body = body or ""
    if not body.strip():
        return []

    is_html = "<" in body and ("href" in body.lower() or "<a " in body.lower())
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    if is_html:
        # Prefer structured <h3>…</h3> cards (Scholar alerts)
        h3_blocks = list(re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>", body))
        if h3_blocks:
            for m in h3_blocks:
                title = _strip_html(m.group(1))[:300].strip()
                if len(title) < 8:
                    continue
                # window after this h3 until next h3
                start = m.end()
                nxt = body.find("<h3", start)
                chunk = body[start:nxt] if nxt >= 0 else body[start : start + 4000]
                # also scan a bit before for the title link
                window = body[max(0, m.start() - 200) : (nxt if nxt >= 0 else m.end() + 4000)]
                links = []
                for hm in _HREF_RE.finditer(window):
                    u = _unwrap_google_url(hm.group(1))
                    if _looks_paper_link(u):
                        links.append(u)
                if not links:
                    continue
                text = _strip_html(chunk)
                authors = ""
                abs_snip = ""
                parts = re.split(r"\s[–—-]\s", text, maxsplit=2)
                if parts:
                    maybe_auth = parts[0].strip()
                    if 3 < len(maybe_auth) < 180 and not maybe_auth.lower().startswith("http"):
                        authors = maybe_auth[:200]
                        if len(parts) > 1:
                            abs_snip = " - ".join(parts[1:])[:500]
                    else:
                        abs_snip = text[:500]
                primary = links[0]
                # prefer non-scholar primary if available
                for u in links:
                    if "scholar.google." not in u.lower():
                        primary = u
                        break
                pdf_link = next((u for u in links if ".pdf" in u.lower()), "") or None
                doi = _extract_doi(primary) or _extract_doi(text) or _extract_doi(" ".join(links))
                iid = _item_id(title, primary)
                if iid in seen:
                    continue
                seen.add(iid)
                items.append(
                    {
                        "id": iid,
                        "title": title,
                        "authors": authors,
                        "abstract": abs_snip,
                        "link": primary,
                        "pdf_link": pdf_link,
                        "doi": doi,
                        "source_subject": meta.get("subject") or "",
                        "source_message_id": meta.get("message_id") or "",
                        "source_date": meta.get("date") or "",
                    }
                )
        if not items:
            # Fallback: split on common Scholar card boundaries
            chunks = re.split(
                r'(?i)(?:<h3[^>]*>|<div[^>]*class=["\'][^"\']*gs_r)',
                body,
            )
            if len(chunks) < 2:
                chunks = [body]
            for chunk in chunks:
                links = []
                for m in _HREF_RE.finditer(chunk):
                    u = _unwrap_google_url(m.group(1))
                    if _looks_paper_link(u):
                        links.append(u)
                if not links:
                    continue
                text = _strip_html(chunk)
                if len(text) < 12:
                    continue
                title = text[:200].split(" - ")[0].strip()[:300]
                if len(title) < 8:
                    continue
                authors = ""
                abs_snip = ""
                rest = text
                if title in rest:
                    rest = rest.split(title, 1)[-1].strip(" -–—|")
                parts = re.split(r"\s[–—-]\s", rest, maxsplit=1)
                if parts:
                    maybe_auth = parts[0].strip()
                    if len(maybe_auth) < 180 and not maybe_auth.lower().startswith("http"):
                        authors = maybe_auth[:200]
                        if len(parts) > 1:
                            abs_snip = parts[1][:500]
                    else:
                        abs_snip = rest[:500]
                primary = links[0]
                for u in links:
                    if "scholar.google." not in u.lower():
                        primary = u
                        break
                pdf_link = next((u for u in links if ".pdf" in u.lower()), None)
                doi = _extract_doi(primary) or _extract_doi(text) or _extract_doi(" ".join(links))
                iid = _item_id(title, primary)
                if iid in seen:
                    continue
                seen.add(iid)
                items.append(
                    {
                        "id": iid,
                        "title": title,
                        "authors": authors,
                        "abstract": abs_snip,
                        "link": primary,
                        "pdf_link": pdf_link,
                        "doi": doi,
                        "source_subject": meta.get("subject") or "",
                        "source_message_id": meta.get("message_id") or "",
                        "source_date": meta.get("date") or "",
                    }
                )
    else:
        # plain text: lines with http
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        i = 0
        while i < len(lines):
            ln = lines[i]
            urls = re.findall(r"https?://\S+", ln)
            urls = [_unwrap_google_url(u.rstrip(").,;")) for u in urls]
            urls = [u for u in urls if _looks_paper_link(u)]
            if urls and i > 0:
                title = lines[i - 1][:300]
                if len(title) >= 8:
                    primary = urls[0]
                    text_blob = " ".join(lines[max(0, i - 1) : i + 3])
                    doi = _extract_doi(primary) or _extract_doi(text_blob)
                    iid = _item_id(title, primary)
                    if iid not in seen:
                        seen.add(iid)
                        items.append(
                            {
                                "id": iid,
                                "title": title,
                                "authors": "",
                                "abstract": "",
                                "link": primary,
                                "pdf_link": next((u for u in urls if ".pdf" in u.lower()), None),
                                "doi": doi,
                                "source_subject": meta.get("subject") or "",
                                "source_message_id": meta.get("message_id") or "",
                                "source_date": meta.get("date") or "",
                            }
                        )
            i += 1

    return items
