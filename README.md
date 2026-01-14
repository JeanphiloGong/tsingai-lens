# TsingAI-Lens: 清华科研文献智能助手

**TsingAI-Lens** 是一个为清华场景定制的私有部署科研助手，基于 [MaxKB](https://github.com/RealityArchitect/MaxKB) 构建，面向科研人员提供一站式文献处理、语义问答、关键词抽取、知识图谱与思维导图自动生成的 AI 系统。

## 📌 项目目标

构建一个本地可部署、支持私有化文献管理的智能助手系统，具备以下能力：

- 支持多种文献格式（PDF、Word、TXT、Markdown 等）
- 从文献中自动提取摘要、关键词
- 基于 Retrieval 标准索引（GraphRAG pipeline）构建知识图谱与检索输出
- 自动识别并归纳无量纲公式结构
- 可扩展对接到前端可视化或笔记系统（如 Obsidian、Logseq）

## 🧠 核心功能

| 模块 | 功能描述 |
|------|----------|
| 📄 文献导入 | 通过 `/retrieval/index/upload` 上传并进入标准索引流程 |
| 📚 标准索引 | Retrieval（GraphRAG pipeline）构建实体/关系与索引结果 |
| 🧠 知识图谱生成 | 生成实体/关系图谱并支持导出与可视化 |
| 🔍 图谱导出 | 提供 GraphML 导出用于 Gephi 等工具 |
| ⚙️ 配置管理 | 支持配置文件上传、创建与查看 |

## 🛠️ 技术栈

- 后端：Python, FastAPI, GraphRAG（networkx 持久化），PyMuPDF
- 前端：React（可选），mindmap.js, D3.js
- 部署：Docker, Docker Compose
- 模型支持：OpenAI 兼容 API / 本地 LLM（如 Qwen, Mistral）

## 🗂️ 项目结构

```

tsingai-lens/
├── backend/
│   ├── controllers/    # FastAPI 路由：/retrieval
│   ├── retrieval/      # GraphRAG 标准检索与索引流程
│   ├── utils/          # 工具模块（日志等）
│   ├── config.py       # 配置与常量
│   ├── data/           # 存储目录（配置、索引、输出）
│   └── tests/          # 单元测试
├── frontend/           # 可选前端静态资源
├── docs/               # 顶层文档
└── backend/docs/       # API 文档（如 api.md）

````

## 🚀 快速启动（本地开发）

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync   # 使用 uv.lock 安装依赖（已通过 uv add 管理）

# 配置本地/远程 LLM，Qwen-8B 的 OpenAI 兼容推理服务示例
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local

# 启动后端（默认 8000，如需和文档一致可用 8010）
uvicorn main:app --reload --port 8010

# 打开前端（纯静态）
python -m http.server 8001 -d ../frontend
```

## 核心 API

- `/retrieval/index`：根据配置启动标准索引流程。
- `/retrieval/index/upload`：上传文件并使用默认配置触发索引。
- `/retrieval/graphml`：导出 GraphML 供可视化工具使用。
- `/retrieval/configs`：配置文件上传、创建、查看与列表。

详见更新后的 API 文档：`backend/docs/api.md`（中文，含 curl 示例）。

## 模型说明

- 生成模型使用 OpenAI 兼容接口，默认 `LLM_MODEL=qwen1.5-8b-chat`。可指向本地 Qwen-8B、DashScope 或其他兼容端点。

## 前端体验

当前后端仅提供 `/retrieval` 相关接口，前端需要按索引与导出结果进行对接与展示。

## Retrieval 流程（标准索引）

- 上传文件：`POST /retrieval/index/upload`
- 直接索引：`POST /retrieval/index`
- 图谱导出：`GET /retrieval/graphml`

后续可以用 React/Vite 将 API 对接 MaxKB UI 或嵌入自定义仪表盘。
