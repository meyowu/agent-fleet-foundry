# OKR 03 — 有证据的复盘与经过评估的组织改进

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

日期：2026-09-07。状态：planned / not started。本文仅设计，不授权学习调用、实验、发布或 commit。

## Purpose and user-visible result

对应 `docs/LEARNING_AND_EVOLUTION_OKRS.zh-CN.md` O3，即系统 S7 的评估式改进子计划。本文“总表”均指该子路线；系统开发排序见 `docs/NEXT_OKRS.zh-CN.md`。用户能看到“哪些重复问题支持这项经验、候选改变什么、与旧组织比较的收益和回归是什么”，再决定是否应用，而不是只收到一段自我表扬的复盘。

KR：3 个重复问题各有一份有界候选和实验；至少一个达到事先冻结的改善目标；所有获准候选按类型沿既有 FleetPatch 人工 review/apply 或 O2 人工知识接受路径，保留版本和恢复证明。无收益/未知时提案可存在，但结果 KR 不算完成。

示例（未来）：`fleet learn propose <run-id>` 生成 LearningJob 和候选；`fleet learn evaluate <candidate-id> --manifest <file>` 运行获准实验；报告只建议，组织应用仍使用现有 `fleet fleet-patch diff/apply`，知识应用使用 O2 的人工接受路径。

## Scope

### In scope

- 独立 LearningJob、明确模型绑定、空工具目录、预算与不可重放所有权。
- 从 O1/O2 的过去证据生成 RetrospectiveProposal 和一个可证伪候选。
- baseline/candidate 在独立 fixture 的 old/new 配对评估。
- 独立 PromotionDecision、Artifact 报告、按候选类型人工发布组织或知识版本。

### Out of scope

- 自动应用 FleetPatch、自动修改权限/模型/预算/凭证、模型训练。
- 常驻反思 Agent、无限候选搜索、把所有历史/客户数据发送给模型。
- 用相同模型自评作为独立评分，或把测试 oracle 当可演进配置。

## Current repository state

`OrganizationService.propose` 校验当前组织 admission/context 并保存 immutable proposal；`apply/rollback` 明确是用户授权入口，不是模型工具。`evolution_context.py` 生成有界组织提案输入。

`SqliteRuntimeBudgetStore.begin_attempt` 要求 RUNNING Run、stage/Agent 身份；`ModelProfileService.for_run` 绑定 root Run/CoS；现有 RuntimeOutput 和 role dispatch 是封闭合同。不能复用 completed Run 来“免费复盘”，也不能把 evaluator 强塞成新的 researcher role。

O1 提供 EvaluationCampaign/Outcome/指标，O2 提供 source history/KnowledgeSnapshot/ContextBinding。本包实施前二者需达到相应发布验收；纯设计可以提前。阅读规范同 O1，另读 `ports/runtime_accounting.py` 和当前模型/计划/组织 ADR。

## Security impact

学习 job 是不可信输出的分析调用，不给业务写工具、approval/publish 能力或原始密钥。每次读取本项目 bounded source，验证 Artifact/secret/UTF-8/身份；必要的模型请求仍在已批准 provider 端点。

生成者与评估者职责分离；独立 verifier/oracle 的要求与文件不在 candidate 修改范围。候选不能降低测试条件以获得更高分。评估代码在与用户 checkout 分离的受控环境执行，permission/命令/cleanup 仍走既有系统路径。

模型切换、Memory 更新、预算增大都必须固定或列为独立实验变量；否则不能把改善归因给组织策略。

## Proposed design

`LearningJob` 冻结 source Run/Artifact/highwater、knowledge snapshot、prompt/extractor 版本、learning model binding、预算策略；状态 pending → running → succeeded/failed/cancelled/recovery_required。claim 不凭 TTL 失效；未知结果不自动重复 provider 调用。

新增 `LearningJobAccounting`/store，复用现有 request reservation、unknown 和脱敏原则但不放宽原 Run accounting 条件。`EvaluationCampaign` 总账累计复盘、候选、old/new 所有根 Run 和重试；每个 Job/Run 局部预算与活动上限取更严格者。先 reserve，再发请求；重启不重置活动账本。

定义单独的 `LearningInvocation → RetrospectiveProposal` 受限 adapter 合同，和业务 `RuntimeAdapter.invoke` 区分。真实适配器复用已固定的 provider 安全传输/usage 验证，不暴露 native tools；不能重新实现一个漏掉 endpoint/secret 防护的 client。先 fake/deterministic，再显式 opt-in PydanticAI analysis adapter；这不是新增供应商或任意角色。

单 job 初版最多一份候选；每活动最多 3 个候选，单次 job 不递归启动下一个。候选先记录 observation、假设、支持/反例、适用范围、预期改善、风险和 exact diff；EvidenceBundle 保持原样。CandidateDescriptor 明确 `candidate_kind=fleet_patch|knowledge`、被评估内容/subject/baseline hash；PromotionDecision 只能评价该确切内容，不跨类型或换字节复用。

