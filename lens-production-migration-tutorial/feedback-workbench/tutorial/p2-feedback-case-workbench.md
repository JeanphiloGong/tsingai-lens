# P2：反馈案例工作台

**前置**：P1 已能从真实反馈生成带 `EvidenceCoverage` 的候选 `FeedbackCase`。

**本版结果**：用户打开工作台就能看到问题、回答、反馈、指定文献、实际检查的 Source、漏读候选、主张支持关系和 AI 建议。用户不需要阅读 prompt，也不手工输入任何业务 ID。

## 用户流程

```text
打开 Collection
  -> 筛选待处理案例
  -> 阅读问题和回答
  -> 对照指定文献、Source 和证据缺口
  -> 进入下一步人工标注
```

点踩仍然只是 `ChatMessageFeedback`。工作台不能把 AI 建议显示成已经确认的错误，也不能在打开详情时自动写入标注。

## 1. 列表和详情接口

新增：

```text
GET /api/v1/feedback-cases
GET /api/v1/feedback-cases/{case_id}
```

列表支持 `collection_id`、`status`、`problem_type`、`needs_human_review`、`limit` 和 `offset`，只返回摘要：

```json
{
  "items": [
    {
      "case_id": "case_123",
      "collection_id": "col_materials",
      "status": "needs_annotation",
      "anchor_message_id": "answer_123",
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

详情返回用户可理解的投影：`question`、`answer`、`requested_scope`、`inspected_sources`、`omitted_candidates`、`claim_support`、`gaps`、`analysis`、当前标注摘要和当前案例状态。每个文档和 Source 同时包含显示标题与内部引用值，前端显示标题和定位，不要求用户理解 ID。

完整 `ChatModelCall.request` 只在已有会话/Collection 访问范围内按需读取，不能成为工作台默认内容。

## 2. 服务端范围校验

在 `FeedbackCaseService` 中复用现有 Session 和 Collection 访问校验。列表先按用户可访问的 Collection 限定，再执行状态和类型筛选；详情不能仅凭 `case_id` 直接读取。跨 Collection、伪造会话或已删除资源返回既有资源错误，不泄露对象是否存在。

推荐落点：

```text
backend/application/feedback/feedback_case_service.py
backend/controllers/feedback_cases.py
backend/controllers/schemas/feedback_cases.py
frontend/src/routes/collections/[id]/feedback/
```

当前不建立标注员、审核员或数据集管理员角色。所有能访问 Collection 的登录用户共享这些动作，后续 RBAC 再单独加入。

## 3. 页面状态

页面必须明确区分：加载中、空列表、收集上下文中、需要标注、来源不足、技术失败和已处理。失败状态显示可重试或等待后台任务的含义，不把 `failed` 作为“回答错误”。

案例详情的主视图顺序是：问题和回答、反馈线索、指定文献、实际检查的 Source、漏读候选、主张支持、缺口、AI 建议。内部审计信息放在可展开的工程诊断区域。

## 4. 验收

- 不同 Collection 的用户不能读取案例。
- 列表分页不会把邻近案例当成当前案例。
- 空、分析中、来源不足和失败状态有稳定的 UI 表现。
- 刷新后详情仍由服务端重新读取，不能依赖前端临时对象。
- 工作台读取不会创建 Annotation、ReviewDecision 或 DatasetSnapshot。
- 用户只操作文献、Source、主张和标签；ID 由前端从当前选择自动携带。

P2 通过后，P3 才增加 `PATCH /annotation`。本版不复制 Chat 消息，也不恢复旧的纠错案例表。
