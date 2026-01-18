# TsingAI-Lens: 清华科研文献智能助手

**TsingAI-Lens** 是一个可私有部署的科研文献后端，基于 Retrieval（GraphRAG pipeline）构建，提供文献导入、索引、知识图谱与结构化检索能力。

## 📌 项目目标

构建一个本地可部署、支持私有化文献管理的智能助手系统，具备以下能力：

- 支持多种文献格式（PDF、TXT 等，PDF 将提取纯文本后入库）
- 基于 Retrieval 标准索引（GraphRAG pipeline）构建知识图谱与检索输出
- 输出可导入 Gephi 的 GraphML 图谱
- 以“集合”为核心组织论文、索引与导出流程

## 🧠 核心功能

| 模块 | 功能描述 |
|------|----------|
| 📄 文献导入 | 上传论文到集合输入存储（支持批量） |
| 📚 标准索引 | Retrieval（GraphRAG pipeline）构建实体/关系与索引结果 |
| 🧠 知识图谱生成 | 生成实体/关系图谱并支持导出与可视化 |
| 🔍 图谱导出 | 提供 GraphML 导出用于 Gephi 等工具 |
| 🗂️ 集合管理 | 创建/列出/删除集合，查询集合统计信息 |

## 🛠️ 技术栈

- 后端：Python, FastAPI, GraphRAG（networkx 持久化），PyMuPDF
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
│   ├── data/           # 存储目录（配置、集合、索引、输出）
│   └── tests/          # 单元测试
├── docs/               # 顶层文档
└── backend/docs/       # API 文档（如 api.md）

```

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

```

## 核心 API

- `/retrieval/collections`：创建/列出集合（含统计指标）。
- `/retrieval/collections/{collection_id}`：删除集合（默认集合不可删除）。
- `/retrieval/index`：对集合启动标准索引流程。
- `/retrieval/index/upload`：上传单文件并触发索引。
- `/retrieval/input/upload`：批量上传文件到集合输入存储（不触发索引）。
- `/retrieval/query`：基于集合索引结果进行结构化检索。
- `/retrieval/graphml`：导出 GraphML 供 Gephi 等工具使用（支持 `include_community`、`community_id`）。

详见更新后的 API 文档：`backend/docs/api.md`（中文，含 curl 示例）。

## 集合列表字段说明

- `status`：`ready`（有实体输出）/ `empty`（未完成索引）。
- `document_count`：集合内文档数（来自 `documents.parquet` 或索引统计）。
- `entity_count`：集合内实体数（来自 `entities.parquet`）。
- `updated_at`：集合输出目录关键产物更新时间，缺失时可回退使用 `created_at`。

## 推荐使用流程（MVP）

1) 创建集合（可选）：`POST /retrieval/collections`
2) 批量上传论文：`POST /retrieval/input/upload`
3) 启动索引：`POST /retrieval/index`
4) 导出图谱：`GET /retrieval/graphml`
5) 进入检索：`POST /retrieval/query`

## GraphML 导出参数（常用）

- `include_community`：默认 `true`，在节点上输出 `community` 字段用于 Gephi 分组着色。
- `community_id`：按社区过滤导出。
- `max_nodes`：限制最大节点数（避免过大文件）。
- `min_weight`：按关系权重过滤。

## 模型说明

- 生成模型使用 OpenAI 兼容接口，默认 `LLM_MODEL=qwen1.5-8b-chat`。可指向本地 Qwen-8B、DashScope 或其他兼容端点。
