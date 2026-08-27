from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.M | re.S)
    if count != 1:
        raise SystemExit(f"Expected one regex match in {path}, got {count}: {pattern[:120]!r}")
    target.write_text(updated, encoding="utf-8")


# Component-level background designation replaces function-level background classification.
replace_once(
    "src/curvemole/core/models.py",
    "    operator: str = \"add\"\n    enabled: bool = True\n    group: str | None = None\n",
    "    operator: str = \"add\"\n    enabled: bool = True\n    is_background: bool = False\n    group: str | None = None\n",
)
replace_once(
    "src/curvemole/core/models.py",
    '            "enabled": self.enabled,\n            "group": self.group,\n',
    '            "enabled": self.enabled,\n            "is_background": self.is_background,\n            "group": self.group,\n',
)
replace_once(
    "src/curvemole/core/models.py",
    '            enabled=bool(value.get("enabled", True)),\n            group=str(value["group"]) if value.get("group") else None,\n',
    '            enabled=bool(value.get("enabled", True)),\n            is_background=bool(value.get("is_background", False)),\n            group=str(value["group"]) if value.get("group") else None,\n',
)
regex_once(
    "src/curvemole/core/models.py",
    r"    def background\(\n.*?\n        return result\n",
    '''    def background(\n        self,\n        x: np.ndarray,\n        *,\n        curve_id: str | None = None,\n        values: Mapping[str, float] | None = None,\n        registry: FunctionRegistry | None = None,\n        component_ids: set[str] | None = None,\n    ) -> np.ndarray:\n        \"\"\"Evaluate marked background components, or an explicit selected subset.\"\"\"\n        registry = registry or default_registry()\n        prefix = curve_id or self.id\n        if values is None:\n            values = resolve_parameter_values(self.parameter_map(prefix))\n        selected = set(component_ids) if component_ids is not None else None\n        result = np.zeros_like(x, dtype=float)\n        for component in self.components:\n            if not component.enabled:\n                continue\n            if selected is None:\n                if not component.is_background:\n                    continue\n            elif component.id not in selected:\n                continue\n            if component.operator not in {\"add\", \"subtract\"}:\n                raise DataValidationError(\n                    f\"Background component '{component.name}' must use add or subtract composition.\"\n                )\n            definition = registry.get(component.function_id)\n            parameters = {\n                name: values.get(self.parameter_path(prefix, component.id, name), parameter.value)\n                for name, parameter in component.parameters.items()\n            }\n            evaluated = definition.evaluate(np.asarray(x, dtype=float), parameters, component.metadata)\n            result += evaluated if component.operator == \"add\" else -evaluated\n        return result\n''',
)

# Built-in baseline shapes are ordinary functions; background is a component flag.
for evaluator, old_name, new_name in (
    ("_constant", "Constant background", "Constant"),
    ("_linear", "Linear background", "Linear"),
    ("_polynomial", "Polynomial background", "Polynomial"),
    ("_spline", "Cubic-spline background", "Cubic spline"),
):
    replace_once(
        "src/curvemole/core/functions.py",
        f'            "{old_name}",\n            "background",\n            {evaluator},',
        f'            "{new_name}",\n            "generic",\n            {evaluator},',
    )

# Copy-fit background filtering now follows the component flag.
replace_once(
    "src/curvemole/core/project.py",
    '''                for component in source_model.components:\n                    definition_is_background = component.function_id in {\n                        "constant",\n                        "linear",\n                        "polynomial",\n                        "cubic_spline",\n                    }\n                    if definition_is_background and not background:\n                        continue\n''',
    '''                for component in source_model.components:\n                    if component.is_background and not background:\n                        continue\n''',
)
replace_once(
    "src/curvemole/core/project.py",
    '''                for source_component, target_component in zip(\n                    source_model.components, target_model.components, strict=False\n                ):\n                    for name, source_parameter in source_component.parameters.items():\n''',
    '''                for source_component, target_component in zip(\n                    source_model.components, target_model.components, strict=False\n                ):\n                    if source_component.is_background and not background:\n                        continue\n                    if background:\n                        target_component.is_background = source_component.is_background\n                    for name, source_parameter in source_component.parameters.items():\n''',
)

