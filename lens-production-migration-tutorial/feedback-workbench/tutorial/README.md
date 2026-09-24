# Lens 反馈分析工作台生产教程

本目录是统一生产迁移仓库中的反馈分析工作台轨道。它从 Lens 真实的 Chat、Source、Collection 访问和用户反馈开始，逐版建立：

```text
FeedbackSignal
  -> AnalysisJob
  -> AnalysisResult + EvidenceCoverage
  -> FeedbackCase
  -> Annotation
  -> ReviewDecision
  -> DatasetSnapshot
  -> evaluation / sft / preference JSONL
  -> 离线评测或训练
```

教程描述生产实现目标和可验证的增量。P1、P2 已在当前仓库完成并有独立提交；P3–P6 按同一检查点规则继续实现。教程正文、契约和代码共用本仓库的版本历史。

## 阅读顺序

| 版本 | 教程 | 可观察结果 | 前置 |
| --- | --- | --- | --- |
| P1 | [反馈分析任务闭环](p1-feedback-analysis.md) | 反馈创建幂等任务，Worker 形成候选案例 | 当前 Chat/Feedback/Source 基线 |
| P2 | [反馈案例工作台](p2-feedback-case-workbench.md) | 用户查看问题、回答、证据覆盖和漏读候选 | P1 |
| P3 | [人工标注](p3-annotation.md) | 保存带 digest 的人工标注 | P2 |
| P4 | [审核决定](p4-review-decisions.md) | 追加 accept/reject/insufficient/withdraw 历史 | P3 |
| P5 | [数据集快照与导出](p5-dataset-snapshots.md) | 冻结 evaluation/sft/preference JSONL | P4 |
| P6 | [离线评测与训练](p6-offline-evaluation-training.md) | 用固定快照完成基线和留出集对照 | P5 |

完整任务拆分、生产文件和验收门槛见[教程计划](production-tutorial-plan.md)。验证状态见[验收记录](verification.md)，版本压力见[版本阅读路径](version-history.md)。设计合同见[反馈工作台上级目录](../README.md)。

## 用户真正操作什么

用户操作的是回答、论文、原文片段、问题类型、修正目标和数据用途。`job_id`、`case_id`、`document_id`、`source_ref` 和并发 digest 由页面自动携带，用户不需要输入或理解这些 ID。当前验证阶段不建立 RBAC；任何已登录且能访问 Collection 的用户都可以查看、标注、审核、创建快照和下载数据。

AI 分析只产生候选意见。它不能修改 Chat、宣布回答错误或批准训练数据。人工标注确认问题、目标和证据，审核决定确认某种数据用途的准入，快照再把当时的内容固定下来。

## 与其他轨道的关系

本轨道与 Agent 工具循环和请求级权限说明分开。旧 A0–A5 说明模型工具调用和请求级权限；本轨道说明反馈如何成为可追溯案例和数据集。两者不共享旧的 `ChatCorrectionCase` 或 `objective_analyses.payload` 合同。

Paper Experiment V0–V9 可以与 P1–P4 并行准备。生产代码最终接入时，需要在 V9 后的共享 Source/Evidence 合同上重新运行 P1–P6 的集成检查。P5 需要稳定的 provenance 和分区规则，P6 只读取 P5 冻结的快照。

## 检查点

每个 P 版本都要有一个教程提交和一个 Lens 生产代码提交。检查点必须包含：

1. 上一版本的生产提交和工作区边界。
2. 一个可观察行为或明确不变量。
3. 成功、失败、越权和数据不足路径的验证记录。
4. 从研究者反馈到下一个可消费对象的完整链路。

教程提交不能被当作生产能力证明；未运行的 Provider、PostgreSQL 或浏览器检查必须标记为 `not_run`。
