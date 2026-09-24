# 教程验收状态

六篇生产实现教程已经整理到本目录：P1 `p1-feedback-analysis.md`，P2–P6 分别位于 `p2-feedback-case-workbench.md`、`p3-annotation.md`、`p4-review-decisions.md`、`p5-dataset-snapshots.md`、`p6-offline-evaluation-training.md`。版本边界、目标文件、调用方、迁移、失败路径和验收条件已写明；对应 Lens 修改和逐版重放仍需执行。

验证顺序是 P1 → P2 → P3 → P4 → P5 → P6。P5 是发布快照的硬门槛，P6 只读取冻结快照，不会修改在线服务。每版必须在隔离 Lens 副本应用正文改动并运行对应检查，未运行的环境不得标为通过。
