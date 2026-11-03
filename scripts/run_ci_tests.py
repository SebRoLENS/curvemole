"""Run pytest in a disposable CI worker, preserving its completed exit status.

Windows workers have occasionally stayed alive after printing a successful test
summary. End that worker directly after pytest.main returns, rather than waiting
for interpreter finalization. Pytest has already completed fixtures, reporters
and plugin shutdown at that point. Ordinary pytest commands and the application
do not use this entry point.
"""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None, *, hard_exit: bool | None = None) -> int:
    import pytest

    status = int(pytest.main(argv))
    print(f"CI pytest.main returned {status}; fixture teardown and pytest shutdown completed.",
          flush=True)
    if hard_exit is None:
        hard_exit = sys.platform == "win32"
    if hard_exit:
        # Do not turn failures, interruptions or collection errors into success.
        # Flush the final diagnostics before bypassing interpreter-only cleanup.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
