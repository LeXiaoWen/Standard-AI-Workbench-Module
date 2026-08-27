import type {
  AuthLoginResponse,
  AuthStatus,
  AuthUser,
  ChatStreamEvent,
  HealthResponse,
  KnowledgeDraft,
  KnowledgeLintReport,
  KnowledgePage,
  KnowledgeSource,
  KnowledgeVault,
  McpServer,
  McpServerCreate,
  McpServerUpdate,
  McpTool,
  ProviderModel,
  ProviderProfile,
  ResumeToolCallEvent,
  SearchResult,
  SearchResultKind,
  SkillMetadata,
  ThemeAppearance,
  ThemeListResponse,
  ThemePreferences,
  UserTheme,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
  Workflow,
  WorkflowActionResponse,
  WorkflowArtifact,
} from "./types";

let apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8765";

let authToken: string | null = null;
let appAuthSecret: string | null = null;
const APP_AUTH_SECRET_STORAGE_KEY = "ai-workbench-app-auth-secret";
const LOCAL_BACKEND_RETRY_ATTEMPTS = 10;
const LOCAL_BACKEND_RETRY_DELAY_MS = 250;

export function setApiBaseUrl(url: string | null | undefined): void {
  if (url) apiBaseUrl = url.replace(/\/$/, "");
}

export function setAuthContext(next: { token?: string | null; appSecret?: string | null }): void {
  if ("token" in next) authToken = next.token ?? null;
  if ("appSecret" in next) {
    appAuthSecret = next.appSecret ?? null;
    if (typeof window !== "undefined") {
      if (appAuthSecret) {
        window.sessionStorage.setItem(APP_AUTH_SECRET_STORAGE_KEY, appAuthSecret);
      } else {
        window.sessionStorage.removeItem(APP_AUTH_SECRET_STORAGE_KEY);
      }
    }
  }
}

function currentAppAuthSecret(): string | null {
  if (appAuthSecret) return appAuthSecret;
  if (typeof window === "undefined") return null;
  appAuthSecret = window.sessionStorage.getItem(APP_AUTH_SECRET_STORAGE_KEY);
  return appAuthSecret;
}

function withAuthHeaders(options?: RequestInit): RequestInit {
  const headers = new Headers(options?.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const secret = currentAppAuthSecret();
  if (secret) headers.set("X-App-Auth-Secret", secret);
  return { ...options, headers };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function localBackendConnectionError(): Error {
  return new Error(`无法连接本地后端：${apiBaseUrl}。请确认桌面应用后端已启动，或检查当前页面地址是否被 CORS 允许。`);
}

async function fetchWithLocalRetry(url: string, options?: RequestInit): Promise<Response> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < LOCAL_BACKEND_RETRY_ATTEMPTS; attempt += 1) {
    try {
      return await fetch(url, options);
    } catch (caught) {
      lastError = caught;
      await sleep(LOCAL_BACKEND_RETRY_DELAY_MS);
    }
  }
  throw lastError instanceof Error ? localBackendConnectionError() : localBackendConnectionError();
}

async function requestOnce(path: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${apiBaseUrl}${path}`, withAuthHeaders(options));
  } catch {
    throw localBackendConnectionError();
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetchWithLocalRetry(`${apiBaseUrl}${path}`, withAuthHeaders(options));
  } catch (error) {
    throw localBackendConnectionError();
  }
  if (!response.ok) {
    if (response.status === 401 && authToken && !path.startsWith("/api/v1/auth/")) {
      window.dispatchEvent(new Event("ai-workbench-auth-expired"));
    }
    let detail = `请求失败：${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the status fallback when the body is not JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

/** 单次请求，不重试。用于状态轮询场景，由外层控制重试节奏。 */
async function quickRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await requestOnce(path, options);
  if (!response.ok) {
    let detail = `请求失败：${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the status fallback.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getAuthStatus(): Promise<AuthStatus> {
  return quickRequest<AuthStatus>("/api/v1/auth/status");
}

export function registerAuth(input: { username: string; password: string }): Promise<AuthLoginResponse> {
  return request<AuthLoginResponse>("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function loginAuth(input: { username: string; password: string }): Promise<AuthLoginResponse> {
  return request<AuthLoginResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function logoutAuth(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export function getMe(): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/me");
}

export function changePassword(input: { current_password: string; new_password: string }): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function listProjects(): Promise<WorkbenchProject[]> {
  return request<WorkbenchProject[]>("/api/v1/projects");
}

export function createProject(input: { title?: string; workspace_path?: string } = {}): Promise<WorkbenchProject> {
  return request<WorkbenchProject>("/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: input.title ?? "新项目", workspace_path: input.workspace_path }),
  });
}

export function deleteProject(projectId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/projects/${projectId}`, { method: "DELETE" });
}

export function listConversations(projectId?: string): Promise<WorkbenchConversation[]> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return request<WorkbenchConversation[]>(`/api/v1/conversations${suffix}`);
}

