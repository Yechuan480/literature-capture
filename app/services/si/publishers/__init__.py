"""Publisher SI page adapters (Phase 2)."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.services.si.publishers.acs import ACSAdapter
from app.services.si.publishers.base import PublisherAdapter
from app.services.si.publishers.elsevier import ElsevierAdapter
from app.services.si.publishers.generic import GenericLandingAdapter
from app.services.si.publishers.springer_nature import SpringerNatureAdapter
from app.services.si.publishers.wiley import WileyAdapter


class _ClientProxy:
    """Thin bag so adapters can read settings without a real HTTP client object."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings


_ADAPTERS: list[PublisherAdapter] = [
    ElsevierAdapter(),
    SpringerNatureAdapter(),
    WileyAdapter(),
    ACSAdapter(),
    GenericLandingAdapter(),
]


def registered_adapters() -> list[PublisherAdapter]:
    return list(_ADAPTERS)


def discover_publisher_links(
    *,
    doi: str | None,
    landing_url: str | None,
    publisher: str | None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """
    Call matching publisher adapters; scrape public article HTML for SI links.
    No login, CAPTCHA, or paywall bypass.
    """
    settings = settings or get_settings()
    if not settings.si_enabled:
        return []

    client = _ClientProxy(settings)
    url = landing_url or ""
    d = doi or ""
    pub = publisher or ""

    # Specific adapters first; generic last and only if nothing found yet
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    matched_specific = False

    for adapter in _ADAPTERS:
        name = getattr(adapter, "name", "") or type(adapter).__name__
        is_generic = name == "generic"
        try:
            if not adapter.match(url, d, pub):
                continue
        except Exception:
            continue
        if is_generic and found:
            break
        if not is_generic:
            matched_specific = True
        try:
            links = adapter.discover(client, d, url) or []
        except Exception:
            links = []
        for item in links:
            u = (item.get("url") or "").strip()
            if not u.startswith("http"):
                continue
            key = u.split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            # tag adapter name if missing
            if item.get("source") in (None, "", "unknown"):
                item = {**item, "source": f"{name}:html"}
            found.append(item)
        if found and not is_generic:
            # one successful specific adapter is enough
            break

    # If no specific adapter matched but we have landing/doi, generic already runs via match
    _ = matched_specific
    return found
