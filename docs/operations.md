# EqOrch 運用ドキュメント

この文書は、EqOrch の実行系をローカルまたは検証環境で運用する開発者 / 保守者向けの運用メモである。

対象は次に限定する。

- PostgreSQL を正本とする現行の実装範囲
- `KnowledgeIndex` を含む現フェーズの補助層
- 実行時の failure semantics と PostgreSQL 実 DB 検証導線

CLI の基本的な使い方やセットアップは [README.md](/Users/Daily/Development/EqOrch/README.md) を参照する。この文書では、運用判断に必要な正本 / 補助層の区別と、障害時の扱いを中心に説明する。

## 現フェーズの対象範囲

- optional 補助層: `KnowledgeIndex`
- optional 補助層: `ArtifactStore`

`KnowledgeIndex` は Vector DB を用いる optional な補助インデックスであり、PostgreSQL 正本から再構築可能であることを前提に運用する。`ArtifactStore` は Object Storage を用いる optional な補助ストアであり、大容量ログ、外部生成物、中間ファイルを参照 URI 付きで保持する。

## 現行実装における正本と補助層

- 正本: PostgreSQL 上の `WorkflowStore` と `TraceStore`
- 補助層: `KnowledgeIndex`、`ArtifactStore`

replay / restart の成立条件は正本に限定する。補助層の欠損や失敗だけでは再現性を失ったとみなさない。

## 障害時の扱い

### 正本失敗

次は正本失敗として扱う。

- PostgreSQL 正本書き込み失敗
- `WorkflowStore` / `TraceStore` 失敗
- replay 基点の不整合

正本失敗は通知対象であり、再試行上限超過時は停止を許容する。

### 補助層失敗

次は補助層失敗として扱う。

- `KnowledgeIndex` 反映失敗
- `ArtifactStore` 書き込み失敗

補助層失敗は記録と再試行の対象に留め、PostgreSQL 正本コミット成功時はループ継続を優先する。

## PostgreSQL 実 DB 検証導線

標準導線は `Makefile` に揃える。

1. `make postgres-up`
2. `make postgres-ps`
3. `make test-postgres`
4. `make postgres-down`

既定の `TEST_DATABASE_URL` は `postgresql://eqorch:eqorch@127.0.0.1:55432/eqorch_test`。

## 起動時に必要な実行情報

- ポリシーファイル
- `components.yaml`
- LLM provider
- `module:Class` 形式の LLM adapter
- PostgreSQL 接続文字列

## PostgreSQL 正本運用時の留意点

PostgreSQL 正本運用 readiness の判断は [ADR 001](/Users/Daily/Development/EqOrch/.kiro/steering/adrs/001-postgresql-readiness.md) を正本とする。

- スキーマ初期化は、現フェーズでは `WorkflowStore` / `TraceStore` 初期化時の `CREATE TABLE IF NOT EXISTS` を標準とする
- migration フレームワークは現フェーズでは導入せず、互換性を壊す変更では明示的な移行手段を必須とする
- 接続プールは現フェーズでは導入せず、単一 `ConnectionFactory` と永続化 worker の順序制御を標準とする
- 正本失敗は `WorkflowStore` / `TraceStore` 失敗と replay 基点不整合、補助層失敗は `KnowledgeIndex` と `ArtifactStore` 失敗とする
- CLI 終了コードは `0` を正常終了、`1` を起動前検証失敗・正本失敗・replay / restart 不整合などの運用失敗とする
