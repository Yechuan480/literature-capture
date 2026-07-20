"""Local table extraction from screenshot images."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image

from app.config import Settings, get_settings
from app.services.ai_settings import ai_ready
from app.services.ai_vision import extract_table_ai_detailed
from app.services.paddle_runtime import paddle_status, paddlex_importable

_TESSERACT_OK: bool | None = None
_RAPIDOCR: Any = None


def tesseract_available() -> bool:
    global _TESSERACT_OK
    if _TESSERACT_OK is None:
        if shutil.which("tesseract") is not None:
            _TESSERACT_OK = True
        else:
            # Common Homebrew / Mac paths when PATH is minimal (e.g. launchd)
            for candidate in (
                "/opt/homebrew/bin/tesseract",
                "/usr/local/bin/tesseract",
            ):
                if Path(candidate).is_file():
                    # Ensure img2table/TesseractOCR can find it via PATH
                    import os

                    bindir = str(Path(candidate).parent)
                    os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
                    _TESSERACT_OK = True
                    break
            else:
                _TESSERACT_OK = False
    return _TESSERACT_OK


def resolve_engine(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    engine = (settings.ocr_engine or "auto").lower()
    if engine == "auto":
        # Prefer PP-TableMagic when configured + importable (load models lazily on extract)
        if settings.paddle_enabled and paddlex_importable():
            return "paddlex"
        if tesseract_available():
            return "img2table_tesseract"
        return "rapidocr"
    if engine == "paddlex":
        if settings.paddle_enabled and paddlex_importable():
            return "paddlex"
        return "img2table_tesseract" if tesseract_available() else "rapidocr"
    return engine


def ocr_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    engine = resolve_engine(settings)
    pst = paddle_status(settings)
    hint = None
    if engine in ("rapidocr",) and not tesseract_available() and not pst.get("paddle_recognize"):
        hint = (
            "未检测到 tesseract / Paddle，将使用 RapidOCR 后备。"
            "建议: brew install tesseract tesseract-lang；"
            "或 pip install paddlepaddle 'paddlex[ocr]'"
        )
    elif not tesseract_available() and not pst.get("paddle_recognize"):
        hint = "未检测到 tesseract，将使用 RapidOCR 后备。建议: brew install tesseract tesseract-lang"
    return {
        "engine": engine,
        "configured": settings.ocr_engine,
        "tesseract_available": tesseract_available(),
        "lang": settings.ocr_lang,
        "paddle_available": bool(pst.get("paddle_available")),
        "paddle_detect": bool(pst.get("paddle_detect")),
        "paddle_recognize": bool(pst.get("paddle_recognize")),
        "paddle_error": pst.get("paddle_error"),
        "paddle_configured": bool(settings.paddle_enabled),
        "hint": hint,
    }


def _prepare_image(image_path: Path, min_side: int) -> Path:
    """Optionally upscale small images for better OCR; may write a temp sibling."""
    img = Image.open(image_path)
    w, h = img.size
    short = min(w, h)
    if short >= min_side:
        return image_path
    scale = min_side / short
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    up = img.resize(new_size, Image.Resampling.LANCZOS)
    out = image_path.with_name(image_path.stem + "_ocrprep.png")
    up.save(out, format="PNG")
    return out


def _df_from_matrix(matrix: list[list[str]]) -> pd.DataFrame:
    if not matrix:
        return pd.DataFrame()
    width = max(len(r) for r in matrix)
    norm = [list(r) + [""] * (width - len(r)) for r in matrix]
    df = pd.DataFrame(norm)
    # Drop fully empty rows/cols
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    df = df.fillna("")
    df.columns = [str(c) for c in range(df.shape[1])]
    df = df.reset_index(drop=True)
    return df


def _extract_img2table(image_path: Path, lang: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    try:
        from img2table.document import Image as Img2TableImage
        from img2table.ocr import TesseractOCR
    except ImportError as e:
        warnings.append(f"img2table 不可用: {e}")
        return pd.DataFrame(), warnings

    # Prefer requested lang; fall back to eng if chi not installed
    langs_try = [lang, "eng"]
    last_err: Exception | None = None
    for lg in langs_try:
        try:
            ocr = TesseractOCR(n_threads=1, lang=lg)
            doc = Img2TableImage(src=str(image_path))
            tables = doc.extract_tables(
                ocr=ocr,
                implicit_rows=True,
                implicit_columns=True,
                borderless_tables=True,
                min_confidence=50,
            )
            if not tables:
                warnings.append("未检测到表格结构")
                return pd.DataFrame(), warnings
            # Largest table by cell count
            best = max(tables, key=lambda t: (t.df.shape[0] * max(t.df.shape[1], 1)))
            df = best.df.copy()
            df = df.fillna("")
            df.columns = [str(c) for c in range(df.shape[1])]
            df = df.replace(r"^\s*$", pd.NA, regex=True)
            df = df.dropna(axis=0, how="all").dropna(axis=1, how="all").fillna("")
            df = df.reset_index(drop=True)
            if df.empty:
                warnings.append("表格为空")
            return df, warnings
        except Exception as e:
            last_err = e
            continue
    warnings.append(f"img2table/Tesseract 失败: {last_err}")
    return pd.DataFrame(), warnings


def _get_rapidocr():
    global _RAPIDOCR
    if _RAPIDOCR is None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _RAPIDOCR = RapidOCR()
    return _RAPIDOCR


def _parse_rapidocr_result(result: Any) -> list[tuple[Any, str, float]]:
    """Normalize RapidOCR outputs across package versions."""
    if result is None:
        return []
    # rapidocr >=3 returns an object with boxes/txts/scores
    txts = getattr(result, "txts", None)
    if txts is not None:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        txt_list = list(txts)
        scores_raw = getattr(result, "scores", None)
        score_list = list(scores_raw) if scores_raw is not None else [1.0] * len(txt_list)
        out: list[tuple[Any, str, float]] = []
        for i, text in enumerate(txt_list):
            box = boxes[i]
            score = float(score_list[i]) if i < len(score_list) else 1.0
            out.append((box, str(text), score))
        return out
    # older rapidocr-onnxruntime: (list[[box, text, score]], elapse) or list
    if isinstance(result, tuple):
        result = result[0]
    if result is None:
        return []
    out = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            box, text = item[0], item[1]
            score = float(item[2]) if len(item) > 2 else 1.0
            out.append((box, str(text), score))
    return out


def _html_to_df(html: str) -> pd.DataFrame:
    if not html or not str(html).strip():
        return pd.DataFrame()
    tables = None
    for flavor in ("lxml", "bs4", "html5lib"):
        try:
            tables = pd.read_html(str(html), flavor=flavor)
            if tables:
                break
        except Exception:
            tables = None
            continue
    if not tables:
        # Minimal fallback without optional parsers
        try:
            from html.parser import HTMLParser

            class _T(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.rows: list[list[str]] = []
                    self._row: list[str] | None = None
                    self._cell: list[str] | None = None
                    self._in_table = False

                def handle_starttag(self, tag, attrs):
                    t = tag.lower()
                    if t == "table":
                        self._in_table = True
                    elif self._in_table and t == "tr":
                        self._row = []
                    elif self._in_table and t in ("td", "th"):
                        self._cell = []

                def handle_endtag(self, tag):
                    t = tag.lower()
                    if t in ("td", "th") and self._cell is not None:
                        text = "".join(self._cell).strip()
                        if self._row is not None:
                            self._row.append(text)
                        self._cell = None
                    elif t == "tr" and self._row is not None:
                        self.rows.append(self._row)
                        self._row = None
                    elif t == "table":
                        self._in_table = False

                def handle_data(self, data):
                    if self._cell is not None:
                        self._cell.append(data)

            p = _T()
            p.feed(str(html))
            if not p.rows:
                return pd.DataFrame()
            return _df_from_matrix(p.rows)
        except Exception:
            return pd.DataFrame()
    best = max(tables, key=lambda t: int(t.shape[0]) * max(int(t.shape[1]), 1))
    df = best.copy()
    df = df.fillna("")
    df.columns = [str(c) for c in range(df.shape[1])]
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all").fillna("")
    df = df.reset_index(drop=True)
    return df


def _extract_paddlex(image_path: Path, settings: Settings | None = None) -> tuple[pd.DataFrame, list[str]]:
    """PP-TableMagic (table_recognition_v2) on a cropped table image."""
    from app.services.paddle_runtime import ensure_recognizer

    warnings: list[str] = []
    settings = settings or get_settings()
    pipe = ensure_recognizer(settings)
    if pipe is None:
        st = paddle_status(settings)
        warnings.append(st.get("paddle_error") or "Paddle 识别管线不可用")
        return pd.DataFrame(), warnings

    try:
        results = list(
            pipe.predict(
                input=str(image_path),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_layout_detection=False,
            )
        )
    except TypeError:
        try:
            results = list(pipe.predict(input=str(image_path)))
        except Exception as e:
            return pd.DataFrame(), [f"PaddleX 识别失败: {e}"]
    except Exception as e:
        return pd.DataFrame(), [f"PaddleX 识别失败: {e}"]

    htmls: list[str] = []
    for res in results:
        data = res
        if hasattr(res, "json"):
            js = res.json
            data = js() if callable(js) else js
        if not isinstance(data, dict):
            continue
        if "res" in data and isinstance(data["res"], dict):
            data = data["res"]
        table_list = data.get("table_res_list") or []
        if isinstance(table_list, list):
            for t in table_list:
                if isinstance(t, dict) and t.get("pred_html"):
                    htmls.append(str(t["pred_html"]))
        if data.get("pred_html"):
            htmls.append(str(data["pred_html"]))

    if not htmls:
        warnings.append("PaddleX 未返回表格 HTML")
        return pd.DataFrame(), warnings

    best_df = pd.DataFrame()
    best_score = -1
    for html in htmls:
        df = _html_to_df(html)
        score = int(df.shape[0]) * max(int(df.shape[1]), 1)
        if score > best_score:
            best_score = score
            best_df = df

    if best_df.empty:
        warnings.append("PaddleX HTML 解析为空表")
    else:
        warnings.append("已使用 PP-TableMagic (table_recognition_v2)")
    return best_df, warnings


def _extract_rapidocr(image_path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Cluster OCR boxes into a crude table by y then x."""
    warnings: list[str] = ["使用 RapidOCR 粗网格（建议安装 tesseract 以获得更好结构识别）"]
    try:
        engine = _get_rapidocr()
        result = engine(str(image_path))
        parsed = _parse_rapidocr_result(result)
    except Exception as e:
        return pd.DataFrame(), [f"RapidOCR 失败: {e}"]

    if not parsed:
        return pd.DataFrame(), warnings + ["未识别到文字"]

    # items: box (4 points), text, score
    items: list[tuple[float, float, float, str]] = []
    for box, text, score in parsed:
        if not text or not str(text).strip():
            continue
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
        except Exception:
            continue
        cx = sum(xs) / 4.0
        cy = sum(ys) / 4.0
        h = max(ys) - min(ys)
        items.append((cy, cx, max(h, 1.0), str(text).strip()))

    if not items:
        return pd.DataFrame(), warnings + ["未识别到文字"]

    items.sort(key=lambda t: (t[0], t[1]))
    # Row cluster by y
    rows_boxes: list[list[tuple[float, float, float, str]]] = []
    for it in items:
        cy, cx, h, text = it
        if not rows_boxes:
            rows_boxes.append([it])
            continue
        prev = rows_boxes[-1]
        prev_cy = sum(x[0] for x in prev) / len(prev)
        thr = max(8.0, sum(x[2] for x in prev) / len(prev) * 0.6)
        if abs(cy - prev_cy) <= thr:
            prev.append(it)
        else:
            rows_boxes.append([it])

    matrix: list[list[str]] = []
    for row in rows_boxes:
        row_sorted = sorted(row, key=lambda t: t[1])
        matrix.append([t[3] for t in row_sorted])

    df = _df_from_matrix(matrix)
    return df, warnings


