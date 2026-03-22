# 要求仕様書

## はじめに

EqOrch は、方程式探索ワークフローを制御するオーケストレーションフレームワークである。`[dev_doc/EqOrch_SRS_v04_fixed.md](/Users/Daily/Development/EqOrch/dev_doc/EqOrch_SRS_v04_fixed.md)` で整理した SRS v0.4 を基に、本仕様では Kiro の requirements フェーズで扱いやすい要求単位へ再構成する。

EqOrch は探索アルゴリズムそのものを内包せず、LLM ベースのコンシェルジュ、ポリシーコンテキスト、再利用可能スキル、外部ツール、探索・実行エンジン、ワークフローメモリを束ねる制御層を提供する。

## 要求

### Requirement 1: ポリシーコンテキスト管理
**Objective:** As a 研究者, I want 外部ポリシーファイルで探索方針を定義したい, so that コード変更なしに目標と制約を調整できる

#### Acceptance Criteria
1. When 研究者がポリシーファイルを指定したとき, the EqOrch system shall Markdown、YAML、TOML の外部テキスト形式を読み込める
2. The EqOrch system shall ポリシー内に目標、制約、禁止操作、探索戦略、モード遷移基準、トリガー条件を記述できる
3. When ポリシーファイルが手動または `update_policy` Action により更新されたとき, the EqOrch system shall 次のオーケストレーションサイクルから更新内容を有効化する
4. The EqOrch system shall ポリシーをワークフロー状態の解釈と Action 決定の入力として扱う
5. Where ポリシーの差分追跡が有効な構成では, the EqOrch system shall ポリシー改訂履歴を保持できる
6. The EqOrch system shall ポリシーのトリガー条件として少なくとも `stagnation_threshold` と `diversity_threshold` を扱える

### Requirement 2: LLM リサーチコンシェルジュ
**Objective:** As a 研究者, I want LLM コンシェルジュが現在状態を解釈して次の制御を決めてほしい, so that 探索を状態駆動で進行できる

#### Acceptance Criteria
1. When コンシェルジュが判断を行うとき, the EqOrch system shall 現在の State、ポリシー、メモリ、候補、評価を入力として Action を決定する
2. The EqOrch system shall `call_skill`、`call_tool`、`run_engine`、`ask_user`、`update_policy`、`switch_mode`、`terminate` の各 Action を発行できる
3. When 探索状態に停滞、冗長性、探索の偏りが生じたとき, the EqOrch system shall ポリシー条件を参照して適切な Action を選択できる
4. When 対話モードとバッチモードの切り替えが必要になったとき, the EqOrch system shall コンシェルジュ判断に基づきモード遷移を決定できる
5. Where 批評や評価の補助モジュールが導入されている場合, the EqOrch system shall 複数エージェントの補助判断を呼び出せる

### Requirement 3: コアデータモデル
**Objective:** As a 開発者, I want State、Candidate、Evaluation、Action、TraceLog の必須構造を固定したい, so that 各モジュールが同じ前提で接続できる

#### Acceptance Criteria
1. The EqOrch system shall State に `policy_context`、`workflow_memory`、`candidates`、`evaluations`、`current_mode` を含める
2. The EqOrch system shall Candidate に `id`、`equation`、`score`、`reasoning`、`origin`、`created_at` を含める
3. The EqOrch system shall Evaluation に `candidate_id`、評価メトリクス、`timestamp` を含める
4. The EqOrch system shall Action に `type`、`target`、`parameters` を含める
5. The EqOrch system shall LogEntry に `step`、`action`、`input_summary`、`output_summary`、`timestamp` を含める

### Requirement 4: スキル管理
**Objective:** As a 開発者, I want ドメイン固有推論を再利用可能なスキルとして追加したい, so that オーケストレーションコアを変えずに能力を拡張できる

