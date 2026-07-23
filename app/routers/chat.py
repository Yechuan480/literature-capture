"""Chat assistant API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import chat_service as chat_svc
from app.services.ai_settings import ai_ready, public_ai_status

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    paper_filename: str | None = None
    scope: str | None = None
    temperature: float = 0.4
    persist: bool = True


@router.get("/status")
def chat_status():
    ai = public_ai_status()
    return {
        "ready": ai_ready(),
        "ai": ai,
    }


@router.post("")
@router.post("/")
def post_chat(body: ChatRequest):
    msgs = [m.model_dump() for m in body.messages]
    result = chat_svc.chat(
        msgs,
        paper_filename=body.paper_filename,
        scope=body.scope,
        temperature=body.temperature,
        persist=body.persist,
    )
    if not result.get("ok"):
        # 503 when AI not ready; 400 for bad input; 502 for upstream
        err = result.get("error") or "失败"
        code = 503 if "未配置" in err or "未启用" in err else 502
        if "为空" in err:
            code = 400
        raise HTTPException(status_code=code, detail=err)
    return result


@router.get("/history")
def get_history(
    scope: str | None = Query(None),
    limit: int = Query(40, ge=1, le=200),
):
    return {
        "scope": scope or "global",
        "messages": chat_svc.load_history(scope, limit=limit),
    }


@router.delete("/history")
def delete_history(scope: str | None = Query(None)):
    chat_svc.clear_history(scope)
    return {"ok": True, "scope": scope or "global"}
