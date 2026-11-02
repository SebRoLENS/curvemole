"""Dependency-aware derivatives and bounded-memory covariance reductions."""
from __future__ import annotations

import numpy as np

from curvemole.core.expressions import SafeExpression


def residual_sparsity(curves, models, parameters, free_paths, data):
    """Conservatively include equality and relational-link dependencies."""
    if len(curves) < 2 or len(free_paths) < 16:
        return None
    from scipy import sparse
    free = {path: index for index, path in enumerate(free_paths)}
    dependencies = {}

    def columns(path):
        if path not in dependencies:
            parameter = parameters[path]
            result = {free[path]} if path in free else set()
            if parameter.link:
                for source in SafeExpression.compile(parameter.link).references:
                    result.update(columns(source))
            dependencies[path] = result
        return dependencies[path]

    layout = []
    for curve in curves:
        selected = set()
        for path in models[curve.id].parameter_map(curve.id):
            if path in parameters:
                selected.update(columns(path))
        selected = sorted(selected)
        rows = len(data[curve.id][0])
        layout.append((rows, selected))
    total_rows = sum(rows for rows, _ in layout)
    nonzero = sum(rows * len(selected) for rows, selected in layout)
    if nonzero >= .5 * total_rows * len(free_paths):
        return None
    blocks = []
    for rows, selected in layout:
        if selected:
            indices = np.tile(selected, rows)
            indptr = np.arange(rows + 1) * len(selected)
            block = sparse.csr_matrix((np.ones(len(indices), dtype=bool), indices, indptr),
                                      shape=(rows, len(free_paths)))
        else:
            block = sparse.csr_matrix((rows, len(free_paths)), dtype=bool)
        blocks.append(block)
    return sparse.vstack(blocks, format="csr")


def jacobian_svd(jacobian):
    from scipy import sparse
    if not sparse.issparse(jacobian):
        _, singular, vh = np.linalg.svd(jacobian, full_matrices=False)
        return singular, vh
    # Tall-skinny QR preserves singular values without forming J.T@J (which
    # squares the condition number) or materialising the full dense Jacobian.
    columns = jacobian.shape[1]
    reduced = np.empty((0, columns))
    chunk_rows = max(1024, 4 * columns)
    for start in range(0, jacobian.shape[0], chunk_rows):
        block = jacobian[start:start + chunk_rows].toarray()
        reduced = np.linalg.qr(np.vstack((reduced, block)), mode="r")
    _, singular, vh = np.linalg.svd(reduced, full_matrices=False)
    return singular, vh


def weighted_gram(jacobian, weights):
    from scipy import sparse
    if sparse.issparse(jacobian):
        return (jacobian.T @ jacobian.multiply(weights[:, None])).toarray()
    return jacobian.T @ (weights[:, None] * jacobian)
