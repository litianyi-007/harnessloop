# Harnessloop

**長時間実行される AI エージェントタスクを監査可能にするプロトコル——そして、自分が強制できないことについて正直である。**

[![validate](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml/badge.svg)](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml)

> 🇨🇳 [中文](README.md) ・ 🇬🇧 [English](README.en.md)

長時間のエージェントセッションはドリフトする。コンテキストは圧縮され、エビデンスは古くなり、
ラウンドは裏付けのないまま成功を主張し、気づいたときには、その主張を生んだ推論はもう
残っていない。

Harnessloop はその作業を**ラウンド（round）**単位に変換する。各ラウンドは、自分が変更して
よい範囲、生成するエビデンス、そして到達した判定（verdict）を宣言する。そのうえで機械的な
ゲート（gate）が、小規模で特定の一群の**自己矛盾（self-contradictions）**を拒否する
（refuses）——そして、自分が*チェックしないもの*をすべて文書として伝える。

## 実際に行うこと

| | |
|---|---|
| **ラウンド単位のスコープロック（Scope-lock）** | 各ラウンドは自分が触ってよいパスを宣言する。宣言外の変更は報告される。 |
| **エビデンス契約（Evidence contracts）** | 主張は成果物（artifact）を引用する。解決できない引用パスは報告される。 |
| **ランタイム受け入れ評価（Runtime acceptance evals）** | 外部システムを宣言し、評価（eval）をそれに紐付け、実行をラウンドごとの台帳（ledger）に記録する。**due な eval が pass しなかったラウンドは `positive` としてマークされてはならない。** |
| **拒否であって強制ではない（Refusal, not enforcement）** | ゲートには**66 種類の違反（violation kinds）**がある。ゲートは、ラウンドが自分のファイルと矛盾する何かを*主張する*ことをブロックする。 |
| **登録された制限（Registered limits）** | すべての機構は、自分にできることと同じ文書の中に、自分にできないことも同梱して出荷される。 |

## ほとんどのツールが省いている部分

Harnessloop の機械的ゲートは、エージェントが書いたファイルを読む。**それは動機（motive）を
検証できない——そして、そのことを自分で明言している。**

- ラウンドの eval 台帳とその判定（verdict）が一致しているかはチェックできる。**しかし eval
  が実際に実行されたことは証明できない**——でっち上げた成果物の横に手書きで
  `"outcome": "pass"` と書けば、それは通ってしまう。
- レビューが行われたこと、そしてそれがどのファイルに収められているかは記録する。**レビュー
  の本文（prose）を読むことは一切ない。**
- 出荷されているドキュメント自身が、境界（boundary）についてのセクションをこう書き出して
  いる: **"The mechanical gate's exit code decides less than it looks like it decides."**
  （機械的ゲートの終了コードが決めていることは、見た目ほど多くない）
  そして eval 台帳については: **"does not prove the mechanical gate was ever actually
  run."**（機械的ゲートが実際に実行されたことを証明するものではない）

これらの文はどれも、ここだけでなく出荷されている skill のドキュメントの中にも存在する。ある
機構が実際に提供する以上のことを主張していたと判明したときは、その主張は撤回され、撤回した
事実も記録された——Harnessloop を使っているプロジェクトの
`.harnessloop/meta/evolution-issues/` を参照。

## クイックスタート

```bash
# 1. Install (Claude Code)
/plugin marketplace add litianyi-007/harnessloop
/plugin install harnessloop@harnessloop

# 2. In your project
$harnessloop-init      # scaffold .harnessloop/
$harnessloop-setup     # 5-step wizard; three files gate continuation until filled
$harnessloop-goal propose "<one-line goal>"
$harnessloop-loop      # run the loop
```

`$harnessloop-continue` は再開用の経路（resume path）である。現在の状態を読み込み、
continuation gate を実行し、コントロール契約（control contract）が許可する次のアクション
だけを許可する。

## ランタイム eval をひと目で

```jsonc
// .harnessloop/setup/external-systems.json   — no URLs, no secrets, parameter names only
{"version": 1, "systems": [
  {"id": "staging-api", "kind": "http", "description": "...", "params": ["STAGING_API_BASE"]}]}

// <goal>/evals.json
{"evals": [{"eval_id": "RAE-0001", "activation_round": 1, "system": "staging-api"}]}

// <round>/evidence/runtime/acceptance-evals.json
{"entries": [{"eval_id": "RAE-0001", "attempt_id": "0007-a1", "outcome": "fail",
              "frozen_due_set": ["RAE-0001"], "evidence": "evidence/runtime/rae-0001.log"}]}
```

この台帳がある状態で、`Feedback: positive` を宣言する `decision.md` は**拒否される**。
`outcome` を `pass` に変えれば受理される。**Harnessloop は eval を実行しない**——実行する
のはあなたのセッション、CI、あるいはランナーである。Harnessloop が持っているのは台帳と拒否
そのものだけである。

