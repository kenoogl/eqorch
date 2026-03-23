# ADR 001: PostgreSQL 正本運用 readiness

## 状態

承認済み

## 背景

EqOrch は PostgreSQL を正本永続層として用いる。現フェーズでは `WorkflowStore`、`TraceStore`、`ReplayLoader` と PostgreSQL 実 DB の継続検証導線を整備したため、本運用 readiness として次の判断を明示する。

- スキーマ初期化方法
- migration 導入有無
- 接続プール要否
- 障害時観測方法
- 終了コード方針

## 決定

### 1. スキーマ初期化

現フェーズでは `WorkflowStore` と `TraceStore` の初期化時に `CREATE TABLE IF NOT EXISTS` を実行する方式を標準とする。専用 bootstrap CLI は導入しない。

### 2. migration 方針

現フェーズでは migration フレームワークを導入しない。スキーマ変更が replay / restart 互換性に影響する場合は、次のいずれかを必須とする。

- 後方互換な変更として実装する
- 明示的な移行手順または移行スクリプトを提供する

互換性を壊す変更を無告知で投入しない。

### 3. 接続管理

現フェーズでは接続プールを導入しない。`ConnectionFactory` を通じた単一接続生成と、永続化 worker による順序制御を標準とする。

接続プールは次の条件で再検討する。

- PostgreSQL 書込遅延が性能目標を継続的に満たせない
- 複数同時セッションの本運用要件が明確化した
- 接続確立コストが主要なボトルネックになった

### 4. 障害時観測と通知

正本失敗として扱うのは次である。

- PostgreSQL への `WorkflowStore` 書込失敗
- PostgreSQL への `TraceStore` 書込失敗
- replay / restart の基点不整合

補助層失敗として扱うのは次である。

- `KnowledgeIndex` への publish 失敗
- `ArtifactStore` への publish 失敗

運用文書と実装では、正本失敗と補助層失敗を区別できるログまたは通知イベントを出す。

### 5. 終了コード方針

CLI の終了コードは次を標準とする。

- `0`: 正常終了、`terminate` による終了、最大サイクル到達
- `1`: 起動前検証失敗、正本永続化失敗、replay / restart 不整合、その他の運用失敗

## 影響

- `README.md` と `docs/operations.md` は本 ADR を参照して PostgreSQL 本運用 readiness を説明する
- migration フレームワークや接続プールを導入する場合は、新しい ADR を追加する
- `ArtifactStore` 実装時は本 ADR の補助層失敗方針に従う
