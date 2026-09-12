# Agent Fleet Foundry：评估、Memory 与进化子路线

日期：2026-09-07。基线：`3fb09711851b27b5276d7faddd50bc317e2536fb`。

范围更正（2026-09-07）：本文保留上一版设计，**不再作为整个系统的开发 OKR**。系统总表见 [NEXT_OKRS](NEXT_OKRS.zh-CN.md)，总体执行见 [系统开发 ExecPlan](../.agent/plans/2026-09-07-system-development-roadmap.md)。本文 O1 是系统 S1/S2/S8 共享的评估工作流，O2–O4 是系统 S7 子路线；它们不是多供应商、新 Harness、Dashboard、集成或发布的共同前置。下文“暂缓项”只约束本子路线，不代表系统路线不开发这些能力。

状态：**规划已形成，实施未开始。** 本次仅授权 OKR/执行计划设计，不授权实现、真实模型调用、Docker 执行、网络依赖准备、招募用户、GitHub 写入或公开发布。所有新命令、类型、路径均为拟议合同，不能作为当前功能使用。

## 1. 为什么选择这四个 Objective

系统已有 Session、分角色模型、自定义角色、Docker、精确权限、证据交付、FleetPatch 和只读 Dashboard。下一阶段不应重新实现这些能力，也不应以“接入多少框架、创建多少 Agent”为目标。

建议沿一条产品价值链推进：

```text
O1 可信完成真实任务
       ↓
O2 项目经验可追溯、可复用
       ↓
O3 证明新经验/组织策略改善后续任务
       ↓
O4 用户授权范围内的低风险自动进化
```

这四个目标是连续的验收阶段，不假设固定季度、团队人数或工程速度。建议每个工作包交付后复盘一次，按门禁而不是日期推进。每个包由一名实现负责人负责，另一名未参与该包实现的验证者独立复核；这是未来执行职责，不是当前人员承诺。

### 当前基线

| 项目 | 已知状态 |
| --- | --- |
| 工程验收 | 最近发布记录：2283 默认通过、19 个可选跳过；另有真实 Docker 15 通过、安装 3 通过、浏览器 17 项通过 |
| 真实模型任务成功率、人工纠正量、首个真实项目完成耗时 | `NOT_MEASURED`，不是 0%，也不能从测试通过数推算 |
| Memory 对后续任务的收益 | `NOT_MEASURED`；当前只有有界会话、静态知识和执行历史 |
| 自动经验提炼/候选对比/自动知识激活 | 尚未实现 |
| FleetPatch | 已有提案、人工审查、apply/rollback；不能当成已实现自动学习 |
| 验证环境 | 当前版本宿主证据为 macOS arm64/Python 3.14.6；真实模型和新的跨平台验收未完成 |

精确既有结果见 [验收账本](SESSION_FIRST_ACCEPTANCE.md)。既有 [架构与路线图](CURRENT_ARCHITECTURE_AND_ROADMAP.zh-CN.md) 保持不变；本计划根据后续讨论，将 Memory 与证据驱动进化提升为下一阶段主线。

## 2. OKR 总表

下列百分比是**建议的首轮目标**，不是当前结果或统计保证。O1 的测量设计冻结前可有一次公开的目标校准；冻结后不能因为结果差而换分母、删失败、调低门槛或挑选有利指标。

