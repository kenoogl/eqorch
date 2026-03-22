# 要求仕様書

## はじめに

EqOrch は、方程式探索ワークフローを制御するオーケストレーションフレームワークである。`[dev_doc/EqOrch_SRS_v04_fixed.md](/Users/Daily/Development/EqOrch/dev_doc/EqOrch_SRS_v04_fixed.md)` を基礎仕様とし、`[dev_doc/EqOrch_SRS_v08.md](/Users/Daily/Development/EqOrch/dev_doc/EqOrch_SRS_v08.md)` で追加された詳細化内容を取り込んだ requirements フェーズ文書として再構成する。

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
7. The EqOrch system shall 探索戦略として少なくとも `expand`、`refine`、`restart` を扱える
8. The EqOrch system shall ポリシーに `retry.max_retries`、`retry.retry_interval_sec`、`retry.excluded_types` を含むリトライ設定を保持できる
9. The EqOrch system shall ポリシーに `max_candidates`、`max_evaluations`、`max_memory_entries`、`max_parallel_actions`、`llm_context_steps` を保持できる
10. The EqOrch system shall ポリシーのモード遷移基準を `rules` と `notes` に分けて保持できる
11. If ポリシーファイルが必須項目を欠くか不正な値を含む場合, then the EqOrch system shall ロードを拒否し、旧ポリシーを維持したままエラーを返す
12. When LLM API 呼び出し時にコンテキスト長制約へ近づいたとき, the EqOrch system shall ポリシーの `llm_context_steps` で指定された直近ステップ数までの状態要約に入力を縮約する
13. The EqOrch system shall `mode_switch_criteria.rules` の各要素を `condition`、`target_mode`、`reason` で表現し、条件式を EqOrch 本体の式評価機構で機械的に評価できるようにする
14. The EqOrch system shall 既定値として `max_candidates=100`、`max_evaluations=500`、`max_memory_entries=1000`、`llm_context_steps=20`、`retry.max_retries=3`、`retry.retry_interval_sec=5` を用いる
15. The EqOrch system shall `retry.excluded_types` の既定値として `ask_user`、`switch_mode`、`terminate` を用いる
16. The EqOrch system shall ポリシーの `goals` に少なくとも 1 件の探索目標を要求し、空配列を不正として扱う

### Requirement 2: LLM リサーチコンシェルジュ
**Objective:** As a 研究者, I want LLM コンシェルジュが現在状態を解釈して次の制御を決めてほしい, so that 探索を状態駆動で進行できる

#### Acceptance Criteria
1. When コンシェルジュが判断を行うとき, the EqOrch system shall 現在の State、ポリシー、メモリ、候補、評価を入力として Action を決定する
2. The EqOrch system shall `call_skill`、`call_tool`、`run_engine`、`ask_user`、`update_policy`、`switch_mode`、`terminate` の各 Action を発行できる
3. When 探索状態に停滞、冗長性、探索の偏りが生じたとき, the EqOrch system shall ポリシー条件を参照して適切な Action を選択できる
4. When 対話モードとバッチモードの切り替えが必要になったとき, the EqOrch system shall コンシェルジュ判断に基づきモード遷移を決定できる
5. Where 批評や評価の補助モジュールが導入されている場合, the EqOrch system shall 複数エージェントの補助判断を呼び出せる
6. When LLM API が応答しないかエラーを返したとき, the EqOrch system shall 実行結果をエラーとして記録し、オーケストレーションループ自体は継続できる

### Requirement 3: コアデータモデル
**Objective:** As a 開発者, I want State、Candidate、Evaluation、Action、TraceLog の必須構造を固定したい, so that 各モジュールが同じ前提で接続できる

