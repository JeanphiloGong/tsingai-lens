# 前端方案（聊天集成 + 文件管理）

本文档仅供前端开发参考，不包含代码改动。

## 背景
- 后端接口（`backend/docs/api.md`）已更新，默认 Base URL：`http://localhost:8010`。
- 已完成：上传 + 状态轮询（`POST /file/upload`，`GET /file/status/{doc_id}`）。
- 待完成：聊天集成（图谱问答）与文件管理（列表/详情/图谱查看）。

## API 对应关系
- 健康检查：`GET /graph/health`
- 上传：`POST /file/upload`；轮询：`GET /file/status/{doc_id}`
- 文档列表：`GET /graph/documents`
- 文档详情：`GET /graph/documents/{doc_id}`
- 关键词：`GET /graph/documents/{doc_id}/keywords`
- 图谱/脑图：`GET /graph/documents/{doc_id}/graph`
- 图谱问答：`POST /chat/query`，body `{ query, mode, top_k_cards, max_edges }`

## 结构与布局
- 单页保持“聊天为主 + 侧栏”模式；可选再开一个文件管理路由：
  - `src/routes/+page.svelte`：聊天主界面，侧栏含上传、文档列表、激活图谱。
  - 可选 `src/routes/files/+page.svelte`：文件管理（列表 + 详情 + 状态刷新）。

## 工作拆分
### A. 聊天集成（同事 1）
1) API 调用：
   - `runQuery({ query, mode, top_k_cards, max_edges })` → `POST /chat/query`
   - 渲染 `answer` + `sources`（字段包含 `doc_id/source/page/chunk_id/snippet/relation/score` 等）。
2) UI 行为：
   - 表单字段：`query` 文本域；`mode` 下拉（optimize/precision/recall）；`top_k_cards`、`max_edges` 数字输入。
   - 结果区：回答气泡；引用列表，显示 doc_id/page/relation/score。
3) 激活图谱提示：
   - 从 sources 提取 doc_id 集合，展示“本轮激活文档/图谱” chips；点击可触发详情/图谱获取（可与文件管理协作）。

### B. 文件管理（同事 2）
1) 列表：
   - 数据源：`GET /graph/documents`
   - 展示字段：`original_filename`、`status/status_message`、`updated_at`、tags；点击填充 doc_id。
2) 详情：
   - 数据源：`GET /graph/documents/{id}`；必要时补充 keywords/graph/mindmap。
   - 展示：摘要、关键词、info、images、graph/mindmap（无图形时 JSON 展示即可）。
3) 状态刷新：
   - 按钮调用 `GET /file/status/{id}` 更新 `status/status_message`。

## 组件建议
- UploadCard：已实现的上传+轮询卡片，保留。
- DocList：列表行显示 status/status_message + 更新时间；点击派发 select(id)。
- DetailPanel：摘要/关键词/info/images，附 graph/mindmap JSON 区；状态/更新时间在头部。
- ChatPanel：问题表单 + 结果 + sources；提供 mode/top_k_cards/max_edges。
- ActiveDocsChip：根据 sources.doc_id 集合显示 chips，点击触发展示详情/图谱。

## 交互顺序（推荐）
1) 页面加载：healthCheck（`/graph/health`）→ listDocuments。
2) 上传：uploadFile → pollStatus → 状态结束后刷新 listDocuments 并预选 doc_id。
3) 问答：runQuery → 展示回答/sources → ActiveDocsChip 高亮 doc_id。
4) 详情/图谱：点击列表或激活 chip → fetchDocumentDetail (+ keywords/graph/mindmap) → JSON 或图形呈现。

## 测试清单
- 上传 PDF/MD/TXT/DOCX/CSV，轮询至成功/失败，状态文案正确。
- 列表展示 status/status_message，更新时间正确。
- 选中文档后，摘要/关键词/graph/mindmap 正常显示（无数据时友好占位）。
- 问答表单：mode/top_k_cards/max_edges 传参正确；sources 展示 doc_id/page/relation/score。
- 激活图谱 chips 与 sources.doc_id 一致；点击能触发详情加载。
