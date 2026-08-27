from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# main_window.py: curve removal UI, systematic component names, and fit redraw.
path = "src/curvemole/gui/main_window.py"
replace_once(
    path,
    '''        self.select_all_curves_button = QPushButton(self.tr("Select all"))
        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))
        self.select_all_curves_button.clicked.connect(self.curve_tree.select_all_curves)
        self.deselect_all_curves_button.clicked.connect(self.curve_tree.deselect_all_curves)
        selection_row.addWidget(self.select_all_curves_button)
        selection_row.addWidget(self.deselect_all_curves_button)
        selection_row.addStretch(1)
''',
    '''        self.select_all_curves_button = QPushButton(self.tr("Select all"))
        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))
        self.remove_curves_button = QPushButton(self.tr("Remove selected"))
        self.remove_curves_button.setToolTip(
            self.tr("Remove the selected curve(s) from the project. This can be undone.")
        )
        self.select_all_curves_button.clicked.connect(self.curve_tree.select_all_curves)
        self.deselect_all_curves_button.clicked.connect(self.curve_tree.deselect_all_curves)
        self.remove_curves_button.clicked.connect(self.remove_selected_curves)
        selection_row.addWidget(self.select_all_curves_button)
        selection_row.addWidget(self.deselect_all_curves_button)
        selection_row.addWidget(self.remove_curves_button)
        selection_row.addStretch(1)
''',
)
replace_once(
    path,
    '''        self._load_custom_functions()
        self._restore_layout()
        self.refresh_all()
''',
    '''        self._load_custom_functions()
        self._normalise_component_names()
        self._restore_layout()
        self.refresh_all()
''',
)
replace_once(
    path,
    '''            self._load_custom_functions()
            self.refresh_all()
            self._notify(self.tr("Project opened."))
''',
    '''            self._load_custom_functions()
            self._normalise_component_names()
            self.refresh_all()
            self._notify(self.tr("Project opened."))
''',
)
replace_once(
    path,
    '''    def _commit_component(self, component: Component, curve_id: str) -> None:
        model = self.project.model_for(curve_id)
        before = model.to_dict()
        model.add(component)
''',
    '''    def _component_base_name(self, component: Component) -> str:
        definition = self.registry.get(component.function_id)
        base = re.sub(r"[\\W_]+", "", definition.display_name, flags=re.UNICODE)
        return base or "Function"

    def _assign_component_name(
        self,
        component: Component,
        model: Model,
        *,
        exclude_component_id: str | None = None,
    ) -> None:
        base = self._component_base_name(component)
        pattern = re.compile(rf"^{re.escape(base)}(\\d+)$")
        used: list[int] = []
        for existing in model.components:
            if existing.id == exclude_component_id or existing.function_id != component.function_id:
                continue
            match = pattern.fullmatch(existing.name)
            if match:
                used.append(int(match.group(1)))
        component.name = f"{base}{max(used, default=0) + 1}"

    def _normalise_component_names(self) -> None:
        for model in self.project.models.values():
            counters: dict[str, int] = {}
            for component in model.components:
                counters[component.function_id] = counters.get(component.function_id, 0) + 1
                component.name = (
                    f"{self._component_base_name(component)}{counters[component.function_id]}"
                )

    def _commit_component(self, component: Component, curve_id: str) -> None:
        model = self.project.model_for(curve_id)
        before = model.to_dict()
        self._assign_component_name(component, model)
        model.add(component)
''',
)
replace_once(
    path,
    '''    def duplicate_component(self, component_id: str) -> None:
        self._model_mutation(self.tr("Duplicate component"), lambda model: model.duplicate(component_id))
''',
    '''    def duplicate_component(self, component_id: str) -> None:
        created_id: list[str] = []

        def operation(model: Model) -> None:
            duplicate = model.duplicate(component_id)
            self._assign_component_name(
                duplicate, model, exclude_component_id=duplicate.id
            )
            created_id.append(duplicate.id)

        self._model_mutation(self.tr("Duplicate component"), operation)
        if created_id:
            self.selected_component_id = created_id[-1]
            self.refresh_all()
''',
)
replace_once(
    path,
    '''        self.resume_action.setEnabled(bool(result.paused_curve_id))
        self._paused_result = result if result.paused_curve_id else None
        self.refresh_all()
        if result.paused_curve_id:
            self.active_curve_id = result.paused_curve_id
            QMessageBox.warning(
''',
    '''        self.resume_action.setEnabled(bool(result.paused_curve_id))
        self._paused_result = result if result.paused_curve_id else None
        if result.paused_curve_id:
            self.active_curve_id = result.paused_curve_id
        self.refresh_all()
        if result.success or result.curve_outputs:
            self.plot_workspace.auto_range()
        if result.paused_curve_id:
            QMessageBox.warning(
''',
)
replace_once(
    path,
    '''    def _set_visibility(self, curve_id: str, visible: bool) -> None:
        curve = self.project.dataset.curve(curve_id)
''',
    '''    def remove_selected_curves(self) -> None:
        if not self._ensure_editable():
            return
        selected = self.curve_tree.selected_curve_ids()
        if not selected and self.active_curve_id:
            selected = {self.active_curve_id}
        if not selected:
            self._notify(self.tr("Select at least one curve to remove."), warning=True)
            return
        count = len(selected)
        question = (
            self.tr("Remove the selected curve? This action can be undone.")
            if count == 1
            else self.tr("Remove the selected curves? This action can be undone.")
        )
        if QMessageBox.question(self, self.tr("Remove curve"), question) != QMessageBox.StandardButton.Yes:
            return

        records: list[tuple[str, Series, int, Curve, dict[str, Any] | None, bool, Any]] = []
        for curve_id in selected:
            series = self.project.dataset.series_for(curve_id)
            curve = self.project.dataset.curve(curve_id)
            index = series.curves.index(curve)
            model = self.project.models.get(curve_id)
            model_state = model.to_dict() if model is not None else None
            had_result = curve_id in self.project.results
            result_value = copy.deepcopy(self.project.results.get(curve_id))
            records.append((curve_id, series, index, curve, model_state, had_result, result_value))
        active_before = self.active_curve_id

        def redo() -> None:
            for curve_id, *_ in records:
                try:
                    self.project.remove_curve(curve_id)
                except KeyError:
                    pass
            if self.active_curve_id in selected:
                self.active_curve_id = self.project.curves[0].id if self.project.curves else None
            self.selected_component_id = None

        def undo() -> None:
            for curve_id, series, index, curve, model_state, had_result, result_value in sorted(
                records, key=lambda item: item[2]
            ):
                if all(existing.id != curve_id for existing in series.curves):
                    series.add(curve, index)
                if model_state is not None:
                    self.project.models[curve_id] = Model.from_dict(copy.deepcopy(model_state))
                if had_result:
                    self.project.results[curve_id] = copy.deepcopy(result_value)
            self.active_curve_id = active_before if active_before else (self.project.curves[0].id if self.project.curves else None)
            self.selected_component_id = None

        self._push_change(
            self.tr("Remove curve") if count == 1 else self.tr("Remove curves"),
            redo,
            undo,
        )

    def _set_visibility(self, curve_id: str, visible: bool) -> None:
        curve = self.project.dataset.curve(curve_id)
''',
)
replace_once(
    path,
    '''        for curve_id in self.curve_tree.selected_curve_ids() or ({self.active_curve_id} if self.active_curve_id else set()):
            curve = self.project.dataset.curve(curve_id)
            if curve.state == CurveState.FITTED:
                curve.state = CurveState.MODIFIED
''',
    '''        for curve_id in self.curve_tree.selected_curve_ids() or ({self.active_curve_id} if self.active_curve_id else set()):
            try:
                curve = self.project.dataset.curve(curve_id)
            except KeyError:
                continue
            if curve.state == CurveState.FITTED:
                curve.state = CurveState.MODIFIED
''',
)

