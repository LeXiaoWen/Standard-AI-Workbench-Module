from collections.abc import Callable
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..schemas import ApiConfig


def _build_model(api_config: ApiConfig) -> ChatOpenAI:
    # 本地模型可空 key：传占位，避免 ChatOpenAI(api_key=None) 回退读环境变量报错
    api_key = api_config.api_key or "local"
    return ChatOpenAI(
        model=api_config.model,
        api_key=api_key,
        base_url=api_config.base_url or None,
    )


def run_agent(
    api_config: ApiConfig,
    instructions: str,
    prompt: str,
    on_delta: Optional[Callable[[str], None]] = None,
) -> str:
    model = _build_model(api_config)
    messages = [
        SystemMessage(content=instructions),
        HumanMessage(content=prompt),
    ]
    if on_delta is not None:
        chunks: list[str] = []
        for chunk in model.stream(messages):
            content = chunk.content
            if content:
                chunk_str = str(content)
                chunks.append(chunk_str)
                on_delta(chunk_str)
        return "".join(chunks).strip()
    response = model.invoke(messages)
    return str(response.content).strip()
