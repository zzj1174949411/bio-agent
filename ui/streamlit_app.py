from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from types import TracebackType
from typing import Literal

import httpx
import streamlit as st
import streamlit.components.v1 as components

from bioagent.config import Settings

PAGES = ("New Analysis", "Plan Review", "Run Monitor", "Results", "Run History")
_CANCELLABLE_STATUSES = {"AWAITING_APPROVAL", "QUEUED", "RUNNING"}
_RUN_STATUSES = (
    "DRAFT",
    "VALIDATING",
    "AWAITING_APPROVAL",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "VALIDATION_FAILED",
    "FAILED",
    "CANCELLED",
)
_FILENAME_PATTERN = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)


@dataclass(frozen=True)
class DownloadedArtifact:
    name: str
    media_type: str
    content: bytes


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30)

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.close()

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, object]:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("API response must be a JSON object")
        return payload

    def upload_dataset(
        self,
        *,
        counts_name: str,
        counts_type: str,
        counts: bytes,
        metadata_name: str,
        metadata_type: str,
        metadata: bytes,
    ) -> dict[str, object]:
        response = self._client.post(
            "/api/v1/datasets",
            files={
                "counts": (counts_name, counts, counts_type),
                "metadata": (metadata_name, metadata, metadata_type),
            },
        )
        return self._json(response)

    def get_validation(self, dataset_id: str) -> dict[str, object]:
        return self._json(self._client.get(f"/api/v1/datasets/{dataset_id}/validation"))

    def create_run(self, dataset_id: str, goal: str) -> dict[str, object]:
        response = self._client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": goal},
        )
        return self._json(response)

    def get_run(self, run_id: str) -> dict[str, object]:
        return self._json(self._client.get(f"/api/v1/runs/{run_id}"))

    def get_plan(self, run_id: str) -> dict[str, object]:
        return self._json(self._client.get(f"/api/v1/runs/{run_id}/plan"))

    def approve(
        self,
        run_id: str,
        *,
        action: Literal["approve", "reject", "cancel", "revise", "modify"],
        plan_revision: int | None = None,
        plan: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "action": action,
            "plan_revision": plan_revision,
            "plan": plan,
        }
        response = self._client.post(
            f"/api/v1/runs/{run_id}/approval",
            json=payload,
        )
        return self._json(response)

    def cancel(self, run_id: str) -> dict[str, object]:
        return self._json(self._client.post(f"/api/v1/runs/{run_id}/cancel"))

    def list_artifacts(self, run_id: str) -> dict[str, object]:
        return self._json(self._client.get(f"/api/v1/runs/{run_id}/artifacts"))

    def list_runs(self, status: str | None = None) -> dict[str, object]:
        if status is None:
            response = self._client.get("/api/v1/runs")
        else:
            response = self._client.get(
                "/api/v1/runs",
                params={"status": status},
            )
        return self._json(response)

    def download_artifact(self, run_id: str, artifact_id: str) -> DownloadedArtifact:
        response = self._client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}")
        response.raise_for_status()
        disposition = response.headers.get("content-disposition", "")
        match = _FILENAME_PATTERN.search(disposition)
        name = match.group(1).strip() if match else artifact_id
        if not name or "/" in name or "\\" in name:
            name = artifact_id
        media_type = response.headers.get("content-type", "application/octet-stream")
        return DownloadedArtifact(name=name, media_type=media_type, content=response.content)


