# Harnessloop 观察：当框架要求一切都有证据，除了它自己

> 评审基线：仓库 v0.9.0，commit `ac219a3`（2026-06-30）。本文所有论断均附仓库内文件路径，可自行核对——这也是被评审对象自己立下的规矩。

## 一、长任务 agent 的六种死法

让一个 AI agent 连续工作几个小时、跨越多个会话去完成一件事，今天仍然是一场赌博。不是赌模型能力不够，而是赌过程不出这几种事故：上下文被压缩后丢失关键约束；agent 在没有任何新证据的情况下宣布"已完成"；一个会话的工作交到下一个会话手里时只剩一段失真的摘要；验证标准随着轮次悄悄漂移；外部工具和凭据的依赖从头到尾没被写下来；评审沦为"代码看起来不错"式的泛泛之谈。

Harnessloop 的 README 开篇就把这六种失败模式列了出来（`README.md` 的 "Why" 一节），诊断相当准确。它给出的处方是：把长任务 agent 工作的一切——目标、证据、交接、验证、接管、自审——全部落成项目目录里的文件，即 `.harnessloop/` 协议。项目形态是一个双运行时插件（Codex 和 Claude Code 各有安装脚本与 manifest），当前版本 0.9.0，含 12 个 skill 和 27 份模板。

这套设计有不少地方是我在同类项目里没见过的。但通读全部 103 个 tracked 文件之后，一个问题挥之不去：**协议写得这么细，它的强制力从哪里来？** 这个问题会贯穿全文。

## 二、项目速览

仓库结构很干净：`plugins/harnessloop/skills/` 下是 12 个 skill（每个一份 SKILL.md 行为规范）和 27 份可复用模板；`docs/` 下是使用指南、框架设计文档和流程图；`examples/mock-project/` 是一个走完整个生命周期的人造示例；`scripts/` 是安装、初始化、验证入口。

值得注意的是可执行代码的占比：真正能跑的只有三件——创建目录骨架的 `init_project.py`、管理本地凭据引用的 `channel_params.py`、面向本仓库自身的 `validate.ps1`。其余的一切，包括最核心的近 500 行 `harnessloop-loop/SKILL.md`，都是写给模型看的行为规范。这个比例本身就是理解这个项目的钥匙：**Harnessloop 目前是一份协议，不是一个工具。**

git 历史显示 21 个 commit 集中在 2026 年 6 月 28 日到 30 日的三天之内，单作者。这是一个刚刚成型、还带着体温的项目。

## 三、亮点：六处真正的设计

### 1. 接管设计把入口成本压到了最低

跨会话接管是整个项目最聪明的设计。要把一个正在进行的任务从别的 agent 会话接过来，**源会话不需要安装任何东西**——它唯一的责任是照着一份提示词产出"Transfer Packet"（交接包），一个 13 节的结构化文档：任务身份、目标契约、进度、变更、文档清单、过程工件、证据状态、外部工具契约、凭据需求（不含值）、决策日志、风险、交接建议、留给人的问题（`references/transfer-packet-template.md`）。

接收侧则有一道 intake gate：交接包不会因为"写得详细"就被接受，gate 检查的是它是否可行动、是否有证据支撑（`docs/usage.md` 明确写了这条区分）。信息不全时写一份 `gap-review.md`，**只索要缺失的条目**，而不是让用户重新解释一遍任务。`harnessloop-intake/SKILL.md` 的安全规则直白：gate 不过，业务执行不许继续。

单方面降低对方的参与成本，把审查责任留给自己——这是协议设计里少见的成熟做法。

### 2. 证据模型的双维度区分

大多数"要求验证"的框架只有一个维度：验证过了没有。Harnessloop 把它拆成两个正交的维度：**证据工件本身健康吗**（artifact health），和**这份证据支持还是否决验收**（claim support / acceptance effect）。

一个失败的测试输出，是一份完全有效的证据工件，同时否决这一轮的验收。这不是文字游戏——它意味着"测试挂了"不再被当作"证据缺失"处理，失败被完整地记录、引用、归档，而不是被重跑到通过为止。mock 项目的证据索引里有一行活的示例：`artifact health: valid / claim support: refutes / acceptance effect: fail`（`examples/mock-project/.harnessloop/state/evidence-index.md`）。

这个区分对抗的是 agent 工作里最隐蔽的腐败形式：把"让验证通过"误当成"让工作正确"。

### 3. 委派权限矩阵：把"哪些事绝不外包"写死

`harnessloop-loop/SKILL.md` 第 400 行附近有一张 8 行的委派矩阵，按任务类型规定了应委派、可委派、绝不委派：只读探索应当委派（省主会话上下文）；证据收集在只读且有界时可委派；对抗性评审在机制可验证时**必须**委派（避免自我评审偏见）；而轮次验收和控制决策**永不**委派。

