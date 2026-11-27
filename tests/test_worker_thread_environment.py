import os
from concurrent.futures import ThreadPoolExecutor

from curvemole.core.process_pool import WORKER_THREAD_VARIABLES, managed_process_pool


def test_pool_workers_start_single_threaded_and_environment_is_restored(monkeypatch):
    for name in WORKER_THREAD_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OMP_NUM_THREADS", "3")  # an explicit user choice is kept
    with managed_process_pool(ThreadPoolExecutor(1)):
        assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
        assert os.environ["OMP_NUM_THREADS"] == "3"
        with managed_process_pool(ThreadPoolExecutor(1)):
            assert os.environ["MKL_NUM_THREADS"] == "1"
        assert os.environ["MKL_NUM_THREADS"] == "1"  # still held by the outer pool
    assert "OPENBLAS_NUM_THREADS" not in os.environ
    assert os.environ["OMP_NUM_THREADS"] == "3"
