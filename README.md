# Standard AI Workbench Module

从业务项目中抽出的通用 AI 工作台底座，去除标书业务逻辑，保留可复用的基础能力，并内置通用 `SkillAdapter + Workflow + Artifact` 契约，用于快速开发其他 skill 应用。

## 功能特性

- 左右分栏工作台 UI，支持 Chat / Workbench 双模式切换
- 可折叠左侧菜单
- 本地项目工作目录选择
- 项目、历史对话、全文搜索
- OpenAI-compatible 模型配置，内置 OpenAI、DeepSeek、通义千问 DashScope、硅基流动 SiliconFlow、OpenRouter 预设
- 通过 API 拉取模型列表并切换模型
- 右侧聊天窗口，SSE 流式回答
- LLM tool calling：Tavily 联网搜索与本地 MCP stdio 工具确认执行
- Markdown 渲染，工具调用状态展示（ToolReasoning）
- 本机账号登录/注册、改密、退出，登录限流保护
- Electron `APP_AUTH_SECRET` 本机访问保护
- 系统钥匙串保存模型 API key（开发环境可回退到进程内存）
- 文件上传解析（PDF、DOCX、TXT、MD）
- 通用 Workflow / Artifact / ZIP 下载
- 示例 `example_echo_workflow`
- Electron 桌面壳
- FastAPI + SQLite 后端持久化

## 目录结构

```text
standard_ai_workbench_module/
  backend/
    main.py                           # FastAPI 路由
    schemas.py                        # 通用 Pydantic 数据模型
    services/
      workbench_store.py              # SQLite 项目/会话/消息/模型配置/MCP/搜索存储
      workbench_llm.py                # OpenAI-compatible SSE 流式聊天 + tool calling 调度
      llm.py                          # Agno Agent 封装（OpenAI-compatible）
      tool_runtime.py                 # MCP stdio 工具运行时 + web_search 工具定义
      web_search.py                   # Tavily 联网搜索集成
      provider_models.py              # 模型列表拉取
      auth.py                         # 账号注册/登录/改密/登出，登录限流
      config.py                       # API 预设（OpenAI/DeepSeek/DashScope/SiliconFlow/OpenRouter）
      artifacts.py                    # ZIP 文件打包
      document_parser.py              # PDF/DOCX/TXT/MD 文件解析
    skills/
      base.py                         # SkillAdapter 抽象契约
      registry.py                     # Adapter 注册表
      example_echo_workflow/          # 示例 skill（adapter 注册 → 状态流转 → artifact → ZIP）
    tests/
      test_api.py                     # 后端回归测试（auth/CORS/CRUD/MCP/workflow）
      test_services.py                # 服务层单元测试
  desktop/
    main.ts                           # Electron 主进程，启动后端 agent 并打开 UI
    preload.ts                        # 安全暴露选择本地目录能力
    tsconfig.json
  frontend/
    src/
      app/
        page.tsx                      # 聊天窗口 + 模型配置 + Workflow 面板
        layout.tsx                    # 根布局
        globals.css                   # 标准工作台 UI 样式
      components/
        MarkdownPane.tsx              # Markdown 渲染组件
        WorkbenchLayout.tsx           # Chat / Workbench 双模式布局切换
        ToolReasoning.tsx             # 工具调用状态卡片（执行中/完成/错误）
      lib/
        api.ts                        # 前端 API 客户端
        types.ts                      # 前端类型定义
        chatReducer.ts                # SSE 事件 → 消息列表状态机
        chatReducer.test.ts           # chatReducer 单元测试
      types/
        desktop.d.ts                  # Electron preload 类型声明
    next.config.ts
    package.json
  scripts/
    run-agent.js / .sh / .bat         # 启动后端 agent
    setup-agent.js / .sh / .bat       # 安装后端 Python 依赖
    build-agent.mjs                   # PyInstaller 构建后端 agent
    run-electron.mjs                  # 启动 Electron 桌面窗口
    run-electron-builder.mjs          # 执行 electron-builder 打包
    package-desktop.mjs               # 桌面打包编排（Next.js export → PyInstaller → electron-builder）
  packaging/
    agent.spec                        # PyInstaller spec
    agent_entry.py                    # PyInstaller 入口
  .env.example                        # 环境变量模板
  package.json                        # 根 monorepo 脚本与 electron-builder 配置
```

## 环境准备

```bash
cd standard_ai_workbench_module

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

npm install
npm --prefix frontend install
```

## 开发运行

```bash
npm run dev
```

