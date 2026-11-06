"""Proven provider controls; application byte bounds are never token/price bounds.

DeepSeek Chat Completions documents max_tokens and thinking.type=disabled:
https://api-docs.deepseek.com/api/create-chat-completion
The earlier official Chinese reference documents deepseek-v4-flash; the current
English reference uses deepseek-flash. We send the configured ID unchanged and
make no claim that a historical model alias remains available.
"""

from typing import Any

from bioagent.knowledge.retrieval_models import EvaluationControls
from bioagent.knowledge.store import KnowledgeError
from bioagent.models.profiles import ModelSnapshot


def validate_snapshot(snapshot: ModelSnapshot, controls: EvaluationControls) -> None:
    """Reject unsupported controls before model/credential construction."""
    endpoint = snapshot.base_url.rstrip("/")
    if snapshot.provider == "deepseek":
        supported = (
            endpoint in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
            and snapshot.model in {"deepseek-v4-flash", "deepseek-flash", "deepseek-v4-pro"}
            and snapshot.thinking == "disabled"
            and controls.max_input_bytes is not None
            and controls.max_input_tokens is None
            and controls.max_output_tokens <= 2000
        )
    else:
        supported = (
            snapshot.provider == "openai_compatible"
            and endpoint == "https://api.openai.com/v1"
            and snapshot.model in {"gpt-4o-2024-08-06", "gpt-4.1-2025-04-14"}
            and controls.max_input_tokens is not None
        )
    if not supported:
        raise KnowledgeError("EVALUATION_LIMITS_UNSUPPORTED")


def bind_output_limit(
    model: Any,
    snapshot: ModelSnapshot,
    limit: int,
    *,
    temperature: int = 0,
    json_mode: bool = False,
) -> Any:
    if snapshot.provider == "deepseek":
        # ChatOpenAI renames max_tokens to max_completion_tokens. The OpenAI SDK
        # merges extra_body into the final JSON; this keeps DeepSeek's real field.
        # Omit unsupported options entirely: binding None sends JSON null rather
        # than deleting a field. ModelAdapter constructs fresh default clients.
        options: dict[str, Any] = {
            "temperature": temperature,
            "extra_body": {"thinking": {"type": "disabled"}, "max_tokens": limit},
        }
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        return model.bind(**options)
    return model.bind(max_tokens=limit, temperature=temperature, seed=42)


def bind_evaluation(
    model: Any, snapshot: ModelSnapshot, controls: EvaluationControls, messages: list[Any]
) -> tuple[Any, int, int | None]:
    validate_snapshot(snapshot, controls)
    size = sum(len(str(message.content).encode("utf-8")) for message in messages)
    if controls.max_input_bytes is not None and size > controls.max_input_bytes:
        raise KnowledgeError("EVALUATION_INPUT_LIMIT")
    upper = None if snapshot.provider == "deepseek" else size + 1024
    if (
        upper is not None
        and controls.max_input_tokens is not None
        and upper > controls.max_input_tokens
    ):
        raise KnowledgeError("EVALUATION_INPUT_LIMIT")
    return bind_output_limit(model, snapshot, controls.max_output_tokens), size, upper
