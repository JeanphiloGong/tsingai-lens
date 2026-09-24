# Lens Agent 反馈分析工作台 API 设计

状态：2026-09-24，重构设计稿。P1–P6 的生产实现已经撤销，本文描述的是下一轮验证要实现的接口边界，不是当前服务可以直接调用的 API。

这份文档只回答一个问题：**一条用户反馈怎样经过系统，最终变成一种可复现的数据集。** 读者应先看完整场景，再看单个接口。模型 prompt、token 和内部调用记录只用于后台诊断，不是普通用户的操作流程。

## 1. 完整场景

假设研究者在 Collection `col_materials` 中提问：

> 比较文献 A、B、C 中预热温度对 316L 微观结构的影响。

系统生成回答 `answer_123`。研究者发现回答说“B 没有预热”，但 B 的预热信息其实在图注中，于是对回答点踩并选择 `incorrect`。

从这一次反馈到数据集的完整链路是：

```text
研究者正常提问
  → Chat 保存问题、回答、工具调用和 Source 引用
  → 研究者点踩
  → 系统创建 feedback_analysis 任务（内部）
  → Worker 检查回答实际看过哪些文献和证据
  → 生成 AnalysisResult 和 FeedbackCase
  → 用户确认问题、证据和数据用途
  → 用户提交是否准入的审核决定
  → 用户选择用途并冻结快照
  → 下载 evaluation / sft / preference JSONL
```

| 顺序 | 操作者 | 发生的事情 | 下一步消费的对象 |
| --- | --- | --- | --- |
| 1 | 研究者 | 正常聊天并点踩 | `ChatMessageFeedback` |
| 2 | 系统 | 将反馈变成待分析事件 | `AnalysisJob` |
| 3 | Worker | 读取会话、模型输入、工具结果和 Source | `AnalysisResult`、`EvidenceCoverage` |
| 4 | 系统 | 把反馈、回答和分析结果合成待处理案例 | `FeedbackCase` |
| 5 | 用户 | 确认问题类型、缺口、目标和证据 | `Annotation` |
| 6 | 用户 | 接受、拒绝、标记依据不足或撤回 | `ReviewDecision` |
| 7 | 用户 | 指定 `dataset_type` 和 train/eval 分区 | `DatasetSnapshot` |
| 8 | 离线工具 | 按快照类型转换并评测/训练 | JSONL 和实验报告 |

用户不需要先打开模型调用详情，才能完成第 5 步。标注界面首先展示：指定文献、实际检查的文献、使用的 Source、未覆盖的材料、回答主张及其支持关系。内部 `ChatModelCall.request` 只在需要解释“为什么漏看”时，在当前 Collection 的访问范围内按需查看。

## 2. 对象与状态

```text
ChatMessageFeedback
  → AnalysisJob
  → AnalysisResult + EvidenceCoverage
  → FeedbackCase
  → Annotation
  → ReviewDecision
  → DatasetSnapshot
```

这些对象的含义不同：

| 对象 | 作用 | 能否直接进入训练 |
| --- | --- | --- |
| `ChatMessageFeedback` | 用户认为回答有用或有问题的信号 | 不能 |
| `AnalysisJob` | 调度一次 AI 分析 | 不能 |
| `AnalysisResult` | AI 对问题类型和证据缺口的候选判断 | 不能 |
| `EvidenceCoverage` | 记录请求范围、实际检查的 Source、遗漏和主张支持 | 不能 |
| `FeedbackCase` | 用户要处理的一整组上下文 | 不能 |
| `Annotation` | 人工确认问题、目标、证据和数据用途 | 经过审核后才有资格 |
| `ReviewDecision` | 对某个标注摘要作出准入决定 | 决定能否进入指定数据集 |
| `DatasetSnapshot` | 固定某一种用途的一批数据 | 是导出和实验的依据 |

案例状态表示处理进度：

