# Harnessloop

**让长时间运行的 AI agent 任务变得可审计的协议——并且如实说明它强制不了什么。**

[![validate](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml/badge.svg)](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml)

> 🇬🇧 [English](README.en.md) ・ 🇯🇵 [日本語](README.ja.md)

## 长任务里，外部验证在 loop 之外

一个 agent 改完代码之后，真正说明「这次改动行不行」的东西往往不在进程里：
要重新打包、要部署到目标环境、要远程拉起来跑、结果落在另一套数据平台上。

标准的 agent loop 处理这些的方式是——**把它们当日志读**。
agent 看一眼输出，自己决定信不信，然后继续。于是：

- 判定**可以被忽略**，而且忽略不留痕；
- 判定**在远端**，今天被覆盖或重跑之后，昨天那一轮的结论就无从复现；
- 一轮宣布成功时，**没有任何机械的东西**能说「等一下，你自己的记录写着 fail」。

Harnessloop 处理的就是这一段。

## 核心做法：把判定冻进轮次

它把工作切成**轮次**，每轮声明可改哪些路径、会产出什么证据、得到什么结论。
外部系统的判定通过一份**轮内台账**进入这一轮的接受条件。三个动作叠起来才成立：

**① eval 是有稳定 ID 的一等对象。** `RAE-0001` 跨轮可追，不是一次临时调用。

**② 到期集合在写入那一刻被冻进台账。** 这一步是枢纽——它让判定变成**纯轮内**的，
于是「这一轮该不该被接受」不依赖今天外部系统是什么状态。
没有这一步，任何外部判定都会变成跨时间层的比对，而那条路会让历史轮次随远端漂移。

**③ 门拒绝的是「自相矛盾」，不是「结果不好」。** 它不评价外部系统说得对不对，
只拒绝「你的台账写着 fail、你的结论写着 positive」。

> **标准 loop 里，外部判定是一句可以被忽略的话；
> 在这里，它是一条必须被显式否决才能绕过的记录。**

## 一条多阶段流水线长什么样

重型产品（客户端、嵌入式、需要真实部署的服务）的验证往往是**一串系统**，不是一次调用：
打包 → 部署 → 拉起 → 断言，每段一个系统，而且异步。

**这不需要特殊支持：一条流水线 = N 条 eval，一段一条。**

```jsonc
// <goal>/evals.json —— 四段各一条
{"evals": [
  {"eval_id": "RAE-0001", "activation_round": 1, "system": "sys-build"},
  {"eval_id": "RAE-0002", "activation_round": 1, "system": "sys-deploy"},
  {"eval_id": "RAE-0003", "activation_round": 1, "system": "sys-run"},
  {"eval_id": "RAE-0004", "activation_round": 1, "system": "sys-assert"}]}

// <round>/evidence/runtime/acceptance-evals.json —— 这一轮实际跑出什么
{"entries": [
  {"eval_id": "RAE-0001", "outcome": "pass", "frozen_system": "sys-build",  "…": "…"},
  {"eval_id": "RAE-0002", "outcome": "pass", "frozen_system": "sys-deploy", "…": "…"},
  {"eval_id": "RAE-0003", "outcome": "fail", "frozen_system": "sys-run",    "…": "…"},
  {"eval_id": "RAE-0004", "outcome": "skipped", "frozen_system": "sys-assert", "…": "…"}]}
```

这份台账下，一份写着 `Feedback: positive` 的 `decision.md` 会被**拒绝**——
第三段没过。**漏跑同样拦得住**：`frozen_due_set` 里有的 eval，台账里找不到对应条目，一样拒绝。

`frozen_system` 记下每段是对着哪个系统跑的——四段串起来时，
**不记系统就不知道是哪一环挂了**。

**判定结果必须取回并写进本轮 `evidence/`。** 远端记录会被覆盖、清理、重跑；
若轮次判定还指着远端，这一轮的结论就随远端漂移。**取回不是麻烦，是轮次可被重放的前提。**

## 它做不到什么

这一节不是免责声明，是这个项目的设计立场。**机械门读的是 agent 自己写下的文件，
它无法验证动机，而且它明说这一点。**

- **它证明不了 eval 真的跑过。** 手写一个 `"outcome": "pass"` 配一份伪造产物，同样通过。
  它买到的是「可引用、可被对抗评审质问」，不是执行力。
- **它不读评审正文。** 只记录评审发生过、产物在哪份文件里。
- **它不触发也不运行任何外部系统。** 打包、部署、拉起、取数据都由你的会话、CI 或 runner 做。
  **裁判不下场**——这也是它证明不了「跑过」的同一条边界的另一面。
