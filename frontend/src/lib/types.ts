export type WorkbenchProject = {
  id: string;
  title: string;
  workspace_path?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkbenchConversation = {
  id: string;
  project_id: string;
  title: string;
  provider_profile_id?: string | null;
  model?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkbenchMessage = {
  id: string;
  conversation_id: string;
  role: "system" | "user" | "assistant" | string;
  content: string;
  status: "streaming" | "completed" | "interrupted" | "error" | "tool_pending" | string;
  model?: string | null;
  finish_reason?: string | null;
  usage?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProviderProfile = {
  id: string;
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
  has_key: boolean;
  created_at: string;
  updated_at: string;
};

export type ProviderModel = {
  id: string;
  name: string;
};

export type WebSearchConfig = {
  provider: "tavily" | string;
  has_key: boolean;
  source: "db" | "env" | "none" | string;
  max_results: number;
  search_depth: "basic" | "advanced" | string;
};

export type ProviderModelsResponse = {
  models: ProviderModel[];
};

export type SearchResultKind = "project" | "conversation" | "message";

export type SearchResult = {
  kind: SearchResultKind;
  id: string;
  title: string;
  excerpt: string;
  conversation_id?: string | null;
  project_id?: string | null;
};

export type HealthResponse = {
  ok: boolean;
  app: string;
  version: string;
  database: string;
  presets: Record<string, { provider: string; base_url: string; model: string }>;
};

export type AuthStatus = {
  authenticated: boolean;
  username?: string | null;
  registration_allowed: boolean;
};

export type AuthLoginResponse = {
  token: string;
  expires_at: string;
  username: string;
};

export type AuthUser = {
  id: string;
  username: string;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
};

export type ThemeAppearance = "auto" | "light" | "dark";

export type UserTheme = {
  id: string;
  name: string;
  source: "system" | "custom";
  appearance: ThemeAppearance;
  image_url?: string | null;
  width?: number | null;
  height?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ThemeListResponse = {
  active_theme_id: string;
  themes: UserTheme[];
};

export type WallpaperKind = "image" | "url" | "gradient";

/** 外观偏好（预设皮肤 / 强调色 / 壁纸 2.0），与后端 schemas.ThemePreferences 对齐 */
export type ThemePreferences = {
  skin_id: string;
  accent?: string | null;
  wallpaper_kind?: WallpaperKind | null;
  wallpaper_url?: string | null;
  wallpaper_gradient?: string | null;
  wallpaper_opacity?: number;
  wallpaper_blur?: number;
  wallpaper_autodim?: boolean;
};

export type McpServer = {
  id: string;
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type McpServerCreate = {
  name: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
  enabled?: boolean;
};

export type McpServerUpdate = Partial<McpServerCreate>;

export type McpTool = {
  server_id: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  created_at: string;
};

/** 待用户确认/展示的工具调用信息（来自 tool_call_pending 流事件） */
export type ToolCallInfo = {
  id: string;
  tool_name: string;
  schema_name: string;
  tool_kind: string;
  arguments: Record<string, unknown>;
  requires_approval: boolean;
};

export type ToolCallStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "running"
  | "done"
  | "failed";

export type WorkflowStatus =
  | "created"
  | "running"
  | "waiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled";

export type Workflow = {
  id: string;
  skill_name: string;
  project_id: string;
  conversation_id: string;
  status: WorkflowStatus | string;
  stage: string;
  input_summary: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkflowActionResponse = {
  workflow: Workflow;
  message: string;
};

export type WorkflowArtifact = {
  workflow_id: string;
  name: string;
  kind: string;
  mime_type: string;
  size: number;
  created_at: string;
};

export type SkillMetadata = {
  skill_name: string;
  display_name: string;
  description: string;
  accepted_inputs: string[];
  stages: string[];
};

export type KnowledgeVault = {
  project_id: string;
  source_count: number;
  page_count: number;
  path: string;
};

export type KnowledgeSource = {
  id: string;
  project_id: string;
  filename: string;
  content_hash: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgePatch = {
  path: string;
  operation: string;
  content: string;
};

export type KnowledgeDraft = {
  id: string;
  project_id: string;
  source_id: string;
  status: string;
  patches: KnowledgePatch[];
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgePage = {
  path: string;
  title: string;
  content: string;
};

export type KnowledgeLintReport = {
  missing_index: string[];
  broken_links: string[];
  orphan_pages: string[];
  stale_sources: string[];
};

export type ChatStreamEvent =
  | {
      event: "message_start";
      data: {
        conversation_id: string;
        message_id: string;
        user_message_id: string;
        run_id: string;
        model: string;
        usage?: Record<string, unknown> | null;
      };
    }
  | {
      event: "delta";
      data: {
        conversation_id: string;
        message_id: string;
        delta: string;
      };
    }
  | {
      event: "message_done";
      data: {
        conversation_id: string;
        message_id: string;
        status: "completed" | "interrupted" | "error";
        finish_reason?: string | null;
        usage?: Record<string, unknown> | null;
        content: string;
      };
    }
  | {
      event: "conversation_updated";
      data: {
        conversation_id: string;
        project_id: string;
        title: string;
      };
    }
  | {
      event: "tool_call_pending";
      data: {
        conversation_id: string;
        message_id: string;
        tool_call_id: string;
        tool_name: string;
        schema_name: string;
        tool_kind: string;
        arguments: Record<string, unknown>;
        requires_approval: boolean;
      };
    }
  | {
      event: "error";
      data: {
        conversation_id?: string;
        message_id?: string;
        type: string;
        message: string;
        content?: string;
      };
    }
  | {
      event: "warning";
      data: {
        conversation_id?: string;
        message_id?: string;
        type: string;
        message: string;
      };
    };

/** resume-tool 流事件（tool_call_result / tool_call_error / tool_call_rejected 及后续续答 delta/message_done） */
export type ResumeToolCallEvent =
  | {
      event: "tool_call_result";
      data: {
        conversation_id: string;
        message_id: string;
        tool_call_id: string;
        status: "running" | "done";
        result_preview?: string;
      };
    }
  | {
      event: "tool_call_error";
      data: {
        conversation_id: string;
        message_id: string;
        tool_call_id: string;
        message: string;
      };
    }
  | {
      event: "tool_call_rejected";
      data: {
        conversation_id: string;
        message_id: string;
        tool_call_id: string;
        message: string;
      };
    }
  | {
      event: "error";
      data: {
        conversation_id?: string;
        message_id?: string;
        type: string;
        message: string;
      };
    }
  | {
      event: "delta";
      data: {
        conversation_id: string;
        message_id: string;
        delta: string;
      };
    }
  | {
      event: "message_done";
      data: {
        conversation_id: string;
        message_id: string;
        status: "completed" | "interrupted" | "error";
        finish_reason?: string | null;
        usage?: Record<string, unknown> | null;
        content: string;
      };
    };
