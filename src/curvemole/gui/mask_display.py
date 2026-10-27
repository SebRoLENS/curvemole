"""Masked-run utilities and compatibility access to the canonical renderer."""
from __future__ import annotations

import numpy as np


def _true_runs(mask: np.ndarray) -> list[np.ndarray]:
    """Return contiguous runs of true indices without copying source data."""
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    split_at = np.flatnonzero(np.diff(indices) > 1) + 1
    return [run for run in np.split(indices, split_at) if run.size]


def _render_masked_samples(workspace):
    """Compatibility entry point; rendering belongs to RenderController."""
    from curvemole.gui.background_navigation import _masked_sample_renderer
    _masked_sample_renderer(workspace)
