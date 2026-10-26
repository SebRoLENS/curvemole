"""Real Qt IPC, including concurrent election and stale-process recovery."""
import json
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from curvemole.single_instance import MAX_MESSAGE_BYTES, DesktopInstance


def pump(app, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert condition(), "Timed out waiting for local IPC"


@pytest.fixture
def broker(tmp_path):
    app = QApplication.instance() or QApplication([])
    primary = DesktopInstance(tmp_path / "ipc")
    assert primary.acquire()
    primary.listen()
    yield app, primary, tmp_path / "ipc"
    primary.close()
    app.processEvents()


def test_forwarding_preserves_paths_and_does_not_import_the_gui(broker, tmp_path):
    app, primary, directory = broker
    received = []
    activated = []
    primary.paths_received.connect(received.append)
    primary.activate_requested.connect(lambda: activated.append(True))
    path = str(tmp_path / 'spettro λ "quoted" 10.xy')
    child = subprocess.Popen([sys.executable, '-c', '''
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from curvemole.single_instance import DesktopInstance
app=QCoreApplication([])
instance=DesktopInstance(Path(sys.argv[1]))
assert not instance.acquire()
instance.forward([sys.argv[2],sys.argv[2]])
assert 'numpy' not in sys.modules and 'PySide6.QtWidgets' not in sys.modules
assert 'curvemole.gui' not in sys.modules
''', str(directory), path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        pump(app, lambda: child.poll() is not None)
        output, error = child.communicate()
        assert child.returncode == 0, (output, error)
        assert received == [[path]]
        assert activated == [True]
        contender = DesktopInstance(directory)
        assert not contender.acquire()
        contender.close()  # Must never unlink the live owner's socket or lock.
        assert primary.server.isListening()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_partial_frames_and_duplicate_requests_are_acknowledged_once(broker, tmp_path):
    app, primary, _ = broker
    received = []
    primary.paths_received.connect(received.append)
    identifier = uuid.uuid4().hex
    body = json.dumps(dict(protocol=1, request_id=identifier, paths=[str(tmp_path / 'one.xy')])).encode()
    framed = struct.pack('!I', len(body)) + body
    for _ in range(2):
        peer = QLocalSocket()
        peer.connectToServer(primary.server_name)
        assert peer.waitForConnected(1000)
        for fragment in (framed[:1], framed[1:4], framed[4:12], framed[12:]):
            peer.write(fragment)
            peer.flush()
            app.processEvents()
        pump(app, lambda peer=peer: peer.bytesAvailable() > 0)
        assert bytes(peer.readAll()) == b'OK:' + identifier.encode() + b'\n'
        peer.abort()
        app.processEvents()
    assert received == [[str(tmp_path / 'one.xy')]]


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{"paths": "bad"}', None])
def test_malformed_or_oversized_messages_do_not_reach_the_importer(broker, body):
    app, primary, _ = broker
    received = []
    primary.paths_received.connect(received.append)
    peer = QLocalSocket()
    peer.connectToServer(primary.server_name)
    assert peer.waitForConnected(1000)
    peer.write(struct.pack('!I', MAX_MESSAGE_BYTES + 1) if body is None
               else struct.pack('!I', len(body)) + body)
    peer.flush()
    pump(app, lambda: peer.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert not received
    peer.abort()


def test_dead_owner_lock_and_socket_are_recovered(tmp_path):
    app = QApplication.instance() or QApplication([])
    directory = tmp_path / 'ipc'
    child = subprocess.run([sys.executable, '-c', '''
import os,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from curvemole.single_instance import DesktopInstance
app=QCoreApplication([])
instance=DesktopInstance(Path(sys.argv[1]))
assert instance.acquire()
instance.listen()
os._exit(0)
''', str(directory)], capture_output=True, timeout=15)
    assert child.returncode == 0, child.stderr
    primary = DesktopInstance(directory)
    try:
        assert primary.acquire()
        primary.listen()
        assert primary.server.isListening()
    finally:
        primary.close()
        app.processEvents()


def test_waiting_for_startup_times_out_without_electing_another_owner(tmp_path):
    app = QCoreApplication.instance() or QApplication([])
    owner = DesktopInstance(tmp_path / 'ipc')
    assert owner.acquire()
    client = DesktopInstance(tmp_path / 'ipc')
    try:
        assert not client.acquire()
        with pytest.raises(RuntimeError, match='did not become ready'):
            client.forward([], timeout_ms=120)
        assert not client.acquire()
    finally:
        owner.close()
        app.processEvents()


def test_concurrent_starts_elect_exactly_one_receiver(tmp_path):
    script = Path(__file__).with_name('desktop_open_process.py')
    directory = tmp_path / 'ipc'
    report = tmp_path / 'election.json'
    processes = [subprocess.Popen([sys.executable, str(script), 'elect', str(directory), str(report), str(index)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(12)]
    try:
        for child in processes:
            output, error = child.communicate(timeout=45)
            assert child.returncode == 0, (output, error)
        data = json.loads(report.read_text())
        assert len(data['paths']) == 12
        assert len(set(data['paths'])) == 12
        assert len(data['owners']) == 1
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
            child.wait()
