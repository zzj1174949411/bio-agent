from uuid import uuid4

import pytest
from pydantic import ValidationError

from bioagent.artifacts.manifest import AgentContext
from bioagent.workbench.actions import parse_action


def test_actions_are_discriminated_and_cannot_approve() -> None:
    assert parse_action({"kind": "answer", "text": "ok"}).kind == "answer"
    assert parse_action({"kind": "clarify", "question": "which?"}).kind == "clarify"
    assert parse_action(
        {"kind": "plan_analysis", "dataset_id": str(uuid4()), "goal": "compare"}
    ).kind == "plan_analysis"
    with pytest.raises(ValidationError):
        parse_action({"kind": "approve", "approved": True})
    with pytest.raises(ValidationError):
        parse_action({"kind": "answer", "text": "ok", "code": "print(1)"})


def test_agent_context_rejects_mismatched_or_non_sha256_skills() -> None:
    base = {"conversation_id": uuid4(), "turn_id": uuid4()}
    with pytest.raises(ValidationError):
        AgentContext.model_validate({**base, "skill_names": ("geo",), "skill_hashes": ()})
    with pytest.raises(ValidationError):
        AgentContext.model_validate({**base, "skill_names": ("geo",), "skill_hashes": ("x",)})


def test_agent_context_is_optional_and_frozen() -> None:
    context = AgentContext(conversation_id=uuid4(), turn_id=uuid4())
    assert context.skill_names == ()
    with pytest.raises(ValidationError):
        context.turn_id = uuid4()
