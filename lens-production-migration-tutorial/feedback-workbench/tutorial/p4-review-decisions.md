# P4：审核决定

**前置**：P3 已保存当前有效的 `Annotation`。

**本版结果**：用户针对某个标注摘要追加一个审核决定，系统根据最新决定投影案例状态。审核是历史记录，不是一个可随意覆盖的 `accepted` 布尔值。

## 决定模型

`ReviewDecision` 追加保存：

```text
decision_id
case_id
annotation_digest
decision = accept | reject | insufficient | withdraw
reason
created_by
created_at
```

`accept` 只表示当前标注可以申请其声明的数据用途，不表示科学真理，也不自动进入训练。`withdraw` 覆盖之前的准入决定；标注内容变化时旧 digest 自动失效。

## 1. 接口

```text
POST /api/v1/feedback-cases/{case_id}/review
GET  /api/v1/feedback-cases/{case_id}/review-decisions
```

请求示例：

```json
{
  "expected_annotation_digest": "sha256...",
  "decision": "accept",
  "reason": "Source 和问题范围已核对，可以用于 evaluation。"
}
```

服务端必须确认案例有当前 Annotation、digest 未过期、用户能访问 Collection，且决定与标注用途一致。没有标注、案例已撤回或 digest 不匹配时拒绝写入。

## 2. 状态投影

案例状态由历史决定重放得出：

```text
needs_annotation -> ready_for_review
ready_for_review -> accepted
ready_for_review -> rejected
ready_for_review -> insufficient
accepted -> withdrawn
```

数据库保留所有决定；列表可以返回当前投影，但不能删除或覆盖历史。`withdraw` 优先于更早的 `accept`，新的 Annotation 版本需要新的审核摘要。

当前验证阶段不建立审核角色。能访问 Collection 的登录用户都可以完成标注和审核；未来 RBAC 不能改变历史语义，只限制谁能执行动作。

## 3. 验收

- 没有 Annotation 不能审核。
- 旧 digest、跨案例引用和跨 Collection 请求返回 409/422。
- 撤回后旧接受记录仍可审计，但不再具有准入效果。
- 历史决定可以按时间顺序重放得到相同状态。
- 审核不会修改原始消息、反馈、模型调用或 Source。

P4 通过后，P5 才能按用途冻结 `DatasetSnapshot`。审核决定本身不是导出文件。
