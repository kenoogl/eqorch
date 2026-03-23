# EqOrch

EqOrch は、科学ワークフローを制御するオーケストレーション基盤です。

## セットアップ

前提:

- Python 3.11 以上
- `psycopg[binary]` を含む Python 依存
- PostgreSQL 正本永続層
- `KnowledgeIndex` を有効にする場合は Vector DB 相当の補助インデックス実装

最小セットアップ:

```bash
python3 -m pip install -e .
```

実 PostgreSQL を使う場合は、`--database-url` または `TEST_DATABASE_URL` に PostgreSQL 接続文字列を渡す。

## CLI 起動

CLI エントリポイントは `eqorch`。

共通で必要な引数:

- `--policy`: ポリシーファイル
- `--components`: コンポーネント設定ファイル
- `--provider`: `openai` / `anthropic` / `google`
- `--llm-adapter`: `module:Class` 形式の adapter 実装
- `--database-url`: PostgreSQL 接続文字列
- `--max-cycles`: 実行サイクル上限

interactive 起動:

```bash
eqorch interactive \
  --policy configs/policy.yaml \
  --components configs/components/components.yaml \
  --provider openai \
  --llm-adapter your_package.adapters:OpenAIAdapter \
  --database-url postgresql://eqorch:eqorch@127.0.0.1:5432/eqorch \
  --max-cycles 5
```

batch 起動:

```bash
eqorch batch \
  --policy configs/policy.yaml \
  --components configs/components/components.yaml \
  --provider anthropic \
  --llm-adapter your_package.adapters:AnthropicAdapter \
  --database-url postgresql://eqorch:eqorch@127.0.0.1:5432/eqorch \
  --max-cycles 20
```

resume:

```bash
eqorch resume \
  --session-id <uuid> \
  --policy configs/policy.yaml \
  --components configs/components/components.yaml \
  --provider google \
  --llm-adapter your_package.adapters:GoogleAdapter \
  --database-url postgresql://eqorch:eqorch@127.0.0.1:5432/eqorch \
  --max-cycles 5
```

起動前検証では、ポリシー、`components.yaml`、LLM 接続が確認され、不成立時はループ開始前に終了する。

## テスト実行導線

カテゴリ別の標準実行コマンドは `Makefile` に揃える。

- `make test-unit`: 単体テスト
- `make test-integration`: sqlite 代替ストアを使う結合テスト
- `make test-e2e`: CLI 起動と再開の E2E テスト
- `make test-performance`: 性能計測ハーネスのテスト
- `make test-all`: unit / integration / e2e / performance を一括実行

### PostgreSQL 実 DB 検証

PostgreSQL 正本永続層の継続検証は Docker Compose で一時 DB を起動して行う。

1. `make postgres-up`
2. 必要なら `make postgres-ps` で health を確認する
3. `make test-postgres`
4. 終了後に `make postgres-down`

既定の接続先は `postgresql://eqorch:eqorch@127.0.0.1:55432/eqorch_test` で、別の接続先を使う場合は `TEST_DATABASE_URL` を上書きする。

## 現行マイルストーン範囲

- 現フェーズ対象: `KnowledgeIndex`
- 後続開発対象: `ArtifactStore`

`KnowledgeIndex` は PostgreSQL 正本から再構築可能な補助インデックスとして扱う。`ArtifactStore` は契約と failure semantics のみを維持し、Object Storage 連携本体は後続開発で導入する。

## 運用ドキュメント

運用上の failure semantics、正本失敗と補助層失敗の区別、PostgreSQL 正本運用時の注意事項は [docs/operations.md](/Users/Daily/Development/EqOrch/docs/operations.md) を参照する。

## 開発ドキュメント

仕様駆動開発フロー、リポジトリ運用、仕様文書の置き場所は [docs/development.md](/Users/Daily/Development/EqOrch/docs/development.md) を参照する。
