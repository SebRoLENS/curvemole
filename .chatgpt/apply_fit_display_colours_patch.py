from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:140]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Shared colour policy: model sum is reserved red; spectra use non-red palettes.
Path("src/curvemole/gui/colours.py").write_text(
    '''"""Colour policy shared by CurveMole spectrum and model rendering."""\n\nfrom __future__ import annotations\n\nimport colorsys\n\nMODEL_SUM_COLOUR = "#D62728"\nDEFAULT_SERIES_PALETTE = "Colourblind"\nSERIES_PALETTES: dict[str, tuple[str, ...]] = {\n    "Colourblind": (\n        "#0072B2", "#009E73", "#CC79A7", "#E69F00",\n        "#56B4E9", "#F0E442", "#332288", "#88CCEE",\n    ),\n    "Ocean": (\n        "#003F5C", "#2F4B7C", "#007C91", "#00A6A6",\n        "#4C78A8", "#72B7B2", "#5B8FF9", "#6C5CE7",\n    ),\n    "Viridis": (\n        "#440154", "#482878", "#3E4989", "#31688E", "#26828E",\n        "#1F9E89", "#6CCE59", "#B6DE2B", "#FDE725",\n    ),\n    "Pastel": (\n        "#6BAED6", "#74C476", "#9E9AC8", "#9ECAE1",\n        "#A1D99B", "#BCBDDC", "#FDD0A2", "#BDBDBD",\n    ),\n    "Grayscale": (\n        "#111111", "#333333", "#555555", "#777777",\n        "#999999", "#BBBBBB", "#DDDDDD",\n    ),\n}\n\n\ndef spectrum_colour_allowed(value: str) -> bool:\n    """Return False for saturated red hues reserved for the model sum."""\n\n    text = value.strip().lstrip("#")\n    if len(text) != 6:\n        return False\n    try:\n        red, green, blue = (int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))\n    except ValueError:\n        return False\n    hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)\n    degrees = hue * 360.0\n    return not (saturation >= 0.25 and (degrees <= 15.0 or degrees >= 345.0))\n''',
    encoding="utf-8",
)

