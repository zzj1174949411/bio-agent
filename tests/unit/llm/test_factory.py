from unittest.mock import patch

import pytest
from pydantic import SecretStr

from bioagent.config import Settings
from bioagent.llm.factory import create_chat_model


def test_deepseek_requires_key() -> None:
    settings = Settings(llm_provider="deepseek", deepseek_api_key=None)

    with pytest.raises(ValueError, match="^DeepSeek API key is required$"):
        create_chat_model(settings)


@pytest.mark.parametrize("raw_key", ["", "   \t"])
def test_deepseek_rejects_empty_or_whitespace_key(raw_key: str) -> None:
    settings = Settings(
        llm_provider="deepseek",
        deepseek_api_key=SecretStr(raw_key),
    )

    with pytest.raises(ValueError, match="^DeepSeek API key is required$") as caught:
        create_chat_model(settings)

    assert str(caught.value) == "DeepSeek API key is required"


def test_deepseek_uses_configured_chat_openai_without_unwrapping_secret() -> None:
    secret = SecretStr("test-deepseek-key")
    settings = Settings(
        llm_provider="deepseek",
        deepseek_api_key=secret,
        deepseek_base_url="https://deepseek.test/v1",
        deepseek_model="deepseek-test",
    )
    expected_model = object()

    with patch("bioagent.llm.factory.ChatOpenAI", return_value=expected_model) as constructor:
        model = create_chat_model(settings)

    assert model is expected_model
    constructor.assert_called_once_with(
        api_key=settings.deepseek_api_key,
        base_url="https://deepseek.test/v1",
        model="deepseek-test",
        timeout=60,
        max_retries=2,
        extra_body={"thinking": {"type": "disabled"}},
    )


def test_ollama_uses_configured_chat_ollama() -> None:
    settings = Settings(
        llm_provider="ollama",
        ollama_base_url="http://ollama.test:11434",
        ollama_model="qwen-test:8b",
    )
    expected_model = object()

    with patch("bioagent.llm.factory.ChatOllama", return_value=expected_model) as constructor:
        model = create_chat_model(settings)

    assert model is expected_model
    constructor.assert_called_once_with(
        base_url="http://ollama.test:11434",
        model="qwen-test:8b",
    )
