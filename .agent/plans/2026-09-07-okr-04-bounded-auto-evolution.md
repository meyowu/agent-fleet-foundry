# OKR 04 — 可撤销的低风险自动知识进化

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

日期：2026-09-07。状态：planned / not started。规划不启用自动行为、不创建定时任务、不替用户批准策略。

## Purpose and user-visible result

对应 `docs/LEARNING_AND_EVOLUTION_OKRS.zh-CN.md` O4，即系统 S7 的有限自动化子计划。本文“总表”均指该子路线；系统开发排序见 `docs/NEXT_OKRS.zh-CN.md`。用户可以明确允许系统在本项目有限范围内自动激活有直接证据、可确定性校验的项目事实，并随时撤销；后续任务可解释使用了什么，错误记录能停止继续传播。

KR：20 个 shadow 策略判定无发布；首个 pilot 冻结 10 个合格事实候选，分四个 batch campaign（3+3+3+1），至少 8/10 按策略自动完成正确激活，全部未授权操作被拒绝或保留人工审查；revoke/重启/竞争/回退演练全部通过，下一次任务入场不使用撤销记录。

“自动进化”在此仅指非执行式项目事实的激活/停用，不包括推断“这样做会更好”的经验建议。自动修改 workflow、验证命令、角色 Prompt、模型或 Sandbox **不在本目标内**；组织 FleetPatch 仍需要人工 review/apply。

## Scope

### In scope

- 用户状态内的默认关闭 EvolutionPolicy、精确 configure/revoke/explain。
- 只读 shadow 决策，之后有限数量/范围/有效期的自动 KnowledgeActivation。
- 可解释的版本、来源、policy/candidate/factual-validation 绑定，原子激活与撤销。
- 不调用学习模型的确定性事实校验；每批候选上限及独立 pilot 总上限。
- 前台 Session 可选的有界后处理；没有后台 daemon 或自动 provider-key discovery。

### Out of scope

- 自动 FleetPatch/code Patch apply、git commit/push、模型选择、trust/预算上限变化。
- 任意指令文本自动升级为强制规则、跨项目学习、无限递归优化。
- 自动激活模型推断出的经验、组织建议或未经直接证据支持的语义总结。
- 将 pilot 的 100% 测试结果宣称为无风险自治。

## Current repository state

当前没有 EvolutionPolicy 或自动知识激活。`OrganizationService.apply/rollback` 和 `SessionReviewService` 是人工授权边界；现有 Task/Run claim、组织 generation 和 plan-review fence 都必须保留。

O2 accepted KnowledgeRecord 代表真实用户决定；O3 PromotionDecision 是对确切候选的收益评估，不是授权，也不能跨 candidate_kind 转给另一条知识。O4 新增 FactualValidationReport 只证明事实与确切来源一致，不宣称改善任务收益。必须建立新的 policy actor/activation 记录，不能伪造一个 O2 的 human accepted 事件。

前置为 O1/O2/O3 的适用成功验收，以及当前代码/规范刷新。O3 未找到有效候选或只有 inconclusive 时可测策略代码，但不可开始自动激活的真实 pilot。

## Security impact

EvolutionPolicy 由用户明确配置，位于用户状态，不能由 repo、CoS、Memory、模型工具或 FleetPatch 更改。policy revision 和有效期只允许用户更新；取消 policy 不抹去过去合法决定。

低风险分类由受限 schema/静态规则和可核验证据决定，不接受 LLM 自称 low risk。第一版只允许确定性提取、具有明确版本/时效的事实字段，例如“Run Y 在 commit Z 的检查 C 返回结果 R”；“后续变更都应执行 C”属于推断/组织规则，仍需人工。自由文本命令、指令、secret/model reference、路径放宽及外部动作不得进入自动知识 payload；检查仅使用已核验的证据 ID。即便事实影响模型判断，实际工具仍受 Broker/Sandbox 约束，不能承诺语义上绝无错误。

candidate、factual validation、policy、catalog head 在提交事务内重查；policy 撤销或换版发生在 commit 前必须生效。只有用户策略赋予的 activation 权限，不生成 ToolIntent 的业务执行 grant。

## Proposed design

O1/O2 确切来源 → 确定性事实候选与 `FactualValidationReport` → `EvolutionPolicy` + `ActivationDecision` → shadow 或 transaction → `KnowledgeActivation` → 下一次 Run 的 O2 catalog snapshot。事实校验绑定 knowledge payload/source/适用代码版本/validator hash；不能借用 O3 的 FleetPatch 报告，也不把来源正确解释为策略收益。