#### Acceptance Criteria
1. The EqOrch system shall State に `policy_context`、`workflow_memory`、`candidates`、`evaluations`、`interactive` か `batch` を値に取る `current_mode`、`session_id`、`step`、`pending_jobs`、`last_errors` を含める
2. The EqOrch system shall State の `candidates` を `Policy.max_candidates` 件、`evaluations` を `Policy.max_evaluations` 件までオンメモリ保持し、超過分を永続層へ退避する
3. The EqOrch system shall Candidate に `id`、`equation`、`score`、`reasoning`、`LLM`、`Engine`、`Hybrid` のいずれかを値に取る `origin`、`created_at`、`step` を含める
4. The EqOrch system shall Candidate の `score` を生成元に応じて解釈し、`Engine` 生成時はエンジン算出値、`LLM` 生成時は後続評価前の暫定値、`Hybrid` 生成時は LLM 提案後にエンジンが付与した値として扱う
5. The EqOrch system shall Evaluation に `id`、`candidate_id`、`mse` と `complexity` を含む `metrics` 構造、任意の拡張メトリクスを保持する `metrics.extra`、`evaluator`、`timestamp` を含める
6. If Evaluation の `candidate_id` が既存 Candidate を参照しない場合, then the EqOrch system shall 記録エラーとして扱い不整合な評価を受理しない
7. The EqOrch system shall Action に `type`、`target`、`parameters`、`issued_at`、`action_id` を含める
8. The EqOrch system shall LogEntry に `step`、`session_id`、`action_id`、`action`、`result`、`state_diff`、`duration_ms`、`timestamp` を含める
9. The EqOrch system shall Result に `success`、`error`、`timeout`、`partial` を値に取る `status`、`payload`、`error` を含める
10. The EqOrch system shall ErrorInfo に `code`、`message`、`retryable` を含める
11. The EqOrch system shall オンメモリ Memory に `entries`、`max_entries`、`eviction_policy` を含める
12. The EqOrch system shall PendingJob に `job_id`、`engine_name`、`action_id`、`issued_at`、`timeout_at` を含める
13. The EqOrch system shall Memory の各 entry に `key`、`value`、`created_at`、`last_accessed` を含める
14. The EqOrch system shall LogEntry の `state_diff` を RFC 6902 JSON Patch 形式で保持し、各差分要素の `path` を RFC 6901 JSON Pointer として表現する
15. The EqOrch system shall `session_id`、`Candidate.id`、`Evaluation.id`、`action_id` に UUIDv4 を用いる
16. The EqOrch system shall `created_at`、`timestamp`、`issued_at`、`timeout_at`、`last_accessed` を ISO 8601 UTC 形式で表現する

### Requirement 4: スキル管理
**Objective:** As a 開発者, I want ドメイン固有推論を再利用可能なスキルとして追加したい, so that オーケストレーションコアを変えずに能力を拡張できる

#### Acceptance Criteria
1. The EqOrch system shall スキルをドメイン固有推論手順をカプセル化した独立ユニットとして扱う
2. When コンシェルジュが State を評価したとき, the EqOrch system shall 動的に適切なスキルを選択して `call_skill` Action で呼び出せる
3. The EqOrch system shall 新しいスキルをオーケストレーションコア変更なしに追加登録できる
4. When スキルが実行されたとき, the EqOrch system shall 実行結果を State 更新とログ記録の対象に含める
5. The EqOrch system shall スキル選択をワークフロー制御の一部として扱う
6. The EqOrch system shall スキルに対して `State -> Result` の統一シグネチャを適用する
7. If スキルがタイムアウトした場合, then the EqOrch system shall `timeout` ステータスを返す
8. If 未登録のスキルが指定された場合, then the EqOrch system shall `SKILL_NOT_FOUND` コードのエラーを返す

### Requirement 5: ツール統合
**Objective:** As a 開発者, I want 外部ツールを統一的に接続したい, so that 検索や数値処理を制御ループから利用できる

#### Acceptance Criteria
1. The EqOrch system shall ツールに対して呼び出しと結果受け取りの統一インターフェースを提供する
2. The EqOrch system shall 検索システム、データベース、ファイル操作、数値ソルバーをツールとして接続できる
3. The EqOrch system shall 新しいツールをポリシーファイル変更なしに追加登録できる
4. When コンシェルジュが `call_tool` Action を発行したとき, the EqOrch system shall 対応するツールへ委任して結果を回収できる
5. The EqOrch system shall ツール結果を後続の State 解釈と評価に利用できる
6. The EqOrch system shall ツールに対して `Request -> Result` の統一シグネチャを適用する
7. If ツールがタイムアウトした場合, then the EqOrch system shall `timeout` ステータスを返す
8. If 未登録のツールが指定された場合, then the EqOrch system shall `TOOL_NOT_FOUND` コードのエラーを返す

### Requirement 6: 探索・実行エンジンインターフェース
**Objective:** As a 探索エンジン開発者, I want EqOrch から外部探索エンジンと実行バックエンドを呼び出したい, so that 候補生成と評価計算を既存資産で実行できる

