"""Per-user desktop election and acknowledged, bounded local file-open IPC.

No scientific or GUI package imports belong here: secondary launches exit before
constructing a window. QLocalServer uses local sockets on Unix and named pipes
on Windows; a lifetime QLockFile serializes election and stale endpoint cleanup.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import sys
import tempfile
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from platformdirs import user_cache_path
from PySide6.QtCore import QEvent, QLockFile, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_PATHS = 10_000


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
        raise RuntimeError("CurveMole's local communication directory is not owned by this user.")
    if os.name != "nt":
        path.chmod(0o700)
    return path


def absolute_paths(values):
    """Resolve relative arguments in the launching process, not the receiver."""
    result = []
    seen = set()
    for value in values:
        if not value or str(value).startswith("-psn_"):
            continue
        path = os.path.abspath(os.path.expanduser(str(value)))
        key = os.path.normcase(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


class DesktopInstance(QObject):
    paths_received = Signal(list)
    activate_requested = Signal()

    def __init__(self, directory: Path | None = None):
        super().__init__()
        directory = _private_directory(directory or user_cache_path("CurveMole") / "desktop")
        identity = hashlib.sha256(os.path.normcase(str(directory.resolve())).encode()).hexdigest()[:24]
        if sys.platform == "win32":
            self.server_name = "CurveMole-" + identity
        else:
            # macOS ignores socket permission flags. A private parent directory
            # restricts access there too, while keeping Unix socket paths short.
            base = Path(tempfile.gettempdir())
            if len(os.fsencode(str(base))) > 55:
                base = Path("/tmp")
            private = _private_directory(base / ("curvemole-" + identity))
            self.server_name = str(private / "desktop")
        self.lock = QLockFile(str(directory / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.owner = False
        self.server = None
        self._buffers = {}
        self._recent: OrderedDict[str, None] = OrderedDict()

    def acquire(self) -> bool:
        self.owner = self.lock.tryLock(0)
        if not self.owner and self.lock.error() != QLockFile.LockError.LockFailedError:
            raise RuntimeError("Cannot create CurveMole's desktop instance lock.")
        return self.owner

    def listen(self):
        if not self.owner:
            raise RuntimeError("Only the elected CurveMole instance may listen.")
        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.setMaxPendingConnections(256)
        self.server.newConnection.connect(self._accept)
        if not self.server.listen(self.server_name):
            error = self.server.errorString()
            self.close()
            raise RuntimeError(f"Cannot start CurveMole's local file-open service: {error}")

    def forward(self, paths, *, timeout_ms=20_000):
        paths = absolute_paths(paths)
        request_id = uuid.uuid4().hex
        body = json.dumps(dict(protocol=1, request_id=request_id, paths=paths),
                          ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_MESSAGE_BYTES or len(paths) > MAX_PATHS:
            raise ValueError("Too many file paths for one CurveMole open request.")
        deadline = time.monotonic() + timeout_ms / 1000
        socket = QLocalSocket()
        try:
            while time.monotonic() < deadline:
                socket.connectToServer(self.server_name)
                if socket.waitForConnected(min(200, max(1, int((deadline - time.monotonic()) * 1000)))):
                    break
                socket.abort()
                time.sleep(.03)
            else:
                raise RuntimeError("The running CurveMole did not become ready to receive files. Please retry.")
            socket.write(struct.pack("!I", len(body)) + body)
            while socket.bytesToWrite():
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining <= 0 or not socket.waitForBytesWritten(remaining):
                    raise RuntimeError("Could not send files to the running CurveMole.")
            response = bytearray()
            while b"\n" not in response:
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining <= 0:
                    raise RuntimeError("CurveMole did not acknowledge the file-open request. Please retry.")
                if not socket.bytesAvailable() and not socket.waitForReadyRead(remaining):
                    raise RuntimeError("CurveMole did not acknowledge the file-open request. Please retry.")
                response.extend(bytes(socket.readAll()))
                if len(response) > 256:
                    raise RuntimeError("Invalid response from CurveMole's local file-open service.")
            if bytes(response) != b"OK:" + request_id.encode() + b"\n":
                raise RuntimeError("CurveMole rejected the file-open request.")
        finally:
            socket.abort()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(MAX_MESSAGE_BYTES + 5)
            self._buffers[socket] = bytearray()
            timeout = QTimer(socket)
            timeout.setSingleShot(True)
            timeout.timeout.connect(lambda peer=socket: peer.abort())
            timeout.start(20_000)
            socket.readyRead.connect(lambda peer=socket: self._read(peer))
            socket.disconnected.connect(lambda peer=socket: self._discard(peer))
            self._read(socket)

    def _discard(self, socket):
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _read(self, socket):
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) < 4:
            return
        size = struct.unpack("!I", buffer[:4])[0]
        if size > MAX_MESSAGE_BYTES or len(buffer) > size + 4:
            socket.abort()
            return
        if len(buffer) < size + 4:
            return
        try:
            message = json.loads(buffer[4:])
            paths = message["paths"]
            request_id = message["request_id"]
            if (message.get("protocol") != 1 or not isinstance(request_id, str)
                    or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id)
                    or not isinstance(paths, list) or len(paths) > MAX_PATHS
                    or any(not isinstance(path, str) or "\0" in path or len(path) > 32768
                           or not Path(path).is_absolute() for path in paths)):
                raise ValueError("Invalid file-open message")
        except (ValueError, KeyError, TypeError, UnicodeError):
            socket.abort()
            return
        self._buffers.pop(socket, None)
        if request_id not in self._recent:
            self._recent[request_id] = None
            if len(self._recent) > 8192:
                self._recent.popitem(last=False)
            if paths:
                self.paths_received.emit(paths)
            self.activate_requested.emit()
        socket.write(b"OK:" + request_id.encode() + b"\n")
        socket.disconnectFromServer()

    def close(self):
        if self.server is not None:
            self.server.close()
            for socket in tuple(self._buffers):
                socket.abort()
            self._buffers.clear()
        if self.owner:
            QLocalServer.removeServer(self.server_name)
            self.lock.unlock()
            self.owner = False


class NativeFileOpenFilter(QObject):
    """Capture Finder events even before the scientific GUI has been imported."""

    def __init__(self):
        super().__init__()
        self._file_open_handler = None
        self._pending_file_opens = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FileOpen:
            from PySide6.QtGui import QFileOpenEvent
            if isinstance(event, QFileOpenEvent) and event.file():
                self.enqueue([event.file()])
                return True
        return super().eventFilter(watched, event)

    def enqueue(self, paths):
        for path in paths:
            if self._file_open_handler is None:
                self._pending_file_opens.append(path)
            else:
                self._file_open_handler(path)

    def set_file_open_handler(self, handler):
        self._file_open_handler = handler
        pending, self._pending_file_opens = self._pending_file_opens, []
        for path in pending:
            handler(path)
