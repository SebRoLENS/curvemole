from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest

from curvemole.core import uncertainty
from curvemole.core.errors import FitCancelled
from curvemole.core.fitting import CancellationToken


def _telemetry_tail(_input):
    for _ in range(10000):
        uncertainty._WORKER_REPLICA_ACTIVITY.put((os.getpid(), None))
    return "all results ready"


def _unresponsive_replica(marker):
    Path(marker).touch()
    time.sleep(30)
    return "late result"


def test_complete_results_do_not_deadlock_on_pending_telemetry():
    previous = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    result = uncertainty._parallel_map(_telemetry_tail, [0], 1, (), CancellationToken(), None)
    assert result == ["all results ready"]
    assert time.monotonic() - started < 10
    assert {child.pid for child in multiprocessing.active_children()} <= previous


def test_cancellation_kills_unresponsive_replica_without_waiting_for_its_deadline(tmp_path):
    previous = {child.pid for child in multiprocessing.active_children()}
    token = CancellationToken()
    marker = tmp_path / "started"

    def cancel_when_running():
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        token.cancel()

    canceller = threading.Thread(target=cancel_when_running, daemon=True)
    canceller.start()
    started = time.monotonic()
    with pytest.raises(FitCancelled):
        uncertainty._parallel_map(_unresponsive_replica, [str(marker)], 1, (), token, None)
    canceller.join(timeout=5)
    assert marker.exists()
    assert time.monotonic() - started < 10
    assert {child.pid for child in multiprocessing.active_children()} <= previous
