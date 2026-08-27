from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..schemas import ChatStreamRequest
from ..services.workbench_llm import (
    approve_tool_call,
    cancel_run,
    reject_tool_call,
    resume_tool_call_stream,
    stream_chat,
)
from .dependencies import current_user

router = APIRouter()


@router.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: Request, payload: ChatStreamRequest):
    return StreamingResponse(stream_chat(current_user(request).id, payload), media_type="text/event-stream")


@router.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str, request: Request):
    return {"ok": cancel_run(current_user(request).id, run_id)}


@router.post("/api/v1/chat/tool-calls/{tool_call_id}/approve")
def approve_chat_tool_call(tool_call_id: str, request: Request):
    try:
        return approve_tool_call(current_user(request).id, tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@router.post("/api/v1/chat/tool-calls/{tool_call_id}/reject")
def reject_chat_tool_call(tool_call_id: str, request: Request):
    try:
        return reject_tool_call(current_user(request).id, tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@router.post("/api/v1/chat/tool-calls/{tool_call_id}/resume-stream")
async def resume_chat_tool_call(tool_call_id: str, request: Request):
    return StreamingResponse(resume_tool_call_stream(current_user(request).id, tool_call_id), media_type="text/event-stream")
