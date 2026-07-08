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
    AuthSetupRequest,
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
from .services.auth import AuthRateLimitError, change_password, login_user, logout_token, setup_user, user_from_token
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
    "/api/v1/auth/setup",
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


def api_config_from_profile(provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(provider_profile_id)
    api_key = workbench_store.resolve_api_key(provider_profile_id)
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
    first_user = workbench_store.get_first_user()
    return AuthStatus(
        setup_required=first_user is None,
        authenticated=user is not None,
        username=user.username if user else None,
        existing_username=first_user.username if first_user else None,
    )


@app.post("/api/v1/auth/setup", response_model=AuthLoginResponse)
def setup_auth(request: AuthSetupRequest):
    if workbench_store.has_user():
        raise HTTPException(status_code=400, detail="本机账号已存在，请直接登录。")
    try:
        setup_user(request.username, request.password)
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
        first_user = workbench_store.get_first_user()
        if first_user and first_user.username != request.username.strip():
            raise HTTPException(status_code=401, detail=f"本机账号为 {first_user.username}，请使用该用户名登录。") from exc
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
def list_workbench_projects():
    return workbench_store.list_projects()


@app.post("/api/v1/projects")
def create_workbench_project(request: WorkbenchProjectCreate):
    return workbench_store.create_project(request)


@app.get("/api/v1/projects/{project_id}")
def get_workbench_project(project_id: str):
    try:
        return workbench_store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.patch("/api/v1/projects/{project_id}")
def update_workbench_project(project_id: str, request: WorkbenchProjectUpdate):
    try:
        return workbench_store.update_project(project_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.delete("/api/v1/projects/{project_id}")
def delete_workbench_project(project_id: str):
    try:
        workbench_store.delete_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations")
def list_workbench_conversations(project_id: str | None = Query(default=None)):
    return workbench_store.list_conversations(project_id)


@app.post("/api/v1/conversations")
def create_workbench_conversation(request: WorkbenchConversationCreate):
    try:
        return workbench_store.create_conversation(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.get("/api/v1/conversations/{conversation_id}")
def get_workbench_conversation(conversation_id: str):
    try:
        return workbench_store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.patch("/api/v1/conversations/{conversation_id}")
def update_workbench_conversation(conversation_id: str, request: WorkbenchConversationUpdate):
    try:
        return workbench_store.update_conversation(conversation_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.delete("/api/v1/conversations/{conversation_id}")
def delete_workbench_conversation(conversation_id: str):
    try:
        workbench_store.delete_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations/{conversation_id}/messages")
def list_workbench_messages(conversation_id: str):
    try:
        workbench_store.get_conversation(conversation_id)
        return workbench_store.list_messages(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.get("/api/v1/provider-profiles")
def list_provider_profiles():
    return workbench_store.list_provider_profiles()


@app.post("/api/v1/provider-profiles")
def create_provider_profile(request: ProviderProfileCreate):
    return workbench_store.create_provider_profile(request)


@app.get("/api/v1/provider-profiles/{profile_id}/models", response_model=ProviderModelsResponse)
async def list_provider_models(profile_id: str):
    try:
        models = await fetch_provider_models(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型列表拉取失败：{exc}") from exc
    return ProviderModelsResponse(models=models)


@app.patch("/api/v1/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, request: ProviderProfileUpdate):
    try:
        return workbench_store.update_provider_profile(profile_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc


@app.delete("/api/v1/provider-profiles/{profile_id}")
def delete_provider_profile(profile_id: str):
    try:
        workbench_store.delete_provider_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/search")
def search_workbench(q: str = Query(default="")):
    return workbench_store.search(q)


@app.get("/api/v1/skills", response_model=list[SkillMetadata])
def list_skills():
    return [adapter.metadata() for adapter in list_adapters()]


@app.post("/api/v1/workflows", response_model=Workflow)
def create_workflow(request: WorkflowCreateRequest):
    try:
        adapter = get_adapter(request.skill_name)
        workflow = workbench_store.create_workflow(
            skill_name=adapter.skill_name,
            project_id=request.project_id,
            conversation_id=request.conversation_id,
            input_summary=request.input_text.strip(),
        )
        if request.input_text.strip():
            workbench_store.add_message(workflow.conversation_id, "user", request.input_text.strip())
        return workflow
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/workflows", response_model=list[Workflow])
def list_workflows(conversation_id: str | None = Query(default=None)):
    return workbench_store.list_workflows(conversation_id)


@app.get("/api/v1/workflows/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: str):
    try:
        return workbench_store.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@app.post("/api/v1/workflows/{workflow_id}/run", response_model=WorkflowActionResponse)
def run_workflow(workflow_id: str, request: WorkflowRunRequest):
    try:
        workflow = workbench_store.get_workflow(workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        running = workbench_store.update_workflow(workflow_id, status="running", error=None)
        workflow, message = adapter.run_stage(running, request.input_text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@app.post("/api/v1/workflows/{workflow_id}/confirm", response_model=WorkflowActionResponse)
def confirm_workflow(workflow_id: str, request: WorkflowConfirmRequest):
    try:
        workflow = workbench_store.get_workflow(workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        workflow, message = adapter.confirm_stage(workflow, request.text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@app.post("/api/v1/workflows/{workflow_id}/cancel", response_model=WorkflowActionResponse)
def cancel_workflow(workflow_id: str):
    try:
        workflow = workbench_store.update_workflow(workflow_id, status="cancelled", stage="cancelled", error=None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc
    return WorkflowActionResponse(workflow=workflow, message="工作流已取消。")


@app.get("/api/v1/workflows/{workflow_id}/artifacts")
def list_workflow_artifacts(workflow_id: str):
    try:
        return workbench_store.list_workflow_artifacts(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@app.get("/api/v1/workflows/{workflow_id}/artifacts/{name}")
def get_workflow_artifact(workflow_id: str, name: str):
    decoded = unquote(name)
    try:
        content, mime_type = workbench_store.get_workflow_artifact_content(workflow_id, decoded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc
    return Response(
        content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@app.get("/api/v1/workflows/{workflow_id}/export.zip")
def export_workflow_zip(workflow_id: str):
    try:
        files = workbench_store.get_workflow_artifact_files(workflow_id)
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
def get_web_search_config():
    return workbench_store.get_web_search_config()


@app.patch("/api/v1/web-search-config", response_model=WebSearchConfig)
def update_web_search_config(request: WebSearchConfigUpdate):
    return workbench_store.update_web_search_config(request)


@app.get("/api/v1/mcp-servers")
def list_mcp_servers():
    return workbench_store.list_mcp_servers()


@app.post("/api/v1/mcp-servers")
def create_mcp_server(request: McpServerCreate):
    return workbench_store.create_mcp_server(request)


@app.patch("/api/v1/mcp-servers/{server_id}")
def update_mcp_server(server_id: str, request: McpServerUpdate):
    try:
        return workbench_store.update_mcp_server(server_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc


@app.delete("/api/v1/mcp-servers/{server_id}")
def delete_mcp_server(server_id: str):
    try:
        workbench_store.get_mcp_server(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    workbench_store.delete_mcp_server(server_id)
    return {"ok": True}


@app.post("/api/v1/mcp-servers/{server_id}/refresh-tools")
async def refresh_mcp_server_tools(server_id: str):
    try:
        await refresh_mcp_tools(server_id)
        return {"tools": workbench_store.list_mcp_tools(server_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: ChatStreamRequest):
    return StreamingResponse(stream_chat(request), media_type="text/event-stream")


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/approve")
def approve_chat_tool_call(tool_call_id: str):
    try:
        return approve_tool_call(tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/reject")
def reject_chat_tool_call(tool_call_id: str):
    try:
        return reject_tool_call(tool_call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工具调用不存在。") from exc


@app.post("/api/v1/chat/tool-calls/{tool_call_id}/resume-stream")
async def resume_chat_tool_call(tool_call_id: str):
    return StreamingResponse(resume_tool_call_stream(tool_call_id), media_type="text/event-stream")


@app.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str):
    return {"ok": cancel_run(run_id)}
