# Agent Fleet Foundry：当前架构、能力清单与优先级路线图

审阅日期：2026-09-07（America/Los_Angeles）。

代码基线：`3fb09711851b27b5276d7faddd50bc317e2536fb`，包版本 `0.1.0`。本说明基于当前代码、Session-first 验收记录及既有设计文档；后续优先级是建议，不是已获授权的实施任务，也不承诺交付日期。

本文只描述这个仓库的 Agent Fleet Foundry 产品，不把开发它所用的 Codex 工具、插件、记忆或 GitHub 操作能力算作产品能力。历史规格中存在 target、旧阶段状态和概念性目录树；当前实现以实际注册的适配器、调用路径和最新验收记录为依据。

## 阅读导航

1. 产品定位与当前结论
2. 总体架构与技术选型
3. 核心对象及身份关系
4. Repository-aware Bootstrap
5. Session 与任务执行闭环
6. Adaptive Fleet 与角色定制
7. Runtime、模型与凭证
8. Permission Control Plane
9. Sandbox、工作区与恢复
10. Evidence-first Delivery
11. Memory 与持久化
12. Versioned Fleet Evolution
13. Dashboard 与可观测性
14. 当前功能支持矩阵与验收边界
15. 后续路线图：P0 → P3
16. 建议实施顺序与代码导航

## 1. 产品定位与当前结论

> A local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization.

中文：一个面向软件项目、本地优先、用户自带模型凭证的 Agent 组织运行时。用户主要与 Chief of Staff（CoS）对话，系统按任务组建最小团队，在受控工作区内执行，并交付可验证的 Artifact。

与普通 Multi-Agent Framework 的区别不是 Agent 数量，而是六个控制点：仓库理解、按需组队、独立权限、独立执行隔离、证据交付、可审查的组织演进。

当前已经不是只有 Prompt 和 CLI 外壳：Session、模型绑定、自定义角色、图执行、权限、Docker、交付证据、组织版本和只读 Dashboard 已连通。主要差距是日常真实任务的效果验证、更广泛的仓库环境准备、可检索的长期知识和扩展生态。

需要同时保留三个判断：

- **架构已实现**：存在运行路径和安全边界，不是只有类型声明。
- **本地工程验收已通过**：有离线、真实 Docker、安装包和浏览器证据。
- **尚未证明广泛真实任务效果**：没有本次版本的真实模型 API 验收，不能从大量单元测试推导出模型能可靠完成任意项目开发。

“local-first”指控制平面、状态和工作区主要在本机；选择远程模型时，受限任务上下文仍会发送给该供应商，不等于完全离线。

## 2. 总体架构与技术选型

### 2.1 系统关系

```text
用户
 ├─ fleet / fleet chat：前台 Session、审批、审查、应用
 ├─ 显式子命令：模型配置、诊断、恢复等
 └─ 浏览器 Dashboard：只读观察，不执行任务
               │
               ▼
本地 Python 控制平面
 ├─ ConversationService / SessionReviewService
 ├─ BootstrapService / ProjectService
 ├─ WorkflowEngine / FleetPlanner / GraphCoordinator
 ├─ ModelProfileService / PlanReviewService
 ├─ PermissionPolicyService / ApprovalService
 ├─ ResourceService / RecoveryService
 └─ EvidenceAssembler / CompletionGate / OrganizationService
       │                 │                  │
       ▼                 ▼                  ▼
 RuntimeAdapter       执行授权链         SQLite + Artifact
 fake / PydanticAI     ToolGateway        状态、版本、证据
       │              PermissionBroker
       ▼                 │
 模型提议/工具请求         ▼
                     SandboxProvider
                     Docker / fake / local-unsafe
                         │
                         ▼
                 Git candidate worktree
                         │
                   Patch + 独立验证
                         │
                   用户明确审查应用
                         ▼
                    原始项目 checkout
```

上图是职责图，不是所有请求都穿过同一条线。例如 CoS 的纯哈希辅助工具不做 I/O；Git 工作区管理和用户显式应用由可信控制平面负责。模型请求文件、命令等资源操作时，必须走既有 Gateway/Broker 路径。

Dashboard 读取本地持久状态和安全投影，不创建第二套 WorkflowEngine，也不把浏览器显示当成完成证明。

### 2.2 分层

| 层 | 职责 | 代表代码 |
| --- | --- | --- |
| CLI / Session | 参数解析、用户交互、展示与确定性命令分派 | `cli/app.py`、`cli/chat.py` |
| Application / Control Plane | 任务状态机、组队、授权、版本、资源和证据协调 | `application/` |
| Domain | 严格类型、状态、策略、身份及不变量 | `domain/` |
| Ports | 项目拥有的 Runtime、Sandbox、Store 等接口 | `ports/` |
| Adapters | PydanticAI、Docker、Git、SQLite、文件系统、HTTP 的具体实现 | `adapters/` |
| Composition Root | 构造并注入具体实现 | `bootstrap.py` |

依赖方向为 `CLI → Application → Domain`，Application 面向 Ports，Adapters 实现 Ports。领域逻辑不依赖 Typer、模型 SDK 或 Docker 对象。

关键设计：**LLM 提议，确定性程序校验和执行。** PydanticAI 是可替换的模型调用适配器，不拥有最终的权限、图结构、Sandbox 选择或完成判定。

### 2.3 当前技术栈

- Python，声明支持 `>=3.12,<3.15`；本次版本本地验证使用 Python 3.14.6。
- Typer + Rich：CLI 和终端展示。
- Pydantic v2：外部输入、持久化数据及生成 JSON Schema。
- PydanticAI + OpenAI SDK：现有真实模型适配路径。
- SQLite：本地结构化状态，当前迁移版本 1–10。
- 本地文件 Artifact Store：内容与哈希绑定的交付数据。
- Git worktrees：候选工作区和独立验证工作区。
- Docker CLI：受控容器执行，不通过普通 shell 拼接命令。
- 原生 HTML/CSS/JavaScript + 本地 Python HTTP：Dashboard；无必需云后端、CDN 或独立前端框架。
- uv、Ruff、mypy、pytest：依赖、静态检查和测试；当前生成 92 个 Schema。

