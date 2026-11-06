"""A single durable queue supervising killable local PDF parser processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from threading import Event, Thread
from typing import Any

import psutil

from bioagent.knowledge.runtime import readiness
from bioagent.knowledge.store import MAX_OUTPUT_BYTES, KnowledgeError, KnowledgeStore


class KnowledgeService:
    def __init__(
        self,
        store: KnowledgeStore,
        models: Path,
        *,
        timeout_seconds: float = 600,
        memory_bytes: int = 4 * 1024**3,
        readiness: Callable[[], dict[str, Any]] | None = None,
        command: Callable[[dict[str, Any]], list[str]] | None = None,
    ) -> None:
        self.store, self.models = store, models.resolve()
        self.timeout_seconds, self.memory_bytes = timeout_seconds, memory_bytes
        self._readiness = readiness or self.readiness
        self._command = command or self._worker_command
        self._stop = Event()
        self._thread: Thread | None = None
        self.active = False

    def readiness(self) -> dict[str, Any]:
        return readiness(self.models, verify=True)

    def _worker_command(self, job: dict[str, Any]) -> list[str]:
        return [
            sys.executable,
            "-m",
            "bioagent.knowledge.worker",
            "--source",
            str(self.store.original(job["document_id"])),
            "--output",
            str(self.store.job_dir(job["id"])),
            "--models",
            str(self.models),
        ]

    def start(self, *, recover: bool = True) -> None:
        if self._thread is not None:
            return
        if recover:
            self.store.recover()
        self._thread = Thread(target=self._loop, name="literature-ingestion", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError("knowledge worker did not stop")
        self.store.cleanup_deleted()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim()
            if job is None:
                self._stop.wait(0.1)
                continue
            self.active = True
            try:
                ready = self._readiness()
                if not ready["ready"]:
                    self.store.fail(job["id"], ready["code"])
                    continue
                self._run(job)
            except KnowledgeError as error:
                allowed = {
                    "PARSE_OUTPUT_TOO_LARGE",
                    "PARSE_OUTPUT_INVALID",
                    "RESOURCE_INTEGRITY_FAILED",
                }
                code = error.code if error.code in allowed else "PARSE_PROCESS_FAILED"
                self.store.fail(job["id"], code)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.store.fail(job["id"], "PARSE_PROCESS_FAILED")
            finally:
                with suppress(KnowledgeError, OSError):
                    self.store.discard(job["id"])
                self.active = False

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
            parent.kill()
            psutil.wait_procs([*children, parent], timeout=3)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=3)

    def _run(self, job: dict[str, Any]) -> None:
        folder = self.store.job_dir(job["id"])
        folder.mkdir(parents=True, exist_ok=False)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "SYSTEMROOT",
                "WINDIR",
                "PATH",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
                "APPDATA",
                "USERPROFILE",
                "HOME",
                "LANG",
                "LC_ALL",
            }
        }
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "OMP_NUM_THREADS": "2",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        # No provider credentials, PYTHONPATH or user program arguments are inherited.
        command = self._command(job)
        if self.store.job(job["id"])["status"] != "PARSING":
            return
        self.store.progress(job["id"], "loading_and_parsing", 10)
        with (folder / "worker.log").open("wb") as log:
            process = subprocess.Popen(
                command, shell=False, cwd=folder, env=environment, stdout=log, stderr=log
            )
            start, peak = time.monotonic(), 0
            code: str | None = None
            try:
                while process.poll() is None:
                    try:
                        state = self.store.job(job["id"])["status"]
                    except KnowledgeError:
                        state = "CANCELLED"
                    if self._stop.is_set() or state != "PARSING":
                        code = "PARSE_CANCELLED"
                        if state == "PARSING":
                            self.store.cancel(job["id"])
                        break
                    if time.monotonic() - start > self.timeout_seconds:
                        code = "PARSE_TIMEOUT"
                        break
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        parent = psutil.Process(process.pid)
                        memory = sum(p.memory_info().rss for p in [parent, *parent.children(True)])
                        peak = max(peak, memory)
                        if memory > self.memory_bytes:
                            code = "PARSE_MEMORY_LIMIT"
                            break
                    # Bound disk output during conversion, including library logs.
                    total = sum(path.stat().st_size for path in folder.iterdir() if path.is_file())
                    if total > MAX_OUTPUT_BYTES:
                        code = "PARSE_OUTPUT_TOO_LARGE"
                        break
                    self._stop.wait(0.05)
                if code is not None:
                    self._kill(process)
                    self.store.fail(job["id"], code)
                    return
                if process.returncode != 0:
                    failure = "PARSE_PROCESS_FAILED"
                    with suppress(OSError, ValueError, KeyError, TypeError):
                        failure_path = folder / "failure.json"
                        if failure_path.stat().st_size < 1024:
                            reported = json.loads(failure_path.read_bytes())["code"]
                            if reported in {
                                "KNOWLEDGE_MODELS_MISSING",
                                "KNOWLEDGE_MODELS_INVALID",
                                "PARSE_INCOMPLETE",
                                "PARSE_EMPTY",
                            }:
                                failure = reported
                    self.store.fail(job["id"], failure)
                    return
                self.store.progress(job["id"], "verifying", 90)
                (folder / "metrics.json").write_text(
                    f'{{"seconds":{time.monotonic() - start},"peak_rss_bytes":{peak}}}',
                    encoding="utf-8",
                )
                self.store.publish(job["id"])
            finally:
                if process.poll() is None:
                    self._kill(process)
