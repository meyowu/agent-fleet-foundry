# Agent Fleet — 系统级开发路线与执行合同

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

日期：2026-09-07。状态：planned / not started。总体目标见 [系统 OKR](../../docs/NEXT_OKRS.zh-CN.md)。本文是八条主线、32 个工作包的总体执行合同；不是现在执行全部工作的授权。具体 package 的 Task Contract 在领取时冻结人员、写入范围、依赖版本、预算及测试 manifest；改变安全边界的 adapter/远程发布切片另写专项 ADR/ExecPlan，不以总体计划代替具体协议审查。

## Purpose and user-visible result

把当前已有安全内核的产品推进为可真实使用、可替换模型/Agent Harness、可观察、可集成和可发行的项目 Agent 组织运行时。Memory/自进化只是其中一条路线，不再作为其他功能的共同前置。

目标用户旅程（拟议）：用户从 GitHub 获得明确版本，运行 `fleet` 进入 Session，完成仓库 readiness 与显式模型配置；在一个 Session 提交需求、审查最小团队、批准确切动作、查看 Dashboard、获得 Patch/测试证据并选择 apply。不同职责可使用不同的已验收 Provider/Harness；之后用户可以显式连接 GitHub/MCP、管理知识，或选择远程 Sandbox。没有配置的集成保持关闭。

## Scope

### In scope

- S1：当前 OpenAI 实测及回归；Anthropic、Gemini Provider 逐家纵向接入。
- S2：readiness、Session 日常操作、自定义角色/默认模板、Adaptive Fleet 用户验收。
- S3：统一 Runtime conformance、OpenAI Agents SDK、混合 Harness、有限 streaming、LangGraph beta、Coding Harness 可行性。
- S4：安全/恢复合同、隔离依赖准备、权限解释、后续 Modal beta/Hosted 设计。
- S5：现有观察器增强；独立安全合同下的 Dashboard 操作入口。
- S6：MCP、GitHub 语义连接器及受审查示例。
- S7：项目 Memory、收益评估、人工组织改进、后续有限事实自动化。
- S8：离线/跨平台质量、安装升级、数据生命周期、准确文档与发行门禁。

### Out of scope

- 本次规划不授权业务实现、模型消费、Docker/远程任务、下载依赖、GitHub 写入或发行。
- 不一次创建所有抽象、注册占位 adapter、改造为自由群聊或由 SDK 接管 Fleet 调度。
- 不给任意第三方插件控制平面权限，不自动发现凭证、不默认开启全部 Provider/工具组合。
- 不指定许可证、具体模型型号、账户采购、未经估算的工期或发布日期。
- 多用户 SaaS、模型权重训练、插件市场、后台队列是总表中的后续专项，不在近期批次 A/B 偷渡。

## Current repository state

HEAD `3fb09711851b27b5276d7faddd50bc317e2536fb`；版本 0.1.0，Python 声明范围 `>=3.12,<3.15`。`docs/SESSION_FIRST_ACCEPTANCE.md` 记录此前 2283 默认通过/19 可选跳过、真实 Docker 15、安装 3、浏览器 17 项；这些不是本次重跑。live-provider 尚未执行，新版本 Linux 宿主/全部 Python 格子未验收。

代码路径以下无前缀时相对 `src/agent_fleet/`：