policy 初版包含 exact project/repository、允许事实 schema/路径、校验要求、每 campaign 至多 3 候选、pilot 累计候选/资源上限、有效期、policy revision、启用状态。默认 disabled；用户显式配置后先 shadow，shadow 不产生 active knowledge。首个 pilot 共 10 候选，四批 3+3+3+1，不通过拆批绕过总额度；20 次 shadow 判定独立计数，元数据/时间/存储成本同样预注册。

模式 disabled/shadow/bounded-auto。每个自动激活都有 actor_kind=policy、policy revision、candidate/factual-validation/hash、catalog before/after、时间和幂等键。不写作 human accepted；旧用户接受记录保持原义。ContextAssembler 只接受用户接受或有合法 policy activation 的记录。

激活流程检查：政策有效 → 范围/类型合格 → 来源/时效/冲突检查 → 独立确定性校验通过且完整 → 额度预留 → 原子 compare-and-swap 激活。分类不明/证据不足/未知资源消耗则拒绝自动化或要求人工，不放宽来追求 80%。此路径没有学习模型调用；不能因 auto policy 自动拥有任意模型使用权。

pilot 的 10 个独立事实候选及四批分配在激活结果产生前冻结，重复同证据不算新候选。正确自动激活数/全部 10 个预注册合格候选数为自动完成率，race/error/rejected 不从分母移除；真实来源不足则如实记录 KR 缺口。高风险/推断性候选另行固定测试集，零自动激活。

O3 每 campaign 至多 3 个候选的边界继续保留；本目标的事实校验不占用或冒充 O3 的 72 次收益评估任务。将来若自动提升 10 个推断性知识候选，逐个按 O3 完整评估需另加 240 次任务尝试及辅助成本，须单独立项和授权，本目标不包含。

过期、确切来源失效或与受信证据冲突时，在用户预授权停用范围内追加 deactivation；观测到严重异常立即停止新自动 admission。停止自动激活与取消已有业务任务是不同操作；后者仍要求明确的原有授权。

普通 revoke/deactivate 对下一次 Run 入场生效。已入场 Run 使用自己的冻结 snapshot，不静默重写 Prompt；界面标明旧依据失效，用户可显式取消/重建。业务 hard deny 仍按当前 PermissionBroker 检查，不因冻结 Memory 而保留已撤销权限。

## Public contracts

拟新增 `domain/learning_policy.py` 的 EvolutionPolicy、ActivationDecision、KnowledgeActivation、FactualValidationReport；`ports/learning_policy.py`；`adapters/persistence/learning_policy.py`；`application/learning_policy.py`、`knowledge_activation.py`。报告固定 candidate_kind=knowledge、确切 payload/source/version/validator hash 及校验结果；静态 schema 不能承载任意推断或可执行指令。

拟增加 `fleet learn policy show/configure/revoke/explain`，configure 必须显示精确范围/revision并明确确认；模型不拥有这些命令。首次 policy 和从 shadow 升级 auto 都是用户决定。

复用 O3 Campaign 的有界记账约定，增加 pilot 总账；事实路径不创建 LearningJob 或 proposal Run。activation transactional writes 有自己的精确 ownership，不增加无限自动循环。KnowledgeStore 活跃视图增加 policy provenance，schema/migration 前向兼容。Dashboard 初版最多读取安全状态，不增加写路由；若此包触及 UI，独立浏览器验收必需。

## Milestones

### 4.1 用户 Policy 合同

交付默认关闭、用户 configure/revoke/explain、exact revision 校验和只读表示。不要复用 `.fleet/` YAML 作为权威策略来源。

Acceptance：不存在 policy 时行为与 O2 人工路径一致；repo/agent/self-approval/unknown policy denied；精确项目/路径/类型/额度/过期可测试；合法用户也不能通过此入口改变 Broker/Sandbox 上限。

### 4.2 Shadow mode

冻结 20 个判定场景，覆盖 eligible、不明、冲突、过期、越界、撤销、旧 head、批次/总额度不足、伪造事实报告和冒用 FleetPatch 评估。记录 intended decision 与独立预期，不发生 active-head 或组织修改。

Acceptance：20 个结果全部可解释，意外发布零；不明不是 allow。必须先通过 shadow，再考虑升级权限。

### 4.3 有限自动激活

用户明确启用 bounded-auto 后，在 10 个冻结合格的直接事实候选上分四批运行受限 pilot；预先冻结每批 3+3+3+1 及 pilot 总额度。小样本结果不宣称总体可靠性。

Acceptance：至少 8/10 正确自动激活，全部 10 个有结果与原因；所有 active 有 exact FactualValidationReport+policy 身份；高风险/推断性集合全部没有自动发布。每批和 pilot 总额度分别验证，实际学习模型调用为零；模型 mock 返回值不能被当成事实。

### 4.4 停止、撤销和重启

通过并发 configure/revoke/activate、crash 前后、未知事务结果、过期和来源损坏测试。至少三次新进程重启演练，证明不重复 activation/计账、不丢 history，下一次 admission 看不到已撤销记录。

