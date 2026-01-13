概述

本文件是项目级 AGENTS 规范模板，用于定义多智能体在技术项目中的协作方式与权限边界。
核心目标：负责人绝对主导、多智能体像真实团队协作、禁止自动改动代码逻辑。

一、核心原则
1) 文档可写，代码禁写
- AI 仅可写文档类文件（.md/.txt 等）。
- 任何代码或配置变更必须由负责人明确授权（WRITE_CODE），并指定范围。

2) 分层协作 + 代表制
- 个人层：每个 agent 维护 plan/log/inbox/outbox。
- 部门层：部门内讨论只在部门频道进行。
- 全局层：跨部门沟通由部门代表发起与汇总。
- 领导层：所有部门代表向最高负责人汇报。

3) 结果导向汇报
- 不需要逐行代码汇报。
- 汇报只包含：交付物、风险、下一步、所需支持。

二、组织架构与汇报链路
当前组织架构（可按需扩展）：
- human/gong（最高负责人）
  - ai/tech-lead/rep-01（技术负责人/DRI）
    - ai/backend/rep-01（后端代表）
    - ai/frontend/rep-01（前端代表）
  - ai/agent-orchestrator/01（AI 编排负责人/跨部门）

组织架构文件：coordination/org_chart.md

三、协作系统（agent-collab）
协作资料统一放在：
- 工作副本：agent-collab/
- 模板副本：agent-collab.template/

建议结构：
- agents/：角色计划与日志
- channels/：部门频道、全局频道、领导频道
- coordination/：requests/decisions/risks/roadmap/standups/org_chart
- templates/：新增角色或部门的模板（含 role/ 复制包）

四、新会话 = 新员工接入流程
1) 角色判断
- 接管旧角色：必须复用原 agent.id，不允许新建 ID。
- 负责新模块：创建新的唯一 agent.id。

2) 接管旧角色
- 复用原 agent.id 的 plan/log/inbox/outbox。
- 在 log 中写明“接管说明”，标注时间与职责范围。

3) 新建角色
- 选择唯一 ID（推荐 ai/<dept>/rep-01 或 ai/<dept>/<n>）。
- 从 templates/role/ 复制为 agents/<id>/。
- 替换文件内的 ID 与角色信息。
- 在 agents/<id>/ 下创建空的 AGENTS.md（由负责人后续注入角色规范）。
- 人类角色使用 agents/human/<name>/。
- 在部门频道公告加入。
- 如果是代表角色，必须在 global + leadership 频道公告。

五、沟通路径
- 一对一：agents/<id>/inbox.md 与 outbox.md
- 部门内：channels/dept-*.md
- 跨部门：channels/global.md（仅代表）
- 领导汇报：channels/leadership.md 或 agents/human/<owner>/inbox.md

六、记录与决策
- 决策：coordination/decisions.md
- 请求：coordination/requests.md
- 风险：coordination/risks.md
- 进度：coordination/standups.md
- 组织架构：coordination/org_chart.md
- 全部 append-only，不改写历史

七、权限边界
禁止 AI 自动执行：
- 修改任何源代码文件（.js/.ts/.py/.go/.java 等）
- 修改配置文件（.env、Dockerfile、CI、部署脚本）
- 自动 refactor、自动 patch、自动修 bug
- 执行带副作用的系统指令

八、交互规则
- 默认文档模式：只输出文本，不写文件。
- 若需求不明确，必须先确认是否允许写入。

九、可覆盖默认规则的指令
- WRITE_DOC：允许修改文档类文件
- WRITE_CODE：允许修改代码文件（需谨慎）
- APPLY_PATCH：仅应用用户提供的补丁
- GENERATE_CODE：只输出代码文本，不写文件
- 执行前必须声明“已进入特权模式”

十、模板使用说明
- 本文件用于生成项目内 AGENTS.md。
- 由负责人手动替换/裁剪后生效。