- `bootstrap.py::build_container` 仅注册 fake、PydanticAI 两个 Runtime，以及 fake/Docker/local-unsafe Sandbox；后两者不能等同隔离级别。
- `adapters/runtime/pydantic_ai.py::PydanticAIRuntimeAdapter` 已有 OpenAI Responses/Chat 实际构造和工具循环，固定官方端点；`pyproject.toml` 只有 `pydantic-ai-slim[openai]`。
- `domain/model_profiles.py::validate_profile_configuration` 的准入当前仅 fake/PydanticAI、OpenAI 前缀；`application/model_profiles.py`、`WorkflowEngine._runtime_configuration`、`GraphWorkflowExecution` 已按冻结角色 Profile 选择 Runtime。`tests/integration/test_model_profile_workflow.py` 已有 mixed runtime accounting 验证，不另造角色路由。
- `ports/runtime.py::RuntimeAdapter/RuntimeInvocationServices` 和 `application/runtime.py::RuntimeRegistry` 是项目拥有的替换边界。能力类型已有 streaming/checkpoint/resume，但现有 PydanticAI 未宣称实现；工作流恢复不等于原生 checkpoint。
- `cli/chat.py`、`cli/onboarding.py`、`application/conversations.py`、`session_review.py`、`plan_review.py` 已实现会话与独立审查状态机。`domain/role_templates.py` 和 `application/planning.py` 已支持受限自定义角色及五种策略。
- `application/bootstrap.py::BootstrapService`、`adapters/repository/profile.py::StaticRepositoryProfiler` 是仓库入场基础；内置 Canary 不证明业务仓库依赖就绪。
- `application/runtime_tools.py::GatewayRuntimeToolCatalog` → `ToolGateway` → `PermissionBroker` 拥有副作用；`adapters/sandbox/docker.py` 和 `application/resources.py` 拥有实际执行与资源生命周期。
- `application/dashboard.py`、`adapters/dashboard/http.py`、`adapters/persistence/dashboard.py` 提供只读观察，没有写 API。`application/evolution.py::OrganizationService` 提供人工 FleetPatch；无自动学习或 MCP/GitHub 产品连接器。

继续前须读 `AGENTS.md`、`.agent/PLANS.md`、PRODUCT_SPEC/ARCHITECTURE/SECURITY_MODEL/CONFIG_AND_SCHEMAS/IMPLEMENTATION_ROADMAP、最新验收及已完成的 Session-first ExecPlan。旧阶段快照不得覆盖当前实现证据。当前版本相关事实已做只读代码复查。

## Security impact

S1/S3 改 provider/harness transport 和秘密边界；S2/S5 改用户审查入口；S4 改执行与资源边界；S6 改外部网络/凭证/写入；S7 改长期不可信上下文；S8 改持久数据、分发和恢复。所有分支保持 `docs/SECURITY_MODEL.md` 的准确 ALLOW/DENY/REQUIRE_APPROVAL、repo 不授信、Verifier 不贡献修改、未知不重放、无弱 Sandbox fallback。

新 Provider 不是放开 base_url：显式身份/认证/端点、无 ambient key/proxy 路由、无 SDK 隐藏重试、最后发送/响应脱敏守卫。应用层与 domain 不接受 SDK 原始对象，worker 永远不接收模型/外部服务凭证。现有同进程可信 adapter 的安全边界不能夸大为能隔离恶意 Python 插件。

新 Harness 只能处理一个 Fleet 入场后的有界职责。SDK 原生 shell/files/network/MCP/hosted tools、内部无界 handoff、独立授权/恢复不能默认启用。安全合同不满足时不注册为可用；不得通过选择 local-unsafe 绕过。

Dashboard 观察 token 不能自动升级成写权；新的精确用户确认、短期写凭据、Origin/Host/CSRF 与单次 claim 单独设计。MCP 服务元数据不可信；发现/启动服务本身可有副作用，必须显式连接配置和授权，不能只守住后续 tool call。

数据删除/远程取消/发布均先显示确切对象与影响，活动引用和未知 owner 保留。任何资料、日志、导出、页面、模型流片段均不记录 secret 或私有思维链。

## Proposed design

三条可替换边界继续独立：

```text
Session / Dashboard（用户入口）
              ↓
Fleet 控制平面：Scope / Plan / Role / Review / Budget / Evidence
       ├─ Role Profile → RuntimeAdapter → 明确 Provider client
       └─ 工具请求 → ToolGateway → PermissionBroker
                             ├─ 文件 → Fleet 受限 workspace primitives
                             ├─ 命令 → SandboxProvider
                             └─ 外部语义动作 → MCP/GitHub connector
```

