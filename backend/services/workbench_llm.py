from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator
from uuid import uuid4

from openai import AsyncOpenAI

from ..schemas import ChatStreamRequest, WorkbenchConversationCreate
from .tool_runtime import build_tool_specs, execute_tool_call
from .web_search import build_search_context, tavily_search
from .workbench_store import workbench_store


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"

_cancel_events: dict[str, tuple[str, asyncio.Event]] = {}


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def cancel_run(user_id: str, run_id: str) -> bool:
    run = _cancel_events.get(run_id)
    if not run or run[0] != user_id:
        return False
    event = run[1]
    event.set()
    return True


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed_roles = {"system", "user", "assistant"}
    return [message for message in messages if message.get("role") in allowed_roles]


def _parse_tool_arguments(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


async def stream_chat(user_id: str, request: ChatStreamRequest) -> AsyncIterator[str]:
    profile = workbench_store.get_provider_profile(user_id, request.provider_profile_id) if request.provider_profile_id else None
    model = request.model or (profile.model if profile else DEFAULT_MODEL)
    base_url = profile.base_url if profile else DEFAULT_BASE_URL
    api_key = workbench_store.resolve_api_key(user_id, request.provider_profile_id, request.api_key)

    if not api_key:
        yield sse_event("error", {"type": "missing_api_key", "message": "请先配置 API key。"})
        return

    if request.conversation_id:
        conversation = workbench_store.get_conversation(user_id, request.conversation_id)
    else:
        conversation = workbench_store.create_conversation(
            user_id,
            WorkbenchConversationCreate(
                project_id=request.project_id,
                title=request.message.strip()[:32] or "新对话",
                provider_profile_id=request.provider_profile_id,
                model=model,
            )
        )

    previous_messages = workbench_store.list_messages(user_id, conversation.id)
    user_message = workbench_store.add_message(user_id, conversation.id, "user", request.message)
    assistant_message = workbench_store.add_message(user_id, conversation.id, "assistant", "", status="streaming", model=model)
    run_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[run_id] = (user_id, cancel_event)

    yield sse_event(
        "message_start",
        {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "user_message_id": user_message.id,
            "run_id": run_id,
            "model": model,
        },
    )

    if len(previous_messages) == 0:
        yield sse_event(
            "conversation_updated",
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "project_id": conversation.project_id,
            },
        )

    system_parts: list[str] = []
    if request.system_prompt:
        system_parts.append(request.system_prompt)
    if request.web_search_enabled:
        try:
            search_results = await tavily_search(user_id, request.message)
            system_parts.append(build_search_context(search_results))
        except Exception as exc:
            message = str(exc)
            system_parts.append(f"（联网搜索暂时不可用：{message}。请基于已有知识回答，并提示用户稍后重试。）")
            yield sse_event(
                "warning",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "type": exc.__class__.__name__,
                    "message": message,
                },
            )

    if system_parts:
        messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    else:
        messages = []
    messages.extend({"role": message.role, "content": message.content} for message in previous_messages if message.status != "error")
    messages.append({"role": "user", "content": request.message})
    messages = _normalize_messages(messages)

    content_parts: list[str] = []
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        tool_specs = build_tool_specs(user_id, request.mcp_server_ids)
        tool_by_name = {spec.schema_name: spec for spec in tool_specs}
        create_kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if tool_specs:
            create_kwargs["tools"] = [spec.schema for spec in tool_specs]
            create_kwargs["tool_choice"] = "auto"
        stream = await client.chat.completions.create(**create_kwargs)
        tool_call_parts: dict[int, dict[str, Any]] = {}
        async for chunk in stream:
            if cancel_event.is_set():
                final_content = "".join(content_parts)
                workbench_store.update_message(user_id, assistant_message.id, final_content, "interrupted", finish_reason="cancelled")
                yield sse_event(
                    "message_done",
                    {
                        "conversation_id": conversation.id,
                        "message_id": assistant_message.id,
                        "status": "interrupted",
                        "finish_reason": "cancelled",
                        "content": final_content,
                    },
                )
                return

            if chunk.usage:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            for tool_delta in getattr(choice.delta, "tool_calls", None) or []:
                index = int(getattr(tool_delta, "index", 0) or 0)
                current = tool_call_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(tool_delta, "id", None):
                    current["id"] = tool_delta.id
                function_delta = getattr(tool_delta, "function", None)
                if function_delta:
                    if getattr(function_delta, "name", None):
                        current["name"] = function_delta.name
                    if getattr(function_delta, "arguments", None):
                        current["arguments"] += function_delta.arguments
            delta = getattr(choice.delta, "content", None)
            if not delta:
                continue
            content_parts.append(delta)
            yield sse_event("delta", {"conversation_id": conversation.id, "message_id": assistant_message.id, "delta": delta})

        final_content = "".join(content_parts)
        if tool_call_parts:
            first_tool = tool_call_parts[min(tool_call_parts.keys())]
            tool_name = str(first_tool.get("name") or "")
            spec = tool_by_name.get(tool_name)
            if not spec:
                workbench_store.update_message(user_id, assistant_message.id, final_content, "error", error=f"模型请求了未启用的工具：{tool_name}")
                yield sse_event(
                    "error",
                    {
                        "conversation_id": conversation.id,
                        "message_id": assistant_message.id,
                        "type": "tool_not_enabled",
                        "message": f"模型请求了未启用的工具：{tool_name}",
                        "content": final_content,
                    },
                )
                return
            arguments = _parse_tool_arguments(str(first_tool.get("arguments") or ""))
            tool_call = workbench_store.create_tool_call(
                user_id=user_id,
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                provider_tool_call_id=str(first_tool.get("id") or f"call_{uuid4().hex}"),
                tool_name=tool_name,
                tool_kind=spec.kind,
                server_id=spec.server_id,
                arguments=arguments,
            )
            workbench_store.update_message(user_id, assistant_message.id, final_content, "tool_pending", finish_reason="tool_calls")
            yield sse_event(
                "tool_call_pending",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "tool_call_id": tool_call.id,
                    "tool_name": spec.display_name,
                    "schema_name": tool_name,
                    "tool_kind": spec.kind,
                    "arguments": arguments,
                    "requires_approval": True,
                },
            )
            return

        workbench_store.update_message(user_id, assistant_message.id, final_content, "completed", finish_reason=finish_reason, usage=usage)
        yield sse_event(
            "message_done",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "status": "completed",
                "finish_reason": finish_reason,
                "usage": usage,
                "content": final_content,
            },
        )
    except Exception as exc:
        final_content = "".join(content_parts)
        message = str(exc)
        workbench_store.update_message(user_id, assistant_message.id, final_content, "error", error=message)
        yield sse_event(
            "error",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "type": exc.__class__.__name__,
                "message": message,
                "content": final_content,
            },
        )
    finally:
        _cancel_events.pop(run_id, None)


