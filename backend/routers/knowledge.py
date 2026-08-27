from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from ..schemas import KnowledgeDraft, KnowledgeLintReport, KnowledgePage, KnowledgeSource, KnowledgeVault
from ..services.artifacts import make_zip
from ..services.knowledge_base import knowledge_base
from .dependencies import current_user, read_upload_with_limit

router = APIRouter()


@router.get("/api/v1/projects/{project_id}/knowledge-vault", response_model=KnowledgeVault)
def get_knowledge_vault(project_id: str, request: Request):
    try:
        return knowledge_base.vault(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.get("/api/v1/projects/{project_id}/knowledge-sources", response_model=list[KnowledgeSource])
def list_knowledge_sources(project_id: str, request: Request):
    try:
        return knowledge_base.list_sources(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.post("/api/v1/projects/{project_id}/knowledge-sources", response_model=KnowledgeSource)
async def upload_knowledge_source(project_id: str, request: Request, file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise ValueError("请选择要导入的文件。")
        return knowledge_base.upload(current_user(request).id, project_id, file.filename, await read_upload_with_limit(file))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/projects/{project_id}/knowledge-drafts", response_model=list[KnowledgeDraft])
def list_knowledge_drafts(project_id: str, request: Request):
    try:
        return knowledge_base.list_drafts(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.post("/api/v1/projects/{project_id}/knowledge-sources/{source_id}/compile", response_model=KnowledgeDraft)
def compile_knowledge_source(project_id: str, source_id: str, request: Request, provider_profile_id: str | None = Form(default=None)):
    try:
        return knowledge_base.create_draft(current_user(request).id, project_id, source_id, provider_profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="知识来源不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/projects/{project_id}/knowledge-drafts/{draft_id}", response_model=KnowledgeDraft)
def get_knowledge_draft(project_id: str, draft_id: str, request: Request):
    try:
        return knowledge_base.get_draft(current_user(request).id, project_id, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="草案不存在。") from exc


@router.post("/api/v1/projects/{project_id}/knowledge-drafts/{draft_id}/confirm", response_model=KnowledgeDraft)
def confirm_knowledge_draft(project_id: str, draft_id: str, request: Request, approved: bool = Form(...)):
    try:
        return knowledge_base.confirm_draft(current_user(request).id, project_id, draft_id, approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="草案不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/projects/{project_id}/knowledge-pages", response_model=list[KnowledgePage])
def list_knowledge_pages(project_id: str, request: Request, q: str = Query(default="")):
    try:
        return knowledge_base.pages(current_user(request).id, project_id, q)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.get("/api/v1/projects/{project_id}/knowledge-lint", response_model=KnowledgeLintReport)
def lint_knowledge_vault(project_id: str, request: Request):
    try:
        return knowledge_base.lint(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.get("/api/v1/projects/{project_id}/knowledge-vault/export.zip")
def export_knowledge_vault(project_id: str, request: Request):
    try:
        files = knowledge_base.export_files(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return Response(make_zip(files), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=knowledge-vault.zip"})