Provider/Harness/Sandbox 形成显式受支持组合矩阵；不给所有 Provider×Harness×Sandbox 笛卡尔组合自动兼容承诺。runtime/model/config/capability 版本在 Run 入场冻结，Profile 修改只影响未来任务。新的 capability 必须有真正行为实现和 conformance 证据；不支持的旧版本读取 required binding 时拒绝，不能忽略。

评估底座复用既有 [真实任务计划](2026-09-07-okr-01-real-task-baseline.md)。其 1.1/1.3/1.4 对应 S1.1，1.2 对应 S2.1，共用实现/记录/负责人，不建两个 readiness 或 Campaign 系统。它保持预加载离线环境；新的联网依赖准备由 S4.2 独立增加，不追溯扩大旧计划 scope。

每个新模块先纯合同与 fake/MockTransport，再持久化/拒绝路径，再公开入口，最后明确 opt-in 的真实验收。所有来源事件、attempt、模型请求、命令、Artifact、外部结果以确切 ID 关联。用户接受、verified completion、远端发布、知识收益是不同事件。

## Public contracts

以下均为拟议变更，当前不能当成现有 CLI/类型调用：

| 工作线 | 合同与兼容策略 |
| --- | --- |
| Provider | 在 adapter 内建立最小 Provider transport/factory 合同；扩展 ModelProfile 准入及 optional dependencies，不默认启用全部 SDK；原 profile/canonical bytes 不变 |
| Harness | 复用 RuntimeAdapter/Registry；登记实现版本、capability 与选择允许列表；只有用户配置可准入，repo preference 不能安装或授信 |
| Streaming | 新增有界 presentation 事件，带 Run/agent/request/sequence；schema 完整、secret 扫描后才接受工具结果；跨 chunk redaction 需缓冲，不能先流出后脱敏 |
| Readiness/准备 | 拟议 `fleet readiness`、PreparationPlan/Receipt；只读检查与 effectful prepare 明确分离，精确镜像/依赖/命令/网络阶段授权 |
| Session/roles | 拟议会话内模型/角色/任务选择入口，复用现有 service；角色模板只缩小权限，编辑沿 FleetPatch review，输入历史默认不落明文 |
| Dashboard | 保留现有 GET 观察 API；另定义 UserActionRequest、ReviewBinding 与一次性 action receipt，不能给现有 bearer token 直接新增写权限 |
| Connector | 拟议 ConnectorIdentity、CredentialBroker、ExternalActionReceipt；action 如 github.issue.read、github.pull_request.create，精确 repo/ref/content hash；MCP identity/schema/version 绑定 |
| 数据 | 拟议 BackupManifest/RetentionPreview/ExportReceipt；一致性数据库/Artifact 清单及安装身份，导出默认脱敏，不复制现有 trust 为新机器许可 |
| Memory | 复用 S7 三份细计划，独立 KnowledgeSnapshot/PromotionDecision/Policy actor；不是工具权限或组织强制规则 |

新增 schema/migration 按实际合并顺序分配，不预占冲突编号。CLI JSON envelope 和现有退出码不破坏；新 `unsupported`、`not_run`、`unknown` 解释不得伪装成功。实现任何网络/权限/恢复变更前更新对应规范及 ADR。

## Milestones

### Milestone A：真实可用 Alpha

先冻结 S1.1 Outcome/预算合同，再做 S2.1 readiness；S4.1/S8.1 是共同验收。补 S2.2 最小 Session 操作闭环。离线 plumbing 可先交付，真实任务需要另外获准的模型/凭证/预算和已准备镜像。

Acceptance：公开入口、真实 canary、24 任务/12 holdout（至少 9 通过）、3 cold-start、完整失败/usage/资源证据；缺 live 时标未验收，不阻止其他离线开发。没有 Memory/第二 Provider 也能交付范围准确的版本。

### Milestone B：可扩展 Beta

