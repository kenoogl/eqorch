# ディレクトリ構成メモ

## 目的

EqOrch の実装開始前に、リポジトリ内で何を本体として管理し、何を外部コンポーネントとして扱うかを固定する。

この文書は、実装コードの配置判断と初期ディレクトリ作成の基準として使う。

## 基本方針

- `src/eqorch/` には EqOrch 本体のみを置く
- `skills`、`tools`、`engines` は EqOrch の責務そのものではなく、接続対象として扱う
- 同梱実装が必要な場合でも、本体コードと混在させず分離する
- 外部コンポーネントの接続情報は設定ファイルで管理する

## 推奨ディレクトリ構成

```text
/
├─ README.md
├─ AGENTS.md
├─ .kiro/
│  ├─ steering/
│  └─ specs/
├─ configs/
│  ├─ policy/
│  └─ components/
├─ src/
│  └─ eqorch/
│     ├─ app/
│     ├─ domain/
│     ├─ orchestrator/
│     ├─ gateways/
│     ├─ registry/
│     ├─ memory/
│     ├─ tracing/
│     ├─ validation/
│     ├─ runtime/
│     └─ interfaces/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ e2e/
│  └─ performance/
├─ scripts/
└─ examples/
```

## 各ディレクトリの役割

### `src/eqorch/`

EqOrch 本体を置く。外部サービスや探索器の実体ではなく、オーケストレーション、状態管理、境界抽象、検証、トレースを実装する。

### `configs/policy/`

ポリシーファイルを置く。探索方針、モード遷移、再試行、メモリ上限などの設定を管理する。

### `configs/components/`

`components.yaml` など、スキル、ツール、エンジン、外部接続先の登録設定を置く。

### `tests/`

要件に対応する検証を置く。`unit`、`integration`、`e2e`、`performance` に分ける。

## `skills` / `tools` / `engines` の扱い

### 原則

- `skills/`、`tools/`、`engines/` を `src/eqorch/` 直下には置かない
- EqOrch はそれらを実装する主体ではなく、登録・呼び出し・監督する主体である
- 実体は外部 package、外部 service、または別リポジトリとして扱える構造を優先する

### 同梱実装が必要な場合

同梱サンプルや標準実装をこのリポジトリに持つ場合は、以下のように本体と分離する。

```text
/
├─ src/eqorch/
└─ plugins/
   ├─ skills/
   ├─ tools/
   └─ engines/
```

この場合でも、EqOrch 本体は `plugins/` の内部実装に依存せず、`configs/components/` の登録情報を通じて扱う。

### 初期方針

初期段階では `plugins/` を作らず、外部コンポーネント接続を前提に `configs/components/components.yaml` で管理する。

## 配置上の禁止事項

- `domain` と `orchestrator` を混在させない
- `src/eqorch/` に個別の探索アルゴリズム実装を直接置かない
- ローカル検討用の断片コードを追跡対象ディレクトリへ混在させない
- `dev_doc/` の構成メモを正式な配置ルールとして扱わない

## 補足

将来、技術スタック確定後に言語やフレームワーク都合で細部は調整してよい。ただし、本体コードと外部コンポーネントの責務分離は維持する。
