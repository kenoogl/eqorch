# EqOrch

EqOrch は `cc-sdd` スタイルの仕様駆動開発で進める。

## 開発フロー

作業は次の順で進める。

1. まず仕様で課題と成功条件を定義する。
2. 仕様を設計と実装タスクへ分解する。
3. 仕様レビュー後にのみ実装へ進む。
4. 実装後は仕様に対する検証結果を残す。

## リポジトリ運用

- `dev_doc/`: ローカル専用の検討メモ置き場。Git では追跡しない。
- `.kiro/steering/`: プロジェクト全体に適用する恒久的な方針文書。
- `.kiro/specs/`: Kiro ワークフローで管理する追跡対象の仕様。

## 仕様作成ルール

1. プロジェクト横断のルールは `.kiro/steering/` に置く。
2. 機能ごとの仕様は `.kiro/specs/` に置く。
3. 要求、設計、タスクをレビューしてから実装する。
4. 実装後は承認済み仕様に対して検証を行う。

## ドキュメント言語

追跡対象の Markdown 文書は原則として日本語で作成する。

## 運用ショートカット

`git-cp` は、このリポジトリにおいて「必要な変更をコミットしてプッシュする」依頼として扱う。

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