S1.2–1.4、S3.1–3.3、S2.3–2.4、S4.2–4.3、S5.1–5.2；数据生命周期 S8.2 可提前。顺序是一个 Provider/一个 Harness 垂直完成再增加下一个，不同时注册多个壳。

Acceptance：3 Provider、2 真实 Harness 的精确支持组合与独立 live 资格记录；Session 模板、network-off 业务执行、完整 Dashboard 观察；无秘密/审批/清理退化。若新 adapter 尚未通过，已验收组合仍可发行，新项明确 unavailable。

### Milestone C：工作流产品化

S3.4 LangGraph beta/可行性、S5.3–5.4 安全操作、S6 集成、S7.1–7.2 Memory、S8.2–8.4；彼此按下表具体依赖，不以“整批完成”作串行门禁。

Acceptance：MCP 和 GitHub 外部效果有独立授权/结果回读，UI/CLI 竞争只有一个赢家，Memory 不扩权，当前发行矩阵/数据恢复证据完整。S8.4 可随任何边界准确的已验收版本执行，不等自动学习成功。

### Milestone D：学习与远程扩展

S7.3–7.4 按子路线验证收益及有限自动化；S4.4 按独立远程合同引入 Modal/Hosted。后台队列/多用户/更多 Coding Harness 各自立项，不自动加入本轮。

Acceptance：进化和远程分别验收，不能互相借分；远端 unknown 保持 unknown、不盲重试，自动知识不能自动应用组织变更。未实现的 Hosted 或 Coding Harness 不注册占位命令。

## Detailed implementation steps

每行是一张可领取的工作包。路径新增处明确标为“拟新增”；实际领取时列出确切 writer 与 fresh verifier，不允许同一人只自评即宣称通过。

