"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  refreshMcpTools,
  updateMcpServer,
} from "@/lib/api";
import type { McpServer, McpServerCreate, McpServerUpdate, McpTool } from "@/lib/types";

export function useMcpServers(enabled: boolean) {
  const [open, setOpen] = useState(false);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<Record<string, McpTool[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setServers(await listMcpServers());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void refresh();
  }, [enabled, refresh]);

  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && enabled) await refresh();
  }, [open, enabled, refresh]);

  const add = useCallback(async (input: McpServerCreate) => {
    setError(null);
    try {
      await createMcpServer(input);
      await refresh();
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return false;
    }
  }, [refresh]);

  const patch = useCallback(async (serverId: string, input: McpServerUpdate) => {
    setError(null);
    try {
      await updateMcpServer(serverId, input);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [refresh]);

  const remove = useCallback(
    async (serverId: string) => {
      setError(null);
      try {
        await deleteMcpServer(serverId);
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refresh],
  );

  const refreshTools = useCallback(async (serverId: string) => {
    setError(null);
    try {
      const next = await refreshMcpTools(serverId);
      setTools((current) => ({ ...current, [serverId]: next }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  return {
    open,
    setOpen,
    servers,
    tools,
    loading,
    error,
    refresh,
    toggle,
    add,
    patch,
    remove,
    refreshTools,
  };
}
