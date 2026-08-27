from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Optional
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

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
    ThemeAppearance,
    ToolCallRecord,
    UserTheme,
    WebSearchConfig,
    WebSearchConfigUpdate,
    WorkbenchConversation,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchMessage,
    WorkbenchProject,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
    Workflow,
    WorkflowArtifact,
)
DEFAULT_PROJECT_TITLE = "默认项目"
MULTI_TENANT_SCHEMA_VERSION = 3
SCHEMA_VERSION = 10


class CredentialVaultLocked(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def restrict_file_permissions(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def data_dir() -> Path:
    raw = os.getenv("AI_WORKBENCH_DATA_DIR")
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.cwd() / ".data"
    return ensure_private_directory(path)


def db_path() -> Path:
    raw = os.getenv("AI_WORKBENCH_DB_PATH")
    if raw:
        path = Path(raw).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return data_dir() / "app.db"


class WorkbenchStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        restrict_file_permissions(self.path)
        self._connection.row_factory = sqlite3.Row
        self._vault_keys: dict[str, bytes] = {}
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._backup_legacy_database_if_needed()
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
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
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    credential_key TEXT NOT NULL UNIQUE,
                    has_key INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
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

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
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

                CREATE TABLE IF NOT EXISTS credential_vaults (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    salt BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS encrypted_credentials (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    credential_key TEXT NOT NULL,
                    nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, credential_key)
                );

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                    owner_user_id UNINDEXED,
                    kind,
                    source_id,
                    project_id,
                    conversation_id,
                    title,
                    content
                );
                """
            )
            self._migrate_schema()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, tuple(params))

    def _ensure_column(self, table: str, column: str, declaration: str) -> bool:
        columns = {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            return True
        return False

    def _migrate_schema(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        migrations = {
            1: self._migrate_to_v1,
            2: self._migrate_to_v2,
            3: self._migrate_to_v3,
            4: self._migrate_to_v4,
            5: self._migrate_to_v5,
            6: self._migrate_to_v6,
            7: self._migrate_to_v7,
            8: self._migrate_to_v8,
            9: self._migrate_to_v9,
            10: self._migrate_to_v10,
        }
        while version < SCHEMA_VERSION:
            target_version = version + 1
            migrations[target_version]()
            self._connection.execute(f"PRAGMA user_version = {target_version}")
            version = target_version

    def _migrate_to_v1(self) -> None:
        self._ensure_column("projects", "workspace_path", "TEXT")

    def _migrate_to_v2(self) -> None:
        provider_has_key_added = self._ensure_column("provider_profiles", "has_key", "INTEGER NOT NULL DEFAULT 0")
        if provider_has_key_added:
            self._connection.execute("UPDATE provider_profiles SET has_key = 1")
        self._ensure_column("provider_profiles", "api_key", "TEXT")

    def _migrate_to_v3(self) -> None:
        self._ensure_column("projects", "owner_user_id", "TEXT")
        self._ensure_column("provider_profiles", "owner_user_id", "TEXT")
        self._connection.execute("DROP INDEX IF EXISTS idx_single_user")
        owner = self._execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
        if owner:
            owner_user_id = owner["id"]
            self._execute("UPDATE projects SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner_user_id,))
            self._execute("UPDATE provider_profiles SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner_user_id,))
            self._migrate_legacy_credentials(owner_user_id)
        self._rebuild_search_index()

    def _migrate_to_v4(self) -> None:
        self._ensure_column("conversations", "context_summary", "TEXT NOT NULL DEFAULT ''")

    def _migrate_to_v5(self) -> None:
        # 历史迁移：标书工作流索引已随 bid 表移除，改为幂等清理。
        self._connection.execute("DROP INDEX IF EXISTS idx_active_bid_workflows_per_conversation")

    def _migrate_to_v6(self) -> None:
        # 历史迁移：bid_jobs 表已随标书业务移除，无需再补列。
        pass

    def _migrate_to_v7(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS credential_vaults (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                salt BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS encrypted_credentials (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                credential_key TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, credential_key)
            );
            """
        )

    def _migrate_to_v8(self) -> None:
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at)")

    def _migrate_to_v9(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_themes (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                image_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                appearance TEXT NOT NULL DEFAULT 'auto',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_themes_owner_updated ON user_themes(owner_user_id, updated_at DESC);
            """
        )

    def _migrate_to_v10(self) -> None:
        # 通用工作流 / MCP 工具运行时能力并入：建表、多租户回填、清理标书残留表。
        self._connection.executescript(
            """
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
                owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
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

            DROP TABLE IF EXISTS bid_workflows;
            DROP TABLE IF EXISTS bid_artifacts;
            DROP TABLE IF EXISTS bid_artifact_versions;
            DROP TABLE IF EXISTS bid_jobs;
            """
        )
        self._ensure_column("mcp_servers", "owner_user_id", "TEXT")
        owner = self._execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
        if owner:
            self._execute("UPDATE mcp_servers SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner["id"],))

    def _backup_legacy_database_if_needed(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        has_existing_schema = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name IN ('users', 'projects') LIMIT 1"
        ).fetchone()
        backup_path = self.path.with_suffix(f"{self.path.suffix}.pre-multitenant.bak")
        if version >= MULTI_TENANT_SCHEMA_VERSION or not has_existing_schema or backup_path.exists():
            return
        backup = sqlite3.connect(backup_path)
        try:
            self._connection.backup(backup)
        finally:
            backup.close()

    def _migrate_legacy_credentials(self, user_id: str) -> None:
        profiles = self._execute("SELECT id, api_key FROM provider_profiles WHERE owner_user_id = ?", (user_id,)).fetchall()
        for profile in profiles:
            self._execute(
                "UPDATE provider_profiles SET credential_key = ?, has_key = ? WHERE id = ?",
                (f"db:{profile['id']}", 1 if profile["api_key"] else 0, profile["id"]),
            )
        tavily_key = self.get_setting("web_search.api_key")
        if tavily_key:
            self.set_user_setting(user_id, "web_search.api_key", tavily_key)
            self.set_user_setting(user_id, "web_search.has_key", "1")
            self._execute("DELETE FROM app_settings WHERE key IN ('web_search.api_key', 'web_search.has_key')")
        for key in ("web_search.max_results", "web_search.search_depth"):
            value = self.get_setting(key)
            if value is not None:
                self.set_user_setting(user_id, key, value)

    def migrate_legacy_secrets_on_login(self, user_id: str, password: str) -> None:
        """Move legacy plaintext data into the password-encrypted local vault."""
        profiles = self._execute(
            "SELECT id, credential_key, api_key FROM provider_profiles WHERE owner_user_id = ? AND api_key IS NOT NULL AND api_key != ''",
            (user_id,),
        ).fetchall()
        tavily_key = self.get_user_setting(user_id, "web_search.api_key") or ""
        secrets_to_migrate = {
            **{f"provider:{row['id']}": row["api_key"] for row in profiles},
            **({"tavily": tavily_key} if tavily_key else {}),
        }
        if not secrets_to_migrate:
            return

        vault_key = self._credential_vault_key(user_id)
        credentials = [(f"provider:{user_id}:{row['id']}", row["api_key"]) for row in profiles]
        if tavily_key:
            credentials.append((self._tavily_credential_key(user_id), tavily_key))
        now = utc_now()
        encrypted_credentials = []
        for credential_key, value in credentials:
            nonce = os.urandom(12)
            ciphertext = AESGCM(vault_key).encrypt(nonce, value.encode("utf-8"), self._credential_aad(user_id, credential_key))
            encrypted_credentials.append((credential_key, nonce, ciphertext))
        with self._lock, self._connection:
            for credential_key, nonce, ciphertext in encrypted_credentials:
                self._execute(
                    """
                    INSERT INTO encrypted_credentials (user_id, credential_key, nonce, ciphertext, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, credential_key) DO UPDATE SET nonce = excluded.nonce, ciphertext = excluded.ciphertext, updated_at = excluded.updated_at
                    """,
                    (user_id, credential_key, nonce, ciphertext, now, now),
                )
            for row in profiles:
                key = f"provider:{user_id}:{row['id']}"
                self._execute("UPDATE provider_profiles SET credential_key = ?, has_key = 1 WHERE id = ?", (key, row["id"]))
            self._execute("UPDATE provider_profiles SET api_key = NULL WHERE owner_user_id = ?", (user_id,))
            self.set_user_setting(user_id, "web_search.api_key", "")
            self.set_user_setting(user_id, "web_search.has_key", "1" if tavily_key else "0")

    def unlock_credential_vault(self, user_id: str, password: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            row = self._execute("SELECT salt FROM credential_vaults WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                salt = os.urandom(16)
                self._execute(
                    "INSERT INTO credential_vaults (user_id, salt, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (user_id, salt, now, now),
                )
            else:
                salt = bytes(row["salt"])
        self._vault_keys[user_id] = self._derive_vault_key(password, salt)

    def lock_credential_vault(self, user_id: str) -> None:
        self._vault_keys.pop(user_id, None)

    def credential_vault_is_unlocked(self, user_id: str) -> bool:
        return user_id in self._vault_keys

    def set_credential(self, user_id: str, credential_key: str, value: str) -> None:
        key = self._credential_vault_key(user_id)
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), self._credential_aad(user_id, credential_key))
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO encrypted_credentials (user_id, credential_key, nonce, ciphertext, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, credential_key) DO UPDATE SET nonce = excluded.nonce, ciphertext = excluded.ciphertext, updated_at = excluded.updated_at
                """,
                (user_id, credential_key, nonce, ciphertext, now, now),
            )

    def get_credential(self, user_id: str, credential_key: str) -> str | None:
        key = self._credential_vault_key(user_id)
        row = self._execute(
            "SELECT nonce, ciphertext FROM encrypted_credentials WHERE user_id = ? AND credential_key = ?",
            (user_id, credential_key),
        ).fetchone()
        if not row:
            return None
        try:
            return AESGCM(key).decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]), self._credential_aad(user_id, credential_key)).decode("utf-8")
        except Exception as exc:
            raise CredentialVaultLocked("本地加密密钥无法解锁，请重新登录后重试。") from exc

    def delete_credential(self, user_id: str, credential_key: str) -> None:
        self._credential_vault_key(user_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM encrypted_credentials WHERE user_id = ? AND credential_key = ?", (user_id, credential_key))

    def change_user_password_and_rotate_credential_vault(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        new_password_hash: str,
    ) -> None:
        old_key = self._credential_vault_key(user_id)
        row = self._execute("SELECT salt FROM credential_vaults WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise CredentialVaultLocked("本地加密凭据库不可用。")
        expected_key = self._derive_vault_key(current_password, bytes(row["salt"]))
        if expected_key != old_key:
            raise CredentialVaultLocked("本地加密凭据库无法用当前密码解锁。")
        records = self._execute(
            "SELECT credential_key, nonce, ciphertext FROM encrypted_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        values = []
        for record in records:
            name = record["credential_key"]
            value = AESGCM(old_key).decrypt(bytes(record["nonce"]), bytes(record["ciphertext"]), self._credential_aad(user_id, name))
            values.append((name, value))
        salt = os.urandom(16)
        new_key = self._derive_vault_key(new_password, salt)
        now = utc_now()
        with self._lock, self._connection:
            self._execute("UPDATE credential_vaults SET salt = ?, updated_at = ? WHERE user_id = ?", (salt, now, user_id))
            for name, value in values:
                nonce = os.urandom(12)
                ciphertext = AESGCM(new_key).encrypt(nonce, value, self._credential_aad(user_id, name))
                self._execute(
                    "UPDATE encrypted_credentials SET nonce = ?, ciphertext = ?, updated_at = ? WHERE user_id = ? AND credential_key = ?",
                    (nonce, ciphertext, now, user_id, name),
                )
            self._execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (new_password_hash, now, user_id))
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
        self._vault_keys[user_id] = new_key

    def sync_credential_status(self, user_id: str) -> None:
        profiles = self._execute("SELECT id, credential_key FROM provider_profiles WHERE owner_user_id = ?", (user_id,)).fetchall()
        with self._lock, self._connection:
            for profile in profiles:
                has_key = 1 if self.get_credential(user_id, profile["credential_key"]) else 0
                self._execute("UPDATE provider_profiles SET has_key = ? WHERE id = ?", (has_key, profile["id"]))
            has_tavily_key = 1 if self.get_credential(user_id, self._tavily_credential_key(user_id)) else 0
            self.set_user_setting(user_id, "web_search.has_key", str(has_tavily_key))

    def _credential_vault_key(self, user_id: str) -> bytes:
        key = self._vault_keys.get(user_id)
        if key is None:
            raise CredentialVaultLocked("请重新登录以解锁本地加密凭据库。")
        return key

    def _derive_vault_key(self, password: str, salt: bytes) -> bytes:
        return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))

    def _credential_aad(self, user_id: str, credential_key: str) -> bytes:
        return f"{user_id}:{credential_key}".encode("utf-8")

    def _rebuild_search_index(self) -> None:
        self._connection.execute("DROP TABLE IF EXISTS search_index")
        self._connection.execute(
            """
            CREATE VIRTUAL TABLE search_index USING fts5(
                owner_user_id UNINDEXED,
                kind,
                source_id,
                project_id,
                conversation_id,
                title,
                content
            )
            """
        )
        projects = self._execute("SELECT id, owner_user_id, title, workspace_path FROM projects WHERE owner_user_id IS NOT NULL").fetchall()
        for project in projects:
            self._upsert_search(project["owner_user_id"], "project", project["id"], project["id"], None, project["title"], f"{project['title']}\n{project['workspace_path'] or ''}".strip())
        conversations = self._execute(
            """
            SELECT conversations.*, projects.owner_user_id
            FROM conversations JOIN projects ON projects.id = conversations.project_id
            WHERE projects.owner_user_id IS NOT NULL
            """
        ).fetchall()
        for conversation in conversations:
            self._upsert_search(conversation["owner_user_id"], "conversation", conversation["id"], conversation["project_id"], conversation["id"], conversation["title"], conversation["title"])
        messages = self._execute(
            """
            SELECT messages.*, conversations.project_id, projects.owner_user_id
            FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            JOIN projects ON projects.id = conversations.project_id
            WHERE projects.owner_user_id IS NOT NULL
            """
        ).fetchall()
        for message in messages:
            self._upsert_search(message["owner_user_id"], "message", message["id"], message["project_id"], message["conversation_id"], message["role"], message["content"])

    def ensure_default_project(self, user_id: str) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (user_id,)).fetchone()
        if row:
            return self._project_from_row(row)
        return self.create_project(user_id, WorkbenchProjectCreate(title=DEFAULT_PROJECT_TITLE))

    def list_projects(self, user_id: str) -> list[WorkbenchProject]:
        rows = self._execute("SELECT * FROM projects WHERE owner_user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._project_from_row(row) for row in rows]

    def create_project(self, user_id: str, request: WorkbenchProjectCreate) -> WorkbenchProject:
        project_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or DEFAULT_PROJECT_TITLE
        workspace_path = request.workspace_path.strip() if request.workspace_path else None
        with self._lock, self._connection:
            self._execute(
                "INSERT INTO projects (id, owner_user_id, title, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, user_id, title, workspace_path, now, now),
            )
            search_content = f"{title}\n{workspace_path or ''}".strip()
            self._upsert_search(user_id, "project", project_id, project_id, None, title, search_content)
        return self.get_project(user_id, project_id)

    def has_user(self) -> bool:
        row = self._execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def create_user(self, username: str, password_hash: str) -> AuthUser:
        now = utc_now()
        user_id = str(uuid4())
        try:
            with self._lock, self._connection:
                self._execute(
                    """
                    INSERT INTO users (id, username, password_hash, created_at, updated_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (user_id, username.strip(), password_hash, now, now),
                )
                legacy_resources = self._execute(
                    "SELECT 1 FROM projects WHERE owner_user_id IS NULL UNION ALL SELECT 1 FROM provider_profiles WHERE owner_user_id IS NULL UNION ALL SELECT 1 FROM mcp_servers WHERE owner_user_id IS NULL LIMIT 1"
                ).fetchone()
                if legacy_resources:
                    self._execute("UPDATE projects SET owner_user_id = ? WHERE owner_user_id IS NULL", (user_id,))
                    self._execute("UPDATE provider_profiles SET owner_user_id = ? WHERE owner_user_id IS NULL", (user_id,))
                    self._execute("UPDATE mcp_servers SET owner_user_id = ? WHERE owner_user_id IS NULL", (user_id,))
                    self._migrate_legacy_credentials(user_id)
                    self._rebuild_search_index()
                self.ensure_default_project(user_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
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
        with self._lock, self._connection:
            self._execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (password_hash, now, user_id))
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
        return self.get_user(user_id)

    def update_user_last_login(self, user_id: str) -> AuthUser:
        now = utc_now()
        with self._lock, self._connection:
            self._execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
        return self.get_user(user_id)

    def create_auth_session(self, user_id: str, token_hash: str, expires_at: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            self._execute(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (str(uuid4()), user_id, token_hash, now, expires_at),
            )

    def prune_expired_auth_sessions(self, now: str | None = None) -> int:
        with self._lock, self._connection:
            cursor = self._execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now or utc_now(),))
        return cursor.rowcount

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
        with self._lock, self._connection:
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (now, token_hash))

    def has_active_auth_sessions(self, user_id: str, now: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? LIMIT 1",
            (user_id, now),
        ).fetchone()
        return row is not None

    def get_project(self, user_id: str, project_id: str) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects WHERE id = ? AND owner_user_id = ?", (project_id, user_id)).fetchone()
        if not row:
            raise KeyError(project_id)
        return self._project_from_row(row)

    def update_project(self, user_id: str, project_id: str, request: WorkbenchProjectUpdate) -> WorkbenchProject:
        project = self.get_project(user_id, project_id)
        title = request.title.strip() if request.title is not None else project.title
        workspace_path = request.workspace_path.strip() if request.workspace_path is not None and request.workspace_path.strip() else project.workspace_path
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE projects SET title = ?, workspace_path = ?, updated_at = ? WHERE id = ? AND owner_user_id = ?",
                (title or project.title, workspace_path, now, project_id, user_id),
            )
            search_title = title or project.title
            search_content = f"{search_title}\n{workspace_path or ''}".strip()
            self._upsert_search(user_id, "project", project_id, project_id, None, search_title, search_content)
        return self.get_project(user_id, project_id)

    def delete_project(self, user_id: str, project_id: str) -> None:
        self.get_project(user_id, project_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM projects WHERE id = ? AND owner_user_id = ?", (project_id, user_id))
            self._execute("DELETE FROM search_index WHERE project_id = ? AND owner_user_id = ?", (project_id, user_id))
        self.ensure_default_project(user_id)

    def list_conversations(self, user_id: str, project_id: str | None = None) -> list[WorkbenchConversation]:
        if project_id:
            self.get_project(user_id, project_id)
            rows = self._execute("SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)).fetchall()
        else:
            rows = self._execute(
                """
                SELECT conversations.* FROM conversations
                JOIN projects ON projects.id = conversations.project_id
                WHERE projects.owner_user_id = ?
                ORDER BY conversations.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def create_conversation(self, user_id: str, request: WorkbenchConversationCreate) -> WorkbenchConversation:
        project_id = request.project_id or self.ensure_default_project(user_id).id
        self.get_project(user_id, project_id)
        conversation_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or "新对话"
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO conversations (id, project_id, title, provider_profile_id, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, project_id, title, request.provider_profile_id, request.model, now, now),
            )
            self._touch_project(project_id, now)
            self._upsert_search(user_id, "conversation", conversation_id, project_id, conversation_id, title, title)
        return self.get_conversation(user_id, conversation_id)

    def get_conversation(self, user_id: str, conversation_id: str) -> WorkbenchConversation:
        row = self._execute(
            """
            SELECT conversations.* FROM conversations
            JOIN projects ON projects.id = conversations.project_id
            WHERE conversations.id = ? AND projects.owner_user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(conversation_id)
        return self._conversation_from_row(row)

    def update_conversation(self, user_id: str, conversation_id: str, request: WorkbenchConversationUpdate) -> WorkbenchConversation:
        conversation = self.get_conversation(user_id, conversation_id)
        title = request.title.strip() if request.title is not None else conversation.title
        provider_profile_id = request.provider_profile_id if request.provider_profile_id is not None else conversation.provider_profile_id
        model = request.model if request.model is not None else conversation.model
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE conversations
                SET title = ?, provider_profile_id = ?, model = ?, updated_at = ?
                WHERE id = ?
                """,
                (title or conversation.title, provider_profile_id, model, now, conversation_id),
            )
            self._touch_project(conversation.project_id, now)
            self._upsert_search(
                user_id,
                "conversation",
                conversation_id,
                conversation.project_id,
                conversation_id,
                title or conversation.title,
                title or conversation.title,
            )
        return self.get_conversation(user_id, conversation_id)

    def get_context_summary(self, user_id: str, conversation_id: str) -> str:
        self.get_conversation(user_id, conversation_id)
        row = self._execute("SELECT context_summary FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return str(row["context_summary"] or "") if row else ""

    def set_context_summary(self, user_id: str, conversation_id: str, summary: str) -> None:
        conversation = self.get_conversation(user_id, conversation_id)
        with self._lock, self._connection:
            self._execute("UPDATE conversations SET context_summary = ?, updated_at = ? WHERE id = ?", (summary, utc_now(), conversation_id))
            self._touch_project(conversation.project_id)

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        conversation = self.get_conversation(user_id, conversation_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._execute("DELETE FROM search_index WHERE conversation_id = ? AND owner_user_id = ?", (conversation_id, user_id))
            self._touch_project(conversation.project_id)


    def list_mcp_servers(self, user_id: str, include_disabled: bool = True) -> list[McpServer]:
        if include_disabled:
            rows = self._execute("SELECT * FROM mcp_servers WHERE owner_user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        else:
            rows = self._execute("SELECT * FROM mcp_servers WHERE owner_user_id = ? AND enabled = 1 ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._mcp_server_from_row(row, masked=True) for row in rows]

    def get_mcp_server(self, user_id: str, server_id: str, masked: bool = True) -> McpServer:
        row = self._execute("SELECT * FROM mcp_servers WHERE id = ? AND owner_user_id = ?", (server_id, user_id)).fetchone()
        if not row:
            raise KeyError(server_id)
        return self._mcp_server_from_row(row, masked=masked)

    def create_mcp_server(self, user_id: str, request: McpServerCreate) -> McpServer:
        server_id = str(uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO mcp_servers (id, owner_user_id, name, command, args_json, env_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server_id,
                    user_id,
                    request.name.strip(),
                    request.command.strip(),
                    json.dumps(request.args, ensure_ascii=False),
                    json.dumps(request.env, ensure_ascii=False),
                    1 if request.enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_mcp_server(user_id, server_id)

    def update_mcp_server(self, user_id: str, server_id: str, request: McpServerUpdate) -> McpServer:
        current = self.get_mcp_server(user_id, server_id, masked=False)
        now = utc_now()
        name = request.name.strip() if request.name is not None else current.name
        command = request.command.strip() if request.command is not None else current.command
        args = request.args if request.args is not None else current.args
        env = request.env if request.env is not None else current.env
        enabled = request.enabled if request.enabled is not None else current.enabled
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE mcp_servers
                SET name = ?, command = ?, args_json = ?, env_json = ?, enabled = ?, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    name,
                    command,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(env, ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    server_id,
                    user_id,
                ),
            )
        return self.get_mcp_server(user_id, server_id)

    def delete_mcp_server(self, user_id: str, server_id: str) -> None:
        self.get_mcp_server(user_id, server_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM mcp_servers WHERE id = ? AND owner_user_id = ?", (server_id, user_id))

    def replace_mcp_tools(self, user_id: str, server_id: str, tools: list[dict[str, Any]]) -> list[McpTool]:
        self.get_mcp_server(user_id, server_id, masked=False)
        now = utc_now()
        with self._lock, self._connection:
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
        return self.list_mcp_tools(user_id, server_id)

    def list_mcp_tools(self, user_id: str, server_id: str | None = None) -> list[McpTool]:
        if server_id:
            self.get_mcp_server(user_id, server_id)
            rows = self._execute("SELECT * FROM mcp_tools_cache WHERE server_id = ? ORDER BY name", (server_id,)).fetchall()
        else:
            rows = self._execute("SELECT mcp_tools_cache.* FROM mcp_tools_cache JOIN mcp_servers ON mcp_servers.id = mcp_tools_cache.server_id WHERE mcp_servers.owner_user_id = ? ORDER BY mcp_tools_cache.server_id, mcp_tools_cache.name", (user_id,)).fetchall()
        return [self._mcp_tool_from_row(row) for row in rows]

    def create_tool_call(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        provider_tool_call_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: dict[str, Any],
        server_id: str | None = None,
    ) -> ToolCallRecord:
        self.get_conversation(user_id, conversation_id)
        if server_id:
            self.get_mcp_server(user_id, server_id)
        now = utc_now()
        tool_call_id = str(uuid4())
        with self._lock, self._connection:
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
        return self.get_tool_call(user_id, tool_call_id)

    def get_tool_call(self, user_id: str, tool_call_id: str) -> ToolCallRecord:
        row = self._execute(
            "SELECT tool_calls.* FROM tool_calls JOIN conversations ON conversations.id = tool_calls.conversation_id JOIN projects ON projects.id = conversations.project_id WHERE tool_calls.id = ? AND projects.owner_user_id = ?",
            (tool_call_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(tool_call_id)
        return self._tool_call_from_row(row)

    def update_tool_call(
        self,
        user_id: str,
        tool_call_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> ToolCallRecord:
        self.get_tool_call(user_id, tool_call_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE tool_calls SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, result, error, now, tool_call_id),
            )
        return self.get_tool_call(user_id, tool_call_id)

    def create_workflow(
        self,
        user_id: str,
        skill_name: str,
        project_id: str | None,
        conversation_id: str | None,
        input_summary: str = "",
        stage: str = "created",
    ) -> Workflow:
        project_id = project_id or self.ensure_default_project(user_id).id
        self.get_project(user_id, project_id)
        if conversation_id:
            conversation = self.get_conversation(user_id, conversation_id)
        else:
            conversation = self.create_conversation(user_id, WorkbenchConversationCreate(project_id=project_id, title=input_summary[:32] or skill_name))
        workflow_id = str(uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO workflows (id, skill_name, project_id, conversation_id, status, stage, input_summary, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (workflow_id, skill_name, project_id, conversation.id, "created", stage, input_summary, now, now),
            )
            self._touch_conversation(conversation.id, now)
            self._touch_project(project_id, now)
        return self.get_workflow(user_id, workflow_id)

    def get_workflow(self, user_id: str, workflow_id: str) -> Workflow:
        row = self._execute(
            "SELECT workflows.* FROM workflows JOIN projects ON projects.id = workflows.project_id WHERE workflows.id = ? AND projects.owner_user_id = ?",
            (workflow_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(workflow_id)
        return self._workflow_from_row(row)

    def list_workflows(self, user_id: str, conversation_id: str | None = None) -> list[Workflow]:
        if conversation_id:
            self.get_conversation(user_id, conversation_id)
            rows = self._execute("SELECT * FROM workflows WHERE conversation_id = ? ORDER BY updated_at DESC", (conversation_id,)).fetchall()
        else:
            rows = self._execute("SELECT workflows.* FROM workflows JOIN projects ON projects.id = workflows.project_id WHERE projects.owner_user_id = ? ORDER BY workflows.updated_at DESC", (user_id,)).fetchall()
        return [self._workflow_from_row(row) for row in rows]

    def update_workflow(
        self,
        user_id: str,
        workflow_id: str,
        status: str | None = None,
        stage: str | None = None,
        input_summary: str | None = None,
        error: str | None = None,
    ) -> Workflow:
        workflow = self.get_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
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
        return self.get_workflow(user_id, workflow_id)

    def save_workflow_artifacts(self, user_id: str, workflow_id: str, files: dict[str, tuple[str, str, str]]) -> list[WorkflowArtifact]:
        self.get_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
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
        return self.list_workflow_artifacts(user_id, workflow_id)

    def list_workflow_artifacts(self, user_id: str, workflow_id: str) -> list[WorkflowArtifact]:
        self.get_workflow(user_id, workflow_id)
        rows = self._execute("SELECT * FROM workflow_artifacts WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,)).fetchall()
        return [self._workflow_artifact_from_row(row) for row in rows]

    def get_workflow_artifact_content(self, user_id: str, workflow_id: str, name: str) -> tuple[str, str]:
        self.get_workflow(user_id, workflow_id)
        row = self._execute(
            "SELECT content, mime_type FROM workflow_artifacts WHERE workflow_id = ? AND name = ?",
            (workflow_id, name),
        ).fetchone()
        if not row or row["content"] is None:
            raise KeyError(name)
        return row["content"], row["mime_type"]

    def get_workflow_artifact_files(self, user_id: str, workflow_id: str) -> dict[str, str]:
        self.get_workflow(user_id, workflow_id)
        rows = self._execute("SELECT name, content FROM workflow_artifacts WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,)).fetchall()
        return {row["name"]: row["content"] or "" for row in rows}

    def list_messages(self, user_id: str, conversation_id: str) -> list[WorkbenchMessage]:
        self.get_conversation(user_id, conversation_id)
        rows = self._execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        status: str = "completed",
        model: str | None = None,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
        message_id: str | None = None,
    ) -> WorkbenchMessage:
        conversation = self.get_conversation(user_id, conversation_id)
        message_id = message_id or str(uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO messages
                    (id, conversation_id, role, content, status, model, finish_reason, usage_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    status,
                    model,
                    finish_reason,
                    json.dumps(usage) if usage else None,
                    error,
                    now,
                    now,
                ),
            )
            self._touch_conversation(conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search(user_id, "message", message_id, conversation.project_id, conversation_id, role, content)
        return self.get_message(user_id, message_id)

    def update_message(
        self,
        user_id: str,
        message_id: str,
        content: str,
        status: str,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> WorkbenchMessage:
        message = self.get_message(user_id, message_id)
        conversation = self.get_conversation(user_id, message.conversation_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE messages
                SET content = ?, status = ?, finish_reason = ?, usage_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (content, status, finish_reason, json.dumps(usage) if usage else None, error, now, message_id),
            )
            self._touch_conversation(message.conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search(user_id, "message", message_id, conversation.project_id, message.conversation_id, message.role, content)
        return self.get_message(user_id, message_id)

    def update_streaming_message(self, user_id: str, message_id: str, content: str) -> None:
        """Persist partial LLM output without repeatedly updating search indexes."""
        self.get_message(user_id, message_id)
        with self._lock, self._connection:
            self._execute(
                "UPDATE messages SET content = ?, updated_at = ? WHERE id = ? AND status = 'streaming'",
                (content, utc_now(), message_id),
            )

    def get_message(self, user_id: str, message_id: str) -> WorkbenchMessage:
        row = self._execute(
            """
            SELECT messages.* FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            JOIN projects ON projects.id = conversations.project_id
            WHERE messages.id = ? AND projects.owner_user_id = ?
            """,
            (message_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(message_id)
        return self._message_from_row(row)

    def list_provider_profiles(self, user_id: str) -> list[ProviderProfile]:
        rows = self._execute("SELECT * FROM provider_profiles WHERE owner_user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._provider_from_row(row) for row in rows]

    def create_provider_profile(self, user_id: str, request: ProviderProfileCreate) -> ProviderProfile:
        profile_id = str(uuid4())
        now = utc_now()
        credential_key = f"provider:{user_id}:{profile_id}"
        api_key = request.api_key.strip() if request.api_key else None
        if api_key:
            self.set_credential(user_id, credential_key, api_key)
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO provider_profiles (id, owner_user_id, provider, display_name, base_url, model, credential_key, has_key, api_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    user_id,
                    request.provider,
                    request.display_name,
                    request.base_url,
                    request.model,
                    credential_key,
                    1 if api_key else 0,
                    None,
                    now,
                    now,
                ),
            )
        return self.get_provider_profile(user_id, profile_id)

    def get_provider_profile(self, user_id: str, profile_id: str) -> ProviderProfile:
        row = self._execute("SELECT * FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        if not row:
            raise KeyError(profile_id)
        return self._provider_from_row(row)

    def update_provider_profile(self, user_id: str, profile_id: str, request: ProviderProfileUpdate) -> ProviderProfile:
        profile = self.get_provider_profile(user_id, profile_id)
        row = self._execute("SELECT credential_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        now = utc_now()
        if request.api_key is not None:
            api_key = request.api_key.strip() if request.api_key else None
            has_key = 1 if api_key else 0
            credential_key = row["credential_key"] if row else f"provider:{user_id}:{profile_id}"
            if api_key:
                self.set_credential(user_id, credential_key, api_key)
            else:
                self.delete_credential(user_id, credential_key)
        else:
            has_key = int(profile.has_key)
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE provider_profiles
                SET provider = ?, display_name = ?, base_url = ?, model = ?, has_key = ?, api_key = NULL, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    request.provider if request.provider is not None else profile.provider,
                    request.display_name if request.display_name is not None else profile.display_name,
                    request.base_url if request.base_url is not None else profile.base_url,
                    request.model if request.model is not None else profile.model,
                    has_key,
                    now,
                    profile_id,
                    user_id,
                ),
            )
        return self.get_provider_profile(user_id, profile_id)

    def get_setting(self, key: str) -> str | None:
        row = self._execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_user_setting(self, user_id: str, key: str) -> str | None:
        row = self._execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
        return row["value"] if row else None

    def set_user_setting(self, user_id: str, key: str, value: str) -> None:
        now = utc_now()
        self._execute(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (user_id, key, value, now),
        )

    def get_theme_preferences(self, user_id: str) -> dict:
        """读取外观偏好（JSON 存于 user_settings.theme.preferences），脏值/缺失回退空 dict。"""
        raw = self.get_user_setting(user_id, "theme.preferences")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_theme_preferences(self, user_id: str, preferences: dict) -> None:
        self.set_user_setting(user_id, "theme.preferences", json.dumps(preferences, ensure_ascii=False))

    def _theme_from_row(self, row: sqlite3.Row) -> UserTheme:
        return UserTheme(
            id=row["id"], name=row["name"], source="custom",
            appearance=ThemeAppearance(row["appearance"]),
            width=row["width"], height=row["height"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_user_themes(self, user_id: str) -> list[UserTheme]:
        rows = self._execute(
            "SELECT * FROM user_themes WHERE owner_user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [self._theme_from_row(row) for row in rows]

    def get_user_theme(self, user_id: str, theme_id: str) -> UserTheme:
        row = self._execute(
            "SELECT * FROM user_themes WHERE id = ? AND owner_user_id = ?",
            (theme_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(theme_id)
        theme = self._theme_from_row(row)
        return theme.model_copy(update={"image_path": row["image_path"], "media_type": row["media_type"]})

    def create_user_theme(
        self, user_id: str, *, theme_id: str, name: str, image_path: str,
        media_type: str, width: int, height: int, appearance: ThemeAppearance,
    ) -> UserTheme:
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """INSERT INTO user_themes (id, owner_user_id, name, image_path, media_type, width, height, appearance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (theme_id, user_id, name, image_path, media_type, width, height, appearance.value, now, now),
            )
        return self.get_user_theme(user_id, theme_id)

    def delete_user_theme(self, user_id: str, theme_id: str) -> UserTheme:
        theme = self.get_user_theme(user_id, theme_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM user_themes WHERE id = ? AND owner_user_id = ?", (theme_id, user_id))
        return theme

    def get_active_theme_id(self, user_id: str) -> str:
        return self.get_user_setting(user_id, "theme.active_id") or "system"

    def set_active_theme_id(self, user_id: str, theme_id: str) -> None:
        self.set_user_setting(user_id, "theme.active_id", theme_id)

    def get_web_search_config(self, user_id: str) -> WebSearchConfig:
        max_results_raw = self.get_user_setting(user_id, "web_search.max_results")
        search_depth = self.get_user_setting(user_id, "web_search.search_depth") or os.getenv("TAVILY_SEARCH_DEPTH", "basic")
        try:
            max_results = int(max_results_raw or os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
        except ValueError:
            max_results = 5
        max_results = min(max(max_results, 1), 10)
        if search_depth not in {"basic", "advanced"}:
            search_depth = "basic"
        key, source = self._resolve_tavily_api_key_with_source(user_id)
        return WebSearchConfig(
            provider="tavily",
            has_key=key is not None,
            source=source,
            max_results=max_results,
            search_depth=search_depth,
        )

    def update_web_search_config(self, user_id: str, request: WebSearchConfigUpdate) -> WebSearchConfig:
        if request.api_key is not None:
            key = request.api_key.strip() or None
            credential_key = self._tavily_credential_key(user_id)
            if key:
                self.set_credential(user_id, credential_key, key)
            else:
                self.delete_credential(user_id, credential_key)
            self.set_user_setting(user_id, "web_search.api_key", "")
            self.set_user_setting(user_id, "web_search.has_key", "1" if key else "0")
        if request.max_results is not None:
            self.set_user_setting(user_id, "web_search.max_results", str(request.max_results))
        if request.search_depth is not None:
            self.set_user_setting(user_id, "web_search.search_depth", request.search_depth)
        return self.get_web_search_config(user_id)

    def delete_provider_profile(self, user_id: str, profile_id: str) -> None:
        row = self._execute("SELECT credential_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        self.get_provider_profile(user_id, profile_id)
        if row:
            self.delete_credential(user_id, row["credential_key"])
        with self._lock, self._connection:
            self._execute("DELETE FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id))

    def resolve_api_key(self, user_id: str, profile_id: str | None, inline_api_key: str | None = None) -> str | None:
        if inline_api_key:
            return inline_api_key
        if not profile_id:
            return None
        row = self._execute("SELECT credential_key, has_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        if not row:
            raise KeyError(profile_id)
        if not row["has_key"]:
            return None
        return self.get_credential(user_id, row["credential_key"])

    def resolve_tavily_api_key(self, user_id: str) -> str | None:
        """返回 Tavily API key。

        优先级：DB 中用户保存的 key > 环境变量（.env 部署默认）。
        """
        key, _ = self._resolve_tavily_api_key_with_source(user_id)
        return key

    def _resolve_tavily_api_key_with_source(self, user_id: str) -> tuple[str | None, str]:
        """返回 (api_key, source)，source 为 'vault' / 'env' / 'none'。"""
        user_key = self.get_credential(user_id, self._tavily_credential_key(user_id))
        if user_key:
            return user_key, "vault"
        env_key = os.getenv("TAVILY_API_KEY", "").strip()
        if env_key:
            return env_key, "env"
        return None, "none"

    def _tavily_credential_key(self, user_id: str) -> str:
        return f"tavily:{user_id}"

    def search(self, user_id: str, query: str, kind: str | None = None) -> list[SearchResult]:
        trimmed = query.strip()
        if not trimmed:
            return []
        normalized_kind = kind.strip() if kind else ""
        kind_clause = " AND kind = ?" if normalized_kind else ""
        search_params = [trimmed, user_id]
        if normalized_kind:
            search_params.append(normalized_kind)
        try:
            rows = self._execute(
                f"""
                SELECT kind, source_id, project_id, conversation_id, title, snippet(search_index, 5, '', '', '...', 12) AS excerpt
                FROM search_index
                WHERE search_index MATCH ? AND owner_user_id = ?{kind_clause}
                ORDER BY rank
                LIMIT 30
                """,
                search_params,
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            like_query = f"%{trimmed}%"
            fallback_params = [user_id, like_query, like_query]
            if normalized_kind:
                fallback_params.append(normalized_kind)
            rows = self._execute(
                f"""
                SELECT kind, source_id, project_id, conversation_id, title, content AS excerpt
                FROM search_index
                WHERE owner_user_id = ? AND (title LIKE ? OR content LIKE ?){kind_clause}
                ORDER BY title
                LIMIT 30
                """,
                fallback_params,
            ).fetchall()
        return [
            SearchResult(
                kind=row["kind"],
                id=row["source_id"],
                title=row["title"] or row["kind"],
                excerpt=row["excerpt"] or "",
                conversation_id=row["conversation_id"],
                project_id=row["project_id"],
            )
            for row in rows
        ]

    def _touch_project(self, project_id: str, when: str | None = None) -> None:
        self._execute("UPDATE projects SET updated_at = ? WHERE id = ?", (when or utc_now(), project_id))

    def _touch_conversation(self, conversation_id: str, when: str | None = None) -> None:
        self._execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (when or utc_now(), conversation_id))

    def _upsert_search(
        self,
        user_id: str,
        kind: str,
        source_id: str,
        project_id: str | None,
        conversation_id: str | None,
        title: str,
        content: str,
    ) -> None:
        self._execute("DELETE FROM search_index WHERE owner_user_id = ? AND kind = ? AND source_id = ?", (user_id, kind, source_id))
        self._execute(
            """
            INSERT INTO search_index (owner_user_id, kind, source_id, project_id, conversation_id, title, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, kind, source_id, project_id, conversation_id, title, content),
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
        return WorkbenchMessage(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            status=row["status"],
            model=row["model"],
            finish_reason=row["finish_reason"],
            usage=json.loads(row["usage_json"]) if row["usage_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _provider_from_row(self, row: sqlite3.Row) -> ProviderProfile:
        return ProviderProfile(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            base_url=row["base_url"],
            model=row["model"],
            has_key=bool(row["has_key"]),
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