# panels.py: show the systematic component name without redundant type text.
replace_once(
    "src/curvemole/gui/panels.py",
    '''            for row, component in enumerate(model.components):
                definition = self.registry.get(component.function_id)
                label = f"{component.name}  ·  {definition.display_name}"
                if component.is_background:
''',
    '''            for row, component in enumerate(model.components):
                label = component.name
                if component.is_background:
''',
)

# plot.py: component labels, anti-overlap layout, and right-click visibility toggle.
path = "src/curvemole/gui/plot.py"
replace_once(
    path,
    '''from PySide6.QtGui import QColor, QKeySequence, QShortcut
''',
    '''from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
''',
)
replace_once(
    path,
    '''        self._component_items: dict[str, pg.PlotDataItem] = {}
        self._handles: list[Any] = []
''',
    '''        self._component_items: dict[str, pg.PlotDataItem] = {}
        self._component_labels: list[pg.TextItem] = []
        self._component_label_specs: list[tuple[pg.TextItem, float, float]] = []
        self._show_component_labels = True
        self._laying_out_labels = False
        self._handles: list[Any] = []
''',
)
replace_once(
    path,
    '''        self.plot = self.graphics.addPlot(row=0, col=0, viewBox=self.view_box)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.residual_plot = self.graphics.addPlot(row=1, col=0)
''',
    '''        self.plot = self.graphics.addPlot(row=0, col=0, viewBox=self.view_box)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        view_menu = self.view_box.getMenu(None)
        view_menu.addSeparator()
        self.component_labels_action = QAction(self.tr("Show component labels"), self)
        self.component_labels_action.setCheckable(True)
        self.component_labels_action.setChecked(True)
        self.component_labels_action.toggled.connect(self.set_component_labels_visible)
        view_menu.addAction(self.component_labels_action)
        self.residual_plot = self.graphics.addPlot(row=1, col=0)
''',
)
replace_once(
    path,
    '''        self.view_box.placementFinishRequested.connect(self.finish_placement)
        self.residual_toggle.toggled.connect(self.residual_plot.setVisible)
''',
    '''        self.view_box.placementFinishRequested.connect(self.finish_placement)
        self.view_box.sigRangeChanged.connect(self._layout_component_labels)
        self.residual_toggle.toggled.connect(self.residual_plot.setVisible)
''',
)
replace_once(
    path,
    '''        self._component_items.clear()
        self._handles.clear()
''',
    '''        self._component_items.clear()
        self._component_labels.clear()
        self._component_label_specs.clear()
        self._handles.clear()
''',
)
replace_once(
    path,
    '''                    self._component_items[component.id] = component_item
                if curve.id == self._active_curve_id and self._selected_component_id:
''',
    '''                    self._component_items[component.id] = component_item
                    if self._show_component_labels:
                        self._add_component_label(component.name, x, component_y)
                if curve.id == self._active_curve_id and self._selected_component_id:
''',
)
replace_once(
    path,
    '''        self._render_placement_preview()
        self.plot.setTitle("")

    def _add_component_handles(
''',
    '''        self._layout_component_labels()
        self._render_placement_preview()
        self.plot.setTitle("")

    def set_component_labels_visible(self, visible: bool) -> None:
        self._show_component_labels = bool(visible)
        if self.component_labels_action.isChecked() != self._show_component_labels:
            self.component_labels_action.blockSignals(True)
            self.component_labels_action.setChecked(self._show_component_labels)
            self.component_labels_action.blockSignals(False)
        self.refresh()

    def _add_component_label(self, name: str, x: np.ndarray, y: np.ndarray) -> None:
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return
        finite_indices = np.flatnonzero(finite)
        values = y[finite]
        maximum = float(np.nanmax(values))
        tolerance = max(abs(maximum) * 1e-10, np.finfo(float).eps)
        maxima = finite_indices[np.isclose(values, maximum, rtol=1e-10, atol=tolerance)]
        index = int(maxima[len(maxima) // 2]) if len(maxima) else int(finite_indices[np.nanargmax(values)])
        x_position = float(x[index])
        y_position = float(y[index])
        label = pg.TextItem(
            text=name,
            color="#202020",
            anchor=(0.5, 1.0),
            border=pg.mkPen(100, 100, 100, 150),
            fill=pg.mkBrush(255, 255, 255, 220),
        )
        label.setZValue(70)
        self.plot.addItem(label)
        label.setPos(x_position, y_position)
        self._component_labels.append(label)
        self._component_label_specs.append((label, x_position, y_position))

    def _layout_component_labels(self, *_: Any) -> None:
        if self._laying_out_labels or not self._component_label_specs:
            return
        self._laying_out_labels = True
        try:
            _, y_per_pixel = self.view_box.viewPixelSize()
            step_scale = abs(float(y_per_pixel)) if math.isfinite(float(y_per_pixel)) else 0.0
            if step_scale == 0.0:
                return
            direction = -1.0 if bool(self.view_box.state.get("yInverted", False)) else 1.0
            placed: list[Any] = []
            for label, base_x, base_y in sorted(self._component_label_specs, key=lambda item: item[1]):
                y_position = base_y
                label.setPos(base_x, y_position)
                for _ in range(len(self._component_label_specs) + 3):
                    rect = label.sceneBoundingRect().adjusted(-3.0, -2.0, 3.0, 2.0)
                    if not any(rect.intersects(previous) for previous in placed):
                        break
                    y_position += direction * max(16.0, rect.height() + 4.0) * step_scale
                    label.setPos(base_x, y_position)
                placed.append(label.sceneBoundingRect().adjusted(-3.0, -2.0, 3.0, 2.0))
        finally:
            self._laying_out_labels = False

    def _add_component_handles(
''',
)