#### Acceptance Criteria
1. The EqOrch system shall スキルをドメイン固有推論手順をカプセル化した独立ユニットとして扱う
2. When コンシェルジュが State を評価したとき, the EqOrch system shall 動的に適切なスキルを選択して `call_skill` Action で呼び出せる
3. The EqOrch system shall 新しいスキルをオーケストレーションコア変更なしに追加登録できる
4. When スキルが実行されたとき, the EqOrch system shall 実行結果を State 更新とログ記録の対象に含める
5. The EqOrch system shall スキル選択をワークフロー制御の一部として扱う
6. The EqOrch system shall スキルに対して `State -> Result` の統一シグネチャを適用する

### Requirement 5: ツール統合
**Objective:** As a 開発者, I want 外部ツールを統一的に接続したい, so that 検索や数値処理を制御ループから利用できる

#### Acceptance Criteria
1. The EqOrch system shall ツールに対して呼び出しと結果受け取りの統一インターフェースを提供する
2. The EqOrch system shall 検索システム、データベース、ファイル操作、数値ソルバーをツールとして接続できる
3. The EqOrch system shall 新しいツールをポリシーファイル変更なしに追加登録できる
4. When コンシェルジュが `call_tool` Action を発行したとき, the EqOrch system shall 対応するツールへ委任して結果を回収できる
5. The EqOrch system shall ツール結果を後続の State 解釈と評価に利用できる
6. The EqOrch system shall ツールに対して `Request -> Result` の統一シグネチャを適用する

### Requirement 6: 探索・実行エンジンインターフェース
**Objective:** As a 探索エンジン開発者, I want EqOrch から外部探索エンジンと実行バックエンドを呼び出したい, so that 候補生成と評価計算を既存資産で実行できる

#### Acceptance Criteria
1. The EqOrch system shall 探索エンジンを外部コンポーネントとして接続するインターフェースを提供する
2. When コンシェルジュが探索実行を指示したとき, the EqOrch system shall 探索方向、制約、パラメータのみを探索エンジンへ渡す
3. The EqOrch system shall 探索エンジンの内部処理に介入しない
4. The EqOrch system shall 実行バックエンド、シミュレーター、ソルバーへの実行委任インターフェースを提供する
5. Where 複数の探索パラダイムが接続されている場合, the EqOrch system shall 共通インターフェースで切り替えられる

### Requirement 7: 実行モード制御
**Objective:** As a 研究者, I want 対話探索とバッチ探索を同じ枠組みで切り替えたい, so that 状況に応じて介入度を変えられる

#### Acceptance Criteria
1. The EqOrch system shall 対話モードとバッチモードで共通のオーケストレーションロジックを使用する
2. When モードが切り替わったとき, the EqOrch system shall ポリシーコンテキストとワークフロー状態を引き継ぐ
3. When ポリシーのモード遷移基準を満たしたとき, the EqOrch system shall `switch_mode` Action を発行できる
4. When 研究者が明示的にモード変更を指示したとき, the EqOrch system shall その指示による切り替えをサポートする
5. The EqOrch system shall 対話モードとバッチモードの両方で同じ Trace とメモリ管理を維持する

### Requirement 8: ワークフローメモリ
**Objective:** As a 研究者, I want 探索の状態と履歴を永続化したい, so that セッションをまたいで再現可能に探索を継続できる

#### Acceptance Criteria
1. The EqOrch system shall ワークフローメモリをオンメモリ層と永続ストレージ層の 2 層で管理する
2. While オーケストレーションサイクルが進行中である間, the EqOrch system shall 現在サイクルの State をオンメモリ層で低レイテンシに参照できる
3. When オンメモリ層のサイズ上限を超えたとき, the EqOrch system shall 古いエントリを永続層へ退避できる
4. When 各オーケストレーションサイクルが終了したとき, the EqOrch system shall 実行結果、State 差分、ポリシー改訂、モード遷移履歴を永続層へ書き出す
5. The EqOrch system shall 永続層からオンメモリ層へのロードと、過去状態からの再起動をサポートする

### Requirement 9: 説明可能性
**Objective:** As a 研究者, I want 候補と制御判断の根拠を確認したい, so that 探索の妥当性を検証できる

