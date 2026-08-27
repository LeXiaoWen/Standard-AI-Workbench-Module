"use client";

import { X } from "lucide-react";
import { ChangeEvent, FormEvent, Suspense, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { Panel, PanelGroup, PanelResizeHandle, type ImperativePanelHandle } from "react-resizable-panels";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  approveToolCall,
  cancelChat,
  changePassword,
  createConversation,
  downloadWorkflowArtifact,
  downloadWorkflowZip,
  rejectToolCall,
  resumeToolCallStream,
  searchWorkbench,
} from "@/lib/api";
import { ChatWorkspace } from "@/components/ChatWorkspace";
import { ConfigDialog, type ProviderProfileDraft, type ProviderProfileValues, type WebSearchValues } from "@/components/ConfigDialog";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthPanel, type AuthMode as AuthPanelMode } from "@/components/AuthPanel";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { McpPanel } from "@/components/McpPanel";
import { ThemePanel } from "@/components/ThemePanel";
import { ToolReasoning } from "@/components/ToolReasoning";
import { WorkbenchSidebar } from "@/components/WorkbenchSidebar";
import { WorkflowsPanel } from "@/components/WorkflowsPanel";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { useChatStream } from "@/hooks/useChatStream";
import { useConfiguration } from "@/hooks/useConfiguration";
import { useProviderModels } from "@/hooks/useProviderModels";
import { useWorkbenchData } from "@/hooks/useWorkbenchData";
import { useKnowledge } from "@/hooks/useKnowledge";
import { useMcpServers } from "@/hooks/useMcpServers";
import { useWorkflows } from "@/hooks/useWorkflows";
import type {
  ChatStreamEvent,
  ResumeToolCallEvent,
  SearchResult,
  SearchResultKind,
  ThemeAppearance,
  ToolCallInfo,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "@/lib/types";
import { applyChatStreamEvent } from "@/lib/chatReducer";

const providerPresets: ProviderProfileDraft[] = [
  { provider: "OpenAI", display_name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o" },
  { provider: "DeepSeek", display_name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  { provider: "通义千问 DashScope", display_name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { provider: "SiliconFlow", display_name: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { provider: "OpenRouter", display_name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { provider: "自定义", display_name: "自定义", base_url: "", model: "" },
];

const PROJECT_PREVIEW_CONVERSATION_LIMIT = 6;

const passwordChangeSchema = z
  .object({
    currentPassword: z.string().min(1, "请输入当前密码。"),
    newPassword: z.string().min(12, "新密码至少 12 位。"),
    confirmPassword: z.string(),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "两次输入的新密码不一致。",
  });

type PasswordChangeValues = z.infer<typeof passwordChangeSchema>;

function localMessage(role: "user" | "assistant", content: string, status: string): WorkbenchMessage {
  const now = new Date().toISOString();
  return {
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    conversation_id: "local",
    role,
    content,
    status,
    created_at: now,
    updated_at: now,
  };
}

function sanitizeFilename(value: string): string {
  return (value || "项目").replace(/[\\/:*?"<>|]/g, "_").trim() || "项目";
}

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [currentProfileId, setCurrentProfileId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchKind, setSearchKind] = useState<SearchResultKind | "all">("all");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const { isStreaming, send: sendChatStream, abort: abortChatStream } = useChatStream();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [userPanelOpen, setUserPanelOpen] = useState(false);
  const [pendingToolCall, setPendingToolCall] = useState<ToolCallInfo | null>(null);
  const toolResumeAbortRef = useRef<AbortController | null>(null);

  const {
    mode: authMode,
    backendReady: authBackendReady,
    user: authUser,
    initialize: initializeAuth,
    switchMode: switchAuthMode,
    submit: submitAuthRequest,
    logout: logoutAuthSession,
  } = useAuth(setError);
  const theme = useTheme(authMode === "ready");
  const {
    projects,
    projectConversations,
    recentConversations,
    messages,
    refreshProjects,
    refreshConversations,
    refreshMessages,
    updateMessages,
    clear: clearWorkbenchData,
    createProject: createProjectMutation,
    deleteProject: deleteProjectMutation,
    createConversation: createConversationMutation,
    deleteConversation: deleteConversationMutation,
    updateConversation,
  } = useWorkbenchData({ enabled: authMode === "ready", projectId: currentProjectId, conversationId: currentConversationId });
  const {
    profiles,
    webSearchConfig,
    error: configurationError,
    createProfile,
    updateProfile,
    updateWebSearch,
    refresh: refreshConfiguration,
    clear: clearConfiguration,
  } = useConfiguration(authMode === "ready");
  const knowledge = useKnowledge({ enabled: authMode === "ready", projectId: currentProjectId, profileId: currentProfileId });
  const mcp = useMcpServers(authMode === "ready");
  const workflows = useWorkflows({ enabled: authMode === "ready", conversationId: currentConversationId });

  const passwordChangeForm = useForm<PasswordChangeValues>({
    resolver: zodResolver(passwordChangeSchema),
    defaultValues: { currentPassword: "", newPassword: "", confirmPassword: "" },
  });
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [projectConversationsOpen, setProjectConversationsOpen] = useState(true);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [userChatAvatar, setUserChatAvatar] = useState("我");
  const [assistantChatAvatar, setAssistantChatAvatar] = useState("AI");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const sidebarPanelRef = useRef<ImperativePanelHandle>(null);
  const initialConversationSelectedRef = useRef(false);

  const currentProject = useMemo(() => projects.find((project) => project.id === currentProjectId) ?? null, [projects, currentProjectId]);
  const currentConversation = useMemo(
    () => [...projectConversations, ...recentConversations].find((conversation) => conversation.id === currentConversationId) ?? null,
    [projectConversations, recentConversations, currentConversationId],
  );
  const defaultProject = useMemo(
    () => projects.find((project) => !project.workspace_path && project.title === "默认项目") ?? projects.find((project) => !project.workspace_path) ?? null,
    [projects],
  );
  const projectPreviewConversations = useMemo(
    () => (currentProject?.workspace_path ? projectConversations.slice(0, PROJECT_PREVIEW_CONVERSATION_LIMIT) : []),
    [currentProject?.workspace_path, projectConversations],
  );
  const sidebarHistoryConversations = useMemo(() => {
    return recentConversations.filter((conversation) => conversation.project_id === defaultProject?.id);
  }, [defaultProject?.id, recentConversations]);
  const currentProfile = useMemo(() => profiles.find((profile) => profile.id === currentProfileId) ?? null, [profiles, currentProfileId]);
  const configProfile = useMemo<ProviderProfileDraft>(
    () => currentProfile ? { provider: currentProfile.provider, display_name: currentProfile.display_name, base_url: currentProfile.base_url, model: currentProfile.model } : providerPresets[0],
    [currentProfile],
  );
  const { models: providerModels, isLoading: isLoadingModels, error: providerModelsError } = useProviderModels(currentProfileId, modelMenuOpen);
  // 已启用的 MCP 服务器 → 作为聊天流可调用工具
  const mcpServerIds = useMemo(() => mcp.servers.filter((server) => server.enabled).map((server) => server.id), [mcp.servers]);

  useEffect(() => {
    void initializeAuth();
  }, [initializeAuth]);

  useEffect(() => {
    if (authMode !== "ready" || currentProjectId || projects.length === 0) return;
    const initialProject = projects.find((project) => !project.workspace_path && project.title === "默认项目") ?? projects.find((project) => !project.workspace_path) ?? projects[0];
    setCurrentProjectId(initialProject.id);
  }, [authMode, currentProjectId, projects]);

  useEffect(() => {
    if (authMode !== "ready" || currentProfileId || profiles.length === 0) return;
    setCurrentProfileId(profiles[0].id);
  }, [authMode, currentProfileId, profiles]);

  useEffect(() => {
    if (!configurationError) return;
    setError(configurationError instanceof Error ? configurationError.message : String(configurationError));
  }, [configurationError]);

  useEffect(() => {
    if (authMode !== "ready") {
      initialConversationSelectedRef.current = false;
      return;
    }
    if (initialConversationSelectedRef.current || currentConversationId || !currentProjectId || (projectConversations.length === 0 && recentConversations.length === 0)) return;
    const firstConversation = recentConversations.find((conversation) => conversation.project_id === currentProjectId) ?? projectConversations[0];
    if (!firstConversation) return;
    initialConversationSelectedRef.current = true;
    void openConversation(firstConversation.id);
  }, [authMode, currentConversationId, currentProjectId, projectConversations, recentConversations]);

  useEffect(() => {
    const handleAuthExpired = () => {
      void logoutUser();
      setError("登录会话已失效，请重新登录。");
    };
    window.addEventListener("ai-workbench-auth-expired", handleAuthExpired);
    return () => window.removeEventListener("ai-workbench-auth-expired", handleAuthExpired);
  }, []);

  useEffect(() => {
    if (authMode !== "ready" || !error) return;
    toast.error(error);
    setError(null);
  }, [authMode, error]);

  useEffect(() => {
    setUserChatAvatar(window.localStorage.getItem("workbench-user-avatar") || "我");
    setAssistantChatAvatar(window.localStorage.getItem("workbench-assistant-avatar") || "AI");
  }, []);

  useEffect(() => {
    setModelMenuOpen(false);
  }, [currentProfileId]);

  useEffect(() => {
    if (!modelMenuOpen || !providerModelsError) return;
    setModelMenuOpen(false);
    setConfigOpen(true);
    setUserPanelOpen(false);
    setError(providerModelsError instanceof Error ? providerModelsError.message : String(providerModelsError));
  }, [modelMenuOpen, providerModelsError]);

  useEffect(() => {
    if (webSearchConfig?.has_key === false && webSearchEnabled) {
      setWebSearchEnabled(false);
    }
  }, [webSearchConfig?.has_key, webSearchEnabled]);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        setSearchResults(await searchWorkbench(trimmed, searchKind === "all" ? undefined : searchKind));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    }, 240);
    return () => window.clearTimeout(timer);
  }, [searchKind, searchQuery]);

  useEffect(() => {
    return () => toolResumeAbortRef.current?.abort();
  }, []);

  async function openModelMenu() {
    if (!currentProfile?.has_key) {
      openConfigPanel();
      setError("请先配置模型 API。");
      return;
    }
    if (modelMenuOpen) {
      setModelMenuOpen(false);
      return;
    }
    setModelMenuOpen(true);
    setError(null);
  }

  async function chooseModel(modelId: string) {
    if (!currentProfileId || !currentProfile) return;
    try {
      const updated = await updateProfile(currentProfileId, { model: modelId });
      setCurrentProfileId(updated.id);
      setModelMenuOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function switchProject(project: WorkbenchProject) {
    setCurrentProjectId(project.id);
    setProjectConversationsOpen(true);
    setCurrentConversationId(null);
    await refreshConversations(project.id);
  }

  function toggleSidebar() {
    if (sidebarCollapsed) {
      sidebarPanelRef.current?.expand(22);
    } else {
      sidebarPanelRef.current?.collapse();
    }
  }

  async function chooseWorkspaceDirectory() {
    sidebarPanelRef.current?.expand(22);
    setError(null);
    const selected = await window.standardWorkbench?.selectDirectory();
    if (!selected) {
      if (!window.standardWorkbench) {
        setError("当前运行环境不支持选择本地工作目录，请在桌面端使用。");
      }
      return;
    }
    try {
      const latestProjects = await refreshProjects();
      const existingProject = latestProjects.find((project) => project.workspace_path === selected.path);
      if (existingProject) {
        await switchProject(existingProject);
        return;
      }
      const project = await createProjectMutation({ title: selected.name || "未命名项目", workspace_path: selected.path });
      await refreshProjects();
      await switchProject(project);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function openConversation(conversationId: string) {
    const targetConversation = [...projectConversations, ...recentConversations].find((conversation) => conversation.id === conversationId);
    if (targetConversation?.project_id && targetConversation.project_id !== currentProjectId) {
      setCurrentProjectId(targetConversation.project_id);
      void refreshConversations(targetConversation.project_id);
    }
    setCurrentConversationId(conversationId);
    setPendingToolCall(null);
    await refreshMessages(conversationId);
    setError(null);
  }

  async function removeProject(project: WorkbenchProject) {
    if (!window.confirm(`删除项目“${project.title}”？项目下的对话也会被删除。`)) return;
    try {
      await deleteProjectMutation(project.id);
      const nextProjects = await refreshProjects();
      const nextDefaultProject = nextProjects.find((item) => !item.workspace_path && item.title === "默认项目") ?? nextProjects.find((item) => !item.workspace_path);
      const nextProjectId = project.id === currentProjectId ? nextDefaultProject?.id ?? nextProjects[0]?.id ?? null : currentProjectId;
      setCurrentProjectId(nextProjectId);
      await refreshConversations(nextProjectId);
      if (project.id === currentProjectId) {
        setCurrentConversationId(null);
        setPendingToolCall(null);
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function removeConversation(conversation: WorkbenchConversation) {
    if (!window.confirm(`删除对话“${conversation.title}”？`)) return;
    try {
      await deleteConversationMutation(conversation.id);
      await refreshConversations(currentProjectId);
      if (conversation.id === currentConversationId) {
        setCurrentConversationId(null);
        setPendingToolCall(null);
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function startNewChat() {
    setError(null);
    try {
      const latestProjects = projects.length > 0 ? projects : await refreshProjects();
      const targetProject = latestProjects.find((project) => !project.workspace_path && project.title === "默认项目") ?? latestProjects.find((project) => !project.workspace_path);
      const conversation = await createConversationMutation({
        project_id: targetProject?.id,
        title: "新对话",
        provider_profile_id: currentProfileId ?? undefined,
        model: currentProfile?.model,
      });
      await refreshProjects();
      setCurrentProjectId(conversation.project_id);
      setCurrentConversationId(conversation.id);
      setInput("");
      setPendingToolCall(null);
      await refreshConversations(conversation.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function ensureConversation(text: string) {
    if (currentConversationId) return currentConversationId;
    const conversation = await createConversationMutation({
      project_id: currentProjectId ?? undefined,
      title: text.slice(0, 32) || "新对话",
      provider_profile_id: currentProfileId ?? undefined,
      model: currentProfile?.model,
    });
    setCurrentConversationId(conversation.id);
    await refreshConversations(conversation.project_id);
    return conversation.id;
  }

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setError(null);

    if (!currentProfileId || !currentProfile?.has_key) {
      setConfigOpen(true);
      setError("请先配置模型 API。");
      return;
    }
    if (webSearchEnabled && !webSearchConfig?.has_key) {
      setConfigOpen(true);
      setError("请先在模型配置中填写 Tavily API key。");
      return;
    }

    const conversationId = await ensureConversation(text);
    if (currentConversation?.title === "新对话") {
      try {
        const title = text.slice(0, 32) || "新对话";
        await updateConversation({ id: conversationId, title });
        await refreshConversations(currentProjectId);
      } catch {
        // 标题更新尽力而为，失败不阻塞聊天流
      }
    }
    setInput("");
    setPendingToolCall(null);
    updateMessages(conversationId, (current) => [...current, localMessage("user", text, "completed")]);
    try {
      await sendChatStream(
        {
          conversation_id: conversationId,
          project_id: currentProjectId ?? undefined,
          provider_profile_id: currentProfileId,
          message: text,
          web_search_enabled: webSearchEnabled,
          mcp_server_ids: mcpServerIds,
        },
        handleStreamEvent,
      );
      await refreshConversations(currentProjectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setActiveRunId(null);
    }
  }

  function handleStreamEvent(event: ChatStreamEvent) {
    if (event.event === "message_start") {
      setActiveRunId(event.data.run_id);
      setCurrentConversationId(event.data.conversation_id);
      updateMessages(event.data.conversation_id, (current) => applyChatStreamEvent(current, event));
      return;
    }

    if (event.event === "delta" || event.event === "message_done") {
      if (event.event === "message_done") setPendingToolCall(null);
      updateMessages(event.data.conversation_id, (current) => applyChatStreamEvent(current, event));
      return;
    }

    if (event.event === "tool_call_pending") {
      setPendingToolCall({
        id: event.data.tool_call_id,
        tool_name: event.data.tool_name,
        schema_name: event.data.schema_name,
        tool_kind: event.data.tool_kind,
        arguments: event.data.arguments,
        requires_approval: event.data.requires_approval,
      });
      updateMessages(event.data.conversation_id, (current) => applyChatStreamEvent(current, event));
      return;
    }

    if (event.event === "conversation_updated") {
      void refreshConversations(event.data.project_id);
      return;
    }

    if (event.event === "error") {
      setError(event.data.message);
      if (event.data.message_id && event.data.conversation_id) {
        updateMessages(event.data.conversation_id, (current) => applyChatStreamEvent(current, event));
      }
    }

    if (event.event === "warning") {
      setError(event.data.message);
    }
  }

  async function resumeToolStream(toolCallId: string) {
    setPendingToolCall(null);
    const controller = new AbortController();
    toolResumeAbortRef.current = controller;
    try {
      await resumeToolCallStream(toolCallId, (event: ResumeToolCallEvent) => {
        if (event.event === "tool_call_result" && event.data.message_id) {
          updateMessages(event.data.conversation_id, (current) =>
            current.map((message) => message.id === event.data.message_id ? { ...message, status: "completed", updated_at: new Date().toISOString() } : message),
          );
          return;
        }
        if (event.event === "tool_call_error" || event.event === "tool_call_rejected") {
          const message = event.data.message;
          if (event.event === "tool_call_error") setError(message);
          if ("message_id" in event.data && event.data.message_id) {
            updateMessages(event.data.conversation_id, (current) =>
              current.map((m) => m.id === event.data.message_id ? { ...m, status: "completed", error: message, updated_at: new Date().toISOString() } : m),
            );
          }
          return;
        }
        if (event.event === "delta" || event.event === "message_done") {
          if (event.event === "message_done") setPendingToolCall(null);
          updateMessages(event.data.conversation_id, (current) => applyChatStreamEvent(current, event as unknown as ChatStreamEvent));
          return;
        }
        if (event.event === "error") setError(event.data.message);
      }, controller.signal);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function approvePendingTool() {
    if (!pendingToolCall) return;
    const toolCallId = pendingToolCall.id;
    setError(null);
    try {
      await approveToolCall(toolCallId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    await resumeToolStream(toolCallId);
  }

  async function rejectPendingTool() {
    if (!pendingToolCall) return;
    const toolCallId = pendingToolCall.id;
    setError(null);
    try {
      await rejectToolCall(toolCallId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    await resumeToolStream(toolCallId);
  }

  async function stopStreaming() {
    abortChatStream();
    toolResumeAbortRef.current?.abort();
    if (!activeRunId) return;
    await cancelChat(activeRunId);
  }

  function saveBlob(blob: Blob, filename: string) {
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
  }

  async function downloadWorkflowArtifactFile(workflowId: string, name: string) {
    try {
      const blob = await downloadWorkflowArtifact(workflowId, name);
      saveBlob(blob, name);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function downloadWorkflowZipFile(workflowId: string) {
    try {
      const blob = await downloadWorkflowZip(workflowId);
      saveBlob(blob, "workflow-artifacts.zip");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function saveProfile(values: ProviderProfileValues) {
    try {
      const existing = currentProfileId ? profiles.find((profile) => profile.id === currentProfileId) : null;
      const payload = { ...values, api_key: values.api_key || undefined };
      const profile = existing ? await updateProfile(existing.id, payload) : await createProfile(payload);
      setCurrentProfileId(profile.id);
      setConfigOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    }
  }

  async function saveWebSearchConfig(values: WebSearchValues): Promise<WebSearchConfig> {
    try {
      const apiKeyValue = values.api_key.trim();
      const updated = await updateWebSearch({
        api_key: apiKeyValue || undefined,
        max_results: Number(values.max_results),
        search_depth: values.search_depth,
      });
      setError(null);
      return updated;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    }
  }

  function openConfigPanel() {
    setConfigOpen(true);
    setUserPanelOpen(false);
    setModelMenuOpen(false);
  }

  function toggleUserPanel() {
    setConfigOpen(false);
    setModelMenuOpen(false);
    setUserPanelOpen((current) => !current);
  }

  function updateChatAvatar(kind: "user" | "assistant", value: string) {
    if (kind === "user") {
      setUserChatAvatar(value);
      window.localStorage.setItem("workbench-user-avatar", value);
      return;
    }
    setAssistantChatAvatar(value);
    window.localStorage.setItem("workbench-assistant-avatar", value);
  }

  async function submitAuth(mode: AuthPanelMode, values: { username: string; password: string; confirmPassword: string }) {
    await submitAuthRequest(mode, { username: values.username, password: values.password });
  }

  async function changeCurrentPassword(values: PasswordChangeValues) {
    passwordChangeForm.clearErrors("root");
    try {
      await changePassword({
        current_password: values.currentPassword,
        new_password: values.newPassword,
      });
      await logoutUser();
      setError("密码已修改，请重新登录。");
    } catch (caught) {
      passwordChangeForm.setError("root", { message: caught instanceof Error ? caught.message : String(caught) });
    }
  }

  async function logoutUser() {
    toolResumeAbortRef.current?.abort();
    await logoutAuthSession();
    setUserPanelOpen(false);
    clearWorkbenchData();
    clearConfiguration();
    setWebSearchEnabled(false);
    setCurrentProjectId(null);
    setCurrentConversationId(null);
    setCurrentProfileId(null);
    setPendingToolCall(null);
    passwordChangeForm.reset();
  }

  const workspaceMode = messages.length > 0 ? "work" : "welcome";
  const themeStyle = useMemo(() => ({
    ...theme.effectivePalette,
    "--theme-border": theme.activeSkin?.tokens["--theme-border"],
    "--theme-art": theme.art,
    "--theme-art-blur": `${theme.prefs.wallpaper_blur ?? 0}px`,
    "--theme-art-wash": String(theme.prefs.wallpaper_opacity ?? 0),
    "--theme-autodim": theme.prefs.wallpaper_autodim ? "1" : "0",
    "--theme-focus-x": theme.presentation.focusX,
    "--theme-focus-y": theme.presentation.focusY,
  } as CSSProperties), [theme.effectivePalette, theme.activeSkin, theme.art, theme.prefs.wallpaper_blur, theme.prefs.wallpaper_opacity, theme.prefs.wallpaper_autodim, theme.presentation.focusX, theme.presentation.focusY]);
  const themeShellAttrs = useMemo(() => {
    if (theme.activeSkin || theme.prefs.wallpaper_kind !== "image") return {};
    return {
      "data-theme-safe": theme.presentation.safeArea,
      "data-theme-aspect": theme.presentation.wide ? "wide" : "normal",
      "data-theme-task": theme.presentation.taskMode,
    };
  }, [theme.activeSkin, theme.prefs.wallpaper_kind, theme.presentation]);

  async function uploadAppTheme(file: File, appearance: ThemeAppearance) { try { await theme.upload(file, appearance); await theme.setPrefs({ wallpaper_kind: "image" }); toast.success("壁纸已应用"); } catch (e: any) { setError(e?.message ?? String(e)); } }

  if (authMode !== "ready") {
    return <AuthPanel mode={authMode} backendReady={authBackendReady} error={error} onModeChange={switchAuthMode} onSubmit={submitAuth} />;
  }

  const toolReasoning = pendingToolCall ? (
    <ToolReasoning
      name={pendingToolCall.tool_name}
      status="pending"
      args={pendingToolCall.arguments as Record<string, string | number | boolean | null | undefined>}
      requiresApproval={pendingToolCall.requires_approval}
      onApprove={approvePendingTool}
      onReject={rejectPendingTool}
    />
  ) : null;

  return (
    <Suspense fallback={null}>
    <ErrorBoundary>
    <PanelGroup className="workbench-shell" data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"} data-theme={theme.shellSource} data-theme-mode={workspaceMode} {...themeShellAttrs} style={themeStyle} direction="horizontal" autoSaveId="standard-workbench-layout">
      <Panel ref={sidebarPanelRef} id="workbench-sidebar" order={1} defaultSize={22} minSize={18} maxSize={36} collapsible collapsedSize={6} onCollapse={() => setSidebarCollapsed(true)} onExpand={() => setSidebarCollapsed(false)}>
        <WorkbenchSidebar
          collapsed={sidebarCollapsed}
          projects={projects}
          currentProjectId={currentProjectId}
          currentConversationId={currentConversationId}
          projectPreviewConversations={projectPreviewConversations}
          historyConversations={sidebarHistoryConversations}
          searchQuery={searchQuery}
          searchKind={searchKind}
          searchResults={searchResults}
          projectsOpen={projectsOpen}
          projectConversationsOpen={projectConversationsOpen}
          conversationsOpen={conversationsOpen}
          authUser={authUser}
          userPanelOpen={userPanelOpen}
          onToggleSidebar={toggleSidebar}
          onStartNewChat={startNewChat}
          onFocusSearch={() => setSearchQuery((current) => current || " ")}
          onOpenConfig={openConfigPanel}
          onOpenKnowledge={() => { void knowledge.toggle(); }}
          onOpenMcp={() => { void mcp.toggle(); }}
          onOpenWorkflows={() => { void workflows.toggle(); }}
          onSearchQueryChange={setSearchQuery}
          onSearchKindChange={setSearchKind}
          onToggleProjects={() => setProjectsOpen((current) => !current)}
          onChooseWorkspace={chooseWorkspaceDirectory}
          onSwitchProject={switchProject}
          onToggleProjectConversations={() => setProjectConversationsOpen((current) => !current)}
          onRemoveProject={removeProject}
          onOpenConversation={openConversation}
          onRemoveConversation={removeConversation}
          onToggleConversations={() => setConversationsOpen((current) => !current)}
          onToggleUserPanel={toggleUserPanel}
        />
      </Panel>
      <PanelResizeHandle className="sidebar-resize-handle" hitAreaMargins={{ coarse: 16, fine: 8 }} />
      <Panel id="workbench-chat" order={2} minSize={40}>
        <ChatWorkspace
          messages={messages}
          currentProjectTitle={currentProject?.title ?? null}
          currentConversationTitle={currentConversation?.title ?? null}
          input={input}
          onInputChange={setInput}
          onSend={() => sendMessage()}
          isStreaming={isStreaming}
          onStopStreaming={stopStreaming}
          isConfigured={Boolean(currentProfile?.model && currentProfile?.has_key)}
          currentProfileModel={currentProfile?.model ?? null}
          onOpenConfig={openConfigPanel}
          webSearchConfig={webSearchConfig}
          webSearchEnabled={webSearchEnabled}
          onToggleWebSearch={() => {
            if (webSearchConfig?.has_key === false) {
              setError("请先在模型配置中填写 Tavily API key。");
              return;
            }
            setWebSearchEnabled((current) => !current);
          }}
          modelMenuOpen={modelMenuOpen}
          onModelMenuOpenChange={(open) => {
            if (open) void openModelMenu();
            else setModelMenuOpen(false);
          }}
          providerModels={providerModels}
          isLoadingModels={isLoadingModels}
          onChooseModel={chooseModel}
          onChooseWorkspace={chooseWorkspaceDirectory}
          userAvatar={userChatAvatar}
          assistantAvatar={assistantChatAvatar}
          workflowPanel={toolReasoning}
        />

        <ConfigDialog
          open={configOpen}
          onOpenChange={setConfigOpen}
          presets={providerPresets}
          profile={configProfile}
          hasKey={currentProfile?.has_key ?? false}
          onSaveProfile={saveProfile}
          webSearchConfig={webSearchConfig}
          onSaveWebSearch={saveWebSearchConfig}
        />

        <Dialog.Root open={userPanelOpen} onOpenChange={setUserPanelOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="user-modal-backdrop" />
            <Dialog.Content className="user-modal" aria-describedby={undefined}>
              <div className="user-panel-header">
                <Dialog.Title asChild><strong>账号</strong></Dialog.Title>
                <Dialog.Close asChild><button type="button" aria-label="关闭账号面板">
                  <X size={17} />
                </button></Dialog.Close>
              </div>
              <div className="user-panel-scroll">
                <ThemePanel
                  busy={theme.isBusy}
                  prefs={theme.prefs}
                  activeSkin={theme.activeSkin}
                  onUpload={uploadAppTheme}
                  onSetPrefs={async (patch) => { try { await theme.setPrefs(patch); } catch (e: any) { setError(e?.message ?? String(e)); } }}
                />
                <div className="user-section">
                  <div className="user-section-title">账号信息</div>
                  <div className="user-detail">
                    <span>当前账号</span>
                    <strong>{authUser?.username ?? "未登录"}</strong>
                  </div>
                  <div className="user-detail">
                    <span>数据范围</span>
                    <strong>当前账号独立数据</strong>
                  </div>
                </div>
                <div className="user-section">
                  <div className="user-section-title">头像设置</div>
                  <div className="avatar-settings">
                    <label>
                      用户头像
                      <input value={userChatAvatar} onChange={(event) => updateChatAvatar("user", event.target.value)} placeholder="文字、emoji 或图片 URL" />
                    </label>
                    <label>
                      LLM 头像
                      <input value={assistantChatAvatar} onChange={(event) => updateChatAvatar("assistant", event.target.value)} placeholder="文字、emoji 或图片 URL" />
                    </label>
                  </div>
                </div>
                <div className="user-section">
                  <div className="user-section-title">修改密码</div>
                  <form className="user-login-form" onSubmit={passwordChangeForm.handleSubmit(changeCurrentPassword)}>
                    <label>
                      当前密码
                      <input
                        {...passwordChangeForm.register("currentPassword")}
                        type="password"
                        autoComplete="current-password"
                      />
                      {passwordChangeForm.formState.errors.currentPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.currentPassword.message}</small>}
                    </label>
                    <label>
                      新密码
                      <input
                        {...passwordChangeForm.register("newPassword")}
                        type="password"
                        autoComplete="new-password"
                      />
                      {passwordChangeForm.formState.errors.newPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.newPassword.message}</small>}
                    </label>
                    <label>
                      确认新密码
                      <input
                        {...passwordChangeForm.register("confirmPassword")}
                        type="password"
                        autoComplete="new-password"
                      />
                      {passwordChangeForm.formState.errors.confirmPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.confirmPassword.message}</small>}
                    </label>
                    {passwordChangeForm.formState.errors.root && <div className="auth-field-error">{passwordChangeForm.formState.errors.root.message}</div>}
                    <div className="form-actions">
                      <button type="submit" disabled={passwordChangeForm.formState.isSubmitting}>{passwordChangeForm.formState.isSubmitting ? "修改中" : "修改密码"}</button>
                    </div>
                  </form>
                </div>
              </div>
              <div className="user-panel-actions">
                <button type="button" className="user-secondary-action" onClick={logoutUser}>
                  退出登录
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </Panel>
    </PanelGroup>

    <KnowledgePanel
      open={knowledge.open}
      onClose={() => knowledge.setOpen(false)}
      vault={knowledge.vault}
      sources={knowledge.sources}
      drafts={knowledge.drafts}
      pages={knowledge.pages}
      loading={knowledge.loading}
      error={knowledge.error}
      disabled={!currentProjectId}
      fileInputRef={knowledge.fileInputRef}
      onImport={(file) => void knowledge.importFile(file)}
      onReview={(draftId, approved) => void knowledge.review(draftId, approved)}
      onOpenDir={(path) => void window.standardWorkbench?.openPath(path)}
    />
    <McpPanel
      open={mcp.open}
      onClose={() => mcp.setOpen(false)}
      servers={mcp.servers}
      tools={mcp.tools}
      loading={mcp.loading}
      error={mcp.error}
      onAdd={mcp.add}
      onPatch={mcp.patch}
      onRemove={mcp.remove}
      onRefreshTools={mcp.refreshTools}
    />
    <WorkflowsPanel
      open={workflows.open}
      onClose={() => workflows.setOpen(false)}
      workflows={workflows.workflows}
      skills={workflows.skills}
      artifacts={workflows.artifacts}
      loading={workflows.loading}
      error={workflows.error}
      onCreate={workflows.create}
      onRun={workflows.run}
      onConfirm={workflows.confirm}
      onCancel={workflows.cancel}
      onOpenArtifact={downloadWorkflowArtifactFile}
      onDownloadZip={downloadWorkflowZipFile}
    />
    </ErrorBoundary>
    </Suspense>
  );
}
