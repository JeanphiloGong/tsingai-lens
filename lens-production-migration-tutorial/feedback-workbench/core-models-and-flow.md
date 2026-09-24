# Lens Agent 反馈与训练：核心领域模型与流转

状态：P1–P6 生产模型，2026-09-24。P1、P2 已落地，P3–P6 是后续检查点；本文以“反馈信号 → 分析任务 → 案例 → 标注 → 审核 → 数据集”模型为准。旧对象名只用于映射历史迁移，不是新工作台合同。资料依据与阅读入口见 [README](README.md)。

## 一句话结论

用户真正需要知道的不是模型内部调用了几次，而是：模型有没有检查问题要求的文献，实际看到了哪些来源，哪些证据支持了回答，哪些相关材料没有被检查，以及结论为什么不可靠。系统内部仍需保存实际模型输入，作为这些判断的审计依据。

```text
研究问题/文献范围
  → 文献检查与来源覆盖
  → 模型回答与证据判断
  → 用户反馈
  → AI 分析案例
  → 人工标注/审核
  → 按用途冻结数据集

内部审计：实际模型调用、工具轨迹和请求快照
```

`ChatModelCall` 是内部技术执行记录，不是科研事实，也不是普通用户的工作对象。用户-facing 的核心是文献检查、证据覆盖和回答质量；`FeedbackCase`、`Annotation`、`ReviewDecision`、`DatasetSnapshot` 才组成数据整理流程。离线实验报告是实验产物，不需要为了对称而增加在线服务或数据库表。

## 用户问题与内部诊断的边界

一个研究者提出问题时，系统应围绕文献和证据回答：

```text
用户要求：比较文献 A、B、C 中某个变量的影响
系统检查：A/B/C 是否被纳入，实际读取了哪些章节/表格/图，哪些条件缺失
系统回答：结论、证据定位、不可比较原因和不确定性
```

如果用户认为回答不好，分析工具要判断的是：

| 用户可理解的诊断 | 需要使用的内部证据 |
| --- | --- |
| 没有看某篇指定文献 | 选定文献、检索事件、Source 阅读记录 |
| 看了文献但漏掉关键表格/图注 | Source 引用、工具结果、模型输入中的上下文 |
| 引用了来源但推论不成立 | 回答主张、来源片段、人工的证据判断 |
| 检索范围不足 | 查询条件、候选文献、未覆盖的范围 |
| 工具或解析失败 | 工具调用、错误码和恢复状态 |

`ChatModelCall.request` 只在后台诊断、工作台详情或工程审计中按当前 Collection 访问范围读取。用户不需要理解 prompt、token 或调用序列；界面应展示“检查了哪些文献和证据”，而不是把内部请求转嫁给用户。

## 先区分四个层次

这套系统容易把“任务”“案例”“样本”混成一个对象。它们承担的责任不同：

| 层次 | 核心问题 | 对象 | 是否代表人工结论 |
| --- | --- | --- | --- |
| 事实层 | 用户和模型实际做了什么 | `ChatSession`、`ChatMessage`、`ChatModelCall`、工具结果、Source | 否；这是可追溯事实 |
| 信号层 | 用户对结果表达了什么 | `FeedbackSignal`（现有 `ChatMessageFeedback`、后续纠正消息） | 否；这是待分析线索 |
| 分析层 | 系统认为可能发生了什么 | `AnalysisJob`、`AnalysisResult` | 否；这是 AI 假设 |
| 整理层 | 人要确认哪一个问题、目标和证据 | `FeedbackCase`、`Annotation`、`ReviewDecision` | 审核通过后才是数据准入决定 |
| 发布层 | 哪些已审核材料组成一个可复现数据集 | `DatasetSnapshot` | 是数据版本决定，不是科学真理 |

`AnalysisJob` 是调度对象，`AnalysisResult` 是模型输出，`FeedbackCase` 才是标注工作台中的核心工作对象。一个任务可以失败或重复运行，一个案例可以吸收多次分析结果，但不能因为任务成功就自动产生一个已审核样本。

