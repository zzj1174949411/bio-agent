"""The single entry point for creating an auditable analysis run."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bioagent.artifacts.manifest import AgentContext
from bioagent.geo.repository import GeoRepository, GeoRepositoryError, GeoSourceRecord
from bioagent.models.profiles import ModelError

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
        planner: object | None = None,
    ) -> str:
        # Importing the validation helper lazily avoids a route/service cycle.
        from bioagent.api.routes import _stored_validation

        _, summary = _stored_validation(dataset_id, self._dependencies)
        context = self.build_agent_context(agent_context)
        source = self._source_for_run(dataset_id, context)
        run_id = self._dependencies.artifact_manager.create_run()
        if source is not None:
            self._copy_source(run_id, source)
        config = {"configurable": {"thread_id": run_id}}
        initial: dict[str, Any] = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "user_goal": goal,
            "summary": summary.model_dump(mode="json"),
        }
        if context is not None:
            initial["agent_context"] = context.model_dump(mode="json")
        try:
            graph = (
                self._dependencies.planning_graph(planner)
                if planner is not None
                else self._dependencies.graph
            )
            result = graph.invoke(initial, config)
            from bioagent.api.routes import _workflow_state

            state = _workflow_state(result)
            self._dependencies.run_repository.write(run_id, state)
            if planner is not None and state.get("status") != "AWAITING_APPROVAL":
                # A failed bound model must not masquerade as an approval card.
                # Keep the diagnostic index, but never fall back to a default.
                raise ModelError("MODEL_OUTPUT_INVALID")
            return run_id
        except Exception:
            # A run directory without an index is not an analysis record.
            # Keep the directory for diagnostics; no statistical attempt was started.
            raise

    @staticmethod
    def build_agent_context(
        agent_context: Mapping[str, object] | None,
    ) -> AgentContext | None:
        """Validate the immutable model/Skill snapshot at the analysis boundary."""

        if agent_context is None:
            return None
        # AgentContext is extra-forbid, so tool text, prompts, and credentials
        # cannot accidentally become checkpoint metadata.
        return AgentContext.model_validate(agent_context)

    def read_run(self, run_id: str) -> dict[str, Any]:
        from bioagent.api.routes import _read_run

        return _read_run(run_id, self._dependencies)

    def approve_run(self, run_id: str, request: Any, response: Any) -> Mapping[str, object]:
        from bioagent.api.routes import _approve_run

        return _approve_run(run_id, request, response, self._dependencies)

    def cancel_run(self, run_id: str, response: Any) -> Mapping[str, object]:
        from bioagent.api.routes import _cancel_run

        return _cancel_run(run_id, response, self._dependencies)

    def _source_for_run(
        self, dataset_id: str, context: AgentContext | None
    ) -> GeoSourceRecord | None:
        if context is None or context.source_id is None:
            return None
        repository = getattr(self._dependencies, "geo_repository", None)
        if not isinstance(repository, GeoRepository):
            raise GeoRepositoryError("GEO_SOURCE_NOT_FOUND", "source repository is unavailable")
        try:
            record = repository.read(context.source_id)
        except GeoRepositoryError:
            raise
        except (FileNotFoundError, ValueError) as error:
            raise GeoRepositoryError(
                "GEO_SOURCE_NOT_FOUND", "source record is unavailable"
            ) from error
        if record.dataset_id != dataset_id:
            raise GeoRepositoryError("SOURCE_DATASET_MISMATCH")
        return record

    def _copy_source(self, run_id: str, source: GeoSourceRecord) -> None:
        files = (
            ("source/raw/source.bin", source.raw_path),
            ("source/source.json", source.source_json),
            ("source/normalized/counts.csv", source.counts_path),
            ("source/normalized/metadata.csv", source.metadata_path),
        )
        for artifact_id, path in files:
            if not path.is_file():
                raise GeoRepositoryError("GEO_SOURCE_CACHE_TAMPERED", "source file is missing")
            self._dependencies.artifact_manager.write_bytes(run_id, artifact_id, path.read_bytes())
