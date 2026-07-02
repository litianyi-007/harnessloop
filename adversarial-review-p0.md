# Harnessloop P0 修复对抗性复评报告

> 评审人：独立对抗性评审人（外部聘请，非实现方）。
> 立场：怀疑一切，设法证伪。以复现命令、退出码、文件路径行号为唯一依据。
> 基线：仓库 `E:\project\harnessloop`，工作区未提交的 P0 修改（HEAD = `ac219a3`，P0 全部改动尚在工作树）。
> 日期：2026-07-02。
> 验收基准：`product-feedback.md:175-186`（P0-1 ~ P0-6）。

---

## 一、总判定

| 项 | 验收要点 | 判定 | 一句话结论 |
| --- | --- | --- | --- |
| P0-1 | LICENSE + manifest SPDX + marketplace 引用许可证 | **conditional-pass** | LICENSE 全文完整合规，但**两个 plugin manifest 无 SPDX、两个 marketplace 无许可证引用**，且 validate 不检查这两项——3 个子要求只落地 1 个。 |
| P0-2 | 跨平台 validate；无 powershell 字面量；三平台 CI 绿 | **pass** | `validate.py` 六阶段逻辑正确、失败必非零退出；`py -3` 与 `npm run validate` 均退出 0；powershell 字面量为 0。仅 `validate.sh` 版本探测有小瑕疵。 |
| P0-3 | grep `C:\Users`/`litianyi`/`nvm4w` 命中为 0 | **pass** | tracked 文件零命中；仅 3 篇**未跟踪**的历史评审文档命中；`claude` 改由 PATH/环境变量动态解析。 |
| P0-4 | init_project.py 为单一事实源；文档骨架偏离即失败 | **conditional-pass** | 当前 5 份文档骨架确实一致（人工逐份核对属实），但一致性校验是**宽松的“文件名出现即通过”**，存在可复现的假阴性（掩蔽删除 / 错放目录抓不到）。 |
| P0-5 | verify MVP：越界写入 + 悬空引用非零退出 | **conditional-pass** | 满足**字面**验收（对 mock-project 通过；构造的越界/悬空引用触发失败）；但我构造出 **3 个可绕过/误报场景**：模板格式 scope-lock 被误判、非前缀引用不校验、evidence/reviews 之外的越界写入不可见。 |
| P0-6 | 三平台矩阵 CI；PR 未过 CI 不可合并 | **conditional-pass** | CI 矩阵三平台齐备且逻辑合理；但“未过 CI 不可合并”依赖 branch protection（仓库设置，文件层做不到），实现方**既未配置也未标注**为待办——诚实性 gap。 |

**总结论：本轮无 blocker、无 outright fail，工程质量整体扎实且诚实。** 但有 **3 项 major** 与若干 minor 必须在 1.0 前收口，尤其 P0-5 的 verify 门在“真实用户按模板写 scope-lock”与“引用源码/测试文件作证据”这两个最常见路径上会失灵。

---

## 二、逐项检测过程与证据

### P0-1 LICENSE（conditional-pass）

**检测：**
- 通读 `LICENSE`（`E:\project\harnessloop\LICENSE`，共 202 行）。结构完整：前言（Apache License, Version 2.0）→ `TERMS AND CONDITIONS` → 第 1~9 条（`1. Definitions`…`9. Accepting Warranty or Additional Liability`，见 `LICENSE:7/66/73/89/130/138/143/153/165`）→ `END OF TERMS AND CONDITIONS`（`:176`）→ `APPENDIX`（`:178`），版权占位已填 `Copyright 2026 Harnessloop`（`:189`）。**是完整未删节的标准 Apache-2.0，非节选/占位。**
- `package.json:5` 有 `"license": "Apache-2.0"`。

**证伪点（成立）：** 验收原文要求“**两个 plugin manifest 含 SPDX 标识；marketplace 元数据引用许可证**”。实测：
- `grep -i "license|spdx|Apache" plugins/harnessloop/**.json` → **0 命中**：`plugins/harnessloop/.codex-plugin/plugin.json` 与 `plugins/harnessloop/.claude-plugin/plugin.json` 均**无** `license`/SPDX 字段。
- `.claude-plugin/marketplace.json` 与 `.agents/plugins/marketplace.json` 均**无**许可证引用（逐行读毕确认）。
- `scripts/validate.py:94-96` 只断言 `LICENSE` 存在 + `package.json` license，**不检查** manifest/marketplace 的 SPDX——所以此缺口在 validate 里被“漂绿”，绿灯掩盖了未完成。