# main_window.py: colour menus, fit-result commit on GUI state, non-red default palette.
path = "src/curvemole/gui/main_window.py"
replace_once(
    path,
    '''    QApplication,\n    QDockWidget,\n    QFileDialog,\n''',
    '''    QApplication,\n    QColorDialog,\n    QDockWidget,\n    QFileDialog,\n''',
)
replace_once(
    path,
    '''    QMainWindow,\n    QMessageBox,\n''',
    '''    QMainWindow,\n    QMenu,\n    QMessageBox,\n''',
)
replace_once(
    path,
    '''from curvemole.gui.dialogs import (\n''',
    '''from curvemole.gui.colours import (\n    DEFAULT_SERIES_PALETTE,\n    SERIES_PALETTES,\n    spectrum_colour_allowed,\n)\nfrom curvemole.gui.dialogs import (\n''',
)
replace_once(
    path,
    '''PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442"]\n''',
    '''PALETTE = list(SERIES_PALETTES[DEFAULT_SERIES_PALETTE])\n''',
)
replace_once(
    path,
    '''class CurveTree(QTreeWidget):\n    activeCurveChanged = Signal(object)\n    curveVisibilityChanged = Signal(str, bool)\n    curveRenamed = Signal(str, str)\n''',
    '''class CurveTree(QTreeWidget):\n    activeCurveChanged = Signal(object)\n    curveVisibilityChanged = Signal(str, bool)\n    curveRenamed = Signal(str, str)\n    curveColourRequested = Signal(str)\n    seriesPaletteRequested = Signal(str, str)\n''',
)
replace_once(
    path,
    '''        self._updating = False\n        self.currentItemChanged.connect(self._active_changed)\n        self.itemChanged.connect(self._item_changed)\n''',
    '''        self._updating = False\n        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)\n        self.customContextMenuRequested.connect(self._show_context_menu)\n        self.currentItemChanged.connect(self._active_changed)\n        self.itemChanged.connect(self._item_changed)\n''',
)
replace_once(
    path,
    '''    def _active_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:\n''',
    '''    def _show_context_menu(self, position: Any) -> None:\n        item = self.itemAt(position)\n        if item is None:\n            return\n        metadata = item.data(1, Qt.ItemDataRole.UserRole)\n        if not metadata:\n            return\n        menu = QMenu(self)\n        if metadata[0] == "curve":\n            curve_id = str(metadata[1])\n            colour_action = menu.addAction(self.tr("Choose spectrum colour…"))\n            colour_action.triggered.connect(\n                lambda checked=False, curve_id=curve_id: self.curveColourRequested.emit(curve_id)\n            )\n        elif metadata[0] == "series":\n            series_id = str(metadata[1])\n            palette_menu = menu.addMenu(self.tr("Series palette"))\n            for palette_name in SERIES_PALETTES:\n                action = palette_menu.addAction(palette_name)\n                action.triggered.connect(\n                    lambda checked=False, series_id=series_id, palette_name=palette_name: (\n                        self.seriesPaletteRequested.emit(series_id, palette_name)\n                    )\n                )\n        if not menu.isEmpty():\n            menu.exec(self.viewport().mapToGlobal(position))\n\n    def _active_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:\n''',
)
replace_once(
    path,
    '''        self.curve_tree.curveVisibilityChanged.connect(self._set_visibility)\n        self.curve_tree.curveRenamed.connect(self._rename_curve)\n''',
    '''        self.curve_tree.curveVisibilityChanged.connect(self._set_visibility)\n        self.curve_tree.curveRenamed.connect(self._rename_curve)\n        self.curve_tree.curveColourRequested.connect(self.choose_curve_colour)\n        self.curve_tree.seriesPaletteRequested.connect(self.apply_series_palette)\n''',
)
replace_once(
    path,
    '''        series = Series(self.tr("Imported series"))\n        shared_mapping = None\n''',
    '''        series = Series(self.tr("Imported series"))\n        series.metadata["palette"] = DEFAULT_SERIES_PALETTE\n        shared_mapping = None\n''',
)
replace_once(
    path,
    '''    def _fit_finished(self, result: FitResult) -> None:\n        self.project.results["last_attempt"] = result\n''',
    '''    def _apply_fit_result_to_project(self, result: FitResult) -> None:\n        # Fitting runs in a worker thread. Commit the returned estimates explicitly\n        # to the GUI-side project so the redraw never depends on worker-side mutation.\n        if result.success:\n            fitted_curve_ids = set(result.curve_outputs) or {\n                path.split(".", 1)[0] for path in result.parameters\n            }\n        elif result.paused_curve_id:\n            fitted_curve_ids = set(result.curve_outputs)\n        else:\n            fitted_curve_ids = set()\n        if not fitted_curve_ids:\n            return\n\n        parameter_map = self.project.parameter_map()\n        for path, estimate in result.parameters.items():\n            curve_id = path.split(".", 1)[0]\n            if curve_id not in fitted_curve_ids or path not in parameter_map:\n                continue\n            parameter = parameter_map[path]\n            parameter.value = float(estimate.value)\n            parameter.standard_error = estimate.standard_error\n            parameter.ci_low = estimate.ci_low\n            parameter.ci_high = estimate.ci_high\n        for curve_id in fitted_curve_ids:\n            try:\n                self.project.dataset.curve(curve_id).state = CurveState.FITTED\n            except KeyError:\n                continue\n\n    def _fit_finished(self, result: FitResult) -> None:\n        self._apply_fit_result_to_project(result)\n        self.project.results["last_attempt"] = result\n''',
)
replace_once(
    path,
    '''    def _set_visibility(self, curve_id: str, visible: bool) -> None:\n        curve = self.project.dataset.curve(curve_id)\n''',
    '''    def _set_curve_colour(self, curve_id: str, colour: str) -> None:\n        curve = self.project.dataset.curve(curve_id)\n        curve.colour = colour.upper()\n        self.project.touch()\n        self.refresh_all()\n\n    def choose_curve_colour(self, curve_id: str) -> None:\n        if not self._ensure_editable():\n            return\n        curve = self.project.dataset.curve(curve_id)\n        while True:\n            selected = QColorDialog.getColor(\n                QColor(curve.colour),\n                self,\n                self.tr("Choose spectrum colour"),\n            )\n            if not selected.isValid():\n                return\n            colour = selected.name(QColor.NameFormat.HexRgb).upper()\n            if spectrum_colour_allowed(colour):\n                break\n            QMessageBox.warning(\n                self,\n                self.tr("Reserved colour"),\n                self.tr(\n                    "Red is reserved for the Model sum so spectra and fitted-model curves can never use the same colour. Choose another spectrum colour."\n                ),\n            )\n        old = curve.colour.upper()\n        if colour == old:\n            return\n        self.undo_stack.push(\n            CallbackCommand(\n                self.tr("Change spectrum colour"),\n                lambda: self._set_curve_colour(curve_id, colour),\n                lambda: self._set_curve_colour(curve_id, old),\n            )\n        )\n\n    def apply_series_palette(self, series_id: str, palette_name: str) -> None:\n        if not self._ensure_editable():\n            return\n        palette = SERIES_PALETTES.get(palette_name)\n        if not palette:\n            return\n        series = next((item for item in self.project.dataset.series if item.id == series_id), None)\n        if series is None:\n            return\n        before_colours = [curve.colour for curve in series.curves]\n        before_palette = series.metadata.get("palette")\n        after_colours = [palette[index % len(palette)] for index in range(len(series.curves))]\n\n        def restore(colours: list[str], marker: Any) -> None:\n            for curve, colour in zip(series.curves, colours, strict=True):\n                curve.colour = colour.upper()\n            if marker is None:\n                series.metadata.pop("palette", None)\n            else:\n                series.metadata["palette"] = marker\n            self.project.touch()\n            self.refresh_all()\n\n        self.undo_stack.push(\n            CallbackCommand(\n                self.tr("Change series palette"),\n                lambda: restore(after_colours, palette_name),\n                lambda: restore(before_colours, before_palette),\n            )\n        )\n\n    def _set_visibility(self, curve_id: str, visible: bool) -> None:\n        curve = self.project.dataset.curve(curve_id)\n''',
)