更进一步，它要求记录"期望的模型/推理档位"与"实际观察到的模型/推理档位"——这能抓到一类几乎没人防的故障：你以为子任务跑在高配模型上，实际调度到的是别的东西，然后你信任了它的结论。委派前置检查专门有一个 skill（`harnessloop-delegation`）负责这件事。

### 4. 阻塞分类：在"全自动"和"事事请示"之间找到第三条路

最新的 commit（`ac219a3`，classify recoverable blockers）引入了 7 类 blocker 分类。核心区分是：`runtime-recoverable`（运行时可恢复）的阻塞**不打扰用户**，自动进入一个有边界的只读调查轮；而 `access-missing`（缺访问凭据）、`write-safety-required`（写操作需安全确认）、`human-decision-required`（需要业务决策）这些类别才停下来——并且停下来时必须**精确指出缺什么**，而不是抛一句"我被卡住了"。

agent 自主性的调参是所有 harness 的难题：管太死，用户被无穷的请示淹没；放太开，agent 在危险操作上自作主张。按"阻塞的性质"而不是"阻塞的存在"来决定停不停,是我见过的对这个问题最务实的回答之一。

### 5. 秘密处理：少数下沉到代码的规则

凭据处理是整个协议里唯一从文字规范下沉为可执行断言的部分：`.harnessloop/local/` 有专属 `.gitignore` 挡住 `channel-params.json`；有一个真实的 `channel_params.py` 脚本管理参数键；`validate.ps1` 的 smoke test 里有硬断言——add 操作后参数的 `value` 字段必须是 null，否则验证直接失败（`scripts/validate.ps1` 的 `Invoke-HarnessloopSecretsSmoke`）。

所有提交进仓库的文件只允许出现参数的键、存储方式、用途和状态，值永远只存在于被 ignore 的本地文件里。这一块的完成度证明了一件事：**协议规则是可以下沉为机器强制的**——这恰恰反衬出其余部分没有下沉（后文详述）。

### 6. 示例敢于展示失败，甚至展示对自己的批评

`examples/mock-project/` 的唯一一轮以 negative feedback 收场：运行时测试失败,评审引用了失败输出,决策文件写着"不予验收,下一步只允许修改 thresholds.md"（`rounds/0001/decision.md`）。绝大多数框架的示例都是精心摆拍的成功案例,用失败案例做唯一示例,说明作者真正想教的是"失败时协议如何运转"——这才是这类框架存在的意义。

更有意思的是那份 evolution issue（`meta/evolution-issues/0001-validation-drift-template-gap.md`）：它记录的缺陷是**框架自己的**——threshold 模板写得太含糊,导致评审在事后自行发明了更严的标准。示例项目在演示"框架抓到框架的 bug"。README 的 "Current Limits" 一节也同样诚实。这种自我批评的姿态在 0.9.0 的项目里是稀缺品。

## 四、不足：六个盲区

### 1. 仪式感过重，最小可用路径缺失

20 条核心原则（`docs/harnessloop-framework.md`）、12 个 skill、27 份模板、每个目标 5 份文件、每轮再加 6+ 份。README 的 "Start Your First Loop" 一节，在 init 之后是这样一句话："Then use `$harnessloop-loop` to define a goal, create decomposable thresholds, lock the first round scope, write evidence, run adversarial review, classify feedback, and continue only through the control gate."——一句话塞进七个协议步骤，没有任何一步展开。

整个仓库没有一份"5 分钟跑通最小循环"的 walkthrough。一个潜在用户的第一反应几乎必然是："我的任务配得上这套仪式吗？"而文档没有给出"哪些环节可以裁剪"的指引。重协议需要用轻入口来平衡，目前入口和协议一样重。

### 2. 强制力真空（最硬伤）

把 mock 项目里那份 scope-lock 打开看（`rounds/0001/scope-lock.md`）：允许写 evidence 和 review 目录，禁止改源码、改数据契约、改阈值。写得清清楚楚。然后问一个问题：**如果执行的 agent 违反了它，会发生什么？**

答案是：什么也不会发生。没有 hook 校验写入路径是否越界，没有 CI 检查评审是否真的引用了证据文件，没有任何机制阻止一个"只读"的 status 操作顺手改了文件。`harnessloop-status/SKILL.md` 用一整节 Safety Rules 强调"read-only 意味着零写入"——但这句话的执行者，是被要求约束的模型本身。

近 500 行的 `harnessloop-loop/SKILL.md` 是整个协议的核心，它的全部效力建立在模型逐条遵守长文档指令的假设上。而这个框架存在的第一前提恰恰是：**模型的自我报告不可信,所以才需要证据和 gate**。用模型的自觉去执行"防模型不自觉"的协议,这是结构性的矛盾。

