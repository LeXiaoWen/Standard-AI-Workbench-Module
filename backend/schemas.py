from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ApiConfig(BaseModel):
    provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = Field(min_length=1)
    model: str = "gpt-4o"


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


class ProviderProfileCreate(BaseModel):
    provider: str = "OpenAI"
    display_name: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: Optional[str] = None


class ProviderProfileUpdate(BaseModel):
    provider: Optional[str] = None
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ProviderModel(BaseModel):
    id: str
    name: str


class ProviderModelsResponse(BaseModel):
    models: List[ProviderModel] = Field(default_factory=list)


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


class WebSearchConfig(BaseModel):
    provider: str = "tavily"
    has_key: bool = False
    source: str = "none"  # "db" | "env" | "none"
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


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    excerpt: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None


class AuthStatus(BaseModel):
    authenticated: bool = False
    username: Optional[str] = None
    registration_allowed: bool = True


class AuthRegisterRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空。")
        if len(username) > 64:
            raise ValueError("用户名不能超过 64 个字符。")
        return username


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
    new_password: str = Field(min_length=6)


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


class SkillMetadata(BaseModel):
    skill_name: str
    display_name: str
    description: str
    accepted_inputs: List[str] = Field(default_factory=list)
    stages: List[str] = Field(default_factory=list)
