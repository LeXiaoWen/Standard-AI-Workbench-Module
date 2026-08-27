"use client";

import { Check, ChevronDown, Circle, Loader2, Wrench, X } from "lucide-react";
import { useEffect, useRef } from "react";

type ToolReasoningProps = {
  name: string;
  status: "pending" | "executing" | "done" | "error" | "rejected";
  args?: Record<string, string | number | boolean | null | undefined>;
  requiresApproval?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
};

function formatValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "未填写";
  return String(value);
}

export function ToolReasoning({ name, status, args, requiresApproval, onApprove, onReject }: ToolReasoningProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const entries = Object.entries(args ?? {});
  const isRunning = status === "executing";
  const isPending = status === "pending";

  useEffect(() => {
    if (!detailsRef.current) return;
    detailsRef.current.open = isRunning || isPending || status === "error";
  }, [isRunning, isPending, status]);

  return (
    <details ref={detailsRef} className={`tool-card ${status}`} open={isRunning || isPending}>
      <summary>
        <span className="tool-status">
          {isRunning ? <Loader2 className="spin" size={14} /> : status === "done" ? <Check size={14} /> : status === "error" ? <X size={14} /> : <Circle size={14} />}
        </span>
        <Wrench size={14} />
        <span>{name}</span>
        <ChevronDown className="tool-chevron" size={14} />
      </summary>
      {entries.length > 0 ? (
        <div className="tool-args">
          {entries.map(([key, value]) => (
            <div key={key}>
              <span>{key}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {isPending && requiresApproval && (
        <div className="tool-actions">
          <button type="button" className="tool-approve" onClick={onApprove}><Check size={14} />允许</button>
          <button type="button" className="tool-reject" onClick={onReject}><X size={14} />拒绝</button>
        </div>
      )}
    </details>
  );
}
