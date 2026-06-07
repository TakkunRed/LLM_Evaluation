import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from db.database import init_db, get_runs, get_results_by_run, get_summary_by_run, save_run, delete_run, update_result_score, merge_runs
from evaluator.engine import run_evaluation, iter_evaluation, rescore_run
from evaluator.runner import get_client, list_models, fetch_model_info
from evaluator.test_cases import TEST_CASES

init_db()

# ── プリセット管理 ─────────────────────────────────────────────────────────────
PRESETS_FILE = Path(__file__).parent / "presets.json"


def _load_presets() -> dict[str, list[str]]:
    """プリセットファイルを読み込む。{名前: [test_id, ...]}"""
    if PRESETS_FILE.exists():
        try:
            return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_presets(presets: dict[str, list[str]]) -> None:
    PRESETS_FILE.write_text(
        json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _apply_preset(selected_ids: list[str]) -> None:
    """session_state のチェックボックスキーにプリセットを反映して rerun する"""
    id_set = set(selected_ids)
    categories_map: dict[str, list] = {}
    for tc in TEST_CASES:
        categories_map.setdefault(tc["category"], []).append(tc)
    for cat, cases in categories_map.items():
        cat_selected = [tc for tc in cases if tc["id"] in id_set]
        st.session_state[f"cat_{cat}"] = len(cat_selected) > 0
        for tc in cases:
            st.session_state[f"tc_{tc['id']}"] = tc["id"] in id_set
    st.rerun()


CATEGORY_LABELS = {
    "instruction_following": "指示追従性",
    "output_quality":        "出力品質",
    "task_performance":      "タスク別性能",
    "behavioral_stability":  "挙動の安定性",
    "safety":                "安全性・境界",
    "efficiency":            "効率性",
    "tool_use":              "ツール呼び出し",
}

# カラーパレット
PALETTE = {
    "instruction_following": "#7C6AF7",   # 紫
    "output_quality":        "#2DD4BF",   # ティール
    "task_performance":      "#F59E0B",   # アンバー
    "behavioral_stability":  "#34D399",   # エメラルド
    "safety":                "#F472B6",   # ピンク
    "efficiency":            "#60A5FA",   # スカイブルー
    "tool_use":              "#FB923C",   # オレンジ
}
# 比較グラフ用（実行ごとに割り当て）
COMPARE_COLORS = ["#7C6AF7", "#2DD4BF", "#F59E0B", "#F472B6", "#34D399"]
RADAR_LINE   = "#7C6AF7"
RADAR_FILL   = "rgba(124,106,247,0.25)"
PLOT_BG      = "rgba(0,0,0,0)"
GRID_COLOR   = "rgba(150,150,170,0.2)"

st.set_page_config(page_title="LLM Evaluator", page_icon="🧪", layout="wide")

# コンパクトレイアウト用CSS
st.markdown("""
<style>
/* メイン上余白削減 */
.block-container { padding-top: 3rem !important; padding-bottom: 0.5rem !important; }
/* タイトル余白 */
h1 { margin-top: 0 !important; margin-bottom: 0.3rem !important; font-size: 1.4rem !important; }
/* サイドバー上余白 */
[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem !important; }
[data-testid="stSidebarContent"] { padding-top: 0.3rem !important; }
/* メトリクスカード余白 */
[data-testid="stMetric"] { padding: 0.3rem 0 !important; }
/* expander余白 */
.streamlit-expanderHeader { padding: 0.3rem 0 !important; }
/* タブ余白 */
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
</style>
""", unsafe_allow_html=True)

# ── サイドバー ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧪 LLM Evaluator")
    sb_tab_cfg, sb_tab_items = st.tabs(["⚙️ 設定", "📋 評価項目"])

    with sb_tab_cfg:
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
            st.warning("LM Studioに接続できません。")

        run_name = st.text_input("実行名（任意）", placeholder="例: gemma-3-4b-test")
        temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.05)
        max_tokens = st.number_input("max_tokens", min_value=256, max_value=32768,
                                     value=4096, step=256)

    with sb_tab_items:
        # ── プリセット ──────────────────────────────────────────────────────
        presets = _load_presets()
        preset_names = list(presets.keys())

        if preset_names:
            sel_preset = st.selectbox("プリセット選択", preset_names,
                                      label_visibility="collapsed",
                                      placeholder="プリセットを選択…")
            col_load, col_del = st.columns(2)
            with col_load:
                if st.button("📂 ロード", use_container_width=True):
                    _apply_preset(presets[sel_preset])
            with col_del:
                if st.button("🗑️ 削除", key="preset_del", use_container_width=True):
                    del presets[sel_preset]
                    _save_presets(presets)
                    st.rerun()

        with st.form("preset_save_form", clear_on_submit=True):
            new_name = st.text_input("プリセット名", placeholder="例: 指示追従のみ")
            if st.form_submit_button("💾 現在の選択を保存", use_container_width=True):
                if new_name.strip():
                    # 現在の選択IDを収集（session_stateから読む）
                    current_ids = [
                        tc["id"] for tc in TEST_CASES
                        if st.session_state.get(f"tc_{tc['id']}", True)
                        and st.session_state.get(f"cat_{tc['category']}", True)
                    ]
                    presets[new_name.strip()] = current_ids
                    _save_presets(presets)
                    st.success(f"「{new_name.strip()}」を保存しました")
                    st.rerun()
                else:
                    st.warning("プリセット名を入力してください")

        st.divider()

        # カテゴリ別にグループ化
        categories_map: dict[str, list[dict]] = {}
        for tc in TEST_CASES:
            categories_map.setdefault(tc["category"], []).append(tc)

        selected_ids: set[str] = set()
        for cat, cases in sorted(categories_map.items()):
            cat_label = CATEGORY_LABELS.get(cat, cat)
            cat_on = st.checkbox(f"**{cat_label}**", value=True, key=f"cat_{cat}")

            metrics_map: dict[str, list[dict]] = {}
            for tc in cases:
                metrics_map.setdefault(tc["metric"], []).append(tc)

            with st.expander(f"{len(metrics_map)} 指標 / {len(cases)} ケース", expanded=False):
                for metric, tcs in metrics_map.items():
                    st.caption(f"📐 {metric}")
                    for tc in tcs:
                        disabled = not cat_on
                        checked = st.checkbox(
                            tc["description"],
                            value=cat_on,
                            key=f"tc_{tc['id']}",
                            disabled=disabled,
                        )
                        if checked and not disabled:
                            selected_ids.add(tc["id"])

        selected_cases = [tc for tc in TEST_CASES if tc["id"] in selected_ids]
        st.caption(f"選択中: {len(selected_cases)} / {len(TEST_CASES)} 件")


