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


def test_standalone_graphic_exports_do_not_load_pyplot_or_gui_managers(tmp_path) -> None:
    script = """
from pathlib import Path
import sys
from curvemole import Curve, Project
from curvemole.core.export import export_figure, generate_pdf_report
project = Project('Standalone exports')
project.add_curve(Curve('Data', [0., 1.], [1., 2.]))
directory = Path(sys.argv[1])
for suffix in ('png', 'svg'):
    export_figure(project.curves, project.models, directory / ('plot.' + suffix))
generate_pdf_report(project, directory / 'report.pdf')
assert 'matplotlib.pyplot' not in sys.modules
from matplotlib._pylab_helpers import Gcf
assert not Gcf.get_all_fig_managers()
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True,
                   env=dict(os.environ), timeout=60)


@pytest.mark.parametrize("backend", ["svg", "QtAgg"])
def test_worker_exports_preserve_caller_backend_and_existing_figures(tmp_path, backend) -> None:
    script = """
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from curvemole import Curve, Project
from curvemole.core.export import export_figure, generate_pdf_report
import matplotlib
backend = sys.argv[2]
if backend == 'QtAgg':
    from PySide6.QtWidgets import QApplication
    application = QApplication([])
matplotlib.use(backend)
from matplotlib import pyplot
existing = pyplot.figure()
canvas = existing.canvas
identifiers = pyplot.get_fignums()
project = Project('Worker exports')
project.add_curve(Curve('Data', [0., 1.], [1., 2.]))
directory = Path(sys.argv[1])
def export():
    export_figure(project.curves, project.models, directory / 'plot.png')
    generate_pdf_report(project, directory / 'report.pdf')
with ThreadPoolExecutor(max_workers=1) as pool:
    pool.submit(export).result(timeout=30)
assert matplotlib.get_backend().lower() == backend.lower()
assert pyplot.get_fignums() == identifiers
assert pyplot.figure(existing.number) is existing
assert existing.canvas is canvas
later = pyplot.figure()
assert type(later.canvas) is type(canvas)
pyplot.close('all')
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path), backend], check=True,
                   env=dict(os.environ), timeout=60)


def test_failed_graphic_exports_close_figures_and_remove_temporary_files(tmp_path, monkeypatch) -> None:
    from matplotlib import pyplot
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    from curvemole.core import export as exporter

    project = Project("report")
    project.add_curve(Curve("example", [0., 1.], [1., 2.]))
    existing = set(pyplot.get_fignums())
    figures = []
    original_figure = exporter._export_figure

    def capture_figure(**kwargs):
        figure = original_figure(**kwargs)
        figures.append(figure)
        return figure

    monkeypatch.setattr(exporter, "_export_figure", capture_figure)

    def fail(*args, **kwargs):
        raise OSError("test write failure")

    with monkeypatch.context() as patch:
        patch.setattr(Figure, "savefig", fail)
        with pytest.raises(OSError, match="test write failure"):
            export_figure(project.curves, project.models, tmp_path / "plot.png")
    assert set(pyplot.get_fignums()) == existing
    assert all(not figure.axes and figure.canvas is None for figure in figures)

    sentinel = tmp_path / "report.plot.tmp.png"
    sentinel.write_bytes(b"user file")
    monkeypatch.setattr(PdfPages, "savefig", fail)
    with pytest.raises(OSError, match="test write failure"):
        generate_pdf_report(project, tmp_path / "report.pdf")
    assert set(pyplot.get_fignums()) == existing
    assert all(not figure.axes and figure.canvas is None for figure in figures)
    assert not list(tmp_path.glob(".curvemole-report-*"))
    assert sentinel.read_bytes() == b"user file"


def test_pdf_report_does_not_allocate_an_embedded_raster(tmp_path, monkeypatch) -> None:
    from matplotlib.axes import Axes

    project = Project("report")
    project.add_curve(Curve("example", [0., 1.], [1., 2.]))

    def unexpected_raster(*args, **kwargs):
        raise AssertionError("PDF reports must draw vector traces without an intermediate raster")

    monkeypatch.setattr(Axes, "imshow", unexpected_raster)
    destination = generate_pdf_report(project, tmp_path / "report.pdf")
    assert destination.read_bytes().startswith(b"%PDF-")