判定 conditional-pass：信誉最关键的 LICENSE 文件已到位，但验收明列的 3 个子要求只落地 1 个。

### P0-2 跨平台 validate（pass）

**六阶段逻辑核查（`scripts/validate.py`）：** [1]manifests+LICENSE+powershell 断言、[2]init smoke、[3]secrets smoke、[4]文档一致性、[5]verify 机械门+负向 fixture、[6]claude strict（可 `HARNESSLOOP_SKIP_CLAUDE=1` 跳过）。

**失败→非零退出路径追踪（重点对抗）：** `check()`（`:38-43`）在条件假时把 message 追加进模块级 `FAILURES`；`main()`（`:265-278`）在所有阶段跑完后 `if FAILURES: return 1` 否则 `return 0`；`raise SystemExit(main())`（`:282`）。另外 `read_json()`（`:46-49`）对缺失文件 `raise SystemExit`、`doc.read_text()` 等未捕获异常也会以非零退出。**结论：任何失败都会导致非零退出，无“打印但不计分”的漏网路径。**（逐个阶段核对：`validate_init_smoke` 在 init 非零时先 `check()` 记账再 `return`；其余阶段所有失败均经 `check()`。）

**运行证据：**
- `py -3 scripts/validate.py` → 六阶段全 `ok`（含真实 `claude plugin validate --strict` 两次通过，本机 `claude.exe` 在 PATH），末行 `Plugin framework validation passed.`，**EXITCODE=0**。
- `npm run validate` → **NPM_EXIT=0**（经 `run-python.mjs` 解析 Python 3 后同样全绿）。
- `package.json` grep `powershell`（大小写不敏感）= **0 命中**；`validate.py:97-98` 亦断言 `"powershell" not in scripts_blob.lower()`。

**`run-python.mjs` 逻辑（`scripts/run-python.mjs`）：** 依次探测 `py -3` / `python3` / `python`，每个都跑 `--version` 并正则匹配 `/Python 3\./`（`:12-16`）才采用——**能正确跳过只装了 Python 2 的 `python`**，比 `validate.sh` 稳健；对 ENOENT 走 `probe.error` 分支不抛异常；`process.exit(result.status ?? 1)` 对信号杀死回退 1。未见逻辑缺陷。

**`validate.ps1` / `validate.sh`（瘦包装核查）：** `validate.ps1` 用 `Get-Command`+`--version` 匹配 `Python 3`（`:22-23`），正确。`validate.sh:7-14` 仅 `command -v python3` 否则 `python`，**不校验主版本号**——见 minor #4。

判定 pass。

### P0-3 硬编码个人路径（pass）

- `git grep -Iin litianyi` / `nvm4w`（仅 tracked）→ **退出 1（零命中）**。
- ripgrep 全库 `litianyi|nvm4w|C:\Users` → 仅 3 文件：`product-feedback.md`、`observation-article.md`、`observation-outline.md`。`git ls-files` 对这三者返回**空**、`git status` 显示为 `??`——即**均未被 git 跟踪**，属历史评审文档，符合豁免。
- README 的 Validate 段（`README.md:232-248`）与 `scripts/` 全部干净。旧 `validate.ps1:28` 的 `C:\nvm4w\nodejs\claude.cmd` 已消除；claude 现由 `validate.py:239-244` 经 `shutil.which("claude"/".cmd"/".exe")` 或 `CLAUDE_CLI` 动态解析（本机解析到 `C:\Users\litianyi\.local\bin\claude.exe` 是**运行时真实路径**，非硬编码）。

判定 pass。

### P0-4 文档单一事实源（conditional-pass）

**权威源（`init_project.py`）：** `BASE_DIRS`（7 个，`:16-24`）、`BASE_FILES`（9 个，`:26-36`）、`LOCAL_FILES`（2 个，`:38-41`）、`INTAKE_FILES`（1 个，`:43-45`，本轮新增）。

