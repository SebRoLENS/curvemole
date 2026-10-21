"""Exercise real automatic collection without changing the test runner's GC."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("automatic", [True, False])
def test_background_allocations_are_collected_on_the_gui_thread(automatic):
    script = '''
import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from curvemole.gui.garbage_collection import ensure_gui_garbage_collection

app = QApplication([])
gc.collect()
AUTOMATIC_SETUP
collector = ensure_gui_garbage_collection()
assert ensure_gui_garbage_collection() is collector
assert collector.parent() is app
assert not gc.isenabled()
collected = []
main_thread = threading.get_ident()

class Cycle:
    def __init__(self):
        self.cycle = self
    def __del__(self):
        collected.append(threading.get_ident())

def allocate():
    for _ in range(2000):
        Cycle()

with ThreadPoolExecutor(max_workers=1) as pool:
    pool.submit(allocate).result(timeout=5)
assert not collected  # A worker must never run automatic cyclic destruction.
if AUTOMATIC_VALUE:
    collector.timer.setInterval(10)
    deadline = time.monotonic() + 5
    while len(collected) < 2000 and time.monotonic() < deadline:
        QTest.qWait(10)
    assert len(collected) == 2000
    assert set(collected) == {main_thread}
else:
    assert not collector.timer.isActive()  # Respect an embedding caller's GC policy.
# Old widget cycles can retain retired projects even with no new allocations.
# A queued retirement collection runs once on the GUI thread, including when
# the unreachable cycle has already been promoted to an older generation.
cycle = Cycle()
gc.collect(2)
before = len(collected)
del cycle
collector.retire_project()
collector.retire_project()
QTest.qWait(20)
assert len(collected) == before + int(AUTOMATIC_VALUE)
assert not collector._retirement_timer.isActive()
if AUTOMATIC_VALUE:
    assert collected[-1] == main_thread
collector.stop()
collector.stop()
assert gc.isenabled() == AUTOMATIC_VALUE
gc.enable()
'''.replace('AUTOMATIC_SETUP', 'gc.enable()' if automatic else 'gc.disable()')
    script = script.replace('AUTOMATIC_VALUE', repr(automatic))
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