| Objective | Priority | Key Results | 执行计划 |
| --- | --- | --- | --- |
| **O1：让用户在明确支持的真实项目上得到可信交付** | P0 | KR1.1：6 个小仓库、24 个预注册任务形成完整基线；12 个封存任务至少 9 个被独立验收。KR1.2：3 次独立冷启动环境演练都无需改数据库或内部测试初始化即可完成首个项目闭环。KR1.3：全部尝试都有结果/预算/证据记录，安全负向矩阵没有误报成功或未授权副作用。 | [O1 ExecPlan](../.agent/plans/2026-09-07-okr-01-real-task-baseline.md) |
| **O2：让系统在新 Session 中可靠复用项目经验** | P1，核心 | KR2.1：首个受审查经验集合的来源、版本、适用范围完整率 100%。KR2.2：40 个冻结检索场景中，有关查询 Top-3 命中 ≥90%，全部场景的禁止记录零注入。KR2.3：12 对任务两组各至少 9/12 独立通过，memory 组通过数不下降，按失败不获益规则计分的重复发现/同类纠正减少 ≥30%。 | [O2 ExecPlan](../.agent/plans/2026-09-07-okr-02-project-memory.md) |
| **O3：让经验能形成并验证有收益的组织改进** | P1，依赖 O2 | KR3.1：3 个有证据的重复问题各形成一个有界候选和完整实验报告。KR3.2：至少一个候选在预注册未见任务上达到冻结的质量或效率改善目标，安全门禁全部通过；证据不足必须保留 inconclusive。KR3.3：每个获准候选都有人工审查、精确版本发布及恢复演练，候选生成者不能更改评分标准。 | [O3 ExecPlan](../.agent/plans/2026-09-07-okr-03-evaluated-evolution.md) |
| **O4：在预授权范围内减少经验维护负担，并能及时停止错误进化** | P2，依赖 O3 | KR4.1：先完成 20 个策略判定的 shadow 演练，越权发布为零。KR4.2：首个 pilot 的 10 个有直接证据、确定性校验合格的项目事实候选中，≥80% 无需逐项人工确认即可正确激活，其余仍有可解释结果；推断性经验和组织变更全部保留人工门禁。KR4.3：撤销、失效、回滚和重启竞争测试全部通过；下一次任务入场不使用已撤销记录。 | [O4 ExecPlan](../.agent/plans/2026-09-07-okr-04-bounded-auto-evolution.md) |

### 不把什么算成 KR 成功

- “写了 100 条 Memory”“提了 10 个 FleetPatch”“增加 5 个角色”不是收益指标。
- 少询问必要审批，不是改善；人工时间只计不必要的纠正/救援，不奖励绕过确认。
- Agent 自报 PASS、用户应用 Patch、没有报错，分别不等于独立验证成功。
- “未观察到回归”不等于已统计证明不会回归。
- 拒绝所有任务不能得到高成功率；支持范围内的合法任务失败仍在分母中。

## 3. 测量合同：先冻结，再执行

### 3.1 O1 任务集

拟选 6 个获准使用的小型 Git 仓库，Python/Node 各 3 个；只承诺选定环境，不代表整个生态通用支持。每仓库 4 个任务：3 个代码变更任务（bug fix、测试/小变更、限定重构）及 1 个有事实答案的只读任务，共 24 个。

- development：3 个仓库、12 个任务；可用于诊断和修复。
- sealed holdout：另 3 个仓库、12 个任务；在候选冻结后评分。
- 首轮每任务一次，共 24 次。另预先选 4 个任务追加两次重复，共 8 次；总计 32 次尝试。重复只报告稳定性，不扩大“24 个独立任务”的样本量，也不把最佳一次替换首轮结果。
- 安全/恢复负向测试另列，不进入合法任务成功率分母。
- repository/commit、任务要求、允许范围、模型 profile、预算、镜像/依赖、评分版本、期望行为及命令都进入 manifest。

O1 的一次真实 provider canary 和三次冷启动任务是另外 4 个辅助尝试，单独分配 attempt ID、不与上述 32 次重叠；计划上限共 36 次任务尝试，全部包含在明确授权的调用/token/时间活动预算内。公开 init 自带的 fake-runtime Docker Canary 也计入计算/时间/资源账本，但不伪装成真实模型任务样本。辅助失败要报告，不进入 24 个任务的首轮成功分母。

holdout 的参考答案、隐藏检查、失败分析不能输入生成经验的流程。仓库隔离的 holdout 衡量跨仓库可用性；同项目时间上更晚的任务用于 O2，二者不混称“泛化”。一旦 holdout 用来调试、修改经验或候选，它必须退役为 development；后续声明收益需补充新的未见任务。

### 3.2 成功率、证据和失败

`Verified task success = 独立验收通过的合法任务首轮数 / manifest 中预注册的合法任务首轮总数`。

代码任务的成功须有原始条件、受保护的独立检查、最终 Patch、所需验证、资源清理、显式应用及应用后的检查。只读任务按冻结的事实/来源评分，不能要求其伪造非空 Patch。产品 Verifier/CompletionGate 的结果仍保留，但外部评估 oracle 不直接把它们当答案。

