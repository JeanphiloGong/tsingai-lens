# Lens 反馈分析工作台

本目录集中管理反馈分析工作台的领域设计合同和生产实现教程。设计合同描述系统应该表达什么，`tutorial/` 描述如何在 Lens 生产代码中逐个版本实现和验证。

```text
ChatMessageFeedback
  -> AnalysisJob
  -> AnalysisResult + EvidenceCoverage
  -> FeedbackCase
  -> Annotation
  -> ReviewDecision
  -> DatasetSnapshot
  -> evaluation / sft / preference JSONL
```

## 设计合同

- [API 设计](api-design.md)：从用户反馈到快照导出的完整接口流程。
- [核心模型与流转](core-models-and-flow.md)：事实、信号、分析、整理和发布层的责任边界。
- [数据库设计](database-design.md)：任务、案例、标注、审核和快照的字段、约束与索引。

## 生产教程

[进入 P1–P6 教程](tutorial/README.md)

教程包含生产文件、调用方、迁移、失败路径、测试和逐版本检查点。教程与生产代码现在位于同一个仓库；每个 P 版本的实现提交和验证记录以本目录为准。

## 共同边界

用户操作回答、论文、Source、问题类型、修正目标和数据用途。业务 ID 和并发 digest 由页面自动携带，用户不需要输入。当前验证阶段不建立 RBAC，能访问 Collection 的登录用户共享查看、标注、审核、创建快照和下载数据的能力。

AI 分析只产生候选意见，不能修改 Chat、宣布回答错误或批准训练数据。人工标注确认问题、目标和证据，审核决定确认数据用途的准入，快照固定当时的内容。

本轨道与旧 Agent 工具循环和权限教程分开；它不使用旧 `ChatCorrectionCase` 或 `objective_analyses.payload` 作为领域合同。Paper Experiment V0–V9 可以与 P1–P4 并行准备，最终生产接入要在 V9 后重新运行共享 Source/Evidence 合同的集成检查。