FleetPatch 来源桥接必须在评估前完成：LearningJob 输出 tentative 建议 → 用户明确发起新的正常真实项目 CoS proposal Run → 现有 `_scope/OrganizationService.propose` 在该 Run 当前 admission 下生成正式 proposal → 冻结 proposal/before/after tree 与 LearningJob source 链 → 对这份确切提案评估。LearningJob/evaluation Project ID 不能冒充 `source_run_id`，不能重启 completed Run 或伪造人类事件。若规范化后的提案不同于 tentative，评估对象以冻结后的正式提案为准；评估后禁止重新生成“类似”提案来继承分数。

knowledge 候选通过 O2 提案服务形成 exact KnowledgeRecord revision，绑定 LearningJob 与原始证据，不走 OrganizationService。它的实验仅改变这条知识内容，组织/model/其他 Memory 固定；FleetPatch 实验仅改组织、全部 Memory 固定。三个问题类型于活动开始前冻结，不能看到结果后换类型。

实验采用 `EvaluationSubjectBinding` 绑定原项目/配置与新的隔离 evaluation Project/Run：复制需要的受审查内容，不复制原数据库或冒用真实 Project ID。来源知识按允许范围形成投影；evaluation 产物默认隔离，不进入业务 Memory，防止答案回流。

决策 pending/evaluating/improved/no_benefit/regressed/inconclusive；完整但不足改善门槛为 no_benefit，缺失/未知/矛盾为 inconclusive，二者均不晋级。只有完整、同合同对比的结果才能 improved。PromotionDecision 不等于发布权限。输出测试建议不新增 command grant。人工 apply 前再次核对真实组织 head；评估后发生配置变化则 stale，不重定位到 latest。

## Public contracts

拟新增 `domain/learning_job.py`、`domain/learning.py`、`ports/learning_jobs.py`、`ports/learning_runtime.py`、`ports/learning_accounting.py`；`adapters/persistence/learning_jobs.py`、`learning_budgets.py`；`application/learning.py`、`evolution_evaluation.py`；`cli/learning.py`。

LearningModelBinding 明确来自用户选择的 profile revision，不能冒用 `RunModelBindings` 的 root/CoS 假设。没有选择或额度时返回未运行诊断，不读取默认 key。新增 schema/migration 编号在实际合并时确定。

拟新增 `fleet learn propose/evaluate/show/cancel`，所有 effectful 命令有显示范围和预算；默认无后台任务、无自动调用。报告中记录 source/candidate/baseline/rubric/dataset/model/Memory/hash 和实验 split。

正式 FleetPatch 在评估前生成，评估后用独立索引关联 PromotionDecision，不修改已评估 proposal 字节；用户 review 和原 guard 保留。KnowledgeRecord 的人工接受同样核验 exact revision/评估引用。学习历史不写为权限规则。未来的真实组织规则表达能力若不支持候选语义，该候选必须被拒绝或先另立实现包，不能只改 Markdown 宣称执行生效。

## Milestones

### 3.1 Job 生命周期与隔离调用

单写者负责新 store/预算及 provider 边界集成，独立验证者重点 replay/cancel/secret。交付 fake job 全生命周期，真实 analysis adapter 单独审查。

Acceptance：不修改 source Run status；活动/Job 预算跨 restart 正确；缺绑定/unknown response 无 fallback；重复提交只能一个 owner；空工具目录，模型没有发布/命令能力。

### 3.2 有限复盘与候选

选择 3 个真实、由不同任务证据支持的重复问题，每问题一候选。没有三类足够证据就报告数据不足，不把多份同 Run 日志当复现。

Acceptance：每个 claim 有证据或明确为假设；失败原因区分 environment/provider/permission/logic；来源被删除/伪造时拒绝；模型自评分数不能设置 accepted/improved。单活动候选上限和不递归规则可测试。

### 3.3 配对评估

每候选 6 个新任务，old/new 各两次，共 24 次；3 候选最多 72 次。每组两次都通过才算该任务成功；混合结果非成功、缺失结果阻断评估。质量模式至少 5/6 成功且净增 1/6、无新增失败；效率模式两组至少各 5/6，通过失败不获正收益的 token 公式达到 ≥20%，公式和模式冻结见总表。另有最多 3 LearningJob 与最多 3 正式 proposal Run，全部辅助调用计入总授权预算。真实 calls 另行授权，不因计划列出数量就获准消费预算。

Acceptance：manifest/rubric/模型/预算固定；按 candidate_kind 只改变一个变量，其余 Memory/组织固定，相同初始代码，独立 workspace；原始 wins/ties/losses、所有失败/cost 保留；缺样本/指标不全为 inconclusive。达到总表冻结质量/效率目标才能满足结果 KR；安全失败直接阻止建议发布。

### 3.4 人工发布与可恢复证据

