# 前端同源 API 说明

本文档描述当前前端的浏览器公开合同，目标是让产品流程始终通过同源入口访问后端。

如果要看下一阶段 workspace UI 的页面结构、路由迁移和 fixture 策略，请同时参考
[`../src/routes/workspaces/lens-v1-interface-spec.md`](../src/routes/workspaces/lens-v1-interface-spec.md)。

## 当前合同

- 浏览器业务 API 走 `/api/v1/*`；身份查询直连同源 `/user-api/v1/*` 用户服务
- 文档与 OpenAPI 入口统一走 `/api/*`
- API 文档地址：`/api/docs`
- 前端共享请求封装统一从 `frontend/src/routes/_shared/api.ts` 发起请求，并用
  same-origin cookie 传递登录会话
- Lens JSON 保留 `{code,message,data,meta}`；身份拒绝/故障使用 HTTP 401/403/503，其他既有业务错误仍按原合同返回 HTTP 200；
  `requestJson` 返回 `data`，非 200 业务码抛出 `ApiError`。无结果时 `data` 为 `{}`。
- 使用 `isApiErrorCode` 判断六位业务码，使用 `getApiErrorReason` 读取 `data.code`；
  只有 `200301 + authentication_required` 清空登录状态和用户聊天缓存并跳转登录，不能按 HTTP 状态或错误文案猜测。
- 文件成功保留原始字节，下载前先识别 JSON 业务失败；普通 JSON 导出只保存 `data`。
  SSE 开始前先识别 JSON 拒绝，开始后继续处理既有 `error` 事件和取消／恢复。
- 完整业务码与响应定义以 [`backend/docs/specs/api.md`](../../backend/docs/specs/api.md) 为准。

## 产品主流程

- 首页工作空间列表：`GET /api/v1/workspaces`
  首页列表会结合响应中的当前文档状态显示工作空间阶段：全部文档为 `ready` 时显示“文档已准备”，
  不会因为历史数据的顶层 `status=uploaded` 而误显示为“待处理”；处理中或失败文档仍优先显示对应风险状态。
