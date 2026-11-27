"""managed_process_pool reads two private ProcessPoolExecutor attributes to bound
teardown. If a Python release renames them, teardown would silently stop
terminating stuck workers; this contract test catches that."""
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

from curvemole.core.process_pool import managed_process_pool


def _sleep(seconds):
    time.sleep(seconds)
    return seconds


def test_executor_still_exposes_the_attributes_used_for_teardown():
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        pool.submit(_sleep, 0).result(timeout=60)
        assert isinstance(getattr(pool, "_processes", None), dict)
        assert getattr(pool, "_executor_manager_thread", None) is not None
    finally:
        pool.shutdown(wait=True)


def test_teardown_terminates_a_worker_that_is_still_busy():
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    started = time.monotonic()
    with managed_process_pool(pool):
        pool.submit(_sleep, 0).result(timeout=60)  # worker is up
        processes = list(pool._processes.values())
        pool.submit(_sleep, 120)  # would block an ordinary shutdown for two minutes
    assert time.monotonic() - started < 60
    assert processes and not any(process.is_alive() for process in processes)