## 3. 核心对象及身份关系

| 对象 | 含义 | 为什么必须独立 |
| --- | --- | --- |
| Project | 注册仓库及其身份、配置和环境绑定 | 不能只凭当前路径把另一个仓库当成原项目 |
| Conversation | 项目内用户与 CoS 的持久会话 | 会话提供上下文，不授予权限 |
| ConversationTurn | 一次用户提交及其结果 | 重试相同提交不能产生第二次执行 |
| Run | 一次执行生命周期 | 状态、预算、模型、配置和资源都绑定到确切运行 |
| TaskSpec | 目标、路径、验收条件和约束 | 自然语言必须转成可校验的工作范围 |
| FleetPlan | 已校验的策略、节点、依赖和证据要求 | 模型不能边执行边任意改写组织和权限 |
| RoleTemplate | 可复用的职责定义 | 模板不是活跃 Agent，也不是授权规则 |
| AgentInstance | 某次运行中的具体职责实例 | 审批、调用、产物必须知道具体是谁做的 |
| ModelProfile / RunModelBindings | 用户配置及一次任务冻结的模型选择 | 后续配置修改不能暗中改变暂停中的任务 |
| Artifact / EvidenceBundle | 可核验产物及完整交付关系 | 不能只凭 Agent 文本宣称完成 |

一个 Conversation 可以先后产生多个根 Run；一个根 Run 可以包含多个子 Run。图中的独立最终 Verifier保留父任务身份，其他节点可以有自己的子 Run/Task。子任务共享父级累计预算，但不共享一张不受限的授权票据。

## 4. Repository-aware Bootstrap

### 4.1 已实现流程

1. 校验仓库边界和注册条件。
2. `StaticRepositoryProfiler` 读取有界的已知元数据，不执行项目脚本。
3. 生成 RepositoryProfile：生态、构建系统、子项目边界、候选命令、来源、置信度与歧义。
4. 生成事实型 ProjectKnowledge，以及项目化 `.fleet/` 配置提案。
5. 展示配置差异和 Sandbox 选择；preview 不读取所选模型密钥，也不初始化持久状态。
6. 在 Fleet 自己的可丢弃 fixture 仓库里，用 fake runtime + 真实 Docker 运行 Canary。
7. 校验非空 Patch、独立 Verifier 命令、资源清理、CompletionDecision 和 BootstrapReport 的关联及哈希。
8. 通过门禁并完成用户确认后，才发布目标仓库的 `.fleet/`。

裸 `fleet` 在真实交互终端中可以提供上述 onboarding；非交互裸入口只显示帮助，不悄悄初始化项目。

### 4.2 静态识别范围

当前 profiler 包含 Python、Node、Go、Rust、Maven、Gradle、Make 的元数据识别；也读取支持的锁文件及 CI 信号来推导候选命令和歧义。

**静态识别不等于运行支持矩阵。** 看到 `package.json` 不代表 Runner 已装好 Node 及业务依赖；找到 `cargo test` 不代表已对该用户仓库执行过 Rust 测试。

### 4.3 重要边界

- Canary 证明 Fleet 自己的执行闭环，不证明目标业务项目已经能 build/test。
- 不会为了理解仓库自动运行安装脚本、构建脚本或任意 CI 内容。
- fake/local-unsafe Sandbox 不能满足新项目公开初始化的隔离证据门禁。
- Docker 需要已准备好的本地镜像；缺失不会自动拉取镜像或退回宿主机。
- ProjectKnowledge 不是完整代码索引；其摘要还没有逐条事实的来源/置信度结构。

## 5. Session 与任务执行闭环

### 5.1 用户交互

已注册项目可以运行 `fleet` 进入前台会话；显式预执行计划审查使用：

```bash
fleet chat . --review-plan
```

典型交互：

```text
> 修复这个回归，并补测试。
> /plan
> /plan approve
> /confirm <界面给出的精确审查码>
> /resume
> /diff
> /apply
> /confirm <本次应用的审查码>
```

执行中若有权限请求，使用 `/approve` 或指定请求 ID；拒绝、恢复、取消、证据检查和 FleetPatch 审查也已有会话命令。模型 profile 管理目前仍是外部 `fleet models ...` 子命令，不是 `/models`。

### 5.2 四种不同的用户决策

| 决策 | 允许什么 | 不代表什么 |
| --- | --- | --- |
| Plan approval | 同意冻结的任务计划进入后续执行 | 不等于批准所有工具操作 |
| Permission approval | 允许确切动作/资源/条件 | 不等于批准其他 Agent 或整个图 |
| Resume | 消费已有条件并恢复确切运行 | 不应重跑 CoS 或重置预算 |
| Patch apply | 将审查过的确切候选应用到原仓库 | 不等于 commit、push、merge 或部署 |

短期 Session review ticket 有五分钟有效期，绑定所选任务、动作、内容和组织版本，单次消费；真正的计划门禁另有持久化记录，不能用一个前端确认码替代。

### 5.3 执行顺序与恢复

```text
用户目标 → 前置检查与冻结绑定 → CoS 生成范围/策略 → 系统校验 TaskSpec/FleetPlan
                                                   │
                          可选 paused_for_plan ←───┘
                          批准与显式 resume
                                  │
                         工作区准备 / 子任务调度
                                  │
                     Engineer → Verifier → 有界修复
                                  │
                        EvidenceBundle / 审查
                                  │
                            明确 apply
```

上图是常见代码变更路径；direct、single_engineer 等策略不都经过相同节点。是否需要独立 Verifier，由已校验的任务/证据要求决定。