#### Acceptance Criteria
1. The EqOrch system shall すべての Candidate に reasoning フィールドを持たせる
2. When Candidate が生成されたとき, the EqOrch system shall その推論根拠をワークフローメモリ永続層へ保存する
3. When コンシェルジュが Action を選択したとき, the EqOrch system shall その判断根拠を TraceLog に記録できる
4. The EqOrch system shall 候補の出自を LLM、Engine、Hybrid の別で追跡できる
5. The EqOrch system shall 説明情報を後続の比較、レビュー、再実行で参照できる

### Requirement 10: トレーサビリティ
**Objective:** As a 開発者, I want すべての制御判断を追跡したい, so that 任意ステップの状態を再現してデバッグできる

#### Acceptance Criteria
1. The EqOrch system shall 発行されたすべての Action を TraceLog として記録する
2. When TraceLog を参照したとき, the EqOrch system shall 任意ステップの State を再現できる
3. The EqOrch system shall TraceLog を永続層に保存し、セッションをまたいで参照できる
4. When 実行結果が State を更新したとき, the EqOrch system shall その入力要約と出力要約をログへ残す
5. The EqOrch system shall 再現性とデバッグ容易性の基盤として TraceLog を扱う

### Requirement 11: Action 実行とエンドツーエンドワークフロー
**Objective:** As a 研究者, I want EqOrch が一貫した制御ループで探索を進めてほしい, so that 候補生成から終了判断まで同じモデルで運用できる

#### Acceptance Criteria
1. The EqOrch system shall Action を構造化されたデータモデルとして発行し、対応するモジュールへ委任する
2. When Action が実行されたとき, the EqOrch system shall 実行結果を State に反映し、LogEntry として記録する
3. The EqOrch system shall `terminate` Action によりオーケストレーションループを正常終了できる
4. When ワークフローが開始されたとき, the EqOrch system shall ポリシーコンテキストと過去のワークフローメモリを読み込んで State を初期化する
5. The EqOrch system shall 「State 解釈 → Action 決定 → 実行委任 → State 更新 → 継続判断」のサイクルを繰り返せる

### Requirement 12: インターフェース要求
**Objective:** As a 開発者, I want 各外部境界の入出力契約を明確にしたい, so that 実装時にコンポーネント間の接続仕様がぶれない

#### Acceptance Criteria
1. The EqOrch system shall 対話モードとして CLI またはチャット形式のインターフェースを提供できる
2. The EqOrch system shall バッチモードとしてポリシーと初期 State を指定する非対話起動をサポートする
3. The EqOrch system shall スキルに `State -> Result`、ツールに `Request -> Result` の統一シグネチャを定義する
4. The EqOrch system shall 探索エンジンに `Instruction -> list[Candidate] + list[Evaluation]`、実行バックエンドに `(実行コマンド・設定) -> (数値結果・ステータス)` の統一シグネチャを定義する
5. The EqOrch system shall LLM API 呼び出しに OpenAI 互換または Anthropic API 形式を利用できる

### Requirement 13: 非機能要求と設計制約
**Objective:** As a プロジェクト保守者, I want 拡張性、再現性、互換性の制約を明確にしたい, so that 実装判断が SRS の設計方針から逸脱しない

#### Acceptance Criteria
1. The EqOrch system shall 新しいスキル、ツール、探索エンジンをオーケストレーションコア変更なしに追加できる
2. The EqOrch system shall HPC、シミュレーター等の既存科学ソフトウェアスタックと標準インターフェースで接続できる
3. The EqOrch system shall すべての実行サイクルの入力、出力、制御決定を記録し、後から再現、検査できる
4. If 特定の LLM プロバイダ依存の実装を導入する場合, then the EqOrch system shall API 抽象化層を介して依存性を隔離する
5. The EqOrch system shall 探索エンジンとシミュレーションバックエンドを内包せず、外部コンポーネントとして接続する
6. The EqOrch system shall LLM に大規模候補評価や数値シミュレーションを直接実行させない
7. The EqOrch system shall コンシェルジュ、スキル、ツール、エンジンを独立に交換可能なモジュールとして扱う
8. The EqOrch system shall 大規模バッチ探索においてもオーケストレーション層がボトルネックにならないことを前提に設計する