- 它自己发布的文档在边界一节开篇就写着：
  **"The mechanical gate's exit code decides less than it looks like it decides."**
  （机械门的退出码，决定的事情比它看起来少。）
  关于 eval 台账则写着它 **"does not prove the mechanical gate was ever actually run."**
  （不能证明机械门真的被跑过。）

上面每一句都在**随插件分发的 skill 文档里**，不只写在这份 README 上。
当某个机制被发现声称超出了它的实现，那条声称会被撤回、撤回本身会被记录。

## 什么时候适合用它

适合用 Harnessloop 的场景：

- 长时间的编码、研究、数据或验证任务。
- 依赖真实静态数据、生成数据、runtime 证据、源码或外部系统的工作。
- 从另一个 agent 手里跨会话接管任务。
- 需要最小改动的 scope-lock 与可审计 handoff 的任务。
- 失败、回滚或人工确认必须显式化的工作。

不适合的场景：

- 一次性的提问。
- 能立刻验证的小改动。
- 不需要留存证据或 handoff 的任务。

## 安装

Windows 上的 Codex：

```powershell
.\scripts\install-codex.ps1
```

Windows 上的 Claude Code：

```powershell
.\scripts\install-claude.ps1
```

macOS/Linux 上的 Codex：

```bash
./scripts/install-codex.sh
```

macOS/Linux 上的 Claude Code：

```bash
./scripts/install-claude.sh
```

等价的 CLI 命令：

```powershell
codex plugin marketplace add .
codex plugin add harnessloop@harnessloop

claude plugin marketplace add . --scope user
claude plugin install harnessloop@harnessloop --scope user
```

## 跑通第一个 loop

Harnessloop 目前是一套 skill/协议，不是独立的 shell CLI。Codex 里显式调用 skill 用的是 kebab-case 名字，比如 `$harnessloop-init`；`harnessloop:init` 这类冒号写法只是自然语言别名，`$harnessloop:init` 不是合法的 skill 写法。

装好之后，跟 agent 说：

```text
$harnessloop-init
```

要从这个仓库做确定性初始化：

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project
```

macOS/Linux：

```bash
./scripts/init-project.sh --project /path/to/target-project
```

首次 setup 会创建或填充：

```text
.harnessloop/
  setup/
    data-sources.md
    cost-context-policy.md
  local/
    .gitignore
    channel-params.example.json
  intake/
    .gitignore
  state/
    current.md
    environment.md
    control-contract.md
    evidence-index.md
    self-check.md
  meta/
    self-audit.md
    evolution-issues/
  evals/
    matrix.md
  goals/
```

然后用 `$harnessloop-loop` 定义 goal、拆出可分解的阈值、锁定第一轮的 scope、写证据、跑对抗评审、给反馈分类，并且只通过控制门继续。

出现 runtime 阻塞时，Harnessloop 会先分类再停下。可恢复的阻塞会转入一轮有边界的只读调查；缺访问权限、不安全的写操作、外部触发、清理决策或业务决策，则会暂停并向用户追问确切缺失的信息。

## 接管一个已有的 agent 会话

源会话不需要装 Harnessloop。让它生成一份 `Harnessloop Transfer Packet`，再把结果存下来：

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project -Intake task-slug
```

```text
.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/transfer-packet.md
```

在建立正式 goal 之前，Harnessloop 会先跑一道 intake gate：

```text
$harnessloop-intake
```

![Harnessloop takeover intake flow](docs/assets/takeover-intake-flow.svg)

如果 packet 不完整，Harnessloop 会写一份 `gap-review.md`，只追问缺失的事实。通过之后，第一轮通常应该是 `intake-review`——在任何业务执行继续之前，先把导入的证据映射进 `.harnessloop/state/evidence-index.md`。

transfer packet 必须包含：任务身份、goal 契约、进度状态、改动状态、文档清单、过程产物、证据、外部工具、不含密钥值的凭证需求、本地 channel 参数键名、决策、风险，以及下一步的 handoff 建议。完整的 prompt 见 [docs/usage.md](docs/usage.md)。

## 接入外部系统与凭证

### channel 清单与连通性检查是两件事

Harnessloop 把「channel 清单」和「连通性检查」当成两件不同的事：

- `$harnessloop-channels`：列出已声明的外部系统、工具、MCP server、CLI、API、CI 系统、数据库、broker，以及凭证引用——只列出，不探测。
- `$harnessloop-connectivity`：只运行已声明的连通性方法，前提是所需的工具、endpoint/资源、凭证引用、权限范围、参数、写安全规则都已经写明确。
- `$harnessloop-secrets`：在 `.harnessloop/local/channel-params.json` 里创建、检查仅本地保存的 channel 参数键；值不会被提交，也不会被抄进证据里。

某个 channel 的自检失败、被拦、被跳过，或者因为信息缺失需要用户确认时，Harnessloop 必须先追问确切缺失的事实，而不是先试别的办法或者硬着头皮继续。

