from __future__ import annotations

from ...schemas import Workflow
from ...services.workbench_store import workbench_store
from ..base import SkillAdapter


class ExampleEchoAdapter(SkillAdapter):
    skill_name = "example_echo_workflow"
    display_name = "示例 Echo Workflow"
    description = "用于验证 SkillAdapter、workflow 状态流转和 artifact 下载的最小示例。"
    accepted_inputs = ["text"]
    stages = ["created", "draft", "confirmed", "completed"]

    def load_instructions(self) -> str:
        return "Echo 输入内容，等待用户确认后生成 Markdown 成果。"

    def run_stage(self, user_id: str, workflow: Workflow, input_text: str = "") -> tuple[Workflow, str]:
        if workflow.status == "cancelled":
            raise ValueError("工作流已取消。")
        summary = input_text.strip() or workflow.input_summary or "示例输入"
        updated = workbench_store.update_workflow(
            user_id,
            workflow.id,
            status="waiting_confirmation",
            stage="draft",
            input_summary=summary,
            error=None,
        )
        message = f"示例 workflow 已生成草稿：\n\n{summary}\n\n请确认或补充后生成成果。"
        workbench_store.add_message(user_id, updated.conversation_id, "assistant", message)
        return updated, message

    def confirm_stage(self, user_id: str, workflow: Workflow, text: str = "") -> tuple[Workflow, str]:
        if workflow.status == "cancelled":
            raise ValueError("工作流已取消。")
        confirmation = text.strip() or "确认"
        summary = f"{workflow.input_summary}\n\n确认信息：{confirmation}".strip()
        updated = workbench_store.update_workflow(
            user_id,
            workflow.id,
            status="completed",
            stage="completed",
            input_summary=summary,
            error=None,
        )
        workbench_store.save_workflow_artifacts(user_id, updated.id, self.build_artifacts(updated))
        message = "示例 workflow 已完成，已生成 Markdown 成果。"
        workbench_store.add_message(user_id, updated.conversation_id, "assistant", message)
        return updated, message

    def build_artifacts(self, workflow: Workflow) -> dict[str, tuple[str, str, str]]:
        content = f"""# 示例 Echo Workflow 成果

## Skill

{self.display_name}

## 输入与确认

{workflow.input_summary or "无输入"}

## 状态

- Workflow ID: `{workflow.id}`
- Stage: `{workflow.stage}`
- Status: `{workflow.status}`
"""
        return {"example_echo_result.md": (content, "markdown", "text/markdown; charset=utf-8")}
