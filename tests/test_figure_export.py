from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Project
from curvemole.core import figure_export
from curvemole.core.data import CurveState
from curvemole.core.figure_export import PlotSnapshot, PlotTrace, export_plot_snapshot
from curvemole.core.registry import default_registry


def _snapshot(project, curves=None, **options):
    return figure_export._snapshot_for_curves(
        project.curves if curves is None else curves, project.models,
        registry=default_registry(), parameter_values=project.resolved_parameter_values(),
        include_components=options.get("include_components", True),
        include_residuals=options.get("include_residuals", True),
        include_error_bars=options.get("include_error_bars", True), theme="light",
    )


def _project():
    project = Project("Spectral analysis")
    curve = Curve("Band A", [3., 1., 2., 4.], [5., 3., 4., 10.], sigma_y=[.1, .2, .3, .4],
                  x_label="Energy", x_unit="eV", y_label="Intensity", y_unit="counts")
    project.add_curve(curve)
    model = project.model_for(curve.id)
    background = Component.create("constant", name="Baseline", initial={"offset": 2.})
    background.is_background = True
    peak = Component.create("linear", name="Signal", initial={"intercept": 0., "slope": 1.})
    model.add(background)
    model.add(peak)
    return project, curve, model, background, peak


def test_scientific_export_uses_smooth_model_and_raw_unmasked_residuals():
    project, curve, model, _background, _peak = _project()
    curve.masks["Default"].excluded[3] = True
    snapshot = _snapshot(project)
    total = next(trace for trace in snapshot.traces if trace.kind == "fit")
    assert len(total.x) >= 650
    assert np.all(np.diff(total.x) > 0)
    np.testing.assert_allclose(total.y, model.evaluate(total.x))
    np.testing.assert_allclose(snapshot.residuals[0].x, [3., 1., 2.])
    np.testing.assert_allclose(snapshot.residuals[0].y, [0., 0., 0.])
    assert "counts" in snapshot.residual_label
    assert snapshot.x_label == "Energy [eV]"
    excluded = next(trace for trace in snapshot.traces if trace.kind == "masked")
    np.testing.assert_allclose(excluded.x, [4.])
    assert "3 included; 1 excluded" in snapshot.caption


def test_smooth_components_include_composed_background_and_subtract_sign():
    project, _curve, model, background, peak = _project()
    peak.operator = "subtract"
    multiplier = Component.create("constant", name="Scale", initial={"offset": 3.}, operator="multiply")
    model.add(multiplier)
    snapshot = _snapshot(project)
    total = next(trace for trace in snapshot.traces if trace.kind == "fit")
    signal = next(trace for trace in snapshot.traces if trace.kind == "component" and "Signal" in trace.label)
    baseline = next(trace for trace in snapshot.traces if trace.kind == "background")
    np.testing.assert_allclose(signal.y, (2. - total.x) * 3.)
    np.testing.assert_allclose(total.y, signal.y)
    np.testing.assert_allclose(baseline.y, 6.)
    assert signal.label == "Background - Signal"
    assert all("Scale" not in trace.label for trace in snapshot.traces)
    assert "Global model operators applied: multiply: Scale" in snapshot.caption
    assert background.is_background


def test_single_curve_export_resolves_links_to_other_curves(tmp_path, monkeypatch):
    project, curve, _model, _background, peak = _project()
    second = Curve("Reference", [0., 1.], [0., 0.])
    project.add_curve(second)
    reference_model = project.model_for(second.id)
    reference = Component.create("constant", initial={"offset": 7.})
    reference_model.add(reference)
    peak.parameters["slope"].link = "${" + reference_model.parameter_path(second.id, reference.id, "offset") + "}"
    captured = []
    monkeypatch.setattr(figure_export, "export_plot_snapshot", lambda snapshot, path, **kwargs: captured.append(snapshot))
    figure_export.export_figure([curve], {curve.id: project.models[curve.id]}, tmp_path / "linked.svg",
                               parameter_values=project.resolved_parameter_values())
    total = next(trace for trace in captured[0].traces if trace.kind == "fit")
    np.testing.assert_allclose(total.y, 2. + 7. * total.x)


