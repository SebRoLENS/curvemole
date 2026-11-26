"""Functional check named so that pytest does not collect it from tests/."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from curvemole import Curve
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project


def test_exports_values(tmp_path):
    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    try:
        project = Project()
        curve = Curve("Measurement", [1, 2], [3, 4])
        project.add_curve(curve)
        path = tmp_path / "out.tsv"
        context = SimpleNamespace(project=project, active_curve_id=curve.id, path=path)
        extensions.entries[candidate.metadata.identifier + ":xy"].callback(context)
        np.testing.assert_allclose(np.loadtxt(path, skiprows=1), [[1, 3], [2, 4]])
    finally:
        manager.disable(candidate.metadata.identifier)