| ID | 依赖 | 具体实现与写入入口 | 可观察验收/证据 |
| --- | --- | --- | --- |
| S1.1 | 基线刷新；live 部分需 S2.1/S4.1 | 复用 `tests/live/test_provider_smoke.py`；按真实任务子计划新增 Outcome/Campaign、离线评估器及 Session live 场景 | 36 次上限活动完整 records；真实角色请求/工具/独立判定/失败，不能重复建设 Canary |
| S1.2 | S1.1 的离线合同 | 在 `adapters/runtime/pydantic_ai.py` 提取最小显式 construction/transport 策略；扩展 `domain/model_profiles.py`、`application/model_profiles.py` | OpenAI 历史路径行为不变；不支持前缀在取 key 前拒绝，假凭证只走 MockTransport |
| S1.3 | S1.2，S4.1 | 拟新增 `adapters/runtime/providers/anthropic.py`；更新允许列表、pyproject/lock 与安装资产 | 全部职责/工具/usage/取消合同；独立真实 canary +6 任务至少 5 通过 |
| S1.4 | S1.3，S4.1 | 拟新增 `adapters/runtime/providers/google.py`；相同明确 client/预算语义，不自动读云身份 | 同上；3 个跨供应商角色任务全部通过，记录真正目标和绑定但不公开 credential_ref |
| S2.1 | S1.1 Outcome schema | 按旧 1.2 新增 `application/readiness.py`、domain/port；复用 `StaticRepositoryProfiler`、`BootstrapService`、受审命令路径 | 6 仓库真实诊断；不安装、不在宿主跑项目脚本；业务 baseline 与内置 Canary 分开 |
| S2.2 | S2.1；基础 Session 已有 | 扩展 `cli/chat.py`、`onboarding.py`、`application/session_review.py`；精确选择待处理事项，模型/角色管理复用各 service | 冻结10旅程，错误原因/下一步清晰；审批≠执行；退出/竞争无重复；历史默认无明文持久化 |
| S2.3 | S2.2，既有 FleetPatch | `domain/role_templates.py`、`application/planning.py`、`assets/` 中增加4个受审角色/验证模板组合与预览 | 模板在真实 planner/工具范围生效；自定义角色不变成新的无限 execution kind；schema/安装检查 |
| S2.4 | S2.3、S1.1 | 扩展 `tests/integration/test_custom_role_workflow.py`、`test_session_onboarding.py`、`tests/e2e/test_persistent_chat_cli.py` | 五种策略各正反案例；3 cold-start/10 Session 旅程；假模型与live证据分别标注 |
| S3.1 | 当前 Runtime/预算；与 S1.2 协调准入文件 | `ports/runtime.py`、`application/runtime.py`、`domain/models.py`；拟新增 `tests/contract/runtime_conformance/` 参数化公共合同 | PydanticAI/fake先过；完整 deferred batch 校验、准确身份、取消/暂停/unknown 不重放、所有 output kinds |
| S3.2 | S3.1，S4.1，OpenAI基线 | 拟新增 `adapters/runtime/openai_agents.py`；可信 `bootstrap.py` 注册、profile准入和optional依赖；provider安全client复用 | 单次 Fleet role 调用，禁止独立 handoff/原生执行；6任务至少5通过与独立canary；不能只结束时回填usage |
| S3.3 | S3.2 | 复用 `WorkflowEngine._runtime_configuration`/`GraphWorkflowExecution`；若提供 streaming，新增有界 presentation event 通道 | 3 mixed-harness任务全过；取消/中断流不触发工具；旧Run binding不变；原生checkpoint仍unsupported直到专项完成 |
| S3.4 | S3.1–3.3；非发布共同前置 | 拟新增 `adapters/runtime/langgraph.py` 单职责有界图与beta测试；Coding Harness另写可行性ADR | LangGraph6任务至少5通过且完整适用conformance；Codex/Claude Code给明确 supported/blocked 证据，不能以hook存在作安全证明 |
| S4.1 | 当前安全基线，贯穿所有包 | 参数化现有 `tests/unit/test_permission_policy_security.py`、`tests/contract/test_runtime_budgets.py`、Sandbox/恢复测试；更新 `scripts/verify_adversarial.py` manifest | 冻结至少30负向场景且既有安全套件不削弱；审计的DENY和实际无副作用均验证 |
| S4.2 | S2.1，S4.1 | 拟新增 `domain/preparation.py`、`application/preparation.py`；在Docker适配层实现独立、显式授权的准备阶段及PreparationReceipt | Python/Node锁定环境；受审网络范围，不伪称域名过滤；普通命令仍network-off；无宿主安装hooks |
| S4.3 | S4.1；可早于S4.2 | `application/permissions.py`、`permission_policy.py`、`resources.py`、`cli/`诊断；精确grant解释/revoke/owner-stopped恢复 | 现有 allow once/run/exact-scope 原义不变；重复取消、unknown资源和多终端竞争可解释，不能清理他人资源 |
| S4.4 | S4.1–4.3，独立远程ADR/授权 | 拟新增 `adapters/sandbox/modal.py`；扩展 `ports/sandbox.py` 必需能力、远程lease/artifact传输；Hosted另行具体provider合同 | 8类远程场景、确切资源/对象hash、断联不重发、终止回读；worker无模型key；Hosted没有实现不得注册 |
| S5.1 | 当前只读observer；新增字段依赖对应S1/S3 | `application/dashboard.py`、`ports/dashboard.py`、`adapters/persistence/dashboard.py` 新增明确投影 | 12观察场景，provider/harness/role identity可溯，missing/stale/unknown显示准确 |
| S5.2 | S5.1 | `adapters/dashboard/`及打包assets：依赖图/时间线、预算/等待解释、bounded筛选与性能测量 | 20批100事件p95≤2秒，真实持久化到显示的时间戳；断连、移动端/200%文字和键盘可用 |
| S5.3 | S2.2，S4.1，新HTTP授权ADR | 在 `adapters/dashboard/http.py`旁建立独立action路由/短期写session；调用现有plan/session/approval/patch服务 | 观察token无写权，exact hash确认，Origin/CSRF/重放/stale/CLI竞争拒绝，模型无网页自动确认权 |
| S5.4 | S5.2–5.3 | 扩展 `tests/e2e/dashboard_browser.js`与`tests/integration/test_dashboard.py`及action tests（拟新增） | 真实浏览器覆盖全部12journey与写负向矩阵；source和新安装wheel都检查，测试server/token清理 |
| S6.1 | S3.1，S4.1；不依赖S7 | 拟新增 `ports/connectors.py`、`domain/external_actions.py`、`application/credentials.py`；Gateway语义工具扩展 | 明确server/repo/action/版本，读写分离；外部credential不进入AgentInvocation或workspace |
| S6.2 | S6.1 | 拟新增 `adapters/tools/mcp.py`，显式连接身份与静态允许工具映射；本地进程如支持则有独立启动授权/隔离 | 一个受审服务只读路径；tool metadata不自授信，发现不执行，恶意输出/timeout/越界否决 |
| S6.3 | S6.1 | 拟新增 `adapters/connectors/github.py`、应用提案service；先指定issue/PR读取、exact diff提案 | 只读模式无远端写；repo/ref/body/patch版本绑定，secret脱敏及用户可看提案 |
| S6.4 | S6.2–6.3，外部授权 | 持久 `ExternalActionReceipt` reserve/dispatched/confirmed/unknown；受审PR创建/更新、显式revoke | 固定10场景，unknown先远端读回不盲retry；真实PR ID/内容hash证明；两个默认关闭示例随包验收 |
| S7.1 | S1.1 Outcome合同 | 按 [Memory细计划](2026-09-07-okr-02-project-memory.md) 建KnowledgeRecord/store/人工接受 | 来源/范围/版本100%完整，accepted是真用户，不自动总结后授信 |
| S7.2 | S7.1，真实基线能力 | 按同一细计划建ContextAssembler、角色投影、snapshot binding/检索/管理 | 40检索场景及12对任务指标；冻结快照跨resume不换latest；不使用未来答案 |
| S7.3 | S7.2，独立学习预算 | 按 [评估细计划](2026-09-07-okr-03-evaluated-evolution.md) 建LearningJob及exact候选评估；复用OrganizationService人工路径 | 3问题、至少1有收益；source→fresh proposal Run→冻结评估，不重启completed Run，不伪造apply |
| S7.4 | S7.3收益门禁，用户policy | 按 [有限自动化细计划](2026-09-07-okr-04-bounded-auto-evolution.md) 建默认关闭Policy/事实校验/activation | 20shadow、10候选3+3+3+1批、至少8正确激活；撤销有效；不自动更改组织/权限 |
| S8.1 | 基线，贯穿全程 | 现有quality/schema/build/security与release scripts、支持矩阵、离线依赖准备说明 | 当前版本Linux/macOS×Python3.12/3.13/3.14逐格记录；缺宿主不以Docker worker冒充；Actions不自动触发 |
| S8.2 | 当前store/artifact身份；不依赖Memory | 拟新增 `application/data_lifecycle.py`、`ports/backup.py`；SQLite一致性备份、Artifact manifest、脱敏export、引用感知GC preview | 3恢复演练；活跃/rollback引用保护；目标明确且删除需确认；跨安装不继承trust/活跃执行许可 |
| S8.3 | S2最小旅程，S8.1–8.2 | `tests/release/test_installed_distribution.py`、`test_release_upgrades.py`、README/USER_GUIDE、贡献及安全披露文档 | clean wheel/sdist、3fresh-install与3upgrade/restore；验证打包后的所有新adapter/UI/模板资源 |
| S8.4 | 已选发行范围各项gate + owner授权 | 版本/变更记录/支持矩阵、明确license/tag/package/git交付清单，不修改已冻结验收去掩盖失败 | commit/push/merge/tag/package每项有独立receipt；无授权标未发布；不要求S7/S4远程全部完成 |