实际状态包含 `created`、`running`、`waiting_for_children`、`paused_for_plan`、`paused_for_approval`、`ready_for_review`、`applying`、`completed`、`failed`、`cancelled`、`rejected`、`abandoned`。

已实现的恢复约束：

- 每个会话同一时间只有一个活跃 turn；忙碌时输入不会自动变成任务队列。
- 重复 submission 返回原 Run，不获得第二个执行 owner。
- 计划决定按 pending → approved → consumed 留下不可变版本；批准本身不创建 worker。
- 不确定的执行所有权不会超时变成“可以随便重试”。
- `/exit`、EOF、Ctrl-C 遵循取消和清理路径，不是后台 detach。
- CLI 重开可以恢复会话和允许恢复的任务状态，但不是恢复任意中断时刻的模型内部消息堆栈。

## 6. Adaptive Fleet 与角色定制

### 6.1 五种已实现策略

| 策略 | 组织形式 | 约束 |
| --- | --- | --- |
| `direct` | CoS 直接给出受限结果/组织提案 | 不执行任意代码；不能假装已完成代码修改 |
| `single_engineer` | 一个 Engineer | 只能用于任务证据要求允许的情形 |
| `engineer_verifier` | Engineer + 独立 Verifier | 候选与独立验证分开 |
| `parallel_engineers` | 多个有界 writer，汇合后父级验证 | 校验写入范围、依赖、汇合和最终补丁 |
| `research_architect_engineer_verifier` | Researcher → Architect → Engineer → Verifier | 前两者是只读职责，报告作为有界任务依赖 |

CoS 提议最小团队；FleetPlanner 校验并构造受支持的图。当前不是任意 DAG/工作流编程语言，也不保证模型总能选出全局最优团队。

图上限当前为 16 个节点、最多 8 个并发 Agent，实际还受项目配置和任务约束限制。并行结束后，按确定顺序汇合候选；子任务的测试通过不能替代对最终组合 Patch 的独立验证。

### 6.2 角色的真实含义

内置角色是 CoS、Engineer、Verifier、Researcher、Architect。

- CoS 的“持久”主要来自用户会话及系统状态，不是一个永远存活的模型对象。
- Engineer 是候选修改职责。
- Verifier 是独立验证职责，不把自己的写入混入候选。
- Researcher/Architect 当前使用受限的仓库/任务上下文；名称不意味着已有互联网搜索、MCP 或浏览器能力。

### 6.3 自定义角色

`.fleet/agents/roles.yaml` 可声明最多 32 个自定义角色，继承 Engineer、Verifier、Researcher、Architect 中一种 execution kind；不能覆盖内置角色或新建一个特权 CoS。

可定制说明、职责指导、允许路径、允许工具子集、步骤上限及经用户允许的模型偏好。工具/步骤/路径只能在既有上限内收窄。

真正执行时保留自定义 ID：例如 `backend` 不会在权限记录中冒充 `engineer`；给 `engineer` 的用户规则不会仅因为继承关系就自动匹配 `backend`。图节点、模型绑定、Artifact 和 Verifier 身份也保留这种区别。

角色说明/目录变更走 FleetPatch。它不是任意 Python Agent 插件，也不是换一个 Markdown 文件就能添加新的执行权限。

## 7. Runtime、模型与凭证

### 7.1 四个概念必须分开

| 概念 | 当前例子 | 决定什么 |
| --- | --- | --- |
| Role | `engineer`、`backend` | 工作职责和受支持的执行类型 |
| Runtime / Harness | `pydantic-ai`、`fake` | 如何调用模型并转换工具请求/结果 |
| Model profile | 用户命名的 planning/coding 配置 | 具体 runtime、模型及显式凭证引用 |
| Sandbox provider | `docker`、`fake`、`local-unsafe` | 受控命令在哪里执行、具有何种隔离 |

当前唯一真实第三方 Agent 框架适配器是 PydanticAI；fake 是确定性测试 runtime。没有注册 LangGraph、CrewAI、AutoGen、Codex CLI 或 Claude Code Harness。

### 7.2 分角色模型

用户在仓库之外管理 ModelProfile 和 ProjectModelSelection。选择顺序是：用户明确角色覆盖 → 用户允许的仓库模型偏好 → 已审阅默认值；只有不存在新选择配置时才使用真正的旧注册配置。

任务启动前对有效角色组合做前置检查，冻结 RunModelBindings。子节点、Verifier、修复和恢复使用原始绑定；修改 profile 只影响未来任务。需要的绑定缺失时失败，不偷偷 fallback。

当前真实适配器只接受 `openai:<model>`、`openai-chat:<model>`，使用固定官方端点。这里的两个前缀不表示两个供应商；也不能把 PydanticAI 上游的全部能力算作 Fleet 已支持。

### 7.3 凭证边界

- 当前只有严格的 `env:NAME` 引用；没有 OS keyring/远程 Secret Manager 适配器。
- 引用保存在用户状态，不写入仓库的 `.fleet/`；API key 值只在可信控制平面内解析。
- 工具、worker 容器、Prompt、Artifact、日志不应获得 API key。
- 不读取任意环境变量来猜测备用供应商，也不接受环境中的任意 OpenAI base URL 来重定向密钥。
- 无真实模型调用的当前验收证明路由、结构化输出和凭证边界；不证明模型输出质量、供应商在线可用性或真实费用表现。

## 8. Permission Control Plane

权限来自独立的 PermissionBroker，而不是 Prompt、模型同意或角色名称。

对资源动作，主要链路是：

```text
模型工具请求 → 可信上下文补全的 ToolIntent → Gateway/Broker 校验
                                              │
                     DENY / REQUIRE_APPROVAL / ALLOW
                                              │
                     精确授权与单次执行所有权 → 执行 → 审计/Artifact
```

