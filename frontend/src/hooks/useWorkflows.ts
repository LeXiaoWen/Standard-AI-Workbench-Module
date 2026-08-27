"use client";

import { useCallback, useEffect, useState } from "react";

import {
  cancelWorkflow,
  confirmWorkflow,
  createWorkflow,
  getWorkflow,
  listSkills,
  listWorkflowArtifacts,
  listWorkflows,
  runWorkflow,
} from "@/lib/api";
import type { SkillMetadata, Workflow, WorkflowArtifact } from "@/lib/types";

export function useWorkflows(env: { enabled: boolean; conversationId: string | null }) {
  const [open, setOpen] = useState(false);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [artifacts, setArtifacts] = useState<Record<string, WorkflowArtifact[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ws, sk] = await Promise.all([listWorkflows(env.conversationId ?? undefined), listSkills()]);
      setWorkflows(ws);
      setSkills(sk);
      const next: Record<string, WorkflowArtifact[]> = {};
      await Promise.all(ws.filter((w) => w.status === "completed").map(async (w) => {
        next[w.id] = await listWorkflowArtifacts(w.id);
      }));
      setArtifacts(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [env.conversationId]);

  useEffect(() => {
    if (env.enabled) void refresh();
  }, [env.enabled, refresh]);

  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && env.enabled) await refresh();
  }, [open, env.enabled, refresh]);

  const create = useCallback(
    async (input: { skill_name: string; input_text?: string }) => {
      setError(null);
      try {
        await createWorkflow({
          skill_name: input.skill_name,
          conversation_id: env.conversationId ?? undefined,
          input_text: input.input_text ?? "",
        });
        await refresh();
        return true;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        return false;
      }
    },
    [env.conversationId, refresh],
  );

  const run = useCallback(async (workflowId: string, inputText = "") => {
    setError(null);
    try {
      await runWorkflow(workflowId, inputText);
      const updated = await getWorkflow(workflowId);
      setWorkflows((current) => current.map((w) => (w.id === workflowId ? updated : w)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  const confirm = useCallback(async (workflowId: string, text = "") => {
    setError(null);
    try {
      const response = await confirmWorkflow(workflowId, text);
      setWorkflows((current) => current.map((w) => (w.id === workflowId ? response.workflow : w)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  const cancel = useCallback(async (workflowId: string) => {
    setError(null);
    try {
      const response = await cancelWorkflow(workflowId);
      setWorkflows((current) => current.map((w) => (w.id === workflowId ? response.workflow : w)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  return {
    open,
    setOpen,
    workflows,
    skills,
    artifacts,
    loading,
    error,
    refresh,
    toggle,
    create,
    run,
    confirm,
    cancel,
  };
}
