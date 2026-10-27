"""Block diagonal fit matrices; dense conversion is an explicit consumer choice."""
from __future__ import annotations

import numpy as np


class BlockDiagonalMatrix:
    def __init__(self, blocks):
        self.blocks = tuple(np.asarray(block, dtype=float) for block in blocks)
        if any(block.ndim != 2 or block.shape[0] != block.shape[1] for block in self.blocks):
            raise ValueError("Covariance blocks must be square")
        self.offsets = np.cumsum([0, *(len(block) for block in self.blocks)])
        size = int(self.offsets[-1])
        self.shape = (size, size)
        self.ndim = 2
        self.dtype = np.dtype(float)

    def __len__(self):
        return self.shape[0]

    def __iter__(self):
        for start, block in zip(self.offsets, self.blocks, strict=False):
            for values in block:
                row = np.zeros(len(self))
                row[start:start + len(block)] = values
                yield row

    def __array__(self, dtype=None, copy=None):
        result = np.zeros(self.shape, dtype=dtype or float)
        for start, block in zip(self.offsets, self.blocks, strict=False):
            result[start:start + len(block), start:start + len(block)] = block
        return result

    def submatrix(self, indices):
        indices = np.asarray(indices, dtype=int)
        if np.any(indices < 0) or np.any(indices >= len(self)):
            raise IndexError("Matrix index out of bounds")
        result = np.zeros((len(indices), len(indices)))
        block_ids = np.searchsorted(self.offsets[1:], indices, side="right")
        for identity in np.unique(block_ids):
            start, block = self.offsets[identity], self.blocks[identity]
            positions = np.flatnonzero(block_ids == identity)
            local = indices[positions] - start
            result[np.ix_(positions, positions)] = block[np.ix_(local, local)]
        return result

    def to_dict(self):
        return {"block_diagonal": [block.tolist() for block in self.blocks]}

    def tolist(self):
        return [row.tolist() for row in self]


def matrix_from_value(value):
    if value is None or isinstance(value, BlockDiagonalMatrix):
        return value
    if isinstance(value, dict) and "block_diagonal" in value:
        return BlockDiagonalMatrix(value["block_diagonal"])
    return np.asarray(value, dtype=float)


def matrix_payload(value):
    if value is None:
        return None
    return value.to_dict() if isinstance(value, BlockDiagonalMatrix) else value.tolist()


def save_matrix(path, matrix, delimiter):
    """Write rows without materialising an aggregate dense covariance."""
    with path.open("w", encoding="utf-8") as stream:
        for row in matrix:
            np.savetxt(stream, np.asarray(row)[None, :], delimiter=delimiter)


def covariance_statistics(covariance):
    """Shared marginal errors/correlation, with the historical zero-variance policy."""
    errors = np.sqrt(np.clip(np.diag(covariance), 0, np.inf))
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = covariance / np.outer(errors, errors)
    np.fill_diagonal(correlation, 1.0)
    return errors, correlation
