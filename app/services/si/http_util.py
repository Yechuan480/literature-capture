"""Shared HTTP client, UA, and per-host rate limiting for SI downloads."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings, get_settings

_last_host_hit: dict[str, float] = {}
_host_lock = threading.Lock()
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def user_agent(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    ua = settings.si_user_agent or "literature-capture/1.3"
    mail = (settings.si_crossref_mailto or "").strip()
    if mail and "mailto:" not in ua:
        return f"{ua}; mailto:{mail}"
    return ua


def get_client(settings: Settings | None = None) -> httpx.Client:
    global _client
    settings = settings or get_settings()
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(settings.si_request_timeout_s, connect=15.0),
                headers={
                    "User-Agent": user_agent(settings),
                    "Accept-Language": "en-US,en;q=0.9",
                },
                max_redirects=8,
            )
        return _client


def rate_limit_host(url: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    host = urlparse(url).netloc.lower()
    if not host:
        return
    interval = max(0, int(settings.si_min_interval_ms)) / 1000.0
    with _host_lock:
        last = _last_host_hit.get(host, 0.0)
        now = time.monotonic()
        wait = interval - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_host_hit[host] = time.monotonic()


def request(
    method: str,
    url: str,
    *,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> httpx.Response:
    settings = settings or get_settings()
    rate_limit_host(url, settings)
    client = get_client(settings)
    # Browser-like defaults help some publisher CDNs; still no login/cookies store
    hdrs = {
        "User-Agent": user_agent(settings),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        hdrs.update(headers)
    return client.request(method, url, headers=hdrs)


def get_json(url: str, *, settings: Settings | None = None) -> dict[str, Any]:
    r = request("GET", url, settings=settings, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()
