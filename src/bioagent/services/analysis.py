"""The single entry point for creating an auditable analysis run."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bioagent.artifacts.manifest import AgentContext

if TYPE_CHECKING:
    from bioagent.api.dependencies import DependencyContainer


class AnalysisService:
    def __init__(self, dependencies: DependencyContainer) -> None:
        self._dependencies = dependencies

    def create_run(
        self,
        *,
        dataset_id: str,
        goal: str,
        agent_context: Mapping[str, object] | None = None,
    ) -> str:
        # Importing the validation helper lazily avoids a route/service cycle.
        from bioagent.api.routes import _stored_validation

        _, summary = _stored_validation(dataset_id, self._dependencies)
        run_id = self._dependencies.artifact_manager.create_run()
        config = {"configurable": {"thread_id": run_id}}
        initial: dict[str, Any] = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "user_goal": goal,
            "summary": summary.model_dump(mode="json"),
        }
        if agent_context is not None:
            initial["agent_context"] = AgentContext.model_validate(agent_context).model_dump(
                mode="json"
            )
        try:
            result = self._dependencies.graph.invoke(initial, config)
            from bioagent.api.routes import _workflow_state

            state = _workflow_state(result)
            self._dependencies.run_repository.write(run_id, state)
            return run_id
        except Exception:
            # A run directory without an index is not an analysis record.
            # Keep the directory for diagnostics; no statistical attempt was started.
            raise

    def read_run(self, run_id: str) -> dict[str, Any]:
        from bioagent.api.routes import _read_run

        return _read_run(run_id, self._dependencies)

    def approve_run(self, run_id: str, request: Any, response: Any) -> Mapping[str, object]:
        from bioagent.api.routes import _approve_run

        return _approve_run(run_id, request, response, self._dependencies)

    def cancel_run(self, run_id: str, response: Any) -> Mapping[str, object]:
        from bioagent.api.routes import _cancel_run

        return _cancel_run(run_id, response, self._dependencies)
