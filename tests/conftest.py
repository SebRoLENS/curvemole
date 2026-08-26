from __future__ import annotations

import os

import numpy as np
import pytest

from curvemole import Curve

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/curvemole-matplotlib")


@pytest.fixture
def gaussian_curve() -> Curve:
    x = np.linspace(-5, 5, 501)
    sigma = 0.8
    y = 3.0 * np.exp(-0.5 * ((x - 0.7) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi)) + 0.15
    rng = np.random.default_rng(42)
    return Curve("Gaussian", x, y + rng.normal(0, 0.005, len(x)), sigma_y=np.full_like(x, 0.005))