对 improved 且被用户选择的候选按类型显示原有 FleetPatch diff 或 KnowledgeRecord revision 与实验依据；用户明确 apply/accept，读回 before/after hashes。FleetPatch 在隔离 fixture 上演练恢复前一组织内容，版本代际仍前进；知识演练 revoke/supersede、保全历史。真实项目 rollback 仍需用户明确选择。

Acceptance：stale head、pending plan、未知 publication owner 都不能绕过现有 fence。评估成功但用户拒绝仍是未发布。产品支持“有效学习”，不意味着每个实验都必须产生发布。

## Detailed implementation steps

1. 在 `domain/learning_job.py` 冻结 job/claim/context/model/预算键、状态及输出类型；`tests/unit/test_learning_jobs.py` 覆盖非法状态。
2. 实现 store/accounting 两个 port 和 transaction adapter，先 fake 重启、计费 unknown、claim loser 测试；不可修改现有 Run budget adapter 以允许 completed run。
3. 在独立 LearningRuntimeAdapter 接入显式 profile preflight/secret/endpoint 扫描；先 mock transport，验证与现有安全路径同等约束；PydanticAI 的 task 输出 union 不接受 analysis result 混入。
4. `application/learning.py` 从 O2 来源生成 candidate Artifact，只输出有界建议；按 candidate_kind 完成正式提案/知识记录的前评估 provenance 桥接，登记辅助调用预算；注册 CLI/显示 usage、取消路径和幂等 key。
5. `application/evolution_evaluation.py` 通过 O1 campaign 创建隔离评估 Project，显式 SubjectBinding 映射来源；共享活动预算，不给 root business Run 增加隐形 descendant。
6. 固定 independent oracle/heldout；evaluate 只能返回证据和评分。组织审批/发布仍由 `OrganizationService` 的用户路径执行，知识沿 O2 人工接受，不增加模型 publish tool。
7. 拟新增 `tests/contract/test_learning_job_store.py`、`test_learning_runtime.py`、`tests/integration/test_learning_lifecycle.py`、`test_evolution_evaluation.py`、`tests/e2e/test_learning_cli.py`，覆盖生成者改 oracle、泄漏 heldout、改预算、自动 apply、取消/资源污染等拒绝。
8. 运行共用/适用的 Docker/install/live gates；生成 `docs/acceptance/okr-03-evolution.md` 和每候选实验账本（拟议），诚实记录无收益与 inconclusive。

## Validation plan

总表第 6 节全局命令和条件门禁适用。新焦点 tests 建成后：

```bash
uv run --offline --frozen pytest -q -ra tests/unit/test_learning_jobs.py tests/contract/test_learning_job_store.py tests/contract/test_learning_runtime.py tests/integration/test_learning_lifecycle.py tests/integration/test_evolution_evaluation.py tests/e2e/test_learning_cli.py
```

还需现有 provider secret/timeout/cancellation、budget、FleetPatch publication/recovery、schema upgrade 和 fresh install 回归。评估软件逻辑 offline PASS 与真实候选收益分开；未获准真实模型时对应 KR `NOT_RUN`。

## Rollback and recovery

不确定 learning job 保留 claim、request reservations 和 source/candidate bytes，显式 owner-stopped 操作可终止和审计，不重新发同一次未知模型调用。清理只触达该 campaign 的确切 fixture/worktree/container。

未发布候选可拒绝/停用，不影响业务配置；已人工发布的组织仍走当前 rollback-as-new-operation。关闭 learn 功能不删除历史 Experiment/PromotionDecision，不改在途 Run 的冻结上下文。迁移只前进，旧客户端不能忽略 required learning references。

## Progress

- [x] (2026-09-07) 完成规划与现有 budget/model/output 冲突审查；未实施。
- [ ] 3.1 独立 job/预算/调用。
- [ ] 3.2 来源复盘与候选。
- [ ] 3.3 独立配对实验。
- [ ] 3.4 人工发布和 KR 结果验收。

## Discoveries

- 现有 completed Run 不能再次 begin_attempt；用“后台总结一下”绕过该条件会丢失预算、所有权和模型绑定。
- 当前 FleetPatch.apply 明确用户授权且受 generation guard；实验分数不是权限，不能直接调用发布接口。

## Decision Log

- 2026-09-07：本计划归入系统S7.3；收益门禁只控制学习路线晋级，不阻止其他系统主线或范围准确的产品发行。
- 2026-09-07：先 deterministic/fake 验证 job 合同，再授权 live，学习不得成为无限额新通道。
- 2026-09-07：实验按 candidate_kind 只改变组织或单条知识，model/其他上下文固定，避免将模型升级或更多 token 的收益误记为进化。
- 2026-09-07：不保证存在有效候选；无收益应阻止结果 KR 和 O4 pilot，而不是降低 oracle。

## Outcomes

仅计划就绪，尚无自动复盘、实验软件或收益结果。O3 通过后的承诺是“能提出并检验改进，用户决定发布”，不是自动授予组织修改权。
