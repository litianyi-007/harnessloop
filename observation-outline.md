# 观察文章大纲：《Harnessloop 观察：当框架要求一切都有证据，除了它自己》

> 评审基线：仓库 v0.9.0，commit `ac219a3`（2026-06-30）。通读范围：README、`docs/usage.md`、`docs/harnessloop-framework.md`、12 个 SKILL.md、27 份 references 模板、`scripts/`、`examples/mock-project/` 全部文件、git 历史。所有论断附仓库内路径。

## 0. 备选标题

- 《Harnessloop 观察：当框架要求一切都有证据，除了它自己》（选用）
- 《用文件系统给 AI Agent 立规矩：Harnessloop 的野心与代价》
- 《证据驱动的 Agent 协议：Harnessloop 亮点与盲区》

## 1. 引言（钩子）

- 场景切入：长任务 agent 的六种可预测死法（README "Why" 一节原文列出）——上下文压缩、无证据续做、跨会话交接失败、验证漂移、外部依赖隐式化、评审沦为泛泛之谈。
- 一句话定位：项目本地文件协议 + 双运行时插件（Codex / Claude Code），v0.9.0，12 skill、27 模板，把目标、证据、交接、验证全部落进 `.harnessloop/`。
- 抛出全文核心问题：协议设计相当深思熟虑,但它的强制力从哪里来？

## 2. 项目速览（一段带过）

- 结构：`plugins/harnessloop/skills/`（12 skill，56 文件）、`docs/`（10）、`examples/mock-project/`（24）、`scripts/`（7），共 103 个 tracked 文件。
- 可执行部分只有三件：`init_project.py`、`channel_params.py`、面向本仓库的 `validate.ps1`；其余全部是写给模型看的行为规范。
- 节奏：21 个 commit 集中在 2026-06-28 ~ 06-30 三天内。

## 3. 亮点（每条附证据路径）

1. **接管设计把入口成本压到最低** —— 源会话零安装，只需产出 13 节 Transfer Packet；intake gate 阻断盲目续做；gap-review 只索要缺失项（`harnessloop-intake/SKILL.md`、`references/transfer-packet-template.md`）。
2. **证据模型的双维度区分** —— 工件健康度（artifact health）与验收支持方向（claim support / acceptance effect）分离：失败的测试是有效证据、同时否决验收。实证：mock 项目 `state/evidence-index.md` 的 `valid / refutes / fail` 行。
3. **委派权限矩阵清晰** —— 8 类任务 × 应委派/可委派/绝不委派；轮次验收与控制决策永不委派；记录期望 vs 实测模型与推理档位（`harnessloop-loop/SKILL.md:400-411`）。
4. **阻塞分类避免两种极端** —— 7 类 blocker；`runtime-recoverable` 自动进入只读调查轮不打扰用户，`access-missing` 等精确索要缺失事实（最新 commit `ac219a3`）。
5. **秘密处理有工程落地** —— `local/` 专属 gitignore；`channel_params.py` 可执行管理；`validate.ps1` smoke test 断言 `value` 必须为 null。这是少数从文字规范下沉为可执行断言的点——证明下沉可行。
6. **示例敢于展示失败,甚至自我批评** —— mock 唯一一轮以 negative 收场、不予验收（`rounds/0001/decision.md`）；evolution issue HLI-0001 记录的正是框架自身模板缺陷（threshold 模板太含糊导致 review 自行发明标准）。示例在演示"框架抓到框架的 bug"。

## 4. 不足（每条附证据路径）

1. **仪式感过重,最小路径缺失** —— 20 条原则、12 skill、27 模板、每轮 6+ 文件；README "Start Your First Loop" 一句话塞进 7 个协议步骤；无 5 分钟最小 walkthrough。
2. **强制力真空（最硬伤）** —— 所有运行时 gate（scope-lock、只读 status、continuation、intake）只存在于 SKILL.md 文字里，近 500 行的 `harnessloop-loop/SKILL.md` 全靠模型自觉——而框架的前提恰是模型不可信。公平项：纯 prompt 协议换来双运行时便携。
3. **文档五处拷贝,漂移已发生** —— 骨架重复于 README / usage.md / framework.md / 两个 SKILL.md，可执行真相在 `init_project.py`。实证：README 骨架图缺 `intake/` 与 `evals/`；usage.md 清单缺 `current.md`、`self-check.md`、`evals/matrix.md`。把 validation drift 列进自审清单的框架，自己的文档先漂移了。
4. **工程成熟度信号缺失** —— 无 LICENSE（阻断严肃采用）、无 CI、无 CHANGELOG/CONTRIBUTING；README 硬编码 `C:\Users\litianyi\.codex\...`，`validate.ps1` 硬编码 `C:\nvm4w\nodejs\claude.cmd`；npm scripts 直调 `powershell`，macOS/Linux 上 `npm run validate` 必失败（二进制名是 `pwsh`，且无 validate.sh）——而 AGENTS.md 称其为 required regression check。
5. **已装项目无升级路径** —— 模板无版本号字段、无迁移工具；framework.md 烤死 `gpt-5.5-medium`、`Sonnet` 等模型名，注定过时。
6. **token 经济学未被测量** —— 协议要求行动前读全部状态、每轮写多份文件；`cost-context-policy.md` 是协议的一部分，但框架从未给出自身开销的任何数字。

## 5. 深层张力（文章的灵魂，三个思辨点）

1. **自指困境** —— 要求一切断言附证据路径的框架，对自身有效性零证据：无真实项目案例，唯一示例是人造 mock，eval 矩阵只有一列样例值。evidence-backed 的框架目前是 evidence-free 的。
2. **信任悖论** —— 全部保障机制运行在它不信任的载体（LLM 指令遵循）之上。出路是把机械 gate 下沉为工具（pre-commit 校验 scope-lock、CLI 校验 evidence 引用）；README 自认 "not yet a full shell CLI"——这是路线图上最重要的一步。
3. **协议还是论文** —— 当前形态更像方法论论文；价值可能不在被整体采用，而在部件被拆走：transfer packet、blocker 分类、证据双维度都值得被其他工具吸收。

## 6. 结论与适用建议

- 适合：高风险、多天、跨会话任务；愿以重协议换审计性的团队；agent 框架设计者（当思想库读）。
- 不适合：日常编码任务（开销 > 收益）；期望开箱即用工具而非行为公约的用户。
- 收束句：诊断一流，处方认真，但药效目前取决于病人是否自觉服药。

## 7. 写作素材清单

- 引用文件：`README.md`（Why / Current Limits）、`docs/harnessloop-framework.md`（20 条原则）、`plugins/harnessloop/skills/harnessloop-loop/SKILL.md:400-411`（委派矩阵）、`examples/mock-project/.harnessloop/state/evidence-index.md`（refutes 行）、`examples/mock-project/.harnessloop/meta/evolution-issues/0001-validation-drift-template-gap.md`（自我批评示例）、`scripts/validate.ps1`（smoke 断言与硬编码路径并存的对照）。
- 数据点：12 skills / 27 templates / 103 tracked files / 21 commits / 3 天 / v0.9.0 / 13 节 transfer packet / 7 类 blocker / 8 行委派矩阵 / 0 LICENSE / 0 CI。
