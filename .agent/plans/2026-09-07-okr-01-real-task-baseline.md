# OKR 01 — 真实项目可用性与可信任务基线

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

状态：planned / not started。日期：2026-09-07。用户只要求设计 OKR 与执行计划。以下新增文件、命令、类型均为未来实现；不授权现在执行。

## Purpose and user-visible result

对应 [评估与进化子路线](../../docs/LEARNING_AND_EVOLUTION_OKRS.zh-CN.md) O1，同时是系统 S1/S2/S8 的共享评估计划：用户在明确支持的小型 Python/Node 仓库中，从公开入口获得真实 Patch、独立证据和明确失败原因；我们首次测量真实模型任务效果，不用默认测试数代替产品成功率。本文“总表”均指该子路线；系统排序见 `docs/NEXT_OKRS.zh-CN.md`，不是先完成全部学习目标才能扩展系统。

目标 KR：24 个独立任务/6 个仓库；12 个封存首轮任务至少 9 个独立通过；3 次冷启动环境演练全部成功且不修改内部状态；每次尝试都有完整 outcome，安全矩阵零误报成功。阈值是首轮建议目标，见总表的冻结和校准规则。

## Scope

### In scope

- 冻结任务/环境/模型/预算/评分 manifest 与可重算 OutcomeRecord。
- 对选定仓库做只读 readiness 和明确批准的 network-off baseline checks。
- 复用公开 bootstrap/session/审批/patch apply，建立离线测试和获准后的 live 活动。
- 预加载、可核验的 Python/Node 镜像与依赖准备说明；缺失环境如实阻塞。

### Out of scope

- 自动下载依赖、开放 Docker 网络、宿主执行任意项目代码或新供应商。
- Memory、自学习、后台 eval scheduler、外部反馈连接器、公开发布。
- 以消除审批数量为 UX 目标；把测试 fixture 初始化暴露成普通用户入口。

## Current repository state

基线 `3fb0971`，schema/migrations 1–10。`application/bootstrap.py::BootstrapService` 已通过 fake runtime + 真 Docker fixture 验证后发布配置；不能证明业务仓库 readiness。`adapters/repository/profile.py::StaticRepositoryProfiler` 是静态分析。

`WorkflowEngine`、`EvidenceAssembler`、`CompletionGate`、`InspectionService`、`PatchService` 已存在。`tests/live/test_provider_smoke.py` 是显式 opt-in，尚未有当前版本 live 接受记录。PydanticAI 仅显式 OpenAI 前缀，模型 profile 冻结到 Run。现有 `application/conversation_results.py` 是确定性结果摘要，不是任务评估框架。

阅读依据：`AGENTS.md`、`docs/PRODUCT_SPEC.md`、`docs/ARCHITECTURE.md`、`docs/SECURITY_MODEL.md`、`docs/CONFIG_AND_SCHEMAS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/SESSION_FIRST_ACCEPTANCE.md` 和已完成的 Session-first ExecPlan。旧文档阶段快照不覆盖新验收。

## Security impact

新的测量层不授予执行权限。ready 检查只读，真正 baseline/eval commands 必须经过既有 ToolIntent/Gateway/Broker/Sandbox。活动不得直接 `subprocess` 执行业务脚本或读取 ambient key。

hidden oracle 放在与候选分离的受信评估 fixture；candidate 无权修改答案/评分器。将它运行在单独受控验证环境，返回有界评分，不给 writer 隐藏答案。人工裁定保留人和依据，不能由候选生成模型自评。

每个 campaign 有总尝试、model request、token/时间限额；根 Run 的原有累计预算仍生效。新的 Run 不得绕过 campaign 总额。未报告费用为 unknown；所有 secret/output 仍脱敏。

## Proposed design

`EvaluationManifest` → `ReadinessReport` → `EvaluationCampaign` → 每次公开 Run → 独立检查 → `OutcomeRecord` → `EvaluationReport`。

manifest 记录 task/repo/commit/split、允许路径、当前成功合同、命令身份、镜像/依赖、模型 profile 与预算、oracle digest。24 首轮 + 4 个任务各追加 2 次重复，共 32 次，详细 cohort 见总表。