# Manual updates.
path = "docs/manual.md"
replace_once(
    path,
    '''- Use Ctrl-click or Shift-click for a multi-selection, or use **Select all** and **Deselect all** above the tree.
- Use the visibility checkbox to include or exclude it from Overlay and Waterfall
''',
    '''- Use Ctrl-click or Shift-click for a multi-selection, or use **Select all** and **Deselect all** above the tree.
- Use **Remove selected** to delete one or more accidentally imported curves. Removal is undoable.
- Use the visibility checkbox to include or exclude it from Overlay and Waterfall
''',
)
replace_once(
    path,
    '''The coordinate readout displays the pointer coordinate and the nearest finite point
from the active curve. Rendering may be downsampled by the plotting library for
speed, but fitting and export use all usable points.
''',
    '''The coordinate readout displays the pointer coordinate and the nearest finite point
from the active curve. Rendering may be downsampled by the plotting library for
speed, but fitting and export use all usable points.

Model functions receive systematic names such as **Voigt1**, **Voigt2**, and
**Gaussian1**. Their labels are shown above each function maximum by default and are
shifted vertically when necessary to avoid overlap. Right-click the main plot and
toggle **Show component labels** to hide or show these labels. After every completed
fit, CurveMole redraws and auto-ranges the plot so the newly fitted model is visible
immediately.
''',
)