公平地说,纯文字协议有一个真实的好处:它因此能同时跑在 Codex 和 Claude Code 上,不依赖任何一家的 hook 机制。但这更像是对现状的解释,而不是对未来的辩护——机械可判的规则(路径越界、引用存在性、状态文件一致性)完全可以下沉为跨平台的脚本,就像 secrets 部分已经做到的那样。

### 3. 文档五处拷贝，漂移已经发生

同一套 `.harnessloop/` 目录骨架和控制语义,在 README、`docs/usage.md`、`docs/harnessloop-framework.md`、`harnessloop-loop/SKILL.md`、`harnessloop-init/SKILL.md` 里重复了五遍,而可执行的真相在第六处——`init_project.py` 的 `BASE_DIRS`/`BASE_FILES` 常量里。

漂移不是风险，是现状：README 第 100-118 行的骨架图里**没有** `intake/` 和 `evals/` 目录，而 framework.md 和 init 脚本都有；usage.md 第 49-56 行列举的初始化产物里缺了 `state/current.md`、`state/self-check.md` 和 `evals/matrix.md`，这些都是脚本实际会创建的文件。

一个把 "validation drift" 列进自审清单、要求安装项目警惕文档漂移的框架，自己的文档先漂移了。这不只是讽刺，它揭示了一个方法论缺口：协议对"安装它的项目"设计了完整的自审机制，对"它自己这个仓库"却没有——validate.ps1 检查 manifest 和 smoke test，不检查文档一致性。

### 4. 工程成熟度信号缺失

按严重程度排列：

- **没有 LICENSE。** 任何组织的合规流程都无法采用一个无许可证的依赖。对一个明显意在公开分发（有 marketplace manifest、有安装脚本）的项目，这是第一优先级的缺失。
- **跨平台支持名不副实。** README 提供了 `install-codex.sh`/`install-claude.sh`，但 `package.json` 里所有 npm scripts 都直调 `powershell`（macOS/Linux 上二进制名是 `pwsh`，且根本没有 validate 的 shell 版本）。`AGENTS.md` 称 `npm run validate` 是提交前的必要回归检查——在非 Windows 平台上这条命令必然失败。
- **个人环境硬编码进了面向用户的文档。** README 的 "Validate" 一节让用户运行 `python C:\Users\litianyi\.codex\skills\...\quick_validate.py`；`validate.ps1` 里有一条 fallback 路径 `C:\nvm4w\nodejs\claude.cmd`。前者出现在所有用户都会读的 README 里，观感和实用性都受损。
- 没有 CI、没有 CHANGELOG、没有 CONTRIBUTING。三天 21 个 commit 的项目可以理解，但 0.9.0 的版本号暗示着"接近 1.0"，这些缺失和版本号的承诺不匹配。

### 5. 已安装项目没有升级路径

`init_project.py` 对已存在的文件一律跳过（除非 `--force` 全量覆盖）。这意味着：模板在上游演进后，已初始化的项目**没有任何迁移机制**——没有版本号字段写进生成的文件，没有 diff/migrate 工具，甚至没有一份"模板变更需要手工同步哪些文件"的说明。

同类问题还有模型名被烤死在协议里：framework.md 和 cost-context-policy 模板写着 "Codex preference: subagent with `gpt-5.5-medium`"、"Claude Code preference: Sonnet with high or extra-high reasoning"。模型名的半衰期以月计，这些字符串注定在几个月内变成误导信息，而（见上）没有任何机制把更新推送到已安装的项目。

### 6. token 经济学没有被测量

协议要求每次行动前读取 `.harnessloop/` 状态文件、每轮写入 scope-lock/evidence/review/summary/decision 多份文件、自审再读一遍全部状态。这些读写本身就是持续的上下文与 token 开销——对一个以"节约主会话上下文"为设计目标之一的框架（委派矩阵的价值列反复强调 "saves main-session context"），这笔账不能不算。

讽刺的是，`cost-context-policy.md` 是协议钦定的设置文件之一，框架要求每个项目声明预算规则——但框架自己从未提供任何数字：一轮标准循环的协议开销是多少 token？相比裸奔的 agent 会话，开销放大了百分之几？换来的返工减少了多少？没有测量，"重协议是值得的"就只是一个信念。

## 五、深层张力：三个思辨

罗列优缺点不是目的。这个项目真正值得写一篇文章的原因，是它把三个行业级的张力暴露得非常清楚。

### 1. 自指困境：evidence-backed 框架的 evidence-free 处境