```text
detected
  → analyzing
  → needs_annotation
  → ready_for_review
  → accepted / rejected / insufficient / withdrawn
```

`failed` 只表示技术执行失败，应作为任务或分析结果的错误状态；来源不足、答案不正确和人工拒绝不能都写成 `failed`。

## 3. 访问范围

当前验证阶段不建立 RBAC，也不区分标注、审核、数据集管理等角色。任何已登录且能访问当前 Collection 的用户，都可以查看案例、保存标注、提交审核决定、创建数据集快照和下载数据；同一个用户可以连续完成这些动作。现有登录和 Collection 访问校验仍然适用，本阶段不新增 allowlist 或动作级权限。

所有工作台接口都按当前会话用户和 `collection_id` 做服务端范围校验。请求体不能伪造另一个用户的所有者或操作记录；调用 ID 本身也不能代替资源范围校验。

### 用户操作与内部 ID

用户不在界面中输入或复制业务 ID。用户操作回答上的赞、踩、原因和评论，也操作论文、Source 原文、回答主张、标签和修正内容。前端从当前页面和选中对象中取得 ID，再自动组装 API 请求。

| 界面中的操作 | 人看到的内容 | 前端自动携带的字段 |
| --- | --- | --- |
| 打开一个案例 | 问题摘要、回答摘要、反馈原因、论文标题 | `case_id` |
| 在当前 Collection 筛选 | Collection 名称 | `collection_id` |
| 查看被要求检查的论文 | 论文标题、作者、文档状态 | `document_id` |
| 选中支持证据 | 论文标题、页码/章节、原文摘录 | `source_ref` |
| 指出漏读内容 | 论文标题、表格/图注/章节定位 | `document_id + locator` |
| 保存刚才看到的标注 | 页面无额外操作 | `expected_digest` |
| 选择案例进入数据集 | 案例标题和审核状态 | `case_id + annotation_digest` |

这些 ID 是接口保证引用稳定、校验并发和追溯来源所必需的技术字段，不是产品要求用户理解的领域术语。页面可以在 URL 中使用 `case_id` 定位资源，但用户通过点击案例进入页面，不手工构造 URL。

## 4. 通用约定

- 基础路径：`/api/v1`。
- 鉴权：沿用 Lens 登录会话；用户身份由服务端会话确定。
- 请求与响应：JSON；时间使用 ISO-8601 字符串；业务 ID 使用字符串。
- 列表分页：`limit` 默认 50，范围 1..200；`offset` 默认 0。
- 写入幂等：反馈分析任务使用 `idempotency_key`；标注和审核使用 `expected_digest` 防止覆盖别人刚保存的版本。
- 用户通过已有聊天/反馈接口和工作台接口操作；任务 Worker 只在后台运行，不提供面向用户的轮询接口。

错误统一包含可处理的 `code`：

```json
{
  "detail": {
    "code": "feedback_case_stale",
    "message": "The case changed after it was opened."
  }
}
```

常见状态码：`401` 未登录，`403` 当前用户无权访问该 Collection 或资源，`404` 不存在或无权访问，`409` 版本/状态冲突，`422` 字段或领域校验失败，`503` 分析服务暂不可用。

## 5. 第一步：正常反馈

这是当前已经存在的产品接口。它不要求用户理解训练系统。

### 保存或撤回点赞/点踩

- **URL**：`PUT /api/v1/chat-sessions/{session_id}/messages/{message_id}/feedback`
- **调用者**：已登录的会话所有者
- **作用**：保存用户对一条助手回答的有用性判断。

请求：

```json
{
  "rating": "not_helpful",
  "reason": "incorrect",
  "comment": "B 的预热信息在图注中，不能说没有预热。"
}
```

`rating` 为 `helpful`、`not_helpful` 或 `null`（撤回）。这次请求成功后，系统可以创建一个内部 `feedback_analysis` 任务，但不会直接创建已审核案例，也不会直接进入训练集。

## 6. 第二步：后台分析任务（内部）

