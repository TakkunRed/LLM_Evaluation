import json
import time
from openai import OpenAI
from .runner import call_llm, call_llm_stream, call_llm_tools
from .metrics import (
    score_format_json,
    score_format_markdown_headers,
    score_format_bullet_list,
    score_format_numbered_list,
    score_format_table,
    score_length_constraint,
    score_forbidden_keywords,
    score_required_keywords,
    score_persona_keywords,
    score_language_constraint,
    score_code_syntax,
    score_tone_polite,
    score_tone_casual,
    score_step_by_step,
    score_consistency,
    score_qa_exact,
    score_completeness,
    score_summarization,
    score_translation,
    score_classification,
    score_prompt_sensitivity,
    score_context_dependency,
    score_context_refusal,
    score_refusal_required,
    score_no_refusal_expected,
    score_hallucination_hedge,
    score_ttft,
    score_throughput,
    score_tool_use_single,
    score_tool_use_loop,
    score_tool_use_terminate,
)
from .test_cases import TEST_CASES
from db.database import save_result, get_results_by_run, update_result_score


EVAL_DISPATCH = {
    "format_json":             lambda resp, params: score_format_json(resp),
    "format_markdown_headers": lambda resp, params: score_format_markdown_headers(resp, **params),
    "format_bullet_list":      lambda resp, params: score_format_bullet_list(resp, **params),
    "format_numbered_list":    lambda resp, params: score_format_numbered_list(resp, **params),
    "format_table":            lambda resp, params: score_format_table(resp),
    "length_constraint":       lambda resp, params: score_length_constraint(resp, **params),
    "forbidden_keywords":      lambda resp, params: score_forbidden_keywords(resp, **params),
    "required_keywords":       lambda resp, params: score_required_keywords(resp, **params),
    "persona_keywords":        lambda resp, params: score_persona_keywords(resp, **params),
    "language_constraint":     lambda resp, params: score_language_constraint(resp, **params),
    "code_syntax":             lambda resp, params: score_code_syntax(resp, **params),
    "tone_polite":             lambda resp, params: score_tone_polite(resp),
    "tone_casual":             lambda resp, params: score_tone_casual(resp),
    "step_by_step":            lambda resp, params: score_step_by_step(resp, **params),
    "qa_exact":                lambda resp, params: score_qa_exact(resp, **params),
    "completeness":            lambda resp, params: score_completeness(resp, **params),
    "summarization":           lambda resp, params: score_summarization(resp, **params),
    "translation":             lambda resp, params: score_translation(resp, **params),
    "classification":          lambda resp, params: score_classification(resp, **params),
    "context_dependency":      lambda resp, params: score_context_dependency(resp, **params),
    "context_refusal":         lambda resp, params: score_context_refusal(resp),
    "refusal_required":        lambda resp, params: score_refusal_required(resp),
    "no_refusal_expected":     lambda resp, params: score_no_refusal_expected(resp),
    "hallucination_hedge":     lambda resp, params: score_hallucination_hedge(resp),
}