## 推荐的核心模型

```text
事实层
ChatSession ── ChatMessage ── ChatModelCall
      │             │               │
      └────── Source / ToolResult ──┘
                    │
                    ▼
信号层          FeedbackSignal
                    │ 触发
                    ▼
分析层          AnalysisJob ──> AnalysisResult
                    │                 │
                    └──────────────┐  │ AI 建议
                                   ▼  ▼
整理层          FeedbackCase ── Annotation ── ReviewDecision
                    │                 │             │
                    └─────────────────┴─────────────┘
                                      │ accepted
                                      ▼
发布层          DatasetSnapshot ──> JSONL / Evaluation / Training
```

### `FeedbackSignal`：为什么这个案例值得看

它统一表示“需要分析的线索”，但不统一不同来源的语义：

| 信号来源 | 代表什么 | 不能直接推出什么 |
| --- | --- | --- |
| 点赞 | 用户认为回答有帮助 | 回答一定正确 |
| 点踩 | 用户认为回答没有帮助 | 正确答案是什么 |
| 点踩原因/评论 | 用户提供的失败线索 | 已完成科学核验 |
| 后续纠正消息 | 用户提出了可能的修改方向 | 用户目标一定正确 |
| 工具失败 | 技术路径出现异常 | 模型回答一定错误 |

现有 `ChatMessageFeedback` 是其中一种持久化来源。未来可以用一个读取投影把它们统一交给分析器，但不必立刻把现有表重命名或强行改成新的领域表。

### `EvidenceCoverage`：模型到底检查了什么

这是新流程中比“模型调用记录”更接近用户问题的分析对象。它不记录模型是否“聪明”，而记录一次回答相对于研究问题的覆盖情况：

```text
EvidenceCoverage
├── requested_scope[]       用户要求检查的文献/范围
├── inspected_sources[]     实际读取并可定位的 Source
├── omitted_candidates[]    相关但未检查或未能读取的材料
├── claim_support[]         回答主张到 Source 的支持关系
├── gaps[]                  缺失条件、不可比较或读取失败
└── coverage_status         complete | partial | failed | unknown
```

`inspected_sources` 只能来自真实工具结果或可验证的 Source 引用；模型声称“看过”不能单独构成覆盖证据。`coverage_status=complete` 也只表示在声明范围内完成检查，不表示结论正确。这个对象可以由 AI 初步整理，再由用户核对，是反馈分析和评测集的关键输入。

### `FeedbackCase`：用户处理的聚合

案例不是一条反馈，也不是一条 AI 输出。它是一个待处理的工作单元，至少包含：

```text
case_id
source_signal_ids[]
session_id / collection_id
anchor_message_id
context_snapshot
analysis_result_ids[]
annotation_id（可空）
review_state
```

案例负责回答“要处理哪一次回答以及它的完整上下文”。它可以由一个点踩创建，也可以把同一会话中相邻的点踩、纠正消息和工具失败合并进来。合并必须保留所有来源信号，不能只留下最后一条反馈。

案例状态表达整理进度，而不是答案质量：

```text
detected -> collecting_context -> needs_annotation -> ready_for_review
                                      │                    │
                                      ├── rejected          ├── accepted
                                      └── insufficient      └── withdrawn
```

`AnalysisResult` 的 `problem_type/confidence/suggested_evidence/suggested_target` 是候选意见；`Annotation` 才保存人工确认的 `problem_type`、严重程度、正确目标、证据和数据用途。没有 `Annotation` 的案例不能进入审核，更不能进入数据集。

### `Annotation` 与 `ReviewDecision`：两个不同的动作

人工标注回答“这是什么问题、正确目标是什么、依据在哪里”；审核决定回答“这份标注是否允许进入某种数据集”。验证阶段同一个用户可以连续完成这两个动作，因此它们是业务动作，不是当前已实现的角色划分。不能用一个 `status=accepted` 同时表示两者。