export function createConversation(input: {
  project_id?: string;
  title?: string;
  provider_profile_id?: string;
  model?: string;
}): Promise<WorkbenchConversation> {
  return request<WorkbenchConversation>("/api/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function listMessages(conversationId: string): Promise<WorkbenchMessage[]> {
  return request<WorkbenchMessage[]>(`/api/v1/conversations/${conversationId}/messages`);
}

export function deleteConversation(conversationId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/conversations/${conversationId}`, { method: "DELETE" });
}

export function updateConversation(
  conversationId: string,
  input: {
    title?: string;
    provider_profile_id?: string;
    model?: string;
  },
): Promise<WorkbenchConversation> {
  return request<WorkbenchConversation>(`/api/v1/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function listProviderProfiles(): Promise<ProviderProfile[]> {
  return request<ProviderProfile[]>("/api/v1/provider-profiles");
}

export function createProviderProfile(input: {
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
  api_key?: string;
}): Promise<ProviderProfile> {
  return request<ProviderProfile>("/api/v1/provider-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateProviderProfile(
  profileId: string,
  input: Partial<{
    provider: string;
    display_name: string;
    base_url: string;
    model: string;
    api_key: string;
  }>,
): Promise<ProviderProfile> {
  return request<ProviderProfile>(`/api/v1/provider-profiles/${profileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listProviderModels(profileId: string): Promise<ProviderModel[]> {
  const payload = await request<{ models: ProviderModel[] }>(`/api/v1/provider-profiles/${profileId}/models`);
  return payload.models;
}

export function searchWorkbench(query: string, kind?: SearchResultKind): Promise<SearchResult[]> {
  const filter = kind ? `&kind=${encodeURIComponent(kind)}` : "";
  return request<SearchResult[]>(`/api/v1/search?q=${encodeURIComponent(query)}${filter}`);
}

export function getWebSearchConfig(): Promise<WebSearchConfig> {
  return request<WebSearchConfig>("/api/v1/web-search-config");
}

export function updateWebSearchConfig(input: {
  api_key?: string;
  max_results?: number;
  search_depth?: string;
}): Promise<WebSearchConfig> {
  return request<WebSearchConfig>("/api/v1/web-search-config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function cancelChat(runId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/chat/${runId}/cancel`, { method: "POST" });
}

// ----- 主题 -----

export function listThemes(): Promise<ThemeListResponse> {
  return request<ThemeListResponse>("/api/v1/themes");
}

export function uploadTheme(input: { file: File; name?: string; appearance: ThemeAppearance }): Promise<UserTheme> {
  const body = new FormData();
  body.append("file", input.file);
  body.append("name", input.name?.trim() || input.file.name.replace(/\.[^.]+$/, ""));
  body.append("appearance", input.appearance);
  return request<UserTheme>("/api/v1/themes", { method: "POST", body });
}

export function activateTheme(themeId: string): Promise<ThemeListResponse> {
  return request<ThemeListResponse>("/api/v1/themes/active", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme_id: themeId }),
  });
}