- 登录会话：`POST /user-api/v1/login`、`GET /user-api/v1/me`、`POST /user-api/v1/logout`。用户服务错误为顶层 `code`，限流时的 429 另有顶层 `retry_after` 与 `Retry-After` header；`api.ts` 在该明确路径按 HTTP 状态解析，业务响应继续解析 Lens envelope。
- 创建工作空间：`POST /api/v1/workspaces`
- 工作空间详情：`GET /api/v1/workspaces/{workspace_id}`
- 工作空间文档：`GET|POST /api/v1/workspaces/{workspace_id}/documents`
- 单篇文档准备：`POST /api/v1/workspaces/{workspace_id}/documents/{document_id}/preparation`
- 从明确选择的已就绪文档形成研究问题：`POST /api/v1/workspaces/{workspace_id}/objective-discovery`
- 研究目标工作区：`GET /api/v1/workspaces/{workspace_id}/objectives`、
  `GET|POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis`、
  `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings`、
  `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}`、
  `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence`、
  `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence`、
  `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence-map`、
  `GET|POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-plans`、
  `PATCH /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

  其中 Objective discovery 和 `POST .../analysis` 都必须发送明确的
  `document_ids`。`POST .../analysis` 是唯一的确认并分析命令：候选 Objective
  会在同一事务中固化为 `confirmed`，并冻结所选文档的
  `document_id + preparation_fingerprint` 后进入排队状态；已确认 Objective
  则直接创建或复用分析版本。Objective discovery 立即返回持久化的
  `objective_discovery` Pipeline Run；工作空间页通过 Pipeline Run 接口恢复和轮询状态，不能用页面本地
  loading 作为运行事实。分析命令返回后，Objective 列表在当前行展示并轮询进度，
  不自动跳转到详情页。

- 查询 Pipeline Run：`GET /api/v1/workspaces/{workspace_id}/pipeline-runs`、`GET /api/v1/pipeline-runs/{run_id}`
- 文档与 Source 核验：`GET /api/v1/workspaces/{workspace_id}/documents/profiles`、
  `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/profile`、
  `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/content`、
  `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/markdown`
- Workspace-bound Research Agent：`POST /api/v1/conversations`、
  `GET /api/v1/conversations/{conversation_id}`、
  `GET|POST /api/v1/conversations/{conversation_id}/messages`、
  `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/operations/{operation_id}/decision`

## 前端实现约束

- 不再允许浏览器手工设置 Base URL
- 遗留调试入口已从浏览器产品流程中退役
- `frontend/nginx.conf` 终止 HTTPS，将 `/api/` 代理到 `backend:8010`，
  将 `/user-api/` 去掉此前缀后代理到 `user-service:8097/`；HTTP 重定向到配置的公开 HTTPS 源。
  证书、运行配置与升级步骤见 [部署说明](../../deploy/README.md)。
- Workspace 只组织当前文档；Source、DocumentProfile、Paper Map 和就绪状态
  都属于单篇 Document。上传新文档或重试失败文档不会重新处理其他文档
- 同一 Document 同时最多一个准备 Pipeline Run，不同 Document 可以并发准备；上传在准备期间保持可用
- Objective discovery 和 analysis 只使用用户明确勾选的已就绪文档；处理中或失败文档
  不会阻塞已就绪子集的研究工作
- `/workspaces/{workspace_id}/objectives` 和
  `/workspaces/{workspace_id}/objectives/{objective_id}` 是 objective-first
  工作区入口；确认、分析、Findings 复核、数据集、Assistant focus 和实验方案都使用同一个
  `objective_id`，不维护第二套持久化目标身份
- 研究目标详情页默认进入已发布分析的结果总览：先看实验比较表和 Finding 列表；分析范围通过独立页签调整。
  点击 Finding 后通过 `finding_id` 进入单条 Finding 详情，返回操作清理该参数并回到总览，页面不会自动选中第一条 Finding。
- `/workspaces/{workspace_id}/assistant` 使用同源 `conversations` API，是绑定当前
  workspace 的 Research Agent 入口。普通对话不要求 capability；读取和草拟 capability
  自动执行并将结构化结果与最终回答分开显示；消息 POST 通过同一 URL 的
  `Accept: text/event-stream` 内容协商增量显示模型文本，并以服务端持久化后的完整 turn
  收尾；Core 写入停在持久化的精确参数审批点。
  Chat 是会话、消息、capability 轨迹和审批的唯一运行时权威，但不拥有 Objective、
  Evidence、Finding 或 Analysis 真值。Objective 链接仅指向 Core 的规范记录。
- 独立的 `/workspaces/{workspace_id}/comparisons` 页面及导航入口已移除。
  已发布 Findings 及跨论文证据比较统一在所属研究目标中审阅；不读取或重建旧
  comparison row、Evidence Card、Materials 或 Graph 投影
- `/workspaces/{workspace_id}/graph` 是次级的 Objective Evidence Map：用户先选择
  一个已有已发布 analysis 的 Objective，再按 `Objective -> Finding -> Evidence ->
Source -> Document` 回溯关系。页面只调用 Objective 的 `evidence-map` 接口；失败
  或排除论文只表示覆盖情况，不表示反对证据
- `/workspaces/{workspace_id}/documents/{document_id}` 只展示解析后的 Source
  内容，并通过 `source_ref` 与页码完成精确核验
- 报告结果不再是当前浏览器主流程；frontend 不再维护 reports API 客户端或工作区占位入口
- 遗留 workspace-wide Graph API/模型、Materials、Results、Evidence Cards、
  `research-view` 以及调试页
  `/upload`、`/index`、`/configs`、`/export` 已从前端路由中移除；
  新 Evidence Map 不兼容或恢复这些旧合同；产品入口统一收敛到 workspace
  route family 和 `/api/docs`

## 验收重点

- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、工作空间文档、文件上传、单篇任务轮询、明确文档选择、Objective、Published Findings、
  ObjectiveEvidence 与 Source 核验都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`