```text
FeedbackCase
  └── Annotation
       ├── labels
       ├── target（可空；只有明确修正时才填写）
       ├── support_source_refs[]
       ├── dataset_uses[] = evaluation | sft | preference
       └── annotation_digest

ReviewDecision（append-only）
  ├── annotation_digest
  ├── decision = accept | reject | insufficient | withdraw
  ├── reviewer_id（实际操作用户） / reason
  └── created_at
```

点踩但没有正确目标的案例可以标注为“事实错误/来源缺失”，进入评测集候选；它不能直接作为监督微调样本。只有有明确 target、来源和授权的标注，才有资格申请 `sft`。

### `DatasetSnapshot`：发布的是快照，不是动态查询

数据集不是“当前所有 accept 样本的查询结果”。冻结时必须复制行内容、标注摘要、审核摘要、Source 身份、分区和排除原因，并生成 manifest digest。之后反馈撤回或案例更新，不修改旧快照；新导出重新计算。

一个快照只服务一种数据用途，由 `dataset_type` 固定其导出合同：

| `dataset_type` | 允许进入的标注 | 导出内容 | 主要用途 |
| --- | --- | --- | --- |
| `evaluation` | 有问题分类、参考目标或评测标准即可；不要求可训练 target | `input`、`reference`、`evidence`、`criteria` | 比较模型是否改进 |
| `sft` | 必须有明确 target、支持来源和训练授权 | `messages`、`target`、来源元数据 | 监督微调 |
| `preference` | 必须有同一 input 下的 chosen/rejected 两个可比较回答 | `prompt`、`chosen`、`rejected`、比较依据 | 偏好训练 |

因此 `FeedbackCase` 不是“一问一答训练样本”。同一案例可以申请多个用途，但每个 `DatasetSnapshot` 只能有一个类型，并且分别通过对应审核规则。点踩案例通常可以先进入 `evaluation`；没有明确目标时不能进入 `sft`；没有成对答案时不能进入 `preference`。

内部统一保存一份案例和标注，导出时再做格式转换：

```text
FeedbackCase + Annotation + ReviewDecision
  ├── DatasetSnapshot(evaluation)  -> evaluation.jsonl
  ├── DatasetSnapshot(sft)         -> sft.jsonl
  └── DatasetSnapshot(preference)  -> preference.jsonl
```

导出转换不得重新推断事实、补写答案或丢弃来源；转换失败应产生排除原因，而不是输出一条格式看似完整的样本。

## 一次案例的生命周期

```text
用户反馈/纠正/工具异常
  → FeedbackSignal
  → AnalysisJob（异步调度）
  → AnalysisResult（AI 候选，不改变事实）
  → FeedbackCase（自动合并上下文）
  → Annotation（人工填写目标和证据）
  → ReviewDecision（审核准入）
  → DatasetSnapshot（冻结分区和排除报告）
  → 离线评测或训练
```

每一步的失败含义不同：Worker 失败是技术状态，来源不足是证据状态，人工拒绝是准入状态，三者不能共用一个 `failed`。

## 分析任务模型

AI 分析通过一个通用的 `AnalysisJob` 调度模型异步执行。任务表只保存调度生命周期；任务输入放在按 `job_type` 解释的版本化 `payload` 中，不把 `session_id`、`message_id`、`feedback_id` 等不同任务的字段都做成可空列。

```text
AnalysisJob
├── job_id、job_type、status
├── payload_version、payload
├── available_at、started_at、finished_at
├── result_id、error_code、idempotency_key
└── created_at
```

当前验证阶段只实现 `feedback_analysis`：

```json
{
  "payload_version": 1,
  "feedback_id": "feedback_123"
}
```

代码按任务类型拆分 Worker 边界，但部署分两个阶段。验证阶段先用一个进程承载多个独立 Handler；需要资源隔离或独立扩缩容时，再把它们拆成多个进程。无论哪种部署，调用者都不读取 `job_type`，也不自己选择处理器：

