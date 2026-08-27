from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {relative}: {old[:100]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one match in {relative}, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(relative: str, marker: str, addition: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


# Core: a reversible transformation dedicated to background subtraction.
replace_once(
    "src/curvemole/core/data.py",
    '''        elif op in {"curve_add", "curve_subtract", "curve_multiply", "curve_divide"}:\n            if self.operand is None or len(self.operand) != len(y_new):\n                raise DataValidationError(f"Transformation '{op}' is missing its aligned operand.")\n''',
    '''        elif op == "background_subtract":\n            if self.operand is None or len(self.operand) != len(y_new):\n                raise DataValidationError("Background subtraction is missing its background array.")\n            y_new -= self.operand\n        elif op in {"curve_add", "curve_subtract", "curve_multiply", "curve_divide"}:\n            if self.operand is None or len(self.operand) != len(y_new):\n                raise DataValidationError(f"Transformation '{op}' is missing its aligned operand.")\n''',
)

replace_once(
    "src/curvemole/core/calculator.py",
    '''\ndef apply_curve_operation(\n    target: Curve,\n''',
    '''\ndef apply_background_subtraction(\n    curve: Curve,\n    background: np.ndarray,\n    *,\n    method: str,\n    description: str,\n    parameters: dict[str, Any] | None = None,\n) -> Transformation:\n    """Subtract a background array from every data point, including masked points."""\n    values = np.asarray(background, dtype=np.float64).reshape(-1)\n    if len(values) != len(curve):\n        raise DataValidationError(\n            f"Background length {len(values)} does not match curve length {len(curve)}."\n        )\n    usable = np.isfinite(curve.x) & np.isfinite(curve.y)\n    if np.any(usable & ~np.isfinite(values)):\n        raise DataValidationError("Background contains invalid values at usable data points.")\n    metadata: dict[str, Any] = {"method": str(method)}\n    metadata.update(parameters or {})\n    transformation = Transformation(\n        "background_subtract",\n        metadata,\n        description=description,\n        operand=values.copy(),\n    )\n    curve.apply_transformation(transformation)\n    return transformation\n\n\ndef apply_curve_operation(\n    target: Curve,\n''',
)

# Graphically created spline nodes are fit-locked by default.
replace_once(
    "src/curvemole/core/initialization.py",
    '''    component.metadata = metadata\n    component.parameters = registry.get("cubic_spline").make_parameters(initial, metadata)\n    return component\n''',
    '''    component.metadata = metadata\n    component.parameters = registry.get("cubic_spline").make_parameters(initial, metadata)\n    for parameter in component.parameters.values():\n        parameter.fixed = True\n    return component\n''',
)

# Model panel: always-available bulk lock controls.
replace_once(
    "src/curvemole/gui/panels.py",
    '''    parameterChangeRequested = Signal(str, str, str, object)\n    parameterLinkRequested = Signal(str, str)\n    copyFitRequested = Signal()\n''',
    '''    parameterChangeRequested = Signal(str, str, str, object)\n    parameterLinkRequested = Signal(str, str)\n    bulkFixedRequested = Signal(str, bool)\n    copyFitRequested = Signal()\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''        self.parameters.itemChanged.connect(self._parameter_changed)\n        single_layout.addWidget(self.parameters, 2)\n        self.derived = QLabel()\n''',
    '''        self.parameters.itemChanged.connect(self._parameter_changed)\n        single_layout.addWidget(self.parameters, 2)\n        fixed_buttons = QHBoxLayout()\n        self.lock_all_parameters_button = QPushButton(self.tr("Lock all"))\n        self.unlock_all_parameters_button = QPushButton(self.tr("Unlock all"))\n        self.lock_all_parameters_button.setToolTip(\n            self.tr("Fix every parameter in the selected component during fitting.")\n        )\n        self.unlock_all_parameters_button.setToolTip(\n            self.tr("Allow every parameter in the selected component to vary during fitting.")\n        )\n        self.lock_all_parameters_button.clicked.connect(lambda: self._bulk_fixed(True))\n        self.unlock_all_parameters_button.clicked.connect(lambda: self._bulk_fixed(False))\n        fixed_buttons.addWidget(self.lock_all_parameters_button)\n        fixed_buttons.addWidget(self.unlock_all_parameters_button)\n        fixed_buttons.addStretch(1)\n        single_layout.addLayout(fixed_buttons)\n        self.derived = QLabel()\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''    def _duplicate(self) -> None:\n        if component_id := self.selected_component_id():\n            self.duplicateRequested.emit(component_id)\n''',
    '''    def _bulk_fixed(self, fixed: bool) -> None:\n        if component_id := self.selected_component_id():\n            self.bulkFixedRequested.emit(component_id, fixed)\n\n    def _duplicate(self) -> None:\n        if component_id := self.selected_component_id():\n            self.duplicateRequested.emit(component_id)\n''',
)

# Main window imports and state.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''from curvemole.core.calculator import apply_curve_operation, apply_scalar\n''',
    '''from curvemole.core.calculator import (\n    apply_background_subtraction,\n    apply_curve_operation,\n    apply_scalar,\n)\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        self._pending_component: Component | None = None\n        self._pending_component_curve_id: str | None = None\n        self.settings = QSettings("CurveMole", "CurveMole")\n''',
    '''        self._pending_component: Component | None = None\n        self._pending_component_curve_id: str | None = None\n        self._pending_background_subtraction_curve_id: str | None = None\n        self.settings = QSettings("CurveMole", "CurveMole")\n''',
)

# Data action and placement in menus/toolbar.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        self.mask_tolerance_action = QAction(self.tr("Mask transfer tolerance…"), self)\n        self.mask_tolerance_action.triggered.connect(self.set_mask_tolerance)\n\n        self.fit_action = QAction(self.tr("Fit…"), self)\n''',
    '''        self.mask_tolerance_action = QAction(self.tr("Mask transfer tolerance…"), self)\n        self.mask_tolerance_action.triggered.connect(self.set_mask_tolerance)\n        self.subtract_background_action = QAction(self.tr("Subtract background…"), self)\n        self.subtract_background_action.setToolTip(\n            self.tr("Subtract a constant or graphically defined spline background from the active curve.")\n        )\n        self.subtract_background_action.triggered.connect(self.subtract_background)\n\n        self.fit_action = QAction(self.tr("Fit…"), self)\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        data_menu = menu.addMenu(self.tr("&Data"))\n        data_menu.addActions([self.import_action, self.calculator_action, self.worksheet_action])\n        data_menu.addSeparator()\n''',
    '''        data_menu = menu.addMenu(self.tr("&Data"))\n        data_menu.addActions(\n            [\n                self.import_action,\n                self.subtract_background_action,\n                self.calculator_action,\n                self.worksheet_action,\n            ]\n        )\n        data_menu.addSeparator()\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''                self.calculator_action,\n                self.add_component_action,\n''',
    '''                self.calculator_action,\n                self.subtract_background_action,\n                self.add_component_action,\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n        self.model_panel.parameterLinkRequested.connect(self.edit_parameter_link)\n        self.model_panel.copyFitRequested.connect(self.copy_fit)\n''',
    '''        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n        self.model_panel.parameterLinkRequested.connect(self.edit_parameter_link)\n        self.model_panel.bulkFixedRequested.connect(self.set_component_fixed)\n        self.model_panel.copyFitRequested.connect(self.copy_fit)\n''',
)