def _run_single(client, model, case, temperature, max_tokens) -> dict:
    """1件のテストケースを実行してresult辞書を返す（例外はキャッチしない）"""
    eval_type = case["eval_type"]

    if eval_type == "consistency":
        runs = case.get("consistency_runs", 3)
        responses, elapsed_list = [], []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        for _ in range(runs):
            t0 = time.perf_counter()
            resp, usage = call_llm(client, model,
                                   case["system_prompt"], case["user_prompt"],
                                   temperature=temperature, max_tokens=max_tokens)
            elapsed_list.append(time.perf_counter() - t0)
            responses.append(resp)
            total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
            time.sleep(0.3)
        score, details = score_consistency(responses)
        details["responses"] = responses
        response_text = responses[0]
        usage = total_usage
        details["elapsed_sec"] = round(sum(elapsed_list), 3)
        details["elapsed_per_run_sec"] = [round(e, 3) for e in elapsed_list]

    elif eval_type == "prompt_sensitivity":
        variants = case.get("prompt_variants", [case["user_prompt"]])
        responses, elapsed_list = [], []
        for variant in variants:
            t0 = time.perf_counter()
            resp, usage = call_llm(client, model,
                                   case["system_prompt"], variant,
                                   temperature=temperature, max_tokens=max_tokens)
            elapsed_list.append(time.perf_counter() - t0)
            responses.append(resp)
            time.sleep(0.3)
        score, details = score_prompt_sensitivity(responses)
        details["variants"] = variants
        details["responses"] = responses
        response_text = responses[0]
        details["elapsed_sec"] = round(sum(elapsed_list), 3)
        usage = {"prompt_tokens": 0, "completion_tokens": 0}

    elif eval_type in ("tool_use_single", "tool_use_loop", "tool_use_terminate"):
        t0 = time.perf_counter()
        response_text, tool_history, usage = call_llm_tools(
            client, model,
            case["system_prompt"], case["user_prompt"],
            tools=case.get("tools", []),
            tool_responses=case.get("tool_responses", {}),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        elapsed = time.perf_counter() - t0

        if eval_type == "tool_use_single":
            score, details = score_tool_use_single(response_text, tool_history, case["eval_params"])
        elif eval_type == "tool_use_loop":
            score, details = score_tool_use_loop(response_text, tool_history, case["eval_params"])
        else:
            score, details = score_tool_use_terminate(response_text, tool_history, case["eval_params"])

        details["tool_call_history"] = tool_history
        details["elapsed_sec"] = round(elapsed, 3)

    elif eval_type == "ttft":
        response_text, usage = call_llm_stream(client, model,
                                               case["system_prompt"], case["user_prompt"],
                                               temperature=temperature, max_tokens=max_tokens)
        ttft_sec = usage.get("ttft_sec")
        score, details = score_ttft(ttft_sec, **case.get("eval_params", {}))
        details["tokens_per_sec"] = usage.get("tokens_per_sec")
        details["elapsed_sec"] = usage.get("elapsed_sec", 0)

    elif eval_type == "throughput":
        response_text, usage = call_llm_stream(client, model,
                                               case["system_prompt"], case["user_prompt"],
                                               temperature=temperature, max_tokens=max_tokens)
        tps = usage.get("tokens_per_sec")
        score, details = score_throughput(tps, **case.get("eval_params", {}))
        details["ttft_sec"] = usage.get("ttft_sec")
        details["elapsed_sec"] = usage.get("elapsed_sec", 0)

    else:
        t0 = time.perf_counter()
        response_text, usage = call_llm(client, model,
                                        case["system_prompt"], case["user_prompt"],
                                        temperature=temperature, max_tokens=max_tokens)
        elapsed = time.perf_counter() - t0
        eval_fn = EVAL_DISPATCH.get(eval_type)
        if eval_fn:
            score, details = eval_fn(response_text, case["eval_params"])
        else:
            score, details = 0.0, {"error": f"unknown eval_type: {eval_type}"}
        details["elapsed_sec"] = round(elapsed, 3)

    details["usage"] = usage
    completion_tokens = usage.get("completion_tokens", 0)
    elapsed_total = details.get("elapsed_sec", 0)
    if elapsed_total > 0 and completion_tokens > 0 and "tokens_per_sec" not in details:
        details["tokens_per_sec"] = round(completion_tokens / elapsed_total, 1)

    return {
        "id": case["id"],
        "category": case["category"],
        "metric": case["metric"],
        "description": case["description"],
        "score": score,
        "system_prompt": case.get("system_prompt", ""),
        "prompt": case["user_prompt"],
        "response": response_text,
        "details": details,
    }


def iter_evaluation(client: OpenAI, model: str, run_id: int,
                    temperature: float = 0.7,
                    test_cases: list[dict] | None = None,
                    max_tokens: int = 4096):
    """1件ずつ結果を yield するジェネレータ"""
    cases = test_cases if test_cases is not None else TEST_CASES
    total = len(cases)

    for idx, case in enumerate(cases):
        try:
            result = _run_single(client, model, case, temperature, max_tokens)
        except Exception as e:
            result = {
                "id": case["id"],
                "category": case["category"],
                "metric": case["metric"],
                "description": case["description"],
                "score": 0.0,
                "prompt": case["user_prompt"],
                "response": "",
                "details": {"error": str(e)},
            }

        save_result(
            run_id=run_id,
            test_id=result["id"],
            category=result["category"],
            metric=result["metric"],
            prompt=result["prompt"],
            response=result["response"],
            score=result["score"],
            details=result["details"],
        )
        yield idx + 1, total, result


def run_evaluation(client: OpenAI, model: str, run_id: int,
                   temperature: float = 0.7, progress_callback=None,
                   test_cases: list[dict] | None = None,
                   max_tokens: int = 4096) -> list[dict]:
    """後方互換ラッパー（iter_evaluation を使うことを推奨）"""
    results = []
    for current, total, result in iter_evaluation(
        client, model, run_id, temperature, test_cases, max_tokens
    ):
        if progress_callback:
            progress_callback(current, total, result["description"])
        results.append(result)
    return results


def rescore_run(run_id: int, test_cases: list[dict] | None = None) -> list[dict]:
    """LLMを呼ばずにDBの回答を使って評価ロジックだけ再実行し、スコアを更新する。

    - manual_score=True のレコードはスキップ（手動修正を保持）
    - consistency / prompt_sensitivity は details["responses"] から復元して再スコア
    - ttft / throughput は details の計測値から再スコア
    戻り値: 更新したレコードのサマリーリスト
    """
    cases = test_cases if test_cases is not None else TEST_CASES
    id_to_case = {tc["id"]: tc for tc in cases}

    rows = get_results_by_run(run_id)
    updated = []
    skipped = []

    for row in rows:
        row = dict(row)
        details = json.loads(row["details"]) if row.get("details") else {}

        # 手動スコアはスキップ
        if details.get("manual_score"):
            skipped.append(row["test_id"])
            continue

        tc = id_to_case.get(row["test_id"])
        if tc is None:
            skipped.append(row["test_id"])
            continue

        eval_type = tc["eval_type"]
        response_text = row.get("response", "")
        new_score: float | None = None
        new_details: dict = {}

        try:
            if eval_type == "consistency":
                responses = details.get("responses")
                if responses and len(responses) >= 2:
                    new_score, new_details = score_consistency(responses)
                    new_details["responses"] = responses
                    new_details["usage"] = details.get("usage", {})
                    new_details["elapsed_sec"] = details.get("elapsed_sec")
                    new_details["elapsed_per_run_sec"] = details.get("elapsed_per_run_sec")

            elif eval_type == "prompt_sensitivity":
                responses = details.get("responses")
                if responses and len(responses) >= 2:
                    new_score, new_details = score_prompt_sensitivity(responses)
                    new_details["variants"] = details.get("variants", [])
                    new_details["responses"] = responses
                    new_details["elapsed_sec"] = details.get("elapsed_sec")

            elif eval_type == "ttft":
                ttft_sec = details.get("ttft_sec")
                new_score, new_details = score_ttft(ttft_sec, **tc.get("eval_params", {}))
                new_details["tokens_per_sec"] = details.get("tokens_per_sec")
                new_details["elapsed_sec"] = details.get("elapsed_sec", 0)
                new_details["usage"] = details.get("usage", {})

            elif eval_type == "throughput":
                tps = details.get("tokens_per_sec")
                new_score, new_details = score_throughput(tps, **tc.get("eval_params", {}))
                new_details["ttft_sec"] = details.get("ttft_sec")
                new_details["elapsed_sec"] = details.get("elapsed_sec", 0)
                new_details["usage"] = details.get("usage", {})

            elif eval_type in ("tool_use_single", "tool_use_loop", "tool_use_terminate"):
                tool_history = details.get("tool_call_history", [])
                if eval_type == "tool_use_single":
                    new_score, new_details = score_tool_use_single(response_text, tool_history, tc["eval_params"])
                elif eval_type == "tool_use_loop":
                    new_score, new_details = score_tool_use_loop(response_text, tool_history, tc["eval_params"])
                else:
                    new_score, new_details = score_tool_use_terminate(response_text, tool_history, tc["eval_params"])
                new_details["tool_call_history"] = tool_history
                new_details["elapsed_sec"] = details.get("elapsed_sec")
                new_details["usage"] = details.get("usage", {})

            else:
                eval_fn = EVAL_DISPATCH.get(eval_type)
                if eval_fn:
                    new_score, new_details = eval_fn(response_text, tc["eval_params"])
                    new_details["elapsed_sec"] = details.get("elapsed_sec")
                    new_details["usage"] = details.get("usage", {})
                    tps = details.get("tokens_per_sec")
                    if tps is not None:
                        new_details["tokens_per_sec"] = tps

        except Exception as e:
            new_score = None
            new_details = {"rescore_error": str(e)}

        if new_score is not None:
            update_result_score(run_id, row["test_id"], new_score, manual=False)
            updated.append({
                "test_id": row["test_id"],
                "old_score": row["score"],
                "new_score": new_score,
                "delta": round(new_score - (row["score"] or 0), 4),
            })

    return {"updated": updated, "skipped": skipped}