# ── 共通: レーダーチャート ──────────────────────────────────────────────────────
def make_radar(df: pd.DataFrame, name: str = "スコア") -> go.Figure:
    summary = df.groupby("metric")["score"].mean().reset_index()
    r = summary["score"].tolist()
    theta = summary["metric"].tolist()
    fig = go.Figure(go.Scatterpolar(
        r=r + [r[0]],
        theta=theta + [theta[0]],
        fill="toself",
        fillcolor=RADAR_FILL,
        line=dict(color=RADAR_LINE, width=2),
        marker=dict(color=RADAR_LINE, size=6),
        name=name,
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=PLOT_BG,
            radialaxis=dict(
                visible=True, range=[0, 1],
                tickformat=".0%",
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
                tickfont=dict(size=10, color="#9CA3AF"),
            ),
            angularaxis=dict(
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
                tickfont=dict(size=11),
            ),
        ),
        paper_bgcolor=PLOT_BG,
        showlegend=False,
        height=320,
        margin=dict(t=30, b=30, l=40, r=40),
    )
    return fig


# ── 共通: ライブ進捗テーブル ───────────────────────────────────────────────────
def _live_table(placeholder, results: list[dict]):
    if not results:
        return
    rows = [
        {
            "":   "🟣" if r["score"] >= 0.8 else "🔵" if r["score"] >= 0.5 else "⚪",
            "カテゴリ": CATEGORY_LABELS.get(r["category"], r["category"]),
            "テスト": r["description"],
            "スコア": f"{r['score']:.2f}",
            "秒": f"{r['details'].get('elapsed_sec', ''):.1f}" if isinstance(r.get("details", {}).get("elapsed_sec"), float) else "",
        }
        for r in results
    ]
    placeholder.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── 共通: スコア横棒グラフ ──────────────────────────────────────────────────────