反馈接口返回后，应用在同一业务范围内创建：

```text
AnalysisJob
job_type = feedback_analysis
payload = {"payload_version": 1, "feedback_id": "feedback_123"}
```

任务表只负责调度。Worker 根据 `job_type` 读取 payload，再从 `feedback_id` 反查权威的消息、会话、模型调用、工具结果和 Source。

Worker 流程：

```text
pending
  → 校验反馈仍然有效
  → 读取完整上下文
  → 检查请求范围和实际 Source 覆盖
  → 调用分析模型
  → 校验输出 JSON
  → 保存 AnalysisResult
  → 标记 succeeded 或 failed
```

分析输出示例：

```json
{
  "message_id": "answer_123",
  "problem_type": "source_missing",
  "confidence": 0.87,
  "requested_scope": ["document_a", "document_b", "document_c"],
  "inspected_sources": ["source_ref_a1", "source_ref_c2"],
  "omitted_candidates": ["document_b:figure_3_caption"],
  "claim_support": [],
  "gaps": ["document_b 的图注未读取"],
  "suggested_target": null,
  "needs_human_review": true
}
```

AI 不能通过这一步修改 Chat、宣布回答错误或批准训练数据。若 Worker 失败，任务标记 `failed` 并保留错误码；人工重试时创建新任务或显式将原任务重新置为 `pending`。

## 7. 第三步：案例工作台

### 读取待处理案例

- **列表**：`GET /api/v1/feedback-cases`
- **详情**：`GET /api/v1/feedback-cases/{case_id}`
- **调用者**：已登录且能访问对应 Collection 的用户
- **筛选**：`collection_id`、`status`、`problem_type`、`needs_human_review`、`limit`、`offset`。

列表只返回摘要：

```json
{
  "items": [
    {
      "case_id": "case_123",
      "status": "needs_annotation",
      "collection_id": "col_materials",
      "anchor_message_id": "answer_123",
      "question_preview": "比较文献 A、B、C 中预热温度的影响。",
      "answer_preview": "文献 B 没有预热。",
      "document_titles": ["文献 A", "文献 B", "文献 C"],
      "problem_type": "source_missing",
      "confidence": 0.87,
      "needs_human_review": true,
      "created_at": "2026-09-24T10:00:00Z"
    }
  ],
  "limit": 50,
  "offset": 0
}
```

详情返回用户完成判断所需的用户可理解内容。每个可选文档和 Source 同时带内部 ID 与显示字段，前端显示标题、位置和摘录，把 ID 留在组件状态中：

```json
{
  "case_id": "case_123",
  "collection_id": "col_materials",
  "session_id": "session_123",
  "status": "needs_annotation",
  "source_signals": ["feedback_123"],
  "question": "比较文献 A、B、C 中预热温度的影响。",
  "answer": "文献 B 没有预热。",
  "requested_scope": [
    {"document_id": "document_a", "title": "文献 A", "inspection_status": "inspected"},
    {"document_id": "document_b", "title": "文献 B", "inspection_status": "omitted"},
    {"document_id": "document_c", "title": "文献 C", "inspection_status": "inspected"}
  ],
  "inspected_sources": [
    {
      "source_ref": "source_ref_a1",
      "document_id": "document_a",
      "document_title": "文献 A",
      "locator_label": "Results，第 6 页",
      "quote": "..."
    }
  ],
  "omitted_candidates": [
    {
      "document_id": "document_b",
      "document_title": "文献 B",
      "locator": "figure_3_caption",
      "locator_label": "图 3 图注",
      "reason": "not_read"
    }
  ],
  "claim_support": [],
  "gaps": ["document_b 的图注未读取"],
  "analysis": {
    "problem_type": "source_missing",
    "confidence": 0.87,
    "suggested_target": null
  },
  "annotation": null,
  "current_annotation_digest": null
}
```

