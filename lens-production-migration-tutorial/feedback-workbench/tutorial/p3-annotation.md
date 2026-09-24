# P3：人工标注

**前置**：P2 工作台已经能展示一个完整 `FeedbackCase`。

**本版结果**：用户对当前案例保存一版人工确认的标注，包含问题类型、严重程度、可选目标、支持 Source、数据用途和理由；服务端生成可重建的 `annotation_digest`。

## 标注的责任

AI 的 `problem_type`、`confidence` 和 `suggested_target` 只是候选。人工标注回答：

```text
问题到底是什么？
正确目标是否明确？
哪些 Source 支持这个判断？
这条案例允许申请哪些数据用途？
```

保存标注不修改原始 Chat、模型调用或用户反馈。

## 1. 数据模型

新增 `feedback_annotations`（具体迁移编号以当前生产 head 为准），至少包含：

```text
annotation_id
case_id
version
problem_type
severity
target (nullable)
support_source_refs[]
dataset_uses[] = evaluation | sft | preference
reason
annotation_digest
created_by
created_at
updated_at
```

标注引用现有案例和 Source，不复制原文。`target` 为空时不能申请 `sft`；`preference` 需要之后提供同一输入下的成对回答。

## 2. 写入接口

```text
PATCH /api/v1/feedback-cases/{case_id}/annotation
```

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

服务端重新校验 Collection 访问、Source 是否属于案例、问题类型枚举、用途准入和当前案例状态。客户端不能指定 `created_by` 或直接提交 digest。

`expected_digest` 不匹配返回 `409 feedback_case_stale`。相同内容重复提交应幂等；内容变化创建新版本并使旧审核摘要失效。

## 3. 页面与状态

标注表单沿用 P2 的用户可理解对象：问题类型使用显示文案，Source 使用论文标题、位置和摘录，目标使用回答编辑区域。页面不要求用户复制 `case_id` 或 `source_ref`。

保存成功后显示当前 digest 和更新时间；并发冲突要求重新读取案例，不自动覆盖另一人的标注。没有目标的案例可以继续进入评测候选，但不能伪装成监督训练样本。

## 4. 验收

- 标注后原始 Chat 和 `ChatModelCall` digest 不变。
- 越权案例、跨 Collection Source、无效枚举和不合法用途返回明确错误。
- 并发摘要冲突返回 409，不丢失已有标注。
- 没有 Annotation 的案例不能进入 P4 审核。
- 标注变更会使旧 `annotation_digest` 不再作为当前版本使用。

P3 不接受、不拒绝数据，也不创建快照；准入决定由 P4 的追加审核记录完成。