有效权限取多层交集：系统硬上限、用户信任、项目请求、workflow/stage、角色、任务路径、适用授权和 Sandbox 能力。仓库 `.fleet/` 只能请求能力，不能给自己授予能力。

已支持：

- Safe、Balanced、Autonomous Sandbox 信任模式；不是无边界的 allow-all。
- Allow once、Allow for run、Always allow exact project scope。
- list、explain、revoke、reset，以及确切请求的 approve/deny。
- 动作、资源、argv、项目、角色等身份条件匹配；不是字符串前缀匹配。
- 路径穿越、符号链接逃逸、敏感路径、越权角色、自我审批等拒绝路径。
- 持久用户信任位于仓库之外，审批和执行有独立记录。

当前 Autonomous Sandbox 与 Balanced 使用相同的 reviewed-command 上限；这个模式名不代表已经开放任意命令、shell、网络或更高权限。新的信任模式能力需要独立实现和安全验收。

必须诚实限定“任何 Harness 不能绕过 Broker”的含义：当前内置适配器只暴露项目拥有的受控工具，并有契约/安全测试；**任意第三方 Python 代码一旦被用户装进同一个控制平面进程，仍共享该进程的 OS 权限**。安全支持不可信插件，需要未来的进程边界，而不是只实现一个 Python Protocol。

## 9. Sandbox、工作区与恢复

### 9.1 三种已注册 Provider

| Provider | 是否实际执行命令 | 隔离性质 | 可否作为当前隔离验证证据 |
| --- | --- | --- | --- |
| Docker | 是 | 本地 Linux 容器，受控配置 | 在其受支持边界与完整证据成立时可以 |
| Fake | 否，记录模拟结果 | 没有执行隔离 | 不可以 |
| Local unsafe | 是，在宿主机 | 明确非隔离 | 不可以满足要求隔离的门禁 |

Docker 每个经校验的命令创建一个受检查的容器，而不是给每个 Agent 一个无限寿命远程机器。控制平面绑定本地 Unix daemon 和已有镜像的不可变 ID。

已实施的边界包括：非 root、drop capabilities、no-new-privileges、只读根文件系统、受限可写 candidate mount、网络关闭、CPU/内存/PID/超时/输出等限制，不挂载宿主 home、凭证目录或 Docker socket。

当前 Docker 路径不提供任意网络访问或域名 allowlist；模型供应商 HTTPS 在控制平面，和 worker 网络隔离是两回事。

### 9.2 Git 工作区

- Engineer 修改候选 worktree，而不是直接污染用户原 checkout。
- Verifier 使用独立验证路径；其写入不成为交付候选。
- Patch 绑定基线、内容哈希、任务和配置；应用时重新核验。
- 用户已有修改、基线变化、组织代际变化可能导致旧候选拒绝应用，不能自动覆盖。

### 9.3 资源和故障

资源创建前先登记确切 lease；创建结果不确定时留下待核对记录。取消/恢复按所属 Run、完整资源 ID 和标签处理，不对所有容器或目录做宽泛清理。

`fleet recover <run-id> --confirm-owner-stopped` 是操作员确认前 owner 已停止后的明确恢复入口，不是系统猜测某个超时任务已经死掉。它不意味着自动恢复任意已执行的模型工具调用。

限制：Docker 仍信任本机账户、daemon、镜像和内核/VM；没有防御恶意同用户进程或内核漏洞的承诺，也没有通用可移植的 candidate 磁盘配额。

## 10. Evidence-first Delivery

### 10.1 完成不是一句话

EvidenceAssembler 从可信记录和实际 Artifact 组装 EvidenceBundle；CompletionGate 按任务要求计算证据充分性。

主要内容：

- changed files 与完整 canonical Patch；
- TaskSpec、FleetPlan、ConfigSnapshot、基线和哈希关联；
- 实际 commands executed、退出状态、输出和验证归属；
- 测试/build 相关证据和 criterion 映射；
- 独立 Verifier 身份与 verdict；
- 图节点输出、join、最终补丁与清理证据；
- remaining risks、proof gaps、usage 和完成判定原因。

不是每个任务都“跑过所有测试和 build”：没有执行的命令不能算通过；需要哪些证据取决于任务和项目验证合同。任务生命周期结束，也不等于所有要求的证据都成立。

### 10.2 三个容易混淆的结果

- `COMPLETED`：生命周期状态。
- Verifier `PASS`：某个 Agent 的结构化判断，仍需核验。
- `verified_complete`：控制平面从一致且充分的证据计算出的结果。

FakeSandbox 的模拟输出不能升级成真实测试通过；换成真实 LLM 也不能改变这个事实。反过来，fake runtime + 真实 Docker 可以证明确切命令被实际执行，但不证明真实模型的推理能力。

内容哈希和身份核对用于检测不一致，不代表本地日志能抵抗掌握 OS 账户的攻击者任意重写全部状态。

## 11. Memory 与持久化

### 11.1 当前五层“记忆”

| 层 | 当前实现 | 自动用于下一次任务吗 |
| --- | --- | --- |
| Agent working context | 一次 invocation 的角色指导、任务输入、工具往返 message history | 不作为该角色的原始长期对话保存 |
| CoS conversation context | SQLite 中的 turn、结果摘要、状态及 Artifact 引用 | 同一会话加载有界近期摘要 |
| ProjectKnowledge | 从 RepositoryProfile 生成的事实 Artifact | 当前明确注入 CoS 规划，不等于全部 Agent 自动共享完整知识库 |
| Organization knowledge | `.fleet/` 角色/工作流/项目指导及版本快照 | 按运行冻结的配置和职责输入使用 |
| Episodic execution records | Run、Agent、命令、审批、证据、版本历史 | 可检查/恢复，但没有通用语义检索后自动回灌机制 |

### 11.2 会话窗口的精确边界