#### Acceptance Criteria
1. The EqOrch system shall 探索エンジンを外部コンポーネントとして接続するインターフェースを提供する
2. When コンシェルジュが探索実行を指示したとき, the EqOrch system shall 探索方向、制約、パラメータのみを探索エンジンへ渡す
3. The EqOrch system shall 探索エンジンの内部処理に介入しない
4. The EqOrch system shall 実行バックエンド、シミュレーター、ソルバーへの実行委任インターフェースを提供する
5. Where 複数の探索パラダイムが接続されている場合, the EqOrch system shall 共通インターフェースで切り替えられる
6. If エンジンが未登録の場合, then the EqOrch system shall `ENGINE_NOT_FOUND` コードのエラーを返す
7. If エンジンがタイムアウト秒数以内に応答しない場合, then the EqOrch system shall `timeout` ステータスを返す
8. Where `run_engine` が非同期モードで実行される場合, the EqOrch system shall `job_id` を状態の完了待ちジョブ欄へ記録して次サイクルへ進める

### Requirement 7: 実行モード制御
**Objective:** As a 研究者, I want 対話探索とバッチ探索を同じ枠組みで切り替えたい, so that 状況に応じて介入度を変えられる

#### Acceptance Criteria
1. The EqOrch system shall 対話モードとバッチモードで共通のオーケストレーションロジックを使用する
2. When モードが切り替わったとき, the EqOrch system shall ポリシーコンテキストとワークフロー状態を引き継ぐ
3. When ポリシーのモード遷移基準を満たしたとき, the EqOrch system shall `switch_mode` Action を発行できる
4. When 研究者が明示的にモード変更を指示したとき, the EqOrch system shall その指示による切り替えをサポートする
5. The EqOrch system shall 対話モードとバッチモードの両方で同じ Trace とメモリ管理を維持する
6. The EqOrch system shall モード遷移ルールの機械的評価と自然言語補足を分離して扱う

### Requirement 8: ワークフローメモリ
**Objective:** As a 研究者, I want 探索の状態と履歴を永続化したい, so that セッションをまたいで再現可能に探索を継続できる

#### Acceptance Criteria
1. The EqOrch system shall ワークフローメモリをオンメモリ層と永続ストレージ層の 2 層で管理する
2. While オーケストレーションサイクルが進行中である間, the EqOrch system shall 現在サイクルの State をオンメモリ層で低レイテンシに参照できる
3. When オンメモリ層のサイズ上限を超えたとき, the EqOrch system shall 古いエントリを永続層へ退避できる
4. When 各オーケストレーションサイクルが終了したとき, the EqOrch system shall 実行結果、中間サマリー、State 差分、ポリシー改訂、モード遷移履歴を永続層へ書き出す
5. The EqOrch system shall 永続層からオンメモリ層へのロードと、過去状態からの再起動をサポートする
6. The EqOrch system shall オンメモリ層から永続層への書き込みを非同期で実行し、オーケストレーションループを不必要にブロックしない
7. The EqOrch system shall オンメモリ層の退避方針として少なくとも `lru` と `fifo` を扱える
8. The EqOrch system shall 各オーケストレーションサイクル開始時に State の `last_errors` をクリアする
9. The EqOrch system shall オンメモリ層の既定退避方針として `lru` を用いる

### Requirement 9: 説明可能性
**Objective:** As a 研究者, I want 候補と制御判断の根拠を確認したい, so that 探索の妥当性を検証できる

#### Acceptance Criteria
1. The EqOrch system shall すべての Candidate に reasoning フィールドを持たせる
2. The EqOrch system shall Candidate の `reasoning` に空文字列または null を許容しない
3. When Candidate が生成されたとき, the EqOrch system shall その推論根拠をワークフローメモリ永続層へ保存する
4. When コンシェルジュが Action を選択したとき, the EqOrch system shall その判断根拠を TraceLog に記録できる
5. The EqOrch system shall 候補の出自を LLM、Engine、Hybrid の別で追跡できる
6. The EqOrch system shall 説明情報を後続の比較、レビュー、再実行で参照できる

### Requirement 10: トレーサビリティ
**Objective:** As a 開発者, I want すべての制御判断を追跡したい, so that 任意ステップの状態を再現してデバッグできる

