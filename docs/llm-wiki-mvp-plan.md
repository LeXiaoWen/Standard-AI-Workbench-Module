# LLM Wiki 知识库 MVP

## 架构

知识库采用“原始来源 + LLM 维护的 Markdown Wiki + 规则文件”模式，不使用向量 RAG。每个账号与项目拥有应用数据目录中的独立 vault：

- `raw/`：不可变上传文件及其解析文本；
- `wiki/`：`index.md`、`log.md`、`AGENTS.md` 和来源/主题/实体页面；
- `staging/`、`snapshots/`：确认写入前的补丁和回滚副本；
- `checkpoints.db`：LangGraph SQLite checkpoint。

SQLite 只保存来源、草案和版本元数据；Markdown 文件是用户可导出的知识成果。

## 工作流

1. 用户上传 PDF、DOCX、TXT 或 Markdown；服务保存原文件、解析文本，并按 SHA-256 去重。
2. 已配置模型时，服务请求模型返回受限 JSON 页面补丁；失败或未配置时使用确定性来源摘要补丁。
3. 服务校验补丁仅写入 `sources/`、`topics/`、`entities/` 或 `index.md)，并要求每页含来源 ID。
4. LangGraph 创建持久化的人工确认 checkpoint；前端展示即将写入的页面。
5. 用户确认后，补丁先写入 staging，再复制到 wiki，并记录 snapshot、manifest 和 `log.md`。拒绝时不改动 wiki。

## API

- `GET /api/v1/projects/{project_id}/knowledge-vault`
- `POST /api/v1/projects/{project_id}/knowledge-sources`
- `POST /api/v1/projects/{project_id}/knowledge-sources/{source_id}/compile`
- `GET /api/v1/projects/{project_id}/knowledge-drafts`
- `POST /api/v1/projects/{project_id}/knowledge-drafts/{draft_id}/confirm`
- `GET /api/v1/projects/{project_id}/knowledge-pages`
- `GET /api/v1/projects/{project_id}/knowledge-lint`
- `GET /api/v1/projects/{project_id}/knowledge-vault/export.zip`

所有接口均根据登录账号和项目 ID 派生路径；跨账号与跨项目访问返回 404。

## MCP

`python -m backend.knowledge_mcp --user-id <id> --project-id <id>` 启动只读 stdio MCP 服务，提供 `status`、`recall` 和 `review`。它不提供导入、确认或文件写入能力。
