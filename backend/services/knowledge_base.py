from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import OpenAI

from ..schemas import KnowledgeDraft, KnowledgeLintReport, KnowledgePage, KnowledgePatch, KnowledgeSource, KnowledgeVault
from .document_parser import parse_document
from .workbench_store import data_dir, utc_now, workbench_store

MAX_PATCHES = 12
MAX_PAGE_CHARS = 40_000
SAFE_PAGE = re.compile(r"^(?:sources|topics|entities)/[a-zA-Z0-9_-]+\.md$")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


class KnowledgeBase:
    """A source-backed Markdown wiki with database metadata and reviewable patches."""

    def __init__(self) -> None:
        with workbench_store._lock, workbench_store._connection:
            workbench_store._connection.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, filename TEXT NOT NULL,
                    content_hash TEXT NOT NULL, raw_path TEXT NOT NULL, parsed_path TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(owner_user_id, project_id, content_hash)
                );
                CREATE TABLE IF NOT EXISTS knowledge_drafts (
                    id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, patches_json TEXT NOT NULL, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_page_versions (
                    id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL, manifest_path TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    def vault_path(self, user_id: str, project_id: str) -> Path:
        workbench_store.get_project(user_id, project_id)
        vault = data_dir() / "vaults" / user_id / project_id
        for relative in ("raw", "wiki/sources", "wiki/topics", "wiki/entities", "staging", "snapshots"):
            (vault / relative).mkdir(parents=True, exist_ok=True)
        defaults = {
            "wiki/index.md": "# 知识库索引\n\n<!-- 按主题和来源维护的目录。 -->\n",
            "wiki/log.md": "# 知识库日志\n",
            "wiki/AGENTS.md": "# Wiki 维护规则\n\n- raw/ 中来源不可修改。\n- 每个事实必须标记 `来源：source:<id>（文件名，页码或段落）`。\n- 无法核验时标为“待核实”。\n- 仅写入 sources/、topics/、entities/。\n",
        }
        for relative, content in defaults.items():
            path = vault / relative
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        return vault

    def vault(self, user_id: str, project_id: str) -> KnowledgeVault:
        vault = self.vault_path(user_id, project_id)
        count = workbench_store._execute(
            "SELECT COUNT(*) AS count FROM knowledge_sources WHERE owner_user_id = ? AND project_id = ?", (user_id, project_id)
        ).fetchone()["count"]
        pages = len([p for p in (vault / "wiki").rglob("*.md") if p.name not in {"index.md", "log.md", "AGENTS.md"}])
        return KnowledgeVault(project_id=project_id, source_count=count, page_count=pages, path=str(vault))

    def upload(self, user_id: str, project_id: str, filename: str, content: bytes) -> KnowledgeSource:
        vault = self.vault_path(user_id, project_id)
        parsed = parse_document(filename, content)
        digest = hashlib.sha256(content).hexdigest()
        row = workbench_store._execute(
            "SELECT * FROM knowledge_sources WHERE owner_user_id = ? AND project_id = ? AND content_hash = ?",
            (user_id, project_id, digest),
        ).fetchone()
        if row:
            return self._source(row)
        source_id, now = str(uuid4()), utc_now()
        suffix = Path(filename).suffix.lower() or ".bin"
        raw_path, parsed_path = vault / "raw" / f"{source_id}{suffix}", vault / "raw" / f"{source_id}.md"
        raw_path.write_bytes(content)
        parsed_path.write_text(parsed, encoding="utf-8")
        with workbench_store._lock, workbench_store._connection:
            workbench_store._execute(
                """INSERT INTO knowledge_sources
                (id, owner_user_id, project_id, filename, content_hash, raw_path, parsed_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)""",
                (source_id, user_id, project_id, filename, digest, str(raw_path), str(parsed_path), now, now),
            )
        return self.get_source(user_id, project_id, source_id)

    def get_source(self, user_id: str, project_id: str, source_id: str) -> KnowledgeSource:
        return self._source(self._source_row(user_id, project_id, source_id))

    def list_sources(self, user_id: str, project_id: str) -> list[KnowledgeSource]:
        self.vault_path(user_id, project_id)
        rows = workbench_store._execute(
            "SELECT * FROM knowledge_sources WHERE owner_user_id = ? AND project_id = ? ORDER BY created_at DESC", (user_id, project_id)
        ).fetchall()
        return [self._source(row) for row in rows]

    def create_draft(self, user_id: str, project_id: str, source_id: str, profile_id: str | None = None) -> KnowledgeDraft:
        source = self.get_source(user_id, project_id, source_id)
        text = Path(self._source_row(user_id, project_id, source_id)["parsed_path"]).read_text(encoding="utf-8")
        patches = self._model_patches(user_id, source, text, profile_id) or self._fallback_patches(user_id, source, text)
        self._validate(source.id, patches)
        draft_id, now = str(uuid4()), utc_now()
        with workbench_store._lock, workbench_store._connection:
            workbench_store._execute(
                """INSERT INTO knowledge_drafts
                (id, owner_user_id, project_id, source_id, status, patches_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'waiting_confirmation', ?, NULL, ?, ?)""",
                (draft_id, user_id, project_id, source_id, json.dumps([item.model_dump() for item in patches], ensure_ascii=False), now, now),
            )
            workbench_store._execute("UPDATE knowledge_sources SET status = 'drafted', updated_at = ? WHERE id = ?", (now, source_id))
        self._checkpoint(self.vault_path(user_id, project_id), draft_id, {"draft_id": draft_id, "source_id": source_id})
        return self.get_draft(user_id, project_id, draft_id)

    def _fallback_patches(self, user_id: str, source: KnowledgeSource, text: str) -> list[KnowledgePatch]:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(source.filename).stem).strip("-")[:48] or source.id[:8]
        path = f"sources/{slug}-{source.id[:8]}.md"
        content = f"""---
title: {source.filename}
aliases: []
sources:
  - {source.id}
---

# {source.filename}

## 摘要

{text[:4000].strip()}

## 来源

来源：source:{source.id}（{source.filename}，解析全文）
"""
        index = (self.vault_path(user_id, source.project_id) / "wiki/index.md").read_text(encoding="utf-8")
        link = f"[[{path[:-3]}]]"
        if link not in index:
            index = index.rstrip() + f"\n- {link} — {source.filename}\n"
        return [KnowledgePatch(path=path, operation="upsert", content=content), KnowledgePatch(path="index.md", operation="upsert", content=index)]

    def _model_patches(self, user_id: str, source: KnowledgeSource, text: str, profile_id: str | None) -> list[KnowledgePatch] | None:
        if not profile_id:
            return None
        try:
            profile = workbench_store.get_provider_profile(user_id, profile_id)
            key = workbench_store.resolve_api_key(user_id, profile_id)
            if not key:
                return None
            prompt = ("你是受控 Markdown Wiki 编译器。只返回 JSON 数组，元素为 path、operation=upsert、content。"
                f"仅允许 sources/topics/entities 下 .md 或 index.md；每一页必须含来源 source:{source.id}；最多 {MAX_PATCHES} 项。\n"
                f"来源文件：{source.filename}\n内容：\n{text[:30000]}")
            answer = OpenAI(api_key=key, base_url=profile.base_url or None).chat.completions.create(
                model=profile.model, messages=[{"role": "user", "content": prompt}], temperature=0
            ).choices[0].message.content or ""
            matched = re.search(r"\[[\s\S]*\]", answer)
            return [KnowledgePatch.model_validate(item) for item in json.loads(matched.group(0))] if matched else None
        except Exception:
            return None

    def _validate(self, source_id: str, patches: list[KnowledgePatch]) -> None:
        if not patches or len(patches) > MAX_PATCHES:
            raise ValueError("草案页面数量无效。")
        for patch in patches:
            if patch.operation != "upsert" or (patch.path != "index.md" and not SAFE_PAGE.fullmatch(patch.path)):
                raise ValueError(f"草案包含不允许的页面：{patch.path}")
            if len(patch.content) > MAX_PAGE_CHARS:
                raise ValueError(f"页面过大：{patch.path}")
            if patch.path != "index.md" and f"source:{source_id}" not in patch.content:
                raise ValueError(f"页面缺少来源引用：{patch.path}")

    def get_draft(self, user_id: str, project_id: str, draft_id: str) -> KnowledgeDraft:
        row = workbench_store._execute(
            "SELECT * FROM knowledge_drafts WHERE id = ? AND owner_user_id = ? AND project_id = ?", (draft_id, user_id, project_id)
        ).fetchone()
        if not row:
            raise KeyError(draft_id)
        return self._draft(row)

    def list_drafts(self, user_id: str, project_id: str) -> list[KnowledgeDraft]:
        rows = workbench_store._execute(
            "SELECT * FROM knowledge_drafts WHERE owner_user_id = ? AND project_id = ? ORDER BY created_at DESC", (user_id, project_id)
        ).fetchall()
        return [self._draft(row) for row in rows]

    def confirm_draft(self, user_id: str, project_id: str, draft_id: str, approved: bool) -> KnowledgeDraft:
        draft = self.get_draft(user_id, project_id, draft_id)
        if draft.status != "waiting_confirmation":
            raise ValueError("草案已处理。")
        now = utc_now()
        if not approved:
            with workbench_store._connection:
                workbench_store._execute("UPDATE knowledge_drafts SET status = 'rejected', updated_at = ? WHERE id = ?", (now, draft_id))
            return self.get_draft(user_id, project_id, draft_id)
        vault, staging, snapshot = self.vault_path(user_id, project_id), self.vault_path(user_id, project_id) / "staging" / draft_id, self.vault_path(user_id, project_id) / "snapshots" / draft_id
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        manifest: dict[str, str] = {}
        for patch in draft.patches:
            staged = staging / patch.path
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(patch.content, encoding="utf-8")
            manifest[patch.path] = patch.content
            target = vault / "wiki" / patch.path
            if target.exists():
                backup = snapshot / patch.path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
        try:
            for patch in draft.patches:
                target = vault / "wiki" / patch.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staging / patch.path, target)
            source = self.get_source(user_id, project_id, draft.source_id)
            log = vault / "wiki/log.md"
            log.write_text(log.read_text(encoding="utf-8").rstrip() + f"\n\n## [{now[:10]}] ingest | {source.filename}\n\n- draft: {draft_id}\n- source: source:{source.id}\n", encoding="utf-8")
        except Exception:
            for backup in snapshot.rglob("*.md") if snapshot.exists() else []:
                target = vault / "wiki" / backup.relative_to(snapshot)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            raise
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with workbench_store._lock, workbench_store._connection:
            workbench_store._execute("UPDATE knowledge_drafts SET status = 'completed', updated_at = ? WHERE id = ?", (now, draft_id))
            workbench_store._execute("UPDATE knowledge_sources SET status = 'compiled', updated_at = ? WHERE id = ?", (now, draft.source_id))
            workbench_store._execute("INSERT INTO knowledge_page_versions (id, owner_user_id, project_id, draft_id, manifest_path, created_at) VALUES (?, ?, ?, ?, ?, ?)", (str(uuid4()), user_id, project_id, draft_id, str(staging / "manifest.json"), now))
        self._checkpoint(vault, draft_id, {"draft_id": draft_id, "approved": True})
        return self.get_draft(user_id, project_id, draft_id)

    def pages(self, user_id: str, project_id: str, query: str = "") -> list[KnowledgePage]:
        vault = self.vault_path(user_id, project_id)
        paths = [p for p in (vault / "wiki").rglob("*.md") if p.name != "AGENTS.md"]
        paths.sort(key=lambda path: (path.name != "index.md", str(path)))
        needle = query.strip().lower()
        if needle:
            paths = [p for p in paths if needle in p.stem.lower() or needle in p.read_text(encoding="utf-8").lower()]
        return [KnowledgePage(path=str(p.relative_to(vault / "wiki")), title=self._title(p), content=p.read_text(encoding="utf-8")) for p in paths[:30]]

    def lint(self, user_id: str, project_id: str) -> KnowledgeLintReport:
        pages = self.pages(user_id, project_id)
        known = {page.path[:-3] for page in pages}
        index = next((page.content for page in pages if page.path == "index.md"), "")
        broken, orphan = [], []
        for page in pages:
            if page.path in {"index.md", "log.md"}:
                continue
            if f"[[{page.path[:-3]}]]" not in index:
                orphan.append(page.path)
            broken.extend(f"{page.path} -> {link}" for link in WIKILINK.findall(page.content) if link not in known)
        return KnowledgeLintReport(missing_index=orphan, broken_links=broken, orphan_pages=orphan, stale_sources=[])

    def export_files(self, user_id: str, project_id: str) -> dict[str, str]:
        vault = self.vault_path(user_id, project_id)
        return {str(path.relative_to(vault)): path.read_text(encoding="utf-8") for path in vault.rglob("*.md")}

    def _checkpoint(self, vault: Path, thread_id: str, state: dict[str, Any]) -> None:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            from langgraph.graph import END, START, StateGraph
            from langgraph.types import interrupt

            def review(current: dict[str, Any]) -> dict[str, Any]:
                if not current.get("approved"):
                    interrupt({"draft_id": str(current.get("draft_id", "")), "status": "waiting_confirmation"})
                return current

            graph = StateGraph(dict)
            graph.add_node("review", review)
            graph.add_edge(START, "review")
            graph.add_edge("review", END)
            with sqlite3.connect(vault / "checkpoints.db", check_same_thread=False) as conn:
                graph.compile(checkpointer=SqliteSaver(conn)).invoke(state, {"configurable": {"thread_id": thread_id}})
        except ImportError:
            pass

    def _source_row(self, user_id: str, project_id: str, source_id: str) -> sqlite3.Row:
        row = workbench_store._execute("SELECT * FROM knowledge_sources WHERE id = ? AND owner_user_id = ? AND project_id = ?", (source_id, user_id, project_id)).fetchone()
        if not row:
            raise KeyError(source_id)
        return row

    @staticmethod
    def _source(row: sqlite3.Row) -> KnowledgeSource:
        return KnowledgeSource(id=row["id"], project_id=row["project_id"], filename=row["filename"], content_hash=row["content_hash"], status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _draft(row: sqlite3.Row) -> KnowledgeDraft:
        return KnowledgeDraft(id=row["id"], project_id=row["project_id"], source_id=row["source_id"], status=row["status"], patches=[KnowledgePatch.model_validate(item) for item in json.loads(row["patches_json"])], error=row["error"], created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _title(path: Path) -> str:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem


knowledge_base = KnowledgeBase()
