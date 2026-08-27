import re
from enum import Enum
from ipaddress import ip_address
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def is_trusted_local_base_url(value: str) -> bool:
    """判断 host 是否为本机回环或局域网私网段（允许 http、允许空 api_key）。

    覆盖 localhost/.localhost、回环 127.0.0.1/::1、RFC1918 私网、链路本地、保留段等；
    域名（无法判断内网）与非公网路由可达的地址按非本地处理。
    """
    try:
        hostname = (urlsplit(value).hostname or "").casefold()
    except ValueError:
        return False
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return not ip_address(hostname).is_global
    except ValueError:
        return False


def validate_provider_base_url(value: str) -> str:
    base_url = value.strip()
    try:
        parsed = urlsplit(base_url)
    except ValueError as exc:
        raise ValueError("Base URL 格式无效。") from exc
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password:
        raise ValueError("Base URL 协议或格式无效。")
    if not is_trusted_local_base_url(base_url) and parsed.scheme != "https":
        raise ValueError("公网地址必须使用 HTTPS。")
    return base_url.rstrip("/")


class ApiConfig(BaseModel):
    provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None  # 本机/局域网模型可空
    model: str = "gpt-4o"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_provider_base_url(value)


class AuthStatus(BaseModel):
    authenticated: bool = False
    username: Optional[str] = None
    registration_allowed: bool = True


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空。")
        return username


class AuthRegisterRequest(AuthLoginRequest):
    password: str = Field(min_length=12)


class AuthLoginResponse(BaseModel):
    token: str
    expires_at: str
    username: str


class AuthUser(BaseModel):
    id: str
    username: str
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=12)


class ThemeAppearance(str, Enum):
    AUTO = "auto"
    LIGHT = "light"
    DARK = "dark"


class UserTheme(BaseModel):
    id: str
    name: str
    source: Literal["system", "custom"]
    appearance: ThemeAppearance = ThemeAppearance.AUTO
    image_url: Optional[str] = None
    image_path: Optional[str] = Field(default=None, exclude=True)
    media_type: Optional[str] = Field(default=None, exclude=True)
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ThemeListResponse(BaseModel):
    active_theme_id: str
    themes: List[UserTheme]


class ThemeActivateRequest(BaseModel):
    theme_id: str = Field(min_length=1)


