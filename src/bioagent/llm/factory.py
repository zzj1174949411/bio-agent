from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from bioagent.config import Settings
from bioagent.models.adapters import deepseek_body


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Create the configured chat model without exposing provider credentials."""
    if settings.llm_provider == "deepseek":
        if (
            settings.deepseek_api_key is None
            or not settings.deepseek_api_key.get_secret_value().strip()
        ):
            raise ValueError("DeepSeek API key is required")
        return ChatOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout=60,
            max_retries=2,
            # The planner forces one schema tool; DeepSeek thinking mode does
            # not support forced tool_choice. Keep schema validation local.
            extra_body=deepseek_body(),
        )

    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )
