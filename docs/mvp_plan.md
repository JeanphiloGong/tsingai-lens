# 科研助手后端方案（覆盖版：MVP + 下一步）

## 定位与目标
- 将现有 GraphRAG 能力打包成“文献知识图谱助手”的后端 MVP。
- 聚焦 10–100 篇论文：完成导入、抽取、聚类与可视化导出。
- 暂不做聊天与前端，仅保证 Gephi 可用的 GraphML 输出。

## 适配性判断（当前逻辑是否合适）
- 适合：已有文献导入、实体/关系抽取、社区聚类、GraphML 导出闭环。
- 不足：缺批量导入入口、查询/检索 API 对外挂载、图谱字段用于上色与解释不足。
- 结论：可作为科研助手 MVP 的后端核心，但“助手体验”需后续补齐。

## MVP 范围
**范围**
- 论文导入（PDF 为主，转文本入库）
- 图谱抽取、关系构建、社区聚类
- GraphML 导出（用于 Gephi 展示）

**非目标**
- 聊天/对话检索
- OCR（扫描版 PDF 暂不支持）
- 前端可视化仪表盘

## MVP 流程与接口
### 1) 导入
- 单篇导入：`POST /retrieval/index/upload`
- 批量导入：脚本循环上传 10–100 篇
- 纯文本导入：直接放到输入存储目录后运行索引

### 2) 索引与聚类
- `method=standard`（质量优先）或 `fast`（速度优先）
- 增量更新：`is_update_run=true`

### 3) 图谱导出与展示
- `GET /retrieval/graphml` 获取 GraphML
- Gephi 导入后运行布局（如 ForceAtlas2）完成展示

## 关键配置（最小必要）
**模型与环境**
- 需可用的 LLM 与 embedding 端点（`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`）

**可选：生成节点坐标（x/y）**
```yaml
embed_graph:
  enabled: true
  dimensions: 256
  num_walks: 10
  walk_length: 40
  window_size: 2
  iterations: 3
  random_seed: 597832
  use_lcc: true

umap:
  enabled: true
```

**可选：GraphML 快照**
```yaml
snapshots:
  graphml: true
```

## MVP 交付物
- `entities.parquet` / `relationships.parquet` / `communities.parquet`
- `community_reports.parquet`（用于阅读社区摘要）
- GraphML 文件（Gephi 导入）
- 运行日志与输出目录

## 验收标准
- 10–100 篇论文可完成索引且无硬性报错
- GraphML 可在 Gephi 打开并展示网络结构
- `communities.parquet` 存在且可用于分析
- 单次导入时间可接受（假设/待验证）

## 风险与假设（需验证）
- 假设/待验证：PDF 为可复制文本
- 假设/待验证：LLM/Embedding 端点稳定可用
- 假设/待验证：图谱规模在 Gephi 可承载范围内
- 假设/待验证：成本可控

## 下一步（不引入聊天）
- 对外开放检索/查询 API（基于现有查询模块）
- 导出图谱时补充 `community` 字段便于 Gephi 上色
- 批量上传脚本或后端批量接口
- 结果溯源输出（实体/关系 → 原文段落/文献）

## 如需进一步“助手化”（可选）
- 提供自然语言检索入口与对话记忆
- 多项目索引与跨库检索
- 重点议题/实验规律的自动汇总与对比
