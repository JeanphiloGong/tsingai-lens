# MVP 方案：论文批量导入 → 知识图谱聚类 → Gephi 展示

## 目标
- 支持 10–100 篇论文导入并完成知识图谱抽取与聚类。
- 输出可在 Gephi 中展示的图谱（GraphML），用于快速观察主题/实验规律分布。
- 先完成后端闭环，不做前端与聊天功能。

## 范围与非目标
**范围**
- 论文导入（PDF 为主，文本抽取后入库）
- 图谱抽取、实体关系、社区聚类
- 图谱导出（GraphML）

**非目标**
- 聊天/对话检索
- 复杂前端可视化
- OCR（扫描版 PDF 暂不支持）

## 现有能力复用（基于当前代码）
- 索引与图谱生成：GraphRAG 标准/快速流水线（`backend/retrieval/index/workflows/factory.py`）
- PDF 上传与文本抽取：`POST /retrieval/index/upload`（`backend/controllers/retrieval.py`）
- GraphML 导出：`GET /retrieval/graphml`（`backend/controllers/retrieval.py`）
- 社区聚类（Leiden）：`backend/retrieval/index/operations/cluster_graph.py`

## MVP 流程（后端闭环）
### 1) 数据准备与导入
**推荐路径（简单可靠）**
- 将 PDF 逐个上传：`POST /retrieval/index/upload`
- 首次运行用 `method=standard` 或 `fast`
- 后续增量用 `is_update_run=true`（支持增量更新）

**注意**
- 输入类型当前为 `text`，非 PDF 文件需先转换为纯文本再导入。
- 扫描版 PDF 需要 OCR（MVP 不含）。

### 2) 索引与聚类
**标准 vs 快速**
- `standard`：效果好，成本高
- `fast`：速度快，抽取质量略低

**建议**
10–100 篇范围，优先 `standard`，若成本敏感可切 `fast`。

### 3) 图谱导出与展示
- 通过 `/retrieval/graphml` 导出 GraphML
- 在 Gephi 中导入并运行布局算法（如 ForceAtlas2）即可展示

## 配置建议（仅配置文件调整，非代码）
目标是让图谱节点具备坐标，或由 Gephi 计算布局。

**可选：开启节点嵌入 + UMAP（生成 x/y）**
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
说明：`embed_graph` 与 `umap` 默认关闭，开启后可生成节点坐标（`x/y`）。

**可选：GraphML 快照**
```yaml
snapshots:
  graphml: true
```
说明：如需自动落地 GraphML 文件，可开启。

## MVP 交付物
- `entities.parquet` / `relationships.parquet` / `communities.parquet`
- GraphML 文件（用于 Gephi）
- 运行日志与输出目录

## 验收标准
- 10–100 篇论文可完成索引且无硬性报错
- GraphML 可在 Gephi 打开并展示网络结构
- 社区聚类结果存在且可用于分析
- 单次完整导入在可接受时间内完成（假设/待验证）

## 风险与假设（需验证）
- 假设/待验证：PDF 为可复制文本
- 假设/待验证：LLM/Embedding 接口可稳定调用
- 假设/待验证：图谱规模在 Gephi 可承载范围内

## 后续可选增强（非 MVP）
- GraphML 导出增加 `community` 字段（按聚类上色）
- 批量上传脚本或后端批量接口
- 前端可视化仪表盘
- 对话检索/聊天功能
