from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from ..schemas import (
    AuthUser,
    McpServer,
    McpServerCreate,
    McpServerUpdate,
    McpTool,
    ProviderProfile,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    SearchResult,
    ToolCallRecord,
    WebSearchConfig,
    WebSearchConfigUpdate,
    Workflow,
    WorkflowArtifact,
    WorkbenchConversation,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchMessage,
    WorkbenchProject,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
)


DEFAULT_PROJECT_TITLE = "默认项目"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    explicit = os.environ.get("AI_WORKBENCH_DB_PATH")
    if explicit:
        return Path(explicit)
    data_dir = Path(os.environ.get("AI_WORKBENCH_DATA_DIR", ".data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "app.db"


class WorkbenchStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    workspace_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    provider_profile_id TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT,
                    finish_reason TEXT,
                    usage_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_profiles (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    credential_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_credentials (
                    credential_key TEXT PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    input_summary TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_artifacts (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    content TEXT,
                    path TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(workflow_id, name)
                );

                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    command TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    env_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mcp_tools_cache (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(server_id, name)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    provider_tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_kind TEXT NOT NULL,
                    server_id TEXT,
                    arguments_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                    kind,
                    source_id,
                    project_id,
                    conversation_id,
                    title,
                    content
                );
                """
            )
        self.ensure_default_project()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._connection.execute(sql, tuple(params))

    def ensure_default_project(self) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects ORDER BY created_at LIMIT 1").fetchone()
        if row:
            return self._project_from_row(row)
        return self.create_project(WorkbenchProjectCreate(title=DEFAULT_PROJECT_TITLE))

    def has_user(self) -> bool:
        return self._execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def create_user(self, username: str, password_hash: str) -> AuthUser:
        if self.has_user():
            raise ValueError("本机账号已存在。")
        now = utc_now()
        user_id = str(uuid4())
        with self._connection:
            self._execute(
                """
                INSERT INTO users (id, username, password_hash, created_at, updated_at, last_login_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (user_id, username.strip(), password_hash, now, now),
            )
        return self.get_user(user_id)

    def get_first_user(self) -> AuthUser | None:
        row = self._execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
        return self._user_from_row(row) if row else None

    def get_user(self, user_id: str) -> AuthUser:
        row = self._execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError(user_id)
        return self._user_from_row(row)

    def get_user_auth_record_by_username(self, username: str) -> sqlite3.Row | None:
        return self._execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()

    def update_user_password_hash(self, user_id: str, password_hash: str) -> AuthUser:
        now = utc_now()
        with self._connection:
            self._execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (password_hash, now, user_id))
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
        return self.get_user(user_id)

    def update_user_last_login(self, user_id: str) -> AuthUser:
        now = utc_now()
        with self._connection:
            self._execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
        return self.get_user(user_id)

    def create_auth_session(self, user_id: str, token_hash: str, expires_at: str) -> None:
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (str(uuid4()), user_id, token_hash, now, expires_at),
            )

    def get_auth_session_user(self, token_hash: str, now: str) -> AuthUser | None:
        row = self._execute(
            """
            SELECT users.*
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ?
              AND auth_sessions.revoked_at IS NULL
              AND auth_sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        return self._user_from_row(row) if row else None

    def revoke_auth_session(self, token_hash: str) -> None:
        now = utc_now()
        with self._connection:
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (now, token_hash))

    def list_projects(self) -> list[WorkbenchProject]:
        rows = self._execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._project_from_row(row) for row in rows]

    def create_project(self, request: WorkbenchProjectCreate) -> WorkbenchProject:
        project_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or DEFAULT_PROJECT_TITLE
        workspace_path = request.workspace_path.strip() if request.workspace_path else None
        with self._connection:
            self._execute(
                "INSERT INTO projects (id, title, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, title, workspace_path, now, now),
            )
            self._upsert_search("project", project_id, project_id, None, title, f"{title}\n{workspace_path or ''}".strip())
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        return self._project_from_row(row)

    def update_project(self, project_id: str, request: WorkbenchProjectUpdate) -> WorkbenchProject:
        project = self.get_project(project_id)
        title = request.title.strip() if request.title is not None else project.title
        workspace_path = request.workspace_path.strip() if request.workspace_path is not None and request.workspace_path.strip() else project.workspace_path
        now = utc_now()
        with self._connection:
            self._execute(
                "UPDATE projects SET title = ?, workspace_path = ?, updated_at = ? WHERE id = ?",
                (title or project.title, workspace_path, now, project_id),
            )
            search_title = title or project.title
            self._upsert_search("project", project_id, project_id, None, search_title, f"{search_title}\n{workspace_path or ''}".strip())
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> None:
        with self._connection:
            self._execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self._execute("DELETE FROM search_index WHERE project_id = ?", (project_id,))
        self.ensure_default_project()

    def list_conversations(self, project_id: str | None = None) -> list[WorkbenchConversation]:
        if project_id:
            rows = self._execute("SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)).fetchall()
        else:
            rows = self._execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def create_conversation(self, request: WorkbenchConversationCreate) -> WorkbenchConversation:
        project_id = request.project_id or self.ensure_default_project().id
        self.get_project(project_id)
        conversation_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or "新对话"
        with self._connection:
            self._execute(
                """
                INSERT INTO conversations (id, project_id, title, provider_profile_id, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, project_id, title, request.provider_profile_id, request.model, now, now),
            )
            self._touch_project(project_id, now)
            self._upsert_search("conversation", conversation_id, project_id, conversation_id, title, title)
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> WorkbenchConversation:
        row = self._execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not row:
            raise KeyError(conversation_id)
        return self._conversation_from_row(row)

    def update_conversation(self, conversation_id: str, request: WorkbenchConversationUpdate) -> WorkbenchConversation:
        conversation = self.get_conversation(conversation_id)
        title = request.title.strip() if request.title is not None else conversation.title
        provider_profile_id = request.provider_profile_id if request.provider_profile_id is not None else conversation.provider_profile_id
        model = request.model if request.model is not None else conversation.model
        now = utc_now()
        with self._connection:
            self._execute(
                "UPDATE conversations SET title = ?, provider_profile_id = ?, model = ?, updated_at = ? WHERE id = ?",
                (title or conversation.title, provider_profile_id, model, now, conversation_id),
            )
            self._touch_project(conversation.project_id, now)
            self._upsert_search("conversation", conversation_id, conversation.project_id, conversation_id, title or conversation.title, title or conversation.title)
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        conversation = self.get_conversation(conversation_id)
        with self._connection:
            self._execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._execute("DELETE FROM search_index WHERE conversation_id = ?", (conversation_id,))
            self._touch_project(conversation.project_id)

    def list_messages(self, conversation_id: str) -> list[WorkbenchMessage]:
        rows = self._execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC", (conversation_id,)).fetchall()
        return [self._message_from_row(row) for row in rows]

    def add_message(self, conversation_id: str, role: str, content: str, status: str = "completed", model: str | None = None) -> WorkbenchMessage:
        conversation = self.get_conversation(conversation_id)
        message_id = str(uuid4())
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, status, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role, content, status, model, now, now),
            )
            self._touch_conversation(conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search("message", message_id, conversation.project_id, conversation_id, role, content)
        return self.get_message(message_id)

    def get_message(self, message_id: str) -> WorkbenchMessage:
        row = self._execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if not row:
            raise KeyError(message_id)
        return self._message_from_row(row)

    def update_message(
        self,
        message_id: str,
        content: str,
        status: str,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> WorkbenchMessage:
        message = self.get_message(message_id)
        conversation = self.get_conversation(message.conversation_id)
        now = utc_now()
        usage_json = json.dumps(usage, ensure_ascii=False) if usage is not None else None
        with self._connection:
            self._execute(
                """
                UPDATE messages
                SET content = ?, status = ?, finish_reason = ?, usage_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (content, status, finish_reason, usage_json, error, now, message_id),
            )
            self._touch_conversation(message.conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search("message", message_id, conversation.project_id, message.conversation_id, message.role, content)
        return self.get_message(message_id)

    def list_provider_profiles(self) -> list[ProviderProfile]:
        rows = self._execute("SELECT * FROM provider_profiles ORDER BY updated_at DESC").fetchall()
        return [self._profile_from_row(row) for row in rows]

    def get_provider_profile(self, profile_id: str) -> ProviderProfile:
        row = self._execute("SELECT * FROM provider_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise KeyError(profile_id)
        return self._profile_from_row(row)

    def create_provider_profile(self, request: ProviderProfileCreate) -> ProviderProfile:
        profile_id = str(uuid4())
        credential_key = f"profile:{profile_id}"
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO provider_profiles
                    (id, provider, display_name, base_url, model, credential_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    request.provider,
                    request.display_name,
                    request.base_url,
                    request.model,
                    credential_key,
                    now,
                    now,
                ),
            )
        if request.api_key:
            self._save_api_key(credential_key, request.api_key.strip(), now)
        return self.get_provider_profile(profile_id)

    def update_provider_profile(self, profile_id: str, request: ProviderProfileUpdate) -> ProviderProfile:
        profile = self.get_provider_profile(profile_id)
        now = utc_now()
        provider = request.provider if request.provider is not None else profile.provider
        display_name = request.display_name if request.display_name is not None else profile.display_name
        base_url = request.base_url if request.base_url is not None else profile.base_url
        model = request.model if request.model is not None else profile.model
        with self._connection:
            self._execute(
                """
                UPDATE provider_profiles
                SET provider = ?, display_name = ?, base_url = ?, model = ?, updated_at = ?
                WHERE id = ?
                """,
                (provider, display_name, base_url, model, now, profile_id),
            )
        if request.api_key is not None:
            if request.api_key.strip():
                self._save_api_key(profile.credential_key, request.api_key.strip(), now)
            else:
                self._execute("DELETE FROM provider_credentials WHERE credential_key = ?", (profile.credential_key,))
        return self.get_provider_profile(profile_id)

    def delete_provider_profile(self, profile_id: str) -> None:
        profile = self.get_provider_profile(profile_id)
        with self._connection:
            self._execute("DELETE FROM provider_profiles WHERE id = ?", (profile_id,))
            self._execute("DELETE FROM provider_credentials WHERE credential_key = ?", (profile.credential_key,))

    def resolve_api_key(self, profile_id: str | None, explicit_api_key: str | None = None) -> str | None:
        if explicit_api_key:
            return explicit_api_key
        if not profile_id:
            return None
        profile = self.get_provider_profile(profile_id)
        row = self._execute(
            "SELECT api_key FROM provider_credentials WHERE credential_key = ?", (profile.credential_key,)
        ).fetchone()
        return row["api_key"] if row else None

    def get_web_search_config(self) -> WebSearchConfig:
        max_results_raw = self._get_setting("web_search.max_results")
        search_depth = self._get_setting("web_search.search_depth") or os.environ.get("TAVILY_SEARCH_DEPTH", "basic")
        try:
            max_results = int(max_results_raw or os.environ.get("TAVILY_MAX_RESULTS", "5"))
        except ValueError:
            max_results = 5
        max_results = min(max(max_results, 1), 10)
        if search_depth not in {"basic", "advanced"}:
            search_depth = "basic"
        key, source = self._resolve_tavily_api_key_with_source()
        return WebSearchConfig(
            provider="tavily",
            has_key=key is not None,
            source=source,
            max_results=max_results,
            search_depth=search_depth,
        )

    def update_web_search_config(self, request: WebSearchConfigUpdate) -> WebSearchConfig:
        if request.api_key is not None:
            if request.api_key.strip():
                self._set_setting("web_search.api_key", request.api_key.strip())
            else:
                self._set_setting("web_search.api_key", "")
        if request.max_results is not None:
            self._set_setting("web_search.max_results", str(request.max_results))
        if request.search_depth is not None:
            self._set_setting("web_search.search_depth", request.search_depth)
        return self.get_web_search_config()

    def resolve_tavily_api_key(self) -> str | None:
        key, _ = self._resolve_tavily_api_key_with_source()
        return key

    def _resolve_tavily_api_key_with_source(self) -> tuple[str | None, str]:
        db_key = self._get_setting("web_search.api_key")
        if db_key:
            return db_key, "db"
        env_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if env_key:
            return env_key, "env"
        return None, "none"

    def _get_setting(self, key: str) -> str | None:
        row = self._execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key: str, value: str) -> None:
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def list_mcp_servers(self, include_disabled: bool = True) -> list[McpServer]:
        if include_disabled:
            rows = self._execute("SELECT * FROM mcp_servers ORDER BY updated_at DESC").fetchall()
        else:
            rows = self._execute("SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY updated_at DESC").fetchall()
        return [self._mcp_server_from_row(row, masked=True) for row in rows]

    def get_mcp_server(self, server_id: str, masked: bool = True) -> McpServer:
        row = self._execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if not row:
            raise KeyError(server_id)
        return self._mcp_server_from_row(row, masked=masked)

    def create_mcp_server(self, request: McpServerCreate) -> McpServer:
        server_id = str(uuid4())
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO mcp_servers (id, name, command, args_json, env_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server_id,
                    request.name.strip(),
                    request.command.strip(),
                    json.dumps(request.args, ensure_ascii=False),
                    json.dumps(request.env, ensure_ascii=False),
                    1 if request.enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_mcp_server(server_id)

    def update_mcp_server(self, server_id: str, request: McpServerUpdate) -> McpServer:
        current = self.get_mcp_server(server_id, masked=False)
        now = utc_now()
        name = request.name.strip() if request.name is not None else current.name
        command = request.command.strip() if request.command is not None else current.command
        args = request.args if request.args is not None else current.args
        env = request.env if request.env is not None else current.env
        enabled = request.enabled if request.enabled is not None else current.enabled
        with self._connection:
            self._execute(
                """
                UPDATE mcp_servers
                SET name = ?, command = ?, args_json = ?, env_json = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    command,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(env, ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    server_id,
                ),
            )
        return self.get_mcp_server(server_id)

    def delete_mcp_server(self, server_id: str) -> None:
        with self._connection:
            self._execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))

    def replace_mcp_tools(self, server_id: str, tools: list[dict[str, Any]]) -> list[McpTool]:
        self.get_mcp_server(server_id, masked=False)
        now = utc_now()
        with self._connection:
            self._execute("DELETE FROM mcp_tools_cache WHERE server_id = ?", (server_id,))
            for tool in tools:
                self._execute(
                    """
                    INSERT INTO mcp_tools_cache (id, server_id, name, description, input_schema_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        server_id,
                        str(tool.get("name", "")),
                        str(tool.get("description", "")),
                        json.dumps(tool.get("inputSchema") or tool.get("input_schema") or {}, ensure_ascii=False),
                        now,
                    ),
                )
        return self.list_mcp_tools(server_id)

    def list_mcp_tools(self, server_id: str | None = None) -> list[McpTool]:
        if server_id:
            rows = self._execute("SELECT * FROM mcp_tools_cache WHERE server_id = ? ORDER BY name", (server_id,)).fetchall()
        else:
            rows = self._execute("SELECT * FROM mcp_tools_cache ORDER BY server_id, name").fetchall()
        return [self._mcp_tool_from_row(row) for row in rows]

    def create_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        provider_tool_call_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: dict[str, Any],
        server_id: str | None = None,
    ) -> ToolCallRecord:
        now = utc_now()
        tool_call_id = str(uuid4())
        with self._connection:
            self._execute(
                """
                INSERT INTO tool_calls
                    (id, conversation_id, message_id, provider_tool_call_id, tool_name, tool_kind, server_id, arguments_json, status, result, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?)
                """,
                (
                    tool_call_id,
                    conversation_id,
                    message_id,
                    provider_tool_call_id,
                    tool_name,
                    tool_kind,
                    server_id,
                    json.dumps(arguments, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_tool_call(tool_call_id)

    def get_tool_call(self, tool_call_id: str) -> ToolCallRecord:
        row = self._execute("SELECT * FROM tool_calls WHERE id = ?", (tool_call_id,)).fetchone()
        if not row:
            raise KeyError(tool_call_id)
        return self._tool_call_from_row(row)

    def update_tool_call(
        self,
        tool_call_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> ToolCallRecord:
        now = utc_now()
        with self._connection:
            self._execute(
                "UPDATE tool_calls SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, result, error, now, tool_call_id),
            )
        return self.get_tool_call(tool_call_id)

    def create_workflow(
        self,
        skill_name: str,
        project_id: str | None,
        conversation_id: str | None,
        input_summary: str = "",
        stage: str = "created",
    ) -> Workflow:
        project_id = project_id or self.ensure_default_project().id
        self.get_project(project_id)
        if conversation_id:
            conversation = self.get_conversation(conversation_id)
        else:
            conversation = self.create_conversation(WorkbenchConversationCreate(project_id=project_id, title=input_summary[:32] or skill_name))
        workflow_id = str(uuid4())
        now = utc_now()
        with self._connection:
            self._execute(
                """
                INSERT INTO workflows (id, skill_name, project_id, conversation_id, status, stage, input_summary, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (workflow_id, skill_name, project_id, conversation.id, "created", stage, input_summary, now, now),
            )
            self._touch_conversation(conversation.id, now)
            self._touch_project(project_id, now)
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> Workflow:
        row = self._execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if not row:
            raise KeyError(workflow_id)
        return self._workflow_from_row(row)

    def list_workflows(self, conversation_id: str | None = None) -> list[Workflow]:
        if conversation_id:
            rows = self._execute("SELECT * FROM workflows WHERE conversation_id = ? ORDER BY updated_at DESC", (conversation_id,)).fetchall()
        else:
            rows = self._execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [self._workflow_from_row(row) for row in rows]

    def update_workflow(
        self,
        workflow_id: str,
        status: str | None = None,
        stage: str | None = None,
        input_summary: str | None = None,
        error: str | None = None,
    ) -> Workflow:
        workflow = self.get_workflow(workflow_id)
        now = utc_now()
        with self._connection:
            self._execute(
                """
                UPDATE workflows
                SET status = ?, stage = ?, input_summary = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status if status is not None else workflow.status,
                    stage if stage is not None else workflow.stage,
                    input_summary if input_summary is not None else workflow.input_summary,
                    error,
                    now,
                    workflow_id,
                ),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.get_workflow(workflow_id)

    def save_workflow_artifacts(self, workflow_id: str, files: dict[str, tuple[str, str, str]]) -> list[WorkflowArtifact]:
        self.get_workflow(workflow_id)
        now = utc_now()
        with self._connection:
            for name, (content, kind, mime_type) in files.items():
                self._execute(
                    """
                    INSERT INTO workflow_artifacts (id, workflow_id, name, kind, mime_type, size, content, path, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    ON CONFLICT(workflow_id, name) DO UPDATE SET
                      kind = excluded.kind,
                      mime_type = excluded.mime_type,
                      size = excluded.size,
                      content = excluded.content,
                      path = excluded.path,
                      created_at = excluded.created_at
                    """,
                    (str(uuid4()), workflow_id, name, kind, mime_type, len(content.encode("utf-8")), content, now),
                )
        return self.list_workflow_artifacts(workflow_id)

    def list_workflow_artifacts(self, workflow_id: str) -> list[WorkflowArtifact]:
        self.get_workflow(workflow_id)
        rows = self._execute("SELECT * FROM workflow_artifacts WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,)).fetchall()
        return [self._workflow_artifact_from_row(row) for row in rows]

    def get_workflow_artifact_content(self, workflow_id: str, name: str) -> tuple[str, str]:
        row = self._execute(
            "SELECT content, mime_type FROM workflow_artifacts WHERE workflow_id = ? AND name = ?",
            (workflow_id, name),
        ).fetchone()
        if not row or row["content"] is None:
            raise KeyError(name)
        return row["content"], row["mime_type"]

    def get_workflow_artifact_files(self, workflow_id: str) -> dict[str, str]:
        self.get_workflow(workflow_id)
        rows = self._execute("SELECT name, content FROM workflow_artifacts WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,)).fetchall()
        return {row["name"]: row["content"] or "" for row in rows}

    def search(self, query: str) -> list[SearchResult]:
        term = query.strip()
        if not term:
            return []
        rows = []
        try:
            rows = self._execute(
                """
                SELECT kind, source_id, project_id, conversation_id, title, snippet(search_index, 5, '', '', '...', 12) AS excerpt
                FROM search_index
                WHERE search_index MATCH ?
                LIMIT 20
                """,
                (f'"{term}"',),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            rows = self._execute(
                """
                SELECT kind, source_id, project_id, conversation_id, title, content AS excerpt
                FROM search_index
                WHERE content LIKE ? OR title LIKE ?
                LIMIT 20
                """,
                (f"%{term}%", f"%{term}%"),
            ).fetchall()
        return [
            SearchResult(
                kind=row["kind"],
                id=row["source_id"],
                title=row["title"],
                excerpt=row["excerpt"],
                conversation_id=row["conversation_id"],
                project_id=row["project_id"],
            )
            for row in rows
        ]

    def _touch_project(self, project_id: str, when: str | None = None) -> None:
        self._execute("UPDATE projects SET updated_at = ? WHERE id = ?", (when or utc_now(), project_id))

    def _touch_conversation(self, conversation_id: str, when: str | None = None) -> None:
        self._execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (when or utc_now(), conversation_id))

    def _upsert_search(self, kind: str, source_id: str, project_id: str | None, conversation_id: str | None, title: str, content: str) -> None:
        self._execute("DELETE FROM search_index WHERE kind = ? AND source_id = ?", (kind, source_id))
        self._execute(
            """
            INSERT INTO search_index (kind, source_id, project_id, conversation_id, title, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kind, source_id, project_id, conversation_id, title, content),
        )

    def _save_api_key(self, credential_key: str, api_key: str, now: str) -> None:
        self._execute(
            """
            INSERT INTO provider_credentials (credential_key, api_key, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(credential_key) DO UPDATE SET api_key = excluded.api_key, updated_at = excluded.updated_at
            """,
            (credential_key, api_key, now),
        )

    def _project_from_row(self, row: sqlite3.Row) -> WorkbenchProject:
        return WorkbenchProject(
            id=row["id"],
            title=row["title"],
            workspace_path=row["workspace_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _user_from_row(self, row: sqlite3.Row) -> AuthUser:
        return AuthUser(
            id=row["id"],
            username=row["username"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
        )

    def _conversation_from_row(self, row: sqlite3.Row) -> WorkbenchConversation:
        return WorkbenchConversation(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            provider_profile_id=row["provider_profile_id"],
            model=row["model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _message_from_row(self, row: sqlite3.Row) -> WorkbenchMessage:
        usage = json.loads(row["usage_json"]) if row["usage_json"] else None
        return WorkbenchMessage(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            status=row["status"],
            model=row["model"],
            finish_reason=row["finish_reason"],
            usage=usage,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _profile_from_row(self, row: sqlite3.Row) -> ProviderProfile:
        return ProviderProfile(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            base_url=row["base_url"],
            model=row["model"],
            credential_key=row["credential_key"],
            has_key=self._execute(
                "SELECT 1 FROM provider_credentials WHERE credential_key = ?", (row["credential_key"],)
            ).fetchone() is not None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _mcp_server_from_row(self, row: sqlite3.Row, masked: bool) -> McpServer:
        env = json.loads(row["env_json"]) if row["env_json"] else {}
        if masked:
            env = {key: "********" for key, value in env.items() if value}
        return McpServer(
            id=row["id"],
            name=row["name"],
            command=row["command"],
            args=json.loads(row["args_json"]) if row["args_json"] else [],
            env=env,
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _mcp_tool_from_row(self, row: sqlite3.Row) -> McpTool:
        return McpTool(
            server_id=row["server_id"],
            name=row["name"],
            description=row["description"],
            input_schema=json.loads(row["input_schema_json"]) if row["input_schema_json"] else {},
            created_at=row["created_at"],
        )

    def _tool_call_from_row(self, row: sqlite3.Row) -> ToolCallRecord:
        return ToolCallRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            provider_tool_call_id=row["provider_tool_call_id"],
            tool_name=row["tool_name"],
            tool_kind=row["tool_kind"],
            server_id=row["server_id"],
            arguments=json.loads(row["arguments_json"]) if row["arguments_json"] else {},
            status=row["status"],
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _workflow_from_row(self, row: sqlite3.Row) -> Workflow:
        return Workflow(
            id=row["id"],
            skill_name=row["skill_name"],
            project_id=row["project_id"],
            conversation_id=row["conversation_id"],
            status=row["status"],
            stage=row["stage"],
            input_summary=row["input_summary"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _workflow_artifact_from_row(self, row: sqlite3.Row) -> WorkflowArtifact:
        return WorkflowArtifact(
            workflow_id=row["workflow_id"],
            name=row["name"],
            kind=row["kind"],
            mime_type=row["mime_type"],
            size=row["size"],
            created_at=row["created_at"],
        )


workbench_store = WorkbenchStore()