- 最多最近 8 个已结束 turn。
- 完整序列化上下文不超过 32 KiB。
- 每轮用户摘要最多 2048 UTF-8 字节，结果摘要最多 4096 字节。
- 每轮最多 8 个 Artifact 引用；不是把完整 Patch 和命令日志都放入模型历史。
- 摘要由程序根据权威结果组装，并按长度截断，不是自动 LLM 经验提炼。
- 被上下文窗口省略，不等于已从数据库删除。
- 新会话不会自动继承其他会话的全部历史；不同项目也不自动共享一个模型“大脑”。

Engineer 修复调用会获得上一轮独立 Verifier 的结构化反馈；这属于显式任务上下文传递，不是角色自动学习。换模型不应该丢掉任务绑定，但任意时刻的 SDK 消息堆栈没有通用持久恢复。

### 11.3 存储位置

```text
项目仓库/.fleet/                    用户状态根目录/
├─ fleet.yaml                      ├─ state.db
├─ agents/*.md                     ├─ artifacts/
├─ agents/roles.yaml（可选）         ├─ trust/trust.yaml
├─ workflows/                      ├─ installation-id
├─ project/                        └─ 工作区、版本及执行资源记录
└─ skills/（按需引用）
```

状态根由 `AGENT_FLEET_HOME` 显式指定，或使用系统应用数据目录。状态和业务仓库必须分离，不能把 state 放进 `.fleet/`。

SQLite 保存项目、任务、Run、AgentInstance、事件、Artifact 元数据、工具意图/审批/授权、资源 lease、预算、图、会话、组织版本、模型版本和计划决定。内容类产物通过 Artifact Store 保存，并与元数据关联。

### 11.4 当前没有的 Memory 能力

没有角色私有长期经验库、向量检索/RAG、知识自动刷新、跨项目知识共享、经验去重/冲突解决、遗忘策略、用户可审查的 Memory CRUD，或自动把聊天里的偏好升级为长期规则。

也没有通用加密备份/export/delete CLI、自动保留期限或后台 GC。记录可能含商业代码和业务信息；脱敏不等于数据已全面分类或加密。

## 12. Versioned Fleet Evolution

用户提出“后续 backend change 必须跑 integration test”时，可靠的长期生效路径是生成受支持配置的 FleetPatch，并明确审查应用，而不是让 CoS 口头说“我记住了”。

流程为：用户意图 → CoS 提案 → 结构/路径/版本校验 → semantic/text diff → 用户明确 apply → 新组织代际。rollback 也是一个新的、带审计的操作，不抹去原历史。

当前可演进内容包括受支持的角色指导/自定义目录、workflow、验证配置、声明式 verification skill 等。根 `fleet.yaml`、trust、密钥、硬限制和审计不属于模型可修改范围。

需要区分：

- **FleetPatch**：组织规则演进。
- **Code Patch**：业务代码候选。
- **ModelProfile**：用户状态中的模型配置，走显式管理服务。
- **数据库 migration**：软件版本升级；不是 FleetPatch rollback 的对象。

已有组织历史后不能通过重新 init 偷换注册；模型 profile 可以明确改变未来任务的模型选择，但 Sandbox 变更不应被伪装成模型配置变更。状态迁移向前，不能假定旧二进制可读取新版本数据库。

## 13. Dashboard 与可观测性

`fleet dashboard .` 在另一个前台进程中启动本地 IPv4 loopback 服务，浏览器显示实际持久化的 root/child/Agent、模型选择、usage、审批状态、事件及交付证据。

已支持：

- 本地 token 认证；token 在可信终端显示，浏览器仅放内存，不写 URL/localStorage/cookie。
- 精确 Host/Origin 校验、无 CORS、受限 CSP、本地静态资源；仓库/模型文本作为文本渲染。
- 有界 SQLite query-only 查询，不借观察操作初始化或迁移状态。
- fetch-SSE、逐 Run cursor、重连、去重、显式 resync 和失联提示。
- 任务历史、依赖/等待、Patch/证据检查、桌面/移动宽度显示。
- header 截止时间、查询工作量、连接数、stream 和 Artifact 大小限制。

没有：启动任务、approve、apply、角色编辑等浏览器写操作；没有多用户账号、远程认证、云托管或后台 worker。

不同数据源的读数不是整个系统的全球原子快照。Dashboard 不显示虚构的完成百分比；usage/cost 未知不能变成零，也不展示私有 chain-of-thought。停止 Dashboard 会撤销该服务 token，但不会停止另一个 Session 的 worker。

## 14. 当前支持矩阵与验收边界

### 14.1 功能状态

| 能力 | 状态 | 当前限制/缺口 |
| --- | --- | --- |
| 静态仓库识别与 FleetSpec 提案 | 已实现 | 非完整语义代码索引；不执行推导命令 |
| Bootstrap Canary | 已实现并有真实 Docker 验收 | Fleet fixture，不是业务仓库 readiness 证明 |
| 前台 Session + 一次性 CLI | 已实现 | 无 detach/后台队列；部分管理仍需独立子命令 |
| 执行前计划门禁 | 已实现 | 显式 opt-in，与工具审批分离 |
| 五种 Adaptive Fleet 策略 | 已实现 | 有限策略、节点/并发上限，不是任意工作流 DSL |
| 自定义角色 | 已实现 | 仅受支持 execution kinds，不能扩权 |
| 分角色模型 | 已实现并有离线路由验证 | 实际只接现有 OpenAI 适配路径 |
| 多 Harness | 尚未实现 | 只有 PydanticAI 真实适配器，fake 为测试实现 |
| 精确 Permission Control Plane | 已实现 | 不支持模型授予信任或泛化 allow-all |
| Docker / fake / local-unsafe | 已实现 | 只有 Docker 是当前隔离路径，无远程 Provider |
| Patch + 独立验证 + CompletionGate | 已实现 | 只承认实际且绑定正确的证据 |
| FleetPatch apply/rollback | 已实现 | 只支持受约束的组织配置演进 |
| 持久会话与执行记录 | 已实现 | 有界上下文，不等于长期知识检索 |
| 累计预算和调用记录 | 已实现 | token 按响应记账，不是精确的预付美元硬上限 |
| 本地实时 Dashboard | 已实现并有浏览器验收 | 前台、只读、loopback，不是控制台后端 |
| 真实模型端到端效果验收 | 未执行 | 需用户明确指定凭证/模型/预算并授权 |
| 公开 OSS/PyPI 发布 | 未完成 | 许可证及独立公开发布门禁仍需处理 |
| MCP/GitHub App/插件市场 | 未实现 | 开发工具能用 GitHub，不代表产品已有 GitHub connector |