class ThemePreferences(BaseModel):
    """外观偏好：预设皮肤 / 强调色 / 壁纸 2.0，按账号存 user_settings(theme.preferences)。"""

    skin_id: str = "system"
    accent: Optional[str] = None
    wallpaper_kind: Optional[Literal["image", "url", "gradient"]] = None
    wallpaper_url: Optional[str] = None
    wallpaper_gradient: Optional[str] = None
    wallpaper_opacity: float = 0.0
    wallpaper_blur: int = 0
    wallpaper_autodim: bool = False

    @field_validator("accent")
    @classmethod
    def _validate_accent(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", value):
            raise ValueError("强调色必须是 #rrggbb 格式。")
        return value

    @field_validator("wallpaper_opacity")
    @classmethod
    def _validate_opacity(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("壁纸透明度应在 0 到 1 之间。")
        return value

    @field_validator("wallpaper_blur")
    @classmethod
    def _validate_blur(cls, value: int) -> int:
        if not 0 <= value <= 60:
            raise ValueError("壁纸模糊应在 0 到 60 之间。")
        return value


class WorkbenchProject(BaseModel):
    id: str
    title: str
    workspace_path: Optional[str] = None
    created_at: str
    updated_at: str


class WorkbenchProjectCreate(BaseModel):
    title: str = "新项目"
    workspace_path: Optional[str] = None


class WorkbenchProjectUpdate(BaseModel):
    title: Optional[str] = None
    workspace_path: Optional[str] = None


class WorkbenchConversation(BaseModel):
    id: str
    project_id: str
    title: str
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None
    created_at: str
    updated_at: str


class WorkbenchConversationCreate(BaseModel):
    project_id: Optional[str] = None
    title: str = "新对话"
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None


class WorkbenchConversationUpdate(BaseModel):
    title: Optional[str] = None
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None


class WorkbenchMessage(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    status: str = "completed"
    model: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class ProviderProfile(BaseModel):
    id: str
    provider: str
    display_name: str
    base_url: str
    model: str
    has_key: bool = False
    created_at: str
    updated_at: str


class ProviderModel(BaseModel):
    id: str
    name: str


class ProviderModelsResponse(BaseModel):
    models: List[ProviderModel] = Field(default_factory=list)


class ProviderProfileCreate(BaseModel):
    provider: str = "OpenAI"
    display_name: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: Optional[str] = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_provider_base_url(value)


class ProviderProfileUpdate(BaseModel):
    provider: Optional[str] = None
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_provider_base_url(value) if value is not None else None


class WebSearchConfig(BaseModel):
    provider: str = "tavily"
    has_key: bool = False
    source: str = "none"  # "vault" | "env" | "none"
    max_results: int = 5
    search_depth: str = "basic"


class WebSearchConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=10)
    search_depth: Optional[str] = None

    @field_validator("search_depth")
    @classmethod
    def validate_search_depth(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        depth = value.strip()
        if depth not in {"basic", "advanced"}:
            raise ValueError("search_depth 只能是 basic 或 advanced。")
        return depth


class ChatStreamRequest(BaseModel):
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    message: str
    system_prompt: Optional[str] = None
    web_search_enabled: bool = False
    mcp_server_ids: List[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    excerpt: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None


class McpServer(BaseModel):
    id: str
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    created_at: str
    updated_at: str


class McpServerCreate(BaseModel):
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = False


class McpServerUpdate(BaseModel):
    name: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None


class McpTool(BaseModel):
    server_id: str
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ToolCallRecord(BaseModel):
    id: str
    conversation_id: str
    message_id: str
    provider_tool_call_id: str
    tool_name: str
    tool_kind: str
    server_id: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowStatus:
    CREATED = "created"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Workflow(BaseModel):
    id: str
    skill_name: str
    project_id: str
    conversation_id: str
    status: str
    stage: str
    input_summary: str = ""
    error: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowCreateRequest(BaseModel):
    skill_name: str
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    input_text: str = ""


class WorkflowRunRequest(BaseModel):
    input_text: str = ""


class WorkflowConfirmRequest(BaseModel):
    text: str = ""


class WorkflowActionResponse(BaseModel):
    workflow: Workflow
    message: str


class WorkflowArtifact(BaseModel):
    workflow_id: str
    name: str
    kind: str = "file"
    mime_type: str = "text/plain"
    size: int
    created_at: str


class KnowledgeVault(BaseModel):
    project_id: str
    source_count: int = 0
    page_count: int = 0
    path: str


class KnowledgeSource(BaseModel):
    id: str
    project_id: str
    filename: str
    content_hash: str
    status: str
    created_at: str
    updated_at: str


class KnowledgePatch(BaseModel):
    path: str
    operation: str
    content: str


class KnowledgeDraft(BaseModel):
    id: str
    project_id: str
    source_id: str
    status: str
    patches: List[KnowledgePatch] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str
    updated_at: str


class KnowledgePage(BaseModel):
    path: str
    title: str
    content: str


class KnowledgeLintReport(BaseModel):
    missing_index: List[str] = Field(default_factory=list)
    broken_links: List[str] = Field(default_factory=list)
    orphan_pages: List[str] = Field(default_factory=list)
    stale_sources: List[str] = Field(default_factory=list)


class SkillMetadata(BaseModel):
    skill_name: str
    display_name: str
    description: str
    accepted_inputs: List[str] = Field(default_factory=list)
    stages: List[str] = Field(default_factory=list)
