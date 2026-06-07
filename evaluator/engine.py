import time
from openai import OpenAI
from .runner import call_llm
from .metrics import (
    score_format_json,
    score_format_markdown_headers,
    score_format_bullet_list,
    score_length_constraint,
    score_forbidden_keywords,
    score_required_keywords,
    score_persona_keywords,
    score_consistency,
    score_qa_exact,
    score_completeness,
)
from .test_cases import TEST_CASES
from db.database import save_result


EVAL_DISPATCH = {
    "format_json": lambda resp, params: score_format_json(resp),
    "format_markdown_headers": lambda resp, params: score_format_markdown_headers(resp, **params),
    "format_bullet_list": lambda resp, params: score_format_bullet_list(resp, **params),
    "length_constraint": lambda resp, params: score_length_constraint(resp, **params),
    "forbidden_keywords": lambda resp, params: score_forbidden_keywords(resp, **params),
    "required_keywords": lambda resp, params: score_required_keywords(resp, **params),
    "persona_keywords": lambda resp, params: score_persona_keywords(resp, **params),
    "qa_exact": lambda resp, params: score_qa_exact(resp, **params),
    "completeness": lambda resp, params: score_completeness(resp, **params),
}


def run_evaluation(client: OpenAI, model: str, run_id: int,
                   temperature: float = 0.7, progress_callback=None) -> list[dict]:
    results = []
    total = len(TEST_CASES)

    for idx, case in enumerate(TEST_CASES):
        if progress_callback:
            progress_callback(idx, total, case["description"])

        try:
            if case["eval_type"] == "consistency":
                runs = case.get("consistency_runs", 3)
                responses = []
                for _ in range(runs):
                    resp, usage = call_llm(client, model,
                                          case["system_prompt"], case["user_prompt"],
                                          temperature=temperature)
                    responses.append(resp)
                    time.sleep(0.3)
                score, details = score_consistency(responses)
                details["responses"] = responses
                response_text = responses[0]
            else:
                response_text, usage = call_llm(client, model,
                                                case["system_prompt"], case["user_prompt"],
                                                temperature=temperature)
                eval_fn = EVAL_DISPATCH.get(case["eval_type"])
                if eval_fn:
                    score, details = eval_fn(response_text, case["eval_params"])
                else:
                    score, details = 0.0, {"error": f"unknown eval_type: {case['eval_type']}"}

            details["usage"] = usage

        except Exception as e:
            response_text = ""
            score = 0.0
            details = {"error": str(e)}

        save_result(
            run_id=run_id,
            test_id=case["id"],
            category=case["category"],
            metric=case["metric"],
            prompt=case["user_prompt"],
            response=response_text,
            score=score,
            details=details,
        )

        results.append({
            "id": case["id"],
            "category": case["category"],
            "metric": case["metric"],
            "description": case["description"],
            "score": score,
            "response": response_text,
            "details": details,
        })

    if progress_callback:
        progress_callback(total, total, "完了")

    return results
