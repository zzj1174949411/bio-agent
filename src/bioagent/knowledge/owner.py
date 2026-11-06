"""Standard-library process lease, acquired before recovery or deserialization."""

import importlib
import os
from pathlib import Path
from typing import BinaryIO

from bioagent.knowledge.store import KnowledgeError


class ProcessLease:
    def __init__(self, path: Path) -> None:
        self.stream: BinaryIO = path.open("a+b")
        if path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                module = importlib.import_module("msvcrt")
                module.locking(self.stream.fileno(), module.LK_NBLCK, 1)
            else:
                module = importlib.import_module("fcntl")
                module.flock(self.stream.fileno(), module.LOCK_EX | module.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise KnowledgeError("INDEX_OWNER_CONFLICT") from error

    def close(self) -> None:
        self.stream.close()
