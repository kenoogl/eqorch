# AI-DLC と仕様駆動開発

このリポジトリは、Kiro スタイルの仕様駆動開発を前提に運用する。

## プロジェクトメモリ

プロジェクトメモリは、毎回の実行で参照される長期的な判断基準である。設計原則、技術判断、構造ルール、運用ルールはここに残す。

- `.kiro/steering/` にはプロジェクト全体の方針を置く
- ローカルの `AGENTS.md` は、そのディレクトリ配下で有効な補足ルールを書く
- 個別仕様に関する文書は `.kiro/specs/` に置く

## パス

- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

## Steering と Specification の役割

- `Steering` は、プロジェクト横断で守る方針を定義する
- `Specs` は、個別機能の要求、設計、タスク、検証を定義する

## 開発ガイドライン

- 思考は英語でもよいが、ユーザー向け応答は日本語で行う
- 追跡対象の Markdown 文書は原則として日本語で作成する
- `dev_doc/` のようなローカルメモにのみ存在する内容を、正式仕様の前提にしない。ただし、明示的な指示がある場合は参考情報として扱ってよい
- 開発意図のようなプロジェクト横断の文書は `.kiro/steering/` に置く
- アーキテクチャに関する決定事項の履歴は `.kiro/steering/adrs/` に連番の Markdown ファイルで管理する

## 最小ワークフロー

- Phase 0: 必要なら `/prompts:kiro-steering` と `/prompts:kiro-steering-custom` を使う
- Phase 1: `/prompts:kiro-spec-init` → requirements → design → tasks の順に仕様化する
- Phase 2: 承認済み仕様に対して `/prompts:kiro-spec-impl` で実装する
- 進捗確認には `/prompts:kiro-spec-status {feature}` を使う

## 開発ルール

- 承認フローは Requirements → Design → Tasks → Implementation の順に進める
- 各段階で人間レビューを前提とし、`-y` は意図的な省略時のみ使う
- 仕様や方針が変わった場合は、先に `.kiro/steering/` または `.kiro/specs/` を更新する
- 追跡対象のドキュメントは日本語を既定とする
- ユーザーが `git-cp` と指示した場合は、このリポジトリでは「必要な変更をコミットしてプッシュする依頼」として扱う

## Steering 設定

- `.kiro/steering/` 全体をプロジェクトメモリとして扱う
- 既定の主要ファイルは `product.md`, `tech.md`, `structure.md`
- 必要なら `/prompts:kiro-steering-custom` でカスタム文書を追加する
