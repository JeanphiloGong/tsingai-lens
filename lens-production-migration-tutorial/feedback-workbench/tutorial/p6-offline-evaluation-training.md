# P6：离线评测与训练

**前置**：P5 已冻结带 manifest 和 digest 的数据集快照。P5 的候选整理能力不是训练脚本的隐式输入。

**本版结果**：离线工具读取固定快照，先在同一留出集上建立基线，再执行有限训练或偏好实验，最后重新加载权重并生成可审计报告。在线 Chat、部署配置和生产模型都不在本版范围内。

## 1. 离线入口

在生产仓库的独立评测目录新增：

```text
backend/scripts/evaluation/feedback_dataset/prepare.py
backend/scripts/evaluation/feedback_dataset/experiment.py
backend/scripts/evaluation/feedback_dataset/README.md
```

`prepare.py` 读取 `DatasetSnapshot` manifest，校验快照 digest、dataset_type、分区、Source provenance、论文家族和会话树隔离，再生成只读实验目录。环境依赖放在独立 venv/uv 环境，不修改在线 pyproject、Docker 或 workflow。

## 2. 数据合同

- evaluation 使用 `input/reference/evidence/criteria`，报告问题类型和证据覆盖。
- sft 保留实际 request、工具观察和审核 target；标签 token 参与 loss，prompt 和上下文 token 使用 `-100` mask。
- preference 要求相同 input 的 chosen/rejected，记录比较依据和来源。
- 上下文超限直接报错并写入排除报告，不能静默截断 Source 或目标。
- 任何训练/评测行都带 snapshot digest、revision、seed 和来源摘要。

## 3. 实验步骤

```text
读取冻结快照
  -> 校验 manifest 和分区
  -> 固定 tokenizer/template
  -> 运行基线评测
  -> 有限训练或偏好实验
  -> 使用同一留出集评测
  -> 保存权重、配置和报告
  -> 重载权重并复跑一个确定性样例
```

报告必须区分协议执行成功和科学质量改善。没有模型、GPU 或授权环境时记录 `not_run`，不能把环境缺失标成通过。

## 4. 验收

- train/eval 无论文家族、会话树或同一案例泄漏。
- prompt/target mask、overflow、空分区和 malformed JSON 都有明确错误。
- 基线和训练后使用同一留出集，报告能回链 snapshot、annotation 和 Source digest。
- 权重重载后结果与保存时的版本信息一致。
- 失败、未运行和质量下降均保留在报告中，不自动部署或更新在线模型。

P6 完成后，P1–P6 只证明了一条可追溯的数据整理和离线实验链路；是否把模型变更发布到生产，需要另行的产品、科学和发布决策。
