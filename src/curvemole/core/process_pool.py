"""Bounded teardown of owned scientific worker processes."""

from __future__ import annotations

import time
from contextlib import contextmanager


@contextmanager
def managed_process_pool(pool, *, drain=None):
    """Drain telemetry while shutting down; never wait forever on a worker exit."""
    failed = False
    try:
        yield pool
    except BaseException:
        failed = True
        raise
    finally:
        processes = list((getattr(pool, "_processes", None) or {}).values())
        manager = getattr(pool, "_executor_manager_thread", None)
        pool.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + (0 if failed else 2)
        while manager is not None and manager.is_alive() and time.monotonic() < deadline:
            if drain is not None:
                drain()
            manager.join(timeout=.02)
        # Cancellation and a stuck finalizer must not depend on solver cooperation.
        for process in processes:
            if process.is_alive():
                process.terminate()
        deadline = time.monotonic() + 1
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.kill()
        deadline = time.monotonic() + 1
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
        if manager is not None:
            manager.join(timeout=1)