# Make spline placement wording explicit about masked regions.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''                self._notify(\n                    self.tr("Click background points on the graph; finish after at least two points.")\n                )\n''',
    '''                self._notify(\n                    self.tr(\n                        "Click background points anywhere on the graph, including masked regions; "\n                        "finish after at least two points. Spline nodes are locked by default."\n                    )\n                )\n''',
)

# Graphical spline can either create a model component or subtract a background.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''    def _graphical_spline_placed(self, points: object) -> None:\n        component = self._pending_component\n        curve_id = self._pending_component_curve_id\n        self._pending_component = None\n        self._pending_component_curve_id = None\n        if component is None or curve_id is None:\n            return\n        try:\n            selected = [(float(x), float(y)) for x, y in list(points)]\n            initialise_spline_component(component, selected, registry=self.registry)\n            self._commit_component(component, curve_id)\n        except Exception as exc:\n            self._show_error(self.tr("Place spline background"), exc)\n\n    def _graphical_placement_cancelled(self) -> None:\n        if self._pending_component is not None:\n            self._notify(self.tr("Component placement cancelled."), warning=True)\n        self._pending_component = None\n        self._pending_component_curve_id = None\n''',
    '''    def _graphical_spline_placed(self, points: object) -> None:\n        selected = [(float(x), float(y)) for x, y in list(points)]\n        subtraction_curve_id = self._pending_background_subtraction_curve_id\n        self._pending_background_subtraction_curve_id = None\n        if subtraction_curve_id is not None:\n            try:\n                ordered = sorted(selected)\n                component = Component.create(\n                    "cubic_spline",\n                    registry=self.registry,\n                    metadata={"x_nodes": [x for x, _ in ordered]},\n                )\n                initialise_spline_component(component, ordered, registry=self.registry)\n                curve = self.project.dataset.curve(subtraction_curve_id)\n                values = {\n                    name: parameter.value for name, parameter in component.parameters.items()\n                }\n                background = self.registry.get("cubic_spline").evaluate(\n                    curve.x, values, component.metadata\n                )\n                self._apply_background_array(\n                    curve,\n                    background,\n                    method="spline",\n                    description=self.tr("Subtract spline background"),\n                    parameters={\n                        "x_nodes": list(component.metadata["x_nodes"]),\n                        "y_nodes": [values[f"y{index}"] for index in range(len(values))],\n                    },\n                )\n                self._notify(\n                    self.tr(\n                        "Spline background subtracted from the full curve, including masked regions."\n                    )\n                )\n            except Exception as exc:\n                self._show_error(self.tr("Subtract spline background"), exc)\n            return\n\n        component = self._pending_component\n        curve_id = self._pending_component_curve_id\n        self._pending_component = None\n        self._pending_component_curve_id = None\n        if component is None or curve_id is None:\n            return\n        try:\n            initialise_spline_component(component, selected, registry=self.registry)\n            self._commit_component(component, curve_id)\n        except Exception as exc:\n            self._show_error(self.tr("Place spline background"), exc)\n\n    def _graphical_placement_cancelled(self) -> None:\n        if self._pending_component is not None:\n            self._notify(self.tr("Component placement cancelled."), warning=True)\n        if self._pending_background_subtraction_curve_id is not None:\n            self._notify(self.tr("Background subtraction cancelled."), warning=True)\n        self._pending_component = None\n        self._pending_component_curve_id = None\n        self._pending_background_subtraction_curve_id = None\n''',
)