**人工逐份核对（不靠校验放水）——全部一致：**
- `README.md:100-122` 骨架：7 个顶层目录 + 全部文件齐全（含 `intake/`、`evals/`、`channel-params.example.json` 等）。
- `docs/usage.md:47-59` 初始化清单：三份曾缺文件 `state/current.md`、`state/self-check.md`、`evals/matrix.md` 均已补；`goals/` 见 `:253`。
- `docs/harnessloop-framework.md:57-102`、`harnessloop-init/SKILL.md:57-79`、`harnessloop-loop/SKILL.md` 骨架均含全集。

**对抗校验强度（`validate_doc_consistency`，`:174-195`）——发现真实假阴性：**
校验方式是把**顶层目录字符串**（如 `state/`）与**文件裸 basename**（如 `matrix.md`）在**整篇文档全文**里做 `in text` 子串匹配（`:192-195`）。这带来结构无关的盲区。实测（改动后均已还原，README 与备份 hash 一致）：
- 真阳性（有牙）：删掉 `README.md` 骨架里只在骨架出现的 `current.md` → 校验 **FAIL**：`missing: ['state/current.md']`，退出 1。✅ 能抓仅骨架出现的名字。
- **假阴性（漏网）**：删掉骨架里的 `evidence-index.md` → 校验 **PASS**（退出 0）。原因：`evidence-index.md` 同时出现在散文 `README.md:148`（“maps imported evidence into `.harnessloop/state/evidence-index.md`”），子串仍在 → 骨架已残缺却判通过。
- 推论盲区：把 `matrix.md` 错放到 `state/` 下、只要 `evals/` 与 `matrix.md` 两个子串仍各自出现在文中，校验照样通过——**无法发现“错放目录”“掩蔽删除”。**

判定 conditional-pass：现状确实一致，但“单一事实源”的强制力弱于宣称，对“名字在文中复现”的文件（`evidence-index.md` 等多个）可静默漂移。

### P0-5 verify MVP（conditional-pass）

