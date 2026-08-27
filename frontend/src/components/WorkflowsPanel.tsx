"use client";

import { CheckCircle2, Download, Play, Square, Workflow as WorkflowIcon, X } from "lucide-react";
import { FormEvent, useState } from "react";

import type { SkillMetadata, Workflow, WorkflowArtifact } from "@/lib/types";

type WorkflowsPanelProps = {
  open: boolean;
  onClose: () => void;
  workflows: Workflow[];
  skills: SkillMetadata[];
  artifacts: Record<string, WorkflowArtifact[]>;
  loading: boolean;
  error: string | null;
  onCreate: (input: { skill_name: string; input_text?: string }) => Promise<boolean>;
  onRun: (workflowId: string, inputText?: string) => void;
  onConfirm: (workflowId: string, text?: string) => void;
  onCancel: (workflowId: string) => void;
  onOpenArtifact: (workflowId: string, name: string) => void;
  onDownloadZip: (workflowId: string) => void;
};

function statusLabel(status: string): string {
  switch (status) {
    case "created": return "已创建";
    case "running": return "运行中";
    case "waiting_confirmation": return "待确认";
    case "completed": return "已完成";
    case "failed": return "失败";
    case "cancelled": return "已取消";
    default: return status;
  }
}

export function WorkflowsPanel({
  open,
  onClose,
  workflows,
  skills,
  artifacts,
  loading,
  error,
  onCreate,
  onRun,
  onConfirm,
  onCancel,
  onOpenArtifact,
  onDownloadZip,
}: WorkflowsPanelProps) {
  const [skillName, setSkillName] = useState("");
  const [inputText, setInputText] = useState("");
  const [confirmText, setConfirmText] = useState("");
  if (!open) return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!skillName) return;
    const ok = await onCreate({ skill_name: skillName, input_text: inputText });
    if (ok) setInputText("");
  };

  return (
    <div className="config-modal-backdrop" onClick={onClose}>
      <section className="config-modal" role="dialog" aria-modal="true" aria-labelledby="workflow-modal-title" onClick={(event) => event.stopPropagation()}>
        <div className="config-modal-header">
          <div className="config-modal-title">
            <WorkflowIcon size={17} />
            <strong id="workflow-modal-title">工作流</strong>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭工作流面板"><X size={17} /></button>
        </div>

        <div className="config-modal-scroll">
          {error && <div className="config-message error">{error}</div>}

          <form className="config-form" onSubmit={submit}>
            <select value={skillName} onChange={(e) => setSkillName(e.target.value)}>
              <option value="">选择 Skill…</option>
              {skills.map((skill) => (
                <option key={skill.skill_name} value={skill.skill_name}>{skill.display_name}</option>
              ))}
            </select>
            <textarea value={inputText} onChange={(e) => setInputText(e.target.value)} placeholder="输入内容（可选）" rows={2} />
            <div className="config-actions">
              <button type="submit" disabled={!skillName}><Play size={15} />创建并运行</button>
            </div>
          </form>

          {loading ? (
            <div className="config-message">加载中…</div>
          ) : workflows.length === 0 ? (
            <div className="config-message">尚未创建工作流。</div>
          ) : (
            workflows.map((workflow) => (
              <div className="config-section" key={workflow.id}>
                <div className="config-section-title">
                  {skills.find((s) => s.skill_name === workflow.skill_name)?.display_name ?? workflow.skill_name}
                  <span className={`config-tag ${workflow.status === "completed" ? "ok" : workflow.status === "failed" ? "bad" : ""}`}>
                    {statusLabel(workflow.status)}
                  </span>
                </div>
                {workflow.input_summary && <div className="config-message">{workflow.input_summary}</div>}
                {workflow.error && <div className="config-message error">{workflow.error}</div>}
                <div className="config-actions">
                  {workflow.status === "created" && (
                    <button type="button" onClick={() => onRun(workflow.id)}><Play size={14} />运行</button>
                  )}
                  {workflow.status === "waiting_confirmation" && (
                    <>
                      <input
                        value={confirmText}
                        onChange={(e) => setConfirmText(e.target.value)}
                        placeholder="确认说明（可选）"
                        className="config-inline-input"
                      />
                      <button type="button" onClick={() => onConfirm(workflow.id, confirmText)}><CheckCircle2 size={14} />确认</button>
                    </>
                  )}
                  {workflow.status === "running" && (
                    <button type="button" onClick={() => onCancel(workflow.id)}><Square size={14} />取消</button>
                  )}
                  {["completed", "failed", "cancelled"].includes(workflow.status) && (
                    <button type="button" onClick={() => onRun(workflow.id)}><Play size={14} />重新运行</button>
                  )}
                  {workflow.status === "completed" && (artifacts[workflow.id]?.length ?? 0) > 0 && (
                    <>
                      {artifacts[workflow.id].map((artifact) => (
                        <button type="button" key={artifact.name} onClick={() => onOpenArtifact(workflow.id, artifact.name)}>
                          <Download size={14} />{artifact.name}
                        </button>
                      ))}
                      <button type="button" onClick={() => onDownloadZip(workflow.id)}><Download size={14} />ZIP</button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
