# Standard AI Workbench Module

可复制的本地 AI 工作台底座，用于开发单一 skill 应用。它提供项目与对话管理、OpenAI-compatible 流式聊天、账号隔离、模型配置、Tavily 搜索、通用 Workflow/Artifact 和 Electron 打包能力；业务 skill 只通过 `SkillAdapter` 接入。

## 已包含的通用能力

- Codex 风格左右布局，支持可折叠、可拖拽调整宽度的侧栏与响应式布局。
- 本地项目、文件夹工作目录、普通对话和全文搜索。
  - “新对话”始终属于默认项目，显示在“对话”区域。
  - 文件夹项目中的对话只显示在该项目下，不会混入普通对话列表。
- OpenAI-compatible 模型配置、模型列表拉取、模型切换和 SSE 流式回答。
  - 内置 OpenAI、DeepSeek、DashScope、SiliconFlow、OpenRouter 和自定义服务预设。
  - DeepSeek 默认模型为 `deepseek-v4-flash`。
- Tavily 联网搜索。每个账号独立保存 API key、结果数和搜索深度；环境变量可作为全局 fallback。
- 本机多账号登录、注册、退出、改密、8 小时会话和登录失败限流。
- 项目、对话、消息、模型配置、Tavily、MCP、Workflow、Artifact 和搜索索引均按登录账号隔离。跨账号资源统一返回 `404`。
- 本地 stdio MCP 运行时及“模型请求工具 - 用户确认 - 执行 - 继续生成”后端链路。
- 通用 `SkillAdapter + Workflow + Artifact` 契约，以及 `example_echo_workflow` 示例。
- Electron 本地后端启动、随机端口、`APP_AUTH_SECRET` 访问保护、退出时清理后端子进程，以及 macOS/Windows 打包脚本。

## 不包含的业务代码

本模块不包含任何标书专属实现，包括招标文件上传与解析、`bid-design-writer` 指令或模板、阶段一/阶段二标书流程、成果拆分、行为摘要和标书页面文案。新项目应在 `backend/skills/<skill_name>/` 中实现自己的业务逻辑。

## 快速开始

```bash
cd standard_ai_workbench_module
python3 -m pip install -r backend/requirements.txt
npm install
npm --prefix frontend install
npm run dev
```

`npm run dev` 会启动 FastAPI、Next.js 和 Electron。仅调试浏览器界面时：

```bash
npm run dev:agent
npm run dev:ui
```

访问 `http://127.0.0.1:3000`。首次使用可注册任意本机账号；注册后会自动创建该账号的默认项目。

## 配置

模型 API key 通常由用户在界面“模型配置”中保存。可从 `.env.example` 创建 `.env`，配置 Tavily 全局 fallback 或开发环境：

```env
TAVILY_API_KEY=
WEB_SEARCH_MAX_RESULTS=5
TAVILY_SEARCH_DEPTH=basic
APP_AUTH_SECRET=
```

账号保存的 Tavily key 优先于 `TAVILY_API_KEY`。Electron 桌面端会自动注入随机 `APP_AUTH_SECRET`；浏览器开发模式一般不需要配置它。

## 开发新 Skill

1. 复制本目录为新应用，修改 `package.json` 的 `name`、`appId`、`productName` 和 README。
2. 根据目标业务梳理输入、阶段、确认点、成果文件和失败条件。
3. 新建 `backend/skills/<skill_name>/adapter.py`，实现 `SkillAdapter`：`load_instructions()`、`run_stage()`、`confirm_stage()`、`build_artifacts()`。
4. 在 `backend/skills/registry.py` 注册 adapter。业务文件解析、图片处理和文档生成放在该 skill 目录或其 service 中，不修改通用聊天或 Store。
5. 通过通用 `/api/v1/workflows` 接口创建、运行、确认、取消 workflow，并使用 Artifact 下载接口导出成果。
6. 补齐业务 UI 后，运行测试、桌面端验收和打包验证。

`backend/skills/example_echo_workflow/adapter.py` 展示了最小闭环：创建 workflow、生成草稿、用户确认、写入 Markdown Artifact 和 ZIP 下载。

## 数据与安全

桌面版数据目录为 Electron 的 `userData/data`，通常位于：

- macOS：`~/Library/Application Support/standard-ai-workbench-module/data/`
- Windows：`%APPDATA%\\standard-ai-workbench-module\\data\\`
- 浏览器开发模式：项目根目录 `.data/`

`app.db` 保存本地数据与 API key。密码使用 Argon2 哈希；API key 不在接口响应或界面中回显。隔离边界是应用层而非磁盘加密，因此同一系统账号中能直接读取应用数据目录的人也可能读取数据库内容。需要更强隔离时，应使用不同的 macOS 或 Windows 系统账号。

## 打包

后端 agent 由 PyInstaller 生成，因此必须在目标系统打包：

```bash
# macOS
npm run pack:mac        # release/mac/*.app
npm run dist:mac        # ZIP 和 DMG

# Windows
npm run pack:win        # release/win-unpacked/
npm run dist:win        # NSIS 安装包和 ZIP
```

未签名的 macOS 应用首次打开可能需要在 Finder 中右键选择“打开”。正式分发还需分别配置 Apple 签名/公证和 Windows 代码签名。

## 验证

```bash
npm run test:backend
npm run test:frontend
npm run typecheck
npm --prefix frontend run build
```

## 目录

```text
backend/                 FastAPI、SQLite、认证、聊天、搜索和通用 workflow
backend/skills/          SkillAdapter 契约、注册表和示例 skill
frontend/                工作台界面、Markdown 渲染和流式状态机
desktop/                 Electron 主进程、preload 和本地后端生命周期
packaging/               PyInstaller 配置
scripts/                 开发、构建和跨平台打包脚本
```