这就是工作台的主入口。界面按“原问题与回答 → 要求检查的论文 → 已检查证据 → 可能漏读的内容 → AI 建议”展示。用户点击论文或原文完成核对，不操作 `case_id`、`document_id` 或 `source_ref`。必要时详情可以在当前 Collection 访问范围内提供单独的内部审计入口，但不应默认返回完整模型请求。

## 8. 第四步：人工标注和审核

### 保存人工标注

- **URL**：`PATCH /api/v1/feedback-cases/{case_id}/annotation`
- **调用者**：已登录且能访问对应 Collection 的用户
- **前置条件**：案例状态为 `needs_annotation`，且用户有 Collection 权限。

请求：

```json
{
  "expected_digest": null,
  "problem_type": "source_missing",
  "severity": "high",
  "target": null,
  "support_source_refs": ["source_ref_b3"],
  "dataset_uses": ["evaluation"],
  "reason": "图注显示 B 有预热信息，原回答漏读该来源。"
}
```

界面上，用户实际完成的是：选择“来源遗漏”、选择严重程度、点击文献 B 的图 3 图注作为支持证据、填写判断理由，并勾选“可用于评测”。前端把所选原文片段转换为 `support_source_refs`；`expected_digest` 来自案例详情响应并在保存时自动回传。用户不填写这两个字段。

`target` 为空是合法的：这个案例可以用于评测“是否发现证据缺口”，但不能申请 `sft`。申请 `sft` 必须有明确 target、支持 Source 和训练授权；申请 `preference` 必须再有同一输入下的 chosen/rejected。

成功返回新的 `annotation_digest` 和 `status=ready_for_review`。如果 `expected_digest` 与当前版本不一致，返回 409，客户端必须重新读取详情后再保存。

### 提交审核决定

- **URL**：`POST /api/v1/feedback-cases/{case_id}/review`
- **调用者**：已登录且能访问对应 Collection 的用户

请求：

```json
{
  "expected_annotation_digest": "sha256:annotation-v1",
  "decision": "accept",
  "dataset_uses": ["evaluation"],
  "reason": "来源支持该标注，且问题范围和遗漏位置清楚。"
}
```

`decision` 为 `accept`、`reject`、`insufficient` 或 `withdraw`。审核通过只针对列出的 `dataset_uses`；接受为评测数据不等于接受为 SFT 数据。审核记录追加保存，不能覆盖旧记录。标注发生变化后，旧 digest 自动失效。

用户在界面中查看论文标题、选中的原文、标注内容和数据用途，然后点击“接受”“拒绝”“依据不足”或“撤回”。前端自动提交当前 `annotation_digest`；用户不输入摘要或 ID。

## 9. 第五步：按用途冻结和导出

一个数据集快照只能有一种 `dataset_type`：

| 类型 | 最低准入条件 | 导出行 |
| --- | --- | --- |
| `evaluation` | 有问题判断、输入范围和证据/评测标准；target 可为空 | `input`、`reference`、`evidence`、`criteria` |
| `sft` | 有明确 target、支持 Source、训练授权 | `messages`、`target`、`source_refs` |
| `preference` | 同一 input 下有 chosen 和 rejected | `prompt`、`chosen`、`rejected`、比较依据 |

### 冻结快照

- **URL**：`POST /api/v1/dataset-snapshots`
- **调用者**：已登录且能访问对应 Collection 的用户

请求：

```json
{
  "collection_id": "col_materials",
  "dataset_type": "evaluation",
  "items": [
    {"case_id": "case_123", "split": "eval"}
  ],
  "paper_families": {
    "document_a": "family_a",
    "document_b": "family_b",
    "document_c": "family_c"
  }
}
```

用户在界面中勾选已审核案例、选择数据集类型和 train/eval 分区。`case_id` 和 Collection ID 由前端根据当前工作区自动携带。若系统缺少论文家族映射，界面让用户按论文标题和版本确认分组，再由前端提交对应 ID；用户不手工填写 JSON。

服务端逐条检查：