## Validation plan

本节是未来实施合同，**本次没有运行这些业务测试**。每包先实现相应测试并确定适用矩阵，再执行。任务集/边界/成功定义见总表与对应子计划；无需把32包所有未来测试预先写为空壳。

先在已准备的本地依赖环境分配新临时证据目录（不得覆盖现有数据），然后默认关闭所有实际服务 opt-in：

```bash
fleet_evidence_root="$(mktemp -d -t fleet-system-evidence)"
export AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0
export AGENT_FLEET_ENABLE_DOCKER_TESTS=0
export AGENT_FLEET_ENABLE_INSTALL_TESTS=0
export UV_PYTHON_DOWNLOADS=never
uv lock --check --offline
uv sync --all-extras --frozen --offline
uv run --offline --frozen ruff format --check .
uv run --offline --frozen ruff check .
uv run --offline --frozen mypy src tests
uv run --offline --frozen python -m agent_fleet.schemas.generate --check
uv run --offline --frozen pytest -q -ra
uv run --offline --frozen python scripts/verify_adversarial.py --output "$fleet_evidence_root/security"
uv build --offline --out-dir "$fleet_evidence_root/archives"
git diff --check
```

首次缺依赖时先报告缺口，在另外获准的依赖准备阶段获取锁定依赖；不把离线命令改成联网后仍报offline通过。更新lock是实现步骤，与`--frozen`验收分离。