def make_bar(df: pd.DataFrame) -> go.Figure:
    display = df.copy()
    display = display.sort_values(["category", "score"], ascending=[True, True])
    colors = display["category"].map(PALETTE).tolist()

    fig = go.Figure(go.Bar(
        x=display["score"],
        y=display["description"],
        orientation="h",
        marker=dict(
            color=colors,
            line=dict(width=0),
        ),
        text=[f"{s:.0%}" for s in display["score"]],
        textposition="outside",
        textfont=dict(size=12),
        cliponaxis=False,
    ))
    fig.update_layout(
        xaxis=dict(
            range=[0, 1.18],
            tickformat=".0%",
            gridcolor=GRID_COLOR,
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(title="", tickfont=dict(size=11)),
        paper_bgcolor=PLOT_BG,
        plot_bgcolor=PLOT_BG,
        height=max(300, len(display) * 34),
        margin=dict(l=10, r=70, t=10, b=20),
        showlegend=False,
    )
    return fig


# ── 共通: 結果表示 ─────────────────────────────────────────────────────────────
def _category_weighted_score(df: "pd.DataFrame") -> float:
    """カテゴリ平均の単純平均（ケース数の偏りを除去）"""
    cat_means = df.groupby("category")["score"].mean()
    return cat_means.mean() if len(cat_means) > 0 else df["score"].mean()


def show_results(results: list[dict], key_prefix: str = ""):
    df = pd.DataFrame(results)
    overall = _category_weighted_score(df)

    col1, col2, col3 = st.columns(3)
    col1.metric("総合スコア", f"{overall:.1%}", help="カテゴリ平均の平均（ケース数バイアス除去）")
    if_df = df[df["category"] == "instruction_following"]
    oq_df = df[df["category"] == "output_quality"]
    col2.metric("指示追従性", f"{if_df['score'].mean():.1%}" if not if_df.empty else "N/A")
    col3.metric("出力品質", f"{oq_df['score'].mean():.1%}" if not oq_df.empty else "N/A")

    col_radar, col_bar = st.columns([1, 1])
    with col_radar:
        st.plotly_chart(make_radar(df), use_container_width=True, key=f"{key_prefix}_radar")
    with col_bar:
        st.plotly_chart(make_bar(df), use_container_width=True, key=f"{key_prefix}_bar")

    # 応答時間テーブル
    time_rows = []
    for r in results:
        d = r.get("details", {}) if isinstance(r.get("details"), dict) else {}
        elapsed = d.get("elapsed_sec")
        tps = d.get("tokens_per_sec")
        tokens = d.get("usage", {}).get("completion_tokens")
        if elapsed is not None:
            time_rows.append({
                "テスト": r.get("description", r.get("id", "")),
                "応答時間(秒)": elapsed,
                "生成トークン数": tokens,
                "tokens/sec": tps,
            })
    if time_rows:
        with st.expander("⏱️ 応答時間", expanded=False):
            time_df = pd.DataFrame(time_rows)
            avg_elapsed = time_df["応答時間(秒)"].mean()
            avg_tps = time_df["tokens/sec"].dropna().mean()
            c1, c2 = st.columns(2)
            c1.metric("平均応答時間", f"{avg_elapsed:.2f} 秒")
            if not pd.isna(avg_tps):
                c2.metric("平均 tokens/sec", f"{avg_tps:.1f}")
            st.dataframe(
                time_df.style.format({
                    "応答時間(秒)": "{:.3f}",
                    "tokens/sec": lambda v: f"{v:.1f}" if pd.notna(v) else "—",
                    "生成トークン数": lambda v: str(int(v)) if pd.notna(v) else "—",
                }),
                use_container_width=True, hide_index=True,
            )

    # 個別結果の展開
    with st.expander("個別回答を見る"):
        for r in results:
            score = r["score"]
            is_manual = r.get("details", {}).get("manual_score", False)
            score_color = "🟣" if score >= 0.8 else "🔵" if score >= 0.5 else "⚪"
            manual_badge = " ✏️" if is_manual else ""
            st.markdown(f"**{score_color} {r['description']}**{manual_badge}")

            # 質問・回答を左右に並べる
            col_q, col_a = st.columns(2)
            with col_q:
                sys_p = r.get("system_prompt", "")
                default_sys = "あなたは役立つアシスタントです。"
                if sys_p and sys_p != default_sys:
                    st.caption("システムプロンプト")
                    st.text_area("", sys_p, height=60,
                                 key=f"{key_prefix}_sysp_{r['id']}_{id(r)}", disabled=True,
                                 label_visibility="collapsed")
                st.caption("ユーザー質問")
                st.text_area("", r.get("prompt", ""), height=80,
                             key=f"{key_prefix}_prompt_{r['id']}_{id(r)}", disabled=True,
                             label_visibility="collapsed")
            with col_a:
                st.caption("回答")
                st.text_area("", r.get("response", ""), height=120,
                             key=f"{key_prefix}_resp_{r['id']}_{id(r)}", disabled=True,
                             label_visibility="collapsed")

            # スコア表示＋手動上書き
            col_score, col_slider, col_btn = st.columns([1, 3, 1])
            with col_score:
                st.metric("スコア", f"{score:.2f}", delta="手動" if is_manual else None,
                          delta_color="off")
            with col_slider:
                new_score = st.slider(
                    "スコアを修正",
                    0.0, 1.0, float(score), 0.01,
                    key=f"{key_prefix}_slider_{r['id']}_{id(r)}",
                    label_visibility="collapsed",
                )
            with col_btn:
                st.write("")
                st.write("")
                run_id = st.session_state.get("last_run_id") or r.get("run_id")
                if st.button("保存", key=f"{key_prefix}_save_{r['id']}_{id(r)}"):
                    if run_id:
                        update_result_score(run_id, r["id"], new_score)
                        r["score"] = new_score
                        r.setdefault("details", {})["manual_score"] = True
                        st.toast(f"スコアを {new_score:.2f} に更新しました")

            st.json(r.get("details", {}), expanded=False)
            st.divider()


# ── タブ ──────────────────────────────────────────────────────────────────────
tab_run, tab_history, tab_compare, tab_merge = st.tabs(["▶ 評価実行", "📋 履歴", "📊 比較", "🔀 マージ"])

# ── 評価実行タブ ──────────────────────────────────────────────────────────────
with tab_run:
    is_running = st.session_state.get("eval_running", False)

    if not selected_cases:
        st.warning("評価項目をサイドバーで1つ以上選択してください。")

    elif not is_running:
        if st.button("🚀 評価開始", type="primary", use_container_width=True):
            client = get_client(base_url)
            model_info = fetch_model_info(model, base_url)
            run_id = save_run(model, run_name or model,
                              {"temperature": temperature, "max_tokens": max_tokens,
                               "model_info": model_info})
            st.session_state["eval_run_id"] = run_id
            st.session_state["eval_results"] = []
            st.session_state["eval_running"] = True
            st.session_state["eval_generator"] = iter_evaluation(
                client, model, run_id, temperature,
                test_cases=selected_cases,
                max_tokens=max_tokens,
            )
            st.session_state["eval_total"] = len(selected_cases)
            st.rerun()

    else:
        # プレースホルダーを先に確保（rerun後も位置が安定する）
        ph_stop   = st.empty()
        ph_bar    = st.empty()
        ph_status = st.empty()
        ph_table  = st.empty()

        # ── 中断ボタン ────────────────────────────────────────────────────────
        with ph_stop.container():
            if st.button("⏹️ 中断", type="secondary", use_container_width=True):
                st.session_state["eval_running"] = False
                st.session_state.pop("eval_generator", None)
                st.session_state["last_run_id"] = st.session_state.get("eval_run_id")
                st.session_state["last_results"] = st.session_state.get("eval_results", [])
                st.rerun()

        gen            = st.session_state.get("eval_generator")
        total          = st.session_state.get("eval_total", 1)
        results_so_far = st.session_state.get("eval_results", [])

        # 現在の件数を先に表示してからLLMを呼ぶ
        current_n = len(results_so_far)
        ph_bar.progress(current_n / total,
                        text=f"⏳ {current_n} / {total} 件完了")
        if results_so_far:
            ph_status.caption(f"完了: {results_so_far[-1]['description']}")

        _live_table(ph_table, results_so_far)

        # ── 1件進める（ここでLLM呼び出し・ブロッキング）─────────────────────
        try:
            _, _, result = next(gen)
            results_so_far.append(result)
            st.session_state["eval_results"] = results_so_far
            # 即座に画面を更新してから次のイテレーションへ
            ph_bar.progress(len(results_so_far) / total,
                            text=f"✅ {len(results_so_far)} / {total} 件完了")
            ph_status.caption(f"完了: {result['description']}  スコア: {result['score']:.2f}")
            _live_table(ph_table, results_so_far)
            st.rerun()
        except StopIteration:
            st.session_state["eval_running"] = False
            st.session_state.pop("eval_generator", None)
            st.session_state["last_run_id"] = st.session_state.get("eval_run_id")
            st.session_state["last_results"] = results_so_far
            ph_bar.progress(1.0, text="🎉 評価完了")
            ph_status.empty()
            st.rerun()

    if not is_running and "last_results" in st.session_state and st.session_state["last_results"]:
        st.divider()
        show_results(st.session_state["last_results"], key_prefix="run")


# ── 履歴タブ ──────────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("過去の評価実行")
    runs = get_runs()
    if not runs:
        st.info("まだ評価を実行していません。")
    else:
        # ── ランキング ────────────────────────────────────────────────────────
        ranking_rows = []
        for run in runs:
            rows = get_results_by_run(run["id"])
            if not rows:
                continue
            df_r = pd.DataFrame([dict(r) for r in rows])
            overall = _category_weighted_score(df_r)
            if_scores = df_r[df_r["category"] == "instruction_following"]["score"].tolist()
            oq_scores = df_r[df_r["category"] == "output_quality"]["score"].tolist()
            ranking_rows.append({
                "run_id": run["id"],
                "実行名": run["run_name"] or run["model_name"],
                "モデル": run["model_name"],
                "日時": run["created_at"][:16],
                "総合": overall,
                "指示追従性": sum(if_scores) / len(if_scores) if if_scores else None,
                "出力品質": sum(oq_scores) / len(oq_scores) if oq_scores else None,
            })

        if ranking_rows:
            rank_df = (
                pd.DataFrame(ranking_rows)
                .sort_values("総合", ascending=False)
                .reset_index(drop=True)
            )
            rank_df.index += 1  # 1始まり

            # メダル付きラベル
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            rank_df.insert(0, "順位", [medals.get(i, str(i)) for i in rank_df.index])

            display_rank = rank_df.drop(columns=["run_id"])
            col_config_rank = {
                "総合":     st.column_config.ProgressColumn("総合", min_value=0, max_value=100, format="%.1f%%"),
                "指示追従性": st.column_config.ProgressColumn("指示追従性", min_value=0, max_value=100, format="%.1f%%"),
                "出力品質":  st.column_config.ProgressColumn("出力品質", min_value=0, max_value=100, format="%.1f%%"),
            }
            for col in ["総合", "指示追従性", "出力品質"]:
                display_rank[col] = (display_rank[col] * 100).round(1)

            st.dataframe(display_rank, column_config=col_config_rank,
                         use_container_width=True, hide_index=True)
            st.divider()

        for run in runs:
            summary = get_summary_by_run(run["id"])
            if summary:
                avg = sum(r["avg_score"] for r in summary) / len(summary)
                label = (f"[{run['created_at'][:16]}] {run['model_name']} "
                         f"— {run['run_name'] or ''} (平均: {avg:.1%})")
            else:
                label = f"[{run['created_at'][:16]}] {run['model_name']}"

            with st.expander(label):
                # 操作ボタン行
                col_rescore, col_del, col_confirm = st.columns([1, 1, 4])
                with col_rescore:
                    if st.button("🔄 再スコア", key=f"rescore_btn_{run['id']}",
                                 help="LLMを呼ばずにDBの回答で評価ロジックを再実行します"):
                        with st.spinner("再スコア中..."):
                            result = rescore_run(run["id"])
                        updated = result["updated"]
                        skipped = result["skipped"]
                        if updated:
                            improved = [r for r in updated if r["delta"] > 0.001]
                            declined = [r for r in updated if r["delta"] < -0.001]
                            st.success(
                                f"✅ {len(updated)} 件更新（手動スコア {len(skipped)} 件スキップ）  "
                                f"▲ {len(improved)} 件上昇 / ▼ {len(declined)} 件下降"
                            )
                        else:
                            st.info(f"更新対象なし（手動スコア {len(skipped)} 件スキップ）")
                        st.rerun()
                with col_del:
                    if st.button("🗑️ 削除", key=f"del_btn_{run['id']}"):
                        st.session_state[f"confirm_del_{run['id']}"] = True
                if st.session_state.get(f"confirm_del_{run['id']}"):
                    with col_confirm:
                        st.warning("本当に削除しますか？")
                    c1, c2, _ = st.columns([1, 1, 4])
                    with c1:
                        if st.button("はい", key=f"del_yes_{run['id']}", type="primary"):
                            delete_run(run["id"])
                            st.session_state.pop(f"confirm_del_{run['id']}", None)
                            st.rerun()
                    with c2:
                        if st.button("キャンセル", key=f"del_no_{run['id']}"):
                            st.session_state.pop(f"confirm_del_{run['id']}", None)
                            st.rerun()

                # モデル設定情報
                run_config = json.loads(run["config"]) if run["config"] else {}
                model_info = run_config.get("model_info", {})
                if model_info:
                    with st.expander("⚙️ モデル設定情報", expanded=False):
                        LABELS = {
                            "model_id":          "モデルID",
                            "path":              "パス",
                            "architecture":      "アーキテクチャ",
                            "quantization":      "量子化",
                            "context_length":    "コンテキスト長",
                            "max_context_length":"最大コンテキスト長",
                            "gpu_layers":        "GPUオフロード層数",
                            "gpu_layers_loaded": "ロード済みGPU層",
                            "n_gpu_layers":      "GPUレイヤー数",
                            "vram_usage_bytes":  "VRAM使用量",
                            "ram_usage_bytes":   "RAM使用量",
                            "state":             "状態",
                            "vocab_size":        "語彙サイズ",
                            "rope_scaling":      "RoPEスケーリング",
                        }
                        rows_info = []
                        for k, v in model_info.items():
                            if k == "source":
                                continue
                            label = LABELS.get(k, k)
                            if k in ("vram_usage_bytes", "ram_usage_bytes") and isinstance(v, (int, float)):
                                v = f"{v / 1024**3:.2f} GB"
                            rows_info.append({"項目": label, "値": str(v)})
                        if rows_info:
                            st.dataframe(pd.DataFrame(rows_info), use_container_width=True, hide_index=True)
                        else:
                            st.caption("詳細情報を取得できませんでした。")
                    st.caption(f"Temperature: {run_config.get('temperature', '—')}　／　max_tokens: {run_config.get('max_tokens', '—')}")

                rows = [dict(r) for r in get_results_by_run(run["id"])]
                if rows:
                    id_to_tc = {tc["id"]: tc for tc in TEST_CASES}
                    records = []
                    for row in rows:
                        tc = id_to_tc.get(row["test_id"], {})
                        records.append({
                            "id": row["test_id"],
                            "run_id": run["id"],
                            "category": row["category"],
                            "metric": row["metric"],
                            "description": tc.get("description", row["metric"]),
                            "score": row["score"],
                            "system_prompt": tc.get("system_prompt", ""),
                            "prompt": row.get("prompt", ""),
                            "response": row.get("response", ""),
                            "details": json.loads(row["details"]) if row.get("details") else {},
                        })
                    show_results(records, key_prefix=f"hist_{run['id']}")


# ── 比較タブ ──────────────────────────────────────────────────────────────────
with tab_compare:
    st.subheader("モデル間比較")
    runs = get_runs()
    if len(runs) < 2:
        st.info("比較するには2回以上評価を実行してください。")
    else:
        run_options = {
            f"{r['run_name'] or r['model_name']} [{r['created_at'][:16]}]": r["id"]
            for r in runs
        }
        selected = st.multiselect(
            "比較する実行を選択",
            list(run_options.keys()),
            default=list(run_options.keys())[:2],
        )

        if len(selected) >= 2:
            # 同一 metric が複数カテゴリにある場合は平均して1行にまとめる
            compare_data_raw: dict[tuple, list] = {}
            for lbl in selected:
                run_id = run_options[lbl]
                for row in get_summary_by_run(run_id):
                    key = (lbl, row["metric"])
                    compare_data_raw.setdefault(key, []).append(row["avg_score"])
            compare_data = [
                {"run": lbl, "metric": metric, "score": sum(scores) / len(scores)}
                for (lbl, metric), scores in compare_data_raw.items()
            ]
            df_cmp = pd.DataFrame(compare_data)

            # ── LLM考察エリア（グラフの上）────────────────────────────────────
            st.markdown("#### 🤖 LLMによる考察")

            sel_key = "|".join(sorted(selected))
            col_gen, col_clr = st.columns([2, 1])
            with col_gen:
                gen_clicked = st.button("考察を生成", type="primary",
                                        key="gen_analysis", use_container_width=True)
            with col_clr:
                if st.button("クリア", key="clear_analysis", use_container_width=True):
                    st.session_state.pop("analysis_text", None)
                    st.session_state.pop("analysis_sel_key", None)
                    st.rerun()

            if gen_clicked:
                # プロンプト組み立て
                overall_lines = []
                for lbl in selected:
                    run_id = run_options[lbl]
                    rows = get_results_by_run(run_id)
                    if rows:
                        df_r = pd.DataFrame([dict(r) for r in rows])
                        weighted = _category_weighted_score(df_r)
                    else:
                        weighted = 0.0
                    overall_lines.append(f"- {lbl}: 総合 {weighted:.1%}")

                metric_pivot = df_cmp.pivot_table(
                    index="metric", columns="run", values="score", aggfunc="mean"
                ).fillna(0)
                metric_lines = [
                    f"  {m}: " + "  /  ".join(f"{r}: {v:.0%}" for r, v in row_v.items())
                    for m, row_v in metric_pivot.iterrows()
                ]
                cat_df = df_cmp.merge(
                    pd.DataFrame([{"metric": t["metric"], "category": t["category"]}
                                  for t in TEST_CASES]).drop_duplicates("metric"),
                    on="metric", how="left",
                ).groupby(["category", "run"])["score"].mean().reset_index()
                cat_pivot = cat_df.pivot_table(
                    index="category", columns="run", values="score", aggfunc="mean"
                ).fillna(0)
                cat_lines = [
                    f"  {CATEGORY_LABELS.get(c, c)}: "
                    + "  /  ".join(f"{r}: {v:.0%}" for r, v in row_v.items())
                    for c, row_v in cat_pivot.iterrows()
                ]

                prompt = (
                    "以下はローカルLLMの評価結果の比較データです。\n\n"
                    "【総合スコア（カテゴリ加重平均）】\n" + "\n".join(overall_lines)
                    + "\n\n【カテゴリ別スコア】\n" + "\n".join(cat_lines)
                    + "\n\n【評価指標別スコア】\n" + "\n".join(metric_lines)
                    + "\n\n上記の評価結果を分析し、以下の観点で日本語で考察してください。\n"
                    "1. 総合的な優劣とその理由\n"
                    "2. 各モデルが得意・不得意なカテゴリや指標\n"
                    "3. 実用上の使い分けの提案\n"
                    "4. スコアが低い指標について改善の余地があるか\n"
                    "簡潔かつ具体的に、400〜600字程度でまとめてください。"
                )

                with st.spinner("考察を生成中..."):
                    try:
                        resp = get_client(base_url).chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": "あなたはLLM評価の専門家です。"},
                                {"role": "user",   "content": prompt},
                            ],
                            temperature=0.3,
                            max_tokens=8192,
                        )
                        result = (resp.choices[0].message.content if resp.choices else None) or ""
                        if not result:
                            finish = resp.choices[0].finish_reason if resp.choices else "no_choices"
                            result = f"⚠️ 空レスポンス (finish_reason={finish}, usage={resp.usage})"
                    except Exception as e:
                        result = f"⚠️ 考察の生成に失敗しました: {e}"

                st.session_state["analysis_text"] = result
                st.session_state["analysis_sel_key"] = sel_key
                st.markdown(result)

            # キャッシュ済み考察を表示（ページリロード後）
            elif st.session_state.get("analysis_text"):
                cached = st.session_state["analysis_text"]
                if st.session_state.get("analysis_sel_key") != sel_key:
                    st.caption("⚠️ 選択モデルが変わりました。再生成してください。")
                st.markdown(cached)

            st.divider()

            # 横棒グラフ
            color_discrete = {lbl: COMPARE_COLORS[i % len(COMPARE_COLORS)]
                              for i, lbl in enumerate(selected)}
            fig_cmp = px.bar(
                df_cmp,
                y="metric", x="score", color="run", barmode="group", orientation="h",
                range_x=[0, 1.18],
                text=df_cmp["score"].map(lambda s: f"{s:.0%}"),
                color_discrete_map=color_discrete,
                labels={"score": "スコア", "metric": "評価指標", "run": "実行"},
                title="評価指標別スコア比較",
            )
            fig_cmp.update_traces(textposition="outside", marker_line_width=0)
            fig_cmp.update_layout(
                height=max(300, df_cmp["metric"].nunique() * 44 * len(selected)),
                xaxis=dict(tickformat=".0%", gridcolor=GRID_COLOR, showline=False, zeroline=False),
                paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(r=70, t=50),
            )
            st.plotly_chart(fig_cmp, use_container_width=True)

            # 総合比較テーブル（ProgressColumnでデータバー）
            pivot = df_cmp.pivot_table(
                index="metric", columns="run", values="score", aggfunc="mean"
            ).reset_index()
            display_pivot = pivot.copy()
            for col in pivot.columns[1:]:
                display_pivot[col] = (pivot[col] * 100).round(1)
            col_config = {"metric": st.column_config.TextColumn("評価指標")}
            for col in pivot.columns[1:]:
                col_config[col] = st.column_config.ProgressColumn(
                    col, min_value=0, max_value=100, format="%.1f%%"
                )
            st.dataframe(display_pivot, column_config=col_config,
                         use_container_width=True, hide_index=True)