1. 案例和审核属于当前用户可访问的 Collection；
2. 当前 annotation digest 与审核记录一致；
3. 案例满足指定 `dataset_type` 的准入条件；
4. train/eval 不共享论文家族或会话树；
5. 不合格项进入 `exclusions`，不静默丢弃。

返回 `dataset_id`、`dataset_type`、`manifest_digest`、`row_count`、`excluded_count` 和完整 provenance。快照创建后不随案例变化而修改。

### 查询快照

- **列表**：`GET /api/v1/dataset-snapshots?collection_id=...&dataset_type=evaluation`
- **详情**：`GET /api/v1/dataset-snapshots/{dataset_id}`

详情必须显示：

```text
dataset_type
rows / exclusions
manifest_digest
每行的 case_id、annotation_digest、review_id、Source refs、split
```

### 下载对应 JSONL

- **URL**：`GET /api/v1/dataset-snapshots/{dataset_id}/jsonl`
- **成功**：200，`application/x-ndjson`。

根据快照类型输出不同记录：

```json
{"record_type":"evaluation","input":"...","reference":"...","evidence":["source_ref_b3"],"criteria":["不能把未读取信息当成事实"]}
```

```json
{"record_type":"sft","messages":[{"role":"user","content":"..."}],"target":"...","source_refs":["source_ref_b3"]}
```

```json
{"record_type":"preference","prompt":[{"role":"user","content":"..."}],"chosen":"...","rejected":"...","source_refs":["source_ref_b3"]}
```

同一个案例可以分别创建三个不同类型的快照，但每个快照内部只能有一种格式。导出转换不能补写事实或重新判断来源；不满足格式要求的项必须进入排除报告。

## 10. 离线评测和训练

P6 不提供在线 HTTP 接口。离线工具读取已冻结的快照：

```text
evaluation snapshot → 基线模型评测 → 改进模型评测 → 对比报告
sft snapshot        → 训练前检查 → 训练 → 同一 eval 集评测
preference snapshot → 偏好训练/偏好评测
```

实验报告必须记录 `dataset_id`、`dataset_type`、`manifest_digest`、模型 revision、数据分区、Source 和评测结果。训练失败或模型不可用时报告 `not_run`，不能把导出成功当成模型改进。

## 11. 内部审计接口（不属于用户主流程）

历史 P1 接口如下，仅供工程或受授权的案例诊断使用：

```text
GET /api/v1/chat-sessions/{session_id}/model-calls
GET /api/v1/chat-sessions/{session_id}/model-calls/{call_id}
```

它们回答“模型实际收到了什么”，不能回答“模型是否正确理解了论文”。用户主流程应依赖 `FeedbackCase` 的 `EvidenceCoverage`，不是直接浏览这些调用记录。

历史 P2 的：

```text
POST /api/v1/chat-sessions/{session_id}/correction-cases
```

只适合手动把“原回答—用户质疑—修正回答”三条消息连起来。新的分析流程由 Worker 生成 `FeedbackCase` 候选，用户不需要手动填写这些 ID。

## 12. 最小实现顺序

验证阶段按下面顺序实现，每一步都有可观察结果：

1. 保留既有反馈接口，反馈保存后创建 `feedback_analysis` 任务。
2. Worker 读取反馈关联的回答、Source 和工具轨迹，生成 `EvidenceCoverage` 和 `AnalysisResult`。
3. 提供案例列表/详情，让用户能看到“看了什么、漏了什么、主张是否有依据”。
4. 提供标注保存和审核接口，先只允许 `evaluation` 用途。
5. 冻结并下载 evaluation JSONL，验证同一快照可重建。
6. 验证闭环后，再增加 SFT、preference 和内部模型调用审计界面。

验收标准是：研究者的一次真实点踩能在工作台形成可解释案例；用户无需阅读 prompt 就能判断证据覆盖；审核后的快照能导出正确类型的数据；原始聊天、Source 和历史快照不被改写。