这会同时启动：

- `backend.main:app` on `http://127.0.0.1:8765`
- Next.js frontend on `http://127.0.0.1:3000`
- Electron desktop window

开发模式默认复用固定 `8765` 端口；打包后的桌面应用会在启动时分配随机本地端口，并通过 Electron preload 传给前端，避免误连到其他项目或旧进程的后端。

只运行 Web 版本（不启动 Electron）：

```bash
npm run dev:api
npm run dev:ui
```

## 环境变量

参见 [.env.example](.env.example)：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8765
AI_WORKBENCH_DATA_DIR=.data
APP_AUTH_SECRET=
AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS=false
SEARCH_BASE_URL=
SEARCH_MAX_RESULTS=5
FRONTEND_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,app://frontend,null
FRONTEND_ORIGIN_REGEX=^(https?://(localhost|127\\.0\\.0\\.1|\\[::1\\])(:\\d+)?|app://frontend|null)$
```

- `APP_AUTH_SECRET`：Electron 本机访问保护密钥，前端请求需带 `X-App-Auth-Secret` 头。生产环境应设为随机字符串。
- `AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS`：设为 `true` 时，钥匙串不可用则回退到进程内存保存 API key（仅开发/测试）。
- `AI_WORKBENCH_DATA_DIR`：SQLite 数据库存储目录，默认 `.data`。

## 配置模型

前端左侧点击「模型配置」，填写：

- Provider（可从预设中选择）
- Base URL
- Model
- API key

默认支持 OpenAI-compatible API，内置预设：

| 预设 | Base URL |
|------|----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com` |
| 通义千问 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 硅基流动 SiliconFlow | `https://api.siliconflow.cn/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |

也可选择「自定义」填入任意 OpenAI-compatible 服务地址。

API key 不写入 SQLite。默认保存到系统钥匙串；开发/测试环境可设置 `AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS=true`，在钥匙串不可用时回退到进程内存。

## 联网搜索与 MCP 工具

底座内置统一 Tool Layer。普通聊天默认不启用工具；用户在输入栏打开联网搜索或选择 MCP server 后，后端会把可用工具作为 OpenAI-compatible `tools` 暴露给模型。模型请求工具时，当前流会暂停并在消息中显示确认卡片；用户批准或拒绝后，前端调用 resume stream，后端把工具结果或拒绝说明传回模型继续生成。

### 联网搜索

联网搜索使用 Tavily Search API，不依赖模型厂商内置搜索能力。DeepSeek、OpenAI-compatible 模型都通过 function/tool calling 调用本应用的 `web_search`。

配置方式：

```env
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx
TAVILY_SEARCH_URL=https://api.tavily.com/search     # 可选，默认值
TAVILY_SEARCH_TIMEOUT=20                             # 可选，默认 20 秒
```

也可在左侧「模型配置」面板里保存 Tavily API key。未配置 key 时，`web_search` 不会暴露给模型，不影响普通聊天。搜索结果最多 5 条（可配置 1-10），支持 `basic` / `advanced` 两种搜索深度。

### 本地 MCP

MCP v1 只支持本机 stdio server 的 `tools/list` 和 `tools/call`，不支持 resources、prompts、sampling、远程 HTTP/SSE。MCP server 保存字段包括 `name`、`command`、`args`、`env`、`enabled`；API 返回 env 时会脱敏为 `********`。

MCP 命令会在本机执行，只应配置可信 server。建议先手动确认命令来源和权限，再在 UI 中启用。

## 文件上传

支持上传 PDF、DOCX、TXT、MD 文件（最大 25MB），后端自动解析文本内容。旧版 `.doc` 文件不支持，需先转换为 `.docx`。PDF 扫描件需先 OCR 后再上传。

## 后端 API

核心接口：

```text
GET    /health

# 认证
GET    /api/v1/auth/status
POST   /api/v1/auth/setup
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
POST   /api/v1/auth/change-password
GET    /api/v1/me

# 项目
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
DELETE /api/v1/projects/{project_id}

# 对话
GET    /api/v1/conversations
POST   /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}
PATCH  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}
GET    /api/v1/conversations/{conversation_id}/messages

# 模型配置
GET    /api/v1/provider-profiles
POST   /api/v1/provider-profiles
GET    /api/v1/provider-profiles/{profile_id}
PATCH  /api/v1/provider-profiles/{profile_id}
DELETE /api/v1/provider-profiles/{profile_id}
GET    /api/v1/provider-profiles/{profile_id}/models

