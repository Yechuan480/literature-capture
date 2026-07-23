"""FastAPI entrypoint: API + static UI (library shell + capture/review)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.models.schemas import HealthResponse
from app.routers import (
    capture,
    chat,
    detect,
    library,
    papers,
    review,
    settings as settings_router,
    scholar,
    si,
    translate,
)
from app.services.ai_settings import ai_ready, public_ai_status
from app.services.extract_table import ocr_status

settings = get_settings()
settings.ensure_dirs()

app = FastAPI(title="Literature Reader", version="1.6.7")
app.include_router(papers.router)
app.include_router(capture.router)
app.include_router(settings_router.router)
app.include_router(review.router)
app.include_router(detect.router)
app.include_router(si.router)
app.include_router(library.router)
app.include_router(chat.router)
app.include_router(translate.router)
app.include_router(scholar.router)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Local tool: always revalidate JS/CSS so UI changes are not stuck behind cache."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") and path.endswith(
            (".js", ".css", ".html", ".mjs")
        ):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheStaticMiddleware)


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        literature_root=str(settings.literature_root),
        pdfs_root=str(settings.pdfs_root),
        captures_root=str(settings.captures_root),
        ocr=ocr_status(settings),
        ai_enabled=ai_ready(),
    )


@app.get("/api/config")
def public_config():
    ai = public_ai_status()
    ocr = ocr_status(settings)
    return {
        "literature_root": str(settings.literature_root),
        "pdfs_root": str(settings.pdfs_root),
        "captures_root": str(settings.captures_root),
        "ocr": ocr,
        "ai_enabled": bool(ai.get("ready")),
        "ai": ai,
        "si": {
            "enabled": bool(settings.si_enabled),
            "auto_on_open": bool(settings.si_auto_on_open),
        },
        "features": {
            "library": True,
            "reader": True,
            "chat": True,
            "translate": True,
            "scholar": True,
        },
    }


def _asset_v(rel: str) -> str:
    """Cache-bust query from file mtime."""
    p = STATIC_DIR / rel
    try:
        return str(int(p.stat().st_mtime))
    except OSError:
        return "1"


def _serve_html(rel: str, assets: list[str]) -> Response:
    html = (STATIC_DIR / rel).read_text(encoding="utf-8")
    for asset in assets:
        v = _asset_v(asset)
        html = html.replace(f'href="/static/{asset}"', f'href="/static/{asset}?v={v}"')
        html = html.replace(f'src="/static/{asset}"', f'src="/static/{asset}?v={v}"')
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/")
def library_page():
    return _serve_html(
        "library.html",
        ["css/app.css", "css/shell.css", "css/library.css", "js/shell.js", "js/library.js"],
    )


@app.get("/capture")
def capture_page():
    return _serve_html(
        "index.html",
        [
            "css/app.css",
            "css/shell.css",
            "js/shell.js",
            "js/pdf_viewer.js",
            "js/region_select.js",
            "js/app.js",
        ],
    )


@app.get("/read")
def read_page():
    return _serve_html(
        "reader.html",
        [
            "css/app.css",
            "css/shell.css",
            "css/reader.css",
            "js/shell.js",
            "js/pdf_viewer.js",
            "js/region_select.js",
            "js/reader.js",
        ],
    )


@app.get("/settings")
def settings_page():
    return _serve_html(
        "settings.html",
        ["css/app.css", "css/shell.css", "js/shell.js"],
    )


@app.get("/review")
def review_page():
    return _serve_html(
        "review.html",
        [
            "css/app.css",
            "css/shell.css",
            "css/review.css",
            "js/shell.js",
            "js/review.js",
        ],
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
