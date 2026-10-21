"""Compact, lossless fit history with ordinary mutable sequence semantics.

Historical records are rarely inspected while fitting. Keep each untouched record
compressed, rather than retaining thousands of Python dictionaries and numbers.
Explicit indexing materialises that record so edits through the public API still
work; internal readers can stream records without keeping them materialised.
"""

from __future__ import annotations

import copy
import json
import zlib
from collections.abc import Iterable, Iterator, MutableSequence
from typing import Any, overload


class CompactHistory(MutableSequence[dict[str, Any]]):
    def __init__(self, records: Iterable[dict[str, Any]] = ()) -> None:
        if isinstance(records, CompactHistory):
            self._entries = [copy.deepcopy(record) if isinstance(record, dict) else record
                             for record in records._entries]
        else:
            self._entries: list[bytes | dict[str, Any]] = []
            for record in records:
                self.append_record(record)

    @staticmethod
    def _pack(record: dict[str, Any]) -> bytes | dict[str, Any]:
        # Historical records can also be extended through the Python/plugin API.
        # Preserve non-JSON extensions instead of changing their public semantics.
        def plain(value):
            if isinstance(value, dict):
                return all(isinstance(key, str) and plain(item) for key, item in value.items())
            if isinstance(value, list):
                return all(plain(item) for item in value)
            return type(value) in (str, int, float, bool, type(None))

        try:
            if not plain(record):
                return record
            payload = json.dumps(record, ensure_ascii=True, separators=(",", ":"),
                                 allow_nan=True).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            return record
        return zlib.compress(payload, level=1)

    @staticmethod
    def _unpack(record: bytes | dict[str, Any]) -> dict[str, Any]:
        return json.loads(zlib.decompress(record)) if isinstance(record, bytes) else record

    def __len__(self) -> int:
        return len(self._entries)

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...

    @overload
    def __getitem__(self, index: slice) -> CompactHistory: ...

    def __getitem__(self, index: int | slice) -> dict[str, Any] | CompactHistory:
        if isinstance(index, slice):
            result = CompactHistory()
            result._entries = [copy.deepcopy(value) if isinstance(value, dict) else value
                               for value in self._entries[index]]
            return result
        value = self._entries[index]
        if isinstance(value, bytes):
            value = self._unpack(value)
            self._entries[index] = value
        return value

    def __setitem__(self, index, value) -> None:
        if isinstance(index, slice):
            self._entries[index] = list(value)
        else:
            # Keep caller-owned mutable entries by identity, just as a list does.
            self._entries[index] = value

    def __delitem__(self, index) -> None:
        del self._entries[index]

    def insert(self, index: int, value: dict[str, Any]) -> None:
        self._entries.insert(index, value)

    def append_record(self, value: dict[str, Any]) -> None:
        """Store an application-owned completed record without retaining its graph."""
        self._entries.append(self._pack(value))

    def iter_records(self) -> Iterator[dict[str, Any]]:
        for value in self._entries:
            yield self._unpack(value)

    def copy(self) -> CompactHistory:
        return CompactHistory(self)

    def __copy__(self) -> CompactHistory:
        clone = CompactHistory()
        clone._entries = list(self._entries)
        return clone

    def __deepcopy__(self, memo: dict[int, Any]) -> CompactHistory:
        clone = CompactHistory()
        memo[id(self)] = clone
        clone._entries = [copy.deepcopy(record, memo) for record in self._entries]
        return clone

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (CompactHistory, list, tuple)):
            return NotImplemented
        records = other.iter_records() if isinstance(other, CompactHistory) else iter(other)
        return len(self) == len(other) and all(
            a == b for a, b in zip(self.iter_records(), records, strict=True))
