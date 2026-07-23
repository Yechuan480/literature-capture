"""Region translation: accurate CSS→PDF crop + multi-provider + vision fallback."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from app.paths import safe_pdf_path
from app.services.ai_client import chat_complete
from app.services.ai_settings import load_ai_settings
from app.services.translate.providers import translate_with_provider
from app.services.translate.text import TARGET_LABEL, TARGET_LANG


def _map_css_point_to_page(
    css_x: float,
    css_y: float,
    cw: float,
    ch: float,
    pw: float,
    ph: float,
    rotation: int,
) -> tuple[float, float]:
    """Map a CSS point on the rendered (possibly rotated) canvas to page
    coordinates with origin at the **top-left** of the unrotated media box.
    """
    cw = cw or 1.0
    ch = ch or 1.0
    fx = max(0.0, min(1.0, css_x / cw))
    fy = max(0.0, min(1.0, css_y / ch))
    rot = int(rotation or 0) % 360
    # Snap to 90°
    rot = (round(rot / 90) * 90) % 360

    if rot == 0:
        return fx * pw, fy * ph
    if rot == 90:
        # Canvas top-left ≈ page bottom-left; x→up page, y→right on page
        return fy * pw, (1.0 - fx) * ph
    if rot == 180:
        return (1.0 - fx) * pw, (1.0 - fy) * ph
    if rot == 270:
        return (1.0 - fy) * pw, fx * ph
    return fx * pw, fy * ph


def _css_rect_to_pdfplumber_bbox(
    rect: dict[str, float],
    canvas: dict[str, float],
    pw: float,
    ph: float,
    rotation: int,
) -> tuple[float, float, float, float] | None:
    """Return pdfplumber crop bbox (x0, top, x1, bottom) — top-left origin."""
    cw = float(canvas.get("w") or 0) or 1.0
    ch = float(canvas.get("h") or 0) or 1.0
    x = float(rect.get("x") or 0)
    y = float(rect.get("y") or 0)
    w = float(rect.get("w") or 0)
    h = float(rect.get("h") or 0)
    if w < 2 or h < 2:
        return None

    corners = [
        (x, y),
        (x + w, y),
        (x, y + h),
        (x + w, y + h),
    ]
    pts = [
        _map_css_point_to_page(cx, cy, cw, ch, pw, ph, rotation) for cx, cy in corners
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0 = max(0.0, min(pw, min(xs)))
    x1 = max(0.0, min(pw, max(xs)))
    top = max(0.0, min(ph, min(ys)))
    bottom = max(0.0, min(ph, max(ys)))
    # slight pad to avoid clipping glyphs on edges
    pad = 1.5
    x0 = max(0.0, x0 - pad)
    top = max(0.0, top - pad)
    x1 = min(pw, x1 + pad)
    bottom = min(ph, bottom + pad)
    if x1 - x0 < 2 or bottom - top < 2:
        return None
    return (x0, top, x1, bottom)


def _extract_region_text(
    pdf_path: Path,
    page: int,
    rect: dict[str, float],
    canvas: dict[str, float],
    rotation: int = 0,
) -> str:
    """Map CSS rect on rendered page → pdfplumber crop → text."""
    try:
        import pdfplumber
    except ImportError:
        return ""

    with pdfplumber.open(str(pdf_path)) as pdf:
        if page < 1 or page > len(pdf.pages):
            return ""
        p = pdf.pages[page - 1]
        pw = float(p.width or 1)
        ph = float(p.height or 1)
        bbox = _css_rect_to_pdfplumber_bbox(rect, canvas, pw, ph, rotation)
        if not bbox:
            return ""
        try:
            cropped = p.crop(bbox)
            text = cropped.extract_text() or ""
        except Exception:
            text = ""
        if not (text or "").strip():
            # Fallback: words intersecting bbox
            try:
                words = p.within_bbox(bbox).extract_text() or ""
                text = words
            except Exception:
                try:
                    words = p.extract_words() or []
                    x0, top, x1, bottom = bbox
                    kept = []
                    for w in words:
                        wx0 = float(w.get("x0", 0))
                        wx1 = float(w.get("x1", 0))
                        wt = float(w.get("top", 0))
                        wb = float(w.get("bottom", 0))
                        if wx1 < x0 or wx0 > x1 or wb < top or wt > bottom:
                            continue
                        kept.append(w.get("text") or "")
                    text = " ".join(t for t in kept if t)
                except Exception:
                    text = ""
        return (text or "").strip()


def _vision_translate_b64(b64: str, mime: str = "image/png") -> dict[str, Any]:
    cfg = load_ai_settings()
    messages = [
        {
            "role": "system",
            "content": (
                f"你是学术翻译。阅读图片中的文字，翻译成{TARGET_LABEL}（{TARGET_LANG}）。"
                "只输出译文，保留数字与专业符号。若几乎无文字，输出（无可识别文字）。"
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请翻译图中文字为中文。"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ],
        },
    ]
    result = chat_complete(
        messages,
        temperature=0.2,
        max_tokens=4096,
        timeout=120.0,
        cfg=cfg,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "translation": "",
            "error": result.get("error"),
            "model": result.get("model"),
            "source": "vision",
            "provider": "ai",
        }
    return {
        "ok": True,
        "translation": (result.get("content") or "").strip(),
        "error": None,
        "model": result.get("model"),
        "source": "vision",
        "provider": "ai",
    }


def translate_region(
    *,
    filename: str,
    page: int,
    rect: dict[str, float],
    canvas: dict[str, float],
    image_b64: str | None = None,
    rotation: int = 0,
    provider: str | None = None,
    prefer_vision: bool = False,
) -> dict[str, Any]:
    path = safe_pdf_path(filename)
    source_text = ""
    try:
        source_text = _extract_region_text(
            path, int(page), rect, canvas, rotation=int(rotation or 0)
        )
    except Exception:
        source_text = ""

    # Prefer vision when user asked, or text is too short but image present,
    # or page is rotated and text looks suspicious vs image.
    use_vision_first = bool(prefer_vision) and bool(image_b64)

    def _vision() -> dict[str, Any] | None:
        if not image_b64:
            return None
        raw = image_b64
        if "," in raw and raw.strip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            data = b""
        if not data:
            return None
        vt = _vision_translate_b64(base64.b64encode(data).decode("ascii"))
        return {
            **vt,
            "text": source_text,
            "page": page,
            "filename": filename,
        }

    if use_vision_first:
        vt = _vision()
        if vt and vt.get("ok"):
            return vt

    if len(source_text) >= 4:
        tr = translate_with_provider(
            source_text,
            provider=provider,
            context=f"PDF {filename} p.{page}",
        )
        return {
            "ok": bool(tr.get("ok")),
            "text": source_text,
            "translation": tr.get("translation") or "",
            "error": tr.get("error"),
            "model": tr.get("model"),
            "source": "text",
            "provider": tr.get("provider") or provider or "ai",
            "page": page,
            "filename": filename,
        }

    # text weak → vision (AI only)
    vt = _vision()
    if vt:
        return vt

    if source_text:
        tr = translate_with_provider(
            source_text,
            provider=provider,
            context=f"PDF {filename} p.{page}",
        )
        return {
            "ok": bool(tr.get("ok")),
            "text": source_text,
            "translation": tr.get("translation") or "",
            "error": tr.get("error"),
            "model": tr.get("model"),
            "source": "text",
            "provider": tr.get("provider") or provider or "ai",
            "page": page,
            "filename": filename,
        }

    return {
        "ok": False,
        "text": "",
        "translation": "",
        "error": (
            "无法提取选区文字。可：① 框更贴合正文的区域；"
            "② 旋转归零后再选；③ 选用 AI 并依赖视觉（需已配置 Key）；"
            "④ 扫描件无文本层时必须用 AI 视觉。"
        ),
        "model": None,
        "source": "none",
        "provider": provider or "ai",
        "page": page,
        "filename": filename,
    }
