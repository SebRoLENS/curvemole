"""Bounded teardown of owned scientific worker processes."""

from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, wait
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


def bounded_results(pool, inputs, submit, cancellation, stop, *, limit, tick=None):
    """Yield (input index, result) with bounded submission and responsive teardown."""
    iterator = iter(enumerate(inputs))
    pending = {}
    exhausted = False
    try:
        while pending or not exhausted:
            cancellation.raise_if_cancelled()
            if tick is not None:
                tick()
            while not exhausted and len(pending) < max(1, limit):
                try:
                    index, value = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                pending[submit(pool, value)] = index
            if not pending:
                break
            done, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                yield index, future.result()
    finally:
        if pending or not exhausted:
            if stop is not None:
                stop.set()
            for future in pending:
                future.cancel()
