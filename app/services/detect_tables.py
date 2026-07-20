"""Detect table regions on PDF pages using PaddleX layout model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.services.paddle_runtime import ensure_detector, paddle_status
from app.services.pdf_render import page_count, render_page_rgb


def _result_to_dict(res: Any) -> dict[str, Any]:
    if res is None:
        return {}
    if isinstance(res, dict):
        return res
    js = getattr(res, "json", None)
    if callable(js):
        try:
            data = js()
            if isinstance(data, dict):
                # some versions nest under "res"
                if "boxes" in data:
                    return data
                if "res" in data and isinstance(data["res"], dict):
                    return data["res"]
                return data
        except Exception:
            pass
    elif isinstance(js, dict):
        if "boxes" in js:
            return js
        if "res" in js and isinstance(js["res"], dict):
            return js["res"]
        return js
    # fallback attributes
    boxes = getattr(res, "boxes", None)
    if boxes is not None:
        return {"boxes": boxes}
    return {}


def _extract_boxes(data: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = data.get("boxes")
    if boxes is None and isinstance(data.get("layout_det_res"), dict):
        boxes = data["layout_det_res"].get("boxes")
    if not boxes:
        return []
    out: list[dict[str, Any]] = []
    for b in boxes:
        if not isinstance(b, dict):
            continue
        label = str(b.get("label") or b.get("cls_label") or "").lower()
        # PicoDet_layout_1x_table is table-only (empty/any); multi-class needs filter
        if label and label not in ("table", "tables"):
            continue
        coord = b.get("coordinate") or b.get("bbox") or b.get("box")
        if coord is None:
            continue
        try:
            if isinstance(coord, dict):
                x1 = float(coord.get("xmin", coord.get("x1", 0)))
                y1 = float(coord.get("ymin", coord.get("y1", 0)))
                x2 = float(coord.get("xmax", coord.get("x2", 0)))
                y2 = float(coord.get("ymax", coord.get("y2", 0)))
            else:
                vals = list(coord)
                if len(vals) < 4:
                    continue
                x1, y1, x2, y2 = map(float, vals[:4])
        except Exception:
            continue
        score = b.get("score", b.get("confidence", 1.0))
        try:
            score_f = float(score)
        except Exception:
            score_f = 1.0
        out.append(
            {
                "label": label or "table",
                "score": score_f,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
        )
    return out


def detect_tables_in_pdf(
    pdf_path: Path,
    *,
    pages: list[int] | None = None,
    dpi: int | None = None,
    min_score: float | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Detect tables. `pages` is 1-based page numbers; None = all (respecting max_detect_pages).
    """
    settings = settings or get_settings()
    warnings: list[str] = []
    dpi = int(dpi or settings.paddle_detect_dpi or 150)
    min_score = float(
        min_score if min_score is not None else settings.paddle_min_score or 0.4
    )

    detector = ensure_detector(settings)
    if detector is None:
        st = paddle_status(settings)
        raise RuntimeError(st.get("paddle_error") or "Paddle 检测模型不可用")

    total = page_count(pdf_path)
    if pages:
        page_list = sorted({int(p) for p in pages if 1 <= int(p) <= total})
    else:
        page_list = list(range(1, total + 1))
        max_n = int(settings.paddle_max_detect_pages or 0)
        if max_n > 0 and len(page_list) > max_n:
            page_list = page_list[:max_n]
            warnings.append(f"仅检测前 {max_n} 页（paddle.max_detect_pages）")

    pages_out: list[dict[str, Any]] = []
    for page_1 in page_list:
        idx0 = page_1 - 1
        try:
            img, w, h = render_page_rgb(pdf_path, idx0, dpi=dpi)
        except Exception as e:
            warnings.append(f"第 {page_1} 页渲染失败: {e}")
            continue

        try:
            results = list(
                detector.predict(img, batch_size=1, layout_nms=True)
            )
        except TypeError:
            try:
                results = list(detector.predict(img))
            except Exception as e:
                warnings.append(f"第 {page_1} 页检测失败: {e}")
                continue
        except Exception as e:
            warnings.append(f"第 {page_1} 页检测失败: {e}")
            continue

        raw_boxes: list[dict[str, Any]] = []
        for res in results:
            data = _result_to_dict(res)
            raw_boxes.extend(_extract_boxes(data))

        boxes_out: list[dict[str, Any]] = []
        bi = 0
        for b in raw_boxes:
            if b["score"] < min_score:
                continue
            x1 = max(0.0, min(float(b["x1"]), float(w)))
            y1 = max(0.0, min(float(b["y1"]), float(h)))
            x2 = max(0.0, min(float(b["x2"]), float(w)))
            y2 = max(0.0, min(float(b["y2"]), float(h)))
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            nx = x1 / w if w else 0.0
            ny = y1 / h if h else 0.0
            nw = (x2 - x1) / w if w else 0.0
            nh = (y2 - y1) / h if h else 0.0
            boxes_out.append(
                {
                    "id": f"p{page_1}-{bi}",
                    "score": round(float(b["score"]), 4),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                    "nx": round(nx, 6),
                    "ny": round(ny, 6),
                    "nw": round(nw, 6),
                    "nh": round(nh, 6),
                }
            )
            bi += 1

        if boxes_out:
            pages_out.append(
                {
                    "page": page_1,
                    "width": w,
                    "height": h,
                    "boxes": boxes_out,
                }
            )

    return {
        "filename": pdf_path.name,
        "dpi": dpi,
        "engine": "paddlex_layout",
        "page_count": total,
        "pages": pages_out,
        "warnings": warnings,
        "min_score": min_score,
        "box_count": sum(len(p["boxes"]) for p in pages_out),
    }
