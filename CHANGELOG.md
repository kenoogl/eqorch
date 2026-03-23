# Changelog

## 0.2.0 - 2026-03-23

### Added

- EqOrch のコアドメインモデル、ポリシー管理、モード評価、レジストリ / ゲートウェイ境界を実装
- OpenAI、Anthropic、Google Gemini を含む `LLMGateway` と `ResearchConcierge` を実装
- PostgreSQL 正本の `WorkflowStore`、`TraceStore`、`ReplayLoader`、`PersistentMemoryStore` facade を実装
- optional な補助層として `KnowledgeIndex` と `ArtifactStore` を実装
- `OrchestrationLoop`、非同期 job 管理、retry fallback、CLI の `interactive` / `batch` / `resume` を実装
- unit / integration / e2e / performance / PostgreSQL 実 DB 検証のテスト導線を追加
- README、運用ドキュメント、開発ドキュメント、PostgreSQL readiness ADR を追加

### Changed

- 外部記憶アーキテクチャを PostgreSQL 正本 + optional 補助層構成へ整理
- テスト実行導線を `Makefile` に標準化