每次尝试区分：verified success、functional failure、environment failure、provider failure、budget/timeout、cancelled、inconclusive。支持范围内启动后的这些失败留在分母。仅协议事先允许、在模型/执行前确定的无效输入可单列排除，并保留确切原因；整个活动在未授权或未启动时是 `NOT_RUN`，不是失败或通过。

同时报告 `x/n`、按仓库结果、第一次成功率、有界修复后成功率、模型/依赖环境和置信区间说明。重复尝试及同仓库任务相关，不能简单当成独立样本宣称显著性。

### 3.3 人工时间、成本和 Memory

记录主动操作时间和端到端时间；区分必要审批、等待和救援修改。未被供应商报告的美元费用记 `unknown`，不得填 0。全部角色、重试、复盘、Memory 创建、检索和评估的 usage 都必须进入活动账本；禁止只计算最后一次成功调用。

O2 的 12 对后续任务使用相同目标、原始代码、模型、预算及固定历史，只改变 memory 开关。预先定义“重复发现/同类纠正”的事件编码及人类复核规则，不能事后凭印象打分。两组都至少 9/12 独立通过，memory 组通过数不得降低；低于门槛不能宣称效率收益。

每对的纠正差值为 `off_count - on_count`：两组都成功的配对保留该差值，其余配对只保留 `min(0, 差值)`，失败/提前退出不能提供正收益。改善率分子为全部 12 对的上述计分和，分母为 off 组全部事件数。若分母为 0，记 `NOT_APPLICABLE`，KR2.3 不据此通过；需预注册新的相关场景，不能临时换指标。

40 个检索场景分为 20 个有明确相关记录、20 个应拒绝/无结果/过期/冲突/越界场景；Top-3 命中分母是前 20 个。零禁止记录门禁应用于全部 40 个场景的每条返回/注入记录：不能一条正确加两条越权也算成功。经验集合需覆盖 ≥12 条真实证据支持的记录；不足时记录缺口，不能为数量编造经验。

### 3.4 候选收益门禁

O3 先记录基线，再在创建候选前冻结一个主指标：

- 质量模式：候选至少 5/6 任务成功、相对基线净增加至少 1/6（约 16.7 个百分点），且没有原本成功的任务变失败；按原始 wins/ties/losses 报告，成本上限仍遵守活动合同。
- 若开发基线已 ≥90%，可在创建候选前改选效率模式：实际配对的两组各至少 5/6 任务成功，无新增失败，按失败不获益规则计算 reported-token 改善至少 20%。每任务汇总两次尝试 token，差值=`old - new`；两组都成功时保留差值，其余只记 `min(0, 差值)`。分子为六任务计分和，分母为 old 组全部 token；unknown/分母为 0 不得通过。复盘/评估成本另计并报告摊销，不用“只看成功案例”节省成本。

每个候选使用 6 个未用于生成候选的新任务，old/new 各两次，共 24 次尝试；三候选最多 72 次，不含另行授权的失败重试。某组一个任务只有两次都独立通过才算该任务成功；一过一失败计非成功并报告混合结果，缺失/未知结果让实验整体 inconclusive。每个 CandidateDescriptor 固定 `candidate_kind=fleet_patch|knowledge`、payload/subject/baseline hash；FleetPatch 模式只改变组织，knowledge 模式只改变确切知识内容，其他模型/任务/Memory/预算/oracle 均固定，不同时改变两个因素。以六个任务为配对单位而非 24 个独立样本报告；小样本达成工程目标只是受限 pilot 信号，不足以宣称普遍统计收益或打开无限自动发布。

任何安全违规、虚假完成、不可核验结果或状态/清理异常阻止发布；结果相互矛盾或不完整为 inconclusive。完整但无退化、低于改善门槛的结果为 `no_benefit`，不得混成缺证据的 inconclusive；两者都不能通过收益 KR。没有候选达到门槛时 O3 结果 KR 未完成，保留无效实验，不制造一个“进化成功”。

O3 另有最多 3 个 LearningJob；FleetPatch 类候选还需最多 3 个用户明确发起的真实项目 proposal Run，在评估前生成符合既有 admission 的确切提案。72 次是评估任务额度，不含这些辅助调用；最多 3 Job/3 proposal Run 的调用、token、时间另列并纳入同一总预算。