```text
当前验证部署：analysis-worker 进程
  └── FeedbackAnalysisWorker.run_once()
        → claim_next_feedback_analysis_job()
        → FeedbackAnalysisHandler.handle(job)

代码预留的同进程扩展：
  ├── ConversationCaseWorker.run_once()
  └── ToolFailureWorker.run_once()

后续独立部署：
feedback-analysis-worker       → FeedbackAnalysisWorker
conversation-case-worker      → ConversationCaseWorker
tool-failure-worker            → ToolFailureWorker
```

每个进程使用自己的应用服务和明确的 Repository 方法；Repository 内部可以复用一个私有的 `_claim_next_pending_job(job_type=...)`，但不把这个泛型方法暴露为业务调用入口。这样不同任务可以独立设置进程数量、模型、超时、优先级和发布节奏；一个任务类型阻塞时不会拖住其他类型。

一个进程承载多个 Worker 类，并不等于一个 Handler 处理所有类型；每个 Worker 仍只调用自己的 Repository 方法。只有在后续拆成独立进程时，进程边界才与任务类型一一对应。公共表不等于公共业务处理器；`job_type` 仍用于持久化和幂等校验，但不要求业务调用者做运行时分支。

选择拆分的条件是任务需要不同模型或硬件、执行时间差异导致互相阻塞、并发/优先级策略不同，或某类任务需要独立发布和故障隔离。没有这些压力时保持一个进程，减少部署、监控和并发领取的复杂度。

`FeedbackAnalysisHandler` 从 `feedback_id` 关联消息、会话、实际模型输入、工具结果和 Source，并把结构化结果写入分析结果表。未来的 `conversation_case_analysis` 可以使用 `session_id + anchor_message_id`，`tool_failure_analysis` 可以使用 `tool_call_id`；它们不需要现在就修改任务表结构。

`payload` 必须由对应 Handler 校验，不能只依赖 JSONB 可写入；`job_type`、`payload_version` 和 payload schema 必须成对定义。`payload` 只保存任务输入，AI 结果、提示摘要和候选状态放在结果对象中。任务失败先标记 `failed`，验证阶段由对应 Worker 的管理操作重新置为 `pending`，暂不引入自动重试计数和 Worker 锁字段。

## 一个完整场景

研究者比较三篇 LPBF Ti6Al4V 论文的材料条件，决定是否继续比较性能。一篇明确写 ELI，另两篇没有说明。Agent 把“未说明”写成“牌号不同”。

1. 系统在实际模型调用前保存最终请求，之后关联其产生的回答。
2. 研究者在正常会话中指出“未注明 ELI 不代表牌号不同”。此前点过踩也仍只是一条使用反馈。
3. Agent 按已有聊天流程补读材料段落；有资料时修正，没有资料时明确未知，读取失败时保留技术失败。
4. 用户定位原回答、质疑消息和修正回答。没有修正时只形成未解决案例。
5. 系统从修正回答的实际调用冻结输入和目标，并附上可核查的消息、工具结果与来源。
6. 用户查看这份固定材料，接受、拒绝、标记依据不足，或撤回之前的决定。
7. 用户选择已接受样本、论文家族及训练/评测分区。系统验证、排除不合格项，保存清单和排除原因。
8. 实验者使用固定数据集比较训练前后表现，研究者回看来源判断错误是否减少，再决定下一轮收集什么。

前提包括会话访问权、真实消息、可追溯的模型输入、Source 及训练使用授权。原方案没有把缺失输入、失败工具结果或用户满意度自动补成科学证据。

## 当前验证阶段只做什么

先验证最短闭环，不同时实现全部 P1–P6：

```text
已有 ChatMessageFeedback
  → FeedbackSignal 读取投影
  → feedback_analysis 的 AnalysisJob
  → AnalysisResult（含 EvidenceCoverage）
  → FeedbackCase
  → 人工 Annotation
```

