"""Pydantic schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PaperItem(BaseModel):
    filename: str
    size: int
    mtime: str
    capture_count: int = 0
    paper_slug: str | None = None
    no_tables: bool = False
    title: str | None = None


class TitleResponse(BaseModel):
    filename: str
    title: str
    source: str
    candidates: list[dict[str, str]] = Field(default_factory=list)


class SessionRequest(BaseModel):
    filename: str
    title: str


class SessionResponse(BaseModel):
    filename: str
    title: str
    paper_slug: str
    folder: str
    table_counter: int
    no_tables: bool = False


class PaperStatusRequest(BaseModel):
    filename: str
    title: str
    no_tables: bool = True


class PaperStatusResponse(BaseModel):
    filename: str
    title: str
    paper_slug: str
    folder: str
    no_tables: bool
    capture_count: int = 0


class PaperDeleteRequest(BaseModel):
    filename: str
    delete_captures: bool = True


class PaperDeleteResponse(BaseModel):
    filename: str
    deleted_pdf: str
    deleted_captures: list[str] = Field(default_factory=list)


class CaptureListResponse(BaseModel):
    paper_slug: str
    title: str
    folder: str
    captures: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    literature_root: str
    captures_root: str
    ocr: dict[str, Any]
    ai_enabled: bool
    pdfs_root: str | None = None
