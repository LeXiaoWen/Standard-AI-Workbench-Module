"use client";

import { Cable, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { FormEvent, useState } from "react";

import type { McpServer, McpServerCreate, McpServerUpdate, McpTool } from "@/lib/types";

type McpPanelProps = {
  open: boolean;
  onClose: () => void;
  servers: McpServer[];
  tools: Record<string, McpTool[]>;
  loading: boolean;
  error: string | null;
  onAdd: (input: McpServerCreate) => Promise<boolean>;
  onPatch: (serverId: string, input: McpServerUpdate) => void;
  onRemove: (serverId: string) => void;
  onRefreshTools: (serverId: string) => void;
};

const emptyForm: McpServerCreate = { name: "", command: "", args: [], enabled: false };

export function McpPanel({
  open,
  onClose,
  servers,
  tools,
  loading,
  error,
  onAdd,
  onPatch,
  onRemove,
  onRefreshTools,
}: McpPanelProps) {
  const [form, setForm] = useState<McpServerCreate>(emptyForm);
  if (!open) return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const ok = await onAdd(form);
    if (ok) setForm(emptyForm);
  };

  return (
    <div className="config-modal-backdrop" onClick={onClose}>
      <section className="config-modal" role="dialog" aria-modal="true" aria-labelledby="mcp-modal-title" onClick={(event) => event.stopPropagation()}>
        <div className="config-modal-header">
          <div className="config-modal-title">
            <Cable size={17} />
            <strong id="mcp-modal-title">MCP 服务</strong>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭 MCP 面板"><X size={17} /></button>
        </div>

        <div className="config-modal-scroll">
          {error && <div className="config-message error">{error}</div>}

          <form className="config-form" onSubmit={submit}>
            <div className="config-form-row">
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="名称（如 filesystem）" />
              <input value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="stdio 命令（如 npx）" />
            </div>
            <input value={(form.args ?? []).join(" ")} onChange={(e) => setForm({ ...form, args: e.target.value.trim() ? e.target.value.trim().split(/\s+/) : [] })} placeholder="参数（空格分隔，如 -y @modelcontextprotocol/server-filesystem /tmp）" />
            <div className="config-actions">
              <button type="submit" disabled={!form.name.trim() || !form.command.trim()}><Plus size={15} />添加服务</button>
            </div>
          </form>

          {loading ? (
            <div className="config-message">加载中…</div>
          ) : servers.length === 0 ? (
            <div className="config-message">尚未配置 MCP 服务。</div>
          ) : (
            servers.map((server) => (
              <div className="config-section" key={server.id}>
                <div className="config-section-title">
                  {server.name}
                  <span className={`config-tag ${server.enabled ? "ok" : ""}`}>{server.enabled ? "启用" : "禁用"}</span>
                </div>
                <div className="config-message mono">{server.command} {server.args.join(" ")}</div>
                <div className="config-actions">
                  <button type="button" onClick={() => onPatch(server.id, { enabled: !server.enabled })}>
                    {server.enabled ? "停用" : "启用"}
                  </button>
                  <button type="button" onClick={() => onRefreshTools(server.id)}><RefreshCw size={14} />刷新工具</button>
                  <button type="button" className="danger" onClick={() => onRemove(server.id)}><Trash2 size={14} />删除</button>
                </div>
                {tools[server.id] && tools[server.id].length > 0 && (
                  <div className="config-message">
                    {tools[server.id].map((tool) => <span key={tool.name} className="config-tag">{tool.name}</span>)}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
