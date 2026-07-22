"""Publisher SI page adapters (Phase 2 stubs)."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def discover_publisher_links(
    *,
    doi: str | None,
    landing_url: str | None,
    publisher: str | None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """
    Phase 1: no-op (return []).
    Phase 2: call registered adapters for Elsevier/Springer/Wiley/Nature/ACS.
    """
    _ = (settings, doi, landing_url, publisher)
    return []