# Add a focused chooser for model components to subtract.
dialog_insert = '''\n\nclass BackgroundComponentsDialog(QDialog):\n    \"\"\"Choose model components that define the background to subtract.\"\"\"\n\n    def __init__(\n        self,\n        project: Project,\n        curve_id: str,\n        registry: FunctionRegistry,\n        parent: QWidget | None = None,\n    ) -> None:\n        super().__init__(parent)\n        self.project = project\n        self.curve_id = curve_id\n        self.registry = registry\n        model = project.model_for(curve_id)\n        marked = [component for component in model.components if component.is_background]\n        self.marking_mode = not marked\n        candidates = [\n            component\n            for component in (model.components if self.marking_mode else marked)\n            if component.enabled\n        ]\n\n        self.setWindowTitle(self.tr(\"Subtract background\"))\n        self.resize(560, 420)\n        layout = QVBoxLayout(self)\n        if self.marking_mode:\n            message = self.tr(\n                \"No model functions are marked as background. Indicate which functions represent \"\n                \"the background. The selected functions will be marked as background and subtracted.\"\n            )\n        else:\n            message = self.tr(\n                \"Select which functions marked as background should be subtracted from the data.\"\n            )\n        explanation = QLabel(message)\n        explanation.setWordWrap(True)\n        layout.addWidget(explanation)\n\n        self.components = QListWidget()\n        for component in candidates:\n            definition = registry.get(component.function_id)\n            item = QListWidgetItem(f\"{component.name}  ·  {definition.display_name}\")\n            item.setData(Qt.ItemDataRole.UserRole, component.id)\n            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)\n            item.setCheckState(\n                Qt.CheckState.Unchecked if self.marking_mode else Qt.CheckState.Checked\n            )\n            self.components.addItem(item)\n        layout.addWidget(self.components, 1)\n\n        selection = QHBoxLayout()\n        select_all = QPushButton(self.tr(\"Select all\"))\n        deselect_all = QPushButton(self.tr(\"Deselect all\"))\n        select_all.clicked.connect(lambda: _set_list_checked(self.components, True))\n        deselect_all.clicked.connect(lambda: _set_list_checked(self.components, False))\n        selection.addWidget(select_all)\n        selection.addWidget(deselect_all)\n        selection.addStretch(1)\n        layout.addLayout(selection)\n\n        if not candidates:\n            empty = QLabel(\n                self.tr(\n                    \"There are no enabled candidate functions. Add or enable a model function first.\"\n                )\n            )\n            empty.setWordWrap(True)\n            layout.addWidget(empty)\n\n        self.buttons = QDialogButtonBox(\n            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel\n        )\n        self.buttons.accepted.connect(self.accept)\n        self.buttons.rejected.connect(self.reject)\n        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(candidates))\n        layout.addWidget(self.buttons)\n\n    def selected_component_ids(self) -> list[str]:\n        return [\n            str(self.components.item(index).data(Qt.ItemDataRole.UserRole))\n            for index in range(self.components.count())\n            if self.components.item(index).checkState() == Qt.CheckState.Checked\n        ]\n'''
replace_once(
    "src/curvemole/gui/dialogs.py",
    "\n\nclass AddComponentDialog(QDialog):\n",
    dialog_insert + "\n\nclass AddComponentDialog(QDialog):\n",
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    '            self.function.addItem(f"{definition.display_name} — {definition.kind}", definition.identifier)\n',
    '            self.function.addItem(definition.display_name, definition.identifier)\n',
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    '            self.tr("After pressing Add, place the spline nodes directly on the graph.")\n',
    '            self.tr("After pressing Add, place spline nodes anywhere in the plot; pan and zoom remain available.")\n',
)

