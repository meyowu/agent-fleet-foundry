# OKR 02 — 可追溯的项目经验与上下文复用

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

日期：2026-09-07。状态：planned / not started。只获准规划；所有新增接口和命令为未来提案。

## Purpose and user-visible result

对应 `docs/LEARNING_AND_EVOLUTION_OKRS.zh-CN.md` O2，即系统 S7 的 Memory 子计划。本文“总表”均指该子路线；系统开发排序见 `docs/NEXT_OKRS.zh-CN.md`。新 Session 可以复用“本项目过去发生了什么、哪些经验可信”，每次使用能解释来源、适用路径和版本；Agent 不因有 Memory 就取得新权限。

目标：来源完整率 100%；冻结 40 个检索场景中有关查询 Top-3 命中 ≥90%、所有返回/注入的禁止记录为零；12 对未来任务两组各至少 9/12 通过、memory 组通过数不下降，按失败不提供正收益规则计算重复发现/同类人工纠正减少 ≥30%。精确分母及小样本边界遵循总表第 3 节。

示例交互（拟议）：`fleet knowledge propose <run-id>` → `fleet knowledge show <id>` → `fleet knowledge accept <id> --revision <n> --sha256 <hash>`；之后 Session 展示本次采用的知识来源。第一版 propose 是确定性证据提取，不调用 LLM。

## Scope

### In scope

- 从权威 Outcome/Evidence/事件提取事实性 ExperienceCandidate。
- 用户审查、接受、拒绝、过期、替代、tombstone；不改历史证据。
- 项目范围的关键词/路径/类型检索和可解释 abstention；无需新向量依赖。
- CoS 入场快照、worker 窄化视图、恢复/子节点/修复绑定。
- 经验重复使用的配对测量及隐私/越权/失效负向测试。

### Out of scope

- 自动 LLM 复盘、模型权重训练、跨项目检索、自动发布组织规则。
- 给每个角色一个不受控私有向量库、无限 SDK 历史。
- 通用数据物理擦除/加密备份；此包仅定义引用感知 tombstone。

## Current repository state

基线 `3fb0971`。`ConversationService._context` 只加载最多 8 个 settled turns /32 KiB；`conversation_results.py` 从实际结果生成有界摘要。`ProjectKnowledge` 是 profiler 的静态事实 Artifact，不会自动增长。

`WorkflowEngine._scope` 组装 CoS 的 profile/knowledge/conversation/organization；Engineer/Verifier 和 `GraphWorkflowExecution` 有各自 task/patch/report 输入，目前不存在全局 ContextAssembler。

新绑定要穿过 Run、plan review、conversation、graph、model/evolution admission 的完整身份链；不能只在 Prompt 加一段 Memory。Schema 1–10 的历史 canonical bytes 必须保持，source baseline及初始阅读资料同 O1。

## Security impact

Memory 是不可信事实/建议，不是授权或最终验收标准。来源只接受本项目确切 Run/Artifact/hash，并进行已注册 secret、路径/类型/大小和证据读取校验。模型文本引用 Artifact ID 不证明来源有效。

不可把用户已 apply、工作已通过测试、用户主观反馈混为一个 success flag；失败/取消允许生成有缺口的观察，不能捏造根因或可普遍化建议。

accept/revoke 是可信用户命令，不暴露给模型；repo Markdown 不能激活记录。历史上下文有引用时不物理删除；敏感内容撤销后新 Run 不再注入，旧任务保留确切历史依据并提示，用户可显式取消旧任务。

## Proposed design

`OutcomeRecord + EvidenceBundle + bounded events` → `ExperienceCandidate` → 人工精确审查 → `KnowledgeRecord/version` → 冻结 `KnowledgeSnapshot` → `ContextAssembler` → `RunContextBinding`。

Experience key=`source_run_id + source hashes + event highwater + extractor_version`；重复提取返回同一提案，不生成多条“独立支持证据”。记录 claim、recommendation 分列，证据不足只给 observation。

