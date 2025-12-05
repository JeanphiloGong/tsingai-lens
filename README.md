# TsingAI-Lens: 清华科研文献智能助手

**TsingAI-Lens** 是一个为清华场景定制的私有部署科研助手，基于 [MaxKB](https://github.com/RealityArchitect/MaxKB) 构建，面向科研人员提供一站式文献处理、语义问答、关键词抽取、知识图谱与思维导图自动生成的 AI 系统。

## 📌 项目目标

构建一个本地可部署、支持私有化文献管理的智能助手系统，具备以下能力：

- 支持多种文献格式（PDF、Word、TXT、Markdown 等）
- 从文献中自动提取摘要、关键词
- 基于 GraphRAG 构建实体级知识图谱并做图谱问答
- 自动识别并归纳无量纲公式结构
- 可扩展对接到前端可视化或笔记系统（如 Obsidian、Logseq）

## 🧠 核心功能

| 模块 | 功能描述 |
|------|----------|
| 📄 文献导入 | 支持批量导入 PDF/DOCX/TXT/MD，自动分段切片 |
| 🏷️ 关键词提取 | 基于 YAKE 的关键词抽取 |
| 📚 本地知识库 | GraphRAG：抽取实体/关系图谱并持久化到本地 |
| 🔍 智能检索与问答 | 基于图谱子图采样 + LLM 生成回答 |
| 🧠 知识图谱生成 | LLM 抽取三元组构图，保留溯源页码与片段 |
| 🧭 思维导图输出 | （可选）基于图谱数据生成导图/可视化 |
| 📐 无量纲公式归纳 | 自动抽取文中数理公式并转化为维度无关表达式 |

## 🛠️ 技术栈

- 后端：Python, FastAPI, GraphRAG（networkx 持久化），PyMuPDF, YAKE
- 前端：React（可选），mindmap.js, D3.js
- 部署：Docker, Docker Compose
- 模型支持：OpenAI 兼容 API / 本地 LLM（如 Qwen, Mistral）

## 🗂️ 项目结构

```

tsingai-lens/
├── backend/
│   ├── ingest/         # 文档导入与切片处理
│   ├── graphrag/       # 图谱抽取、存储、检索
│   ├── graph/          # 关键词等辅助图相关工具
│   ├── config/         # 配置文件与模型路径
│   ├── deploy/         # Docker、Nginx、启动脚本等
│   └── tests/          # 单元测试目录
├── frontend/           # 图谱、导图、仪表盘可视化
├── docs/               # 用户文档与部署指南
├── MaxKB/              # 上游参考项目
└── README.md

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

# 启动后端
uvicorn main:app --reload

# 打开前端（纯静态）
python -m http.server 8001 -d ../frontend
```

## 核心 API

- `POST /documents` 上传 PDF/DOCX/TXT/MD/CSV → 自动切片、关键词、图谱抽取、摘要。
- `GET /documents` / `GET /documents/{id}` 文档列表与详情。
- `GET /documents/{id}/keywords`、`GET /documents/{id}/graph` 取关键词、知识图谱/思维导图。
- `POST /query` 基于 GraphRAG，对图谱子图生成回答并返回溯源片段。

## 模型说明

- 生成模型使用 OpenAI 兼容接口，默认 `LLM_MODEL=qwen1.5-8b-chat`。可指向本地 Qwen-8B、DashScope 或其他兼容端点。

## 前端体验

打开 `frontend/index.html`，可完成：
- 上传文献，获取返回的文档 `id`
- 基于图谱问答获取结果
- 基于 `id` 查看关键词和图谱 JSON

## GraphRAG 模式（本地实验优化）

- 上传 PDF：`POST /documents`，自动切页切片并抽取实体/关系构建本地图谱（`data/graph_store.json`）。
- 基于图谱问答：`POST /query`，参数 `query="<目标>"`，`mode=optimize`（输出针对目标的实验优化建议）或 `mode=methods`（输出实验方法/流程片段）。
- 响应形态：`{answer, sources:[{doc_id,page,chunk_id,snippet,edge_id}]}`，便于溯源页码/片段。

后续可以用 React/Vite 将 API 对接 MaxKB UI 或嵌入自定义仪表盘。
