from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..schemas import (
    Workflow,
    WorkflowActionResponse,
    WorkflowConfirmRequest,
    WorkflowCreateRequest,
    WorkflowRunRequest,
)
from ..services.artifacts import make_zip
from ..services.workbench_store import workbench_store
from ..skills.registry import get_adapter
from .dependencies import current_user

router = APIRouter()


@router.post("/api/v1/workflows", response_model=Workflow)
def create_workflow(request: Request, payload: WorkflowCreateRequest):
    try:
        user = current_user(request)
        adapter = get_adapter(payload.skill_name)
        workflow = workbench_store.create_workflow(
            user.id,
            skill_name=adapter.skill_name,
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
            input_summary=payload.input_text.strip(),
        )
        if payload.input_text.strip():
            workbench_store.add_message(user.id, workflow.conversation_id, "user", payload.input_text.strip())
        return workflow
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/workflows", response_model=list[Workflow])
def list_workflows(request: Request, conversation_id: str | None = Query(default=None)):
    return workbench_store.list_workflows(current_user(request).id, conversation_id)


@router.get("/api/v1/workflows/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: str, request: Request):
    try:
        return workbench_store.get_workflow(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@router.post("/api/v1/workflows/{workflow_id}/run", response_model=WorkflowActionResponse)
def run_workflow(workflow_id: str, request: Request, payload: WorkflowRunRequest):
    try:
        user = current_user(request)
        workflow = workbench_store.get_workflow(user.id, workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        running = workbench_store.update_workflow(user.id, workflow_id, status="running", error=None)
        workflow, message = adapter.run_stage(user.id, running, payload.input_text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(current_user(request).id, workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@router.post("/api/v1/workflows/{workflow_id}/confirm", response_model=WorkflowActionResponse)
def confirm_workflow(workflow_id: str, request: Request, payload: WorkflowConfirmRequest):
    try:
        user = current_user(request)
        workflow = workbench_store.get_workflow(user.id, workflow_id)
        adapter = get_adapter(workflow.skill_name)
        if workflow.status in {"completed", "cancelled"}:
            raise ValueError("当前工作流已结束。")
        workflow, message = adapter.confirm_stage(user.id, workflow, payload.text)
        return WorkflowActionResponse(workflow=workflow, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        failed = workbench_store.update_workflow(current_user(request).id, workflow_id, status="failed", error=str(exc))
        return WorkflowActionResponse(workflow=failed, message=str(exc))


@router.post("/api/v1/workflows/{workflow_id}/cancel", response_model=WorkflowActionResponse)
def cancel_workflow(workflow_id: str, request: Request):
    try:
        workflow = workbench_store.update_workflow(current_user(request).id, workflow_id, status="cancelled", stage="cancelled", error=None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc
    return WorkflowActionResponse(workflow=workflow, message="工作流已取消。")


@router.get("/api/v1/workflows/{workflow_id}/artifacts")
def list_workflow_artifacts(workflow_id: str, request: Request):
    try:
        return workbench_store.list_workflow_artifacts(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc


@router.get("/api/v1/workflows/{workflow_id}/artifacts/{name}")
def get_workflow_artifact(workflow_id: str, name: str, request: Request):
    decoded = unquote(name)
    try:
        content, mime_type = workbench_store.get_workflow_artifact_content(current_user(request).id, workflow_id, decoded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc
    return Response(
        content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@router.get("/api/v1/workflows/{workflow_id}/export.zip")
def export_workflow_zip(workflow_id: str, request: Request):
    try:
        files = workbench_store.get_workflow_artifact_files(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="工作流不存在。") from exc
    if not files:
        raise HTTPException(status_code=404, detail="暂无可导出的成果文件。")
    return Response(
        make_zip(files),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''workflow-artifacts.zip"},
    )
