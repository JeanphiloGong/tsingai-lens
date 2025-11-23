# TsingAI-Lens: 清华科研文献智能助手

**TsingAI-Lens** 是一个为清华场景定制的私有部署科研助手，基于 [MaxKB](https://github.com/RealityArchitect/MaxKB) 构建，面向科研人员提供一站式文献处理、语义问答、关键词抽取、知识图谱与思维导图自动生成的 AI 系统。

## 📌 项目目标

构建一个本地可部署、支持私有化文献管理的智能助手系统，具备以下能力：

- 支持多种文献格式（PDF、Word、TXT、Markdown 等）
- 从文献中自动提取摘要、关键词
- 对文献进行语义向量化和本地检索
- 支持自然语言问答
- 自动构建实体级知识图谱与思维导图
- 自动识别并归纳无量纲公式结构
- 可扩展对接到前端可视化或笔记系统（如 Obsidian、Logseq）

## 🧠 核心功能

| 模块 | 功能描述 |
|------|----------|
| 📄 文献导入 | 支持批量导入 PDF/DOCX/TXT/MD，自动分段切片 |
| 🏷️ 关键词提取 | 基于 KeyBERT/YAKE 的关键词抽取，支持领域词典增强 |
| 📚 本地知识库 | 使用 FAISS/Chroma 构建文献语义向量数据库 |
| 🔍 智能检索与问答 | 基于 RAG（检索增强生成）模型提供问答能力 |
| 🧠 知识图谱生成 | 使用实体识别与关系抽取构建图谱结构，支持可视化 |
| 🧭 思维导图输出 | 将图谱转换为主题导图视图，便于理解与展示 |
| 📐 无量纲公式归纳 | 自动抽取文中数理公式并转化为维度无关表达式 |

## 🛠️ 技术栈

- 后端：Python, FastAPI, LangChain, FAISS, PyMuPDF, spaCy
- 前端：React（可选），mindmap.js, D3.js
- 部署：Docker, Docker Compose
- 模型支持：OpenAI API / 本地 LLM（如 Mistral, Qwen）

## 🗂️ 项目结构

```

tsingai-lens/
├── backend/
│   ├── ingest/         # 文档导入与切片处理
│   ├── extractor/      # 关键词、实体、公式抽取模块
│   ├── retriever/      # 向量化与本地语义检索
│   ├── qna/            # 基于文献问答模块
│   ├── graph/          # 知识图谱与思维导图生成
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
# 依赖不再使用 requirements.txt

# 配置本地模型，Qwen-8B 的 OpenAI 兼容推理服务示例
export LLM_BASE_URL=http://localhost:11434/v1   # 例如 Ollama/vLLM/OpenAI 兼容网关
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local                     # 只要服务端接受即可
export EMBEDDING_BASE_URL=http://localhost:11434/v1
export EMBEDDING_MODEL=text-embedding-3-large
export EMBEDDING_API_KEY=sk-local

# 启动后端
uvicorn main:app --reload

# 打开前端（纯静态）
python -m http.server 8001 -d ../frontend
```

## 核心 API

- `POST /documents` 上传 PDF/DOCX/TXT/MD/CSV → 自动切片、向量化、关键词、知识图谱、思维导图、摘要。
- `GET /documents` / `GET /documents/{id}` 文档列表与详情。
- `GET /documents/{id}/keywords`、`GET /documents/{id}/graph` 取关键词、知识图谱/思维导图。
- `POST /query` 搭配 RAG 对话，返回回答与引用片段。

## 模型说明

- 向量化默认使用 `BAAI/bge-small-zh-v1.5`（可通过 `EMBEDDING_MODEL` 环境变量替换为已下载路径）。
- 生成模型使用 OpenAI 兼容接口，默认 `LLM_MODEL=qwen1.5-8b-chat`。可指向本地 Qwen-8B、DashScope 或其他兼容端点。
- spaCy 中文模型（可选，用于更好的实体识别）需额外安装：`python -m spacy download zh_core_web_sm`。

## 前端体验

打开 `frontend/index.html`，可完成：
- 上传文献，获取返回的文档 `id`
- 输入问题走 RAG 检索与回答
- 基于 `id` 查看关键词、知识图谱和思维导图 JSON

后续可以用 React/Vite 将 API 对接 MaxKB UI 或嵌入自定义仪表盘。
