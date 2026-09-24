# P5：数据集快照与 JSONL 导出

**前置**：P4 已有当前有效的 Annotation 和审核历史。

**本版结果**：用户选择一种数据用途，系统复制符合规则的案例、来源、分区和排除原因，冻结一个不可变 `DatasetSnapshot`，并下载可重建的 JSONL。

## 三种用途

一个快照只有一种 `dataset_type`：

| 类型 | 最低准入 | JSONL 形状 |
| --- | --- | --- |
| `evaluation` | 有问题分类、参考目标或评测标准 | `input`、`reference`、`evidence`、`criteria` |
| `sft` | 明确 target、支持来源和训练授权 | `messages`、`target`、来源元数据 |
| `preference` | 同一输入下可比较的 chosen/rejected | `prompt`、`chosen`、`rejected`、比较依据 |

没有明确 target 的案例可以进入 evaluation，不能进入 sft；没有成对回答的案例不能进入 preference。

## 1. 快照模型

`DatasetSnapshot` 保存：

```text
snapshot_id
collection_id
dataset_type
rows[]
manifest
provenance
exclusions[]
split
content_digest
created_by
created_at
```

快照复制当时的标注摘要、审核摘要、Source 身份、论文家族、会话树和分区。之后反馈撤回或案例更新，不修改旧快照；重新导出会得到新快照和新 digest。

## 2. 接口

```text
POST /api/v1/dataset-snapshots
GET  /api/v1/dataset-snapshots
GET  /api/v1/dataset-snapshots/{snapshot_id}
GET  /api/v1/dataset-snapshots/{snapshot_id}/jsonl
```

创建请求只表达用途、筛选范围和分区策略。服务端从当前可访问 Collection 重新读取案例和审核状态，不接受客户端直接提交训练行、owner 或来源证明。

详情返回 manifest、行数、digest 和 exclusions；下载响应的内容必须与 manifest digest 一致。空快照可以创建用于诊断，但不能交给训练脚本。

## 3. 隔离规则

- train 和 eval 不能共享论文家族或会话树。
- 失效、撤回、依据不足、未解决和缺来源项进入 exclusions，并保留稳定原因。
- 导出转换不得重新推断事实、补写目标或静默丢弃 Source。
- 快照是发布对象，不是“当前 accepted 行”的动态查询。

## 4. 验收

- 同一组 provenance 和规范化内容得到相同 digest。
- 三种类型分别执行准入校验，错误用途返回可理解的 422。
- 跨 Collection、跨论文家族和会话树泄漏会被拒绝。
- 下载后可用 manifest 重建行内容，篡改会被检测。
- 撤回源案例后旧快照仍可读取，新快照会排除该案例。

P5 不接在线训练平台、不自动消歧论文，也不修改 Chat。P6 只读取冻结快照。