この宣言ファイルには、構造上**URL・ホスト・パスのフィールドが存在しない**——存在するのは
`^[A-Z][A-Z0-9_]{0,63}$` に一致するパラメータの*名前*だけである。書き込む場所がそもそも
ないので、認証情報（credential）をそこに書き込むことはできない。

## こういうときに使う

Harnessloop を使うべき場面:

- 長時間にわたるコーディング、リサーチ、データ、または検証タスク。
- 実データ（static data）、生成データ（generated data）、ランタイムのエビデンス、
  ソースコード、あるいは外部システムに依存する作業。
- 別のエージェントからのセッションをまたぐタスク引き継ぎ（takeover）。
- 最小変更のスコープロックと監査可能なハンドオフ（handoff）が必要なタスク。
- 失敗、ロールバック、あるいは人間による確認が明示的でなければならない作業。

使うべきでない場面:

- 一回きりの質問。
- その場で検証できる小さな編集。
- 永続的なエビデンスやハンドオフが不要なタスク。

## インストール

Windows 上の Codex:

```powershell
.\scripts\install-codex.ps1
```

Windows 上の Claude Code:

```powershell
.\scripts\install-claude.ps1
```

macOS/Linux 上の Codex:

```bash
./scripts/install-codex.sh
```

macOS/Linux 上の Claude Code:

```bash
./scripts/install-claude.sh
```

同等の CLI コマンド:

```powershell
codex plugin marketplace add .
codex plugin add harnessloop@harnessloop

claude plugin marketplace add . --scope user
claude plugin install harnessloop@harnessloop --scope user
```

## 最初のループを始める

Harnessloop は現時点では skill／プロトコルであり、独立したシェル CLI ではない。Codex の
明示的な skill 呼び出しは `$harnessloop-init` のような kebab-case 名を使う。
`harnessloop:init` のようなコロン形式は自然言語のエイリアスにすぎない。`$harnessloop:init`
は正当な skill mention ではない。

インストール後、エージェントにこう頼む:

```text
$harnessloop-init
```

このリポジトリから決定的に初期化するには:

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project
```

macOS/Linux:

```bash
./scripts/init-project.sh --project /path/to/target-project
```

最初のセットアップで作成/記入されるのは:

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

その後 `$harnessloop-loop` を使って、goal を定義し、分解可能な閾値（decomposable
thresholds）を作り、最初のラウンドのスコープをロックし、エビデンスを書き、対抗的レビュー
（adversarial review）を実行し、フィードバックを分類し、コントロールゲートを通してのみ
継続する。

ランタイムのブロッカー（blocker）が現れた場合、Harnessloop は停止する前にそれを分類する。
回復可能なブロッカーは、範囲が限定された読み取り専用の調査ラウンドへと移行する。アクセスの
欠如、安全でない書き込み、外部トリガー、クリーンアップの判断、あるいはビジネス上の判断が
必要な場合は、そこで一時停止し、不足している入力を正確にユーザーに尋ねる。

## 既存のエージェントセッションを引き継ぐ

引き継ぎ元のセッションに Harnessloop がインストールされている必要はない。そのセッションに
`Harnessloop Transfer Packet` を生成するよう依頼し、その結果を保存する:

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project -Intake task-slug
```

```text
.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/transfer-packet.md
```

Harnessloop は正式な goal を作成する前に intake gate を実行する:

```text
$harnessloop-intake
```

![Harnessloop の引き継ぎ intake フロー](docs/assets/takeover-intake-flow.svg)

パケットが不完全な場合、Harnessloop は `gap-review.md` を書き、不足している事実だけを
尋ねる。パケットが通過した場合、最初のラウンドは通常 `intake-review` であるべきで、そこで
ビジネス上の実行が続く前に、取り込んだエビデンスを `.harnessloop/state/evidence-index.md`
にマッピングする。

Transfer packet には、タスクの識別情報（task identity）、goal contract、進捗状態、変更
状態、ドキュメント一覧、プロセス成果物、エビデンス、外部ツール、秘密の値を含まない認証情報
の要件、ローカルのチャネルパラメータキー、決定事項、リスク、そして次のハンドオフ推奨事項が
含まれていなければならない。完全なプロンプトは [docs/usage.md](docs/usage.md) を参照。

## エビデンスモデル

Harnessloop は、エビデンス成果物そのものの健全性（health）と、そのエビデンスが受け入れ
（acceptance）を裏付けるかどうかを分けて扱う。失敗したランタイムテストは、有効なエビデンス
成果物でありながら、なお negative なフィードバックを生むことがある。

![Harnessloop の evidence スタック](docs/assets/evidence-stack.svg)

エビデンスの分類（classes）:

