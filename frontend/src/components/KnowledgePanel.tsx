"use client";

import { BookOpen, FolderOpen, Upload, X } from "lucide-react";
import { type RefObject } from "react";

import type { KnowledgeDraft, KnowledgePage, KnowledgeSource, KnowledgeVault } from "@/lib/types";

type KnowledgePanelProps = {
  open: boolean;
  onClose: () => void;
  vault: KnowledgeVault | null;
  sources: KnowledgeSource[];
  drafts: KnowledgeDraft[];
  pages: KnowledgePage[];
  loading: boolean;
  error: string | null;
  disabled: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onImport: (file: File) => void;
  onReview: (draftId: string, approved: boolean) => void;
  onOpenDir: (path: string) => void;
};

export function KnowledgePanel({
  open,
  onClose,
  vault,
  sources,
  drafts,
  pages,
  loading,
  error,
  disabled,
  fileInputRef,
  onImport,
  onReview,
  onOpenDir,
}: KnowledgePanelProps) {
  if (!open) return null;
  const visiblePages = pages.filter((page) => page.path !== "log.md" && page.path !== "index.md");

  return (
    <div className="config-modal-backdrop" onClick={onClose}>
      <section className="config-modal" role="dialog" aria-modal="true" aria-labelledby="knowledge-modal-title" onClick={(event) => event.stopPropagation()}>
        <div className="config-modal-header">
          <div className="config-modal-title">
            <BookOpen size={17} />
            <strong id="knowledge-modal-title">知识库</strong>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭知识库"><X size={17} /></button>
        </div>

        <div className="config-modal-scroll">
          {error && <div className="config-message error">{error}</div>}
          <div className="config-message">
            {vault ? `${vault.source_count} 个来源 · ${vault.page_count} 个 Wiki 页面` : "加载中"}
          </div>

          <div className="config-actions">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,.md"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) onImport(file);
              }}
            />
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={disabled}>
              <Upload size={15} />
              导入资料
            </button>
            <button type="button" onClick={() => vault && onOpenDir(vault.path)} disabled={!vault}>
              <FolderOpen size={15} />
              打开目录
            </button>
          </div>

          {drafts.filter((draft) => draft.status === "waiting_confirmation").length > 0 && (
            <div className="config-section">
              <div className="config-section-title">待确认草案</div>
              {drafts.filter((draft) => draft.status === "waiting_confirmation").map((draft) => (
                <div className="config-row" key={draft.id}>
                  <div className="config-message">{draft.patches.map((patch) => <span key={patch.path} className="config-tag">{patch.path}</span>)}</div>
                  <div className="config-actions">
                    <button type="button" onClick={() => onReview(draft.id, false)}>拒绝</button>
                    <button type="button" onClick={() => onReview(draft.id, true)}>确认写入</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="config-section">
            <div className="config-section-title">导入来源</div>
            {loading ? (
              <div className="config-message">加载中…</div>
            ) : sources.length === 0 ? (
              <div className="config-message">尚未导入资料。</div>
            ) : (
              sources.slice(0, 12).map((source) => (
                <div className="config-message" key={source.id}>{source.filename} · {source.status}</div>
              ))
            )}
          </div>

          <div className="config-section">
            <div className="config-section-title">Wiki 页面</div>
            {visiblePages.length === 0 ? (
              <div className="config-message">确认草案后将显示 Wiki 页面。</div>
            ) : (
              visiblePages.slice(0, 20).map((page) => (
                <div className="config-message" key={page.path}>{page.title}</div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
