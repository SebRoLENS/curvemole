from __future__ import annotations

import os
import subprocess
import sys

import pytest

from curvemole import Curve, Project
from curvemole.core.export import export_figure, generate_pdf_report


def test_gui_startup_and_table_exports_do_not_import_matplotlib(tmp_path) -> None:
    # A fresh interpreter matters: other export tests may have loaded pyplot.
    subprocess.run([
        sys.executable, "-c",
        "import sys; from curvemole.gui.app import CurveMoleMainWindow; "
        "from curvemole.core.export import export_dataframe; import pandas as pd; "
        "export_dataframe(pd.DataFrame({'x':[1.]}), sys.argv[1]); "
        "assert not any(m == 'matplotlib' or m.startswith('matplotlib.') for m in sys.modules)",
        str(tmp_path / "table.csv"),
    ], check=True, env=dict(os.environ))


def test_failed_graphic_exports_close_figures_and_remove_temporary_files(tmp_path, monkeypatch) -> None:
    from matplotlib import pyplot
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    project = Project("report")
    project.add_curve(Curve("example", [0., 1.], [1., 2.]))
    existing = set(pyplot.get_fignums())

    def fail(*args, **kwargs):
        raise OSError("test write failure")

    with monkeypatch.context() as patch:
        patch.setattr(Figure, "savefig", fail)
        with pytest.raises(OSError, match="test write failure"):
            export_figure(project.curves, project.models, tmp_path / "plot.png")
    assert set(pyplot.get_fignums()) == existing

    sentinel = tmp_path / "report.plot.tmp.png"
    sentinel.write_bytes(b"user file")
    monkeypatch.setattr(PdfPages, "savefig", fail)
    with pytest.raises(OSError, match="test write failure"):
        generate_pdf_report(project, tmp_path / "report.pdf")
    assert set(pyplot.get_fignums()) == existing
    assert not list(tmp_path.glob(".curvemole-report-*"))
    assert sentinel.read_bytes() == b"user file"


def test_pdf_report_keeps_embedded_raster_as_byte_pixels(tmp_path, monkeypatch) -> None:
    import numpy as np
    from matplotlib.axes import Axes

    project = Project("report")
    project.add_curve(Curve("example", [0., 1.], [1., 2.]))
    original_imshow = Axes.imshow
    dtypes = []

    def imshow(axis, pixels, *args, **kwargs):
        dtypes.append(pixels.dtype)
        return original_imshow(axis, pixels, *args, **kwargs)

    monkeypatch.setattr(Axes, "imshow", imshow)
    destination = generate_pdf_report(project, tmp_path / "report.pdf")
    assert destination.read_bytes().startswith(b"%PDF-")
    assert dtypes == [np.uint8]