- `static`: 実データセット、ドキュメント、レポート、正本記録（source-of-truth records）。
- `dynamic`: 生成されたデータ、サンプリングされた出力、モデル／ツールの出力。
- `runtime`: テスト、CI、リモート自動化、プローブ（probes）、カナリア（canaries）、
  モニタリング。
- `source`: リポジトリのソース、スキーマファイル、ソースデータファイル。

## 外部チャネル

Harnessloop は、チャネルの棚卸し（inventory）と接続性チェック（connectivity checks）を
分けて扱う:

- `$harnessloop-channels`: 宣言済みの外部システム、ツール、MCP サーバー、CLI、API、CI
  システム、データベース、ブローカー、認証情報の参照先を、プローブすることなく列挙する。
- `$harnessloop-connectivity`: 必要なツール、エンドポイント／リソース、認証情報の参照先、
  権限スコープ、パラメータ、書き込みの安全性ルールが明示された後にのみ、宣言済みの接続性
  チェック手法を実行する。
- `$harnessloop-secrets`: `.harnessloop/local/channel-params.json` にあるローカル限定の
  チャネルパラメータキーを作成・チェックする。値がコミットされたりエビデンスにコピーされ
  たりすることは決してない。

チャネルのセルフチェックが失敗する、ブロックされる、スキップされる、あるいは情報が不足して
いてユーザーの確認が必要になる場合、Harnessloop は代替手段を試したり続行したりする前に、
不足している事実を正確に尋ねなければならない。

## 主要な概念

- `goal`: ループが達成しようとしていること。
- `transfer packet`: 既存のエージェントセッションからの構造化されたハンドオフ。
- `intake gate`: 安全でない続行をブロックする、引き継ぎ時のレビュー。
- `scope-lock`: 1 つのラウンドが変更してよい範囲の正確な境界。
- `evidence gate`: ラウンドが pass するために必要な証明。
- `handoff`: サブエージェントやレビュアーのための、ファイルベースのタスク引き渡し。
- `channel inventory`: プローブすることなく列挙される、宣言済みの外部システムとツール。
- `connectivity check`: 必要なアクセス情報が不足している場合に停止して尋ねる、宣言済みの
  アクセス検証。
- `local channel parameters`: 外部チャネルが使う、無視される（ignored）ローカル値または
  プロバイダ参照。
- `blocker type`: ブロックされたラウンドが読み取り専用の回復（recovery）に進めるか、それとも
  ユーザーに尋ねなければならないかを決める分類。
- `self-audit`: デッドループ、矛盾、ドリフト、暴走したコンテキストについてのループ健全性
  チェック。
- `evolution issue`: Harnessloop 自身の改善に役立つ、機密情報を除去した（redacted）issue。

## 実行の委任（Execution Delegation）

Harnessloop は、オーケストレーションと制御判断の責任をメインセッションに保持し続ける。
境界が定められた作業については、それがコンテキストを保護しレビュー品質を高める場合に限り、
ファイルハンドオフを通じて委任する:

| タスク種別 | 判断 |
| --- | --- |
| 読み取り専用の探索（Read-only discovery） | パスと問いの範囲が限定されている場合は委任すべき。 |
| エビデンス収集（Evidence collection） | 読み取り専用であり、機微性（sensitivity）が理解されており、出力がパスを引用している場合に限り委任する。 |
| 外部接続性（External connectivity） | `$harnessloop-connectivity` を使う。当て推量のプロービング（blind probing）は委任しない。 |
| 低リスクなローカル実装（Low-risk local implementation） | scope-lock、ロールバック、検証コマンドを伴えば委任してよい。 |
| 高リスクな実装（High-risk implementation） | 統合はメインセッションが所有する。委任するのは狭いサブタスクのみ。 |
| 対抗的レビューと受け入れテスト（Adversarial review and acceptance testing） | 機構とエビデンスの引用が検証可能な場合は委任する。 |
| ラウンドの受け入れと制御判断（Round acceptance and control decisions） | 決して委任しない。 |

モデル、努力量（effort）、スコープ制御、出力パスの制御、あるいはエビデンス引用の挙動を検証
しなければならない場合は、サブエージェントやスウォーム（swarm）の作業に頼る前に
`$harnessloop-delegation` を実行する。

## コストの説明責任（Cost Accountability）

Harnessloop は、自分自身のオーバーヘッドをプロトコルの第一級の測定値として扱う。各ラウンドの
クローズ時に、`round_cost.py` がローカルのセッショントランスクリプトからトークン使用量を
精算し、ラウンドサマリーに項目別の `## Cost` セクションを書き込む: 入力／キャッシュ／出力
トークン、プロトコル起因分の見積もり（protocol-attribution estimate）、そしてユーザー指定
のレートに基づく任意のドル金額。ゲートによる差し止め——対抗的レビューによって却下された
ラウンド、self-audit が捉えたドリフト——は decision ファイルに記録され、プロトコルのコスト
とその捕捉実績が同じ監査可能な台帳の中に収まるようにしている。