# Bulk fixed/unfixed action in MainWindow.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''    def edit_parameter_link(self, component_id: str, name: str) -> None:\n''',
    '''    def set_component_fixed(self, component_id: str, fixed: bool) -> None:\n        if not self.active_curve_id:\n            return\n        component = self.project.model_for(self.active_curve_id).component(component_id)\n        before = {name: parameter.fixed for name, parameter in component.parameters.items()}\n        after = {name: bool(fixed) for name in component.parameters}\n        if before == after:\n            return\n\n        def restore(values: dict[str, bool]) -> None:\n            for name, value in values.items():\n                component.parameters[name].fixed = value\n\n        text = self.tr("Lock all parameters") if fixed else self.tr("Unlock all parameters")\n        self._push_change(text, lambda: restore(after), lambda: restore(before))\n\n    def edit_parameter_link(self, component_id: str, name: str) -> None:\n''',
)

# Background subtraction workflow. Constant estimation deliberately ignores fit masks.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''    def find_peaks(self) -> None:\n''',
    '''    def subtract_background(self) -> None:\n        if not self._ensure_editable():\n            return\n        if not self.active_curve_id:\n            self._notify(self.tr("Activate a curve first."), warning=True)\n            return\n        curve = self.project.dataset.curve(self.active_curve_id)\n        choices = [\n            self.tr("Constant from x interval"),\n            self.tr("Spline from graph"),\n        ]\n        selected_method, accepted = QInputDialog.getItem(\n            self,\n            self.tr("Subtract background"),\n            self.tr("Background method:"),\n            choices,\n            0,\n            False,\n        )\n        if not accepted:\n            return\n        if selected_method == choices[1]:\n            self.plot_workspace.cancel_placement()\n            self._pending_background_subtraction_curve_id = curve.id\n            self.plot_workspace.begin_spline_placement(self.tr("Background subtraction"))\n            self._notify(\n                self.tr(\n                    "Place spline background nodes anywhere, including masked regions. "\n                    "Double-click or press Finish to subtract it from the full curve."\n                )\n            )\n            return\n\n        finite_x = curve.x[np.isfinite(curve.x)]\n        if not len(finite_x):\n            self._notify(self.tr("The active curve has no finite x values."), warning=True)\n            return\n        x_min = float(np.min(finite_x))\n        x_max = float(np.max(finite_x))\n        lower, accepted = QInputDialog.getDouble(\n            self,\n            self.tr("Constant background"),\n            self.tr("Interval start (x):"),\n            x_min,\n            -1e100,\n            1e100,\n            12,\n        )\n        if not accepted:\n            return\n        upper, accepted = QInputDialog.getDouble(\n            self,\n            self.tr("Constant background"),\n            self.tr("Interval end (x):"),\n            x_max,\n            -1e100,\n            1e100,\n            12,\n        )\n        if not accepted:\n            return\n        lo, hi = sorted((float(lower), float(upper)))\n        in_interval = (\n            np.isfinite(curve.x)\n            & np.isfinite(curve.y)\n            & (curve.x >= lo)\n            & (curve.x <= hi)\n        )\n        if not np.any(in_interval):\n            self._notify(\n                self.tr("The selected interval contains no finite data points."),\n                warning=True,\n            )\n            return\n        offset = float(np.nanmedian(curve.y[in_interval]))\n        background = np.full(len(curve), offset, dtype=float)\n        self._apply_background_array(\n            curve,\n            background,\n            method="constant_interval",\n            description=self.tr("Subtract constant background"),\n            parameters={"lower": lo, "upper": hi, "offset": offset},\n        )\n        self._notify(\n            self.tr("Constant background subtracted: ") + f"{offset:.8g}"\n        )\n\n    def _apply_background_array(\n        self,\n        curve: Curve,\n        background: np.ndarray,\n        *,\n        method: str,\n        description: str,\n        parameters: dict[str, Any] | None = None,\n    ) -> None:\n        transformation = apply_background_subtraction(\n            curve,\n            background,\n            method=method,\n            description=description,\n            parameters=parameters,\n        )\n        curve.undo_transformation()\n\n        def redo() -> None:\n            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:\n                curve.redo_transformation()\n            elif transformation not in curve.transformations:\n                curve.apply_transformation(transformation)\n\n        def undo() -> None:\n            if curve.transformations and curve.transformations[-1] is transformation:\n                curve.undo_transformation()\n\n        self._push_change(self.tr("Subtract background"), redo, undo)\n\n    def find_peaks(self) -> None:\n''',
)

