import re
import time
import json
import httpx
from openai import OpenAI


def get_client(base_url: str = "http://localhost:1234/v1", api_key: str = "lm-studio"):
    return OpenAI(base_url=base_url, api_key=api_key)


def _base_origin(base_url: str) -> str:
    """'http://localhost:1234/v1' → 'http://localhost:1234'"""
    return re.sub(r"/v\d.*$", "", base_url.rstrip("/"))


def fetch_model_info(model_id: str, base_url: str = "http://localhost:1234/v1") -> dict:
    """
    LM Studio の /api/v0/models/{id} から詳細情報を取得。
    失敗した場合は /v1/models から取得できる範囲の情報を返す。
    """
    origin = _base_origin(base_url)
    info: dict = {"model_id": model_id, "source": "unknown"}

    # LM Studio 独自エンドポイント（v0 API）
    try:
        r = httpx.get(f"{origin}/api/v0/models/{model_id}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            info = _parse_lmstudio_model(data)
            info["source"] = "lmstudio_v0"
            return info
    except Exception:
        pass

    # フォールバック: /v1/models リスト
    try:
        r = httpx.get(f"{origin}/v1/models", timeout=5)
        if r.status_code == 200:
            for m in r.json().get("data", []):
                if m.get("id") == model_id:
                    info = {"model_id": model_id, "source": "openai_compat"}
                    info.update({k: v for k, v in m.items()
                                 if k not in ("id", "object")})
                    return info
    except Exception:
        pass

    return info


def _parse_lmstudio_model(data: dict) -> dict:
    """LM Studio v0 API レスポンスから表示に有用なフィールドを抽出"""
    result: dict = {}

    def pick(d: dict, *keys):
        for k in keys:
            if k in d:
                result[k] = d[k]

    pick(data, "id", "path", "architecture", "quantization",
         "context_length", "max_context_length",
         "gpu_layers", "gpu_layers_loaded", "n_gpu_layers",
         "vram_usage_bytes", "ram_usage_bytes",
         "state", "loaded")

    # ネストされた config / params
    for sub in ("config", "params", "load_config", "model_info"):
        if isinstance(data.get(sub), dict):
            pick(data[sub],
                 "context_length", "max_context_length",
                 "gpu_offload", "gpu_layers", "n_gpu_layers",
                 "quantization", "architecture",
                 "rope_scaling", "vocab_size")

    return result


def call_llm(client: OpenAI, model: str, system_prompt: str, user_prompt: str,
             temperature: float = 0.7, max_tokens: int = 4096) -> tuple[str, dict]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
    }
    return content, usage


def call_llm_stream(client: OpenAI, model: str, system_prompt: str, user_prompt: str,
                    temperature: float = 0.7, max_tokens: int = 4096) -> tuple[str, dict]:
    """ストリーミングで呼び出し、TTFTと生成速度を計測する"""
    t_start = time.perf_counter()
    t_first = None
    chunks = []

    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if t_first is None:
            t_first = time.perf_counter()
        delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
        chunks.append(delta)

    t_end = time.perf_counter()
    content = "".join(chunks)
    ttft = round(t_first - t_start, 3) if t_first else None
    total_elapsed = round(t_end - t_start, 3)
    # 日本語は空白区切りがないため split() は過小評価になる
    # 英数字トークン数 + CJK文字数÷2 で近似（CJKは約2文字=1トークン）
    ascii_tokens = len(content.split())
    cjk_chars = len(re.findall(r"[　-鿿＀-￯]", content))
    completion_tokens = ascii_tokens + cjk_chars // 2
    tps = round(completion_tokens / total_elapsed, 1) if total_elapsed > 0 else None

    usage = {
        "prompt_tokens": 0,
        "completion_tokens": completion_tokens,
        "ttft_sec": ttft,
        "elapsed_sec": total_elapsed,
        "tokens_per_sec": tps,
    }
    return content, usage


def call_llm_tools(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    tool_responses: dict,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_iterations: int = 6,
) -> tuple[str, list[dict], dict]:
    """マルチターンのツール呼び出しループを実行する。

    Returns:
        (最終レスポンステキスト, ツール呼び出し履歴, usage)
        ツール呼び出し履歴: [{"name", "args", "result", "iteration"}, ...]
    """
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    tool_call_history: list[dict] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    for iteration in range(max_iterations):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if resp.usage:
            total_usage["prompt_tokens"]     += resp.usage.prompt_tokens     or 0
            total_usage["completion_tokens"] += resp.usage.completion_tokens or 0

        choice = resp.choices[0]
        msg    = choice.message

        # アシスタントメッセージを会話履歴に追加
        assistant_msg: dict = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        # ツール呼び出しがなければ終了
        if not msg.tool_calls or choice.finish_reason == "stop":
            return msg.content or "", tool_call_history, total_usage

        # 各ツール呼び出しを実行してモック結果を返す
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except Exception:
                fn_args = {}

            mock = tool_responses.get(fn_name)
            if mock is None:
                tool_result = {"error": f"tool '{fn_name}' is not available"}
            elif callable(mock):
                try:
                    tool_result = mock(**fn_args)
                except Exception as e:
                    tool_result = {"error": str(e)}
            else:
                tool_result = mock

            tool_call_history.append({
                "name":      fn_name,
                "args":      fn_args,
                "result":    tool_result,
                "iteration": iteration,
            })

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(tool_result, ensure_ascii=False),
            })

    # 最大イテレーション到達 — 最後のアシスタントメッセージ内容を返す
    last_assistant = next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"),
        "",
    )
    return last_assistant or "", tool_call_history, total_usage


def list_models(base_url: str = "http://localhost:1234/v1", api_key: str = "lm-studio") -> list[str]:
    try:
        client = get_client(base_url, api_key)
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception:
        return []