### 14.2 最近版本的验收记录

以下是已有发布验收记录，不是本次写文档重新运行测试的结果。当前 source/tests/scripts 聚合哈希已复核为 `de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`，与验收记录一致。

| 验证类别 | 已记录结果 |
| --- | --- |
| 默认离线完整分区 | 2283 passed，19 个显式可选 skip；2302 个 collected identity 完整且不重叠 |
| Unit + Contract | 1749 passed |
| Integration | 501 passed |
| 剩余默认 E2E/可选目录 | 33 passed，19 skipped |
| 独立 adversarial 脚本 | 736 passed，和默认测试重叠，不额外相加 |
| 显式真实 Docker | 15 passed |
| fresh wheel/sdist + installed Docker | 2 + 1 passed |
| 真实浏览器 | 17 项断言，通过源码与新安装 wheel 路径验证 |
| 格式、lint、mypy、Schema、JS、构建 | 已通过；mypy 260 文件、92 Schema |
| 合并后包/Schema smoke | 6 passed，构建包哈希不变 |

19 个默认 skip 是 15 个 Docker、3 个安装和 1 个 live-provider；前 18 项已有另行启用的验证，最后 1 项仍未执行。具体耗时、旧失败和修复、清理记录见 [Session-first 验收账本](SESSION_FIRST_ACCEPTANCE.md)。

本次版本的宿主机证据为 macOS arm64/Python 3.14.6，Docker worker 为 Colima Linux 环境。历史版本的 Linux/macOS/Python CI 不能算作这次版本新的跨平台验收。该版本因 Actions 配额限制跳过 hosted CI；既有记录显示没有新增运行，没有降低工作流或保护规则。

## 15. 后续路线图：按 Priority 排序

### 15.1 排序原则

优先解决“用户能否安全、稳定完成真实任务”，其次解决“是否越用越理解这个项目”，最后扩张集成数量。每个阶段都需要成功、失败、取消/恢复和权限负向验收。

- **P0**：真实可用性及公开发布的阻塞点。
- **P1**：形成日常使用和项目长期价值的核心体验。
- **P2**：在契约和安全边界稳定后扩展能力。
- **P3**：只有明确需求和规模证据才投入的平台化方向。

以下均为建议；“需要实现”“需要验证”“需要 owner 决策”分开标识，不应混成一个编码任务。

| 顺序 | Priority | 工作项 | 类型 | 主要依赖 |
| --- | --- | --- | --- | --- |
| 1 | P0 | 真实模型闭环与任务级评估基线 | 验证 + 发现后的修复 | 明确授权的模型/凭证/预算 |
| 2 | P0 | 真实仓库 readiness 与隔离依赖准备 | 实现 + 环境验证 | 现有 Bootstrap/Sandbox/Permission |
| 3 | P0 | 可分发版本与公开发布门禁 | 验证 + owner 决策 | 1、2；许可证、平台/安装验证 |
| 4 | P1 | 项目 Memory v1 与上下文装配 | 实现 | 稳定 Artifact/身份/组织版本；配套 eval |
| 5 | P1 | 第二模型供应商与能力预检 | 实现 + 独立 live gate | 第一供应商真实基线与凭证契约 |
| 6 | P1 | Session 管理体验、错误诊断和用量解释 | 实现 | 复用现有应用服务，不增加第二调度器 |
| 7 | P1 | 数据导出、备份、保留和可控删除 | 实现 | 先明确运行/Artifact/信任的引用关系 |
| 8 | P2 | 第二 Harness 与安全 conformance suite | 实现 + 安全证明 | Runtime 契约、任务级 eval、不可绕过工具边界 |
| 9 | P2 | GitHub/MCP 等受控连接器 | 实现 | 独立外部动作/凭证/审批/重试语义 |
| 10 | P2 | Dashboard 安全交互与组织配置编辑 | 实现 | 精确 review/claim 契约和认证加固 |
| 11 | P2 | 更丰富的任务策略和团队选择评估 | 实现 + eval | 真实任务数据证明现有五策略不足 |
| 12 | P3 | 远程 Sandbox、后台队列与多机器组织 | 分别设计/实现 | 资源身份、租约、网络、远程故障模型 |

### 15.2 P0-1：真实模型闭环与任务级 eval

**为什么第一：** 当前最关键的未知是模型在真实工具循环中是否能稳定规划、修改、验证及正确失败，不是能否再注册一个角色。

建议从少量固定小任务开始：修复 bug、增加回归测试、限定重构、只读分析、错误候选被 Verifier 拒绝；加入拒绝审批、额度耗尽和执行中取消。

需要记录模型/profile/config/代码版本、首轮与修复后成功率、Verifier 误判、权限拒绝、实际 Patch、命令证据、清理、延迟和 reported usage。不同模型对比须使用相同任务合同，不能用发言次数作为质量指标。

验收：

- 在明确授权的 disposable 凭证和预算下，走公开 CLI → 真实模型 → 真实 Docker → 独立验证 → 显式 apply。
- 证明不同角色实际使用选定模型，失败不换备用 key/model，不把模拟命令算真通过。
- 同时展示成功、失败和不确定结果；每项都有 Artifact，不只汇总一个成功率。
- 将发现的问题转成可离线复现的回归；live 测试仍独立 opt-in，不塞进普通 CI。