OutcomeRecord 保存产品 verdict 和独立 outcome 两个字段，不能互相替代。保留环境/模型失败、预算耗尽、cancel、未启动和未知。后续用户反馈另加记录，不改过去事实。用户接受和功能正确分列。

执行工具以 preflight、dispatch-reserved、running、settled/unknown 记录确切 task-attempt/run identity；恢复只读回结果，不自动启动 unknown attempt。评分器纯计算，可从同一记录重新生成相同结果。

只读 readiness 不触发依赖安装。可执行检查按显示的 CommandSpec 逐项批准，网络仍关闭；环境准备由独立获准步骤完成并核验 manifest，不在此包引入网络代理或联网 Sandbox。

## Public contracts

拟新增：`domain/outcomes.py` 的 OutcomeRecord/OutcomeKind、`domain/evaluation.py` 的 EvaluationManifest/Campaign/Report、`domain/readiness.py` 的 ReadinessReport。字段变动须先生成 schema 并定义上限。

拟新增 `fleet readiness [path]`（只读）和显式 `--verify`（走既有授权），命令名于 1.1 冻结；不能把 `doctor` 的完成 exit 0 当 healthy。CLI 复用稳定 JSON envelope，unknown 不是 false success。

拟增加 `scripts/run_project_evals.py --manifest <file> --mode fake|live --output <new-dir>`。live 模式要求独立明确模型/凭证引用/预算授权；当前不存在，不可先运行该命令。manifest 使用逻辑路径和 hash，不嵌入凭证值。

新增 store 只通过 Ports，先保存 outcome artifact 和索引；需要事务/恢复状态时增加按实际合并顺序编号的迁移。历史 Run JSON 无新增强制默认字段；不改旧历史哈希。

## Milestones

### 1.1 测量与 Outcome 合同

交付：domain schemas、fixture manifest、评分器、活动 budget/claim 合同。实现负责人负责新 domain 和纯评估模块；独立验证者负责分母、重复、失败分类和防择优审查。

Acceptance：从固定 records 重算一致；provider failure/timeout 不丢失；不把 repeated attempts 当独立任务；NOT_RUN 不得变成功；manifest 冻结后变化生成新版本。live 尚未执行也可完成此包。

### 1.2 真实仓库 readiness

交付：`application/readiness.py`、`ports/readiness.py`、CLI 注册及两个受控环境 fixture，复用 profiler/config/Sandbox preflight。不得在 readiness adapter 私藏命令执行器。

Acceptance：缺工具/依赖/命令不明都可解释；只读没有状态/代码/容器副作用；verify 使用准确授权，实际失败保留；自带 Canary 成功不能覆盖项目 baseline 失败。

### 1.3 离线公开闭环与故障矩阵

交付：`application/evaluations.py`、脚本、case fixtures 和故障注入 tests。活动启动/结果回读/重启单次所有权落地后才可 live。

Acceptance：fake/MockTransport 测试成功、denial、timeout、budget、cancel、provider error、未知 dispatch 和冷启动；Docker 另行 opt-in，结果强度不混用。所有失败有 receipt；原仓库只在明确 apply 后改变。

### 1.4 受授权真实测量与结果报告

前置：1.1–1.3 全过；明确实际环境、模型引用和活动预算已获准。先跑已有 `tests/live/test_provider_smoke.py` 的 canary，再跑冻结 cohort。

Acceptance：32 条 cohort 尝试记录、24 个独立任务、12 个首轮 holdout 原始 x/n；额外 1 次 live canary +3 次冷启动任务独立编号，不重叠且不进入该成功率分母，36 次尝试都在明确获准的活动预算中。公开初始化的 fake-runtime Canary 单独计时间/资源。冷启动使用新的状态/仓库副本/安装环境，记录操作者身份（可为同一人，不能称 3 个独立用户）；将原仓库/数据授权和 dependency preparation 从计时起点中单独列出。KR 门槛不满足则 O1 未验收。

## Detailed implementation steps

