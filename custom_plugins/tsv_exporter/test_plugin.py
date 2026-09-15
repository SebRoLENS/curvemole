from pathlib import Path
from types import SimpleNamespace

import numpy as np

from curvemole import Curve
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project


def test_exported_values_and_header(tmp_path):
    manager = PluginManager()
    candidate = manager.discover_local(Path(__file__).parent)[0]
    manager.load(candidate, trust=True)
    try:
        project = Project()
        curve = Curve("Measurement", [1, 2, 3], [7, 8, 9])
        project.add_curve(curve)
        path = tmp_path / "result.tsv"
        context = SimpleNamespace(project=project, active_curve_id=curve.id, path=path)
        extensions.entries[candidate.metadata.identifier + ":tsv"].callback(context)
        assert path.read_text().splitlines()[0] == "x\ty"
        np.testing.assert_allclose(np.loadtxt(path, skiprows=1), [[1, 7], [2, 8], [3, 9]])
    finally:
        manager.disable(candidate.metadata.identifier)