export function deleteTheme(themeId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/themes/${themeId}`, { method: "DELETE" });
}

export async function downloadThemeImage(path: string): Promise<Blob> {
  const response = await fetchWithLocalRetry(`${apiBaseUrl}${path}`, withAuthHeaders());
  if (!response.ok) throw new Error("无法加载主题背景。");
  return response.blob();
}

export function getThemePreferences(): Promise<ThemePreferences> {
  return request<ThemePreferences>("/api/v1/themes/preferences");
}

export function updateThemePreferences(prefs: Partial<ThemePreferences>): Promise<ThemePreferences> {
  return request<ThemePreferences>("/api/v1/themes/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
}

// ----- 知识库 -----

export function getKnowledgeVault(projectId: string): Promise<KnowledgeVault> {
  return request<KnowledgeVault>(`/api/v1/projects/${projectId}/knowledge-vault`);
}

export function listKnowledgeSources(projectId: string): Promise<KnowledgeSource[]> {
  return request<KnowledgeSource[]>(`/api/v1/projects/${projectId}/knowledge-sources`);
}

export async function uploadKnowledgeSource(projectId: string, file: File): Promise<KnowledgeSource> {
  const body = new FormData();
  body.append("file", file);
  return request<KnowledgeSource>(`/api/v1/projects/${projectId}/knowledge-sources`, { method: "POST", body });
}

export function compileKnowledgeSource(
  projectId: string,
  sourceId: string,
  providerProfileId?: string,
): Promise<KnowledgeDraft> {
  const body = new FormData();
  if (providerProfileId) body.append("provider_profile_id", providerProfileId);
  return request<KnowledgeDraft>(`/api/v1/projects/${projectId}/knowledge-sources/${sourceId}/compile`, {
    method: "POST",
    body,
  });
}

export function listKnowledgeDrafts(projectId: string): Promise<KnowledgeDraft[]> {
  return request<KnowledgeDraft[]>(`/api/v1/projects/${projectId}/knowledge-drafts`);
}

export function confirmKnowledgeDraft(projectId: string, draftId: string, approved: boolean): Promise<KnowledgeDraft> {
  const body = new FormData();
  body.append("approved", String(approved));
  return request<KnowledgeDraft>(`/api/v1/projects/${projectId}/knowledge-drafts/${draftId}/confirm`, {
    method: "POST",
    body,
  });
}

export function listKnowledgePages(projectId: string, query = ""): Promise<KnowledgePage[]> {
  return request<KnowledgePage[]>(`/api/v1/projects/${projectId}/knowledge-pages?q=${encodeURIComponent(query)}`);
}

export function lintKnowledgeVault(projectId: string): Promise<KnowledgeLintReport> {
  return request<KnowledgeLintReport>(`/api/v1/projects/${projectId}/knowledge-lint`);
}

// ----- MCP 服务器 -----

export function listMcpServers(): Promise<McpServer[]> {
  return request<McpServer[]>("/api/v1/mcp-servers");
}

export function createMcpServer(input: McpServerCreate): Promise<McpServer> {
  return request<McpServer>("/api/v1/mcp-servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateMcpServer(serverId: string, input: McpServerUpdate): Promise<McpServer> {
  return request<McpServer>(`/api/v1/mcp-servers/${serverId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function deleteMcpServer(serverId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/mcp-servers/${serverId}`, { method: "DELETE" });
}

export async function refreshMcpTools(serverId: string): Promise<McpTool[]> {
  const payload = await request<{ tools: McpTool[] }>(`/api/v1/mcp-servers/${serverId}/refresh-tools`, {
    method: "POST",
  });
  return payload.tools;
}

// ----- 通用工作流 -----

export function listWorkflows(conversationId?: string): Promise<Workflow[]> {
  const suffix = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
  return request<Workflow[]>(`/api/v1/workflows${suffix}`);
}

export function createWorkflow(input: {
  skill_name: string;
  project_id?: string;
  conversation_id?: string;
  input_text?: string;
}): Promise<Workflow> {
  return request<Workflow>("/api/v1/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getWorkflow(workflowId: string): Promise<Workflow> {
  return request<Workflow>(`/api/v1/workflows/${workflowId}`);
}

export function runWorkflow(workflowId: string, input_text = ""): Promise<WorkflowActionResponse> {
  return request<WorkflowActionResponse>(`/api/v1/workflows/${workflowId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_text }),
  });
}