### 三份文件，三种分工

同一件「外部系统怎么接进这个协议」的事，实际上散在三份文件里，各管一段（`plugins/harnessloop/skills/harnessloop-loop/SKILL.md` 里对这三份文件的分工有更完整的说明）：

- `.harnessloop/setup/data-sources.md` 的 `## Runtime Validation Systems` 表：用散文描述**怎么验证、通过条件是什么**——这份描述只存在于这里，没有任何机械门会去读它。
- `.harnessloop/setup/external-systems.json`：纯元数据式地声明**系统 id、接口类别（`kind`）与所需的参数名**——不涉及怎么判断结果。
- 一轮自己的 `evidence/runtime/acceptance-evals.json` 台账：记录**这一轮实际跑出了什么**——每个阶段一条，含 `outcome`，以及这条 eval 是对着哪个已声明系统跑的（`frozen_system`）。

三份文件各司其职——散文式的怎么验证、静态声明、逐轮的实际记录，这个协议从没把它们混在一起过。

### 为什么凭证在构造上写不进去

`.harnessloop/setup/external-systems.json` 里，每个系统只有 `id`、`kind`、`description`、`params` 四个字段——没有 URL、没有 host、没有 path 字段。`params` 收的也不是值，是参数**名**，且只认匹配 `^[A-Z][A-Z0-9_]{0,63}$` 的字符串——这个字符集里没有 `/`、`:`、`.`，也没有小写字母，所以不管怎么拼，一个 URL、host 或 path 都不可能匹配这个形状。

真正的值走 `$harnessloop-secrets` 管理的 channel-params（`.harnessloop/local/channel-params.json`，已 gitignore）。

这是**结构性约束**——凭证在这份声明文件里根本没有地方可放，不是「我们会小心不写进去」。

### `kind` 描述的是接口类别，不是角色

`kind` 目前的取值是 `http` / `grpc` / `database` / `queue` / `filesystem` / `ssh` / `process` / `other`。这是单一一根轴——**调用方通过什么接口形状跟这个系统说话**——而不是这个系统在某条流水线里扮演什么角色。一个 CI 系统、一个设备实验室、一个数据平台，各自仍然要按照它实际被访问的接口形状去声明 `kind`（多数情况下是 `http`，或者远程/本地执行命令时的 `ssh`/`process`），而不是声明一个按角色命名的 `kind`——枚举里没有 `ci` 或 `dataplatform` 这种成员，以后也不会加。这是一个刚做的、刻意的设计决定——直觉上很容易想反，把 `kind` 当成「这是什么系统」，而不是「怎么跟它说话」。

## Skills 一览

- `$harnessloop-init`：初始化 `.harnessloop/` 项目文件。
- `$harnessloop-setup`：通过五步向导完成或检查环境探测、数据源、成本/上下文策略与控制契约 profile。
- `$harnessloop-intake`：审查 transfer packet，跑 intake gate。
- `$harnessloop-goal`：查看、协商、更新、拆分、归档、取消、替代 goal，或评估删除影响。
- `$harnessloop-evidence`：新增、检查、修订、拒绝或对比证据契约。
- `$harnessloop-channels`：列出已声明的外部系统、channel 与工具，不探测。
- `$harnessloop-connectivity`：检查已声明的外部系统/工具连通性，缺访问事实时会追问。
- `$harnessloop-secrets`：管理本地 channel 参数键、密钥引用、存在性检查与脱敏规则。
- `$harnessloop-delegation`：检查子代理/swarm 是否就绪、scope 控制、输出路径、证据引用行为，以及 model/effort 是否匹配。
- `$harnessloop-status`：读取 Harnessloop 当前状态。
- `$harnessloop-continue`：执行前跑继续门。
- `$harnessloop-loop`：在已安装的项目里跑或接管一个 goal 驱动的 Harnessloop。
- `$harnessloop-issue`：记录、分析或提出 Harnessloop evolution issue 的修复方案。

## 核心概念

- `goal`：这个 loop 想要达成的东西。
- `transfer packet`：来自已有 agent 会话的结构化 handoff。
- `intake gate`：接管时的审查，拦下不安全的继续执行。
- `scope-lock`：一轮可以改动的确切边界。
- `evidence gate`：一轮要通过必须具备的证明。
- `handoff`：给子代理或评审者用的、基于文件的任务转交。
- `channel inventory`：已声明的外部系统与工具清单，只列出不探测。
- `connectivity check`：已声明的访问验证；所需的访问事实缺失时会停下来追问。
- `local channel parameters`：外部系统用到的本地值或 provider 引用，不参与提交。
- `blocker type`：分类判定——被阻塞的一轮能不能转入只读恢复，还是必须去问用户。
- `self-audit`：loop 的健康检查，查死循环、自相矛盾、drift 与失控增长的上下文。
- `evolution issue`：一份脱敏后的 issue，用来帮助改进 Harnessloop 本身。