这一阶段先不做正式训练、多用户协作隔离或多种任务类型。当前用户可以连续完成标注、审核和导出；这些动作不对应独立角色。`ChatModelCall` 作为内部审计记录，`EvidenceCoverage` 作为用户可理解的诊断结果；`DatasetSnapshot` 和 `ReviewDecision` 先作为模型边界设计，等案例分析和标注工作台验证有效后再实现。这样可以先回答“自动整理是否真的减少人工工作”，不会因为过早建设完整训练平台而掩盖核心流程问题。

## 模型总览

| 对象 | 身份与所有权 | 回答的问题 | 写入规则 |
| --- | --- | --- | --- |
| `ChatSession`、`ChatMessage` | 既有 Chat；受用户和 Collection 访问范围约束 | 谁在什么上下文中说了什么 | 继续由 Chat 保存轨迹 |
| `FeedbackSignal` / `ChatMessageFeedback` | 用户对消息的反馈、纠正或工具异常 | 为什么这条轨迹值得分析 | 可追加或撤回；不代表训练准入。现有 `ChatMessageFeedback` 是第一种信号来源 |
| `ChatModelCall` | `call_id`，归属一个会话 | 模型当时实际收到什么 | 先保存请求，再完成执行状态；重试使用新身份 |
| `AnalysisJob` | `job_id`，按 `job_type` 调度 | 何时分析哪种输入 | 技术执行状态；不代表分析结论 |
| `AnalysisResult` | `result_id`，归属任务 | AI 认为可能是什么问题 | 可重复生成；候选意见，不改变事实 |
| `FeedbackCase`（原方案的 `ChatCorrectionCase` 可视为一种实现） | `case_id`，归属会话/Collection | 哪个回答和哪些信号组成一个待处理案例 | 聚合上下文和分析结果，不复制原始聊天 |
| `Annotation` | `annotation_id`，归属案例 | 人工确认的问题、目标、证据和用途 | 新版本替换旧标注；旧审核因此失效 |
| `ReviewDecision`（原方案的 `ChatCorrectionReview`） | `review_id`、`annotation_digest + seq` | 哪个标注是否准入 | 追加历史，不覆盖旧决定 |
| `DatasetSnapshot`（原方案的 `ChatCorrectionDatasetManifest`） | `dataset_id`，归属 owner 和 Collection | 哪些材料以什么版本和分区进入实验 | 冻结 rows、exclusions、provenance |
| `ChatCorrectionCandidate` | `candidate_id`，归属 owner 和会话 | 模型建议检查哪段纠错 | 保存提议及执行证据；不能批准样本 |
| 离线实验产物 | 输出目录及数据/模型摘要 | 同一留出集上训练前后发生了什么 | 保存配置、结果、权重和重载检查 |

这些对象不发布或改写 `ResearchObjective`、`PaperExperiment`、`Finding`。科研结论的正式修订仍属于科研模型的写入流程。

## 内部模型调用审计记录

关键字段：`call_id`、`session_id`、`trigger_message_id`、`response_message_id`、`purpose`、`model`、`request`、`request_digest`、执行状态、起止时间、错误码、Provider 确认及 token 用量。它服务于 `EvidenceCoverage`、案例复核和工程排障，不直接面向普通用户。

| 内容 | 规则 |
| --- | --- |
| `request` | 最终交给 SDK 的 JSON 参数，包括实际 messages、tools、模型参数和流式选项；不能事后从完整历史拼装 |
| `purpose` | `decision`、`compaction`、`finalization`；压缩调用不等于用户可见答案 |
| `response_message_id` | 可空；没有最终回答的调用也有记录 |
| `provider_confirmed` | 表示有 Provider 响应证据；仅写入本地请求不代表远端执行成功 |
| 重试和历史 | 重试新建调用；旧消息没有记录时明确缺失，不伪造回填 |
| 敏感信息 | 不保存 API 密钥、认证头或环境变量；实际请求中的用户内容仍需受访问控制 |

原实现状态为 `recorded/provider_succeeded/provider_failed/response_invalid/cancelled`。进程崩溃可能留下 `recorded`；它不是科学上的“未知”，也不是成功。如何将孤立执行记录明确标为中断，是恢复策略的问题。