# plot.py: fixed reserved red for every model sum.
path = "src/curvemole/gui/plot.py"
replace_once(
    path,
    '''from curvemole.core.models import component_height\n''',
    '''from curvemole.core.models import component_height\nfrom curvemole.gui.colours import MODEL_SUM_COLOUR\n''',
)
replace_once(
    path,
    '''                self.plot.plot(x, total, pen=pg.mkPen("#D55E00", width=2.1), name=f"{curve.name} fit")\n''',
    '''                self.plot.plot(\n                    x,\n                    total,\n                    pen=pg.mkPen(MODEL_SUM_COLOUR, width=2.2),\n                    name=f"{curve.name} Model sum",\n                )\n''',
)

# Manual: explain fitted redraw and colour controls.
path = "docs/manual.md"
replace_once(
    path,
    '''After a successful fit, the model line and residual panel update. Parameter standard\nerrors appear in the `±1 sigma` column when covariance is available. Open\n''',
    '''After a successful fit, CurveMole commits the optimized parameter values back into\nthe displayed model and immediately redraws the model sum, individual components, and\nresidual panel. Parameter standard errors appear in the `±1 sigma` column when covariance\nis available. Open\n''',
)
replace_once(
    path,
    '''- Double-click an editable name to rename a series or curve.\n- Use the search field to filter curves by name without removing them.\n''',
    '''- Double-click an editable name to rename a series or curve.\n- Right-click a **curve** and choose **Choose spectrum colour…** to set its colour. Red is\n  reserved for the fitted Model sum and cannot be assigned to a spectrum.\n- Right-click a **series** and choose **Series palette** to recolour the complete series\n  with one of the built-in non-red palettes. Palette and individual colours are saved in\n  the project.\n- Use the search field to filter curves by name without removing them.\n''',
)
replace_once(
    path,
    '''fit, CurveMole redraws and auto-ranges the plot so the newly fitted model is visible\nimmediately.\n''',
    '''fit, CurveMole explicitly applies the returned optimized parameters to the displayed\nmodel, redraws and auto-ranges the plot so the newly fitted curves are visible immediately.\nThe **Model sum is always red**; imported spectra and selectable series palettes exclude red\nso a data curve can never be confused with the fitted sum.\n''',
)