KnowledgeRecord 绑定 project/repository、scope paths、类型、来源、code/config 有效版本、来源评估、创建时间和 supersedes。状态 proposed/accepted/stale/superseded/rejected/tombstoned，更新采用 CAS 和不可变版本。O2 accepted 必须是真实用户决策。

第一次 CoS 请求前，在已注册项目/用户允许范围内冻结 eligible catalog revision 和候选来源。TaskSpec 形成后从同一快照生成角色/路径交集视图，并在计划门禁前冻结。resume、子任务和 repair 不查询最新记录。缺失/哈希损坏的必需快照 fail closed，不能退回“无记忆但继续执行”。

初版知识上下文建议默认最多 8 条、总计 16 KiB UTF-8（是待冻结新上限，不是当前值）；加上既有历史和输入仍须满足 runtime 总预算。记录排除/截断原因和每条来源，不把全文 Artifact 自动塞进 Prompt。

先只做可解释筛选，不从稀疏数据发明置信分数。冲突时返回冲突和 abstain，不取最后写入者为事实。版本不匹配标 stale；ProjectKnowledge 本体和原 EvidenceBundle 不被新经验覆写。

## Public contracts

拟新增：`domain/experience.py`、`domain/knowledge.py`、`domain/context.py`；`ports/knowledge.py`；`application/experience.py`、`knowledge.py`、`context.py`；`adapters/persistence/knowledge.py`；`cli/knowledge.py`。

拟新增 KnowledgeRecord、KnowledgeVersion、KnowledgeDecision、KnowledgeSnapshot、RunContextBinding；来源及完整上下文 Artifact 不携带宿主路径/credential。新 migration 在实际集成时分配，旧记录省略 absent authority fields。

拟新增 `fleet knowledge propose/show/accept/reject/query/revoke`，精确 revision/hash 使用单独参数并支持 JSON。`query` 只读，`propose` 写候选不调用模型，`accept` 不触发业务 Run。新命令必须标状态并增加 CLI/help/包内指南测试后才可宣称支持。

## Milestones

### 2.1 确定性经验与用户接受

依赖 O1 1.1 的 OutcomeRecord；纯 domain/store 可提前完成，但实效验收依赖 O1。交付 source extraction、不可变版本、CAS 和用户决策。

Acceptance：至少 12 条受证据支持的审查记录覆盖成功、失败和有缺口情形；100% 来源可读回。若不足，报告数据缺口而不凑数；重复 source 不算重复经验；损坏/外项目/secret 拒绝。

### 2.2 ContextAssembler 与执行身份

根负责人单写 `workflow.py`/`bootstrap.py` 及 shared model/store；纯检索 tests 可独立写。冻结 catalog 后按真实自定义角色派生视图，而非把 `backend` 当 `engineer`。

Acceptance：CoS、Engineer、Verifier、specialist、parallel join/repair 均得到恰当范围；任务中途接受新知识不改变当前输入；plan approval/restart 均保留 snapshot；不存在因去掉 binding 而回到更宽的 legacy 路径。

### 2.3 管理、失效与保留

交付 CLI 管理与 inspect 输出、状态过滤、冲突/失效逻辑和 tombstone。拒绝、撤销记录不是删除用户业务文件。

Acceptance：CAS loser 不改 winner；重复 accept/revoke 可安全回读；被历史 Run 引用的版本仍可核验，新 admission 不再选择 revoked；repo/config 改变触发可解释失效，不静默更新旧事实。

### 2.4 相关性和后续任务收益

冻结 20 个相关查询 +20 个无结果/越界/冲突/过期查询；相关命中至少 18/20，全部 40 场景的每条返回/注入记录都须合法且没有禁止记录。另有 corruption/secret/cross-project 安全矩阵，成功率不抵消安全失败。

12 个时间上更晚的任务用隔离副本做 on/off 配对，共 24 次首轮尝试。历史仅含早于任务的经历；模型、预算、目标/代码相同，不给 memory 组未来答案。两组至少各 9/12 成功，on 组成功数不下降；全部主动人工纠正按预定义代码计数，失败配对不能提供正改善，分母为 0 时收益 KR 不适用而非自动通过。

