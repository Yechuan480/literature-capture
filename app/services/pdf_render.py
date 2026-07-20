"""Server-side PDF page rasterization via pypdfium2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def page_count(pdf_path: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def render_page_rgb(
    pdf_path: Path,
    page_index: int,
    *,
    dpi: int = 150,
) -> tuple[np.ndarray, int, int]:
    """
    Render a 0-based page to RGB uint8 array (H, W, 3).
    Returns (array, width, height).
    """
    import pypdfium2 as pdfium

    if dpi < 36 or dpi > 400:
        raise ValueError("dpi out of range (36-400)")

    scale = float(dpi) / 72.0
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        n = len(doc)
        if page_index < 0 or page_index >= n:
            raise IndexError(f"page_index {page_index} out of range 0..{n-1}")
        page = doc[page_index]
        bitmap = page.render(scale=scale, rotation=0)
        pil = bitmap.to_pil()
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        arr = np.asarray(pil)
        h, w = int(arr.shape[0]), int(arr.shape[1])
        return arr, w, h
    finally:
        doc.close()


def render_pages(
    pdf_path: Path,
    page_indices: list[int],
    *,
    dpi: int = 150,
) -> list[dict[str, Any]]:
    """Render multiple 0-based pages. Each item: page_index, width, height, image(ndarray)."""
    out: list[dict[str, Any]] = []
    for idx in page_indices:
        img, w, h = render_page_rgb(pdf_path, idx, dpi=dpi)
        out.append({"page_index": idx, "width": w, "height": h, "image": img})
    return out
