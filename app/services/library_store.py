"""File-based library overlay: collections + per-PDF metadata (data/library.json)."""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.config import APP_ROOT, get_settings
from app.paths import list_pdfs, utc_now_iso

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None

DATA_DIR = APP_ROOT / "data"
LIBRARY_PATH = DATA_DIR / "library.json"

STATUS_CHOICES = frozenset({"unread", "reading", "done", "archived"})


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now_iso(),
        "collections": [
            {
                "id": "all",
                "name": "全部文献",
                "builtin": True,
                "created_at": utc_now_iso(),
            },
            {
                "id": "unread",
                "name": "未读",
                "builtin": True,
                "created_at": utc_now_iso(),
            },
            {
                "id": "reading",
                "name": "在读",
                "builtin": True,
                "created_at": utc_now_iso(),
            },
            {
                "id": "done",
                "name": "已读",
                "builtin": True,
                "created_at": utc_now_iso(),
            },
        ],
        "items": {},  # filename -> overlay
    }


def _read_file() -> dict[str, Any]:
    if not LIBRARY_PATH.is_file():
        return {}
    try:
        with LIBRARY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_store(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty_store()
    if not raw:
        return base
    cols = raw.get("collections")
    if isinstance(cols, list) and cols:
        # Ensure builtins exist
        by_id = {c.get("id"): c for c in cols if isinstance(c, dict) and c.get("id")}
        for b in base["collections"]:
            if b["id"] not in by_id:
                cols.insert(0, b)
        base["collections"] = [c for c in cols if isinstance(c, dict) and c.get("id")]
    items = raw.get("items")
    if isinstance(items, dict):
        base["items"] = {
            str(k): v for k, v in items.items() if isinstance(v, dict) and k
        }
    if raw.get("updated_at"):
        base["updated_at"] = str(raw["updated_at"])
    if raw.get("version"):
        base["version"] = int(raw["version"] or 1)
    return base


def load_library(*, force: bool = False) -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not force:
            return json.loads(json.dumps(_CACHE))
        store = _normalize_store(_read_file())
        _CACHE = store
        return json.loads(json.dumps(store))


def save_library(store: dict[str, Any]) -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        store = _normalize_store(store)
        store["updated_at"] = utc_now_iso()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LIBRARY_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        tmp.replace(LIBRARY_PATH)
        _CACHE = store
        return json.loads(json.dumps(store))


def _default_item_overlay(filename: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "status": "unread",
        "tags": [],
        "collection_ids": [],
        "notes": "",
        "title_override": None,
        "translated_pdf": None,
        "paper_slug": None,
        "updated_at": utc_now_iso(),
    }


def sync_from_disk() -> dict[str, Any]:
    """Merge disk PDFs into library items; drop overlays for missing files."""
    store = load_library(force=True)
    pdfs = list_pdfs()
    on_disk = {p["filename"] for p in pdfs}
    items = store.get("items") or {}
    # drop missing
    for fn in list(items.keys()):
        if fn not in on_disk:
            del items[fn]
    # ensure every PDF has overlay
    for p in pdfs:
        fn = p["filename"]
        if fn not in items:
            ov = _default_item_overlay(fn)
            if p.get("paper_slug"):
                ov["paper_slug"] = p["paper_slug"]
            if p.get("title"):
                ov["title_override"] = None  # keep disk/capture title as display
            items[fn] = ov
        else:
            # refresh paper_slug from capture stats if empty
            if not items[fn].get("paper_slug") and p.get("paper_slug"):
                items[fn]["paper_slug"] = p["paper_slug"]
    store["items"] = items
    return save_library(store)


def _merge_item(pdf: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    ov = overlay or _default_item_overlay(pdf["filename"])
    status = ov.get("status") or "unread"
    if status not in STATUS_CHOICES:
        status = "unread"
    tags = ov.get("tags") if isinstance(ov.get("tags"), list) else []
    tags = [str(t).strip() for t in tags if str(t).strip()]
    coll = ov.get("collection_ids") if isinstance(ov.get("collection_ids"), list) else []
    coll = [str(c) for c in coll if c]
    title = (ov.get("title_override") or pdf.get("title") or "").strip() or None
    return {
        "filename": pdf["filename"],
        "size": int(pdf.get("size") or 0),
        "mtime": pdf.get("mtime") or "",
        "title": title,
        "doi": pdf.get("doi"),
        "paper_slug": ov.get("paper_slug") or pdf.get("paper_slug"),
        "capture_count": int(pdf.get("capture_count") or 0),
        "pending_extract": int(pdf.get("pending_extract") or 0),
        "review_passed": int(pdf.get("review_passed") or 0),
        "review_failed": int(pdf.get("review_failed") or 0),
        "review_pending": int(pdf.get("review_pending") or 0),
        "unextracted": int(pdf.get("unextracted") or 0),
        "no_tables": bool(pdf.get("no_tables")),
        "si_status": pdf.get("si_status"),
        "si_file_count": int(pdf.get("si_file_count") or 0),
        "status": status,
        "tags": tags,
        "collection_ids": coll,
        "notes": str(ov.get("notes") or ""),
        "translated_pdf": ov.get("translated_pdf"),
        "updated_at": ov.get("updated_at") or utc_now_iso(),
    }


def list_items(
    *,
    q: str | None = None,
    collection_id: str | None = None,
    status: str | None = None,
    sync: bool = True,
) -> dict[str, Any]:
    store = sync_from_disk() if sync else load_library()
    pdfs = list_pdfs()
    overlays = store.get("items") or {}
    merged = [_merge_item(p, overlays.get(p["filename"])) for p in pdfs]

    if status and status in STATUS_CHOICES:
        merged = [m for m in merged if m["status"] == status]
    elif collection_id and collection_id not in ("all", "", None):
        if collection_id in ("unread", "reading", "done", "archived"):
            merged = [m for m in merged if m["status"] == collection_id]
        else:
            merged = [m for m in merged if collection_id in (m.get("collection_ids") or [])]

    if q:
        ql = q.strip().lower()
        if ql:
            def hit(m: dict[str, Any]) -> bool:
                hay = " ".join(
                    [
                        m.get("filename") or "",
                        m.get("title") or "",
                        m.get("doi") or "",
                        " ".join(m.get("tags") or []),
                        m.get("notes") or "",
                    ]
                ).lower()
                return ql in hay

            merged = [m for m in merged if hit(m)]

    # sort: status weight then mtime desc then name
    order = {"reading": 0, "unread": 1, "done": 2, "archived": 3}

    def sort_key(m: dict[str, Any]) -> tuple:
        return (
            order.get(m.get("status") or "unread", 9),
            -(0 if not m.get("mtime") else 1),
            m.get("mtime") or "",
            (m.get("filename") or "").lower(),
        )

    # mtime ISO sorts lexicographically; reverse by using reverse=True on mtime string
    merged.sort(
        key=lambda m: (
            order.get(m.get("status") or "unread", 9),
            (m.get("filename") or "").lower(),
        )
    )
    # Prefer newer mtime within status — secondary reverse sort
    merged.sort(key=lambda m: m.get("mtime") or "", reverse=True)
    merged.sort(key=lambda m: order.get(m.get("status") or "unread", 9))

    return {
        "collections": store.get("collections") or [],
        "items": merged,
        "total": len(merged),
        "updated_at": store.get("updated_at"),
    }


def get_item(filename: str, *, sync: bool = True) -> dict[str, Any] | None:
    data = list_items(sync=sync)
    for m in data["items"]:
        if m["filename"] == filename:
            return m
    # may be filtered out? re-merge single
    store = load_library(force=sync)
    pdfs = {p["filename"]: p for p in list_pdfs()}
    if filename not in pdfs:
        return None
    return _merge_item(pdfs[filename], (store.get("items") or {}).get(filename))


def patch_item(filename: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update overlay fields for a PDF. Validates file exists via list_pdfs."""
    pdfs = {p["filename"]: p for p in list_pdfs()}
    if filename not in pdfs:
        raise KeyError("PDF 不存在")
    store = load_library(force=True)
    items = store.setdefault("items", {})
    ov = dict(items.get(filename) or _default_item_overlay(filename))
    if "status" in patch and patch["status"] is not None:
        st = str(patch["status"]).strip()
        if st not in STATUS_CHOICES:
            raise ValueError(f"非法 status: {st}")
        ov["status"] = st
    if "tags" in patch and patch["tags"] is not None:
        if not isinstance(patch["tags"], list):
            raise ValueError("tags 须为数组")
        ov["tags"] = [str(t).strip() for t in patch["tags"] if str(t).strip()]
    if "collection_ids" in patch and patch["collection_ids"] is not None:
        if not isinstance(patch["collection_ids"], list):
            raise ValueError("collection_ids 须为数组")
        ov["collection_ids"] = [str(c).strip() for c in patch["collection_ids"] if str(c).strip()]
    if "notes" in patch and patch["notes"] is not None:
        ov["notes"] = str(patch["notes"])
    if "title_override" in patch:
        to = patch["title_override"]
        ov["title_override"] = (str(to).strip() if to else None) or None
    if "translated_pdf" in patch:
        ov["translated_pdf"] = patch["translated_pdf"] or None
    if "paper_slug" in patch and patch["paper_slug"]:
        ov["paper_slug"] = str(patch["paper_slug"])
    ov["filename"] = filename
    ov["updated_at"] = utc_now_iso()
    items[filename] = ov
    store["items"] = items
    save_library(store)
    return _merge_item(pdfs[filename], ov)


def list_collections() -> list[dict[str, Any]]:
    store = load_library()
    return list(store.get("collections") or [])


def create_collection(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("集合名称不能为空")
    store = load_library(force=True)
    cols = store.setdefault("collections", [])
    for c in cols:
        if (c.get("name") or "").strip() == name and not c.get("builtin"):
            raise ValueError("同名集合已存在")
    cid = "c_" + uuid.uuid4().hex[:10]
    col = {
        "id": cid,
        "name": name,
        "builtin": False,
        "created_at": utc_now_iso(),
    }
    cols.append(col)
    store["collections"] = cols
    save_library(store)
    return col


def rename_collection(collection_id: str, name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("集合名称不能为空")
    store = load_library(force=True)
    cols = store.get("collections") or []
    found = None
    for c in cols:
        if c.get("id") == collection_id:
            if c.get("builtin"):
                raise ValueError("内置集合不可改名")
            c["name"] = name
            found = c
            break
    if not found:
        raise KeyError("集合不存在")
    store["collections"] = cols
    save_library(store)
    return found


def delete_collection(collection_id: str) -> None:
    store = load_library(force=True)
    cols = store.get("collections") or []
    target = next((c for c in cols if c.get("id") == collection_id), None)
    if not target:
        raise KeyError("集合不存在")
    if target.get("builtin"):
        raise ValueError("内置集合不可删除")
    store["collections"] = [c for c in cols if c.get("id") != collection_id]
    # strip from items
    for fn, ov in (store.get("items") or {}).items():
        ids = ov.get("collection_ids") or []
        if collection_id in ids:
            ov["collection_ids"] = [x for x in ids if x != collection_id]
    save_library(store)


_SAFE_NAME = re.compile(r"^[^/\\]+$")


def is_safe_filename(name: str) -> bool:
    return bool(name and _SAFE_NAME.match(name) and name.lower().endswith(".pdf"))