export function confirmWorkflow(workflowId: string, text = ""): Promise<WorkflowActionResponse> {
  return request<WorkflowActionResponse>(`/api/v1/workflows/${workflowId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function cancelWorkflow(workflowId: string): Promise<WorkflowActionResponse> {
  return request<WorkflowActionResponse>(`/api/v1/workflows/${workflowId}/cancel`, { method: "POST" });
}

export function listWorkflowArtifacts(workflowId: string): Promise<WorkflowArtifact[]> {
  return request<WorkflowArtifact[]>(`/api/v1/workflows/${workflowId}/artifacts`);
}

export function getWorkflowArtifactUrl(workflowId: string, name: string): string {
  return `${apiBaseUrl}/api/v1/workflows/${workflowId}/artifacts/${encodeURIComponent(name)}`;
}

export function downloadWorkflowZipUrl(workflowId: string): string {
  return `${apiBaseUrl}/api/v1/workflows/${workflowId}/export.zip`;
}

export async function downloadWorkflowArtifact(workflowId: string, name: string): Promise<Blob> {
  const response = await fetch(getWorkflowArtifactUrl(workflowId, name), withAuthHeaders());
  if (!response.ok) throw new Error(`下载失败：${response.status}`);
  return response.blob();
}

export async function downloadWorkflowZip(workflowId: string): Promise<Blob> {
  const response = await fetch(downloadWorkflowZipUrl(workflowId), withAuthHeaders());
  if (!response.ok) throw new Error(`下载失败：${response.status}`);
  return response.blob();
}

// ----- Skills -----

export function listSkills(): Promise<SkillMetadata[]> {
  return request<SkillMetadata[]>("/api/v1/skills");
}

// ----- 工具调用审批 -----

export function approveToolCall(toolCallId: string): Promise<{ ok: boolean; status: string }> {
  return request<{ ok: boolean; status: string }>(`/api/v1/chat/tool-calls/${toolCallId}/approve`, { method: "POST" });
}

export function rejectToolCall(toolCallId: string): Promise<{ ok: boolean; status: string }> {
  return request<{ ok: boolean; status: string }>(`/api/v1/chat/tool-calls/${toolCallId}/reject`, { method: "POST" });
}

import { fetchEventSource } from "@microsoft/fetch-event-source";

export async function streamChat(
  input: {
    conversation_id?: string;
    project_id?: string;
    provider_profile_id?: string;
    model?: string;
    api_key?: string;
    message: string;
    system_prompt?: string;
    web_search_enabled?: boolean;
    mcp_server_ids?: string[];
  },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const requestOptions = withAuthHeaders({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    await fetchEventSource(`${apiBaseUrl}/api/v1/chat/stream`, {
      method: "POST",
      headers: Object.fromEntries(new Headers(requestOptions.headers).entries()),
      body: requestOptions.body as string,
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) return;
        if (response.status === 401 && authToken) {
          window.dispatchEvent(new Event("ai-workbench-auth-expired"));
        }
        let detail = `请求失败：${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.detail ?? detail;
        } catch {
          // Keep the HTTP fallback if an upstream response has no JSON body.
        }
        throw new Error(detail);
      },
      onmessage(message) {
        if (!message.event || !message.data) return;
        try {
          onEvent({ event: message.event as ChatStreamEvent["event"], data: JSON.parse(message.data) } as ChatStreamEvent);
        } catch {
          throw new Error("本地后端返回了无法识别的流式消息。");
        }
      },
      onerror(error) {
        // Re-throwing disables the library's automatic reconnect: replaying a POST could bill the LLM twice.
        throw error;
      },
    });
  } catch (error) {
    if (signal?.aborted) return;
    if (error instanceof Error) throw error;
    throw localBackendConnectionError();
  }
}

export async function resumeToolCallStream(
  toolCallId: string,
  onEvent: (event: ResumeToolCallEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const requestOptions = withAuthHeaders({ method: "POST" });
    await fetchEventSource(`${apiBaseUrl}/api/v1/chat/tool-calls/${toolCallId}/resume-stream`, {
      method: "POST",
      headers: Object.fromEntries(new Headers(requestOptions.headers).entries()),
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) return;
        let detail = `请求失败：${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.detail ?? detail;
        } catch {
          // Keep the HTTP fallback if an upstream response has no JSON body.
        }
        throw new Error(detail);
      },
      onmessage(message) {
        if (!message.event || !message.data) return;
        onEvent({ event: message.event as ResumeToolCallEvent["event"], data: JSON.parse(message.data) } as ResumeToolCallEvent);
      },
      onerror(error) {
        throw error;
      },
    });
  } catch (error) {
    if (signal?.aborted) return;
    if (error instanceof Error) throw error;
    throw localBackendConnectionError();
  }
}