def test_snapshot_preserves_display_offsets_ranges_and_log_coordinates(tmp_path, monkeypatch):
    from curvemole.core import export as exporter

    seen = []
    original_release = exporter._release_export_figure

    def inspect(figure):
        axis, residual = figure.axes
        seen.append({"x": axis.lines[0].get_xdata(), "y": axis.lines[0].get_ydata(),
                     "xlim": axis.get_xlim(), "ylim": axis.get_ylim(), "rylim": residual.get_ylim(),
                     "xscale": axis.get_xscale(), "yscale": axis.get_yscale(),
                     "xlabel": residual.get_xlabel(), "spans": len(axis.patches)})
        original_release(figure)

    monkeypatch.setattr(exporter, "_release_export_figure", inspect)
    snapshot = PlotSnapshot(
        [PlotTrace("Visible, offset data", np.array([1., 10., 100.]), np.array([3., 30., 300.]),
                   line_style="-", marker=False)],
        residuals=[PlotTrace("Residual", np.array([1., 10., 100.]), np.array([-.2, .1, .3]), kind="residual")],
        x_label="Delay [s]", y_label="Displayed intensity", x_range=(2., 80.), y_range=(4., 250.),
        residual_range=(-1., 1.), log_x=True, log_y=True, title="Current screen",
        masked_ranges=[(4., 6.)],
    )
    destination = export_plot_snapshot(snapshot, tmp_path / "screen.svg")
    assert destination.read_text().startswith("<?xml")
    assert seen[0]["xscale"] == seen[0]["yscale"] == "log"
    np.testing.assert_allclose(seen[0]["x"], [1., 10., 100.])
    np.testing.assert_allclose(seen[0]["y"], [3., 30., 300.])
    np.testing.assert_allclose(seen[0]["xlim"], [2., 80.])
    np.testing.assert_allclose(seen[0]["ylim"], [4., 250.])
    np.testing.assert_allclose(seen[0]["rylim"], [-1., 1.])
    assert seen[0]["spans"] == 1 and seen[0]["xlabel"] == "Delay [s]"


def test_pdf_pages_are_vector_one_per_curve_and_never_borrow_fit_statistics(tmp_path, monkeypatch):
    from matplotlib.backends.backend_pdf import PdfPages

    project, curve, model, _background, _peak = _project()
    curve.state = CurveState.FITTED
    fitted = Fitter().fit_single(curve, model)
    project.results["last_fit"] = fitted
    second = Curve("Unrelated spectrum", [0., 1., 2.], [5., 6., 7.])
    second.state = CurveState.FITTED
    project.add_curve(second)
    pages = []
    original_save = PdfPages.savefig

    def save(pdf, figure, **kwargs):
        pages.append({"title": figure.axes[0].get_title(loc="left"),
                      "text": " ".join(text.get_text() for text in figure.texts),
                      "images": sum(len(axis.images) for axis in figure.axes)})
        original_save(pdf, figure, **kwargs)

    monkeypatch.setattr(PdfPages, "savefig", save)
    path = figure_export.generate_pdf_report(project, tmp_path / "report.pdf", result=fitted)
    assert path.read_bytes().startswith(b"%PDF-")
    assert [page["title"] for page in pages] == ["Band A", "Unrelated spectrum"]
    assert all(page["images"] == 0 for page in pages)
    assert "RMSE" in pages[0]["text"]
    assert "RMSE" not in pages[1]["text"]
    assert all("RRID:SCR_029214" in page["text"] for page in pages)


def test_pdf_omits_statistics_after_model_parameters_change(tmp_path, monkeypatch):
    from matplotlib.backends.backend_pdf import PdfPages

    project, curve, model, _background, peak = _project()
    result = Fitter().fit_single(curve, model)
    curve.state = CurveState.FITTED
    peak.parameters["slope"].value += 1.
    text = []
    original_save = PdfPages.savefig

    def save(pdf, figure, **kwargs):
        text.extend(label.get_text() for label in figure.texts)
        original_save(pdf, figure, **kwargs)

    monkeypatch.setattr(PdfPages, "savefig", save)
    figure_export.generate_pdf_report(project, tmp_path / "report.pdf", result=result)
    assert "RMSE" not in " ".join(text)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_empty_export_and_empty_pdf_are_valid(tmp_path, theme):
    figure_export.export_figure([], {}, tmp_path / f"empty-{theme}.png", theme=theme)
    path = figure_export.generate_pdf_report(Project("Empty project"), tmp_path / "empty.pdf")
    assert path.read_bytes().startswith(b"%PDF-")


@pytest.mark.parametrize("count", [20, 98])
def test_large_current_view_legends_stay_inside_canvas_without_dropping_traces(count):
    from curvemole.core.export import _export_figure, _release_export_figure

    traces = [PlotTrace(f"{index:02d}_very_long_spectrum_acquisition_name_with_pressure_and_other_details_" * 2,
                        np.array([1., 2., 3.]), np.array([index, index + 1., index + 2.]))
              for index in range(count)]
    figure = _export_figure(figsize=(9., 5.5), constrained_layout=True)
    try:
        axis, _ = figure_export._draw_snapshot(figure, PlotSnapshot(traces, title="Current view"))
        figure.canvas.draw()
        bounds = axis.get_legend().get_window_extent(figure.canvas.get_renderer())
        assert bounds.x0 >= 0 and bounds.y0 >= 0
        assert bounds.x1 <= figure.bbox.width and bounds.y1 <= figure.bbox.height
        assert len(axis.lines) == count
        if count > 20:
            assert [text.get_text() for text in axis.get_legend().get_texts()] == ["Data (98 traces)"]
            assert any("98 visible traces; legend grouped by role" in text.get_text() for text in figure.texts)
    finally:
        _release_export_figure(figure)
