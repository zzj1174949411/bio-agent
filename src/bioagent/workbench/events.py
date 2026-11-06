"""SSE is a read-only projection of committed events, never a task owner."""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from uuid import UUID

from pydantic import TypeAdapter

from bioagent.workbench.models import EventKind, WorkbenchError
from bioagent.workbench.store import WorkbenchStore


def event_cursor(after: str | None, last_event_id: str | None) -> int:
    values = [0]
    for raw in (after, last_event_id):
        if raw is None:
            continue
        if len(raw) > 19 or re.fullmatch(r"[0-9]+", raw) is None or int(raw) > 2**63 - 1:
            raise WorkbenchError("INVALID_CURSOR")
        values.append(int(raw))
    return max(values)


def encode_sse(seq: int, kind: str, payload: Mapping[str, object]) -> str:
    if type(seq) is not int or seq < 1:
        raise WorkbenchError("INVALID_CURSOR")
    TypeAdapter(EventKind).validate_python(kind)
    body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"id: {seq}\nevent: {kind}\ndata: {body}\n\n"


async def stream_events(
    store: WorkbenchStore,
    conversation_id: UUID,
    after: int = 0,
    *,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    last_activity = clock()
    while True:
        events = store.list_events(conversation_id, after=after, limit=100)
        for event in events:
            yield encode_sse(
                event.seq,
                event.kind,
                {**event.payload, "turn_id": str(event.turn_id)},
            )
            after = event.seq
            last_activity = clock()
        if len(events) == 100:
            continue
        if clock() - last_activity >= 15:
            yield ": heartbeat\n\n"
            last_activity = clock()
        await pause(0.25)
