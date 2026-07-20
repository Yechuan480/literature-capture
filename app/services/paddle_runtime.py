"""Lazy PaddleX singletons for table detection and recognition."""

from __future__ import annotations

import threading
from typing import Any

from app.config import Settings, get_settings

_lock = threading.Lock()
_state: dict[str, Any] = {
    "init_attempted": False,
    "enabled": False,
    "detect": None,
    "recognize": None,
    "detect_ok": False,
    "recognize_ok": False,
    "error": None,
    "detect_model": None,
    "recognize_pipeline": None,
    "device": None,
    "import_ok": None,
}


def paddlex_importable() -> bool:
    """Cheap check: can import paddlex (does not load models)."""
    if _state["import_ok"] is not None:
        return bool(_state["import_ok"])
    try:
        import paddlex  # noqa: F401

        _state["import_ok"] = True
        return True
    except Exception:
        _state["import_ok"] = False
        return False


def paddle_status(settings: Settings | None = None) -> dict[str, Any]:
    """Status without forcing model load."""
    settings = settings or get_settings()
    st = _state
    import_ok = paddlex_importable() if settings.paddle_enabled else False
    return {
        "configured_enabled": bool(settings.paddle_enabled),
        "import_ok": bool(import_ok),
        "paddle_available": bool(st["detect_ok"] or st["recognize_ok"] or import_ok),
        "paddle_detect": bool(st["detect_ok"]),
        "paddle_recognize": bool(st["recognize_ok"]),
        "paddle_error": st["error"],
        "detect_model": st["detect_model"] or settings.paddle_detect_model,
        "recognize_pipeline": st["recognize_pipeline"]
        or settings.paddle_recognize_pipeline,
        "device": st["device"] or settings.paddle_device,
        "init_attempted": bool(st["init_attempted"]),
    }


def _try_import_paddlex() -> tuple[Any, Any] | None:
    try:
        from paddlex import create_model, create_pipeline  # type: ignore

        _state["import_ok"] = True
        return create_model, create_pipeline
    except Exception as e:
        _state["import_ok"] = False
        _state["error"] = f"paddlex 不可用: {e}"
        return None


def ensure_detector(settings: Settings | None = None) -> Any:
    """Load layout/table detector once. Returns model or None."""
    settings = settings or get_settings()
    with _lock:
        if not settings.paddle_enabled:
            _state["init_attempted"] = True
            _state["enabled"] = False
            _state["error"] = _state["error"] or "paddle.enabled=false"
            return None

        _state["enabled"] = True
        _state["device"] = settings.paddle_device or "cpu"
        _state["detect_model"] = settings.paddle_detect_model

        if _state["detect_ok"] and _state["detect"] is not None:
            return _state["detect"]

        mods = _try_import_paddlex()
        if mods is None:
            _state["init_attempted"] = True
            return None

        create_model, _ = mods
        try:
            _state["detect"] = create_model(
                model_name=settings.paddle_detect_model,
                device=settings.paddle_device or "cpu",
            )
            _state["detect_ok"] = True
            _state["init_attempted"] = True
            if _state["error"] and "检测" in str(_state["error"]):
                _state["error"] = None
            return _state["detect"]
        except Exception as e:
            _state["detect"] = None
            _state["detect_ok"] = False
            _state["init_attempted"] = True
            _state["error"] = f"检测模型加载失败: {e}"
            return None


def ensure_recognizer(settings: Settings | None = None) -> Any:
    """Load table_recognition_v2 pipeline once. Returns pipeline or None."""
    settings = settings or get_settings()
    with _lock:
        if not settings.paddle_enabled:
            _state["init_attempted"] = True
            _state["enabled"] = False
            _state["error"] = _state["error"] or "paddle.enabled=false"
            return None

        _state["enabled"] = True
        _state["device"] = settings.paddle_device or "cpu"
        _state["recognize_pipeline"] = settings.paddle_recognize_pipeline

        if _state["recognize_ok"] and _state["recognize"] is not None:
            return _state["recognize"]

        mods = _try_import_paddlex()
        if mods is None:
            _state["init_attempted"] = True
            return None

        _, create_pipeline = mods
        try:
            _state["recognize"] = create_pipeline(
                pipeline=settings.paddle_recognize_pipeline,
                device=settings.paddle_device or "cpu",
            )
            _state["recognize_ok"] = True
            _state["init_attempted"] = True
            if _state["detect_ok"]:
                _state["error"] = None
            return _state["recognize"]
        except Exception as e:
            _state["recognize"] = None
            _state["recognize_ok"] = False
            _state["init_attempted"] = True
            prev = _state["error"]
            msg = f"识别管线加载失败: {e}"
            _state["error"] = f"{prev}; {msg}" if prev else msg
            return None


def detect_ready(settings: Settings | None = None) -> bool:
    return ensure_detector(settings) is not None


def recognize_ready(settings: Settings | None = None) -> bool:
    return ensure_recognizer(settings) is not None


def ensure_paddle(
    settings: Settings | None = None, *, load_recognize: bool = True
) -> dict[str, Any]:
    ensure_detector(settings)
    if load_recognize:
        ensure_recognizer(settings)
    return paddle_status(settings)
