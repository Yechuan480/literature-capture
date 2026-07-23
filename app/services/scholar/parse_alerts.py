"""Parse Google 学术搜索快讯 / Scholar alert HTML into paper title + link."""

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
# Title may be inside <a href="...">Title</a> under h3
_H3_A_RE = re.compile(
    r'(?is)<h3[^>]*>\s*(?:<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*(.*?)\s*</a>|(.*?))\s*</h3>',
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Scholar often prefixes titles with [PDF] / [HTML] / [TXT]
_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:\[\s*(?:PDF|HTML|TXT|DOC|DOCX|PPT|PPTX)\s*\]\s*)+",
    re.I,
)
_NOISE_TITLES = frozenset(
    {
        "google 学术搜索",
        "google scholar",
        "scholar alerts",
        "学术搜索快讯",
        "取消订阅",
        "unsubscribe",
        "my citations",
        "我的引用",
    }
)


def _strip_html(html: str) -> str:
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = _TAG_RE.sub(" ", t)
    t = unescape(t)
    return _WS_RE.sub(" ", t).strip()


def _clean_title(title: str) -> str:
    t = _strip_html(title) if "<" in title else unescape(title or "")
    t = _WS_RE.sub(" ", t).strip()
    t = _TITLE_PREFIX_RE.sub("", t).strip()
    # drop leftover bracket noise at start
    t = re.sub(r"^\[[^\]]{0,12}\]\s*", "", t).strip()
    return t[:300]


def _is_noise_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if len(t) < 8:
        return True
    if t in _NOISE_TITLES:
        return True
    if t.startswith("http://") or t.startswith("https://"):
        return True
    return False


def _unwrap_google_url(url: str) -> str:
    """Unwrap scholar_url?url= / url?url= / google.com/url?q= (possibly nested)."""
    cur = (url or "").strip()
    if not cur:
        return cur
    for _ in range(4):
        try:
            u = urlparse(cur)
            host = (u.netloc or "").lower()
            path = (u.path or "").lower()
            qs = parse_qs(u.query)
            next_url = None
            for key in ("url", "q", "u"):
                if key in qs and qs[key]:
                    next_url = unquote(qs[key][0])
                    break
            # scholar.google.*/scholar_url?url=...
            if next_url and (
                "scholar_url" in path
                or "scholar.google." in host
                or host.endswith("google.com")
                or host.endswith("google.cn")
            ):
                cur = next_url
                continue
            if next_url and ("url" in qs or "q" in qs) and "google." in host:
                cur = next_url
                continue
            break
        except Exception:
            break
    return cur


def _looks_paper_link(url: str) -> bool:
    low = (url or "").lower()
    if not low.startswith("http"):
        return False
    if any(
        x in low
        for x in (
            "accounts.google",
            "support.google",
            "scholar.google.com/scholar_alerts",
            "scholar.google.com/scholar_settings",
            "scholar.google.com/citations",
            "scholar.google.com/scholar_share",
            "mailto:",
            "javascript:",
            "unsubscribe",
            "google.com/preferences",
            "google.com/intl/",
        )
    ):
        return False
    # Redirect wrappers are unwrapped first; leftover scholar_url without url= skip
    if "scholar_url" in low and "url=" not in low:
        return False
    if "scholar.google." in low and ("/scholar?" in low or "/scholar_url" in low):
        return True
    # publisher / doi / pdf / open repos
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
            "sciencedirect.com",
            "elsevier.com",
            "agu.org",
            "geoscienceworld",
            "cambridge.org",
            "iop.org",
            "aps.org",
        )
    ):
        return True
    # Any remaining http(s) publisher page after unwrap
    if "scholar.google." not in low:
        return True
    return False


def _pick_primary_link(links: list[str]) -> str:
    """Prefer unwrapped publisher/DOI over scholar.google landing pages."""
    if not links:
        return ""
    for u in links:
        low = u.lower()
        if "scholar.google." not in low and "google.com/url" not in low:
            return u
    for u in links:
        if "doi.org/" in u.lower() or "/doi/" in u.lower():
            return u
    return links[0]


def _extract_doi(text: str) -> str | None:
    m = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    if not m:
        return None
    return m.group(0).rstrip(").,;]")


