from __future__ import annotations

import argparse
import os

from .services.knowledge_base import knowledge_base

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - dependency is packaged with the desktop agent
    raise SystemExit("Install the MCP dependency: pip install 'mcp>=1.27,<2'") from exc


def build_server(user_id: str, project_id: str) -> FastMCP:
    server = FastMCP("AI Workbench Knowledge (read-only)")

    @server.tool()
    def status() -> dict:
        """Return local vault counts. This server never writes to the vault."""
        return knowledge_base.vault(user_id, project_id).model_dump()

    @server.tool()
    def recall(query: str) -> list[dict]:
        """Search wiki page names and contents, returning source-backed Markdown pages."""
        return [page.model_dump() for page in knowledge_base.pages(user_id, project_id, query)]

    @server.tool()
    def review() -> list[dict]:
        """List pending review-only compilation drafts; confirmation remains in the workbench UI."""
        return [draft.model_dump() for draft in knowledge_base.list_drafts(user_id, project_id) if draft.status == "waiting_confirmation"]

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only AI Workbench knowledge MCP server")
    parser.add_argument("--user-id", default=os.getenv("AI_WORKBENCH_MCP_USER_ID"))
    parser.add_argument("--project-id", default=os.getenv("AI_WORKBENCH_MCP_PROJECT_ID"))
    args = parser.parse_args()
    if not args.user_id or not args.project_id:
        raise SystemExit("--user-id and --project-id are required")
    build_server(args.user_id, args.project_id).run()


if __name__ == "__main__":
    main()