现有焦点入口可直接作为回归起点，实施时追加新文件：

```bash
uv run --offline --frozen pytest -q -ra tests/contract/test_pydantic_ai_runtime.py tests/contract/test_runtime_budgets.py tests/contract/test_model_profile_transport.py tests/integration/test_model_profile_workflow.py
uv run --offline --frozen pytest -q -ra tests/integration/test_session_onboarding.py tests/integration/test_session_review.py tests/integration/test_custom_role_workflow.py tests/e2e/test_persistent_chat_cli.py
uv run --offline --frozen pytest -q -ra tests/contract/test_dashboard_reader.py tests/integration/test_dashboard.py tests/integration/test_release_upgrades.py
node --check tests/e2e/dashboard_browser.js
```

`node --check` 只证明语法，不算真实浏览器验收。实际浏览器fixture/server/installed-wheel步骤复用 `docs/SESSION_FIRST_ACCEPTANCE.md` 和用户指南，在需要的环境重新检查。

条件 gate：资源/命令/Runtime工具路径变更需显式 real Docker；packaging/README/USER_GUIDE/新依赖/资源变更需fresh wheel/sdist；UI行为变更需真实浏览器；真实Provider/远程/MCP/GitHub另有明确opt-in、端点/凭证引用/预算与远端读回。现有真实模型入口是 `tests/live/test_provider_smoke.py`，不得另外创建重复的无工具聊天smoke替代它。没有授权/环境时 `NOT_RUN`，不是PASS。

每包产出拟议 `docs/acceptance/system-Sx-y.md` 和外部保留的脱敏原始receipt/JUnit/manifest：标明freeze hash、exact command、exit/count/skip、source vs installed、mock vs live、平台、cleanup、known risks。全部统计按 attempt ID 去重；通用 conformance 通过不等于全生态安全证明。

## Rollback and recovery

- Provider/Harness：禁用新选择只影响未来任务；历史Run固定实现/配置版本，缺对应版本拒绝或显式放弃，不自动换回另一个模型。未知请求保留reservation，不能取消账目后重发。
- Session/UI：持久审查由现有控制平面所有，关闭UI不取消其他进程业务Run；单次claim消费与状态变更事务化，失败读回，不重播用户确认。
- Sandbox/准备/远程：记录完整lease/daemon或remote identity/hash；只清理确切拥有资源，断联后先reconcile。网络准备成功不默认授权下一阶段继续联网。
- Connector：外部写结果unknown时按确切请求身份/远端目标读回；没有可靠去重依据则保留人工恢复。撤销凭证/授权停止新动作，但不能声称已撤销的远端写自动消失。
- Memory/组织：新增revision和revoke/supersede，保留旧Run上下文；FleetPatch rollback仍是新用户操作，知识策略不授予组织权限。
- 数据/发行：备份包含一致性清单和校验；restore到明确的新状态目录，活跃owner/资源/许可须重新核验。迁移前备份、失败前向修复，不通过降级程序忽略required字段；发行回退记录确切旧版本及尚不兼容的数据，不删除历史审计。