def _item_id(title: str, link: str) -> str:
    base = (link or "").split("?")[0]
    raw = f"{title.strip().lower()}|{base}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _make_item(
    *,
    title: str,
    link: str,
    links: list[str],
    authors: str = "",
    abstract: str = "",
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    title = _clean_title(title)
    if _is_noise_title(title) or not link:
        return None
    pdf_link = next((u for u in links if ".pdf" in u.lower()), None)
    doi = _extract_doi(link) or _extract_doi(abstract) or _extract_doi(" ".join(links))
    return {
        "id": _item_id(title, link),
        "title": title,
        "authors": authors or "",
        "abstract": abstract or "",
        "link": link,
        "pdf_link": pdf_link,
        "doi": doi,
        "source_subject": meta.get("subject") or "",
        "source_message_id": meta.get("message_id") or "",
        "source_date": meta.get("date") or "",
    }


def _links_in(html: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for hm in _HREF_RE.finditer(html or ""):
        u = _unwrap_google_url(hm.group(1))
        if not _looks_paper_link(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        links.append(u)
    return links


def parse_alert_body(body: str, *, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Extract paper entries from a Google 学术搜索快讯 body.
    Focus fields: title (文献名称) + link (链接).
    Returns list of {id, title, authors, abstract, link, pdf_link, doi, ...}.
    """
    meta = meta or {}
    body = body or ""
    if not body.strip():
        return []

    is_html = "<" in body and ("href" in body.lower() or "<a " in body.lower())
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(row: dict[str, Any] | None) -> None:
        if not row:
            return
        iid = row.get("id")
        if not iid or iid in seen:
            return
        seen.add(iid)
        items.append(row)

    if is_html:
        # 1) Preferred: <h3><a href="scholar_url?url=...">Title</a></h3>
        h3_linked = list(_H3_A_RE.finditer(body))
        if h3_linked:
            for m in h3_linked:
                href = (m.group(1) or "").strip()
                inner = m.group(2) if m.group(1) is not None else m.group(3)
                title = _clean_title(inner or "")
                if _is_noise_title(title):
                    continue
                start = m.end()
                nxt = body.find("<h3", start)
                chunk = body[start:nxt] if nxt >= 0 else body[start : start + 4000]
                window = body[max(0, m.start() - 80) : (nxt if nxt >= 0 else m.end() + 4000)]
                links = _links_in(window)
                if href:
                    u0 = _unwrap_google_url(href)
                    if _looks_paper_link(u0) and u0 not in links:
                        links.insert(0, u0)
                if not links:
                    continue
                primary = _pick_primary_link(links)
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
                _add(
                    _make_item(
                        title=title,
                        link=primary,
                        links=links,
                        authors=authors,
                        abstract=abs_snip,
                        meta=meta,
                    )
                )

        # 2) Classic h3 text + nearby hrefs (empty h3 skipped by title length)
        if not items:
            h3_blocks = list(re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>", body))
            for m in h3_blocks:
                title = _clean_title(m.group(1))
                if _is_noise_title(title):
                    continue
                start = m.end()
                nxt = body.find("<h3", start)
                chunk = body[start:nxt] if nxt >= 0 else body[start : start + 4000]
                window = body[max(0, m.start() - 200) : (nxt if nxt >= 0 else m.end() + 4000)]
                links = _links_in(window)
                if not links:
                    continue
                primary = _pick_primary_link(links)
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
                _add(
                    _make_item(
                        title=title,
                        link=primary,
                        links=links,
                        authors=authors,
                        abstract=abs_snip,
                        meta=meta,
                    )
                )

        # 3) Fallback: card split / plain link clusters
        if not items:
            chunks = re.split(
                r'(?i)(?:<h3[^>]*>|<div[^>]*class=["\'][^"\']*gs_r)',
                body,
            )
            if len(chunks) < 2:
                chunks = [body]
            for chunk in chunks:
                links = _links_in(chunk)
                if not links:
                    continue
                text = _strip_html(chunk)
                if len(text) < 12:
                    continue
                title = _clean_title(text[:200].split(" - ")[0])
                if _is_noise_title(title):
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
                primary = _pick_primary_link(links)
                _add(
                    _make_item(
                        title=title,
                        link=primary,
                        links=links,
                        authors=authors,
                        abstract=abs_snip,
                        meta=meta,
                    )
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
                title = _clean_title(lines[i - 1][:300])
                if not _is_noise_title(title):
                    primary = _pick_primary_link(urls)
                    text_blob = " ".join(lines[max(0, i - 1) : i + 3])
                    _add(
                        _make_item(
                            title=title,
                            link=primary,
                            links=urls,
                            abstract=text_blob[:500],
                            meta=meta,
                        )
                    )
            i += 1

    return items