def extract_table(
    image_path: Path,
    *,
    use_ai: bool = False,
    force_engine: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Extract table from PNG.
    force_engine: None|auto|paddlex|img2table_tesseract|rapidocr|ai
      - ai: skip local OCR, vision only
      - paddlex / rapidocr / img2table_tesseract: force that path (AI only if use_ai)
    Returns {dataframe, engine, warnings, rows, cols}.
    """
    settings = settings or get_settings()
    warnings: list[str] = []
    work_path = image_path
    prep_path: Path | None = None
    try:
        prep_path = _prepare_image(image_path, settings.upscale_min_side)
        work_path = prep_path
    except Exception as e:
        warnings.append(f"图像预处理跳过: {e}")
        work_path = image_path

    forced = (force_engine or "").strip().lower() or None
    if forced in ("auto", ""):
        forced = None

    df = pd.DataFrame()
    source = "none"

    # --- AI-only strategy ---
    if forced == "ai":
        if not ai_ready():
            warnings.append("AI 未配置/未启用")
        else:
            ai_res = extract_table_ai_detailed(image_path)
            if ai_res.get("ok") and ai_res.get("matrix"):
                df = _df_from_matrix(ai_res["matrix"])
                source = "ai_vision"
                model = ai_res.get("model") or ""
                warnings.append(f"已使用 AI 视觉结果{f'（{model}）' if model else ''}")
            else:
                warnings.append(f"AI: {ai_res.get('error') or '提取失败'}")
    else:
        # --- Local strategies ---
        if forced == "rapidocr":
            engine = "rapidocr"
        elif forced == "img2table_tesseract":
            engine = "img2table_tesseract"
        elif forced in ("paddlex", "pp-tablemagic", "table_recognition_v2"):
            engine = "paddlex"
        else:
            engine = resolve_engine(settings)

        if engine == "paddlex":
            df, w = _extract_paddlex(work_path, settings)
            warnings.extend(w)
            source = "paddlex" if not df.empty else "paddlex"
            if df.empty:
                # fall through to tesseract / rapidocr
                if tesseract_available():
                    df2, w2 = _extract_img2table(work_path, settings.ocr_lang)
                    warnings.extend(w2)
                    if not df2.empty:
                        df = df2
                        source = "img2table_tesseract"
                if df.empty:
                    df2, w2 = _extract_rapidocr(work_path)
                    warnings.extend(w2)
                    if not df2.empty:
                        df = df2
                        source = "rapidocr"
        elif engine == "img2table_tesseract" and tesseract_available():
            df, w = _extract_img2table(work_path, settings.ocr_lang)
            warnings.extend(w)
            source = "img2table_tesseract"
        else:
            if engine == "img2table_tesseract" and not tesseract_available():
                warnings.append("配置为 tesseract 但未安装，回退 RapidOCR")
            if engine == "paddlex":
                pass
            else:
                df, w = _extract_rapidocr(work_path)
                warnings.extend(w)
                source = "rapidocr"

        # AI enhancement / fallback
        want_ai = use_ai or df.empty
        if want_ai and ai_ready():
            ai_res = extract_table_ai_detailed(image_path)
            if ai_res.get("ok") and ai_res.get("matrix"):
                df_ai = _df_from_matrix(ai_res["matrix"])
                if not df_ai.empty:
                    df = df_ai
                    source = "ai_vision"
                    model = ai_res.get("model") or ""
                    warnings.append(f"已使用 AI 视觉结果{f'（{model}）' if model else ''}")
            elif use_ai:
                warnings.append(f"AI: {ai_res.get('error') or '提取失败'}")
        elif use_ai and not ai_ready():
            warnings.append("已勾选 AI 但未配置/未启用（请在右侧「AI 设置」中填写 API Key）")

    if df.empty:
        # Last resort: rapidocr if not already used
        if source != "rapidocr" and forced != "ai":
            df2, w2 = _extract_rapidocr(work_path)
            warnings.extend(w2)
            if not df2.empty:
                df = df2
                source = "rapidocr_fallback"
        if df.empty:
            df = pd.DataFrame({"raw_text": [""]})
            warnings.append("no_table_structure")

    if prep_path is not None and prep_path != image_path and prep_path.exists():
        try:
            prep_path.unlink()
        except OSError:
            pass

    return {
        "dataframe": df,
        "engine": source,
        "warnings": warnings,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "strategy": forced or ("ai" if use_ai else "auto"),
    }


def save_table_exports(df: pd.DataFrame, csv_path: Path, xlsx_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8-SIG for Excel-friendly Chinese on Windows/macOS
    df.to_csv(csv_path, index=False, header=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False, header=False, engine="openpyxl")


def dataframe_preview(df: pd.DataFrame, max_rows: int = 20) -> list[list[str]]:
    if df is None or df.empty:
        return []
    head = df.head(max_rows)
    return [[("" if pd.isna(v) else str(v)) for v in row] for row in head.values.tolist()]