## Progress

- [x] (2026-09-07) 用户纠正后重建系统级目标，区分真实模型已实现与live未验收。
- [x] (2026-09-07) 只读复核Provider/Harness/按角色路由及产品覆盖；保留进化子路线并修正引用。
- [x] (2026-09-07) 拆分32包、具体入口、依赖、KR、验证和恢复；未实施。
- [x] (2026-09-07) 七份规划文档结构/链接/空白检查通过，八目标/32唯一工作包核对通过；产品覆盖与Adapter边界两次独立只读审查通过，修正文件I/O与Sandbox命令执行的图区分。
- [ ] Milestone A：真实可用。
- [ ] Milestone B：可扩展。
- [ ] Milestone C：工作流产品化。
- [ ] Milestone D：学习与远程。

## Discoveries

- Observation：现有角色Profile已保存runtime_name，mixed fake/PydanticAI已验证。Evidence：`tests/integration/test_model_profile_workflow.py::test_mixed_runtime_roles_keep_exact_accounting_identity`。Consequence：新增Harness延伸既有准入和路由，不重写组织层。
- Observation：OpenAI代码路径已有而live未运行；PydanticAI上游支持更多Provider不意味着本项目已支持。Evidence：`pyproject.toml`、`adapters/runtime/pydantic_ai.py`、验收账本。Consequence：分别列验证任务与开发任务。
- Observation：上版只规划评估/Memory/进化，缺完整产品范围。Evidence：用户明确纠正。Consequence：S7降为八条主线之一，第二Provider/Harness/MCP/发行无S7依赖。
- Observation：Dashboard已有读UI，不包含用户写权限；Docker worker不是Linux宿主平台测试。Consequence：新写入口和跨平台支持分别验收。

## Decision Log

- Decision：使用S1–S8与32包、A–D门禁批次，不虚构时间承诺。Rationale：近期实现与后续扩展都可见，但不并行启动全产品。Date：2026-09-07。
- Decision：Provider默认顺序OpenAI实测、Anthropic、Gemini；Harness默认OpenAI Agents SDK、LangGraph beta。Rationale：先固定另一个变量检验可替换性；具体型号留给用户配置。Alternatives：直接接CLI Harness风险边界更大，先做可行性。Date：2026-09-07。
- Decision：供应商SDK只提供适配层能力，Fleet仍拥有团队、工具许可、Sandbox、预算与证据。Rationale：官方SDK的tools/handoff/interrupt本身不是Fleet安全证明；依当前锁定版本重新核对。Date：2026-09-07。
- Decision：保留旧四份细计划为共享评估和S7子路线，不删除历史设计；不修改已完成Session-first验收或包内README/guide。Rationale：范围纠正不应抹去有用测量合同或制造新发行。Date：2026-09-07。
- Decision：Actions不足时继续本地完整验收，发布/外部消费保持单独门禁。Rationale：规划不扩大执行权限，未跑结果不算通过。Date：2026-09-07。

## Outcomes

仅系统级路线和执行合同形成；八项新增目标全部未实施。七份规划文档、五份ExecPlan各14个必需标题、24个本地链接、八目标和32唯一工作包的结构/围栏/空白/EOF检查通过；两份独立只读审查无剩余阻塞。tracked diff为空，source/tests/scripts聚合hash仍为`de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`。

本次未运行业务format/lint/type/unit/integration/E2E、Docker、安装或live测试；未更改代码、依赖、README、打包资源，也没有GitHub写入或Actions触发。后续每包完成后在此追加确切结果，不覆盖失败或把planned标成shipped。
