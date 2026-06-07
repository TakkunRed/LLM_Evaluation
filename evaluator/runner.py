from openai import OpenAI


def get_client(base_url: str = "http://localhost:1234/v1", api_key: str = "lm-studio"):
    return OpenAI(base_url=base_url, api_key=api_key)


def call_llm(client: OpenAI, model: str, system_prompt: str, user_prompt: str,
             temperature: float = 0.7, max_tokens: int = 1024) -> tuple[str, dict]:
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


def list_models(base_url: str = "http://localhost:1234/v1", api_key: str = "lm-studio") -> list[str]:
    try:
        client = get_client(base_url, api_key)
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception:
        return []
