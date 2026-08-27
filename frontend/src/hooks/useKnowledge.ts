"use client";

import { useCallback, useRef, useState } from "react";

import {
  compileKnowledgeSource,
  confirmKnowledgeDraft,
  getKnowledgeVault,
  listKnowledgeDrafts,
  listKnowledgePages,
  listKnowledgeSources,
  uploadKnowledgeSource,
} from "@/lib/api";
import type { KnowledgeDraft, KnowledgePage, KnowledgeSource, KnowledgeVault } from "@/lib/types";

export type KnowledgeEnv = {
  enabled: boolean;
  projectId: string | null;
  profileId: string | null;
};

/** 本地 LLM Wiki 知识库：导入资料、编译草案、确认写入、浏览页面。 */
export function useKnowledge(env: KnowledgeEnv) {
  const [open, setOpen] = useState(false);
  const [vault, setVault] = useState<KnowledgeVault | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [drafts, setDrafts] = useState<KnowledgeDraft[]>([]);
  const [pages, setPages] = useState<KnowledgePage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const { projectId } = env;
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [v, s, d, p] = await Promise.all([
        getKnowledgeVault(projectId),
        listKnowledgeSources(projectId),
        listKnowledgeDrafts(projectId),
        listKnowledgePages(projectId),
      ]);
      setVault(v);
      setSources(s);
      setDrafts(d);
      setPages(p);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [env.projectId]);

  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && env.enabled) await refresh();
  }, [open, env.enabled, refresh]);

  const importFile = useCallback(
    async (file: File) => {
      const { projectId, profileId } = env;
      if (!projectId) return;
      setError(null);
      try {
        const source = await uploadKnowledgeSource(projectId, file);
        await compileKnowledgeSource(projectId, source.id, profileId ?? undefined);
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [env.projectId, env.profileId, refresh],
  );

  const review = useCallback(
    async (draftId: string, approved: boolean) => {
      const { projectId } = env;
      if (!projectId) return;
      setError(null);
      try {
        await confirmKnowledgeDraft(projectId, draftId, approved);
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [env.projectId, refresh],
  );

  return {
    open,
    setOpen,
    vault,
    sources,
    drafts,
    pages,
    loading,
    error,
    refresh,
    toggle,
    importFile,
    review,
    fileInputRef,
  };
}
