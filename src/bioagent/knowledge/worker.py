"""Fixed subprocess entry. Inputs come only from the trusted local supervisor."""

import argparse
import json
import socket
from pathlib import Path

from bioagent.knowledge.parser import DoclingParser
from bioagent.knowledge.store import KnowledgeError


def deny_network(*args: object, **kwargs: object) -> None:
    raise PermissionError("local parser network disabled")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    # Offline flags alone can still allow a library's independent download path.
    # Block Python socket connections before importing any optional parser packages.
    for name in ("connect", "connect_ex"):
        setattr(socket.socket, name, deny_network)
    for name in ("create_connection",):
        setattr(socket, name, deny_network)
    try:
        DoclingParser().parse(args.source, args.output, args.models)
        return 0
    except Exception as error:
        code = error.code if isinstance(error, KnowledgeError) else "PARSE_PROCESS_FAILED"
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "failure.json").write_text(json.dumps({"code": code}), encoding="utf-8")
        # Never serialize raw exceptions or PDF content to API-visible diagnostic state.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