Harnessloop 的第 13 条核心原则："验证必须引用真实证据……而不是泛泛的工程判断。"现在把这条原则指向框架自身：Harnessloop 有效吗？

仓库里没有任何真实项目的使用案例。唯一的示例是人造的 mock。`evals/matrix.md` 模板只有一列"样例值"，没有任何已执行的评估。框架对自身价值的全部论证,恰恰是它明令禁止的那种形式——听起来合理的工程判断。

这不是抬杠。一个要求用户接受重协议的框架，最有力的推销就是一份用协议自身格式写成的实战记录：某个真实的长任务，走完 N 轮，这里是全部 scope-lock、证据和决策文件，这里是它抓住的三次将错就错。这份记录目前不存在。**框架最大的缺失证据，是它自己的使用证据。**

### 2. 信任悖论：出路是下沉

第二个张力前面已经点出：协议的全部保障机制，运行在它所不信任的载体（LLM 的指令遵循能力）之上。

值得展开的是出路。协议规则可以分成两类：需要判断的（这份证据是否支持验收？这个目标解释漂移了吗？）和机械可判的（写入路径是否在 scope-lock 允许清单内？评审文件引用的证据路径是否存在？status 操作是否产生了文件变更？）。前者留给模型没有问题——那本来就是模型的工作。后者留给模型就是浪费信任：一个 pre-commit hook、一个 30 行的校验脚本就能把它们变成硬约束。

仓库里已经有了正面样板：secrets 部分的"值必须为 null"就是用脚本断言强制的。README 的 Current Limits 也承认 "does not yet provide a full shell CLI"。从 0.9 到 1.0 最重要的一步不是增加第 13 个 skill,而是把已有协议里所有机械可判的规则从 SKILL.md 的文字里搬进可执行的 gate。**协议的下限应该由代码保证,模型只负责协议的上限。**

### 3. 这是一个产品，还是一篇论文？

三天写成、21 个 commit、可执行代码不足三百行、行为规范上万字——Harnessloop 当前的真实形态,更接近一篇"如何用文件系统运行长任务 agent"的方法论论文,附带一个恰好可以安装的 demo。

这不是贬低。它的部件质量高到值得被单独拆走：Transfer Packet 的 13 节结构可以直接被任何 agent 交接场景借用；7 类 blocker 分类是所有 harness 都该抄的自主性策略；证据双维度应该成为 agent 验证的常识。即使 Harnessloop 本体从未流行,这些思想通过被拆解、被吸收而存活的概率也相当高。

判断它最终是产品还是论文的观察指标只有一个:**下一批 commit 是在增加规范文字,还是在增加可执行的 gate。**

## 六、结论

适合认真评估 Harnessloop 的人：运行高风险、多天、跨会话 agent 任务的团队，愿意用重协议换完整审计轨迹；以及所有 agent 框架的设计者——把它当思想库读，收益极高。

不适合的人：日常编码任务的用户（协议开销远大于收益，README 自己也这么说）；期望装上就能用的工具、而不是一份需要模型自觉遵守的行为公约的人。

Harnessloop 对"长任务 agent 为何失败"的诊断是一流的，开出的处方是认真的，示例甚至诚实地展示了失败。但在强制力下沉为代码、并拿出自己的使用证据之前——**药效仍然取决于病人是否自觉服药。**

而一个所有人都该记住的细节是：这个框架已经证明了下沉是可行的，因为它对秘密值的保护就是这么做的。它只是还没有对自己的其余部分,使用同样的标准。

---

*附：本文引用的关键文件*

| 论断 | 证据路径 |
| --- | --- |
| 六种失败模式 | `README.md`（Why 一节） |
| 20 条核心原则 | `docs/harnessloop-framework.md` |
| 委派矩阵 / 永不委派 | `plugins/harnessloop/skills/harnessloop-loop/SKILL.md:400-411` |
| 证据双维度实例 | `examples/mock-project/.harnessloop/state/evidence-index.md` |
| 失败示例决策 | `examples/mock-project/.../rounds/0001/decision.md` |
| 框架自我批评 | `examples/mock-project/.harnessloop/meta/evolution-issues/0001-validation-drift-template-gap.md` |
| 7 类 blocker | `harnessloop-loop/SKILL.md`（Verification Phase）与 commit `ac219a3` |
| secrets 硬断言 | `scripts/validate.ps1`（Invoke-HarnessloopSecretsSmoke） |
| README 骨架缺目录 | `README.md:100-118` 对照 `init_project.py` BASE_DIRS |
| 硬编码个人路径 | `README.md`（Validate 一节）、`scripts/validate.ps1:28` |
| npm scripts 仅 Windows | `package.json` |
| 无升级机制 | `init_project.py`（skip-unless-force 逻辑） |