O4 第一版刻意只自动激活机器可核对的项目事实，不自动提升“这样做会更好”的推断。它使用新的 `FactualValidationReport`，绑定 exact knowledge payload/source/适用版本及校验器 hash；这证明来源事实一致，不宣称任务收益，也不能借用 FleetPatch 的 PromotionDecision。首个 pilot 共 10 个确切候选，分四个 batch campaign（3+3+3+1），保留每 campaign 最多 3 个和独立 pilot 总上限；20 个 shadow 判定另外计数，全部元数据/时间预算预注册。此事实路径不调用学习模型。若将来对 10 个推断性知识候选逐个采用 O3 完整收益评估，将是另加 240 次任务尝试及辅助成本，必须单独立项/授权，不能隐藏在 O3 的 72 次额度中。

## 4. 可直接领取的工作包

| ID | 最小交付 | 前置依赖 | 验收者检查 |
| --- | --- | --- | --- |
| 1.1 | 冻结任务 manifest、OutcomeRecord、评分/活动预算合同 | 重新核验基线 | 能从同一组 records 重算全部指标；未运行不算通过 |
| 1.2 | 两类仓库的只读 readiness + 受审查的离线 baseline 执行 | 1.1 | 不隐式安装、不改 daemon 网络策略、不在宿主执行项目脚本 |
| 1.3 | 故障注入与公开 CLI 离线闭环 | 1.2 | 请求/退出/取消/审批/清理都有持久证据 |
| 1.4 | 获准的真实模型活动、首次使用演练与报告 | 1.3 + 外部授权 | 完整 32 次记录和 12 个首轮 holdout 结果，无择优删样本 |
| 2.1 | KnowledgeRecord 的来源校验、版本和人工接受 | 1.1；集成验收需 O1 | 经验不能通过写摘要变成证据或权限 |
| 2.2 | 冻结上下文快照、角色筛选与恢复绑定 | 2.1 | resume 不重新读取最新 Memory，跨项目不泄漏 |
| 2.3 | CLI 管理、失效与保留语义 | 2.2 | 撤销不会抹掉已执行任务的历史依据 |
| 2.4 | 40 场景检索 + 12 对后续任务测量 | 2.3 + O1 活动能力 | 记忆来自过去，不含未来答案；成本完整 |
| 3.1 | 独立 LearningJob 生命周期、模型绑定和活动记账 | O1、O2 | 不复用已结束 Run 的预算 owner，不自动读取密钥 |
| 3.2 | 有限证据复盘与 3 个可证伪候选 | 3.1 | 原始证据引用可核验；生成者不授予权限 |
| 3.3 | old/new 隔离评估与独立 PromotionDecision | 3.2 | 评分条件不能被候选改写；封存数据不回流 |
| 3.4 | 按 candidate_kind 人工审查 FleetPatch 或知识、版本发布/恢复与报告 | 3.3 | exact payload 对应确切评估；组织沿用当前 guard，不自动应用 |
| 4.1 | 用户拥有的默认关闭 EvolutionPolicy | O3 | CoS、repo、Memory、FleetPatch 都不能修改策略 |
| 4.2 | shadow 判定与可解释拒绝 | 4.1 | 20 个判定、零实际发布 |
| 4.3 | 项目证据事实的有限自动激活与撤销 | 4.2 全通过 | 10 个事实候选分 3+3+3+1 批；组织与推断性经验仍人工；预算/幂等安全 |
| 4.4 | 重启/竞争/退化演练与有限 pilot 复盘 | 4.3 | 冻结旧任务、新任务不见已撤销版本；异常停止 |

## 5. 排期与并行边界

默认同时只推进一个涉及状态机/安全边界的实现包。稳定合同后，fixture/纯 domain 测试与只读文档可并行；`workflow.py`、`bootstrap.py`、schema 注册和数据库迁移保持单写者。

O1 真模型授权或环境未准备时，可完成离线 plumbing；在 1.1 合同冻结后，可开展 2.1 的纯 domain/store 工作，但不能宣布 O1 完成或跳过 O1/O2 的实效门禁直接发布自动进化。没有授权不是技术成功，也不阻止安全的规划/离线实现。

