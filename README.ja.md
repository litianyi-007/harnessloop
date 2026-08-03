# Harnessloop

**長時間実行される AI エージェントタスクを監査可能にするプロトコル——そして、自分が強制できないことについて正直である。**

[![validate](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml/badge.svg)](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml)

> 🇨🇳 [中文](README.md)（デフォルト） ・ 🇬🇧 [English](README.en.md)

## 長時間タスクでは、外部検証が loop の外にある

agent がコードを書き終えたあと、「この変更がうまくいっているかどうか」を実際に語るものは、
たいていそのプロセスの中にはない——再パッケージが必要で、対象環境へのデプロイが必要で、
リモートで起動して走らせる必要があり、結果は別のデータ基盤に落ちる。

標準的な agent loop はこれらを——**ログとして読む**ことで処理する。
agent は出力をひと目見て、自分で信じるかどうかを決め、そのまま続行する。その結果:

- 判定は**無視され得る**、しかも無視した痕跡は残らない。
- 判定は**リモート側にある**ため、今日それが上書きされるか再実行されれば、昨日のラウンドの
  結論はもう再現できなくなる。
- あるラウンドが成功を宣言するとき、**機械的な何か**が「待て、お前自身の記録には fail と
  書いてあるぞ」と言ってくれることはない。

Harnessloop が扱うのは、まさにこの部分である。

## 中核となる仕組み：判定をラウンドに凍結する

Harnessloop は作業を**ラウンド（round）**単位に切り分け、各ラウンドは自分が変更してよい
パス、生成するエビデンス、そして到達する結論を宣言する。外部システムの判定は、**ラウンド内
台帳（ledger）**を通じてそのラウンドの受け入れ条件に組み込まれる。これは 3 つの動作が
重なって初めて成立する:

**① eval は安定した ID を持つ第一級オブジェクトである。** `RAE-0001` はラウンドをまたいで
追跡できる——その場限りの呼び出しではない。

**② 到達すべき集合は、書き込まれた瞬間に台帳へ凍結される。** これが要である——この一手が
判定を**純粋にラウンド内で完結するもの**に変える。そのため「このラウンドを受け入れるべきか」
は、今日の時点で外部システムがどんな状態かに依存しなくなる。この一手がなければ、あらゆる
外部判定は時間をまたいだ突き合わせになってしまい、その道筋は過去のラウンドをリモート側の
変化とともに漂流させる。

**③ ゲートが拒否するのは「自己矛盾」であって「結果が悪いこと」ではない。** 外部システムの
判定が正しいかどうかは評価しない。「お前の台帳には fail と書いてあるのに、お前の結論には
positive と書いてある」ということだけを拒否する。

> **標準的な loop では、外部の判定は無視してもよいひと言にすぎない。
> ここでは、それは明示的に却下しない限り回避できない記録である。**

## 多段パイプラインの実際の形

重量級のプロダクト（クライアント、組み込み、実デプロイを要するサービス）の検証は、たいてい
1 回の呼び出しではなく**一連のシステム**である: パッケージング → デプロイ → 起動 →
アサーション、各段が別のシステムで、しかも非同期に進む。

**これに特別な仕組みは要らない: 1 本のパイプライン = N 個の eval、1 段につき 1 個。**

```jsonc
// <goal>/evals.json —— 4 段それぞれに 1 件
{"evals": [
  {"eval_id": "RAE-0001", "activation_round": 1, "system": "sys-build"},
  {"eval_id": "RAE-0002", "activation_round": 1, "system": "sys-deploy"},
  {"eval_id": "RAE-0003", "activation_round": 1, "system": "sys-run"},
  {"eval_id": "RAE-0004", "activation_round": 1, "system": "sys-assert"}]}

// <round>/evidence/runtime/acceptance-evals.json —— このラウンドで実際に何が起きたか
{"entries": [
  {"eval_id": "RAE-0001", "outcome": "pass", "frozen_system": "sys-build",  "…": "…"},
  {"eval_id": "RAE-0002", "outcome": "pass", "frozen_system": "sys-deploy", "…": "…"},
  {"eval_id": "RAE-0003", "outcome": "fail", "frozen_system": "sys-run",    "…": "…"},
  {"eval_id": "RAE-0004", "outcome": "skipped", "frozen_system": "sys-assert", "…": "…"}]}
```

この台帳がある状態では、`Feedback: positive` と書かれた `decision.md` は**拒否される**——
3 段目が通っていないからである。**実行漏れも同様に食い止められる**: `frozen_due_set` に
含まれる eval なのに台帳に対応するエントリが見つからない場合も、同じく拒否される。

`frozen_system` は各段がどのシステムに対して実行されたかを記録する——4 段が連なっている
とき、**どのシステムかを記録しなければ、どの一環が壊れたのか分からなくなる。**

**判定結果は取得され、そのラウンドの `evidence/` に書き込まれなければならない。** リモート
側の記録は上書きされ、消去され、再実行される。ラウンドの判定がリモートを指したままだと、
そのラウンドの結論はリモート側の変化とともに漂流してしまう。**取得は手間ではなく、ラウンドが
再生可能であるための前提条件である。**

## できないこと

このセクションは免責事項ではなく、このプロジェクトの設計上の立場である。**機械的なゲートが
読むのは agent 自身が書いたファイルであり、動機（motive）を検証することはできない——そして、
そのことを自分で明言している。**

- **eval が実際に実行されたことは証明できない。** `"outcome": "pass"` を手書きし、偽造した
  成果物を添えれば、それも通ってしまう。それが買っているのは「引用可能で、対抗的レビューに
  問い質せる」ということであって、実行力ではない。