Acceptance：旧 Run snapshot不变，新 Run 使用新 active set；policy revoked 时不自动重新生成同义条目规避撤销；所有 scope/head冲突 fail closed。组织 FleetPatch 从未自动应用。

## Detailed implementation steps

1. 冻结 policy/activation/factual-validation schema、确定性事实白名单、默认 disabled、human/policy actor 区分及每批/pilot 两层上限；`tests/unit/test_learning_policy.py`（拟议）。
2. 在用户状态实现带审计/CAS 的 policy store；新表 migration 顺序由集成负责人分配。`tests/contract/test_learning_policy_store.py` 检验并发/持久/坏数据。
3. `application/knowledge_activation.py` 实现确定性 source→fact 校验、纯 decision 及 shadow 路径，固定资格集合/重复来源规则，不根据输出删候选；伪造来源、过期版本、跨 kind 报告和自由文本指令全部拒绝。
4. 在 O2 store 的事务中统一重查 policy、factual validation、candidate、catalog；原子两层额度消费/activation receipt。未知提交只读回幂等键，不重发不确定动作。
5. `application/context.py` 仅把有效 activation 纳入新快照，记录实际激活身份；现有 required binding 读取不再重新做“latest”检索。
6. CLI 增加明确用户 policy 管理；Session 前台按配置运行一次有界后处理，不递归生成新的学习任务，不默默 detach。
7. 拟建 `tests/integration/test_knowledge_activation.py`、`test_learning_policy_recovery.py`、`tests/e2e/test_learning_policy_cli.py`，负向覆盖伪造 policy/改 prompt命令/越界/自我授权/撤销竞态/预算耗尽。
8. 运行所有共用质量及条件 gates，保存 `docs/acceptance/okr-04-auto-knowledge.md`（拟议），分别报告 shadow、自动 pilot、rollback、未执行 live 和未支持自动组织发布。

## Validation plan

执行总表第 6 节共用门禁，焦点文件建成后：

```bash
uv run --offline --frozen pytest -q -ra tests/unit/test_learning_policy.py tests/contract/test_learning_policy_store.py tests/integration/test_knowledge_activation.py tests/integration/test_learning_policy_recovery.py tests/e2e/test_learning_policy_cli.py
```

还需 O2 context/旧 run upgrade、O3 lifecycle/budget、既有 plan/session/FleetPatch publication、Docker 清理和安装回归。default tests 禁止实际 provider/网络；真实 pilot 需要精确活动授权。只读 Dashboard 若展示新状态，浏览器仍不得拥有 configure/apply 能力。

## Rollback and recovery

用户可 revoke policy 停止新 activation，并在授权范围内停用具体事实；写入新的 catalog revision，历史 activation/validation/来源不擦除。停止自动化不是全局恢复旧数据库或修改已冻结任务。

activation 事务未知时按唯一幂等键、完整 policy/candidate/head 读回；不能以“可能失败”重放消耗。进程崩溃后同一候选不再次计账/激活；不可确定则阻塞新 activation并给确切诊断。旧程序若不理解新 required activation binding，必须拒绝读取。

## Progress

- [x] (2026-09-07) 规划完成；明确有限自动化而非自动授予组织权限。
- [ ] 4.1 用户 Policy。
- [ ] 4.2 Shadow。
- [ ] 4.3 有限激活 pilot。
- [ ] 4.4 撤销/恢复与 KR 验收。

## Discoveries

- 当前 FleetPatch 已有人工权限合同，不能因用户表达长期自动进化愿景而直接删除确认。
- O2 accepted 表示用户接受；自动 policy activation 必须保留不同 actor，避免伪造人类决策。
- 事实来源一致和经验收益是两种不同证据；首个事实 pilot 不沿用另一类候选的收益报告，也不隐式扩大 O3 的评估预算。

## Decision Log

- 2026-09-07：本计划归入系统S7.4；本文对推断性经验/组织发布的限制不排除系统S3/S4/S5/S6各自经新合同批准后的功能开发。
- 2026-09-07：只让可确定性验证的项目事实先自动化，推断性经验、组织及执行权限持续人工。
- 2026-09-07：10 候选分四批 3+3+3+1，并设独立 pilot 总上限；此事实路径不调用学习模型。
- 2026-09-07：候选分母和高风险测试集先冻结，不能靠全拒绝或扩大资格集合让自动化指标好看。
- 2026-09-07：从 shadow 到 auto 需要真实用户配置；规划/模型分数不是授权。

## Outcomes

尚无 Policy 或自动激活实现。完成本目标后只能宣称“有证据和预授权的项目知识自动更新”；全面自动组织发布、多机器自治等仍是未来独立合同。
