import os
import re
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv

from .schemas import (
    ApiConfig,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthRegisterRequest,
    AuthStatus,
    AuthUser,
    ChangePasswordRequest,
    ChatStreamRequest,
    McpServerCreate,
    McpServerUpdate,
    ProviderModelsResponse,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    SkillMetadata,
    WebSearchConfig,
    WebSearchConfigUpdate,
    Workflow,
    WorkflowActionResponse,
    WorkflowConfirmRequest,
    WorkflowCreateRequest,
    WorkflowRunRequest,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
)
from .services.artifacts import make_zip
from .services.auth import AuthRateLimitError, change_password, login_user, logout_token, register_user, user_from_token
from .services.config import API_PRESETS
from .services.provider_models import list_provider_models as fetch_provider_models
from .services.tool_runtime import refresh_mcp_tools
from .services.workbench_llm import approve_tool_call, cancel_run, reject_tool_call, resume_tool_call_stream, stream_chat
from .services.workbench_store import db_path, workbench_store
from .skills.registry import get_adapter, list_adapters

load_dotenv()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def get_cors_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,app://frontend,null")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


LOCAL_FRONTEND_ORIGIN_REGEX = r"^(https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?|app://frontend|null)$"


app = FastAPI(title="Standard AI Workbench Module")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_origin_regex=os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

PUBLIC_API_V1_PATHS = {
    "/api/v1/auth/status",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
}


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def app_auth_secret_is_valid(request: Request) -> bool:
    expected = os.getenv("APP_AUTH_SECRET", "").strip()
    if not expected:
        return True
    return request.headers.get("x-app-auth-secret", "") == expected


def auth_error_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    origin = request.headers.get("origin")
    origin_is_allowed = origin in get_cors_origins()
    origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX)
    if origin and (origin_is_allowed or re.match(origin_regex, origin)):
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-credentials"] = "true"
        response.headers["access-control-allow-private-network"] = "true"
        response.headers["vary"] = "Origin"
    return response


@app.middleware("http")
async def require_local_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    protected_path = path.startswith("/api/v1/")
    if not protected_path:
        return await call_next(request)

    if not app_auth_secret_is_valid(request):
        return auth_error_response(request, 403, "本机访问密钥无效。")

    if path in PUBLIC_API_V1_PATHS:
        return await call_next(request)

    user = user_from_token(bearer_token(request))
    if user is None:
        return auth_error_response(request, 401, "请先登录。")
    request.state.user = user
    return await call_next(request)


def current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