# Regression tests for fit-result display and colour policy.
Path("tests/test_fit_display_and_colours.py").write_text(
    '''from __future__ import annotations\n\nimport numpy as np\nimport pytest\n\npytest.importorskip("PySide6", exc_type=ImportError)\npytest.importorskip("pyqtgraph", exc_type=ImportError)\n\nfrom PySide6.QtGui import QColor\nfrom PySide6.QtWidgets import QApplication, QColorDialog\n\nfrom curvemole import Component, Curve, Project\nfrom curvemole.core.data import CurveState, Series\nfrom curvemole.core.fitting import FitSettings, Fitter\nfrom curvemole.gui.colours import (\n    MODEL_SUM_COLOUR,\n    SERIES_PALETTES,\n    spectrum_colour_allowed,\n)\nfrom curvemole.gui.main_window import MainWindow, PALETTE\n\n\ndef _gaussian_project() -> tuple[Project, Curve, Component]:\n    x = np.linspace(-5.0, 5.0, 301)\n    sigma = 0.75\n    y = 2.4 * np.exp(-0.5 * ((x - 0.65) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))\n    curve = Curve("spectrum", x, y)\n    project = Project("fit display")\n    project.add_curve(curve)\n    component = Component.create(\n        "gaussian", initial={"area": 1.0, "center": -1.0, "sigma": 1.5}\n    )\n    project.model_for(curve.id).add(component)\n    project.dirty = False\n    return project, curve, component\n\n\ndef test_fit_finished_commits_returned_estimates_to_displayed_model() -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, component = _gaussian_project()\n    window = MainWindow(project)\n    model = project.model_for(curve.id)\n    result = Fitter(window.registry).fit_single(\n        curve, model, FitSettings(max_nfev=4000)\n    )\n    assert result.success\n\n    # Simulate the GUI holding the pre-fit values when the worker result arrives.\n    component.parameters["area"].value = 1.0\n    component.parameters["center"].value = -1.0\n    component.parameters["sigma"].value = 1.5\n    window._fit_finished(result)\n\n    for path, estimate in result.parameters.items():\n        assert project.parameter_map()[path].value == pytest.approx(estimate.value)\n    rendered = model.evaluate(\n        curve.x,\n        curve_id=curve.id,\n        values=project.resolved_parameter_values(),\n        registry=window.registry,\n    )\n    output = result.curve_outputs[curve.id]\n    np.testing.assert_allclose(rendered[output.indices], output.fitted, rtol=1e-9, atol=1e-11)\n    assert curve.state == CurveState.FITTED\n    project.dirty = False\n    window.close()\n    app.processEvents()\n\n\ndef test_model_sum_red_is_reserved_from_all_builtin_spectrum_palettes() -> None:\n    assert MODEL_SUM_COLOUR.upper() == "#D62728"\n    assert not spectrum_colour_allowed(MODEL_SUM_COLOUR)\n    assert all(spectrum_colour_allowed(colour) for colours in SERIES_PALETTES.values() for colour in colours)\n    assert all(colour.upper() != MODEL_SUM_COLOUR.upper() for colour in PALETTE)\n\n\ndef test_series_palette_changes_colours_without_invalidating_fits() -> None:\n    app = QApplication.instance() or QApplication([])\n    project = Project("palette")\n    series = Series("series")\n    for index in range(4):\n        curve = Curve(f"curve {index}", [0.0, 1.0], [float(index), float(index + 1)])\n        curve.state = CurveState.FITTED\n        series.add(curve)\n    project.add_series(series)\n    project.dirty = False\n    window = MainWindow(project)\n    window.apply_series_palette(series.id, "Ocean")\n    expected = list(SERIES_PALETTES["Ocean"][:4])\n    assert [curve.colour for curve in series.curves] == expected\n    assert all(curve.state == CurveState.FITTED for curve in series.curves)\n    assert series.metadata["palette"] == "Ocean"\n    window.undo_stack.undo()\n    assert all(curve.state == CurveState.FITTED for curve in series.curves)\n    project.dirty = False\n    window.close()\n    app.processEvents()\n\n\ndef test_individual_spectrum_colour_picker_changes_non_red_colour(\n    monkeypatch: pytest.MonkeyPatch,\n) -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, _ = _gaussian_project()\n    curve.state = CurveState.FITTED\n    project.dirty = False\n    window = MainWindow(project)\n    monkeypatch.setattr(\n        QColorDialog,\n        "getColor",\n        lambda *args, **kwargs: QColor("#3455AA"),\n    )\n    window.choose_curve_colour(curve.id)\n    assert curve.colour == "#3455AA"\n    assert curve.state == CurveState.FITTED\n    project.dirty = False\n    window.close()\n    app.processEvents()\n''',
    encoding="utf-8",
)