# Model panel: explicit per-component background marker.
replace_once(
    "src/curvemole/gui/panels.py",
    "    enabledRequested = Signal(str, bool)\n    parameterChangeRequested = Signal(str, str, str, object)\n",
    "    enabledRequested = Signal(str, bool)\n    backgroundRequested = Signal(str, bool)\n    parameterChangeRequested = Signal(str, str, str, object)\n",
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''        self.components.currentItemChanged.connect(self._component_selected)\n        self.components.itemChanged.connect(self._component_enabled)\n        single_layout.addWidget(self.components, 1)\n        buttons = QHBoxLayout()\n''',
    '''        self.components.currentItemChanged.connect(self._component_selected)\n        self.components.itemChanged.connect(self._component_enabled)\n        single_layout.addWidget(self.components, 1)\n        self.background_toggle = QCheckBox(self.tr(\"Mark as background\"))\n        self.background_toggle.setToolTip(\n            self.tr(\"Treat the selected model function as part of the background.\")\n        )\n        self.background_toggle.toggled.connect(self._background_toggled)\n        single_layout.addWidget(self.background_toggle)\n        buttons = QHBoxLayout()\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''                label = f"{component.name}  ·  {definition.display_name}"\n                item = QListWidgetItem(label)\n''',
    '''                label = f"{component.name}  ·  {definition.display_name}"\n                if component.is_background:\n                    label += self.tr(\"  ·  Background\")\n                item = QListWidgetItem(label)\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''                if definition.kind == "background":\n                    item.setForeground(QColor("#666666"))\n''',
    '''                if component.is_background:\n                    item.setForeground(QColor("#666666"))\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''            if not component_id or not self.project or not self.curve_id:\n                self.derived.clear()\n                return\n            model = self.project.model_for(self.curve_id)\n            component = model.component(component_id)\n''',
    '''            if not component_id or not self.project or not self.curve_id:\n                self.background_toggle.blockSignals(True)\n                self.background_toggle.setChecked(False)\n                self.background_toggle.setEnabled(False)\n                self.background_toggle.blockSignals(False)\n                self.derived.clear()\n                return\n            model = self.project.model_for(self.curve_id)\n            component = model.component(component_id)\n            self.background_toggle.blockSignals(True)\n            self.background_toggle.setEnabled(True)\n            self.background_toggle.setChecked(component.is_background)\n            self.background_toggle.blockSignals(False)\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''    def _parameter_changed(self, item: QTableWidgetItem) -> None:\n''',
    '''    def _background_toggled(self, marked: bool) -> None:\n        if self._updating:\n            return\n        if component_id := self.selected_component_id():\n            self.backgroundRequested.emit(component_id, marked)\n\n    def _parameter_changed(self, item: QTableWidgetItem) -> None:\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''        self.kind = QComboBox()\n        self.kind.addItems(["peak", "background", "generic"])\n''',
    '''        self.kind = QComboBox()\n        self.kind.addItem(self.tr(\"Peak-shaped function (graphical peak placement)\"), \"peak\")\n        self.kind.addItem(self.tr(\"General function\"), \"generic\")\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '        layout.addRow(self.tr("Classification"), self.kind)\n',
    '        layout.addRow(self.tr("Graphical behaviour"), self.kind)\n',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '                kind=self.kind.currentText(),\n',
    '                kind=str(self.kind.currentData()),\n',
)

# Main window imports, signal, component flag mutation, and model-based subtraction.
replace_once(
    "src/curvemole/gui/main_window.py",
    '''    AboutDialog,\n    AddComponentDialog,\n    CopyFitDialog,\n''',
    '''    AboutDialog,\n    AddComponentDialog,\n    BackgroundComponentsDialog,\n    CopyFitDialog,\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "        self._pending_background_subtraction_curve_id: str | None = None\n",
    "",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        self.model_panel.enabledRequested.connect(self.enable_component)\n        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n''',
    '''        self.model_panel.enabledRequested.connect(self.enable_component)\n        self.model_panel.backgroundRequested.connect(self.set_component_background)\n        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n''',
)
regex_once(
    "src/curvemole/gui/main_window.py",
    r"    def _graphical_spline_placed\(self, points: object\) -> None:\n        selected = .*?\n\n        component = self\._pending_component",
    '''    def _graphical_spline_placed(self, points: object) -> None:\n        selected = [(float(x), float(y)) for x, y in list(points)]\n        component = self._pending_component''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        if self._pending_background_subtraction_curve_id is not None:\n            self._notify(self.tr("Background subtraction cancelled."), warning=True)\n        self._pending_component = None\n        self._pending_component_curve_id = None\n        self._pending_background_subtraction_curve_id = None\n''',
    '''        self._pending_component = None\n        self._pending_component_curve_id = None\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''    def change_parameter(self, component_id: str, name: str, field: str, value: Any) -> None:\n''',
    '''    def set_component_background(self, component_id: str, marked: bool) -> None:\n        if not self.active_curve_id:\n            return\n        component = self.project.model_for(self.active_curve_id).component(component_id)\n        old = component.is_background\n        if old == bool(marked):\n            return\n        self._push_change(\n            self.tr(\"Mark background\") if marked else self.tr(\"Unmark background\"),\n            lambda: setattr(component, \"is_background\", bool(marked)),\n            lambda: setattr(component, \"is_background\", old),\n        )\n\n    def change_parameter(self, component_id: str, name: str, field: str, value: Any) -> None:\n''',
)
regex_once(
    "src/curvemole/gui/main_window.py",
    r"    def subtract_background\(self\) -> None:\n.*?\n    def _apply_background_array\(",
    '''    def subtract_background(self) -> None:\n        if not self._ensure_editable():\n            return\n        if not self.active_curve_id:\n            self._notify(self.tr(\"Activate a curve first.\"), warning=True)\n            return\n        curve_id = self.active_curve_id\n        curve = self.project.dataset.curve(curve_id)\n        model = self.project.model_for(curve_id)\n        if not model.components:\n            self._notify(\n                self.tr(\"Add at least one model function before subtracting a background.\"),\n                warning=True,\n            )\n            return\n\n        dialog = BackgroundComponentsDialog(self.project, curve_id, self.registry, self)\n        if dialog.exec() != dialog.DialogCode.Accepted:\n            return\n        component_ids = dialog.selected_component_ids()\n        if not component_ids:\n            self._notify(self.tr(\"Select at least one background function.\"), warning=True)\n            return\n\n        selected = [model.component(component_id) for component_id in component_ids]\n        try:\n            background = model.background(\n                curve.x,\n                curve_id=curve_id,\n                values=self.project.resolved_parameter_values(),\n                registry=self.registry,\n                component_ids=set(component_ids),\n            )\n        except Exception as exc:\n            self._show_error(self.tr(\"Subtract background\"), exc)\n            return\n        if not np.all(np.isfinite(background)):\n            self._notify(\n                self.tr(\"The selected background functions produce non-finite values.\"),\n                warning=True,\n            )\n            return\n\n        states_before = {\n            component.id: (component.is_background, component.enabled)\n            for component in selected\n        }\n        states_after = {component.id: (True, False) for component in selected}\n        transformation = apply_background_subtraction(\n            curve,\n            background,\n            method=\"model_components\",\n            description=self.tr(\"Subtract marked model background\"),\n            parameters={\n                \"component_ids\": list(component_ids),\n                \"component_names\": [component.name for component in selected],\n            },\n        )\n        curve.undo_transformation()\n\n        def restore_states(states: dict[str, tuple[bool, bool]]) -> None:\n            for component_id, (marked, enabled) in states.items():\n                component = model.component(component_id)\n                component.is_background = marked\n                component.enabled = enabled\n\n        def redo() -> None:\n            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:\n                curve.redo_transformation()\n            elif transformation not in curve.transformations:\n                curve.apply_transformation(transformation)\n            restore_states(states_after)\n\n        def undo() -> None:\n            if curve.transformations and curve.transformations[-1] is transformation:\n                curve.undo_transformation()\n            restore_states(states_before)\n\n        self._push_change(self.tr(\"Subtract background\"), redo, undo)\n        self._notify(\n            self.tr(\"Background subtracted. Selected background functions were disabled to avoid double-counting.\")\n        )\n\n    def _apply_background_array(''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '            self.tr("Subtract a constant or graphically defined spline background from the active curve.")\n',
    '            self.tr("Subtract selected model functions that are marked as background.")\n',
)

# Spline placement: keep manual navigation, prevent auto-range, and preview outside data extent.
replace_once(
    "src/curvemole/gui/plot.py",
    '''        if self.interaction_mode == "spline" and event.button() == Qt.MouseButton.LeftButton:\n            event.accept()\n            return\n''',
    '''        if self.interaction_mode == "spline" and event.button() == Qt.MouseButton.LeftButton:\n            # Preserve normal ViewBox left-drag panning while spline placement is active.\n            super().mouseDragEvent(event, axis=axis)\n            return\n''',
)
replace_once(
    "src/curvemole/gui/plot.py",
    '''        self._spline_points = []\n        self.view_box.interaction_mode = "spline"\n        self.mask_toggle.setChecked(False)\n''',
    '''        self._spline_points = []\n        self.view_box.interaction_mode = "spline"\n        # Placement graphics must never force a new view range. Manual pan/zoom stays active.\n        self.view_box.disableAutoRange()\n        self.mask_toggle.setChecked(False)\n''',
)
replace_once(
    "src/curvemole/gui/plot.py",
    '''        curve = self._project.dataset.curve(self._active_curve_id)\n        finite = np.isfinite(curve.x)\n        if not np.any(finite):\n            return\n        metadata = {"x_nodes": node_x.tolist()}\n        values = {f"y{index}": value for index, value in enumerate(node_y)}\n        preview = self.registry.get("cubic_spline").evaluate(curve.x[finite], values, metadata)\n        line = self.plot.plot(\n            curve.x[finite] + x_offset,\n            preview + y_offset,\n''',
    '''        curve = self._project.dataset.curve(self._active_curve_id)\n        finite = np.isfinite(curve.x)\n        if not np.any(finite):\n            return\n        data_x = np.asarray(curve.x[finite], dtype=float)\n        lower = float(min(np.min(data_x), np.min(node_x)))\n        upper = float(max(np.max(data_x), np.max(node_x)))\n        preview_count = max(400, min(4000, len(data_x) * 2))\n        preview_x = np.linspace(lower, upper, preview_count)\n        metadata = {"x_nodes": node_x.tolist()}\n        values = {f"y{index}": value for index, value in enumerate(node_y)}\n        preview = self.registry.get("cubic_spline").evaluate(preview_x, values, metadata)\n        line = self.plot.plot(\n            preview_x + x_offset,\n            preview + y_offset,\n''',
)
replace_once(
    "src/curvemole/gui/plot.py",
    '''                "Place spline background nodes: left-click adds a point, right-click removes the nearest point, "\n                "and a left double-click accepts the spline. The curve updates live. "\n''',
    '''                "Place spline nodes anywhere: left-click adds a point, right-click removes the nearest point, "\n                "left-drag pans, the mouse wheel zooms, and a left double-click accepts the spline. "\n                "Adding points never changes the current zoom. The curve updates live. "\n''',
)

# Manual: explain component-level background semantics and spline navigation.
manual = ROOT / "docs/manual.md"
manual_text = manual.read_text(encoding="utf-8")
manual_marker = "## 8. Building models\n"
if manual_marker not in manual_text:
    raise SystemExit("Manual section 8 heading not found")
manual_note = '''## 8. Building models\n\nAll entries in the function library are fitting functions. Constant, linear, polynomial,\ncubic-spline, peak-shaped, and custom formulas are not separated into a special\nbackground-function class. Background is instead a property of a model component.\nSelect a component in **Model and parameters** and enable **Mark as background** when\nthat component represents the experimental baseline or background.\n\n**Data > Subtract background...** uses these component-level marks. If no component is\nmarked, CurveMole first asks which model functions should be designated as background.\nIf background components already exist, it asks which of the marked components should\nbe subtracted. The subtraction uses the current resolved/fitted parameter values, is\nreversible with Undo, applies over the complete data array, and disables the subtracted\ncomponents afterwards to prevent double-counting.\n\nDuring graphical cubic-spline placement, nodes may be placed anywhere in plot\ncoordinates, including outside the x/y extent of the measured data. Adding nodes does\nnot auto-range the graph. Left-drag continues to pan and the mouse wheel continues to\nzoom while placement is active.\n'''
manual.write_text(manual_text.replace(manual_marker, manual_note, 1), encoding="utf-8")

# Focused regression tests.
(ROOT / "tests/test_background_semantics.py").write_text(
    '''from __future__ import annotations\n\nimport numpy as np\nimport pytest\n\nfrom curvemole import Component, Curve, Project\nfrom curvemole.core.models import Model\nfrom curvemole.core.registry import default_registry\n\n\ndef test_background_is_a_component_property_and_serialises() -> None:\n    component = Component.create(\"gaussian\")\n    component.is_background = True\n    clone = Component.from_dict(component.to_dict())\n    assert clone.is_background is True\n\n\ndef test_any_function_can_be_marked_as_background() -> None:\n    registry = default_registry()\n    assert registry.get(\"constant\").kind == \"generic\"\n    assert registry.get(\"linear\").kind == \"generic\"\n    assert registry.get(\"polynomial\").kind == \"generic\"\n    assert registry.get(\"cubic_spline\").kind == \"generic\"\n\n    model = Model()\n    gaussian = Component.create(\n        \"gaussian\",\n        initial={\"area\": 2.0, \"center\": 0.0, \"sigma\": 1.0},\n    )\n    gaussian.is_background = True\n    model.add(gaussian)\n    x = np.array([-1.0, 0.0, 1.0])\n    result = model.background(x, curve_id=\"curve\", registry=registry)\n    expected = registry.get(\"gaussian\").evaluate(\n        x, {name: parameter.value for name, parameter in gaussian.parameters.items()}, {}\n    )\n    assert result == pytest.approx(expected)\n\n\ndef test_explicit_background_selection_can_designate_unmarked_components() -> None:\n    model = Model()\n    component = Component.create(\"constant\", initial={\"offset\": 3.0})\n    model.add(component)\n    x = np.arange(4.0)\n    assert model.background(x, curve_id=\"curve\") == pytest.approx(np.zeros(4))\n    assert model.background(\n        x, curve_id=\"curve\", component_ids={component.id}\n    ) == pytest.approx(np.full(4, 3.0))\n\n\ndef test_background_rejects_non_additive_component_composition() -> None:\n    model = Model()\n    component = Component.create(\"constant\", initial={\"offset\": 2.0}, operator=\"multiply\")\n    component.is_background = True\n    model.add(component)\n    with pytest.raises(Exception, match=\"must use add or subtract\"):\n        model.background(np.arange(3.0), curve_id=\"curve\")\n''',
    encoding="utf-8",
)

(ROOT / "tests/test_background_gui.py").write_text(
    '''from __future__ import annotations\n\nimport pytest\n\npytest.importorskip(\"PySide6\", exc_type=ImportError)\npytest.importorskip(\"pyqtgraph\", exc_type=ImportError)\n\nfrom PySide6.QtCore import Qt\nfrom PySide6.QtWidgets import QApplication\n\nfrom curvemole import Component, Curve, Project\nfrom curvemole.gui.dialogs import AddComponentDialog, BackgroundComponentsDialog\nfrom curvemole.gui.main_window import MainWindow\nfrom curvemole.gui.plot import PlotWorkspace\nfrom curvemole.core.registry import default_registry\n\n\ndef make_project() -> tuple[Project, Curve, Component, Component]:\n    project = Project(\"Background UX\")\n    curve = Curve(\"curve\", [0.0, 1.0, 2.0], [3.0, 4.0, 3.0])\n    project.add_curve(curve)\n    first = Component.create(\"constant\", initial={\"offset\": 3.0})\n    second = Component.create(\"gaussian\")\n    project.model_for(curve.id).add(first)\n    project.model_for(curve.id).add(second)\n    project.dirty = False\n    return project, curve, first, second\n\n\ndef test_add_component_dialog_does_not_label_functions_as_background() -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, _, _ = make_project()\n    dialog = AddComponentDialog(default_registry(), curve)\n    labels = [dialog.function.itemText(index) for index in range(dialog.function.count())]\n    assert \"Constant\" in labels\n    assert \"Cubic spline\" in labels\n    assert all(\" — background\" not in label for label in labels)\n    dialog.close()\n    app.processEvents()\n\n\ndef test_subtract_dialog_first_designates_then_selects_marked_backgrounds() -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, first, second = make_project()\n    dialog = BackgroundComponentsDialog(project, curve.id, default_registry())\n    assert dialog.marking_mode is True\n    assert dialog.components.count() == 2\n    dialog.components.item(0).setCheckState(Qt.CheckState.Checked)\n    assert len(dialog.selected_component_ids()) == 1\n    dialog.close()\n\n    first.is_background = True\n    marked = BackgroundComponentsDialog(project, curve.id, default_registry())\n    assert marked.marking_mode is False\n    assert marked.components.count() == 1\n    assert marked.selected_component_ids() == [first.id]\n    marked.close()\n    app.processEvents()\n\n\ndef test_model_panel_can_mark_selected_component_as_background() -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, first, _ = make_project()\n    window = MainWindow(project)\n    window._set_component(first.id)\n    window.model_panel.background_toggle.setChecked(True)\n    assert first.is_background is True\n    assert \"Background\" in window.model_panel.components.currentItem().text()\n    project.dirty = False\n    window.close()\n    app.processEvents()\n\n\ndef test_spline_points_outside_data_do_not_change_view_range() -> None:\n    app = QApplication.instance() or QApplication([])\n    project, curve, _, _ = make_project()\n    workspace = PlotWorkspace(default_registry())\n    workspace.set_context(project, curve.id, {curve.id}, None)\n    workspace.plot.setXRange(-1.0, 3.0, padding=0)\n    workspace.plot.setYRange(-2.0, 6.0, padding=0)\n    before = workspace.view_box.viewRange()\n    workspace.begin_spline_placement(\"Spline\")\n    workspace._add_spline_point(10.0, 20.0)\n    workspace._add_spline_point(12.0, 18.0)\n    after = workspace.view_box.viewRange()\n    assert workspace._spline_points == [(10.0, 20.0), (12.0, 18.0)]\n    assert after[0] == pytest.approx(before[0])\n    assert after[1] == pytest.approx(before[1])\n    workspace.cancel_placement()\n    workspace.close()\n    app.processEvents()\n''',
    encoding="utf-8",
)

print("Function/background/spline UX patch applied")