## Detailed implementation steps

1. 建 `tests/unit/test_experience_extraction.py`，由不可变 O1 records 生成候选；在提交事件 highwater 前后新增日志不改变旧提案。
2. 加 store port/SQLite 版本、不可变 audit、索引和引用校验；`tests/contract/test_knowledge_store.py` 覆盖 CAS、重复、损坏与迁移。
3. 建 `application/knowledge.py` 的用户决策与检索，过滤先于评分；测试 candidate 文本不能把 protected action 变 allowed。
4. 在 `_scope` 首次模型边界前冻结，在 TaskSpec 后派生视图；同步 `PlanReviewBinding`、Conversation/graph admission、Run serialization、模型请求上下文和检查服务。新字段非空时强校验，缺失不得忽略。
5. 通过 `graph_workflow.py` 显式传递 descendant context binding，Verifier 不接收 Engineer 原始模型历史；保留当前独立工具和证据路径。
6. 新 `cli/knowledge.py` 与 Session 的只读来源提示；接受/revoke 仍显式管理命令，不做隐式自然语言授权。
7. 加 `tests/integration/test_knowledge_context.py`、`test_knowledge_recovery.py`、`tests/e2e/test_knowledge_cli.py`、`tests/unit/test_knowledge_retrieval.py`（拟议），重跑 legacy/plan/model/graph/evolution 身份回归。
8. 保存 `docs/acceptance/okr-02-memory.md`（拟议）：source collection/snapshot、40 场景结果、12 对 wins/ties/losses、纠正事件原始计数、全部成本与未满足 KR。

## Validation plan

执行总表第 6 节共用命令。重点 tests 建成后：

```bash
uv run --offline --frozen pytest -q -ra tests/unit/test_experience_extraction.py tests/unit/test_knowledge_retrieval.py tests/contract/test_knowledge_store.py tests/integration/test_knowledge_context.py tests/integration/test_knowledge_recovery.py tests/e2e/test_knowledge_cli.py
```

这些是未来文件。本包触及 workflow/上下文，必须再跑原完整 offline、独立 adversarial、真实 Docker 和 fresh-installed 路径；live 配对实验需单独授权。offline retrieval 的 90% 不能证明真实模型已获益。

## Rollback and recovery

用户可停止为新任务选择知识，但已入场 Run 必须保留冻结 snapshot。普通 revoke 只影响后续 admission；若有敏感内容风险，显式取消相关在途任务后另做权限/数据处理，不能改历史 hash 蒙混。

store 决策与引用写入同一事务；crash 后按确切版本回读，不重新接受。tombstone 不意味着物理擦除。新 schema/required binding 防止旧程序默读；需要回退时先停新 admission，保全数据库/Artifact，按前向修复而非删除迁移。

## Progress

- [x] (2026-09-07) 已完成规划；未实施或测量。
- [ ] 2.1 来源/版本/审查。
- [ ] 2.2 context snapshot 与全链路绑定。
- [ ] 2.3 管理/失效。
- [ ] 2.4 检索、安全和实效验收。

## Discoveries

- 当前 CoS/worker context 并非共用装配器；只改 CoS Prompt 会漏掉 graph、repair 和 resume。
- 当前 budget/模型 binding 依赖活跃 Run，不适合任务结束后顺手调用复盘模型；本包先确定性提取，LLM 留给 O3 独立 lifecycle。

## Decision Log

- 2026-09-07：本计划归入系统S7.1–S7.2，原O1–O4编号只表示子路线；Memory不是多Provider/Harness、集成或发行的共同前置。
- 2026-09-07：项目共享、可审查知识优先于 agent 私有长期历史/向量库。
- 2026-09-07：来源、accepted 决策、实际 RunContextBinding 是三个独立合同；知识不授予权限。
- 2026-09-07：初版只人工接受建议性事实；不能从这个计划推导自动 FleetPatch 授权。

## Outcomes

计划已形成，所有实现与收益 KR 尚未完成。O2 通过后才能声称“可追溯地复用经验”；仍不能声称“组织已经自动优化”。
