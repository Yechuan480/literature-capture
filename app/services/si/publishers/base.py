"""Publisher adapter protocol (Phase 2)."""

from __future__ import annotations

from typing import Any, Protocol


class PublisherAdapter(Protocol):
    def match(self, url: str, doi: str, publisher: str) -> bool: ...

    def discover(self, client: Any, doi: str, landing_url: str) -> list[dict[str, Any]]: ...
