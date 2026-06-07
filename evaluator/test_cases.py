"""
評価テストケース定義
各テストケースは辞書形式で定義する。

schema:
  id: str              ユニークID
  category: str        "instruction_following" | "output_quality"
  metric: str          評価指標名
  description: str     テスト内容の説明
  system_prompt: str   システムプロンプト
  user_prompt: str     ユーザープロンプト
  eval_type: str       評価関数の種別
  eval_params: dict    評価関数へのパラメータ
  consistency_runs: int  (output_quality/consistency のみ) 何回実行するか
"""

TEST_CASES = [

    # ── 1. 指示追従性: フォーマット ──────────────────────────────────────────

    {
        "id": "if_format_json_01",
        "category": "instruction_following",
        "metric": "format_json",
        "description": "JSON形式で回答するよう指示",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "以下の情報をJSON形式のみで返してください。他のテキストは一切含めないでください。\n"
            "名前: 田中太郎, 年齢: 30, 職業: エンジニア"
        ),
        "eval_type": "format_json",
        "eval_params": {},
    },
    {
        "id": "if_format_json_02",
        "category": "instruction_following",
        "metric": "format_json",
        "description": "リスト構造をJSONで返す",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "日本の主要都市を5つ、JSON配列形式で返してください。"
            "例: [\"東京\", ...] のように配列のみを返し、説明文は不要です。"
        ),
        "eval_type": "format_json",
        "eval_params": {},
    },
    {
        "id": "if_format_markdown_01",
        "category": "instruction_following",
        "metric": "format_markdown_headers",
        "description": "Markdownヘッダーを使った構造化回答",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "Pythonの特徴を3つ説明してください。必ずMarkdownの##ヘッダーで各項目を区切ってください。"
        ),
        "eval_type": "format_markdown_headers",
        "eval_params": {"min_headers": 3},
    },
    {
        "id": "if_format_bullet_01",
        "category": "instruction_following",
        "metric": "format_bullet_list",
        "description": "箇条書き形式での回答",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "健康的な生活習慣を5つ、箇条書き（- または * で始まる）で列挙してください。"
            "箇条書き以外の文章は不要です。"
        ),
        "eval_type": "format_bullet_list",
        "eval_params": {"min_items": 5},
    },

    # ── 2. 指示追従性: 文字数制約 ────────────────────────────────────────────

    {
        "id": "if_length_max_01",
        "category": "instruction_following",
        "metric": "length_constraint",
        "description": "100文字以内の制約",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": "機械学習とは何か、100文字以内で簡潔に説明してください。",
        "eval_type": "length_constraint",
        "eval_params": {"max_chars": 100},
    },
    {
        "id": "if_length_max_02",
        "category": "instruction_following",
        "metric": "length_constraint",
        "description": "50文字以内の厳しい制約",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": "人工知能を50文字以内で定義してください。",
        "eval_type": "length_constraint",
        "eval_params": {"max_chars": 50},
    },
    {
        "id": "if_length_min_01",
        "category": "instruction_following",
        "metric": "length_constraint",
        "description": "200文字以上の制約",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": "気候変動の原因について、最低200文字以上で説明してください。",
        "eval_type": "length_constraint",
        "eval_params": {"min_chars": 200},
    },

    # ── 3. 指示追従性: 否定命令 ──────────────────────────────────────────────

    {
        "id": "if_forbidden_01",
        "category": "instruction_following",
        "metric": "forbidden_keywords",
        "description": "特定の単語を使わないよう指示",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "コーヒーについて説明してください。ただし「カフェイン」という単語は絶対に使わないでください。"
        ),
        "eval_type": "forbidden_keywords",
        "eval_params": {"forbidden": ["カフェイン", "caffeine"]},
    },
    {
        "id": "if_forbidden_02",
        "category": "instruction_following",
        "metric": "forbidden_keywords",
        "description": "謝罪表現を使わないよう指示",
        "system_prompt": "あなたは自信を持って答えるアシスタントです。謝罪や言い訳は一切しないでください。",
        "user_prompt": "円周率の近似値を教えてください。",
        "eval_type": "forbidden_keywords",
        "eval_params": {"forbidden": ["申し訳", "すみません", "ごめん", "sorry"]},
    },

    # ── 4. 指示追従性: 役割維持 ──────────────────────────────────────────────

    {
        "id": "if_persona_01",
        "category": "instruction_following",
        "metric": "persona_keywords",
        "description": "医師ペルソナの維持",
        "system_prompt": "あなたは内科の医師です。患者に対して専門的かつ丁寧に説明してください。",
        "user_prompt": "最近疲れやすいのですが、何か原因が考えられますか？",
        "eval_type": "persona_keywords",
        "eval_params": {
            "persona_keywords": ["症状", "検査", "医師", "診断", "受診", "疾患", "治療", "体調"],
            "anti_keywords": ["AIとして", "言語モデル", "私はAI"],
        },
    },
    {
        "id": "if_persona_02",
        "category": "instruction_following",
        "metric": "persona_keywords",
        "description": "シェフペルソナの維持",
        "system_prompt": "あなたはフランス料理の一流シェフです。料理について情熱を持って語ってください。",
        "user_prompt": "パスタを美味しく作るコツを教えてください。",
        "eval_type": "persona_keywords",
        "eval_params": {
            "persona_keywords": ["食材", "火加減", "塩", "味", "料理", "調理", "仕上げ"],
            "anti_keywords": ["AIとして", "言語モデル"],
        },
    },

    # ── 5. 出力品質: QA正答率 ────────────────────────────────────────────────

    {
        "id": "oq_qa_01",
        "category": "output_quality",
        "metric": "qa_exact",
        "description": "基礎知識QA: 日本の首都",
        "system_prompt": "あなたは知識豊富なアシスタントです。",
        "user_prompt": "日本の首都はどこですか？一言で答えてください。",
        "eval_type": "qa_exact",
        "eval_params": {"expected": "東京"},
    },
    {
        "id": "oq_qa_02",
        "category": "output_quality",
        "metric": "qa_exact",
        "description": "計算QA: 単純な掛け算",
        "system_prompt": "あなたは計算を得意とするアシスタントです。",
        "user_prompt": "17 × 13 の答えを数字だけで答えてください。",
        "eval_type": "qa_exact",
        "eval_params": {"expected": "221"},
    },
    {
        "id": "oq_qa_03",
        "category": "output_quality",
        "metric": "qa_exact",
        "description": "知識QA: 光の速度",
        "system_prompt": "あなたは科学に詳しいアシスタントです。",
        "user_prompt": "光の速度は秒速何kmですか？数値のみ答えてください。",
        "eval_type": "qa_exact",
        "eval_params": {"expected": "300000"},
    },
    {
        "id": "oq_qa_04",
        "category": "output_quality",
        "metric": "qa_exact",
        "description": "プログラミングQA",
        "system_prompt": "あなたはプログラミングの専門家です。",
        "user_prompt": "Pythonでリストを逆順にするメソッドは何ですか？メソッド名だけ答えてください。",
        "eval_type": "qa_exact",
        "eval_params": {"expected": "reverse"},
    },

    # ── 6. 出力品質: 完全性 ──────────────────────────────────────────────────

    {
        "id": "oq_completeness_01",
        "category": "output_quality",
        "metric": "completeness",
        "description": "必須要素をすべて含む説明",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": (
            "HTTPとHTTPSの違いを説明してください。"
            "必ず「暗号化」「SSL」「ポート番号」「セキュリティ」の4点に触れてください。"
        ),
        "eval_type": "completeness",
        "eval_params": {"checklist": ["暗号化", "SSL", "ポート番号", "セキュリティ"]},
    },
    {
        "id": "oq_completeness_02",
        "category": "output_quality",
        "metric": "completeness",
        "description": "レシピの必須要素",
        "system_prompt": "あなたは料理が得意なアシスタントです。",
        "user_prompt": (
            "カレーライスの作り方を教えてください。"
            "材料、手順、調理時間、ポイントの4つを必ず含めてください。"
        ),
        "eval_type": "completeness",
        "eval_params": {"checklist": ["材料", "手順", "調理時間", "ポイント"]},
    },

    # ── 7. 出力品質: 一貫性 ──────────────────────────────────────────────────

    {
        "id": "oq_consistency_01",
        "category": "output_quality",
        "metric": "consistency",
        "description": "同一質問の一貫性（3回）",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": "「成功」を一文で定義してください。",
        "eval_type": "consistency",
        "eval_params": {},
        "consistency_runs": 3,
    },
    {
        "id": "oq_consistency_02",
        "category": "output_quality",
        "metric": "consistency",
        "description": "事実確認の一貫性（3回）",
        "system_prompt": "あなたは役立つアシスタントです。",
        "user_prompt": "富士山の高さは何メートルですか？",
        "eval_type": "consistency",
        "eval_params": {},
        "consistency_runs": 3,
    },
]