# Focused regression tests.
Path("tests/test_curve_labels_and_removal.py").write_text(
    '''from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitMode, FitResult, FitSettings
from curvemole.gui.main_window import MainWindow


def _project_with_curve() -> tuple[Project, Curve]:
    project = Project("labels")
    curve = Curve("curve", np.linspace(-5.0, 5.0, 101), np.exp(-np.linspace(-5.0, 5.0, 101) ** 2))
    project.add_curve(curve)
    project.dirty = False
    return project, curve


def test_components_get_systematic_names_and_labels_are_on_by_default() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    model = project.model_for(curve.id)
    model.add(Component.create("voigt"))
    model.add(Component.create("voigt"))
    window = MainWindow(project)
    assert [component.name for component in model.components] == ["Voigt1", "Voigt2"]
    window.plot_workspace.refresh()
    assert window.plot_workspace.component_labels_action.isChecked()
    assert [label.toPlainText() for label in window.plot_workspace._component_labels] == ["Voigt1", "Voigt2"]
    window.plot_workspace.component_labels_action.setChecked(False)
    assert window.plot_workspace._component_labels == []
    project.dirty = False
    window.close()
    app.processEvents()


def test_new_and_duplicated_components_continue_numbering() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    model = project.model_for(curve.id)
    first = Component.create("voigt")
    model.add(first)
    window = MainWindow(project)
    second = Component.create("voigt")
    window._commit_component(second, curve.id)
    assert [item.name for item in project.model_for(curve.id).components] == ["Voigt1", "Voigt2"]
    window.duplicate_component(second.id)
    assert [item.name for item in project.model_for(curve.id).components] == ["Voigt1", "Voigt2", "Voigt3"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_remove_selected_curve_is_undoable(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("remove")
    first = Curve("first", [0.0, 1.0], [0.0, 1.0])
    second = Curve("second", [0.0, 1.0], [1.0, 0.0])
    project.add_curve(first)
    project.add_curve(second)
    project.dirty = False
    window = MainWindow(project)
    window.curve_tree.select_all_curves()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.remove_selected_curves()
    assert project.curves == []
    window.undo_stack.undo()
    assert [curve.id for curve in project.curves] == [first.id, second.id]
    window.undo_stack.redo()
    assert project.curves == []
    project.dirty = False
    window.close()
    app.processEvents()


def test_fit_completion_refreshes_and_auto_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    window = MainWindow(project)
    calls = {"range": 0}
    monkeypatch.setattr(window.plot_workspace, "auto_range", lambda: calls.__setitem__("range", calls["range"] + 1))
    result = FitResult(
        success=True,
        mode=FitMode.INDEPENDENT,
        message="ok",
        status=1,
        evaluations=1,
        parameters={},
        curve_outputs={},
        statistics={},
        warnings=[],
        settings=FitSettings(),
        free_parameter_paths=[],
    )
    window._fit_finished(result)
    assert calls["range"] == 1
    project.dirty = False
    window.close()
    app.processEvents()
''',
    encoding="utf-8",
)