## 历史 P2 纠错案例与新的 `FeedbackCase`

```text
ChatCorrectionCase
├── original_message_id -> 原最终回答 -> original_model_call_id
├── feedback_message_id -> 后续用户质疑
├── corrected_message_id -> 修正最终回答 -> corrected_model_call_id
└── status、trace_digest
```

`feedback_message_id` 指一条 USER 消息，不是点赞表的 `feedback_id`。这两个名字容易混淆，重新设计时应明确区分。历史 `ChatCorrectionCase` 只适合描述“原回答—质疑—修正”这一种情况；新的 `FeedbackCase` 还要容纳“漏看文献、来源未覆盖、检索失败、工具失败、回答不完整”等没有明确修正回答的情况。

消息须属于同一真实会话，并满足“原最终回答在前、用户质疑居中、修正最终回答在后”。工具调用请求、临时流式文本、失败调用不能充当最终回答。原方案不强行连接不同分支的消息。

`linked` 表示三段引用齐备，`unresolved` 表示尚无修正；两者都不表达科学正确性。原实现只有创建和读取接口，没有完整的案例修订/版本接口，因此不能把“未解决案例随后原地补齐”宣称为已定义合同。

## 固定样本与审核

样本内容为 `case_id/session_id/collection_id/model_call_id/input/observations/target/source_refs`；`digest` 覆盖这些内容。

| 部分 | 含义 | 不能做的事 |
| --- | --- | --- |
| `input` | 修正回答所对应调用的实际 request | 把补读后的资料放回原错误回答的输入 |
| `observations` | 案例范围内消息、工具请求和工具结果的审核快照 | 把全部观察再次拼入训练 prompt，导致重复或目标泄漏 |
| `target` | 最终修正回答正文 | 用原错误答案作为监督目标 |
| `source_refs` | 选中原文及工具返回的来源引用 | 只有 URL 或摘要就声称原文语义已经核验 |
| `digest` | 绑定内容版本 | 将内容完整性校验等同于科学正确性 |

原实现的 observations 包含修正答案本身，因此它首先是审核与追溯材料。训练输入以 `input` 为准，不能将 observations 不加区分地追加进去。

审核记录含 `sample_digest`、`decision`、`reviewer_id`、`reason`、`support_message_ids`、`seq` 和时间。这里的用户字段只记录实际操作人，不表示一个独立的权限角色。状态查询是从当前材料与审核历史计算出的投影，不是样本的一份独立可写状态。

| 状态/决定 | 语义 | 可进入新数据集 |
| --- | --- | --- |
| `pending` | 尚无决定 | 否 |
| `accept` | 人工同意使用当前样本 | 仍须通过来源、分区等检查 |
| `reject` | 不接受该目标 | 否 |
| `insufficient` | 依据不足以判断 | 否 |
| `withdraw` | 撤回使用许可/之前的决定 | 否；原实现不再允许追加其他决定 |
| `stale` | 无法重建原材料或摘要不一致 | 否；不是人工选择项 |

非撤回决定需要支持消息；拒绝、依据不足和撤回需要原因。接受要求有目标及来源，但程序不能凭“非空来源”证明结论正确。历史实现只允许会话所有者提交审核；当前验证方案沿用 Collection 访问范围，同一个用户可以完成整个流程。

## 数据集与隔离边界

`Manifest` 拥有 `rows`、`exclusions` 和 `provenance`。行是快照内值，不另建可修改的数据集行服务。每行固定输入、目标、审核引用、来源、论文家族、会话树及 `split=train/eval`。

| 边界 | 原方案规则 |
| --- | --- |
| 内容版本 | 保存行摘要、provenance 摘要和清单摘要；同一内容可核对 |
| 论文家族 | 同一论文的不同文件/版本归入相同 `family_id`；原方案由用户提供映射 |
| 会话树 | 同一树不能同时出现在 train 和 eval |
| 排除 | 保留样本及原因，不能静默少导出若干行 |
| 撤回 | 新冻结排除；旧快照不自动变更，已下载文件也无法自动召回 |
| 空数据 | 空清单合法；训练要求 train、eval 都非空 |

