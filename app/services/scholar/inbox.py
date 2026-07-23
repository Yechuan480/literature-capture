"""Day-scoped Scholar inbox store: data/scholar_inbox.json."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from typing import Any

from app.config import APP_ROOT
from app.paths import utc_now_iso
from app.services.scholar import parse_alerts
from app.services.scholar.email_settings import email_ready, load_email_settings
from app.services.scholar.imap_client import fetch_recent_messages

_LOCK = threading.Lock()

DATA_DIR = APP_ROOT / "data"
INBOX_PATH = DATA_DIR / "scholar_inbox.json"

# pending | kept | dismissed | fetching | fetched | paywalled | failed | no_pdf
STATUSES = frozenset(
    {"pending", "kept", "dismissed", "fetching", "fetched", "paywalled", "failed", "no_pdf"}
)


def _today() -> str:
    return date.today().isoformat()


def _empty() -> dict[str, Any]:
    return {"version": 1, "updated_at": utc_now_iso(), "days": {}}


def _load() -> dict[str, Any]:
    if not INBOX_PATH.is_file():
        return _empty()
    try:
        with INBOX_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        if "days" not in data or not isinstance(data["days"], dict):
            data["days"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return _empty()


def _save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now_iso()
    with INBOX_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_day(day: str | None = None) -> dict[str, Any]:
    day = day or _today()
    with _LOCK:
        store = _load()
        bucket = store["days"].get(day) or {"date": day, "items": [], "refreshed_at": None}
        return {
            "date": day,
            "items": list(bucket.get("items") or []),
            "refreshed_at": bucket.get("refreshed_at"),
            "email_ready": email_ready(),
        }


def _merge_items(existing: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {it["id"]: dict(it) for it in existing if it.get("id")}
    for it in new_items:
        iid = it.get("id")
        if not iid:
            continue
        if iid in by_id:
            # keep decision/fetch state; refresh title/links if empty
            cur = by_id[iid]
            for k in ("title", "authors", "abstract", "link", "pdf_link", "doi"):
                if not cur.get(k) and it.get(k):
                    cur[k] = it[k]
        else:
            row = dict(it)
            row.setdefault("status", "pending")
            row.setdefault("filename", None)
            row.setdefault("error", None)
            row["added_at"] = utc_now_iso()
            by_id[iid] = row
    # pending first, then others by added_at
    items = list(by_id.values())

    def sort_key(x: dict[str, Any]) -> tuple:
        st = x.get("status") or "pending"
        pri = 0 if st == "pending" else 1
        return (pri, x.get("added_at") or "")

    items.sort(key=sort_key)
    return items


def refresh_inbox(*, days: int = 1, force: bool = False) -> dict[str, Any]:
    """Fetch IMAP Scholar mails and merge into today's inbox."""
    if not email_ready():
        raise RuntimeError("请先在设置中启用邮箱并填写 IMAP 账号与应用专用密码")

    day = _today()
    messages = fetch_recent_messages(days=max(1, days), limit=50)
    parsed: list[dict[str, Any]] = []
    for msg in messages:
        items = parse_alerts.parse_alert_body(
            msg.get("body") or "",
            meta={
                "subject": msg.get("subject"),
                "message_id": msg.get("message_id"),
                "date": msg.get("date"),
            },
        )
        parsed.extend(items)

    with _LOCK:
        store = _load()
        bucket = store["days"].get(day) or {"date": day, "items": [], "refreshed_at": None}
        # Optionally only refresh once/day unless force
        if (
            not force
            and bucket.get("refreshed_at")
            and (bucket.get("items") or [])
        ):
            # still allow merge if new mails — always merge when called
            pass
        merged = _merge_items(list(bucket.get("items") or []), parsed)
        bucket = {
            "date": day,
            "items": merged,
            "refreshed_at": utc_now_iso(),
            "source_messages": len(messages),
            "parsed_new": len(parsed),
        }
        store["days"][day] = bucket
        # prune days older than 14
        try:
            keep_from = date.fromisoformat(day)
            prune = []
            for k in list(store["days"].keys()):
                try:
                    d = date.fromisoformat(k)
                    if (keep_from - d).days > 14:
                        prune.append(k)
                except ValueError:
                    prune.append(k)
            for k in prune:
                del store["days"][k]
        except Exception:
            pass
        _save(store)
        return {
            "date": day,
            "items": merged,
            "refreshed_at": bucket["refreshed_at"],
            "source_messages": len(messages),
            "parsed": len(parsed),
            "email_ready": True,
        }


def decide_items(
    *,
    ids: list[str],
    action: str,
    day: str | None = None,
) -> dict[str, Any]:
    """action: keep | dismiss."""
    action = (action or "").strip().lower()
    if action not in ("keep", "dismiss"):
        raise ValueError("action 须为 keep 或 dismiss")
    day = day or _today()
    idset = {i for i in ids if i}
    with _LOCK:
        store = _load()
        bucket = store["days"].get(day) or {"date": day, "items": [], "refreshed_at": None}
        items = list(bucket.get("items") or [])
        changed = 0
        for it in items:
            if it.get("id") not in idset:
                continue
            if action == "dismiss":
                it["status"] = "dismissed"
                it["error"] = None
            else:
                # keep → pending fetch unless already fetched
                if it.get("status") not in ("fetched", "fetching"):
                    it["status"] = "kept"
                it["error"] = None
            it["decided_at"] = utc_now_iso()
            changed += 1
        bucket["items"] = items
        store["days"][day] = bucket
        _save(store)
        return {"date": day, "changed": changed, "items": items}


def patch_item(item_id: str, fields: dict[str, Any], *, day: str | None = None) -> dict[str, Any] | None:
    day = day or _today()
    with _LOCK:
        store = _load()
        bucket = store["days"].get(day)
        if not bucket:
            return None
        items = list(bucket.get("items") or [])
        found = None
        for it in items:
            if it.get("id") == item_id:
                for k, v in fields.items():
                    if k == "id":
                        continue
                    it[k] = v
                found = dict(it)
                break
        if not found:
            return None
        bucket["items"] = items
        store["days"][day] = bucket
        _save(store)
        return found


def pending_keep_for_fetch(day: str | None = None) -> list[dict[str, Any]]:
    day = day or _today()
    data = get_day(day)
    return [
        it
        for it in data["items"]
        if it.get("status") in ("kept", "failed", "no_pdf", "paywalled")
        and not it.get("filename")
    ]


def count_pending(day: str | None = None) -> int:
    data = get_day(day)
    return sum(1 for it in data["items"] if it.get("status") == "pending")