#### Acceptance Criteria
1. The EqOrch system shall 発行されたすべての Action を TraceLog として記録する
2. When TraceLog を参照したとき, the EqOrch system shall 任意ステップの State を再現できる
3. The EqOrch system shall TraceLog を永続層に保存し、セッションをまたいで参照できる
4. When 実行結果が State を更新したとき, the EqOrch system shall その入力要約と出力要約をログへ残す
5. The EqOrch system shall 再現性とデバッグ容易性の基盤として TraceLog を扱う
6. The EqOrch system shall 並行実行時でも `action_id` により命令と実行記録を一意に突合できる
7. The EqOrch system shall 再現対象を決定的な状態データと構造化ログに限定し、LLM 生成テキストそのものを一致判定の必須対象にしない

### Requirement 11: Action 実行とエンドツーエンドワークフロー
**Objective:** As a 研究者, I want EqOrch が一貫した制御ループで探索を進めてほしい, so that 候補生成から終了判断まで同じモデルで運用できる

#### Acceptance Criteria
1. The EqOrch system shall Action を構造化されたデータモデルとして単独または命令リストで発行し、対応するモジュールへ委任する
2. The EqOrch system shall 各サイクルで 1 件以上の Action を決定し、命令リストとして扱える
3. When 1 サイクルに複数命令が発行されたとき, the EqOrch system shall ポリシーで許可された最大並行数の範囲で独立に並行実行できる
4. The EqOrch system shall `ask_user` と `terminate` を並行発行リストへ含めた場合にバリデーションエラーとする
5. When Action が実行されたとき, the EqOrch system shall 成功した命令の結果のみを状態へ差分適用し、失敗分は適用しない
6. The EqOrch system shall `terminate` Action によりオーケストレーションループを正常終了できる
7. When ワークフローが開始されたとき, the EqOrch system shall ポリシーコンテキストと過去のワークフローメモリを読み込んで State を初期化する
8. The EqOrch system shall 「State 解釈 → Action 決定 → 実行委任 → State 更新 → 継続判断」のサイクルを繰り返せる
9. The EqOrch system shall `Action.parameters` に対して命令種別ごとの必須スキーマを適用し、少なくとも `call_skill.input`、`call_tool.query`、`run_engine.instruction`、`ask_user.prompt`、`update_policy.patch`、`switch_mode.target_mode` を必須とする
10. If Action が未定義フィールドまたは種別不整合な `parameters` を含む場合, then the EqOrch system shall 実行前にバリデーションエラーとして拒否する
11. The EqOrch system shall `Action.parameters` の任意フィールドとして `call_skill.timeout_sec=60`、`call_tool.timeout_sec=30`、`run_engine.timeout_sec=3600`、`run_engine.async=false`、`ask_user.options`、`switch_mode.reason`、`terminate.reason` を扱える

### Requirement 12: インターフェース要求
**Objective:** As a 開発者, I want 各外部境界の入出力契約を明確にしたい, so that 実装時にコンポーネント間の接続仕様がぶれない

#### Acceptance Criteria
1. The EqOrch system shall 対話モードとして CLI またはチャット形式のインターフェースを提供できる
2. The EqOrch system shall バッチモードとしてポリシーと初期 State を指定する非対話起動をサポートする
3. The EqOrch system shall スキルに `State -> Result`、ツールに `Request -> Result` の統一シグネチャを定義する
4. The EqOrch system shall 探索エンジンに `Instruction -> list[Candidate] + list[Evaluation]`、実行バックエンドに `(実行コマンド・設定) -> (数値結果・ステータス)` の統一シグネチャを定義する
5. The EqOrch system shall LLM API 呼び出しに OpenAI 互換または Anthropic API 形式を利用できる
6. The EqOrch system shall ポリシーファイルに Markdown、YAML、TOML を使用できる
7. The EqOrch system shall オンメモリ層のワークフローメモリをプロセス内辞書または同等の言語標準データ構造で扱える
8. The EqOrch system shall 永続層のワークフローメモリに JSON Lines、SQLite、または同等のファイルベース DB を使用できる
9. The EqOrch system shall TraceLog を JSON Lines 形式で永続層へ保存できる
10. The EqOrch system shall スキル、ツール、エンジンの登録設定を YAML 形式のコンポーネント設定ファイルで管理できる
11. The EqOrch system shall エンジン通信方式として少なくとも REST と gRPC を扱える
12. The EqOrch system shall 非同期エンジン実行について `run-async` と `poll` 相当の契約を表現できる
13. The EqOrch system shall コンポーネント設定ファイルに少なくとも `name`、`module`、`class` または `endpoint`、`protocol` を定義できる
14. Where `protocol` が `grpc` の場合, the EqOrch system shall コンポーネント設定ファイルに `proto`、`service`、`Run` / `RunAsync` / `PollJob` に対応する RPC 情報を定義できる
15. Where `protocol` が `rest` の場合, the EqOrch system shall 同期実行に `POST {endpoint}/run`、非同期実行に `POST {endpoint}/run-async`、状態確認に `GET {endpoint}/job/{job_id}` 相当の契約を扱える
16. The EqOrch system shall ワークフローメモリ永続層の既定実装として SQLite を用いる

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
9. Where ポリシー外部化が有効な構成では, the EqOrch system shall ポリシーファイル変更のみで振る舞いを変更できる
10. The EqOrch system shall オンメモリ状態参照で p99 10ms 以下を目標とする
11. The EqOrch system shall 永続化によるループブロック時間を 1ms 以下に抑えることを目標とする
12. The EqOrch system shall 1 サイクルあたりの最大並行命令数を設定可能とし、既定値を 8 とする
13. The EqOrch system shall LLM の命令決定時間を除くオーケストレーション制御オーバーヘッドを p99 50ms/サイクル以下に抑えることを目標とする
14. The EqOrch system shall 1 バッチあたり 1000 候補以上を処理しても、方程式文字列長 256 文字以下かつ評価メトリクス数 3 以下の条件でオーケストレーション層の CPU 使用率が単独コアの 80% を超えないことを目標とする
15. The EqOrch system shall クラッシュ後の再起動時に永続層の最終コミット済み状態を保全する