def approve_tool_call(user_id: str, tool_call_id: str) -> dict[str, Any]:
    record = workbench_store.get_tool_call(user_id, tool_call_id)
    if record.status == "pending":
        record = workbench_store.update_tool_call(user_id, tool_call_id, "approved")
    return {"ok": True, "status": record.status}


def reject_tool_call(user_id: str, tool_call_id: str) -> dict[str, Any]:
    record = workbench_store.get_tool_call(user_id, tool_call_id)
    if record.status in {"pending", "approved"}:
        record = workbench_store.update_tool_call(user_id, tool_call_id, "rejected", result="用户拒绝执行该工具调用。")
    return {"ok": True, "status": record.status}


async def resume_tool_call_stream(user_id: str, tool_call_id: str) -> AsyncIterator[str]:
    record = workbench_store.get_tool_call(user_id, tool_call_id)
    assistant_message = workbench_store.get_message(user_id, record.message_id)
    conversation = workbench_store.get_conversation(user_id, record.conversation_id)
    profile = workbench_store.get_provider_profile(user_id, conversation.provider_profile_id) if conversation.provider_profile_id else None
    model = conversation.model or (profile.model if profile else DEFAULT_MODEL)
    base_url = profile.base_url if profile else DEFAULT_BASE_URL
    api_key = workbench_store.resolve_api_key(user_id, conversation.provider_profile_id)
    if not api_key:
        yield sse_event("error", {"conversation_id": conversation.id, "message_id": assistant_message.id, "type": "missing_api_key", "message": "请先配置 API key。"})
        return

    if record.status == "pending":
        yield sse_event(
            "tool_call_error",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "tool_call_id": record.id,
                "message": "工具调用尚未确认。",
            },
        )
        return

    tool_result = record.result or ""
    if record.status == "approved":
        try:
            workbench_store.update_tool_call(user_id, record.id, "running")
            yield sse_event(
                "tool_call_result",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "tool_call_id": record.id,
                    "status": "running",
                },
            )
            tool_result = await execute_tool_call(user_id, record)
            record = workbench_store.update_tool_call(user_id, record.id, "done", result=tool_result)
            yield sse_event(
                "tool_call_result",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "tool_call_id": record.id,
                    "status": "done",
                    "result_preview": tool_result[:500],
                },
            )
        except Exception as exc:
            tool_result = f"工具执行失败：{exc}"
            record = workbench_store.update_tool_call(user_id, record.id, "failed", result=tool_result, error=str(exc))
            yield sse_event(
                "tool_call_error",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "tool_call_id": record.id,
                    "message": str(exc),
                },
            )
    elif record.status == "rejected":
        yield sse_event(
            "tool_call_rejected",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "tool_call_id": record.id,
                "message": tool_result or "用户拒绝执行该工具调用。",
            },
        )
        tool_result = tool_result or "用户拒绝执行该工具调用。"
    elif record.status in {"done", "failed"}:
        tool_result = record.result or tool_result

    history: list[dict[str, Any]] = []
    for message in workbench_store.list_messages(user_id, conversation.id):
        if message.id == assistant_message.id:
            break
        if message.status != "error" and message.role in {"system", "user", "assistant"}:
            history.append({"role": message.role, "content": message.content})
    history.append(
        {
            "role": "assistant",
            "content": assistant_message.content or None,
            "tool_calls": [
                {
                    "id": record.provider_tool_call_id,
                    "type": "function",
                    "function": {"name": record.tool_name, "arguments": json.dumps(record.arguments, ensure_ascii=False)},
                }
            ],
        }
    )
    history.append({"role": "tool", "tool_call_id": record.provider_tool_call_id, "content": tool_result})

    content_parts = [assistant_message.content]
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        stream = await client.chat.completions.create(model=model, messages=history, stream=True)
        async for chunk in stream:
            if chunk.usage:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = getattr(choice.delta, "content", None)
            if not delta:
                continue
            content_parts.append(delta)
            yield sse_event("delta", {"conversation_id": conversation.id, "message_id": assistant_message.id, "delta": delta})
        final_content = "".join(content_parts)
        workbench_store.update_message(user_id, assistant_message.id, final_content, "completed", finish_reason=finish_reason, usage=usage)
        yield sse_event(
            "message_done",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "status": "completed",
                "finish_reason": finish_reason,
                "usage": usage,
                "content": final_content,
            },
        )
    except Exception as exc:
        final_content = "".join(content_parts)
        workbench_store.update_message(user_id, assistant_message.id, final_content, "error", error=str(exc))
        yield sse_event(
            "error",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "type": exc.__class__.__name__,
                "message": str(exc),
                "content": final_content,
            },
        )