## 证据模型

Harnessloop 把「证据产物本身是否健康」和「这份证据能不能支持验收」分开看待。一次失败的 runtime 测试可以是一份有效的证据产物，同时依然产出 negative 的反馈。

![Harnessloop evidence stack](docs/assets/evidence-stack.svg)

证据类别：

- `static`：真实数据集、文档、报告、源头记录。
- `dynamic`：生成的数据、抽样输出、模型/工具输出。
- `runtime`：测试、CI、远程自动化、探针、金丝雀、监控。
- `source`：仓库源码、schema 文件、源数据文件。

## 执行委派

Harnessloop 让主会话始终对编排与控制决策负责。当委派能保护上下文、提升评审质量时，它会通过文件 handoff 把有边界的工作派出去：

| 任务类型 | 决定 |
| --- | --- |
| 只读探索 | 路径和问题有边界时应当委派。 |
| 证据收集 | 只有在只读、敏感度已明确、输出会引用路径时才委派。 |
| 外部连通性 | 用 `$harnessloop-connectivity`；不要把盲目探测委派出去。 |
| 低风险的本地实现 | 可以委派，但要带 scope-lock、回滚方案与验证命令。 |
| 高风险的实现 | 集成由主会话自己掌握；只把狭窄的子任务委派出去。 |
| 对抗评审与验收测试 | 机制和证据引用可核实时可以委派。 |
| 一轮的验收与控制决策 | 绝不委派。 |

在依赖子代理或 swarm 的产出之前，如果需要核实 model、effort、scope 控制、输出路径控制或证据引用行为，先跑一次 `$harnessloop-delegation`。

## 成本记账

Harnessloop 把自己的开销当成协议里的一等度量。每一轮收尾时，`round_cost.py` 都会从本地会话记录里结算 token 用量，往轮次总结里写一份逐项的 `## Cost`：input/cache/output token、一个协议归因估算，以及一个可选的、按用户提供费率算出的美元数字。门拦下的记录——被对抗评审拒绝的轮次、被 self-audit 抓到的 drift——也会记进 decision 文件，让协议自身的成本和它拦下的东西落在同一份可审计的台账里。

Harnessloop 不声称这份开销能自己赚回来；它给你的是账单、拦截记录和一套判断框架，剩下的交给你自己项目的数据去决定。见 [docs/cost-model.md](docs/cost-model.md)。

## 仓库结构与校验

- `docs/usage.md`：产品层面的使用指南与 transfer packet 的 prompt。
- `docs/harnessloop-framework.md`：框架设计与详细协议。
- `docs/cost-model.md`：协议开销度量与成本/收益判断框架。
- `docs/harnessloop-flow.mmd`：规范的详细 Mermaid 流程源文件。
- `docs/harnessloop-flow.svg`：渲染出的详细流程预览图。
- `docs/assets/`：README 与文档用的视觉素材。
- `plugins/harnessloop/`：插件源码。
- `plugins/harnessloop/skills/`：可安装的 skills 与模板。
- `examples/mock-project/`：一个人工构造的参考项目，展示 setup、intake、evidence、review、decision、self-audit 与 evolution issue 各类文件。

### 校验

```bash
npm run validate
```

或者在任意平台上直接调用校验器：

```bash
python scripts/validate.py
```

包装脚本 `scripts/validate.ps1`（Windows）与 `scripts/validate.sh`（macOS/Linux）跑的是同一个 Python 校验器。

校验器会检查 marketplace manifest、跑 init 与 secrets 的 smoke test、核对文档骨架与 `init_project.py`（唯一真相源）是否一致、用 `verify_protocol.py` 对 `examples/mock-project` 强制执行机械协议门，并跑 Claude Code 的严格插件校验。在没装 Claude CLI 的环境里，设置 `HARNESSLOOP_SKIP_CLAUDE=1` 可以跳过那一步。

如果装了 Codex skill-creator 工具集，它的 `quick_validate.py` 还能额外对 `plugins/harnessloop/skills/` 下的每个目录做 lint。

## 当前限制

- Harnessloop 定义的是一套协议和 skills；目前还没有提供完整的 shell CLI。
- 它不附带固定的数据连接器。项目必须自己声明工具、账号、数据源与验证系统。
- 详细流程图应该以 `docs/harnessloop-flow.mmd` 为准维护；生成或装饰性的图片不能替代承载证据的流程图。

两份 manifest 里插件名都要保持 `harnessloop`，marketplace 的选择器才能稳定：

```text
harnessloop@harnessloop
```