应按实际输入所涉及的全部论文做隔离，而不只检查目标末尾引用。历史实现主要从样本 `source_refs` 提取论文，无法据此证明所有 prompt 中的论文都已覆盖；重新实施时必须补充输入来源覆盖校验。

## 候选与离线实验

候选状态为 `needs_review/ambiguous/no_candidate/invalid_proposal/provider_failed`。只有可选择的候选才进入同一套案例与样本校验；“选择候选”不写 `accept`。Provider 失败不能记成没有纠错。

P6 从 P4 数据文件开始：校验清单与分区、套用固定 tokenizer 模板、屏蔽 prompt labels 为 `-100`、只监督最终目标、先评测再训练再用同一留出集评测、保存并重载权重。超长上下文拒绝，不静默截断已审核材料。报告记录模型/tokenizer revision、seed、数据摘要、生成结果、loss 和来源。环境或授权缺失记录 `not_run`；loss 降低不等于科研正确率提高。

## 普通反馈如何接入：尚未完成的产品决策

用户已经点过赞/踩，应该成为后续整理的输入，不能要求再去界面里重复表达“这个回答不好”。但使用反馈和训练目标仍是不同信息。

| 用户已有操作 | 可直接复用的信息 | 仍缺少什么 |
| --- | --- | --- |
| 点赞 | 用户认为回答有用、消息身份、回答摘要 | 科学核验、训练授权及样本准入策略 |
| 点踩与原因 | 应优先检查的消息、错误类型线索 | 正确目标；没有修正时不能构造 SFT 样本 |
| 后续自然语言纠正 | 用户提出的修改意图 | 与原回答的可靠关联、模型实际输入和来源 |
| 纠正后继续使用 | 正常会话中的后续行为 | 不能据此默认已同意用于训练 |

后续建议的产品方向是从既有反馈自动汇集待检查材料，在专门的训练入口集中查看和导出。以下设计尚未定稿，本文不虚构对应表或 API：正反馈是否直接进入 SFT 候选、负反馈是否构造偏好对、自动准入规则、反馈更新/撤回的传播、多用户协作和数据隔离边界，以及“一键导出”的默认范围和排除说明。

## 版本与验收

| 版本 | 建立的对象/边界 | 最小验证场景 |
| --- | --- | --- |
| P1 | 实际调用记录 | 输入裁剪后仍可回看实收请求；失败不伪装成功 |
| P2 | 案例引用 | 错序、跨会话、工具请求拒绝；未修正保留 unresolved |
| P3 | 样本与追加审核 | 内容变化失效；撤回不被旧 accept 覆盖 |
| P4 | 数据集 | 缺来源和分区冲突有排除记录；历史快照可核对 |
| P5 | 候选 | 歧义、假 ID、Provider 失败区分；选择后仍待审核 |
| P6 | 离线实验 | 不泄漏目标；固定留出集比较；重载结果可检查 |

P1 → P2 → P3 → P4；P5 和 P6 都依赖 P4，P6 不必经过 P5。重新实施还必须验证普通反馈到整理入口的完整流程，不能只用这六个技术检查点替代产品验收。

## 教程与历史实现差异

P1 教程列有 `provider_request_id/response_metadata`；历史实现采用 `response_message_id/model/provider_confirmed/token 用量`。后两份设计文档采用历史实现的具体字段，避免合并出从未存在的结构。教程口语中的“accepted”在历史 API 中实际为 `accept`。

待处理的实现缺口包括：审核提交没有客户端 `expected_digest`，案例/样本缺少修订协议，来源语义核验与完整输入来源覆盖不足，以及反馈自动汇集与多用户协作边界未定义。这些是新实施前的设计工作，不应以恢复旧代码替代。
