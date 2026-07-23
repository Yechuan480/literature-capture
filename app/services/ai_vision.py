"""Optional AI vision table extraction (OpenAI-compatible chat/completions)."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from app.services.ai_client import chat_complete, normalize_base_url
from app.services.ai_client import normalize_base_url as _normalize_base_url
from app.services.ai_client import api_headers as _api_headers
from app.services.ai_settings import load_ai_settings


def extract_table_ai(
    image_path: Path,
    settings: Any = None,  # kept for call-site compatibility; ignored in favor of runtime cfg
) -> list[list[str]] | None:
    """Call vision API for structured table JSON. Returns None if disabled or failed."""
    result = extract_table_ai_detailed(image_path)
    return result.get("matrix")


def extract_table_ai_detailed(image_path: Path) -> dict[str, Any]:
    """
    Returns {ok, matrix, error, model, caption, notes}.
    matrix is list[list[str]] on success; caption row prepended and notes
    appended when the model provides them.
    """
    cfg = load_ai_settings()
    if not cfg.get("enabled"):
        return {"ok": False, "matrix": None, "error": "AI 未启用", "model": cfg.get("model")}
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "matrix": None, "error": "未配置 API Key", "model": cfg.get("model")}

    model = (cfg.get("model") or "gpt-4o").strip()

    try:
        with image_path.open("rb") as f:
            raw = f.read()
        if not raw:
            return {"ok": False, "matrix": None, "error": "图片为空", "model": model}
        if len(raw) > 15 * 1024 * 1024:
            return {"ok": False, "matrix": None, "error": "图片过大（>15MB）", "model": model}
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png"
        if image_path.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"

        messages = [
            {
                "role": "system",
                "content": (
                    "You extract scientific tables from images, including "
                    "table title/caption (表题), column headers (表头), body cells, "
                    "and footnotes/notes below the table (表后附注/脚注/来源说明). "
                    "Respond with ONLY a JSON object (no markdown fences, no commentary):\n"
                    '{"caption":"<table title or empty>",'
                    '"matrix":[[...],[...]],'
                    '"notes":"<footnotes or empty>"}\n'
                    "matrix is a 2D string array: first row(s) = column headers, "
                    "then data rows. Merge multi-line cells with space; keep numbers "
                    "and units as shown; empty cells as \"\". "
                    "If multiple tables appear, extract the main/largest one. "
                    "You may also respond with only a 2D array for backward compatibility."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extract the main table in this image. Include:\n"
                            "1) caption/title above the table if present\n"
                            "2) full column headers + all body cells\n"
                            "3) footnotes/notes/source lines immediately below the table\n"
                            "Return JSON object {caption, matrix, notes} as specified."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            },
        ]
        result = chat_complete(
            messages,
            model=model,
            temperature=0,
            max_tokens=8192,
            timeout=120.0,
            cfg=cfg,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "matrix": None,
                "error": result.get("error") or "AI 调用失败",
                "model": model,
            }
        content = result.get("content") or ""
        parsed = _parse_table_payload(content)
        matrix = parsed.get("matrix")
        if not matrix:
            return {
                "ok": False,
                "matrix": None,
                "error": "AI 返回无法解析为表格矩阵",
                "model": model,
                "raw_preview": (content or "")[:400],
            }
        return {
            "ok": True,
            "matrix": matrix,
            "error": None,
            "model": model,
            "caption": parsed.get("caption") or "",
            "notes": parsed.get("notes") or "",
        }
    except Exception as e:
        return {"ok": False, "matrix": None, "error": f"{type(e).__name__}: {e}", "model": model}


def test_ai_connection() -> dict[str, Any]:
    """Lightweight text-only call to verify key / endpoint / model."""
    cfg = load_ai_settings()
    result = chat_complete(
        [{"role": "user", "content": "Reply with exactly: OK"}],
        temperature=0,
        max_tokens=8,
        timeout=45.0,
        cfg=cfg,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error") or "连接失败",
            "model": result.get("model"),
            "base_url": result.get("base_url")
            or normalize_base_url(cfg.get("base_url") or ""),
        }
    return {
        "ok": True,
        "model": result.get("model"),
        "base_url": result.get("base_url"),
        "reply": (result.get("content") or "").strip()[:80],
    }


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _coerce_matrix(data: Any) -> list[list[str]] | None:
    if not isinstance(data, list) or not data:
        return None
    rows: list[list[str]] = []
    for row in data:
        if isinstance(row, list):
            rows.append(["" if c is None else str(c).strip() for c in row])
        else:
            rows.append([str(row).strip()])
    return rows or None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, list):
                parts.append(" ".join("" if c is None else str(c).strip() for c in item).strip())
            else:
                parts.append(str(item).strip())
        return " ".join(p for p in parts if p).strip()
    return str(value).strip()


def _full_width_row(text: str, width: int) -> list[str]:
    w = max(1, width)
    row = [""] * w
    row[0] = text
    return row


def _assemble_matrix(
    *,
    caption: str,
    matrix: list[list[str]],
    notes: str,
) -> list[list[str]]:
    width = max((len(r) for r in matrix), default=1)
    width = max(width, 1)
    out: list[list[str]] = []
    cap = (caption or "").strip()
    if cap:
        # Avoid duplicating if model already put caption as first matrix row
        first = " ".join(matrix[0]).strip() if matrix else ""
        if first != cap and not first.startswith(cap[: min(40, len(cap))]):
            out.append(_full_width_row(cap, width))
    for row in matrix:
        out.append(list(row) + [""] * (width - len(row)))
    note = (notes or "").strip()
    if note:
        last = " ".join(out[-1]).strip() if out else ""
        if last != note and note not in last:
            # Multi-line notes → one row per line when short lines; else single row
            lines = [ln.strip() for ln in re.split(r"[\r\n]+", note) if ln.strip()]
            if len(lines) > 1 and all(len(ln) < 200 for ln in lines):
                for ln in lines:
                    out.append(_full_width_row(ln, width))
            else:
                out.append(_full_width_row(note, width))
    return out


def _parse_table_payload(content: str) -> dict[str, Any]:
    """
    Accept either:
      - legacy 2D array matrix
      - {caption, matrix, notes} object
    Always returns matrix with caption (top) and notes (bottom) folded in when present.
    """
    text = _strip_fences(content)
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Prefer object, then array
        m_obj = re.search(r"\{.*\}", text, re.DOTALL)
        m_arr = re.search(r"\[.*\]", text, re.DOTALL)
        for m in (m_obj, m_arr):
            if not m:
                continue
            try:
                data = json.loads(m.group(0))
                break
            except json.JSONDecodeError:
                continue
    if data is None:
        return {"matrix": None, "caption": "", "notes": ""}

    caption = ""
    notes = ""
    matrix: list[list[str]] | None = None

    if isinstance(data, dict):
        caption = _as_text(
            data.get("caption")
            or data.get("title")
            or data.get("table_title")
            or data.get("表题")
            or data.get("表头标题")
        )
        notes = _as_text(
            data.get("notes")
            or data.get("footnotes")
            or data.get("footnote")
            or data.get("footer")
            or data.get("表注")
            or data.get("附注")
        )
        raw_matrix = data.get("matrix") or data.get("table") or data.get("rows") or data.get("data")
        matrix = _coerce_matrix(raw_matrix)
        # Some models put headers separately
        headers = data.get("headers") or data.get("header") or data.get("columns")
        if matrix is not None and headers is not None:
            if isinstance(headers, list) and headers and not isinstance(headers[0], list):
                header_row = ["" if c is None else str(c).strip() for c in headers]
                first = matrix[0] if matrix else []
                if first != header_row:
                    matrix = [header_row] + matrix
    elif isinstance(data, list):
        matrix = _coerce_matrix(data)

    if not matrix:
        return {"matrix": None, "caption": caption, "notes": notes}

    assembled = _assemble_matrix(caption=caption, matrix=matrix, notes=notes)
    return {"matrix": assembled, "caption": caption, "notes": notes}


def _parse_matrix(content: str) -> list[list[str]] | None:
    """Backward-compatible helper used by older call sites / tests."""
    return _parse_table_payload(content).get("matrix")
