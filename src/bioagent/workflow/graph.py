from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from bioagent.workflow.nodes import (
    approval_interrupt,
    await_user,
    complete,
    execute,
    failed,
    load_summary,
    make_plan,
    report,
    validate_outputs,
    validate_plan,
)
from bioagent.workflow.state import (
    WorkflowState,
    validate_approval_decision,
    validate_run_id,
    validate_workflow_input,
)


def _after_plan(state: WorkflowState) -> Literal["validate_plan", "await_user"]:
    if state.get("status") == "VALIDATION_FAILED":
        return "await_user"
    return "validate_plan"


def _after_validation(
    state: WorkflowState,
) -> Literal["approval_interrupt", "await_user"]:
    if state.get("status") == "VALIDATION_FAILED":
        return "await_user"
    return "approval_interrupt"


def _after_approval(
    state: WorkflowState,
) -> Literal["approval_interrupt", "execute", "complete"]:
    if state.get("status") == "QUEUED":
        return "execute"
    if state.get("status") == "AWAITING_APPROVAL":
        return "approval_interrupt"
    return "complete"


def _after_execute(
    state: WorkflowState,
) -> Literal["validate_outputs", "failed", "complete"]:
    if state.get("status") == "RUNNING":
        return "validate_outputs"
    if state.get("status") == "FAILED":
        return "failed"
    return "complete"


def _after_output_validation(
    state: WorkflowState,
) -> Literal["report", "failed"]:
    if state.get("status") == "RUNNING":
        return "report"
    return "failed"


class WorkflowGraph:
    """Public graph facade that validates inputs before checkpoint persistence."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    def invoke(
        self,
        value: object,
        config: object | None = None,
        **kwargs: object,
    ) -> Any:
        thread_id = self._thread_id(config)
        if isinstance(value, Command):
            if value.update is not None or value.goto or value.graph is not None:
                raise ValueError("workflow commands may only resume an approval")
            safe_value: object = Command(resume=validate_approval_decision(value.resume))
            snapshot = self._compiled.get_state(config)
            if not snapshot.values:
                raise ValueError("workflow thread does not exist")
            if snapshot.values.get("run_id") != thread_id:
                raise ValueError("checkpoint run_id does not match thread_id")
        else:
            safe_value = validate_workflow_input(value)
            if safe_value["run_id"] != thread_id:
                raise ValueError("thread_id must match run_id")
            snapshot = self._compiled.get_state(config)
            if snapshot.values:
                raise ValueError("workflow thread already exists; resume it with Command")
        return self._compiled.invoke(safe_value, config, **kwargs)

    @staticmethod
    def _thread_id(config: object | None) -> str:
        if not isinstance(config, Mapping):
            raise ValueError("workflow config with thread_id is required")
        configurable = config.get("configurable")
        if not isinstance(configurable, Mapping):
            raise ValueError("workflow config with thread_id is required")
        return validate_run_id(configurable.get("thread_id"))

    def get_graph(self, *args: object, **kwargs: object) -> Any:
        return self._compiled.get_graph(*args, **kwargs)

    def get_state(self, *args: object, **kwargs: object) -> Any:
        return self._compiled.get_state(*args, **kwargs)


def build_graph(
    planner: Any,
    executor: Any,
    checkpointer: BaseCheckpointSaver[Any],
    *,
    reporter: Callable[[WorkflowState], dict[str, object]] | None = None,
) -> WorkflowGraph:
    """Build the approval workflow with dependencies kept outside checkpoint state."""

    workflow = StateGraph(WorkflowState)
    workflow.add_node("load_summary", load_summary)
    workflow.add_node("plan", lambda state: make_plan(state, planner=planner))
    workflow.add_node("validate_plan", validate_plan)
    workflow.add_node("approval_interrupt", approval_interrupt)
    workflow.add_node("execute", lambda state: execute(state, executor=executor))
    workflow.add_node("validate_outputs", validate_outputs)
    workflow.add_node("report", lambda state: (reporter or report)(state))
    workflow.add_node("complete", complete)
    workflow.add_node("await_user", await_user)
    workflow.add_node("failed", failed)

    workflow.add_edge(START, "load_summary")
    workflow.add_edge("load_summary", "plan")
    workflow.add_conditional_edges("plan", _after_plan)
    workflow.add_conditional_edges("validate_plan", _after_validation)
    workflow.add_conditional_edges("approval_interrupt", _after_approval)
    workflow.add_conditional_edges("execute", _after_execute)
    workflow.add_conditional_edges("validate_outputs", _after_output_validation)
    workflow.add_edge("report", "complete")
    workflow.add_edge("complete", END)
    workflow.add_edge("await_user", END)
    workflow.add_edge("failed", END)
    return WorkflowGraph(workflow.compile(checkpointer=checkpointer))
