from fastapi import APIRouter, HTTPException, Request

from ..schemas import McpServerCreate, McpServerUpdate
from ..services.tool_runtime import refresh_mcp_tools
from ..services.workbench_store import workbench_store
from .dependencies import current_user

router = APIRouter()


@router.get("/api/v1/mcp-servers")
def list_mcp_servers(request: Request):
    return workbench_store.list_mcp_servers(current_user(request).id)


@router.post("/api/v1/mcp-servers")
def create_mcp_server(request: Request, payload: McpServerCreate):
    return workbench_store.create_mcp_server(current_user(request).id, payload)


@router.patch("/api/v1/mcp-servers/{server_id}")
def update_mcp_server(server_id: str, request: Request, payload: McpServerUpdate):
    try:
        return workbench_store.update_mcp_server(current_user(request).id, server_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc


@router.delete("/api/v1/mcp-servers/{server_id}")
def delete_mcp_server(server_id: str, request: Request):
    try:
        workbench_store.delete_mcp_server(current_user(request).id, server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    return {"ok": True}


@router.post("/api/v1/mcp-servers/{server_id}/refresh-tools")
async def refresh_mcp_server_tools(server_id: str, request: Request):
    try:
        user = current_user(request)
        await refresh_mcp_tools(user.id, server_id)
        return {"tools": workbench_store.list_mcp_tools(user.id, server_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP 服务不存在。") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