Harnessloop は、そのオーバーヘッドが元を取れる（pays for itself）とは主張しない。Harnessloop
が渡すのは、請求書（bill）、差し止めの記録、そして判断のためのフレームワークであり、判断
そのものはあなた自身のプロジェクトのデータに委ねる。詳細は
[docs/cost-model.md](docs/cost-model.md) を参照。

## Skills

- `$harnessloop-init`: `.harnessloop/` のプロジェクトファイルを初期化する。
- `$harnessloop-setup`: 5 ステップのセットアップウィザードを通じて、環境検出、データ
  ソース、コスト／コンテキストポリシー、control-contract プロファイルを完成させる、または
  チェックする。
- `$harnessloop-intake`: transfer packet をレビューし、intake gate を実行する。
- `$harnessloop-goal`: goal の検査、交渉、更新、分割、アーカイブ、キャンセル、置き換え
  （supersede）、削除影響の評価を行う。
- `$harnessloop-evidence`: エビデンス契約の追加、チェック、修正、却下、差分（diff）比較を
  行う。
- `$harnessloop-channels`: 宣言済みの外部システム、チャネル、ツールを、プローブすることなく
  列挙する。
- `$harnessloop-connectivity`: 宣言済みの外部システム／ツールの接続性をチェックし、不足して
  いるアクセス情報を尋ねる。
- `$harnessloop-secrets`: ローカルのチャネルパラメータキー、シークレット参照、存在チェック、
  redaction ルールを管理する。
- `$harnessloop-delegation`: サブエージェント／スウォームの準備状況、スコープ制御、出力
  パス、エビデンス引用の挙動、モデル／エフォートの一致を確認する。
- `$harnessloop-status`: 現在の Harnessloop の状態を読み取る。
- `$harnessloop-continue`: 実行前に continuation gate を実行する。
- `$harnessloop-loop`: インストール済みのプロジェクトで goal 駆動の Harnessloop を実行、
  または引き継ぐ。
- `$harnessloop-issue`: Harnessloop の evolution issue を記録、分析、あるいは修正案を
  提示する。

## リポジトリマップ

- `docs/usage.md`: プロダクトレベルの利用ガイドと transfer packet のプロンプト。
- `docs/harnessloop-framework.md`: フレームワークの設計と詳細なプロトコル。
- `docs/cost-model.md`: プロトコルのオーバーヘッド測定とコスト／ベネフィットの判断
  フレームワーク。
- `docs/harnessloop-flow.mmd`: 正本となる詳細な Mermaid フローのソース。
- `docs/harnessloop-flow.svg`: レンダリングされた詳細フローのプレビュー。
- `docs/assets/`: README とドキュメントのビジュアル素材。
- `plugins/harnessloop/`: プラグインのソース。
- `plugins/harnessloop/skills/`: インストール可能な skill とテンプレート。
- `examples/mock-project/`: setup、intake、evidence、review、decision、self-audit、
  evolution issue の各ファイルを示す、人工的な参照プロジェクト。

## Validate（検証）

```bash
npm run validate
```

あるいは、どのプラットフォームでもバリデータを直接呼び出す:

```bash
python scripts/validate.py
```

ラッパースクリプト `scripts/validate.ps1`（Windows）と `scripts/validate.sh`
（macOS/Linux）は、同じ Python バリデータを実行する。

このバリデータは、marketplace マニフェストをチェックし、init と secrets のスモークテストを
実行し、ドキュメントのスケルトンの整合性を `init_project.py`（唯一の正本）と照合して検証し、
`verify_protocol.py` の機械的なプロトコルゲートを `examples/mock-project` に対して強制し、
Claude Code の strict プラグイン検証を実行する。Claude CLI がインストールされていない環境
では、`HARNESSLOOP_SKIP_CLAUDE=1` を設定するとその CLI ステップをスキップできる。

Codex の skill-creator ツールキットがインストールされている場合、その `quick_validate.py`
によって `plugins/harnessloop/skills/` 配下の各ディレクトリを追加で lint できる。

## 現在の制限（Current Limits）

- Harnessloop はプロトコルと skill を定義するものであり、完全なシェル CLI はまだ提供して
  いない。
- 固定のデータコネクタは同梱していない。プロジェクト側が自分自身のツール、アカウント、
  データソース、検証システムを宣言しなければならない。
- 詳細フローは `docs/harnessloop-flow.mmd` から保守されるべきであり、生成された、あるいは
  装飾的な画像がエビデンスを担うフロー図の代わりになってはならない。

marketplace のセレクタが安定した状態を保てるよう、両方のマニフェストでプラグイン名を
`harnessloop` のままにしておく:

```text
harnessloop@harnessloop
```