- **レビューの本文は読まない。** レビューが行われたこと、そしてその成果物がどのファイルに
  あるかだけを記録する。
- **外部システムを一切トリガーせず、実行もしない。** パッケージング、デプロイ、起動、データ
  取得はすべてあなたのセッション、CI、あるいは runner が行う。**審判はコートに立たない**
  ——これも、「実行されたことを証明できない」のと同じ境界の裏側にすぎない。
- 出荷されているドキュメント自身が、境界（boundary）についてのセクションの冒頭でこう書いて
  いる:
  **"The mechanical gate's exit code decides less than it looks like it decides."**
  （機械的ゲートの終了コードが決めていることは、見た目ほど多くない。）
  そして eval 台帳については、こう書いている: **"does not prove the mechanical gate was
  ever actually run."**（機械的ゲートが実際に実行されたことを証明するものではない。）

上記の一文一文はすべて**プラグインと一緒に配布される skill のドキュメントの中にも**存在し、
この README だけに書かれているわけではない。ある機構が実装以上のことを主張していると判明した
場合、その主張は撤回され、撤回した事実自体も記録される。

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

## 外部システムと認証情報の接続

### channel の棚卸しと接続性チェックは別物である

Harnessloop は「channel の棚卸し（inventory）」と「接続性チェック（connectivity check）」を
別の 2 つの事柄として扱う:

- `$harnessloop-channels`: 宣言済みの外部システム、ツール、MCP サーバー、CLI、API、CI
  システム、データベース、ブローカー、そして認証情報の参照先を列挙する——列挙するだけで、
  プローブはしない。
- `$harnessloop-connectivity`: 必要なツール、エンドポイント／リソース、認証情報の参照先、
  権限スコープ、パラメータ、書き込みの安全性ルールがすべて明示されている場合に限り、宣言済み
  の接続性チェック手法を実行する。
- `$harnessloop-secrets`: `.harnessloop/local/channel-params.json` にローカル限定の
  channel パラメータキーを作成・チェックする。値がコミットされることも、エビデンスに書き
  写されることもない。

あるチャネルのセルフチェックが失敗する、ブロックされる、スキップされる、あるいは情報不足で
ユーザーの確認が必要になる場合、Harnessloop は他の方法を試したり無理に続行したりする前に、
不足している事実を正確に尋ねなければならない。

### 3 つのファイル、3 つの役割

「外部システムをこのプロトコルにどう接続するか」という 1 つの事柄は、実際には 3 つのファイル
に分かれて、それぞれが 1 つの役割を担っている（この 3 ファイルの分担については
`plugins/harnessloop/skills/harnessloop-loop/SKILL.md` により完全な説明がある）:

- `.harnessloop/setup/data-sources.md` の `## Runtime Validation Systems` テーブル:
  **どう検証するか、合格条件は何か**を散文で記述する——この記述はここにしか存在せず、
  どの機械的ゲートもこれを読みには行かない。
- `.harnessloop/setup/external-systems.json`: 純粋にメタデータとして**システム id、
  インターフェース種別（`kind`）、必要なパラメータ名**を宣言する——結果をどう判定するかには
  一切触れない。
- 各ラウンド自身の `evidence/runtime/acceptance-evals.json` 台帳: **そのラウンドで実際に
  何が起きたか**を記録する——段階ごとに 1 件、`outcome` を含み、その eval がどの宣言済み
  システムに対して実行されたか（`frozen_system`）も記録する。

3 つのファイルはそれぞれの役割に専念する——散文によるどう検証するかの説明、静的な宣言、
ラウンドごとの実際の記録。このプロトコルはこれらを混ぜたことは一度もない。

### なぜ認証情報は構造上書き込めないのか

`.harnessloop/setup/external-systems.json` では、各システムは `id`、`kind`、
`description`、`params` の 4 つのフィールドしか持たない——URL フィールドも、host
フィールドも、path フィールドもない。`params` が受け取るのも値ではなく、パラメータの
**名前**であり、しかも `^[A-Z][A-Z0-9_]{0,63}$` に一致する文字列しか受け付けない——この
文字集合には `/` も `:` も `.` も、小文字も含まれていないため、どう組み立てても URL、
host、path がこの形にマッチすることはあり得ない。

実際の値は `$harnessloop-secrets` が管理する channel-params
（`.harnessloop/local/channel-params.json`、gitignore 済み）経由でのみ扱われる。

これは**構造上の制約**である——認証情報はこの宣言ファイルの中にそもそも置き場所がない
のであって、「注意して書かないようにしている」わけではない。

### `kind` が表すのはインターフェース種別であって役割ではない

`kind` が現在取り得る値は `http` / `grpc` / `database` / `queue` / `filesystem` / `ssh` /
`process` / `other` である。これは単一の軸——**呼び出す側がどのインターフェースの形で
このシステムと話すか**——であって、そのシステムが特定のパイプラインの中でどんな役割を
果たすかではない。CI システムであれ、デバイスラボであれ、データ基盤であれ、それぞれが実際に
アクセスされるインターフェースの形に従って `kind` を宣言しなければならない（多くの場合は
`http`、あるいはリモート／ローカルでコマンドを実行する場合の `ssh`/`process`）。役割に
ちなんで名付けた `kind` を宣言するのではない——列挙型には `ci` や `dataplatform` のような
メンバーは存在しないし、今後も追加されない。これは最近下された、意図的な設計判断である——
直感的には逆に考えがちで、`kind` を「これは何のシステムか」だと捉えてしまい、「どうやって
それと話すか」だとは捉えにくい。

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

## リポジトリ構成と検証

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

### Validate（検証）

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