1. 冻结 manifest、评分/排除/重复规则和 OutcomeKind；新增 `tests/unit/test_evaluation_metrics.py`、`test_outcomes.py`（拟议）。
2. 增加 outcome port/store 和 source Artifact 校验；保存 key=`campaign/task/repetition`，attempt 注册前 reserve 活动额度，unknown 不回收额度以允许重跑。测试同请求幂等与新请求确实消耗新额度。
3. 在 `application/readiness.py` 读取已有 profiler/config，输出明确不足；verify 通过受控 workflow/ToolGateway 命令路径，不扩展现有 executor ceiling。
4. 在 `cli/app.py` 单写者注册 readiness；`tests/integration/test_readiness.py` 验证只读与验证模式的副作用区别。
5. 构造独立 test repositories 和不可变 oracle；worker 不可写 oracle，最终评分复核 canonical Patch 与最终代码。不要把 raw database copy 当新 Project 注册。
6. 在 `scripts/run_project_evals.py` 只编排获准公开入口，保存 manifest/hash、child Run ID、评分/时间/usage，不构造第二个 agent runtime。
7. 补 `tests/contract/test_outcome_store.py`、`tests/integration/test_evaluation_campaign.py`、`tests/e2e/test_readiness_cli.py` 及现有 live/Docker 的合适新增 case（均拟议）。
8. 跑共用门禁、显式环境 gates，生成 `docs/acceptance/okr-01-reality.md`（拟议）；记录 unmet KRs、NOT_RUN 和支持矩阵，不覆盖旧 release ledger。

## Validation plan

遵循 `docs/LEARNING_AND_EVOLUTION_OKRS.zh-CN.md` 第 6 节全部共用命令及适用 Docker/install 门禁。焦点命令在相应 tests 建成后为：

```bash
uv run --offline --frozen pytest -q -ra tests/unit/test_outcomes.py tests/unit/test_evaluation_metrics.py tests/contract/test_outcome_store.py tests/integration/test_readiness.py tests/integration/test_evaluation_campaign.py tests/e2e/test_readiness_cli.py
```

以上文件目前不存在。live 另行 opt-in，使用已有指南的确切环境变量，不把示例当授权。Node readiness 需真实 Node fixture 镜像/依赖验证；未准备则仅称设计/离线逻辑完成，不能宣称 Node 实际可用。

## Rollback and recovery

移除新 CLI 注册可停止新活动，不删既有任务/证据。campaign 关闭只禁止新 admission；在途 Run 按原有取消流程清理。未知 provider/dispatch outcome 留为 unknown，操作员确认 owner 停止后按确切 Run 恢复，不自动补一遍调用。

新增 schema 为前向迁移；备份需一致数据库+Artifact，不能只复制正在运行的 `state.db`。恢复策略先演练，禁止通过清空 DB“修复”重复 claim。

## Progress

- [x] (2026-09-07) 完成规划、指标与安全边界设计；未实施。
- [ ] 1.1 合同与评分。
- [ ] 1.2 readiness。
- [ ] 1.3 离线/资源验证。
- [ ] 1.4 获准 live/冷启动测量与 KR 验收。

## Discoveries

- 当前 fake runtime + 真 Docker canary 只证明系统 fixture；未知真实模型效果是测量缺口，不是已有失败率。
- 预置 Python Runner 不能证明所有 Node 项目可运行；静态 manifest 识别和 execution readiness 必须分离。

## Decision Log

- 2026-09-07：用户明确要求完整系统路线；本计划改为 S1/S2/S8 共享的评估切片，其1.2由S2.1负责，同一实现不重复计数；不限制第二Provider/Harness或其他产品主线的排序。
- 2026-09-07：先在当前供应商建立基线，不把 provider/model 变更混入后续 Memory 实验。
- 2026-09-07：选择 offline/preloaded readiness 的最小安全范围，联网依赖准备另设授权与技术合同。
- 2026-09-07：32 次尝试是小样本 pilot，不宣称产品总体 75% 成功率。

## Outcomes

仅计划就绪，O1 功能与测量 KR 全部未完成。实际开始时先刷新 checkout、依赖/模型权限和本计划，不把当前用户的规划请求当成 live 调用或提交授权。