def _initialize_session_state() -> None:
    defaults: dict[str, object] = {
        "dataset_id": None,
        "run_id": None,
        "plan_revision": None,
        "page": PAGES[0],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _current_identifier(key: str) -> str | None:
    value = st.session_state.get(key)
    return value if isinstance(value, str) and value else None


def _error_code(error: httpx.HTTPStatusError) -> str:
    try:
        payload = error.response.json()
    except ValueError:
        return f"HTTP {error.response.status_code}"
    if not isinstance(payload, dict):
        return f"HTTP {error.response.status_code}"
    detail = payload.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    return f"HTTP {error.response.status_code}"


def _show_api_error(error: Exception) -> None:
    if isinstance(error, httpx.HTTPStatusError):
        st.error(f"API request failed: {_error_code(error)}")
    elif isinstance(error, httpx.RequestError):
        st.error("Cannot reach the Bio-Agent API. Check that the backend is running.")
    else:
        st.error("The API returned an invalid response.")


def _render_qc(qc: object) -> None:
    if not isinstance(qc, dict):
        st.info("QC is not available yet.")
        return
    status = qc.get("status", "UNKNOWN")
    st.markdown(f"**QC: {status}**")
    issues = qc.get("issues", [])
    if not isinstance(issues, list):
        return
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        code = issue.get("code", "QC_ISSUE")
        message = issue.get("message", "No details provided")
        text = f"{code}: {message}"
        severity = issue.get("status")
        if severity == "FAIL":
            st.error(text)
        elif severity == "WARN":
            st.warning(text)
        else:
            st.info(text)


def _render_new_analysis(api: ApiClient) -> None:
    st.write("Upload a count matrix and matching sample metadata, then create an analysis run.")
    counts_file = st.file_uploader("Counts matrix", type=("csv", "tsv"))
    metadata_file = st.file_uploader("Sample metadata", type=("csv", "tsv"))

    if st.button(
        "Upload and validate",
        disabled=counts_file is None or metadata_file is None,
    ):
        assert counts_file is not None and metadata_file is not None
        try:
            created = api.upload_dataset(
                counts_name=counts_file.name,
                counts_type=counts_file.type or "application/octet-stream",
                counts=counts_file.getvalue(),
                metadata_name=metadata_file.name,
                metadata_type=metadata_file.type or "application/octet-stream",
                metadata=metadata_file.getvalue(),
            )
            dataset_id = created.get("dataset_id")
            if not isinstance(dataset_id, str):
                raise ValueError("dataset_id is missing")
            st.session_state["dataset_id"] = dataset_id
            validation = api.get_validation(dataset_id)
            st.success(f"Dataset validated: {dataset_id}")
            _render_qc(validation.get("qc"))
            st.json(validation)
        except (httpx.HTTPError, ValueError) as error:
            _show_api_error(error)

    dataset_id = _current_identifier("dataset_id")
    if dataset_id:
        st.caption(f"Current dataset: {dataset_id}")
    goal = st.text_area("Analysis goal", placeholder="Compare AD with Control")
    if st.button(
        "Create analysis run",
        disabled=dataset_id is None or not goal.strip(),
    ):
        assert dataset_id is not None
        try:
            run = api.create_run(dataset_id, goal.strip())
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                raise ValueError("run_id is missing")
            st.session_state["run_id"] = run_id
            revision = run.get("plan_revision")
            st.session_state["plan_revision"] = revision if isinstance(revision, int) else None
            st.success(f"Run created: {run_id}")
        except (httpx.HTTPError, ValueError) as error:
            _show_api_error(error)


def _comparison(plan: dict[str, object]) -> tuple[str, str, str]:
    value = plan.get("comparison")
    if not isinstance(value, dict):
        raise ValueError("plan comparison is missing")
    factor = value.get("factor")
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not all(isinstance(item, str) and item for item in (factor, numerator, denominator)):
        raise ValueError("plan comparison is invalid")
    return factor, numerator, denominator


def _render_plan_review(api: ApiClient) -> None:
    run_id = _current_identifier("run_id")
    if run_id is None:
        st.info("Create or select a run before reviewing a plan.")
        return
    try:
        payload = api.get_plan(run_id)
        revision = payload.get("plan_revision")
        plan = payload.get("plan")
        if not isinstance(revision, int) or not isinstance(plan, dict):
            raise ValueError("plan response is invalid")
        factor, numerator, denominator = _comparison(plan)
    except (httpx.HTTPError, ValueError) as error:
        _show_api_error(error)
        return

    st.session_state["plan_revision"] = revision
    st.markdown(f"**{numerator} relative to {denominator}**")
    st.caption(f"Factor: {factor} · Plan revision: {revision}")
    st.json(plan)

    approve_column, reject_column = st.columns(2)
    if approve_column.button("Approve plan", type="primary", use_container_width=True):
        try:
            result = api.approve(run_id, action="approve", plan_revision=revision)
            st.success(f"Plan approved. Run status: {result.get('status', 'QUEUED')}")
        except (httpx.HTTPError, ValueError) as error:
            _show_api_error(error)
    if reject_column.button("Reject plan", use_container_width=True):
        try:
            result = api.approve(run_id, action="reject", plan_revision=revision)
            st.warning(f"Plan rejected. Run status: {result.get('status', 'REJECTED')}")
        except (httpx.HTTPError, ValueError) as error:
            _show_api_error(error)

    with st.expander("Modify plan"):
        options = plan.get("options")
        options_dict = options if isinstance(options, dict) else {}
        modified_factor = st.text_input("Factor", value=factor)
        modified_numerator = st.text_input("Numerator", value=numerator)
        modified_denominator = st.text_input("Denominator", value=denominator)
        alpha = st.number_input(
            "Alpha",
            min_value=0.0001,
            max_value=0.9999,
            value=float(options_dict.get("alpha", 0.05)),
        )
        lfc_shrink = st.checkbox(
            "LFC shrink",
            value=bool(options_dict.get("lfc_shrink", True)),
        )
        if st.button("Submit modified plan"):
            modified_plan = deepcopy(plan)
            modified_plan["comparison"] = {
                "factor": modified_factor,
                "numerator": modified_numerator,
                "denominator": modified_denominator,
            }
            modified_options = dict(options_dict)
            modified_options["alpha"] = alpha
            modified_options["lfc_shrink"] = lfc_shrink
            modified_plan["options"] = modified_options
            try:
                result = api.approve(
                    run_id,
                    action="modify",
                    plan_revision=revision,
                    plan=modified_plan,
                )
                next_revision = result.get("plan_revision")
                st.session_state["plan_revision"] = (
                    next_revision if isinstance(next_revision, int) else None
                )
                st.success("Modified plan submitted for review.")
            except (httpx.HTTPError, ValueError) as error:
                _show_api_error(error)


def _render_run_monitor(api: ApiClient) -> None:
    run_id = _current_identifier("run_id")
    if run_id is None:
        st.info("Create or select a run before monitoring it.")
        return
    try:
        run = api.get_run(run_id)
    except (httpx.HTTPError, ValueError) as error:
        _show_api_error(error)
        return

    status = str(run.get("status", "UNKNOWN"))
    st.metric("Run status", status)
    st.caption("Status is polled from the API on every page refresh.")
    _render_qc(run.get("qc"))
    error = run.get("error")
    if isinstance(error, dict):
        st.error(f"Run failed: {error.get('code', 'UNKNOWN_ERROR')}")
    refresh_column, cancel_column = st.columns(2)
    refresh_column.button("Refresh status", use_container_width=True)
    if cancel_column.button(
        "Cancel run",
        disabled=status not in _CANCELLABLE_STATUSES,
        use_container_width=True,
    ):
        try:
            result = api.cancel(run_id)
            st.warning(f"Cancellation status: {result.get('status', 'REQUESTED')}")
        except (httpx.HTTPError, ValueError) as error:
            _show_api_error(error)


def _artifact_records(payload: dict[str, object]) -> list[dict[str, object]]:
    records = payload.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("artifacts response is invalid")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("artifact record is invalid")
    return records


def _render_results(api: ApiClient) -> None:
    run_id = _current_identifier("run_id")
    if run_id is None:
        st.info("Create or select a run before viewing results.")
        return
    try:
        run = api.get_run(run_id)
    except (httpx.HTTPError, ValueError) as error:
        _show_api_error(error)
        return
    _render_qc(run.get("qc"))
    if run.get("status") != "COMPLETED":
        st.warning(f"Results are unavailable while the run is {run.get('status', 'UNKNOWN')}.")
        return
    try:
        records = _artifact_records(api.list_artifacts(run_id))
        artifacts: list[DownloadedArtifact] = []
        for record in records:
            artifact_id = record.get("artifact_id")
            if not isinstance(artifact_id, str):
                raise ValueError("artifact_id is missing")
            artifacts.append(api.download_artifact(run_id, artifact_id))
    except (httpx.HTTPError, ValueError) as error:
        _show_api_error(error)
        return

    for index, artifact in enumerate(artifacts):
        st.subheader(artifact.name)
        if artifact.media_type.startswith("image/png") or artifact.name.lower().endswith(".png"):
            st.image(artifact.content, caption=artifact.name)
        elif artifact.media_type.startswith("text/html") or artifact.name.lower().endswith(
            ".html"
        ):
            components.html(
                artifact.content.decode("utf-8", errors="replace"),
                height=500,
                scrolling=True,
            )
        st.download_button(
            f"Download {artifact.name}",
            data=artifact.content,
            file_name=artifact.name,
            mime=artifact.media_type,
            key=f"artifact-{index}",
        )


def _render_run_history(api: ApiClient) -> None:
    selected_status = st.selectbox("Status filter", ("All", *_RUN_STATUSES))
    status_filter = None if selected_status == "All" else selected_status
    try:
        payload = api.list_runs(status_filter)
        runs = payload.get("runs")
        issues = payload.get("issues")
        if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
            raise ValueError("runs response is invalid")
        if not isinstance(issues, list) or not all(
            isinstance(issue, dict) for issue in issues
        ):
            raise ValueError("run issues response is invalid")
    except (httpx.HTTPError, ValueError) as error:
        _show_api_error(error)
        return

    st.caption("History includes every analysis run indexed by this Bio-Agent project.")
    for issue in issues:
        issue_run_id = issue.get("run_id")
        code = issue.get("code")
        if not isinstance(issue_run_id, str) or not isinstance(code, str):
            continue
        st.warning(f"{code}: integrity issue for run {issue_run_id}")

    if not runs:
        st.info("No project runs match this filter.")
        return

    for run in runs:
        run_id = run.get("run_id")
        dataset_id = run.get("dataset_id")
        status = run.get("status", "UNKNOWN")
        revision = run.get("plan_revision", "—")
        attempt = run.get("attempt_id", "—")
        qc_status = run.get("qc_status", "—")
        evidence_status = run.get("evidence_status", "INVALID")
        completed_at = run.get("completed_at")
        index_updated_at = run.get("index_updated_at")
        if not isinstance(run_id, str) or not isinstance(dataset_id, str):
            st.warning("RUN_INDEX_INVALID: a run summary is missing its identity.")
            continue
        st.markdown(f"**{run_id}** — **{status}**")
        time_label = (
            f"Completed: {completed_at}"
            if isinstance(completed_at, str)
            else f"Index updated: {index_updated_at}"
        )
        st.caption(
            f"Dataset: {dataset_id} · Plan revision: {revision or '—'} · "
            f"Attempt: {attempt or '—'} · QC: {qc_status or '—'} · "
            f"Evidence: {evidence_status} · {time_label}"
        )
        if st.button("Open run", key=f"open-run-{run_id}"):
            st.session_state["run_id"] = run_id
            st.session_state["plan_revision"] = (
                revision if isinstance(revision, int) else None
            )
            st.success(f"Current run selected: {run_id}")


def main() -> None:
    st.set_page_config(page_title="Bio-Agent", page_icon="🧬", layout="wide")
    _initialize_session_state()
    page = st.sidebar.radio("Workflow", PAGES, key="page")
    st.title("Bio-Agent")
    st.header(page)
    settings = Settings()
    with ApiClient(settings.api_base_url) as api:
        if page == "New Analysis":
            _render_new_analysis(api)
        elif page == "Plan Review":
            _render_plan_review(api)
        elif page == "Run Monitor":
            _render_run_monitor(api)
        elif page == "Results":
            _render_results(api)
        else:
            _render_run_history(api)


if __name__ == "__main__":
    main()
