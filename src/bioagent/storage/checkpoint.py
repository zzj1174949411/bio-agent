from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def sqlite_checkpoint(database: Path) -> Iterator[SqliteSaver]:
    """Open the independent SQLite store used only for LangGraph checkpoints."""

    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(database)) as checkpointer:
        yield checkpointer