建议每包流程：冻结 Task Contract → 单 Writer → 焦点测试 → 新鲜独立验证 → 全局验收（适用时）→ 更新 ExecPlan。提交/推送需另行授权；Actions 配额限制继续有效。规划不创建日历、后台任务或新产品 agent roster。

## 6. 共用质量与安全门禁

所有 ExecPlan 的验证步骤须读本节。以下是**未来实施时的命令合同，本次未运行**。先在已准备依赖的环境执行，所有 live/Docker/install 默认关闭：

```bash
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
AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_ENABLE_DOCKER_TESTS=0 \
AGENT_FLEET_ENABLE_INSTALL_TESTS=0 UV_PYTHON_DOWNLOADS=never \
uv run --offline --frozen pytest -q -ra
uv run --offline --frozen python scripts/verify_adversarial.py --output "$fleet_evidence_root/security"
uv build --offline --out-dir "$fleet_evidence_root/archives"
git diff --check
```

`fleet_evidence_root` 必须先分配为新的独立临时目录，不得覆盖用户仓库或现有证据。若分区跑完整测试，保存完整采集身份清单，证明无遗漏或重复。新增 tests 不能仅验证 mock 被调用。

触及资源/执行/上下文路径的包另跑显式 opt-in Docker；触及安装资源/README/USER_GUIDE 的包重建并 fresh install wheel/sdist；触及 UI 需实际浏览器检查。安装使用事先准备、锁定的 wheelhouse。具体条件及命令复用 [用户指南](USER_GUIDE.md) 和 [验收账本](SESSION_FIRST_ACCEPTANCE.md)，不能把 skip 算 PASS。本文和新 ExecPlan 本身不在包清单中，不改 frozen README/guide。

共用 fail-closed 门禁：所有权未知不重放、审批精确且不扩权、active claim 不自动过期、权限/secret/路径负向测试、最终资源清理、预算跨暂停不重置、旧 canonical bytes 兼容。未来迁移按真正合并顺序分配下一个编号，不在四个计划里抢占相同 migration number。

## 7. 暂缓项、开放门禁与退出条件

- 第二供应商：保留后续候选，在 O1 发现现有供应商能力确实阻塞或用户明确需要时单独立项；不边测 Memory 边换供应商来制造收益。
- 第二 Harness、MCP、GitHub App、Dashboard 写操作、远程 Sandbox、后台队列：本轮四个 OKR 均不实施。
- 公开 OSS：许可证、发布目标及 live/platform gate 是独立发布清单；本轮不替用户选择许可证、公开仓库或发布包。
- 自动修改 workflow/验证命令/角色 Prompt：O3 可生成受审查提案；O4 **只自动激活/停用可确定性验证的项目事实**，推断性经验与组织变更仍人工审查，不取消 FleetPatch gate。更广义的自动组织发布需要未来新的明确产品与授权合同。
- 活动预算不足、模型未授权、准备环境缺失：记录 `NOT_RUN/BLOCKED_GATE`，暂停该外部步骤；不搜寻备用 key、降低评估质量或启用 host fallback。
- 数据稀少、实验无收益：继续保留和分析事实，但对应 KR 不算完成。能证明某个改进无效，也是有效实验，不是自动进化成功。

## 8. 当前规划交付状态

- [x] 基于当前代码及既有验收，区分工程基线与未测量产品指标。
- [x] 定义四个 Objective、指标分母、依赖、工作包和安全边界。
- [x] 建立四份符合 `.agent/PLANS.md` 的可维护 ExecPlan。
- [x] (2026-09-07) 五份新增文档的结构、相对链接、代码围栏、标题空行及空白检查通过；两次独立只读闭环审查通过。当前 source/tests/scripts 内容摘要与规划前相同，tracked diff 为空。
- [ ] O1–O4 实施、实效验证和验收：全部尚未开始。

本次没有运行业务格式化、lint、类型、单元/集成/E2E、Docker、安装或真实模型验收；第 6 节命令是未来实施门禁，不是本次结果。没有 commit、push、merge 或 Actions 触发。

下一步建议只启动 **1.1：测量与 Outcome 合同**，先把“什么算做得更好”固定下来，再投入自动学习代码。
