"""Compact, detached plugin snapshots kept solely in process memory.

The bytes here are produced by this process, never loaded from a project file or
plugin. Pickle preserves the complete Python project graph without making a
second persistent file format. Field buffers are immutable and weakly interned:
Undo commands share unchanged results/history without sharing writable objects.
"""
from __future__ import annotations

import hashlib
import pickle
import weakref
import zlib
from dataclasses import dataclass, fields
from typing import Any

from curvemole.core.project import Project


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _ArrayBuffer:
    payload: bytes
    digest: bytes


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _PackedField:
    payload: bytes
    arrays: tuple[tuple[_ArrayBuffer, bool], ...]

    def restore(self) -> Any:
        # Writable arrays must get their own storage. Read-only arrays can
        # safely use the detached immutable bytes: even setflags(write=True)
        # cannot expose a live project or another snapshot to mutation.
        buffers = [memoryview(value.payload) if readonly else bytearray(value.payload)
                   for value, readonly in self.arrays]
        return pickle.loads(zlib.decompress(self.payload), buffers=buffers)


class _CompressedWriter:
    """Feed Pickler directly into compression, avoiding a full raw pickle copy."""

    def __init__(self) -> None:
        self.compressor = zlib.compressobj(level=1)
        self.parts: list[bytes] = []

    def write(self, value: bytes | pickle.PickleBuffer) -> int:
        compressed = self.compressor.compress(value)
        if compressed:
            self.parts.append(compressed)
        return memoryview(value).nbytes

    def finish(self) -> bytes:
        self.parts.append(self.compressor.flush())
        return b"".join(self.parts)


class ProjectSnapshotStore:
    """Weakly share exact field snapshots across contexts and Undo commands."""

    def __init__(self) -> None:
        self._fields: weakref.WeakValueDictionary[bytes, _PackedField] = weakref.WeakValueDictionary()
        self._arrays: weakref.WeakValueDictionary[bytes, _ArrayBuffer] = weakref.WeakValueDictionary()

    def _array(self, buffer: pickle.PickleBuffer) -> tuple[_ArrayBuffer, bool]:
        raw = buffer.raw()
        digest = hashlib.sha256(raw).digest()
        previous = self._arrays.get(digest)
        if previous is not None and previous.payload == raw:
            value = previous
        else:
            value = _ArrayBuffer(raw.tobytes(), digest)
            self._arrays[digest] = value
        return value, raw.readonly

    def capture(self, project: Project) -> ProjectSnapshot:
        packed = {}
        for item in fields(Project):
            writer = _CompressedWriter()
            arrays = []

            def array_buffer(buffer, target=arrays):
                target.append(self._array(buffer))

            pickle.Pickler(writer, protocol=5, buffer_callback=array_buffer).dump(getattr(project, item.name))
            payload = writer.finish()
            digest = hashlib.sha256(payload)
            for array, readonly in arrays:
                digest.update(array.digest)
                digest.update(bytes([readonly]))
            key = digest.digest()
            previous = self._fields.get(key)
            if previous is not None and previous.payload == payload and previous.arrays == tuple(arrays):
                value = previous
            else:
                value = _PackedField(payload, tuple(arrays))
                self._fields[key] = value
            packed[item.name] = value
        return ProjectSnapshot(packed)

    @property
    def retained_bytes(self) -> int:
        return (sum(len(value.payload) for value in self._fields.values())
                + sum(len(value.payload) for value in self._arrays.values()))


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    _fields: dict[str, _PackedField]

    def field(self, name: str) -> Any:
        """Restore one isolated field; the stored state always stays immutable."""
        return self._fields[name].restore()

    def restore(self) -> Project:
        # Restoring slots directly preserves derived Curve arrays and avoids
        # re-running constructors, exactly as deepcopy/pickle of Project does.
        project = object.__new__(Project)
        for name, value in self._fields.items():
            setattr(project, name, value.restore())
        return project

    @property
    def retained_bytes(self) -> int:
        arrays = {id(value): value for field in self._fields.values() for value, _ in field.arrays}
        return (sum(len(value.payload) for value in self._fields.values())
                + sum(len(value.payload) for value in arrays.values()))