## 账号流程

匿名用户可访问 `/login`、`/register`、`/forgot-password`；已登录用户的页头右侧仅保留研究 Agent 和头像昵称，手机仅显示头像。点击头像昵称展开个人菜单，顶部显示昵称和邮箱，下方提供“账号设置”、外观、语言和退出。账号设置进入 `/account`。外观与语言在同一面板内切换选择视图，有返回按钮及当前选中标记；选择立即应用，返回主菜单并聚焦原入口，不刷新页面或清空草稿。点击外部、按 Escape、焦点离开或页面跳转时关闭菜单；Escape 将焦点返回头像。账号请求使用同源 `/user-api/v1/*`，复用 user-service 的账号能力，不依赖权限组。

注册、找回与本人改密都要求重复输入新密码；前端比较一致后只提交一次新密码，后端负责密码与邮箱证明规则。验证码保留前导零，仅与密码一起保存在表单内存；更换邮箱会丢弃旧挑战和验证码。重发倒计时来自服务端 `retry_after` / `Retry-After`，刷新后仍由后端限流。

注册页在输入框旁显示密码的最低长度与当前字符数、两次密码不一致和验证码的获取／格式提示，并通过 `aria-describedby` 关联输入框。未获取本页验证码、验证码不是 6 位数字、密码不足 12 个字符或确认密码未匹配时，创建按钮禁用；刷新后明确提示重新获取验证码。

注册成功引导登录。本人改密成功后清理登录和私有聊天缓存，并同步其他标签；失败保留有效登录状态。正在改密时，新登录等待改密响应，避免清除 Cookie 的响应覆盖新登录。找回本人账号成功时也清理其本地登录状态。密码、验证码和邮箱不写入跳转 URL。

## 人员与权限管理

个人菜单内的“管理后台”入口根据 `GET /user-api/v1/me/permissions` 的结果显示。具有 `users.manage` 时进入人员页，只有 `models.manage` 时进入模型管理页。人员、权限组、权限码页面分别位于 `/admin/users`、`/admin/groups`、`/admin/permissions`，都需要 `users.manage`。直接访问这些地址也经过共享权限门，分别显示查询中、403 或服务故障重试。会话过期时清理账号状态并进入登录。人员管理接口由 user-service 独立鉴权。

管理区使用统一侧栏。人员页以表格和详情面板展示已有账号，支持启停、授组和撤组；权限组页使用目录与详情分栏，详情切换组内权限和基本信息；权限码页使用目录表格与按需打开的编辑对话框。新建表单通过页面主按钮打开。仅展示当前接口支持的字段与总数，不提供搜索、类型筛选或分类数量。列表、关联列表与授权候选项分别分页；候选选择器按目录接口继续翻页，以已有稳定代码提交授权，不把第一页当成完整目录。代码不可改名，内置条目不可删除。禁用账号与删除自定义条目需确认；写入期间禁用相关控件，失败保留草稿并展示服务端拒绝，409 包括关联占用或最后管理员保护。不会提供管理员建号或替用户重置密码的表单。

权限只保存在当前账号的内存状态中。主体变化、退出和页面卸载会使旧请求失效；列表翻页和切换选择也会丢弃晚到响应。进入管理路由、窗口重新获得焦点以及管理写入完成后重新查询权限。其他管理员的变更在下一次查询时反映到界面，后端对每次操作实时校验。接口和字段以 [user-service HTTP 契约](../../user-service/docs/http-api.md) 为准。

## 模型管理

`/admin/models` 需要 `models.manage`。用同一次保存提交配置和 Key 的改动。省略 Key 保留已保存值，输入非空 Key 时替换，显式清除时提交 `null`。Key 草稿仅保留在当前页面内存，请求完成、离开编辑器或账号权限变化时清除。页面自动携带配置版本，冲突时提示重新读取。测试使用已保存的配置，启停由管理员单独操作。接口和字段以 [模型连接 HTTP 契约](../../backend/docs/specs/model-connections/api.md) 为准。
