"""Region translation: pdfplumber crop text + vision fallback."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from app.paths import safe_pdf_path
from app.services.ai_client import chat_complete
from app.services.ai_settings import load_ai_settings
from app.services.translate.text import TARGET_LABEL, TARGET_LANG, translate_text


def _extract_region_text(
    pdf_path: Path,
    page: int,
    rect: dict[str, float],
    canvas: dict[str, float],
) -> str:
    """Map CSS top-left rect on rendered page → pdfplumber crop → text."""
    try:
        import pdfplumber
    except ImportError:
        return ""

    cw = float(canvas.get("w") or 0) or 1.0
    ch = float(canvas.get("h") or 0) or 1.0
    x = float(rect.get("x") or 0)
    y = float(rect.get("y") or 0)
    w = float(rect.get("w") or 0)
    h = float(rect.get("h") or 0)
    if w < 2 or h < 2:
        return ""

    with pdfplumber.open(str(pdf_path)) as pdf:
        if page < 1 or page > len(pdf.pages):
            return ""
        p = pdf.pages[page - 1]
        pw = float(p.width or 1)
        ph = float(p.height or 1)
        # CSS origin top-left; PDF origin bottom-left
        x0 = max(0.0, min(pw, x / cw * pw))
        x1 = max(0.0, min(pw, (x + w) / cw * pw))
        y_top_css = y / ch * ph
        y_bot_css = (y + h) / ch * ph
        # PDF y from bottom
        y1 = max(0.0, min(ph, ph - y_top_css))  # top of selection in PDF coords
        y0 = max(0.0, min(ph, ph - y_bot_css))  # bottom of selection
        if x1 <= x0 or y1 <= y0:
            return ""
        # pdfplumber crop: (x0, top, x1, bottom) with top > bottom in PDF space
        try:
            cropped = p.crop((x0, y0, x1, y1))
            text = cropped.extract_text() or ""
        except Exception:
            # try alternate order
            try:
                cropped = p.crop((x0, y1, x1, y0))
                text = cropped.extract_text() or ""
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
        }
    return {
        "ok": True,
        "translation": (result.get("content") or "").strip(),
        "error": None,
        "model": result.get("model"),
        "source": "vision",
    }


def translate_region(
    *,
    filename: str,
    page: int,
    rect: dict[str, float],
    canvas: dict[str, float],
    image_b64: str | None = None,
) -> dict[str, Any]:
    path = safe_pdf_path(filename)
    source_text = ""
    try:
        source_text = _extract_region_text(path, int(page), rect, canvas)
    except Exception:
        source_text = ""

    if len(source_text) >= 8:
        tr = translate_text(source_text, context=f"PDF {filename} p.{page}")
        return {
            "ok": bool(tr.get("ok")),
            "text": source_text,
            "translation": tr.get("translation") or "",
            "error": tr.get("error"),
            "model": tr.get("model"),
            "source": "text",
            "page": page,
            "filename": filename,
        }

    # vision fallback
    if image_b64:
        raw = image_b64
        if "," in raw and raw.strip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            data = b""
        if data:
            # optional: also try writing temp for debugging — not needed
            vt = _vision_translate_b64(base64.b64encode(data).decode("ascii"))
            return {
                **vt,
                "text": source_text,
                "page": page,
                "filename": filename,
            }

    if source_text:
        tr = translate_text(source_text, context=f"PDF {filename} p.{page}")
        return {
            "ok": bool(tr.get("ok")),
            "text": source_text,
            "translation": tr.get("translation") or "",
            "error": tr.get("error"),
            "model": tr.get("model"),
            "source": "text",
            "page": page,
            "filename": filename,
        }

    return {
        "ok": False,
        "text": "",
        "translation": "",
        "error": "无法提取文字：请框更大区域，或确认该页有可选中文本（扫描件需依赖视觉）",
        "model": None,
        "source": "none",
        "page": page,
        "filename": filename,
    }