# ── マージタブ ─────────────────────────────────────────────────────────────────
with tab_merge:
    st.subheader("評価結果のマージ")
    st.caption("複数の評価実行を1つにまとめます。同じテストケースが複数のrunに存在する場合、優先度の高いrunの結果を使用します。")

    runs_m = get_runs()
    if len(runs_m) < 2:
        st.info("マージするには2回以上評価を実行してください。")
    else:
        run_opts_m = {
            f"{r['run_name'] or r['model_name']} [{r['created_at'][:16]}]": r["id"]
            for r in runs_m
        }

        # ── Step 1: マージ対象を選択 ─────────────────────────────────────────
        st.markdown("#### Step 1: マージするrunを選択")
        sel_lbls = st.multiselect(
            "マージするrunを選択（2つ以上）",
            list(run_opts_m.keys()),
            key="merge_sel",
        )

        if len(sel_lbls) >= 2:
            sel_ids = [run_opts_m[lbl] for lbl in sel_lbls]

            # ── Step 2: 優先度順を設定 ────────────────────────────────────────
            st.markdown("#### Step 2: 優先度順を設定")
            st.caption("同じテストケースが複数のrunに存在する場合、**上位のrunの結果**を採用します。")

            prio_key = "merge_priority_" + "_".join(str(i) for i in sel_ids)
            if prio_key not in st.session_state or set(st.session_state[prio_key]) != set(sel_lbls):
                st.session_state[prio_key] = sel_lbls[:]

            prio_lbls: list = st.session_state[prio_key]

            for i, lbl in enumerate(prio_lbls):
                col_rank, col_name, col_up, col_dn = st.columns([1, 7, 1, 1])
                col_rank.markdown(f"**{i+1}位**")
                col_name.write(lbl)
                if i > 0 and col_up.button("↑", key=f"pup_{i}_{prio_key}"):
                    prio_lbls[i-1], prio_lbls[i] = prio_lbls[i], prio_lbls[i-1]
                    st.rerun()
                if i < len(prio_lbls)-1 and col_dn.button("↓", key=f"pdn_{i}_{prio_key}"):
                    prio_lbls[i], prio_lbls[i+1] = prio_lbls[i+1], prio_lbls[i]
                    st.rerun()

            prio_ids = [run_opts_m[lbl] for lbl in prio_lbls]

            # ── Step 3: テストケース別の個別優先指定 ──────────────────────────
            st.markdown("#### Step 3: テストケース別の優先指定（任意）")
            st.caption("デフォルトは Step 2 の優先度順。特定のテストケースだけ別のrunを使いたい場合に設定します。")

            tid_to_lbls: dict[str, list] = {}
            for rid in prio_ids:
                for row in get_results_by_run(rid):
                    tid = row["test_id"]
                    lbl = next(k for k, v in run_opts_m.items() if v == rid)
                    if lbl not in tid_to_lbls.get(tid, []):
                        tid_to_lbls.setdefault(tid, []).append(lbl)

            duplicates = {tid: lbls for tid, lbls in tid_to_lbls.items() if len(lbls) >= 2}
            overrides: dict[str, int] = {}

            if duplicates:
                with st.expander(f"重複テストケース: {len(duplicates)}件 — クリックして個別優先を設定"):
                    for tid, lbls in sorted(duplicates.items()):
                        # デフォルト: prio_lbls の中で最初に登場するrun
                        default_lbl = next((l for l in prio_lbls if l in lbls), lbls[0])
                        chosen = st.selectbox(
                            f"`{tid}`",
                            options=lbls,
                            index=lbls.index(default_lbl),
                            key=f"ov_{tid}",
                        )
                        chosen_id = run_opts_m[chosen]
                        # 1位のrunと異なる選択のみ overrides に追加
                        default_id = run_opts_m[default_lbl]
                        if chosen_id != default_id:
                            overrides[tid] = chosen_id
            else:
                st.info("重複するテストケースはありません。")

            # ── Step 4: マージ実行 ────────────────────────────────────────────
            st.markdown("#### Step 4: マージ実行")

            total_count = len(tid_to_lbls)
            col_a, col_b = st.columns(2)
            col_a.metric("マージ後テストケース数", total_count)
            col_b.metric("重複（優先判定あり）", len(duplicates))

            merged_name = st.text_input(
                "マージ後のrun名",
                value="merged_" + "_".join(lbl.split("[")[0].strip()[:10] for lbl in prio_lbls[:2]),
                key="merge_name_input",
            )

            if st.button("🔀 マージ実行", type="primary", key="do_merge"):
                if not merged_name.strip():
                    st.error("run名を入力してください。")
                else:
                    try:
                        new_id = merge_runs(
                            run_ids_by_priority=prio_ids,
                            merged_name=merged_name.strip(),
                            overrides=overrides,
                        )
                        st.success(f"マージ完了！新しい run ID: {new_id}（名前: {merged_name}）")
                        st.caption("「履歴」タブまたは「比較」タブで確認できます。")
                    except Exception as e:
                        st.error(f"マージに失敗しました: {e}")