边界：本次文档不执行这些调用，不寻找环境里的密钥。

### 15.3 P0-2：真实仓库 readiness 和依赖准备

**为什么第二：** 用户项目能被静态识别，但依赖、工具链和验证命令未必能在当前 Runner 中执行。自带 Canary 不能替代这一步。

建议先选少数明确支持的项目类型（例如 Python、Node 小仓库），逐个建立可重放的 readiness 合同，再拓展 Go/Rust/JVM。不是一次宣称所有生态均可运行。

新增能力应包括：

- 区分“检测到的候选命令”和“已确认可执行的验证命令”。
- 展示缺失工具链、锁文件、镜像和依赖原因。
- 把联网依赖准备做成单独的、用户审阅的隔离步骤，不在现有网络关闭的 Docker 路径里偷偷放行网络。
- 记录准备结果、镜像/依赖身份，正式实现和验证回到网络关闭状态。
- 对真实目标仓库运行获准的 baseline checks；已有失败明确记录，不归因给新 Patch。

验收：从一个全新用户环境按指南得到首个实际项目的完整 Patch 和证据；不需要手工篡改状态，不在宿主运行未知安装 hook，准备失败不退回 local-unsafe。

### 15.4 P0-3：发布门禁，而非继续堆功能

已有 wheel/sdist 和安装验证基础，需要在公开宣称支持前补齐该版本的 live-provider、支持平台和首次使用证据，锁定准确的支持矩阵。

许可证、仓库公开、版本 tag 和包发布是 owner 决策/外部动作，不应由 Agent 自行选择。Actions 配额不足时保持本地门禁并标注平台缺口，不修改安全标准来制造“全绿”。

验收：新用户能安装明确版本、完成公开 quickstart、知道需要什么 Docker/模型条件；release notes 不把旧平台 CI 或 fake 模型测试当成新版本真实验证。

### 15.5 P1-1：项目 Memory v1

**建议先做项目共享知识，不先做每个角色私藏一套向量库。** Agent 是临时职责实例，长期价值应沉淀在项目可审查资产中，角色只拿到相关、获准的部分。

建议设计（尚未实现）：

- `KnowledgeRecord`：事实/经验/偏好类型、项目及适用路径、来源 Artifact/文件/commit、创建时间、验证状态、有效版本。
- 状态：proposed、accepted、stale、superseded、rejected；未经验证的模型总结不能直接成为项目事实。
- `KnowledgeService`：查询、审查、失效、替换和明确删除；先做可解释的路径/关键词/类型筛选，需要时再加 embedding。
- `ContextAssembler`：按角色、任务范围和上下文预算选择知识，冻结本次选中记录及 hash。
- 从成功或失败任务生成候选经验，但用户审查或满足明确规则后才提升为长期知识。
- 代码/组织版本改变后标记相关知识过期；注入前做跨项目、权限、来源和 secret 检查。

三类内容不能混用：普通事实记忆、用户偏好、可执行的组织规则。最后一类继续走 FleetPatch；Memory 不允许变成绕过权限的后门。

验收：新 Session 能找到相关已接受知识；无关/过期/其他项目记录不注入；恶意“经验”不能扩权；每个被使用的结论可回溯来源；对照测试证明收益而非仅增加 token。现有 Conversation/Run 历史仍独立保留。

### 15.6 P1-2：第二供应商，而不是任意 endpoint

复用现有 profile/binding，让至少第二种真实供应商通过完整契约，才能证明 BYOK 不止是 OpenAI-only。

需要实现供应商特有的认证、端点、结构化输出、工具调用、usage、错误、超时和取消语义；明确支持哪些能力。不自动迁移旧任务绑定，也不把不兼容模型静默替换为另一模型。

验收：离线 MockTransport 证明每个角色的模型/凭证/目标地址正确；独立授权的 live canary 通过；跨供应商不泄漏凭证和历史；不支持的能力在模型请求前拒绝。

暂不指定供应商或具体模型。选择应依据用户需求和 P0 的实测，而不是在架构文档中预设采购。

### 15.7 P1-3：Session 日常管理和可解释诊断

已有 Session 不需要推倒重做。优先减少用户必须记忆的 ID、状态和外部管理步骤：

- 统一列出“待计划审查、待工具批准、待代码应用、需恢复”，解释它们的区别。
- 将模型/角色/项目知识的管理入口安全地接入 Session，复用显式服务；不是让自然语言自动授权敏感变更。
- 展示“下一步是什么、为什么被拒绝、配置修改会影响哪些未来任务”。
- 聚合 usage、预算余量、重试和等待原因；费用未知就显示未知，不承诺绝对美元硬上限。
- 输入历史/补全需要独立的 secret 和保留策略，不能顺手记录所有用户输入。

验收：新用户在单个 Session 完成常见审查与管理；退出、重复确认、多个终端竞争和失效 review 仍安全；非交互/JSON 兼容不退化。

### 15.8 P1-4：数据生命周期

持久化越多，备份、隐私和磁盘管理越重要；Memory 上线前后尤其如此。

建议提供一致性备份/restore、脱敏 export、空间统计、保留策略和引用感知 GC；删除先显示确切目标和不可恢复影响。不能通过删 Artifact 绕过活跃任务、审批、组织 rollback 或审计一致性。

验收：SQLite WAL 场景可恢复，数据库与 Artifact/信任/安装身份匹配；跨版本不静默降级；活跃引用不被误删；敏感导出有明确边界。加密备份需要真实密钥管理，不等于给压缩包起一个“secure”名字。

### 15.9 P2：扩展能力，但保留控制权

**第二 Harness。** 优先接一个边界可控的实现，验证 RuntimeAdapter 不是纸面抽象。若接 Codex/Claude Code 等已有执行工具的 Harness，必须先证明其原生文件、shell、网络工具被禁用或受 Fleet 统一边界约束；仅把命令包装成 subprocess 不算安全适配。不可信插件还需要独立进程/IPC 和凭证隔离。

