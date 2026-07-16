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
  ProviderModel,
  ProviderProfile,
  SearchResult,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "./types";

let apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8765";

let authToken: string | null = null;
let appAuthSecret: string | null = null;
const APP_AUTH_SECRET_STORAGE_KEY = "standard-workbench-app-auth-secret";
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

async function requestOnce(path: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${apiBaseUrl}${path}`, withAuthHeaders(options));
  } catch {
    throw localBackendConnectionError();
  }
}

/** 状态轮询由调用方控制重试节奏，避免一次请求阻塞登录界面。 */
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

export function searchWorkbench(query: string): Promise<SearchResult[]> {
  return request<SearchResult[]>(`/api/v1/search?q=${encodeURIComponent(query)}`);
}

export function getKnowledgeVault(projectId: string): Promise<KnowledgeVault> { return request<KnowledgeVault>(`/api/v1/projects/${projectId}/knowledge-vault`); }
export function listKnowledgeSources(projectId: string): Promise<KnowledgeSource[]> { return request<KnowledgeSource[]>(`/api/v1/projects/${projectId}/knowledge-sources`); }
export async function uploadKnowledgeSource(projectId: string, file: File): Promise<KnowledgeSource> { const body = new FormData(); body.append("file", file); return request<KnowledgeSource>(`/api/v1/projects/${projectId}/knowledge-sources`, { method: "POST", body }); }
export function compileKnowledgeSource(projectId: string, sourceId: string, providerProfileId?: string): Promise<KnowledgeDraft> { const body = new FormData(); if (providerProfileId) body.append("provider_profile_id", providerProfileId); return request<KnowledgeDraft>(`/api/v1/projects/${projectId}/knowledge-sources/${sourceId}/compile`, { method: "POST", body }); }
export function listKnowledgeDrafts(projectId: string): Promise<KnowledgeDraft[]> { return request<KnowledgeDraft[]>(`/api/v1/projects/${projectId}/knowledge-drafts`); }
export function confirmKnowledgeDraft(projectId: string, draftId: string, approved: boolean): Promise<KnowledgeDraft> { const body = new FormData(); body.append("approved", String(approved)); return request<KnowledgeDraft>(`/api/v1/projects/${projectId}/knowledge-drafts/${draftId}/confirm`, { method: "POST", body }); }
export function listKnowledgePages(projectId: string, query = ""): Promise<KnowledgePage[]> { return request<KnowledgePage[]>(`/api/v1/projects/${projectId}/knowledge-pages?q=${encodeURIComponent(query)}`); }
export function lintKnowledgeVault(projectId: string): Promise<KnowledgeLintReport> { return request<KnowledgeLintReport>(`/api/v1/projects/${projectId}/knowledge-lint`); }

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

export function parseSseChunk(chunk: string): ChatStreamEvent[] {
  return chunk
    .split("\n\n")
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const eventLine = block.split("\n").find((line) => line.startsWith("event:"));
      const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
      if (!eventLine || !dataLine) return null;
      const event = eventLine.replace("event:", "").trim() as ChatStreamEvent["event"];
      const data = JSON.parse(dataLine.replace("data:", "").trim());
      return { event, data } as ChatStreamEvent;
    })
    .filter((event): event is ChatStreamEvent => event !== null);
}

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
  },
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const response = await fetchWithLocalRetry(`${apiBaseUrl}/api/v1/chat/stream`, {
    ...withAuthHeaders({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    }),
  });

  if (!response.ok || !response.body) {
    let detail = `请求失败：${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep status fallback.
    }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      for (const event of parseSseChunk(`${part}\n\n`)) {
        onEvent(event);
      }
    }
  }

  if (buffer.trim()) {
    for (const event of parseSseChunk(buffer)) {
      onEvent(event);
    }
  }
}
