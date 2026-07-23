"""FastAPI entrypoint: API + static UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.models.schemas import HealthResponse
from app.routers import capture, detect, papers, review, settings as settings_router, si
from app.services.ai_settings import ai_ready, public_ai_status
from app.services.extract_table import ocr_status

settings = get_settings()
settings.ensure_dirs()

app = FastAPI(title="Literature Table Capture", version="1.3.0")
app.include_router(papers.router)
app.include_router(capture.router)
app.include_router(settings_router.router)
app.include_router(review.router)
app.include_router(detect.router)
app.include_router(si.router)

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
    }


def _asset_v(rel: str) -> str:
    """Cache-bust query from file mtime."""
    p = STATIC_DIR / rel
    try:
        return str(int(p.stat().st_mtime))
    except OSError:
        return "1"


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for rel in (
        "css/app.css",
        "js/pdf_viewer.js",
        "js/region_select.js",
        "js/app.js",
    ):
        v = _asset_v(rel)
        html = html.replace(f'href="/static/{rel}"', f'href="/static/{rel}?v={v}"')
        html = html.replace(f'src="/static/{rel}"', f'src="/static/{rel}?v={v}"')
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/review")
def review_page():
    html = (STATIC_DIR / "review.html").read_text(encoding="utf-8")
    for rel in ("css/app.css", "css/review.css", "js/review.js"):
        v = _asset_v(rel)
        html = html.replace(f'href="/static/{rel}"', f'href="/static/{rel}?v={v}"')
        html = html.replace(f'src="/static/{rel}"', f'src="/static/{rel}?v={v}"')
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