**路径规整正确性（`verify_protocol.py:40-46`）：** `norm = normcase(normpath(...))`——Windows 大小写经 `normcase` 归一、`/`↔`\` 经 `normpath`+span 的 `replace("\\","/")` 归一、`..` 经 `normpath` 折叠；`is_under` 以 `startswith(parent + os.sep)` 判定，杜绝 `/foo/bar` 误判为 `/foo/ba` 的前缀假阳性。**规整层无越界绕过漏洞。**

**对 mock-project：** `py -3 …/verify_protocol.py --project examples/mock-project` → `violations: []`，**EXITCODE=0**。✅

**`.tmp/` 手工 fixture（均已清理）：**

| Fixture | 构造 | 期望 | 实测 |
| --- | --- | --- | --- |
| A 越界写入 | scope-lock 仅允许 `rounds/0001/evidence/static/`，却写 `evidence/runtime/leak.md` | 非零 | **exit 1，scope-lock-violation** ✅ |
| B 悬空引用 | review 引用 `.harnessloop/…/evidence/runtime/DOES-NOT-EXIST.md` | 非零 | **exit 1，dangling-citation** ✅ |
| C 绕过①：非前缀引用 | review 引用不存在的 `src/app/missing_module.py`、`tests/test_missing.py`、`../../../etc/passwd` | 应抓 | **exit 0，无 violation —— 门被骗过** ❌ |
| D 绕过②：evidence/reviews 之外越界 | scope-lock 仅允许 `evidence/`，却在 round 根写 `SNEAKY-out-of-scope.md` 并在项目写 `src/hijacked.py` | 应抓 | **exit 0，无 violation —— 门被骗过** ❌ |
| F 模板格式 scope-lock | scope-lock 完全按 `scope-lock-template.md` 的**表格**写（路径无反引号） | 应通过 | **exit 1，unparseable-allowed-changes —— 误报，合规轮被判失败** ❌ |

**对抗结论（对应清单 10a-d）：**
- 10a（规整绕过）：未发现——大小写/分隔符/`..` 均被正确归一。
- 10b（scope-lock 变体）：小节标题大小写经 `.lower()` 容错；带冒号 / h3 / 无反引号路径 → 归为 `unparseable-allowed-changes` **报错（fail-safe，非静默放行）**——方向正确。**但**该检查仅在 `checked_files` 非空时触发（`:85`），若某轮不往 evidence/reviews 写任何文件，畸形/缺失 scope-lock **不产生任何 violation**（与 D 复合）。
- 10c（PATHISH_PREFIXES 过滤）：`:26-37/63-69` 只对以 10 个前缀开头的反引号 span 做存在性校验，`src/`、`tests/`、`lib/`、相对/绝对路径、裸文件名一律**跳过且无任何“已跳过 N 条”提示**——见 Fixture C。**这是真实漏洞：评审最常引用的源码/测试文件恰好落在盲区。**
- 10d：A、B 确认非零退出；C、D 确认可绕过；F 确认误报。

**门的本质边界：** Rule A 只扫描 `round/evidence/**` 与 `round/reviews/**`（`:77-82`），**根本不看 agent 对真实代码的改动**——而协议语境里“scope-lock”正是约束代码改动边界的。故 verify 满足**字面**验收（evidence/review 写入路径受检），但远弱于“scope-lock”一词给用户的心理预期。

判定 conditional-pass。

### P0-6 CI（conditional-pass）

- `.github/workflows/validate.yml`：`matrix.os = [ubuntu-latest, windows-latest, macos-latest]`（`:12-13`），`fail-fast: false`（`:11`），`actions/checkout@v4`、`actions/setup-python@v5`（3.12），`env HARNESSLOOP_SKIP_CLAUDE: "1"` 且注释说明“CI 无 Claude CLI、strict 校验在本地/发布前跑”（`:23-26`）——**跳过合理且诚实标注**。`python scripts/validate.py` 内部即涵盖 verify（阶段 5）与文档一致性（阶段 4），三合一无遗漏。
- 版本/action 无明显过时或 YAML 错误。
- `.github/` 下仅 `workflows/validate.yml`，无 CODEOWNERS/CONTRIBUTING/ruleset。

**证伪点（成立）：** 验收要求“**PR 未过 CI 不可合并**”。这需要 GitHub branch protection / rulesets（仓库设置，文件层无法表达）。全库 grep `branch protection|required check|cannot be merged|ruleset|CODEOWNERS` **无任何相关标注**（唯一命中是无关模板 `intake-review-round-template.md:24` 的 “## Required Checks”）。实现方既未配置也未在 README/工作流/CONTRIBUTING 里注明“需手动开启分支保护”——按清单 12 要求，**报告为 gap**。
- 附带 minor：CI 实际跑 `python scripts/validate.py`，**不是** `npm run validate`（P0-2 验收字面要求的入口），导致 `run-python.mjs` 这条 npm 入口在**任何平台 CI 都未被覆盖**。

判定 conditional-pass。

### 回归检查（无回归）

- `git diff HEAD -- init_project.py`：仅新增 `INTAKE_FILES` 字典（`:43-45`）与其写入循环（`:113-114`），纯增量；`BASE_DIRS` 仍含 `.harnessloop/intake`。
- `harnessloop-loop/SKILL.md` +`intake/.gitignore` 注释行；`harnessloop-init/SKILL.md` +`intake/`+`.gitignore` 两行。均与新 `INTAKE_FILES` 一致。
- init smoke（validate 阶段 2）实测创建全部 12 个文件含 `intake/.gitignore`，退出 0。
- 未发现引入回归。

---

## 三、缺陷清单（按严重度排序）

### BLOCKER
无。核心交付物均存在并对已演示场景正常工作。

### MAJOR

**M1 · verify 门与 scope-lock 模板格式漂移 → 合规轮被误判失败（P0-5）**
- 现象：`scripts/../references/scope-lock-template.md:8-11` 教用户用**表格**写 Allowed Changes（无反引号）；`verify_protocol.extract_allowed_spans:49-60` 只认反引号 span。用户照模板写 → `unparseable-allowed-changes` → 退出 1。
- 复现：Fixture F（表格式 scope-lock + 任一 evidence 文件）→ `EXIT 1`。而 verify 只对**手工调成反引号-bullet 格式的** `examples/mock-project/.../scope-lock.md:7-11` 验证过。
- 影响：真实用户首次对合规轮跑 verify 大概率报错，且报错信息晦涩。这正是 P0-4 想消灭的“文档/实现漂移”在 verify 与模板之间复现。
- 建议：统一 scope-lock 格式约定——要么 `extract_allowed_spans` 同时解析表格单元格路径（并容忍无反引号），要么把模板改成反引号-bullet 并在 SKILL/文档明确“路径必须反引号包裹”，并加一个 fixture 锁定该约定。

**M2 · Rule B 引用存在性对源码/测试引用整体失效（P0-5，清单 10c）**
- 现象：`PATHISH_PREFIXES`（`verify_protocol.py:26-37`）只覆盖 `.harnessloop/`/`rounds/`/`evidence/` 等 10 个前缀；评审引用 `src/…`、`tests/…`、相对/绝对路径、裸文件名一律不校验且无提示。
- 复现：Fixture C，review 引用三条不存在路径（含 `src/app/missing_module.py`）→ `EXIT 0`，零 violation。
- 影响：评审最常见的证据引用（源码、测试文件）恰在盲区，可引用完全捏造的证据而过门——直接削弱验收原文“评审文件引用的证据路径必须存在”的承诺。且“通过”是**静默**的，用户误以为已核验全部引用。
- 建议：对“看起来像路径但不在前缀白名单”的 span，至少输出“N 条引用未校验（不在受控目录）”的告警计数；或扩展为“含 `/` 且非命令样式”的启发式并结合 `.gitignore`/存在性做软校验。

**M3 · P0-1 的 manifest SPDX / marketplace 许可证引用未落地且未被校验**
- 现象：见 P0-1。两个 plugin manifest 无 SPDX，两个 marketplace 无许可证引用；`validate.py` 不检查这两项。
- 复现：`grep -i license/spdx/Apache` 于 `plugins/harnessloop/**.json`、`.claude-plugin/marketplace.json`、`.agents/plugins/marketplace.json` 全部 0 命中。
- 影响：3 个 P0-1 子验收只满足 1 个；且缺口被 validate 绿灯掩盖（漂绿）。
- 建议：向两个 `plugin.json` 加 `"license": "Apache-2.0"`（Claude 用 SPDX 字段、Codex 按其 schema），marketplace 元数据加许可证引用；并在 `validate_manifests` 增加对应断言，使“未加”即红灯。

> 备注：Fixture D（evidence/reviews 之外的越界写入不可见）严格按 P0-5 **字面**验收（只提“evidence/review 写入路径”）可算 by-design，故未单列 major；但“scope-lock”一词强烈暗示约束真实代码改动，用户很可能误期 verify 能抓越界源码编辑——列为下方 minor #7 并入 1.0 扩面。

### MINOR

**m4 · `validate.sh` 不校验 Python 主版本**（`scripts/validate.sh:7-14`）。在“`python`=Python2 且无 `python3`”的主机上会用 Python 2 执行 `validate.py`，因 `from __future__ import annotations`/f-string 触发 SyntaxError 而非预期的干净“Python 3 not found”提示。仍 fail-safe（非零），但与 `run-python.mjs`/`validate.ps1` 的行为不一致。建议对齐：探测 `--version` 匹配 `Python 3`。

**m5 · P0-6 “未过 CI 不可合并”未配置也未标注**。branch protection 属仓库设置，文件层做不到；实现方无任何“需手动开启分支保护/必需状态检查”的说明。建议在 CONTRIBUTING 或 README 明写为发布前手动待办，避免误以为文件层已强制。

**m6 · 文档一致性校验假阴性（P0-4）**。`validate_doc_consistency` 只做“basename/顶层目录子串出现即通过”，无法发现“掩蔽删除”（如 `evidence-index.md` 被散文掩蔽，已复现）与“错放目录”。建议：把骨架块（fenced ```text 区）单独抽取，按**相对路径**（含父目录）匹配，而非全文裸 basename。

**m7 · verify 覆盖面过窄（P0-5，Fixture D）**。Rule A 只扫 `evidence/`、`reviews/`；对 round 根、`state/`、项目源码的越界写入完全不可见；且某轮不写 evidence/reviews 时，畸形/缺失 scope-lock 不报错。P1-6 已规划扩面，建议至少把“round 目录内 scope-lock 之外的新文件”纳入扫描。

**m8 · CI 未覆盖 `npm run validate` 入口**。CI 直接 `python scripts/validate.py`，`run-python.mjs` 三平台均未在 CI 跑到。建议 CI 增一步 `npm run validate`（或至少一个平台）以覆盖 npm 入口。

### NOTE

- **n9 · 最低 Python 版本未声明/未强制**。`skeleton_entries` 用 `str.removeprefix`（3.9+）；CI 固定 3.12 无碍，但本地 3.8 会在阶段 4 崩。建议文档/`package.json engines` 或运行时提示注明 ≥3.9。
- **n10 · `.tmp/` 残留 smoke 目录**（`init-smoke-*`、`secrets-smoke-*` 等，已 gitignore，纯 cosmetic，疑似历史开发残留；本人对抗 fixture 已全部清理）。

---

## 四、结论

**本轮 P0 修复达到了 `product-feedback.md` 承诺验收标准的“可用下限”，且方法诚实**：跨平台 validate 真正跑通并对失败非零退出、硬编码路径清除彻底、文档现状确实一致、verify MVP 对承诺演示的越界/悬空场景确实非零退出、CI 三平台矩阵齐备。没有 blocker，没有需要驳回的 outright fail。

**但作为对抗方，我必须指出：6 项里有 4 项是 conditional-pass，且其中的门在“真实用户的常见路径”上会失灵。** 尤其 P0-5 的 verify——它当前主要是对**手工调成兼容格式的 mock-project**成立，一旦用户按官方 scope-lock 模板写（M1）或用源码/测试文件作证据引用（M2），门要么误报要么漏判。这与本轮想树立的“代码保证协议下限”承诺存在实质差距：**下限存在，但比宣称的窄。**

**1.0 前必须解决（阻塞“信誉底线”）：**
1. **M1**：verify 与 scope-lock 模板格式对齐（否则 verify 对真实轮不可用）。
2. **M2**：Rule B 至少对未校验引用给出告警计数，消除“静默漏判源码/测试引用”。
3. **M3**：补齐两个 manifest SPDX 与 marketplace 许可证引用，并让 validate 断言之。
4. **m5**：把 branch protection 明确写为发布前手动待办（兑现“未过 CI 不可合并”）。

**建议一并处理：** m4（validate.sh 版本探测）、m6（骨架按相对路径校验）、m7/m8（verify 扩面 + CI 覆盖 npm 入口）、n9（声明最低 Python 版本）。

> 复评过程中对 `README.md` 的临时改动、`.tmp/` 下 Fixture A–F 均已还原/清理；工作树已恢复至复评前状态（`README.md` 与备份 hash 一致，tracked 修改仍为原 10 个 P0 文件）。本报告为唯一新增产物。

---

## 复检（第二轮）

> 日期：2026-07-02（同日第二轮）。立场不变：设法证伪。基线：实现方声称已修复第一轮 3 个 major 与部分 minor。
> 环境：`py -3` = Python 3.13.0；README 复检前后 SHA256 均 = `68b5a4217c370cecc9595a5a6e27f369349e2e70fa83f71ba8aaa22053a25390`（byte-identical，已还原）。
> 所有第二轮 fixture 置于 `.tmp/adv-recheck/`，测后删除；README 经 hash 校验还原。

### 基线回归（先确认无回归）

- `py -3 …/verify_protocol.py --project examples/mock-project --json` → `violations: []`，**EXIT 0**。新引入的路径启发式**未对 shipped 仓库产生误报**。
- `HARNESSLOOP_SKIP_CLAUDE=1 py -3 scripts/validate.py` → 六阶段全 `ok`，**EXIT 0**；含新增的 4 条 license 断言与 stage-5 的 2 条新 fixture。
- `npm run validate`（经 `run-python.mjs` shim，即 CI 实际入口）→ 同样全绿，**NPM_EXIT 0**。

### 逐项声称修复判定

**① major-1 模板表格 scope-lock —— VERIFIED（已修复）**
- 代码：`verify_protocol.py:49-77` `extract_allowed_spans` 现同时 (a) 收反引号 span，(b) 解析 `|` 表格行首列为路径，并正确跳过表头（`path/data/tool`/`path`/`file`/`target`）、分隔行（仅 `-`/`:`/空格）、含空格单元格。
- 独立 fixture F（严格按 `scope-lock-template.md` 的 `Path/data/tool` 表头 + 两行路径）→ **EXIT 0，零 violation**（第一轮此处为误报 EXIT 1）。
- 畸形表格鲁棒性（fixture WT：空首列、含空格散文行、junk 单词行、真实路径行混排）→ 不崩溃、真实路径仍被解析、越界的 `reviews/sneaky.md` 仍被 `scope-lock-violation` 抓住，junk 单词 span **未**造成误放行。
- validate.py stage 5 有对应表格 fixture 断言（`scripts/validate.py:268-283`）并通过。
- 残留 note（非 blocker）：表格解析假设「路径在**首列**」（与模板一致）。若用户重排列序且路径不带反引号，会漏解析——属格式偏离，与原 M1 同类但概率大降。

**② major-2 非前缀引用存在性 —— VERIFIED（已修复），但引入新的误报 minor**
- 代码：`verify_protocol.py:80-102` `pathish_citations` 现对「含 `/` 且（有扩展名/以 `/` 结尾/含 `..`）」的 span 也做存在性校验，排除含空格/`://`/以 `-`/`$`/`<` 开头的 span。
- 独立 fixture Bsrc（review 引用 `src/app/missing_module.py` 与 `tests/test_missing.py`）→ **两条均 EXIT 1 `dangling-citation`**（第一轮此处为 EXIT 0 漏判）。validate.py stage 5 亦断言 `src/app/missing_module.py` 悬空（`:262-266`）。
- **新问题（minor，见下 nm11）**：误报探针 fixture FP 证明——启发式**正确跳过**了任务重点担心的常见非文件 span（`a/b`、`and/or`、`n/a`、`read/write`、`client/server`、`24/7`、`key/value`、`foo/bar`、以及带 `://` 的 URL），即 `a/b` 不误报；但**会误报**：无协议裸域名且尾段带扩展名的链接（如 `docs.python.org/3/library/os.html`、`github.com/org/repo/blob/main/src/foo.py`）、带斜杠的点号代码表达式（`numpy.ma/core.py`、`a.b/c.d`）、以及评审引用的项目外/绝对路径（如 `/etc/nginx/nginx.conf`）。这些在第一轮是被跳过的，属**修复新引入的误报**。

**③ major-3 manifest/marketplace 许可证 —— VERIFIED（已修复）**
- 4 个 JSON 均含 `"license": "Apache-2.0"`：`plugins/harnessloop/.claude-plugin/plugin.json:5`、`.codex-plugin/plugin.json:4`、`.claude-plugin/marketplace.json:14`、`.agents/plugins/marketplace.json:9`。
- `validate.py:100-105` 4 条断言全部 `ok`。删任一 license 字段即会红灯（断言硬编码 `== "Apache-2.0"`）。
- note：验收字样为「SPDX 标识」，此处以 `license` 字段值承载 SPDX 表达式（与 `package.json` 一致的惯例），视为满足。

**④ 文档一致性假阴性 —— PARTIALLY VERIFIED（声称的散文掩蔽已堵，但仍可用 code block 掩蔽）**
- 代码：`validate.py:181-227` 新增 `skeleton_blocks`，tree 型文档只在含 `.harnessloop/` 的 fenced code block 内匹配。
- 攻击 (a)【重复第一轮】：从 README 骨架删 `evidence-index.md`、保留散文提及（`README.md:148`）→ 现 **FAIL**：`missing: ['state/evidence-index.md']`。**第一轮的散文掩蔽绕过已关闭。** ✅
- 攻击 (b)【新角度】：删真实骨架条目 + 另加一个**假的** `.harnessloop/` code block（含 `evidence-index.md`）→ **PASS（仍被绕过）**。❌ 原因：`skeleton_blocks` 把**所有**含 `.harnessloop/` 的 fenced block 拼成一个字符串做裸 `name not in scope` 子串判定，未校验该文件名是否落在**真正画树的那个** block、也不校验相对父路径。→ **残留 minor（nm12）**：掩蔽面从「任意散文」收窄到「任意 `.harnessloop/` code block」，实用性大增（散文不再掩蔽），但决定性/巧合性的第二个 code block 仍可掩蔽（例如某文件同时出现在示例命令 block 与骨架 block 时，从骨架删除不会被抓）。实现方 docstring 只声称「防散文掩蔽」——该字面声称属实；残留超出其声称范围。

**⑤ CI gaps —— VERIFIED（已修复）**
- `.github/workflows/validate.yml:33` 改跑 `npm run validate`（覆盖 `run-python.mjs` shim）；`:22-24` 新增 `actions/setup-node@v4`；`:35-37` 尾注释明确 merge gating 需仓库层 branch protection / ruleset。
- `package.json:7` `validate` → `node scripts/run-python.mjs scripts/validate.py`，故 shim 三平台均被 CI 覆盖（第一轮 m8 关闭）；实测 `npm run validate` EXIT 0。
- 第一轮 m5（branch protection 未标注的诚实性 gap）：现由 workflow 尾注释明写为「仓库设置、文件层无法表达」，兑现了「文档化为发布前手动待办」的要求。✅（注：仍**未**也无法在仓库文件内真正启用分支保护，属既定限制，已诚实标注。）

**⑥ validate.sh 版本探测 —— VERIFIED（已修复）**
- `scripts/validate.sh:8-13`：对 `python3`/`python` 逐个 `--version 2>&1 | grep -q "Python 3\."` 校验主版本，与 `run-python.mjs`/`validate.ps1` 行为对齐。第一轮 m4 关闭。

### 新发现的问题

- **nm11（minor，P0-5）· major-2 修复引入路径启发式误报**。`pathish_citations`（`verify_protocol.py:98-101`）对「含 `/` 且尾段有扩展名」的 span 一律做存在性校验，导致无协议裸域名链接、带斜杠的点号表达式、项目外/绝对路径被误判 `dangling-citation` 使合规轮 EXIT 1。复现：fixture FP。影响面：需同时满足「反引号 + 无 `://` + 含 `/` + 尾段带点」，常见比率/连词类 span 已正确豁免，故为 minor；shipped 仓库当前零误报。建议：URL 放宽（识别裸域名/顶级域）、对绝对路径或项目外路径降级为「N 条未校验」告警而非硬失败。
- **nm12（minor，P0-4）· 骨架一致性仍可被第二个 code block 掩蔽**。`skeleton_blocks` 跨所有 `.harnessloop/` code block 拼接后裸子串匹配，未按「画树的 block + 相对路径」定位。复现：攻击 (b)。较第一轮（任意散文即掩蔽）已大幅收窄，但非彻底。建议：仅取**首个/最长**的树骨架 block，或按相对路径（含父目录，如 `state/evidence-index.md`）匹配。

> 第一轮 m7（verify 覆盖面：round 根/`state/`/源码越界不可见；某轮不写 evidence/reviews 时畸形/缺失 scope-lock 不报错）、n9（最低 Python 版本未声明）实现方本轮**未声称修复**，经复看代码仍然存在，维持原判，属 P1 扩面项，不阻塞。

### 最终逐项 P0 判定表（第二轮）

| 项 | 第一轮 | 第二轮 | 变化 | 依据 |
| --- | --- | --- | --- | --- |
| P0-1 | conditional-pass | **pass** | **升级** | M3 关闭：4 个 manifest/marketplace 均有 `license` 且 validate 断言之。 |
| P0-2 | pass | **pass** | 维持（强化） | m4 关闭：`validate.sh` 现校验 Python 主版本。 |
| P0-3 | pass | **pass** | 维持 | 本轮无相关改动，无回归。 |
| P0-4 | conditional-pass | **pass（带残留 minor nm12）** | **升级** | 散文掩蔽（第一轮实证绕过）已堵；残留仅「第二个 code block 掩蔽」，收窄且非致命。 |
| P0-5 | conditional-pass | **pass（带新 minor nm11 + 既有 m7）** | **升级** | 两个 major 绕过（M1 表格误报、M2 源码/测试悬空引用漏判）均已关闭；新引入的误报 nm11 与既有覆盖面 m7 为 minor。 |
| P0-6 | conditional-pass | **pass** | **升级** | m8 关闭（CI 跑 npm 入口覆盖 shim）；m5 关闭（branch protection 已在 workflow 内诚实标注为仓库层待办）。 |

**第二轮总结论：实现方声称的 6 项修复中，5 项 fully verified（①②③⑤⑥ 对应 major-1/2/3、CI、validate.sh），1 项 partially verified（④ 文档一致性：声称的散文掩蔽已堵属实，但仍可被 code block 掩蔽）。3 个原 major 全部关闭，6 项 P0 全部升级为 pass。新发现 2 个 minor（nm11 路径启发式误报、nm12 骨架二次掩蔽），均不阻塞 1.0，建议随 m7/n9 一并收口。无 blocker、无 outright fail、无回归。**

> 第二轮所有临时产物已清理：`.tmp/adv-recheck/`（fixture A/Bsrc/D/F/FP/WT）与 `drive_doc.py`、`README.md.bak` 均删除；`README.md` 经 SHA256 校验 byte-identical 还原。`.tmp/` 下遗留的 `init-smoke-*`/`secrets-smoke-*` 目录为第一轮 n10 已记录的既有残留（validate.py 自管理、gitignored），非本轮 fixture。本次仅新增本节文字。