# Plot instructions and spline-handle tooltip.
replace_once(
    "src/curvemole/gui/plot.py",
    '''                target.setToolTip(\n                    self.tr("Drag spline y node. Its x position remains fixed by default.")\n                )\n''',
    '''                target.setToolTip(\n                    self.tr(\n                        "Drag an unlocked spline y node. Fixed nodes stay locked unless Ctrl is held; "\n                        "the x position always remains fixed."\n                    )\n                )\n''',
)
replace_once(
    "src/curvemole/gui/plot.py",
    '''                "Place spline background nodes: left-click adds a point, right-click removes the nearest point, "\n                "and a left double-click accepts the spline. The curve updates live. "\n''',
    '''                "Place spline background nodes: left-click adds a point, right-click removes the nearest point, "\n                "and a left double-click accepts the spline. Masked regions are allowed and the curve updates live. "\n''',
)

# Regression tests.
replace_once(
    "tests/test_data.py",
    '''from curvemole.core.calculator import apply_curve_operation, apply_scalar\n''',
    '''from curvemole.core.calculator import (\n    apply_background_subtraction,\n    apply_curve_operation,\n    apply_scalar,\n)\n''',
)
append_once(
    "tests/test_data.py",
    "def test_background_subtraction_applies_inside_masks",
    '''def test_background_subtraction_applies_inside_masks() -> None:\n    curve = Curve("background", np.arange(5.0), np.array([10.0, 11.0, 12.0, 13.0, 14.0]))\n    curve.mask_interval(1.0, 3.0)\n    before_mask = curve.effective_mask.copy()\n\n    apply_background_subtraction(\n        curve,\n        np.array([1.0, 2.0, 3.0, 4.0, 5.0]),\n        method="test",\n        description="test background",\n    )\n\n    assert curve.y.tolist() == pytest.approx([9.0, 9.0, 9.0, 9.0, 9.0])\n    assert curve.effective_mask.tolist() == before_mask.tolist()\n    assert curve.undo_transformation()\n    assert curve.y.tolist() == pytest.approx([10.0, 11.0, 12.0, 13.0, 14.0])''',
)
replace_once(
    "tests/test_initialization.py",
    '''    assert component.metadata["x_nodes"] == [0.0, 1.0, 2.0]\n    values = {name: parameter.value for name, parameter in component.parameters.items()}\n''',
    '''    assert component.metadata["x_nodes"] == [0.0, 1.0, 2.0]\n    assert all(parameter.fixed for parameter in component.parameters.values())\n    values = {name: parameter.value for name, parameter in component.parameters.items()}\n''',
)
append_once(
    "tests/test_gui_smoke.py",
    "def test_spline_bulk_lock_controls_and_background_subtraction",
    '''def test_spline_bulk_lock_controls_and_background_subtraction() -> None:\n    app = QApplication.instance() or QApplication([])\n    project = Project("Background")\n    curve = Curve(\n        "curve",\n        [0.0, 1.0, 2.0, 3.0, 4.0],\n        [2.0, 3.0, 5.0, 3.0, 2.0],\n    )\n    curve.mask_interval(1.0, 3.0)\n    project.add_curve(curve)\n    spline = Component.create("cubic_spline", metadata={"x_nodes": [0.0, 4.0]})\n    initialise_spline_component = pytest.importorskip(\n        "curvemole.core.initialization"\n    ).initialise_spline_component\n    initialise_spline_component(spline, [(0.0, 2.0), (4.0, 2.0)])\n    project.model_for(curve.id).add(spline)\n    project.dirty = False\n    window = MainWindow(project)\n    window._set_component(spline.id)\n\n    assert all(parameter.fixed for parameter in spline.parameters.values())\n    window.model_panel.unlock_all_parameters_button.click()\n    assert all(not parameter.fixed for parameter in spline.parameters.values())\n    window.model_panel.lock_all_parameters_button.click()\n    assert all(parameter.fixed for parameter in spline.parameters.values())\n\n    mask_before = curve.effective_mask.copy()\n    window._pending_background_subtraction_curve_id = curve.id\n    window._graphical_spline_placed([(0.0, 2.0), (4.0, 2.0)])\n    assert curve.y.tolist() == pytest.approx([0.0, 1.0, 3.0, 1.0, 0.0])\n    assert curve.effective_mask.tolist() == mask_before.tolist()\n    assert curve.transformations[-1].operation == "background_subtract"\n\n    project.dirty = False\n    window.close()\n    app.processEvents()''',
)

