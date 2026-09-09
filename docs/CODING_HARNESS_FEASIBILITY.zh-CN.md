# Codex / Claude Code Harness 可行性审查

审查日期：2026-09-09 UTC。结论：**当前两者均 NOT_ADMITTED，不属于 Fleet
已支持的 Harness**。有值得验证的工具替换路径，但还没有满足本项目的全部执行、
凭证和预算边界；不是认定这些 SDK 永远无法集成。本文是 S3.4 的接口可行性证据，
不是其 live 资格集验收，也不替代优先建设 OpenAI Agents SDK Adapter。

## 已核实的接口

### Codex

官方 App Server 提供客户端执行的 dynamic tools，同时原生命令和文件修改走
独立的审批/执行流程。批准原生命令后，执行仍由服务器负责；不能把一次审批响应
直接当成 Fleet Sandbox 执行凭证。dynamic tools 目前属于实验接口。
[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental)

本地只运行了 `codex --version`、帮助和离线协议 Schema 生成器：版本
`codex-cli 0.153.4`，未启动 app-server、线程或模型请求。生成416个 Schema。
`ThreadStartParams` 实际包含 `dynamicTools`、`environments`、`ephemeral` 和
`allowProviderModelFallback`；其环境字段描述空列表可禁用未作 turn 覆盖时的环境访问，但这不是
“所有内置工具、插件和内部副作用均已被禁用”的运行证据。

`DynamicToolCallParams` 将调用绑定到 thread/turn/call ID；原生命令批准响应
仍是 decision，而非由客户端提供任意执行结果的接口。这两类通道不能混同。
本地二进制 SHA-256：
`a30ec314bbd0e3721632234d07db7c99855db3b9f1e32dbe8c791947f07e7629`。
离线 `ThreadStartParams.json` SHA-256：
`25f490368ec6df52a2a3b82a5469d2413307eb93439121b309f415b5648eee7a`。
生成器输出不是 Fleet 的公共 Schema，也不会加入产品包。

### Claude Code / Claude Agent SDK

官方文档明确区分工具可见性与自动批准：`tools: []` 可移除内置工具并保留自定义
MCP 工具；`allowedTools` 本身不是工具可见性白名单。自定义工具异常可能被转成
模型可见的错误并继续循环，不能直接抛出含秘密的底层异常。
[官方自定义工具文档](https://code.claude.com/docs/en/agent-sdk/custom-tools#configure-allowed-tools)

`canUseTool` 并非无条件覆盖每次工具调用，较早的规则或模式可能提前批准；
官方建议需要逐调用检查时使用 `PreToolUse`。仅添加一个批准回调不能证明无法
绕过 Fleet PermissionBroker。
[官方权限文档](https://code.claude.com/docs/en/agent-sdk/permissions#how-permissions-are-evaluated)

这里没有安装、启动或认证 Claude Agent SDK；结论来自已打开的官方页面，
不是某个已锁定 SDK 版本的行为测试。OpenAI 密钥没有被发送给其他 Provider。

## 对 Fleet 的决定与准入阻碍

下表是根据已核实接口作出的工程判断，不是外部文档对 Fleet 的保证。

| 边界 | 接入前必须证明 | 当前结论 |
| --- | --- | --- |
| 原生工具 | 关闭所有原生执行/文件/网络/插件/子 Agent 路径；仅暴露 Fleet 绑定工具 | Codex 有实验性动态工具路径，Claude 有移除内置工具的文档路径；均未完成固定版本负向测试 |
| PermissionBroker | 整批工具先校验和预留；每个实际副作用只经 Gateway/Broker 执行；SDK 批准缓存不能增权 | 不能直接映射 accept-for-session、允许列表或模式到 Fleet 持久信任 |
| Sandbox | 命令只由 Fleet SandboxProvider 执行；SDK 不能另选主机执行器或原生沙盒 | 包装 CLI 并让其原生工具执行不满足此条件 |
| 凭证 | 精确 Provider/端点绑定，禁止环境/登录态 fallback；秘密不进入 worker、错误、事件或历史 | 未建立固定版本进程、配置来源、遥测和凭证隔离证明 |
| 预算 | 每次物理模型请求在发送前持久预留；内部重试、断线及 unknown 都计入且不自动重放 | 事后 token/费用事件或总预算参数不能独自满足本项目的逐请求账本合同 |
| 恢复与证据 | 精确调用身份恢复、不重复副作用；独立工作区/原始 Patch/命令收据/清理可重算 | 原生会话恢复和最终文本均不能自动接受为 Fleet 证据 |

因此，不新增 `codex` / `claude-code` Runtime 名称、配置别名或看似可用的命令。
不采用批准所有请求、把凭证挂进 worker、允许主机执行或忽略未知请求来绕过缺口。

## 可以重新开启实现的最小实验

1. 单独冻结一个版本、一个无秘密测试仓库及有限预算；先做离线 SDK/协议测试。
2. 禁用原生能力和环境配置注入，只提供 Fleet 自定义工具；从模型、插件、恢复和
   错误路径分别尝试越界，确认未授权副作用为零。
3. 在实际底层传输上验证每次发送前预留、零隐式重试、凭证隔离、日志脱敏和
   whole-batch 校验；不能只断言回调被调用。
4. 通过公共 Runtime conformance 和真实 Sandbox 的命令/补丁/清理证据审查后，
   才允许独立 opt-in live canary 与冻结资格集。任何未知步骤保留 NOT_RUN。

当前优先级不变：先完成可明确注入模型客户端与工具边界的第二 Harness，
再决定是否为 Coding Harness 开启独立实现计划。