### Requirement 14: 前提条件
**Objective:** As a プロジェクト保守者, I want システム成立に必要な前提条件を明確にしたい, so that 設計と運用の責任境界を曖昧にしない

#### Acceptance Criteria
1. The EqOrch system shall LLM API へのアクセスが確保されていることを前提条件として扱う
2. The EqOrch system shall 外部探索エンジンおよび実行バックエンドがインターフェース仕様に従って接続されることを前提条件として扱う
3. The EqOrch system shall ポリシーファイルが有効な形式で提供されることを前提条件として扱う

### Requirement 15: エラー処理とリトライ
**Objective:** As a プロジェクト保守者, I want コンポーネント障害時の振る舞いを固定したい, so that ループ継続条件と停止条件が曖昧にならない

#### Acceptance Criteria
1. The EqOrch system shall 単一コンポーネントのエラーでオーケストレーションループ全体を停止させない
2. The EqOrch system shall すべてのエラーを `ErrorInfo` モデルに従って記録する
3. When LLM API がタイムアウトまたは HTTP 5xx を返したとき, the EqOrch system shall ポリシーのリトライ設定に従って再試行する
4. If リトライ上限を超過した場合, then the EqOrch system shall 失敗した命令のエラー情報を状態のエラー記録欄へ保持し、次サイクルのコンシェルジュ入力に含める
5. If 永続層への書き込みが失敗した場合, then the EqOrch system shall 次サイクルで再試行する
6. If 永続層への書き込みがリトライ上限を超えて失敗した場合, then the EqOrch system shall ユーザへ通知してプロセス停止を許容する
7. If 部分的な状態変更が適用途中で失敗した場合, then the EqOrch system shall ロールバックして直前の整合状態を維持する
8. If LLM API のリトライが上限を超過した場合, then the EqOrch system shall 対話モードでは `ask_user` 相当の問い合わせへ遷移し、バッチモードでは終了処理へ遷移する

### Requirement 16: 実行結果と非同期ジョブ管理
**Objective:** As a 研究者, I want 実行結果と非同期エンジンジョブを同じモデルで扱いたい, so that 失敗、部分成功、完了待ちを一貫して追跡できる

#### Acceptance Criteria
1. The EqOrch system shall 実行結果に `success`、`error`、`timeout`、`partial` を含む統一ステータスを用いる
2. When 実行結果が `partial` の場合, the EqOrch system shall 取得済みデータを `payload` に残し、部分失敗理由を `error` に記録する
3. When エンジンが非同期実行を受け付けたとき, the EqOrch system shall 返却された `job_id` を `PendingJob` として状態へ保持する
4. The EqOrch system shall 後続サイクルで完了待ちジョブを参照し、ポーリングまたは結果回収 Action を発行できる
5. When 終了命令発行時に完了待ちジョブが残っている場合, the EqOrch system shall キャンセル要求送信の成否を実行記録へ残した上で最終コミットできる
