import json
import re
from difflib import SequenceMatcher


# ── Instruction Following ─────────────────────────────────────────────────────

def score_format_json(response: str) -> tuple[float, dict]:
    """JSONとしてパースできるか"""
    text = response.strip()
    # コードブロック除去
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        parsed = json.loads(text)
        return 1.0, {"parsed": True, "type": type(parsed).__name__}
    except json.JSONDecodeError as e:
        return 0.0, {"parsed": False, "error": str(e)}


def score_format_markdown_headers(response: str, min_headers: int = 1) -> tuple[float, dict]:
    """Markdownヘッダー(#)が指定数以上あるか"""
    headers = re.findall(r"^#{1,6}\s+.+", response, re.MULTILINE)
    count = len(headers)
    score = 1.0 if count >= min_headers else count / min_headers
    return score, {"header_count": count, "required": min_headers}


def score_format_bullet_list(response: str, min_items: int = 1) -> tuple[float, dict]:
    """箇条書きが指定数以上あるか"""
    items = re.findall(r"^[\-\*・･]\s+.+", response, re.MULTILINE)
    count = len(items)
    score = 1.0 if count >= min_items else count / min_items
    return score, {"bullet_count": count, "required": min_items}


def score_length_constraint(response: str, max_chars: int = None, min_chars: int = None) -> tuple[float, dict]:
    """文字数制約への遵守"""
    length = len(response.strip())
    details = {"length": length}
    score = 1.0

    if max_chars and length > max_chars:
        over_ratio = (length - max_chars) / max_chars
        score = max(0.0, 1.0 - over_ratio)
        details["max_chars"] = max_chars
        details["exceeded_by"] = length - max_chars

    if min_chars and length < min_chars:
        score = min(score, length / min_chars)
        details["min_chars"] = min_chars
        details["short_by"] = min_chars - length

    return score, details


def score_forbidden_keywords(response: str, forbidden: list[str]) -> tuple[float, dict]:
    """禁止キーワードが含まれていないか"""
    found = [kw for kw in forbidden if kw.lower() in response.lower()]
    score = 1.0 if not found else 0.0
    return score, {"forbidden": forbidden, "found": found}


def score_required_keywords(response: str, required: list[str]) -> tuple[float, dict]:
    """必須キーワードが含まれているか"""
    found = [kw for kw in required if kw.lower() in response.lower()]
    score = len(found) / len(required) if required else 1.0
    return score, {"required": required, "found": found, "missing": list(set(required) - set(found))}


def score_persona_keywords(response: str, persona_keywords: list[str],
                           anti_keywords: list[str] = None) -> tuple[float, dict]:
    """役割・ペルソナ維持: persona_keywordsが存在しanti_keywordsが不在"""
    found = [kw for kw in persona_keywords if kw.lower() in response.lower()]
    anti_found = [kw for kw in (anti_keywords or []) if kw.lower() in response.lower()]
    persona_score = len(found) / len(persona_keywords) if persona_keywords else 1.0
    anti_score = 1.0 if not anti_found else 0.0
    score = (persona_score + anti_score) / 2 if anti_keywords else persona_score
    return score, {"persona_found": found, "anti_found": anti_found}


# ── Output Quality ─────────────────────────────────────────────────────────────

def score_consistency(responses: list[str]) -> tuple[float, dict]:
    """複数回応答の一貫性（平均類似度）"""
    if len(responses) < 2:
        return 1.0, {"note": "single response"}
    pairs = []
    for i in range(len(responses)):
        for j in range(i + 1, len(responses)):
            sim = SequenceMatcher(None, responses[i], responses[j]).ratio()
            pairs.append(sim)
    avg = sum(pairs) / len(pairs)
    return avg, {"avg_similarity": avg, "num_pairs": len(pairs)}


def score_qa_exact(response: str, expected: str) -> tuple[float, dict]:
    """QA正答照合（部分一致）"""
    resp_lower = response.lower()
    exp_lower = expected.lower()
    if exp_lower in resp_lower:
        return 1.0, {"match": "exact_substring"}
    # トークン重複率
    resp_tokens = set(re.findall(r"\w+", resp_lower))
    exp_tokens = set(re.findall(r"\w+", exp_lower))
    if not exp_tokens:
        return 0.0, {"match": "none"}
    overlap = len(resp_tokens & exp_tokens) / len(exp_tokens)
    return overlap, {"match": "token_overlap", "overlap_ratio": overlap}


def score_completeness(response: str, checklist: list[str]) -> tuple[float, dict]:
    """チェックリスト達成率"""
    found = [item for item in checklist if item.lower() in response.lower()]
    score = len(found) / len(checklist) if checklist else 1.0
    return score, {"total": len(checklist), "found": len(found),
                   "missing": list(set(checklist) - set(found))}