# Documentation source. Generated LaTeX/PDF editions are rebuilt by the release workflow.
append_once(
    "docs/manual.md",
    "## Background subtraction and spline controls",
    '''## Background subtraction and spline controls\n\nUse **Data > Subtract background...** when the measured zero line should be corrected before or after model construction. Two methods are available:\n\n- **Constant from x interval** asks for an x interval, calculates the median y value in that interval, and subtracts that constant from the entire active curve. The interval calculation deliberately includes masked data points if they lie inside the requested x range.\n- **Spline from graph** starts the graphical spline editor. Left-click adds a node, right-click removes the nearest node, and a left double-click or **Finish** accepts the spline. Nodes may be placed inside masked regions. The resulting spline is evaluated and subtracted over the entire x array, including masked regions.\n\nBackground subtraction is stored as a reversible data transformation. The original imported arrays are retained, **Undo** reverses the subtraction, and **Restore original data** in the Data Calculator removes the transformation history. Masks are not removed or changed by background subtraction: they still control which data points participate in fitting.\n\nFor cubic-spline model components, the y values of newly placed spline nodes are **fixed by default**. This prevents an intentionally drawn baseline from drifting when a fit starts. Individual nodes can be unlocked with the **Fixed** checkbox in the parameter table. The **Lock all** and **Unlock all** controls below the parameter table change the fixed state of every parameter in the selected component at once. The x positions of spline nodes remain fixed; unlocking a node allows its y value to vary or be dragged.\n\nA spline is evaluated continuously through masked regions even though masked measurements are excluded from the objective function. This makes it possible to define a baseline through masked peaks or artifacts without temporarily unmasking those data.''',
)

print("Background subtraction and spline UX patch applied.")
