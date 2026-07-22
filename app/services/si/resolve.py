"""Resolve DOI/URL via Crossref and collect raw link candidates."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.config import Settings, get_settings
from app.services.si.doi_extract import normalize_doi
from app.services.si.http_util import get_json, request


def crossref_work(doi: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    d = normalize_doi(doi)
    if not d:
        raise ValueError("invalid DOI")
    url = f"https://api.crossref.org/works/{quote(d, safe='')}"
    data = get_json(url, settings=settings)
    msg = data.get("message") if isinstance(data, dict) else None
    if not isinstance(msg, dict):
        raise ValueError("unexpected Crossref response")
    return msg


def links_from_crossref(msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for link in msg.get("link") or []:
        if not isinstance(link, dict):
            continue
        u = link.get("URL")
        if not u:
            continue
        raw.append(
            {
                "url": u,
                "content_type": link.get("content-type"),
                "intended": link.get("intended-application"),
                "source": "crossref:link",
            }
        )
    resource = msg.get("resource") or {}
    if isinstance(resource, dict):
        primary = resource.get("primary") or {}
        if isinstance(primary, dict) and primary.get("URL"):
            raw.append(
                {
                    "url": primary["URL"],
                    "content_type": None,
                    "intended": None,
                    "source": "crossref:resource",
                }
            )
    if msg.get("URL"):
        raw.append(
            {
                "url": msg["URL"],
                "content_type": None,
                "intended": None,
                "source": "crossref:url",
            }
        )
    return raw


def title_from_crossref(msg: dict[str, Any]) -> str | None:
    titles = msg.get("title") or []
    if isinstance(titles, list) and titles:
        return str(titles[0]).strip() or None
    return None


def publisher_from_crossref(msg: dict[str, Any]) -> tuple[str | None, str | None]:
    pub = msg.get("publisher")
    container = msg.get("container-title") or []
    ct = container[0] if isinstance(container, list) and container else None
    return (str(pub) if pub else None, str(ct) if ct else None)


def resolve_doi(doi: str, settings: Settings | None = None) -> dict[str, Any]:
    """Return resolved metadata + raw link list."""
    msg = crossref_work(doi, settings)
    title = title_from_crossref(msg)
    publisher, container = publisher_from_crossref(msg)
    links = links_from_crossref(msg)
    landing = msg.get("URL") or f"https://doi.org/{normalize_doi(doi)}"
    return {
        "doi": normalize_doi(doi),
        "title": title,
        "publisher": publisher,
        "container_title": container,
        "landing_url": landing,
        "raw_links": links,
        "crossref": True,
    }


def probe_url(url: str, settings: Settings | None = None) -> dict[str, Any]:
    """HEAD/GET headers for a manual URL (no full body)."""
    settings = settings or get_settings()
    try:
        r = request("HEAD", url, settings=settings)
        if r.status_code >= 400 or r.status_code < 200:
            r = request("GET", url, settings=settings, headers={"Range": "bytes=0-0"})
        return {
            "url": str(r.url),
            "status_code": r.status_code,
            "content_type": r.headers.get("content-type"),
            "content_disposition": r.headers.get("content-disposition"),
        }
    except Exception as e:
        return {"url": url, "error": str(e)}
