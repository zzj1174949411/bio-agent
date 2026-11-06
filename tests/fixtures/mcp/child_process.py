"""Child-process helper for verifying adapter-owned process-tree cleanup."""

import os
import subprocess
import sys
import time
from pathlib import Path


def spawn_child() -> subprocess.Popen[bytes]:
    child = subprocess.Popen(
        [sys.executable, __file__, "child"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    Path.cwd().joinpath("child.pid").write_text(str(child.pid), encoding="ascii")
    return child


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "child":
    Path.cwd().joinpath("child.started").write_text(str(os.getpid()), encoding="ascii")
    time.sleep(600)
