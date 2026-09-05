# Agent Fleet 用户指南

本指南用中文解释产品，保留命令、字段和架构名的 English 原名。目标是让你理解每一步会做什么、授权什么，以及什么证据才算完成。

文档状态：Phase6 已通过本地验收并推送为 `b42cdf9`。Phase7 已完成首轮全新 wheel/sdist 安装和安装后公开 Docker 练习验证；最终冻结检查与跨平台 CI 仍单独记录。确切范围见 [MVP acceptance ledger](MVP_ACCEPTANCE.md)，不要把示例命令当成执行记录。当前没有已获授权的开源许可证，也没有真实模型供应商调用的验收结论。安装包附带本指南全文；跨文档相对链接请在同版本源码仓库中浏览。

## 目录

1. [产品是什么](#1-产品是什么)
2. [安装与环境](#2-安装与环境)
3. [首次初始化](#3-首次初始化)
4. [配置 BYOK](#4-配置-byok)
5. [与 Chief of Staff 对话](#5-与-chief-of-staff-对话)
6. [Adaptive Fleet 如何工作](#6-adaptive-fleet-如何工作)
7. [理解与管理权限](#7-理解与管理权限)
8. [审查交付并应用代码](#8-审查交付并应用代码)
9. [让组织规则随项目演进](#9-让组织规则随项目演进)
10. [暂停、取消与故障恢复](#10-暂停取消与故障恢复)
11. [项目配置与本地数据](#11-项目配置与本地数据)
12. [预算与上下文](#12-预算与上下文)
13. [脚本与 JSON 接口](#13-脚本与-json-接口)
14. [常见问题](#14-常见问题)
15. [验证与贡献](#15-验证与贡献)
16. [实现边界与下一步](#16-实现边界与下一步)

## 1. 产品是什么

Agent Fleet 是本地优先、用户自带模型的 **Agent 组织运行时**，不是把固定数量的机器人放进一个聊天室。

你只与 Chief of Staff（CoS，参谋长）沟通。CoS 提议任务范围、团队和操作；确定性的控制平面负责检查范围、决定权限、调度隔离执行、记录证据。模型不能批准自己的请求，也不能自行更换执行环境。

```text
用户目标 → CoS 提议 → 控制平面验证 TaskSpec / FleetPlan
                         ↓
            按需创建角色实例、分配独立工作区
                         ↓
               ToolGateway → PermissionBroker
                         ↓
                  SandboxProvider 执行
                         ↓
            Artifact / Patch / 独立验证 / 风险
                         ↓
                用户审查并明确应用代码
```

六个关键能力及其实际含义：

| 能力 | 你能观察到的结果 |
| --- | --- |
| Repository-aware Bootstrap | 识别支持的语言、构建系统、命令与仓库边界；生成项目知识和完整配置补丁；先运行隔离 Canary，再发布配置。 |
| Adaptive Fleet | 每个任务选择最小的受支持团队；角色实例按需产生，不存在永远在线的固定“十二人团队”。 |
| Permission Control Plane | 每项操作得到 ALLOW、DENY 或 REQUIRE_APPROVAL；授权可解释、精确持久化与撤销。 |
| Sandbox Abstraction | 执行边界由独立 provider 管理；模型或 harness 不能把失败的 Docker 执行降级到宿主机。 |
| Evidence-first Delivery | 文件、补丁、命令、测试输出、独立判定、风险和证据缺口具有可检查的关联。 |
| Versioned Fleet Evolution | 组织变更先产生 FleetPatch；明确应用和回滚都留下版本与审计记录。 |

**Local-first 不等于所有数据永远离开不了电脑。** 本地保存状态、信任与 Artifact；启用 BYOK 时，选定的任务、代码和项目上下文会通过控制平面的 HTTPS 请求发送给你选择的模型供应商。工作容器不会得到 API key。

## 2. 安装与环境

### 支持的基础环境

- Python 3.12、3.13 或 3.14；Git 2.45 或更新。
- 完整工作流面向 macOS/Linux；不能把 POSIX 文件锁、无符号链接访问和本地 Unix Docker 连接的实现等同于 Windows 支持。
- 真正隔离执行需要本地 Linux Docker daemon，例如 Linux Docker 或 macOS 上的 Linux VM。远程/TCP daemon 不受支持。
- 组织版本发布需要支持原生、同文件系统目录交换的本地文件系统；不支持的元数据或文件系统会被拒绝，不会退化成逐文件覆盖。

当前实际平台证据和未完成的矩阵必须以 [验收账本](MVP_ACCEPTANCE.md) 为准。

### 从源码安装

在本项目 checkout 内：

```bash
uv sync --all-extras
uv run fleet version --json
uv run fleet --help
```

源码工作流使用 `uv run fleet`。下文为简洁统一写成 `fleet`；如果没有将 CLI 安装到独立环境，把它替换为 `uv run fleet`。

可以自行构建 wheel/sdist，再通过标准 Python 包工具安装你明确选择的本地归档文件：

```bash
uv build
uv venv /absolute/path/to/fleet-cli --python 3.14
source /absolute/path/to/fleet-cli/bin/activate
uv pip install /absolute/path/to/agent_fleet-0.1.0-py3-none-any.whl
fleet version --json
```

以上安装可能需要下载声明的依赖，不属于离线测试。不要把源码里的 `.venv` 或 `--no-deps` 解包检查当成全新依赖安装。当前没有承诺 PyPI 发布、公开 runner 镜像或已选择的许可证；不要根据包名安装来源不明的同名产品。

### 选择状态目录

为学习演练使用一个独立的、由自己控制的目录：

```bash
export AGENT_FLEET_HOME=/absolute/path/to/fleet-learning-state
```

仓库和状态目录必须彼此分离，不能互相包含。不要把状态放进 `.fleet/`，也不要让状态目录覆盖整个 home、凭证目录或浏览器配置。跨终端继续工作时必须使用相同的 `AGENT_FLEET_HOME`，否则你会打开另一个独立的本地安装状态。

未设置该变量时使用平台用户数据目录。目录必须满足所有权、权限和非链接检查；不要用全局放宽权限的方式处理拒绝。

### 准备 runner

Fleet 只执行已经存在于本地的镜像，**不会自动 pull、build 或安装项目依赖**。初次准备是操作者的独立操作。

runner v1 随 wheel/sdist 分发：固定 Python3.14 基础镜像的 OCI digest 和五个真实 pytest wheel 的版本/哈希。先激活刚安装 Fleet 的环境，再获取资源目录；不要用另一个全局 Python 查找安装资源。

```bash
python -c "from importlib.resources import files; print(files('agent_fleet').joinpath('assets/runner'))"
docker build --pull -t agent-fleet-runner:local /printed/runner/directory
```

把最后一个路径替换为上一步打印的真实目录。源码用户也可从 `src/agent_fleet/assets/runner` 构建。构建可能联网下载基础镜像和 hash-checked 依赖；运行时 Fleet 只接受已经存在的本地镜像，并绑定实际 image ID。它清除继承的镜像环境配置，由 Docker adapter 逐命令设置非 root、关闭网络、资源上限和挂载。其他项目工具必须事先经你审查后装入独立 runner；不会自动补装。固定输入不保证不同平台/构建器的镜像逐字节相同，也不是没有漏洞的证明。

### 公开学习项目：无需模型 key

安装包带有一个故意保留除零错误的小项目。只复制到**不存在的新目录**：

```bash
python -c "from importlib.resources import files; import shutil,sys; shutil.copytree(str(files('agent_fleet').joinpath('assets/canary')), sys.argv[1], ignore=shutil.ignore_patterns('__pycache__','*.pyc'))" /absolute/path/to/new-fleet-learning
git -C /absolute/path/to/new-fleet-learning init --initial-branch=main
git -C /absolute/path/to/new-fleet-learning add .
git -C /absolute/path/to/new-fleet-learning commit -m "Learning baseline"
export AGENT_FLEET_HOME=/absolute/path/to/separate-fleet-learning-state
fleet init /absolute/path/to/new-fleet-learning --runtime fake --sandbox docker \
  --docker-image agent-fleet-runner:local --trust-mode safe --allow-path src --yes
fleet run "Fix the canary behavior" --project /absolute/path/to/new-fleet-learning --json
```

Git commit 使用你自己的身份；如尚未配置，按 Git 提示设置该练习仓库的身份。遇到 `paused_for_approval`，用返回的 `pending_approval_id` 查看请求并明确批准，再恢复同一 Run：

```text
fleet permissions explain <request-id> --json
fleet approve <request-id> --once --json
fleet resume <run-id> --json
fleet status <run-id> --json
fleet patch show <run-id> --json
fleet patch apply <run-id> --json
```

Engineer 与 Verifier 的请求分别审阅，不能把前一个角色的授权当成后一个角色的授权。最终应看到 `ready_for_review`、`verified_complete=true`、两个独立角色的 `python-test` 命令记录和空的 proof gaps；显式 apply 之前，目标源码保持原样。此项目原有5个测试，修复前1个失败，修复后5个通过。它证明真实隔离验证与交付流程，不证明通用模型推理；真实模型要在另一个明确配置的 BYOK 项目中使用。

## 3. 首次初始化

### 先检查，再预览

选择一个已有提交、工作树干净的 Git 仓库，建议先用没有敏感信息的练习项目。

```bash
fleet doctor --path /absolute/path/to/repo \
  --sandbox docker --docker-image agent-fleet-runner:local --json

fleet init /absolute/path/to/repo \
  --runtime fake --sandbox docker --docker-image agent-fleet-runner:local \
  --trust-mode safe --allow-path src --preview --json
```

`--allow-path src` 是明确审阅过的最大候选改动范围；有多个边界时重复此参数。它不是 glob，也不能由 CoS 自行放宽。若项目没有 `src`，请选择实际需要的规范相对路径。

`doctor` 成功返回仅表示诊断完成；还要检查 `data.healthy` 以及各项必需检查。诊断不是模型供应商在线可用性的证明。

`--preview` 是只读流程，不运行仓库脚本、不解析 API key 的实际值、不迁移状态数据库、不写 `.fleet/`，也不进行模型调用。检查输出中的：

- 仓库根目录与边界。
- 识别出的语言、清单、构建系统及命令来源。
- 命令的 executable、argv、cwd、timeout 和 network 要求。
- 信心不足的识别结果、缺少的命令与警告。
- Project Knowledge 和完整生成文件补丁。
- 请求权限与用户路径上限，而不只是角色提示词。

静态识别是建议和证据，不代表测试已经运行。识别到需要网络或当前 runner 无法执行的命令，也不意味着系统会为它开网或安装依赖。

### 明确应用初始化

确认同一份配置后，移除 `--preview`，添加 `--yes`：

```bash
fleet init /absolute/path/to/repo \
  --runtime fake --sandbox docker --docker-image agent-fleet-runner:local \
  --trust-mode safe --allow-path src --yes --json
```

`--preview` 与 `--yes` 不能同时使用。`--yes` 只确认此次初始化，不是永久批准所有模型操作。

实际顺序是：静态识别 → 单独暂存配置 → 在 Fleet 自己生成的临时 fixture 上执行 Canary → 独立验证 patch、命令和清理证据 → 生成 BootstrapReport → 发布目标 `.fleet/`。

Canary 使用确定性的假模型，不消耗真实模型调用；这里的 Docker 命令是真实执行。它证明 Fleet 的隔离、交付和清理链路，不证明目标仓库的全部功能、依赖或测试都可运行。

只有隔离验证与清理都通过才发布。`fake` sandbox 只模拟命令，`local-unsafe` 没有隔离，两者可用于适用的预览/测试，但都不能满足公开初始化的验证门槛。不要为通过初始化而使用内部测试初始化方法。

初始化后的 `.fleet/` 可以按项目决定纳入 Git。Fleet 允许初始化留下的精确、未被改动的 `.fleet/` 状态；其他用户改动或配置漂移不能悄悄混入后续任务。准备提交时自行审阅和提交，Fleet 不会替你 stash、reset 或 push。

## 4. 配置 BYOK

假模型只能执行受支持的确定性 fixture 场景，不能理解任意软件需求。真正使用 CoS 处理项目，需要在**最初注册该项目时**选择 `pydantic-ai`。

当前支持显式 `openai:<model-id>` 或 `openai-chat:<model-id>`。前者选择 Responses 路径，后者选择 Chat Completions 路径。模型 ID 由操作者明确提供；示例中的占位符不能直接当成可用模型。其他 provider 前缀会被拒绝，不会自动选择替代供应商。

先通过你正常的安全环境配置方式设定 key；不要把 key 放进聊天、命令参数、仓库文件或截图。然后只传引用：

```bash
fleet init /absolute/path/to/new-project \
  --runtime pydantic-ai --provider-model 'openai:YOUR_MODEL_ID' \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker --docker-image agent-fleet-runner:local \
  --trust-mode safe --allow-path src --preview --json
```

审阅后用同样参数改为 `--yes --json`。初始化会验证并解析你明确选择的凭证引用，但 Canary 仍不进行真实模型请求。第一次真实 `run` 或任务型 `chat --message` 才可能调用模型并产生费用。

重要边界：

- `env:OPENAI_API_KEY` 是引用，不是 key 本身；引用保存在 Fleet 用户状态中，不写入 `.fleet/fleet.yaml`。
- 只解析注册时明确选择的引用；环境中的其他 key 不会成为默认 fallback。
- Provider endpoint 固定在支持的官方边界；`OPENAI_BASE_URL`、代理等环境值不能把 key 重定向到任意端点。
- 实际 key 不被挂载进容器，不允许模型读取，也不作为项目配置或 Artifact 留存。
- 项目一旦已有组织版本头，不能通过再次 init 改 runtime、模型、credential reference 或 sandbox；移动 `.fleet/` 也不能绕过这个约束。需要不同受保护配置时，保留旧项目和状态，创建独立注册。
- 在同一个已记录的环境引用下轮换 key 的**值**不需要修改组织配置。换成另一个引用名称是不同操作。

本地离线 FunctionModel 测试验证接口、输出检查和控制流，不等于真实供应商可用性或模型质量验收。当前未提供/使用实际验收凭证。

## 5. 与 Chief of Staff 对话

```bash
fleet chat /absolute/path/to/repo
```

它选取该项目最近的对话；显式 `--conversation <conversation-id>` 可以重开指定对话，`--new` 创建一个新对话。对话与项目的注册身份绑定，不能拿其他仓库的 conversation ID 来工作。

一个更容易验证的请求：

> 修复后端除零错误，只修改 src/calculator。除数为零时返回既定错误；保留正常除法行为。按项目当前验证要求执行，并交付完整 patch、独立验证与剩余风险。

这段自然语言是任务意图，不是扩大路径权限的授权。CoS 的 ScopeDecision 必须受用户上限、项目配置和受支持角色约束。

交互模式支持：

| 命令 | 含义 |
| --- | --- |
| `/help` | 查看真实支持的交互命令。 |
| `/status` | 查看当前 turn/run、计划、结果和暂停信息。 |
| `/artifacts` | 查看当前任务的交付记录。 |
| `/permissions` 或 `/permissions <id>` | 列出或解释当前上下文的权限。 |
| `/approve <request-id> --once` | 批准这一次精确操作；其他期限见权限章节。 |
| `/deny <request-id>` | 拒绝当前请求。 |
| `/resume` | 在批准后恢复当前任务。批准本身不会偷偷恢复。 |
| `/cancel` | 取消当前任务并等待受控清理。 |
| `/exit` | 退出；正在执行的本地任务先被取消和清理，而不是转成后台 daemon。 |

一个对话同一时间只运行一个任务，不会自动排队你在忙碌时发出的新目标。Ctrl-C/退出遵循取消路径；不承诺强制杀死操作系统进程后仍能保留任意模型内存。

脚本式单条消息：

```bash
fleet chat /absolute/path/to/repo \
  --message 'Explain the current architecture and its evidence gaps.' \
  --submission-id architecture-review-001 --json
```

`--submission-id` 是精确重试键：同一对话、相同目标和选项重复提交会返回原来的持久化 turn，不会再次运行模型、重建任务或重置预算。不同目标必须用新 ID。历史重复读取在组织规则变更后仍可检查原始结果，但不能让旧任务重新获得执行资格。

不需要持久对话时：

```bash
fleet run 'Fix the bounded backend validation bug.' --project /absolute/path/to/repo --json
```

运行时默认使用已经审查的注册配置；不能靠 `--runtime` 或 `--sandbox` 临时切换执行边界。

## 6. Adaptive Fleet 如何工作

CoS 提议团队，控制平面验证后创建职责实例。支持五种策略：

| FleetStrategy | 适用场景 | 交付限制 |
| --- | --- | --- |
| `direct` | 只读解释与分析。 | 不创建 Engineer；文本回答不等于代码通过测试。 |
| `single_engineer` | 一个受限 writer 即可处理的改动。 | 没有独立 Verifier 时不能伪装成独立验证完成。 |
| `engineer_verifier` | 需要修改代码并独立确认的任务。 | Verifier 在单独工作区验证，不能把自己的改动并入候选 patch。 |
| `parallel_engineers` | 可划分为明确且互不重叠的子目标。 | 每个 writer 独立 scope/workspace/身份；合并后的完整候选还要重新验证。 |
| `specialist` | 需要 Researcher、Architect 再实施验证。 | Researcher/Architect 当前只读；报告是分析，不是测试证据或授权。 |

不是任务越难就任意增加 Agent。计划还受角色注册、delegation、step、并发、范围、验收条件覆盖和总预算约束。默认生成的 workflow 允许最多两个并行子任务；模型不能自己提升配置上限。

并行任务可通过父 Run 的 `fleet status <parent-id> --json` 查看图结构、依赖、子 Run 和 `pending_child_approval_ids`。批准每个精确子请求后，恢复**父 Run**。不要直接 resume、apply、cancel 或 recover 内部 child Run。

子任务完成顺序可以不同，patch 按稳定顺序汇入父候选。某个子任务的全套测试可能因为另一分支文件尚未加入而失败；最终以合并候选上的独立验证为准。发生冲突会保留证据并停止，而不是静默覆盖其他 worker 的改动。

## 7. 理解与管理权限

权限决定只有三种：`ALLOW`、`DENY`、`REQUIRE_APPROVAL`。看到某个 tool 名称不代表已经有权调用。

Safe 模式允许路径上限内的受支持候选文件操作，但命令执行需要审批。Balanced 允许当前受支持的、精确审阅过的验证命令；`autonomous-sandbox` 当前具有同样的受支持命令上限，不代表任意 shell、网络或宿主机权限。LocalUnsafe 的命令仍需要精确审批。

查看和配置用户信任：

```bash
fleet permissions list --project /absolute/path/to/repo --json
fleet permissions configure --project /absolute/path/to/repo \
  --mode safe --allow-path src --json
fleet permissions explain <request-id> --json
```

批准前至少检查：哪个项目、哪个 Run/Agent、什么 action、哪个资源、完整 executable+argv+cwd、网络模式，以及权限会持续多久。

一次请求只选择一种期限：

```text
fleet approve <request-id> --once
fleet approve <request-id> --run
fleet approve <request-id> --always --scope project
```

- **Allow once**：一次精确使用。逻辑 dispatch 已被占用但结果不明时，重启不会再发一次来“试试看”。
- **Allow for run**：仅匹配该 Run 的范围，不授权兄弟子任务或下一个任务。
- **Always allow exact scope**：保留当前项目的精确规则；改变命令参数、路径、条件或身份可能要求重新审批。不存在普通的“永远允许所有内容”。

批准之后明确恢复：

```text
fleet resume <run-id>
```

持久化 chat 可用对应的 `/approve` 与 `/resume`。两种界面最终使用同一个权限控制平面。

拒绝、解释、撤销：

```text
fleet deny <request-id> --reason 'This command is outside the reviewed need.'
fleet permissions explain <rule-id> --json
fleet permissions revoke <rule-id> --json
fleet permissions reset --project /absolute/path/to/repo --json
```

撤销不会删除审计历史，也不会撤回一个已经完成的外部效果。`reset` 撤销项目 grant/rule，保留模式与路径上限；因此 Balanced 的默认允许不一定因撤销某条规则而消失。若要让后续命令重新审批，明确切换 Safe。

仓库权限请求、提示词和 FleetPatch 都不能覆盖硬拒绝：例如读原始 secret、关闭审计/隔离、批准自己、挂载 home/宿主根目录/Docker socket，或获取 root 权限。

## 8. 审查交付并应用代码

不要只看模型写的“完成”。先检查：

```text
fleet status <run-id> --json
fleet artifacts <run-id> --json
fleet logs <run-id> --json
fleet patch show <run-id>
```

`status` 展示任务、计划、changed files、命令结果、verifier verdict、风险、proof gaps 和完成判定。`artifacts` 列出持久化元数据与内容哈希；它不是任意本地文件读取工具，也没有未实现的 `artifact show` 子命令。

审查清单：

1. 任务范围与验收条件是否准确，是否遗漏需求？
2. 完整 patch 是否只包含预期文件，是否偷偷改测试、构建或权限？
3. 命令是否实际执行，测试/build 的出口码、输出、来源和绑定是否完整？没有 build 命令时应报告缺口，而不是声称 build passed。
4. 是否由不同的 verifier principal 在干净候选上独立执行所需验证？
5. 多个验收条件是否各自链接到当前有效证据？一个笼统 PASS 不能覆盖多个未证明条件。
6. `verified_complete`、remaining risks 与 proof gaps 是否一致？清理是否完成？

`READY_FOR_REVIEW` 表示可以审查；`COMPLETED` 是生命周期状态；`verified_complete` 是根据证据计算的保证。它们不是同义词。FakeSandbox 不运行命令，LocalUnsafe 不提供隔离，即使模型给出 PASS 也不能得到隔离验证完成。

确认后明确应用：

```text
fleet patch apply <run-id> --json
```

这只把控制平面计算并验证绑定的 patch 应用到目标工作树，不会自动 stage、commit、push 或部署。随后按项目正常流程自行检查 Git diff、提交和审查。

如果 Git HEAD、索引/状态、配置或组织版本已变化，旧 patch 会被拒绝。不要清空审计或修改哈希来绕过；保存当前用户工作，基于新的实际状态启动任务。即使组织回滚到旧文件，单调增长的版本仍使旧候选失效。

当前代码交付是有界的 UTF-8 文本 patch。新增普通文本文件受支持；修改/删除二进制文件、危险类型或受保护路径会失败。安全上限不是“支持任意仓库内容”的承诺。

## 9. 让组织规则随项目演进

### 一次可审查的组织变更

对 CoS 说：

> 后续 backend change 都必须跑 integration test。把 backend 定义为 src/backend，使用项目的 tests/integration 命令。请产生可审查的 FleetPatch，不要应用。

实际 backend 路径和验证命令必须来自你的项目。CoS 可以提出声明式要求，不能为了实现这句话偷偷放宽命令、路径或网络权限。

```text
fleet fleet-patch list --path /absolute/path/to/repo --json
fleet fleet-patch show <proposal-id> --json
fleet fleet-patch diff <proposal-id>
```

`show` 检查提议绑定的项目、源 Run、base revision、完整文件变更和 rationale。`diff` 展示语义变化与 unified text diff。提议阶段不会修改活动 `.fleet/`，也不会启动 Engineer 或执行项目命令。

不想接受时，**不执行 apply** 即可。当前没有 `fleet-patch reject/delete` 命令；提议留在不可变历史中。不应用不会改变组织行为，也不需要删除数据库记录。

明确接受：

```text
fleet fleet-patch apply <proposal-id> --json
```

控制平面验证完整目标树、引用、哈希、当前版本、Git 边界和活动资源，单独暂存后一次原生目录交换发布。无关用户改动、仍在运行/暂停的任务、未清理资源或不确定 ownership 会阻止发布，而不是被忽略。

### VerificationSkill 不是权限

受支持的技能是声明式验证要求，例如：

```yaml
apiVersion: agentfleet.dev/v1alpha1
kind: VerificationSkill
metadata:
  name: backend-integration
appliesToPaths:
  - src/backend
requiredCommandIds:
  - backend-integration
```

只有被当前 workflow 的 `verificationSkills` 引用，且 command ID 存在于已验证的 VerificationProfile，文件才成为有效要求。它不是可安装的任意可执行 plugin。

完整提议通常同时包含新增 skill、`workflows/code-change.yaml` 引用，以及必要的 `project/verification.yaml` 命令定义。例如 `python` 与 `['-m', 'pytest', 'tests/integration']` 必须满足准确命令契约、runner 工具、超时和权限上限。只往目录里放文件不会自动生效。

此 YAML 用于解释 schema，不是建议直接编辑已注册组织。让 CoS 生成可审查的完整提议，通过发布器更新。活动树被手工修改后，历史绑定检查会阻止继续执行。

范围采用路径组件重叠：`src/backend` 任务触发该要求，宽泛的 `src` 任务也触发；不相关的 `src/frontend` 不触发。只读任务不要求执行代码验证。TaskSpec 冻结所需 command IDs，EvidenceAssembler 又从不可变配置独立计算一遍，不能靠修改 TaskSpec 省略集成测试。

即使技能要求运行 integration test，Safe 下仍需精确审批。CoS 不能通过技能获得网络、原始 key、宿主执行或改变审批人。

### 回滚不是擦除历史

```text
fleet fleet-patch rollback <current-applied-proposal-id> --json
```

只允许回滚当前头对应的已应用提议。系统生成新的 inverse proposal、operation 和版本，恢复之前的完整组织树，包括受支持的安全附加文件、文件模式和空目录；原提议与应用记录仍保留。

```text
版本 0：backend 只要求 baseline
   → apply：版本 1，要求 baseline + integration
   → rollback：版本 2，恢复 baseline
```

版本 2 的文件可以和版本 0 一样，但不是同一个执行代际。版本 0/1 的旧代码任务不能恢复 apply 资格。已经应用的代码也不会因为组织 rollback 被撤销；代码与组织是两个独立变更面。

重复 `apply` 一个已提交提议只读取原始提交结果，不再次交换目录。不要把重复读取当成重新检查了当前所有清理状态。

## 10. 暂停、取消与故障恢复

先区分“等待用户决定”和“执行结果不确定”，不要对所有错误统一重试。

| 当前情况 | 正常操作 |
| --- | --- |
| `PAUSED_FOR_APPROVAL` | 检查 request，approve/deny；批准后 resume，不继续时 cancel。 |
| `WAITING_FOR_CHILDREN` | 检查父 Run 的子请求；逐项批准后 resume 父 Run。 |
| 正在本进程执行，用户想停止 | `fleet cancel <run-id>` 或 chat `/cancel`，等待受控清理。 |
| 进程崩溃、Run 或 dispatch ownership 不确定 | 确认原 owner 已停止，再做 exact-run recovery。 |
| 组织发布 `prepared` / `recovery_required` | 检查 organization operation，再做独立的 FleetPatch recovery。 |
| 历史记录没有可靠预算或配置绑定 | 保留历史，启动绑定当前状态的新任务，不编造恢复证据。 |

### 运行资源恢复

确认原进程已停止后：

```text
fleet status <run-id> --json
fleet recover <run-id> --confirm-owner-stopped --json
```

只处理这个 Run 与其明确拥有的子资源。这不是继续旧模型推理，不接管未知 owner，也不重新发送已经占用的 command。普通审批暂停用 resume/cancel；保留不确定 graph/chat ownership 的特殊状态需要按报错说明放弃并清理。

不要并行启动多个“恢复者”、手改 lease，或用 `docker system prune`、删除整个状态目录、Git reset 来假装清理成功。若 daemon 不可用，保留具体资源身份，恢复连通后检查该 Run，而不是换 sandbox。

### 组织发布恢复

```text
fleet fleet-patch operation <operation-id> --json
fleet fleet-patch recover <operation-id> --owner-stopped --json
```

两个确认参数名字不同：运行资源用 `--confirm-owner-stopped`，组织发布用 `--owner-stopped`。

恢复观察确切原始/新树方向及持久化 receipt：保持已知原始方向时可放弃准备；已交换到确切新树时补足持久性确认和版本提交。**绝不再交换一次**，也不推断未知用户改动可以覆盖。源代码、Git index、元数据或目录身份无法解释时保持 fence，留给操作者检查。

| `cleanup_complete` | 含义 |
| --- | --- |
| `true` | 此次检查确认所需清理已完成。 |
| `false` | 已观察到清理缺口；同时检查 warnings。 |
| `null` | 此次没有检查；典型例子是已提交 apply 的历史重复读取。 |

如果失败发生在 staging receipt 写入之前，仓库旁可能留下未记入 journal 的私有 `.fleet-publication-*` 暂存目录。保留它和状态，按错误给出的**精确目录**检查；不能编造 operation ID 自动恢复，也不要批量删除相似目录。

这些机制验证本地进程崩溃恢复，不承诺抵抗恶意同用户进程、损坏的内核/daemon、硬件断电或任意网络文件系统故障。

## 11. 项目配置与本地数据

### 两个分离的存储范围

```text
项目仓库/.fleet/                 Fleet 用户状态根目录/
├── fleet.yaml                  ├── state.db
├── agents/*.md                 ├── artifacts/
├── workflows/code-change.yaml  ├── trust/trust.yaml
├── project/charter.md          ├── trust/版本备份与锁
├── project/architecture.md     ├── installation-id
├── project/verification.yaml   └── 工作区及执行资源记录
└── skills/*.yaml（按需引用）
```

`fleet.yaml` 定义注册角色、runtime/sandbox、workflow 和能力上限；项目文本是受限、不可信的指导信息。Project Knowledge 是可追溯的项目上下文，不是全仓库索引服务，也不会自动执行仓库脚本验证自己的猜测。

FleetPatch 支持约定的角色指导、workflow/verification/skill 等组织内容，不允许改 `fleet.yaml`、trust、credential reference、审计或 runtime/sandbox ceilings。完整允许路径和 schema 见 [CONFIG_AND_SCHEMAS](CONFIG_AND_SCHEMAS.md)。

逻辑 ConfigSnapshot 保存被引用的配置闭包；完整 OrganizationTree 另外绑定有界的 `.fleet/` 内容与受支持元数据。只改 README 也可能改变组织代际，即使逻辑配置哈希未变化。

### 保留、备份与隐私

本地保存项目身份、任务目标/摘要、预算、权限请求/规则、事件、patch、代码片段、命令输出、verdict、conversation 摘要、组织提议和历史树。这些记录可能含商业代码或敏感业务信息。Secret redaction 是防泄露措施，不是数据分类系统或绝对不泄露保证。

API key 值不应被持久化；显式引用会保留。不要公开 key、完整数据库、未脱敏 Artifact、信任备份或原始日志。供应商按自身政策处理模型上下文，Fleet 不提供额外的供应商零保留承诺。

当前没有自动保留期限、后台清理 daemon 或通用加密备份/export/delete CLI。`logs`、`status` 和 `artifacts` 是观察界面，不是安全擦除工具。

备份前先停止任务和 publisher，处理确切的未完成资源。使用 SQLite 一致性备份方式，或确认全部进程关闭后保存完整状态集合；运行中只复制 `state.db` 可能漏掉 WAL。保留匹配的 trust、Artifact 和组织文件/receipt；仅拷贝 `.fleet/` 无法恢复本地权限与历史身份。

移除学习数据前先确认 exact-run 和 organization 清理完成，然后只归档或移除你明确创建的练习目录。不要删除生产状态的个别行或 Artifact 来“重置”。文件系统快照、备份或供应商副本仍可能留有数据，普通删除不是密码学擦除。

### 升级与回退

迁移是版本化的前向升级。升级前保留一致备份，旧二进制不应读取新 schema。Phase 6 引入 migration 8，保留旧 Run/Task/对话的 wire identity，并增加独立 organization journal/admission。

FleetPatch rollback 是组织配置回滚，**不是数据库降级**。回退程序必须遵循发布说明、匹配的备份与资源处置记录，不能把旧程序直接放回去继续写新数据库。

## 12. 预算与上下文

父任务及子任务共享累计预算，但不共享授权。默认 RunBudgetLimits：

| 上限 | 默认值 |
| --- | --- |
| Agent invocations | 64 |
| Model requests | 128 |
| Tool calls | 512 |
| Provider-reported total tokens | 262,144 |
| Active execution seconds | 3,600 |

角色 `maxSteps`、workflow 的 repair/concurrency ceiling 和 provider 请求限制还会收紧范围。当前 CLI 没有任意 `--budget` 参数，内部 schema 字段不等于已存在的 CLI 选项。

暂停、失败、取消和重启不清零使用量。Token 根据供应商回报在响应后累计，因此总上限不是硬性的事前费用封顶：最后一次请求可能超过剩余值。费用控制还应使用供应商账户级预算机制。

持久 CoS 上下文是受限摘要，不是无限聊天记录或完整 SDK 会话。当前最多引用八个近期上下文条目，每个 turn 最多八个精选 Artifact 引用，摘要还有 UTF-8 大小限制。历史仍保留在本地，但不保证全部进入下一次请求。

长期要求应成为审阅后的组织指导/验证规则，不只依赖模型“记住上次说过”。指导文本不能改变权限；可靠验收要求必须进入可验证的 schema 和证据链。

## 13. 脚本与 JSON 接口

多数命令支持 `--json`；成功 envelope 包含 `ok`、`command`、`correlation_id`、`data` 和 `warnings`，失败包含稳定的 `error.code`、message、remediation 和 details。

不要从终端颜色猜状态，也不要把返回码零当成 `verified_complete=true`。doctor 返回零仍可能 `data.healthy=false`；历史 apply 查询可能 `cleanup_complete=null`。

命令级错误中，配置/凭证类通常返回 2，仓库/patch 状态类返回 3，审批类返回 4，runtime/provider 类返回 5，其余可能返回 1。脚本优先按 `error.code` 分类。参数解析失败可能直接由 CLI 返回，不一定存在持久 Run。

chat JSON 模式使用 `--message`，不是交互终端。保存输出里的 IDs，它们不能互换：

| 对象 | 查看方式 |
| --- | --- |
| Run | `fleet status`、`logs`、`artifacts`、`patch show` |
| Approval request / trust rule | `fleet permissions explain` |
| Conversation | 在相同项目/状态中用 `fleet chat --conversation` 重开 |
| FleetPatch proposal | `fleet fleet-patch show`、`diff` |
| Organization operation | `fleet fleet-patch operation` |

## 14. 常见问题

### 为什么 init 默认 fake，却不能用 fake sandbox 完成初始化？

Runtime 与 Sandbox 是不同维度。Fake runtime 不调用模型、确定性地提出 Canary 修复；Docker sandbox 仍真实执行命令。FakeSandbox 只记录命令，不提供隔离验证，不能满足公开 bootstrap 的门槛。

### 为什么模型说完成，但 verified_complete 是 false？

检查 proof gaps：可能是假执行、没有独立 Verifier、命令未执行、条件未绑定、候选漂移或清理不完整。不要改 verdict 或删除缺口，应补齐真实证据。

### 为什么 approve 后又问一次？

可能是另一 Agent/子 Run、不同命令/参数、一次授权已用完、规则已撤销，或只批准但未 resume。检查新请求的 exact scope，不要用宽泛授权掩盖身份变化。

### 为什么 rollback 后旧 patch 仍不能 apply？

Rollback 产生新版本，不复用旧代际。旧任务冻结在原规则下，不能借相同文件哈希恢复资格。启动当前版本的新任务。

### 为什么本地存在 Docker image 仍被拒绝？

Fleet 还检查本地 Unix daemon、Linux 环境、镜像身份、环境配置、用户、网络、挂载和资源限制。不受支持的继承环境或缺少真实工具也可能失败。检查 doctor/具体错误，不要改为 privileged 或回落宿主机。

### macOS/Colima 的临时测试目录为什么挂载失败？

VM 必须能访问测试根目录。在已共享的 cache 目录下创建**全新临时目录**，用 `--basetemp` 指向它。pytest 会管理该目录，绝不能把已有项目、home 或 cache 根目录本身当成 basetemp。

### 为什么改 `.fleet/agents/engineer.md` 后不能运行？

角色提示词也是绑定的组织配置。直接改活动树不等于经过版本发布。保存自己的改动并检查原始版本，按审阅/恢复流程处理，不要改数据库哈希或删除状态。后续通过 FleetPatch 更新指导。

### 清理报错，可以重复运行原命令吗？

先查结果是否不确定。已经 dispatch 的命令不能为确认结果再执行一次。使用原 Run/operation 的精确恢复流程；无法确认 owner 停止或无法解释目录变化时，保留现场。

## 15. 验证与贡献

普通测试不使用网络、外部 API key、Docker 或真实模型。贡献者基本检查：

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m agent_fleet.schemas.generate --check
uv run pytest -q
```

从源码根目录执行。只将某个 tests 文件传给 mypy 可能缺少源码与共享 conftest 的分析上下文，不能替代规定的全量检查。

真实 Docker 测试需事先准备本地镜像，设置 Docker opt-in 和镜像变量。完整 suite 包含真实 pytest 的项目命令，stdlib-only runner 不足以通过全部场景。具体命令与准确结果见 README/验收账本，不把历史数字当成最新结果。

真实供应商 smoke 是另一项明确授权、可能计费的验收。setup 已改为真实 Docker，并同时要求 live 与 Docker opt-in、本地 runner、受支持模型和明确 credential reference。未启用 live 时跳过；明确启用但缺少任一前置输入时 setup 失败。实际 live canary 尚未执行，不要发现或复用任意环境 key；跳过不是通过。

发布检查把联网准备与离线安装分开。下面的准备命令只接受不存在的新目录，并记录当前 lock 与 wheel 的哈希；明确使用当前已激活环境的 Python。准备结束后再打开安装测试：

```bash
uv run python scripts/prepare_release_dependencies.py --destination /absolute/path/to/new-wheelhouse
AGENT_FLEET_ENABLE_INSTALL_TESTS=1 \
AGENT_FLEET_TEST_WHEELHOUSE=/absolute/path/to/new-wheelhouse \
uv run --offline pytest -q -m 'installed_distribution and not docker_integration' tests/release
```

普通默认测试不会下载依赖，也不会自动运行这些安装案例。显式安装 opt-in 缺少 wheelhouse、哈希不匹配或依赖缺失时失败，不会借用开发环境中的包。安装后的公开 Docker 练习另需 Docker opt-in。安全回放、CI 矩阵与发布限制见 [发布流程](RELEASE.md)；数据去向见 [数据处理说明](DATA_HANDLING.md)。公开学习项目是打包数据而非运行库，单独执行真实 pytest 检验，不纳入 Fleet 运行库的 mypy 模块发现。

修改跨模块、安全、持久化或公开契约前读 [AGENTS](../AGENTS.md) 与 [ExecPlan 规则](../.agent/PLANS.md)，维护 living plan。分层是 `cli → application → domain/ports`，adapter 实现项目自有接口。模型资源操作必须通过 Gateway/Broker，新 sandbox 不能成为隐式 fallback。

## 16. 实现边界与下一步

核心是本地受控组织：静态 bootstrap、五种有界策略、精确权限、Docker 边界、持久证据、CoS 对话和可审查的组织版本。实际阶段与提交身份见 [验收账本](MVP_ACCEPTANCE.md) 和 [living plan](../.agent/plans/2026-09-05-mvp-completion.md)。

尚不能据此宣称任意模型稳定完成任意需求；Modal/Hosted sandbox、任意 harness/plugin、联网 worker、自动部署已经实现；或能隔离恶意宿主账户、daemon、内核和任意控制平面 adapter 代码。

全新安装、Linux/macOS 矩阵、公开发布、许可证与最终 GitHub merge 都必须有实际记录，不能由示例命令、源码实现或本地测试推断。

推荐学习顺序：只读 preview → 确定性 Docker Canary → 在无敏感信息的独立项目配置明确 BYOK → Safe 审批 → 审查完整证据并 apply 代码 → 提议验证规则 → 检查后续任务要求变化 → 当前头 rollback。

你不需要同时管理所有 Agent。需要管理的是：**范围、授权、证据，以及可追踪的组织规则。**
