"""Library API: collections + paper items overlay."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import library_store as lib

router = APIRouter(prefix="/api/library", tags=["library"])


class CollectionCreate(BaseModel):
    name: str


class CollectionPatch(BaseModel):
    name: str


class ItemPatch(BaseModel):
    status: str | None = None
    tags: list[str] | None = None
    collection_ids: list[str] | None = None
    notes: str | None = None
    title_override: str | None = None
    translated_pdf: str | None = None


@router.get("/collections")
def get_collections():
    return {"collections": lib.list_collections()}


@router.post("/collections")
def post_collection(body: CollectionCreate):
    try:
        col = lib.create_collection(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return col


@router.patch("/collections/{collection_id}")
def patch_collection(collection_id: str, body: CollectionPatch):
    try:
        return lib.rename_collection(collection_id, body.name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/collections/{collection_id}")
def remove_collection(collection_id: str):
    try:
        lib.delete_collection(collection_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "id": collection_id}


@router.get("/items")
def get_items(
    q: str | None = Query(None),
    collection_id: str | None = Query(None),
    status: str | None = Query(None),
    sync: bool = Query(True),
):
    return lib.list_items(q=q, collection_id=collection_id, status=status, sync=sync)


@router.get("/items/{filename}")
def get_one_item(filename: str):
    if not lib.is_safe_filename(filename):
        raise HTTPException(status_code=400, detail="非法文件名")
    item = lib.get_item(filename)
    if not item:
        raise HTTPException(status_code=404, detail="文献不存在")
    return item


@router.patch("/items/{filename}")
def patch_one_item(filename: str, body: ItemPatch):
    if not lib.is_safe_filename(filename):
        raise HTTPException(status_code=400, detail="非法文件名")
    try:
        return lib.patch_item(filename, body.model_dump(exclude_unset=True))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sync")
def sync_library():
    store = lib.sync_from_disk()
    data = lib.list_items(sync=False)
    return {
        "ok": True,
        "total": data["total"],
        "updated_at": store.get("updated_at"),
        "collections": data["collections"],
    }
