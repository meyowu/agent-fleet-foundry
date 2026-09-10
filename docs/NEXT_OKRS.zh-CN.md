# Agent Fleet：整个系统的开发 OKR 与路线图

> 本文保留 2026-09-07 的目标设计与当时状态，不是当前功能清单。
> 2026-09-10 的已实现功能、真实 E2E 结果和未完成项见
> [README](../README.md#s1s3-development-status--2026-09-10-utc) 与
> [交付执行计划](../.agent/plans/2026-09-10-verified-foundations-merge.md)。
> 合并已验证的基础版本不代表这些 OKR 已全部完成。

日期：2026-09-07。代码基线：`3fb09711851b27b5276d7faddd50bc317e2536fb`。状态：**计划已修订，新增功能未开始实施**。

范围更正：上一版把系统路线收窄成了自进化路线。本版覆盖真实模型、Agent/Harness Adapter、Bootstrap、Session、角色、权限、Sandbox、Dashboard、工具集成、Memory 和开源交付。上一版保留为 [评估与进化子路线](LEARNING_AND_EVOLUTION_OKRS.zh-CN.md)，不能再据此推迟其他系统能力。

详细工作包、代码入口、验收和恢复策略见 [系统开发 living ExecPlan](../.agent/plans/2026-09-07-system-development-roadmap.md)。本次不执行模型/Docker、安装新依赖、修改业务代码、提交/推送、发布或启动后台任务；Actions 配额限制保持。

## 1. 从什么状态继续，而不是重新开始

| 系统部分 | 当前代码状态 | 下一步的真正缺口 |
| --- | --- | --- |
| 真实模型 | PydanticAI + OpenAI Responses/Chat 路径已实现 | 当前版本 live canary 和实际项目效果未验收；不是尚未写接入代码 |
| 分角色模型/Runtime | ModelProfile 已包含模型和 runtime_name，Run 冻结角色绑定；fake/PydanticAI 混合路由已有离线测试 | 第二、第三供应商；第二个真实 Harness；真实混合路由验收 |
| Session | 已有前台持久会话、计划审查、审批、恢复、Patch 审查 | 统一日常管理、补全/历史的隐私策略、更清晰的诊断；不是再造 REPL |
| Bootstrap/Adaptive Fleet/角色 | 静态仓库识别、Canary、五种策略、自定义角色已实现 | 目标仓库 readiness、隔离依赖准备、模板可用性、团队选择评测 |
| 权限和 Sandbox | Broker、精确审批、Docker/fake/local-unsafe、资源恢复已实现 | 新适配器的共同安全合同；真正可执行的依赖准备；远程后端 |
| Dashboard | 本地只读实时观察、事件重连、证据检查已实现 | 完整任务图与诊断/用量解释、性能基线；后续安全操作入口 |
| Memory/进化 | 静态项目知识、会话/Run 历史、人工 FleetPatch 已有 | 长期知识检索、经验提炼、收益实验、有限自动化 |
| 外部集成与交付 | 打包/安装/本地验收已有；产品 MCP/GitHub connector 没有 | 受控连接器、数据生命周期、当前版本跨平台验收及正式发行 |

来源：[当前架构](CURRENT_ARCHITECTURE_AND_ROADMAP.zh-CN.md)、[既有验收账本](SESSION_FIRST_ACCEPTANCE.md)、`src/agent_fleet/bootstrap.py`、`ports/runtime.py`、`application/model_profiles.py`。2283 个默认测试通过是已有工程记录，不是本次重跑，也不是实际模型任务成功率。

## 2. 三种 Adapter 必须分开规划

| 层 | 回答什么问题 | 当前 | 本路线候选 |
| --- | --- | --- | --- |
| Model Provider | 用谁的模型和接口？ | OpenAI | Anthropic → Google Gemini；之后独立设计本地模型/兼容端点 |
| Agent/Harness Runtime | 谁执行受限模型循环、解释工具和输出？ | PydanticAI；fake 仅测试 | OpenAI Agents SDK → LangGraph beta；Codex/Claude Code 独立可行性门禁 |
| Sandbox Provider | 项目代码实际在哪里执行？ | Docker；fake 不执行；local-unsafe 不隔离 | Modal beta → HostedSandbox；不让 Harness 接管最终执行边界 |

例如目标组合可以是：CoS 使用 PydanticAI + OpenAI，Engineer 使用 OpenAI Agents SDK + OpenAI，Verifier 使用 PydanticAI + Anthropic，项目命令仍由 Fleet 的 Docker Sandbox 执行。这是**拟议验收组合**，不是当前支持声明；模型 ID 和凭证由用户配置，不固定某个型号。

上游存在 Anthropic/Google 模型集成，但 Fleet 仍须逐项实现自己的认证、传输、预算和安全合同，不能把上游支持表直接复制成产品支持表。[PydanticAI Anthropic](https://pydantic.dev/docs/ai/models/anthropic/)、[Google](https://pydantic.dev/docs/ai/models/google/)。

## 3. 系统级 OKR

这是跨多个开发周期的总路线，不是要求一个季度同时完成八项。Priority 表示启动顺序；后续扩展不阻塞边界准确的小版本发行。所有数字均为拟议验收目标，实施前冻结样本/预算/评分；未知仍为 `NOT_MEASURED`，未获准执行为 `NOT_RUN`。

### S1 · P0 → P1：真实模型可用，BYOK 不局限于一家供应商

- **KR1.1**：完成既有 OpenAI live canary，并完成 24 个任务/6 个 Python、Node 仓库的基线；12 个封存任务至少 9 个独立通过，全部失败和费用未知保留。
- **KR1.2**：按 OpenAI → Anthropic → Google Gemini 顺序，累计 3 个 Provider 通过各自的认证、结构化输出、工具循环、usage、超时/取消与秘密保护合同；每家有独立 opt-in live canary，不能只返回一句聊天文本。
- **KR1.3**：3 个预注册跨供应商角色组合任务均完整通过，实际请求与冻结 Profile 相符，零隐式模型/密钥/端点 fallback。新增供应商各有 6 个小任务资格集，至少 5/6 独立通过，安全负向测试另列全过。

执行：S1.1 真实基线及回归 → S1.2 最小 Provider 安全接口 → S1.3 Anthropic → S1.4 Gemini 与跨供应商验收。

### S2 · P0 → P1：普通用户能从仓库进入一个好用的 Session

- **KR2.1**：6 个选定仓库的 readiness 正确指出验证命令、工具链/依赖缺口及原有失败；3 次冷启动环境能按公开指南完成首个任务，不改内部数据库。
- **KR2.2**：10 个固定日常使用场景可以留在同一 Session 完成：任务选择、计划审查、工具审批、Patch 审查/应用、取消/恢复、模型选择、角色查看与诊断等；仍区分不同授权，不要求用户抄内部 ID。
- **KR2.3**：提供 4 个经过验收的项目角色/验证模板组合；五种现有团队策略各有正反场景，合法计划成功、越界计划正确拒绝，不靠固定多 Agent 数量得分。

执行：S2.1 readiness/业务 baseline → S2.2 Session 管理与隐私友好的输入体验 → S2.3 默认模板与自定义角色工具 → S2.4 五策略/冷启动用户旅程。

### S3 · P1 → P2：新增真实 Agent Adapter，证明 Harness 可以替换

- **KR3.1**：建立统一 Runtime conformance suite，覆盖五类执行职责、自定义角色、工具、审批、预算、取消、错误、恢复与证据绑定；所有声明支持的 Harness 通过全部适用项，缺能力在调用前拒绝。
- **KR3.2**：累计 2 个真实 Harness：现有 PydanticAI + 新 OpenAI Agents SDK Adapter；至少 3 个混合 Harness 任务完整通过，新 Harness 在冻结 6 任务资格集中至少 5/6 通过。
- **KR3.3**：完成一个受限 LangGraph beta 纵向切片（资格集至少 5/6、全部适用安全合同通过），并交付 Codex/Claude Code Harness 的明确可行性结论。后者只有原生工具、凭证和执行可被 Fleet 边界接管时才进入独立实现，不能用 subprocess 包装冒充安全接入。

执行：S3.1 能力合同及准入 → S3.2 OpenAI Agents SDK → S3.3 分角色混合运行/有限 streaming → S3.4 LangGraph beta 与 Coding Harness 可行性。

SDK 的循环、handoff、checkpoint 并不自动成为 Fleet 的调度和审批权威。OpenAI Agents SDK 有相应运行能力；LangGraph 的恢复有自身状态语义。我们的集成选择是把它们限制在一个受授权职责内部，继续由 Fleet 拥有组织图和副作用许可。[OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)、[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

### S4 · P0 贯穿、P1/P3 扩展：所有执行受控，并能从失败恢复

- **KR4.1**：新增 Provider/Harness/Tool/Sandbox 均通过共同安全矩阵；冻结至少 30 个覆盖越权、路径逃逸、secret、取消、重放和资源身份的负向场景，未授权副作用为零，不能降低现有门禁。
- **KR4.2**：Python/Node 各一个可复现的隔离依赖准备切片；网络步骤独立显示/批准，锁定依赖及镜像，业务执行回到 network-off，宿主不运行项目安装脚本。
- **KR4.3**：P3 交付 ModalSandboxProvider beta：预注册 8 类生命周期/断联/取消/清理场景全部得到正确状态和证据，能力不匹配拒绝；HostedSandbox 作为随后独立实现合同，不静默替换 Docker。

执行：S4.1 安全/恢复合同 → S4.2 Docker 依赖准备 → S4.3 精确权限诊断和资源恢复体验 → S4.4 Modal beta/Hosted 接口与远程故障合同。

S4.4 是后续扩展，不是 S1/S2 首发前置；第一批可以使用预先准备、受审查的离线环境。

### S5 · P1 → P2：Dashboard 能解释系统状态，之后安全地操作

- **KR5.1**：12 个固定观察场景完整显示任务/依赖/角色、Provider/Harness、预算、等待原因、Patch、Verifier 和 proof gaps；无虚构完成百分比，费用未知不填零。
- **KR5.2**：在冻结本地环境的 20 组事件批次中，100 个指定已持久化事件从提交到可见的 p95 ≤2 秒；记录原始时间样本，断网/重连无漏项，不能拿历史 102ms 单次观察当 SLA。
- **KR5.3**：在独立认证/Origin/防重放合同通过后，提供 plan approve、tool approve/deny、cancel、patch review/apply 的精确用户入口；固定浏览器/CLI 竞争及 stale review 场景全过，不添加默认远程/多用户控制面。

执行：S5.1 观察数据合同 → S5.2 图/时间线/用量及故障诊断 → S5.3 安全操作 API → S5.4 浏览器安全、性能和可访问性验收。

### S6 · P2：连接真实开发工作流，而不把凭证和权限交给 Agent

- **KR6.1**：提供受控 MCP client，至少一个显式配置的服务完成发现、只读调用、身份固定、超时、输出限额与审计；发现工具不等于批准执行。
- **KR6.2**：GitHub connector 完成指定仓库 issue/PR 读取及受审查的 PR 创建/更新；10 个冻结场景覆盖成功、拒绝、重复、未知远端结果和撤销，每次外部写入有精确批准与远端读回证明。
- **KR6.3**：发布 2 个随发行包提供、默认关闭的受审查工具配置示例（MCP 与 GitHub），从干净配置完成启用/解释/撤销；任意第三方代码自动安装不在第一版。

执行：S6.1 Tool/Connector 与凭证合同 → S6.2 只读 MCP → S6.3 GitHub 读路径/PR 提案 → S6.4 精确外部写与结果回读。

GitHub App、插件市场不是首个 connector 的必要条件；产品集成也不等于开发本项目时能使用 GitHub 工具。

### S7 · P1 → P2：项目知识可持续积累，之后再进化

- **KR7.1**：实现来源可追溯、版本化、可撤销的项目 Memory；40 场景中相关 Top-3 命中 ≥90%，全部禁止记录零注入。
- **KR7.2**：12 对任务两组各至少 9/12 通过，Memory 组成功数不下降，按失败不获益口径减少 ≥30% 重复发现/纠正。
- **KR7.3**：3 个真实重复问题形成有界候选，至少一个通过冻结的新旧评估，发布仍需人工；更后的自动化只先做 10 个直接事实候选、至少 8 个正确激活及完整撤销验证。

执行：S7.1 KnowledgeStore/来源 → S7.2 Context/检索/管理 → S7.3 独立复盘/评估/人工 FleetPatch → S7.4 有限事实自动激活。

精确指标、预算及细化步骤沿用 [Memory](../.agent/plans/2026-09-07-okr-02-project-memory.md)、[评估式改进](../.agent/plans/2026-09-07-okr-03-evaluated-evolution.md)、[有限自动化](../.agent/plans/2026-09-07-okr-04-bounded-auto-evolution.md)。**S7 不是 S1/S3/S5/S6/S8 的共同前置。**

### S8 · P0 → P1：成为可安装、可升级、可信任的开源产品

- **KR8.1**：每个候选版本通过完整离线质量、security、schema、wheel/sdist 与适用 Docker/browser gates；当前版本的 Linux/macOS 宿主及所声明 Python 版本逐格验收，无证据格明确 unsupported/unverified。
- **KR8.2**：完成 3 次 fresh-install 首次任务、3 次升级/一致性备份恢复，以及活跃引用/保留策略负向矩阵；Run、Artifact、审批和组织恢复证据不因 GC 丢失。
- **KR8.3**：交付版本化 quickstart、支持矩阵、故障说明、迁移/数据说明、贡献与安全披露流程；经独立 owner 门禁完成 release/tag/package 的精确交付与读回，未授权时如实保留未发布。

执行：S8.1 可复现本地验收/支持矩阵 → S8.2 备份恢复/脱敏导出/保留 → S8.3 安装升级/指南/贡献者体验 → S8.4 发布门禁与远端证据。

许可证、包名/发布目标、公开仓库等保留到实际发布门禁，不在规划阶段反复询问，也不替用户决定。Actions 配额不足时使用本地完整门禁，不能关闭保护或把旧 CI 当新版本结果。

## 4. 建议开发批次与依赖

| 批次 | 重点工作包 | 这一批交付什么 | 不必等待什么 |
| --- | --- | --- | --- |
| A：真实可用 Alpha | S1.1、S2.1、S2.2 最小闭环、S4.1、S8.1 | 现有模型在选定真实仓库上完成任务；普通用户知道如何操作和排错 | Memory、第三供应商、远程 Sandbox |
| B：可扩展 Beta | S1.2–S1.4、S3.1–S3.3、S2.3–S2.4、S4.2–S4.3、S5.1–S5.2 | 多 Provider、第二真实 Harness、角色模板、可用环境、清晰状态 | 自动学习、MCP、浏览器写操作 |
| C：工作流产品化 | S3.4、S5.3–S5.4、S6.1–S6.4、S7.1–S7.2、S8.2–S8.4 | 外部开发工作流、可管理数据、可交付版本、长期项目上下文 | S7 收益实验成功、Modal/Hosted |
| D：学习与远程扩展 | S7.3–S7.4、S4.4；后续专项 | 有证据的改进、有限自治、远程执行 beta | 不应倒过来阻塞 A–C |

S3.1 的纯合同工作可以在 A 后期与 Provider 工作并行；S8.2 数据生命周期可以从 B 提前，不依赖 Memory。S8.4 可对任意已验收、范围明确的版本执行，不要求先完成整个 C。不指定未经估算的周数或虚构发布时间。

共享文件 `bootstrap.py`、domain 配置、数据库迁移及 workflow 集成保持单写者；稳定接口后 adapter 独立文件、测试 fixture 和只读 UI 可并行。每包有单一实现负责人、独立验证者和证据链接，人员/日期在领取包时填入。

## 5. 预算、指标和支持声明

- S1.1 复用 [真实基线 ExecPlan](../.agent/plans/2026-09-07-okr-01-real-task-baseline.md)，不另造相同 canary/评估器；其 32 次 cohort +4 辅助尝试合计 36 次，按同一身份去重。S2/S8 的 3 次首次旅程只有版本/环境/评分合同完全一致时才能共享证据，不能称为额外 6 个独立用户。
- 新 Provider、新 Harness 的 canary、6 任务资格集、3 个混合任务均另有 manifest 和活动总预算。能精确共享同一次混合运行的场景引用同一 receipt，不把它们加成两个独立样本；不能默认塞进 S1.1 的 36 次额度。
- 每包冻结尝试上限、request/token/时间预算、预期输出、代码/依赖/模型/适配器版本。所有失败/取消/未知都报告；unknown 不被记成 0 成本，不自动重发可能已发生的外部动作。
- `implemented`、`offline-tested`、`live-verified`、`beta`、`released` 是不同状态。资格集中至少 5/6 只是有限支持门槛，不证明普遍任务成功或新 Harness 优于旧 Harness。若要声称改进，另行使用未见任务和固定对照。
- 供应商、Harness、Sandbox 按明确组合发布支持矩阵，不承诺任意组合全兼容。流式 UI 事件不等于模型 token streaming，也不等于 Harness 原生 checkpoint 恢复。

## 6. 已纳入但不抢占近期主线的专项

| 专项 | 归属/启动条件 |
| --- | --- |
| Ollama/本地模型、OpenAI-compatible endpoint | S1 后续；独立端点信任与凭证绑定，不能直接打开任意 base_url |
| OS keyring/凭证轮换管理 | S1 后续 + S8；不改变历史 binding，不在 repo 写 secret |
| Codex/Claude Code/OpenHands 类 Coding Harness | S3.4 可行性后独立 ExecPlan；无法拦截原生副作用则标 unsupported |
| HostedSandbox、受控 egress proxy | S4.4 后；实测网络/身份/清理与费用约束，不能宣传未强制执行的域名白名单 |
| detach/attach、后台队列、跨机器/多仓库调度 | S2/S4 后续；独立 supervisor、所有权和恢复合同，不用 Session 后台线程冒充服务 |
| 原生 checkpoint/长上下文压缩 | S3/S7 后续；精确 resume、费用和证据语义，不能重放未知调用 |
| GitHub App、第三方插件、角色/技能市场 | S6/S8 后续；安装来源/版本/权限、进程隔离与撤销先行 |
| 远程 Dashboard、多用户/RBAC、托管控制面 | S5/S4 后续；独立租户/认证/审计设计，保持本地优先不是强制上云 |
| 更多语言/monorepo 支持、更多团队策略 | S2 后续；逐生态 readiness 与任务评测，不把静态识别算完整可执行支持 |
| 模型权重微调/自训练 | 不属于当前产品开发承诺；先证明配置、工具与 Memory 层收益 |

Claude Agent SDK 官方的权限机制本身并非 Fleet Broker；是否能形成不可绕过的接管需要专项验证，不能仅凭存在一个权限回调就宣称兼容。[Claude Agent SDK permissions](https://code.claude.com/docs/en/agent-sdk/permissions)。

## 7. 当前交付状态与下一步

- [x] 更正总体范围，覆盖八条系统主线、32 个开发工作包及后续专项。
- [x] 将既有进化 OKR 保留为子路线，修正四份原 ExecPlan 的索引语义。
- [x] 建立总体 living ExecPlan，明确每包交付、代码入口、验证与安全依赖。
- [x] (2026-09-07) 七份规划文档的结构、24个本地链接、空白/围栏与32唯一工作包检查通过；两份独立只读审查通过。
- [ ] 新增代码、live 验收、发布：均未开始。

建议下一轮按批次 A 开工；第一张合同是 **S1.1 现有真实模型闭环 + S2.1 最小 readiness 接口**，共享一个测量基线。没有真实调用授权时先交付离线评估和诊断，不停止其余可安全推进的开发，也不绕过 live 门禁宣布产品已实测。

本次只有文档变更：tracked diff为空，source/tests/scripts内容摘要与规划前一致；业务格式/lint/type/测试、Docker、安装和真实模型验收均未运行，没有commit/push/merge、发行或Actions触发。