**GitHub/MCP 连接器。** 从少量语义动作开始，如读取指定 issue、生成待审 PR 提案。外部写入使用独立 action/resource、CredentialBroker、确认与幂等/结果回读；不要把通用任意 HTTP 或 token 交给 Agent。GitHub PR 是否已创建必须有外部确认，不能只看本地日志。

**Dashboard 写操作。** 先复用服务层，再定义浏览器认证、CSRF/Origin、一次性精确 review、并发 owner 和审计；CLI/browser 同时操作只能有一个赢家。不能因“仅 localhost”省略这些条件。

**更丰富策略。** 只有评估证明需要，才加入额外 plan shapes、角色模板/verification skill 包和更细粒度调度；保持拓扑、输出和验收可校验。不优先实现自由群聊、无限 delegation 或任意 workflow DSL。

### 15.10 P3：远程执行与后台组织

这些是独立工程方向，不应当合成“加一个 Provider”任务：

- Modal/Hosted Sandbox：远程身份、上传/下载、网络策略、凭证、资源费用、断联和清理证明。
- 后台队列：显式 detach/attach、持久队列、单 owner、进程监督、重启和取消协议。
- 多仓库/多机器：项目隔离、权限归属、资源配额、状态同步与审计一致性。
- 托管/企业：多用户认证、RBAC、租户隔离、政策服务、签名导出和隐私边界。

当前前台进程内的取消/恢复合同不能直接外推为远程 exactly-once；发生网络分区时，未知执行仍需保持未知，而不是自动重复请求。

## 16. 建议实施顺序与代码导航

### 16.1 建议的下一批小版本

1. **Reality baseline**：真实模型小任务评估 + 选定项目类型 readiness，修复暴露的问题。
2. **Project continuity**：可追溯 Memory v1 + 对应上下文/质量 eval。
3. **Daily usability**：第二供应商、Session 管理、诊断和数据生命周期，按各自独立验收切片交付。
4. **Controlled extensibility**：第二 Harness/连接器；先安全 conformance，再宣称支持。
5. **Optional scale**：在真实用户需求下分别引入远程 Sandbox、后台队列、托管。

公开发布门禁和回归评估贯穿上述步骤，不必等所有 P1–P3 功能完成才发布一个边界准确的小版本。扩展数量不是成功标准，**Verified Completion Rate、正确拒绝、可恢复性、证据完整性和用户完成首个任务的成本**才是。

### 16.2 主要代码入口

以下路径相对仓库根目录，链接可直接查看实现：

| 模块 | 入口 |
| --- | --- |
| 应用装配、Runtime/Sandbox 注册、状态根 | [bootstrap.py](../src/agent_fleet/bootstrap.py) |
| 前台 Session 与 onboarding | [chat.py](../src/agent_fleet/cli/chat.py)、[onboarding.py](../src/agent_fleet/cli/onboarding.py) |
| Bootstrap / 项目静态识别 | [bootstrap service](../src/agent_fleet/application/bootstrap.py)、[profiler](../src/agent_fleet/adapters/repository/profile.py) |
| 会话历史与摘要 | [conversations](../src/agent_fleet/application/conversations.py)、[conversation_results](../src/agent_fleet/application/conversation_results.py) |
| 主状态机与规划 | [workflow](../src/agent_fleet/application/workflow.py)、[planning](../src/agent_fleet/application/planning.py) |
| 图调度与执行桥接 | [graph](../src/agent_fleet/application/graph.py)、[graph_workflow](../src/agent_fleet/application/graph_workflow.py) |
| 计划门禁/精确审查 | [plan_review](../src/agent_fleet/application/plan_review.py)、[session_review](../src/agent_fleet/application/session_review.py) |
| 模型 profile / Runtime 接口 | [model_profiles](../src/agent_fleet/application/model_profiles.py)、[runtime port](../src/agent_fleet/ports/runtime.py) |
| PydanticAI 工具往返 | [pydantic_ai](../src/agent_fleet/adapters/runtime/pydantic_ai.py) |
| 自定义角色合同 | [role_templates](../src/agent_fleet/domain/role_templates.py) |
| 权限与资源动作 | [permission_policy](../src/agent_fleet/application/permission_policy.py)、[gateway](../src/agent_fleet/application/gateway.py) |
| Docker / 资源恢复 | [docker](../src/agent_fleet/adapters/sandbox/docker.py)、[resources](../src/agent_fleet/application/resources.py) |
| 证据组装/完成判定 | [application evidence](../src/agent_fleet/application/evidence.py)、[domain evidence](../src/agent_fleet/domain/evidence.py) |
| 组织演进 | [evolution](../src/agent_fleet/application/evolution.py) |
| Dashboard | [projection](../src/agent_fleet/application/dashboard.py)、[HTTP](../src/agent_fleet/adapters/dashboard/http.py)、[reader](../src/agent_fleet/adapters/persistence/dashboard.py) |
| 数据库版本 | [migrations](../src/agent_fleet/adapters/persistence/migrations/) |

配套文档：[用户指南](USER_GUIDE.md)、[产品规范](PRODUCT_SPEC.md)、[架构规范](ARCHITECTURE.md)、[安全模型](SECURITY_MODEL.md)、[配置与 Schema](CONFIG_AND_SCHEMAS.md)、[原阶段路线图](IMPLEMENTATION_ROADMAP.md)、[Session/模型/角色 ADR](adr/0007-session-model-role-bindings.md)、[Dashboard ADR](adr/0008-local-read-only-observer.md)、[当前验收账本](SESSION_FIRST_ACCEPTANCE.md)。

本文新增一个面向现状的说明和建议排序，不改写既有发布验收，不修改代码或运行权限，不启动上述未来功能的实现。