# 搜索
GET    /api/v1/search?q=...

# 聊天
POST   /api/v1/chat/stream
POST   /api/v1/chat/{run_id}/cancel
POST   /api/v1/chat/tool-calls/{tool_call_id}/approve
POST   /api/v1/chat/tool-calls/{tool_call_id}/reject
POST   /api/v1/chat/tool-calls/{tool_call_id}/resume-stream

# 联网搜索配置
GET    /api/v1/web-search-config
PATCH  /api/v1/web-search-config

# MCP Server
GET    /api/v1/mcp-servers
POST   /api/v1/mcp-servers
PATCH  /api/v1/mcp-servers/{server_id}
DELETE /api/v1/mcp-servers/{server_id}
POST   /api/v1/mcp-servers/{server_id}/refresh-tools

# Skill / Workflow
GET    /api/v1/skills
POST   /api/v1/workflows
GET    /api/v1/workflows
GET    /api/v1/workflows/{workflow_id}
POST   /api/v1/workflows/{workflow_id}/run
POST   /api/v1/workflows/{workflow_id}/confirm
POST   /api/v1/workflows/{workflow_id}/cancel
GET    /api/v1/workflows/{workflow_id}/artifacts
GET    /api/v1/workflows/{workflow_id}/artifacts/{name}
GET    /api/v1/workflows/{workflow_id}/export.zip
```

`/api/v1/chat/stream` 返回 SSE，事件包括：

- `message_start`
- `delta`
- `message_done`
- `conversation_updated`
- `tool_call_pending`
- `tool_call_result`
- `tool_call_rejected`
- `tool_call_error`
- `error`

## SkillAdapter 开发流程

推荐复制整个目录作为新项目的基础模板：

```bash
cp -R standard_ai_workbench_module ../your_new_ai_app
```

然后按项目需要修改应用名、包名、默认文案和打包名称。

开发新 skill 的最小路径：

1. 阅读目标 skill 的 `SKILL.md`，整理输入类型、阶段、确认点、成果文件和失败场景。
2. 新增 `backend/skills/<skill_name>/adapter.py`，实现 `SkillAdapter`。
3. 在 `backend/skills/registry.py` 注册 adapter。
4. 如需文件解析、图片处理、PPT/DOCX 生成，放在该 skill 自己的 service 中。
5. 前端默认已有通用 WorkflowPanel，单 skill 应用只需修改入口文案、图标或补充专属表单。
6. 跑通：输入/上传 → 创建 workflow → run → confirm → artifact → ZIP 下载。

不要直接把业务工作流写进 `workbench_llm.py` 或 `workbench_store.py`。这两个文件建议保持为通用基础设施，业务逻辑放在独立 service 中，再由 `main.py` 挂载路由。

底座内置 `example_echo_workflow`，用于演示 adapter 注册、状态流转、Markdown artifact 和 ZIP 下载。

## 打包

只做构建检查：

```bash
npm run build
```

打包当前平台应用：

```bash
npm run dist
```

分平台打包：

```bash
npm run dist:mac          # macOS（ZIP + DMG）
npm run dist:mac:zip      # macOS（仅 ZIP）
npm run dist:mac:dmg      # macOS（仅 DMG）
npm run dist:win          # Windows（NSIS 安装包 + ZIP）
npm run dist:linux        # Linux（AppImage + tar.gz）
```

快速生成未压缩应用目录：

```bash
npm run pack              # 当前平台
npm run pack:mac          # macOS
npm run pack:win          # Windows
```

打包链路为：

```text
Next.js static export → PyInstaller onedir backend agent → electron-builder desktop app
```

后端 agent 使用 onedir 形式放入应用资源目录，路径类似：

```text
Contents/Resources/agent/ai-workbench-agent/ai-workbench-agent
```

这种形式比 PyInstaller one-file 冷启动更快，也不会每次启动都解包到临时目录。

## 验证

```bash
npm run test:backend      # 后端 pytest 回归测试
npm run test:frontend     # 前端单元测试
npm run typecheck         # TypeScript 类型检查
npm --prefix frontend run build
```

## 与原项目的边界

本模块不包含：

- bid-design-writer skill
- 招标文件上传与解析
- 阶段一/阶段二标书 workflow
- 业务模板选择

这些内容应在具体项目中作为独立业务模块接入。

本模块包含通用的文件解析（PDF/DOCX/TXT/MD）、Workflow 引擎、artifact/ZIP 导出能力，但不包含任何具体业务成果格式。
