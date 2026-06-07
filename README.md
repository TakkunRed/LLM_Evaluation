# LLM Evaluator — セットアップ & 起動手順

## 1. uv のインストール（未インストールの場合）

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. 依存ライブラリのインストール

```
cd D:\ClaudeWork\llm_evaluation
uv sync
```

## 3. LM Studio の準備

1. LM Studio を起動
2. 評価したいモデル（Gemma、Qwen等）をロード
3. 左サイドバーの **Local Server** タブを開く
4. **Start Server** を押す（デフォルトポート: 1234）

## 4. アプリの起動

```
cd D:\ClaudeWork\llm_evaluation
uv run streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます。

## 使い方

1. サイドバーで LM Studio の URL（デフォルト: `http://localhost:1234/v1`）を確認
2. **更新** ボタンでモデル一覧を取得
3. モデルを選択し、任意で実行名を入力
4. **評価開始** ボタンを押す
5. 結果はレーダーチャートと表で表示。SQLiteに自動保存される
6. **比較** タブで複数モデルのスコアを並べて比較できる

## 評価項目

### 指示追従性 (Instruction Following)
| 指標 | 内容 |
|------|------|
| format_json | JSON形式で出力できるか |
| format_markdown_headers | Markdownヘッダーを使えるか |
| format_bullet_list | 箇条書き形式で出力できるか |
| length_constraint | 文字数制約を守れるか |
| forbidden_keywords | 禁止ワードを使わないか |
| persona_keywords | 与えたペルソナを維持できるか |

### 出力品質 (Output Quality)
| 指標 | 内容 |
|------|------|
| qa_exact | 事実・計算問題の正答率 |
| completeness | 指定要素をすべて含む完全性 |
| consistency | 同一質問に対する回答の一貫性 |