async def read_upload_with_limit(file: UploadFile, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(f"上传文件不能超过 {limit // (1024 * 1024)}MB。")
        chunks.append(chunk)
    return b"".join(chunks)


def truncate_text(text: str, max_chars: int = 120_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[文本过长，已截断。请优先基于已有内容提取，并提示用户可补充缺失页。]"


def api_config_from_profile(user_id: str, provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(user_id, provider_profile_id)
    api_key = workbench_store.resolve_api_key(user_id, provider_profile_id)
    if not api_key:
        raise ValueError("请先配置 API key。")
    return ApiConfig(provider=profile.provider, base_url=profile.base_url, api_key=api_key, model=profile.model)


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "standard-ai-workbench-module",
        "version": "0.1.0",
        "database": str(db_path()),
        "presets": API_PRESETS,
    }


@app.get("/api/v1/auth/status", response_model=AuthStatus)
def get_auth_status(request: Request):
    user = user_from_token(bearer_token(request))
    return AuthStatus(
        authenticated=user is not None,
        username=user.username if user else None,
    )


@app.post("/api/v1/auth/register", response_model=AuthLoginResponse)
def register_auth(request: AuthRegisterRequest):
    try:
        register_user(request.username, request.password)
        return login_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/auth/login", response_model=AuthLoginResponse)
def login_auth(request: AuthLoginRequest):
    try:
        return login_user(request.username, request.password)
    except AuthRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/v1/auth/logout")
def logout_auth(request: Request):
    logout_token(bearer_token(request))
    return {"ok": True}


@app.get("/api/v1/me", response_model=AuthUser)
def get_me(request: Request):
    return current_user(request)


@app.post("/api/v1/auth/change-password")
def change_auth_password(request: Request, payload: ChangePasswordRequest):
    try:
        change_password(current_user(request), payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/v1/projects")
def list_workbench_projects(request: Request):
    return workbench_store.list_projects(current_user(request).id)


@app.post("/api/v1/projects")
def create_workbench_project(request: Request, payload: WorkbenchProjectCreate):
    return workbench_store.create_project(current_user(request).id, payload)


@app.get("/api/v1/projects/{project_id}")
def get_workbench_project(project_id: str, request: Request):
    try:
        return workbench_store.get_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.patch("/api/v1/projects/{project_id}")
def update_workbench_project(project_id: str, request: Request, payload: WorkbenchProjectUpdate):
    try:
        return workbench_store.update_project(current_user(request).id, project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.delete("/api/v1/projects/{project_id}")
def delete_workbench_project(project_id: str, request: Request):
    try:
        workbench_store.delete_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations")
def list_workbench_conversations(request: Request, project_id: str | None = Query(default=None)):
    return workbench_store.list_conversations(current_user(request).id, project_id)


@app.post("/api/v1/conversations")
def create_workbench_conversation(request: Request, payload: WorkbenchConversationCreate):
    try:
        return workbench_store.create_conversation(current_user(request).id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.get("/api/v1/conversations/{conversation_id}")
def get_workbench_conversation(conversation_id: str, request: Request):
    try:
        return workbench_store.get_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.patch("/api/v1/conversations/{conversation_id}")
def update_workbench_conversation(conversation_id: str, request: Request, payload: WorkbenchConversationUpdate):
    try:
        return workbench_store.update_conversation(current_user(request).id, conversation_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.delete("/api/v1/conversations/{conversation_id}")
def delete_workbench_conversation(conversation_id: str, request: Request):
    try:
        workbench_store.delete_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations/{conversation_id}/messages")
def list_workbench_messages(conversation_id: str, request: Request):
    try:
        return workbench_store.list_messages(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.get("/api/v1/provider-profiles")
def list_provider_profiles(request: Request):
    return workbench_store.list_provider_profiles(current_user(request).id)


@app.post("/api/v1/provider-profiles")
def create_provider_profile(request: Request, payload: ProviderProfileCreate):
    return workbench_store.create_provider_profile(current_user(request).id, payload)


@app.get("/api/v1/provider-profiles/{profile_id}/models", response_model=ProviderModelsResponse)
async def list_provider_models(profile_id: str, request: Request):
    try:
        models = await fetch_provider_models(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型列表拉取失败：{exc}") from exc
    return ProviderModelsResponse(models=models)


@app.patch("/api/v1/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, request: Request, payload: ProviderProfileUpdate):
    try:
        return workbench_store.update_provider_profile(current_user(request).id, profile_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc


@app.delete("/api/v1/provider-profiles/{profile_id}")
def delete_provider_profile(profile_id: str, request: Request):
    try:
        workbench_store.delete_provider_profile(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/search")
def search_workbench(request: Request, q: str = Query(default="")):
    return workbench_store.search(current_user(request).id, q)


@app.get("/api/v1/skills", response_model=list[SkillMetadata])
def list_skills(request: Request):
    current_user(request)
    return [adapter.metadata() for adapter in list_adapters()]


@app.post("/api/v1/workflows", response_model=Workflow)
def create_workflow(request: Request, payload: WorkflowCreateRequest):
    try:
        user = current_user(request)
        adapter = get_adapter(payload.skill_name)
        workflow = workbench_store.create_workflow(
            user.id,
            skill_name=adapter.skill_name,
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
            input_summary=payload.input_text.strip(),
        )
        if payload.input_text.strip():
            workbench_store.add_message(user.id, workflow.conversation_id, "user", payload.input_text.strip())
        return workflow
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/workflows", response_model=list[Workflow])
def list_workflows(request: Request, conversation_id: str | None = Query(default=None)):
    return workbench_store.list_workflows(current_user(request).id, conversation_id)


@app.get("/api/v1/workflows/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: str, request: Request):
    try:
        return workbench_store.get_workflow(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@app.post("/api/v1/workflows/{workflow_id}/run", response_model=WorkflowActionResponse)
def run_workflow(workflow_id: str, request: Request, payload: WorkflowRunRequest):
    try:
        user = current_user(request)
        workflow = workbench_store.get_workflow(user.id, workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        running = workbench_store.update_workflow(user.id, workflow_id, status="running", error=None)
        workflow, message = adapter.run_stage(user.id, running, payload.input_text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(current_user(request).id, workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@app.post("/api/v1/workflows/{workflow_id}/confirm", response_model=WorkflowActionResponse)
def confirm_workflow(workflow_id: str, request: Request, payload: WorkflowConfirmRequest):
    try:
        user = current_user(request)
        workflow = workbench_store.get_workflow(user.id, workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        workflow, message = adapter.confirm_stage(user.id, workflow, payload.text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(current_user(request).id, workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@app.post("/api/v1/workflows/{workflow_id}/cancel", response_model=WorkflowActionResponse)
def cancel_workflow(workflow_id: str, request: Request):
    try:
        workflow = workbench_store.update_workflow(current_user(request).id, workflow_id, status="cancelled", stage="cancelled", error=None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc
    return WorkflowActionResponse(workflow=workflow, message="工作流已取消。")


@app.get("/api/v1/workflows/{workflow_id}/artifacts")
def list_workflow_artifacts(workflow_id: str, request: Request):
    try:
        return workbench_store.list_workflow_artifacts(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@app.get("/api/v1/workflows/{workflow_id}/artifacts/{name}")
def get_workflow_artifact(workflow_id: str, name: str, request: Request):
    decoded = unquote(name)
    try:
        content, mime_type = workbench_store.get_workflow_artifact_content(current_user(request).id, workflow_id, decoded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc
    return Response(
        content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@app.get("/api/v1/workflows/{workflow_id}/export.zip")
def export_workflow_zip(workflow_id: str, request: Request):
    try:
        files = workbench_store.get_workflow_artifact_files(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc
    if not files:
        raise HTTPException(status_code=404, detail="暂无可导出的成果文件。")
    return Response(
        make_zip(files),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''workflow-artifacts.zip"},
    )


@app.get("/api/v1/web-search-config", response_model=WebSearchConfig)
def get_web_search_config(request: Request):
    return workbench_store.get_web_search_config(current_user(request).id)


@app.patch("/api/v1/web-search-config", response_model=WebSearchConfig)
def update_web_search_config(request: Request, payload: WebSearchConfigUpdate):
    return workbench_store.update_web_search_config(current_user(request).id, payload)


@app.get("/api/v1/mcp-servers")
def list_mcp_servers(request: Request):
    return workbench_store.list_mcp_servers(current_user(request).id)


@app.post("/api/v1/mcp-servers")
def create_mcp_server(request: Request, payload: McpServerCreate):
    return workbench_store.create_mcp_server(current_user(request).id, payload)


@app.patch("/api/v1/mcp-servers/{server_id}")
def update_mcp_server(server_id: str, request: Request, payload: McpServerUpdate):
    try:
        return workbench_store.update_mcp_server(current_user(request).id, server_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc


@app.delete("/api/v1/mcp-servers/{server_id}")
def delete_mcp_server(server_id: str, request: Request):
    try:
        workbench_store.delete_mcp_server(current_user(request).id, server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    return {"ok": True}


@app.post("/api/v1/mcp-servers/{server_id}/refresh-tools")
async def refresh_mcp_server_tools(server_id: str, request: Request):
    try:
        user = current_user(request)
        await refresh_mcp_tools(user.id, server_id)
        return {"tools": workbench_store.list_mcp_tools(user.id, server_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: Request, payload: ChatStreamRequest):
    return StreamingResponse(stream_chat(current_user(request).id, payload), media_type="text/event-stream")


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/approve")
def approve_chat_tool_call(tool_call_id: str, request: Request):
    try:
        return approve_tool_call(current_user(request).id, tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/reject")
def reject_chat_tool_call(tool_call_id: str, request: Request):
    try:
        return reject_tool_call(current_user(request).id, tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/resume-stream")
async def resume_chat_tool_call(tool_call_id: str, request: Request):
    return StreamingResponse(resume_tool_call_stream(current_user(request).id, tool_call_id), media_type="text/event-stream")


@app.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str, request: Request):
    return {"ok": cancel_run(current_user(request).id, run_id)}
