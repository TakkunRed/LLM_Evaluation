import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from db.database import init_db, get_runs, get_results_by_run, get_summary_by_run, save_run
from evaluator.engine import run_evaluation
from evaluator.runner import get_client, list_models
from evaluator.test_cases import TEST_CASES

init_db()

st.set_page_config(page_title="LLM Evaluator", page_icon="🧪", layout="wide")
st.title("🧪 ローカルLLM 評価ツール")

# ── サイドバー ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")
    base_url = st.text_input("LM Studio URL", value="http://localhost:1234/v1")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("更新", use_container_width=True):
            st.session_state["models"] = list_models(base_url)

    if "models" not in st.session_state:
        st.session_state["models"] = list_models(base_url)

    models = st.session_state["models"]
    if models:
        model = st.selectbox("モデル", models)
    else:
        model = st.text_input("モデル名（手動入力）", value="local-model")
        st.warning("LM Studioに接続できません。モデル名を手動入力してください。")

    run_name = st.text_input("実行名（任意）", placeholder="例: gemma-3-4b-test")
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.05)

    st.divider()
    st.caption(f"テストケース数: {len(TEST_CASES)}")
    categories = list({c["category"] for c in TEST_CASES})
    for cat in sorted(categories):
        count = sum(1 for c in TEST_CASES if c["category"] == cat)
        label = "指示追従性" if cat == "instruction_following" else "出力品質"
        st.caption(f"  • {label}: {count}件")


# ── 共通: 結果表示 ─────────────────────────────────────────────────────────────
def show_results(results: list[dict]):
    df = pd.DataFrame(results)
    overall = df["score"].mean()

    col1, col2, col3 = st.columns(3)
    col1.metric("総合スコア", f"{overall:.1%}")

    if_df = df[df["category"] == "instruction_following"]
    oq_df = df[df["category"] == "output_quality"]
    col2.metric("指示追従性", f"{if_df['score'].mean():.1%}" if not if_df.empty else "N/A")
    col3.metric("出力品質", f"{oq_df['score'].mean():.1%}" if not oq_df.empty else "N/A")

    # レーダーチャート
    summary = df.groupby("metric")["score"].mean().reset_index()
    fig_radar = go.Figure(go.Scatterpolar(
        r=summary["score"].tolist() + [summary["score"].iloc[0]],
        theta=summary["metric"].tolist() + [summary["metric"].iloc[0]],
        fill="toself",
        name="スコア",
    ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        showlegend=False,
        height=350,
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    # 詳細テーブル
    display_df = df[["category", "metric", "description", "score"]].copy()
    display_df["category"] = display_df["category"].map({
        "instruction_following": "指示追従性",
        "output_quality": "出力品質",
    })
    st.dataframe(
        display_df.style.background_gradient(subset=["score"], cmap="RdYlGn", vmin=0, vmax=1),
        use_container_width=True,
        hide_index=True,
    )

    # 個別結果の展開
    with st.expander("個別回答を見る"):
        for r in results:
            score_color = "🟢" if r["score"] >= 0.8 else "🟡" if r["score"] >= 0.5 else "🔴"
            st.markdown(f"**{score_color} {r['description']}** — スコア: `{r['score']:.2f}`")
            st.text_area("回答", r.get("response", ""), height=100,
                         key=f"resp_{r['id']}_{id(r)}", disabled=True)
            st.json(r.get("details", {}), expanded=False)
            st.divider()


# ── タブ ──────────────────────────────────────────────────────────────────────
tab_run, tab_history, tab_compare = st.tabs(["▶ 評価実行", "📋 履歴", "📊 比較"])

# ── 評価実行タブ ──────────────────────────────────────────────────────────────
with tab_run:
    st.subheader("評価を実行する")

    if st.button("🚀 評価開始", type="primary", use_container_width=True):
        client = get_client(base_url)
        run_id = save_run(model, run_name or model, {"temperature": temperature})

        progress_bar = st.progress(0)
        status_text = st.empty()

        def on_progress(current, total, desc):
            if total > 0:
                progress_bar.progress(current / total)
            status_text.text(f"[{current}/{total}] {desc}")

        with st.spinner("評価中..."):
            results = run_evaluation(client, model, run_id, temperature, on_progress)

        progress_bar.progress(1.0)
        status_text.text("✅ 評価完了")
        st.session_state["last_run_id"] = run_id
        st.session_state["last_results"] = results

    if "last_results" in st.session_state:
        st.divider()
        st.subheader("評価結果")
        show_results(st.session_state["last_results"])


# ── 履歴タブ ──────────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("過去の評価実行")
    runs = get_runs()
    if not runs:
        st.info("まだ評価を実行していません。")
    else:
        for run in runs:
            summary = get_summary_by_run(run["id"])
            if summary:
                avg = sum(r["avg_score"] for r in summary) / len(summary)
                label = (f"[{run['created_at'][:16]}] {run['model_name']} "
                         f"— {run['run_name'] or ''} (平均: {avg:.1%})")
            else:
                label = f"[{run['created_at'][:16]}] {run['model_name']}"

            with st.expander(label):
                detail_results = get_results_by_run(run["id"])
                rows = [dict(r) for r in detail_results]
                if rows:
                    df = pd.DataFrame(rows)[["category", "metric", "score"]]
                    df["category"] = df["category"].map({
                        "instruction_following": "指示追従性",
                        "output_quality": "出力品質",
                    })
                    st.dataframe(
                        df.style.background_gradient(
                            subset=["score"], cmap="RdYlGn", vmin=0, vmax=1
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )


# ── 比較タブ ──────────────────────────────────────────────────────────────────
with tab_compare:
    st.subheader("モデル間比較")
    runs = get_runs()
    if len(runs) < 2:
        st.info("比較するには2回以上評価を実行してください。")
    else:
        run_options = {
            f"[{r['created_at'][:16]}] {r['model_name']} / {r['run_name'] or ''}": r["id"]
            for r in runs
        }
        selected = st.multiselect(
            "比較する実行を選択",
            list(run_options.keys()),
            default=list(run_options.keys())[:2],
        )

        if len(selected) >= 2:
            compare_data = []
            for label in selected:
                run_id = run_options[label]
                summary = get_summary_by_run(run_id)
                for row in summary:
                    compare_data.append({
                        "run": label,
                        "metric": row["metric"],
                        "score": row["avg_score"],
                    })

            df_cmp = pd.DataFrame(compare_data)
            fig = px.bar(
                df_cmp, x="metric", y="score", color="run", barmode="group",
                range_y=[0, 1],
                labels={"score": "スコア", "metric": "評価指標"},
                title="評価指標別スコア比較",
            )
            st.plotly_chart(fig, use_container_width=True)

            # 総合比較テーブル
            pivot = df_cmp.pivot(index="metric", columns="run", values="score")
            st.dataframe(
                pivot.style.background_gradient(cmap="RdYlGn", vmin=0, vmax=1),
                use_container_width=True,
            )
