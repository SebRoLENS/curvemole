from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one match in {path}: {old[:80]!r}; found {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


# dialogs.py: selection helpers, graphical parameter-link picker and cross-spectrum validation.
replace_once(
    "src/curvemole/gui/dialogs.py",
    "from dataclasses import asdict\nfrom pathlib import Path\nfrom typing import Any\n",
    "from dataclasses import asdict\nfrom pathlib import Path\nfrom typing import Any\n",
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    "from curvemole.core.fitting import FitMode, FitPlan, FitSettings\n",
    "from curvemole.core.expressions import SafeExpression\nfrom curvemole.core.fitting import FitMode, FitPlan, FitSettings\n",
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    "from curvemole.version import __version__\n\n\nclass ImportMappingDialog(QDialog):\n",
    '''from curvemole.version import __version__\n\n\ndef _set_list_checked(widget: QListWidget, checked: bool) -> None:\n    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked\n    for index in range(widget.count()):\n        item = widget.item(index)\n        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:\n            item.setCheckState(state)\n\n\ndef _set_table_checked(table: QTableWidget, column: int, checked: bool) -> None:\n    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked\n    for row in range(table.rowCount()):\n        item = table.item(row, column)\n        if item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:\n            item.setCheckState(state)\n\n\nclass ImportMappingDialog(QDialog):\n''',
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    "        layout.addWidget(mapping_box)\n\n        self.apply_all = QCheckBox",
    '''        layout.addWidget(mapping_box)\n        y_buttons = QHBoxLayout()\n        self.select_all_y_button = QPushButton(self.tr("Select all Y columns"))\n        self.deselect_all_y_button = QPushButton(self.tr("Deselect all Y columns"))\n        self.select_all_y_button.clicked.connect(lambda: _set_list_checked(self.y_columns, True))\n        self.deselect_all_y_button.clicked.connect(lambda: _set_list_checked(self.y_columns, False))\n        y_buttons.addWidget(self.select_all_y_button)\n        y_buttons.addWidget(self.deselect_all_y_button)\n        y_buttons.addStretch(1)\n        layout.addLayout(y_buttons)\n\n        self.apply_all = QCheckBox''',
)

parameter_link_dialog = r'''

class ParameterLinkDialog(QDialog):
    """Graphical editor for a parameter dependency."""

    def __init__(
        self,
        project: Project,
        target_curve_id: str,
        target_component_id: str,
        target_parameter: str,
        current_link: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.target_curve_id = target_curve_id
        self.target_component_id = target_component_id
        self.target_parameter = target_parameter
        self._result_link = current_link
        target_curve = project.dataset.curve(target_curve_id)
        target_component = project.model_for(target_curve_id).component(target_component_id)

        self.setWindowTitle(self.tr("Link parameter"))
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        title = QLabel(
            self.tr("Link ")
            + f"<b>{target_curve.name} / {target_component.name} / {target_parameter}</b>"
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(
            self.tr(
                "Choose the parameter that should control this value. CurveMole creates the "
                "internal reference automatically. Links between different spectra require a "
                "Global simultaneous fit."
            )
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.source_curve = QComboBox()
        self.source_component = QComboBox()
        self.source_parameter = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Equal to source"), "equal")
        self.mode.addItem(self.tr("Advanced expression"), "advanced")
        self.advanced = QLineEdit()
        self.advanced.setPlaceholderText("2 * ${source} + 1")
        self.advanced_help = QLabel(
            self.tr("Use ${source} for the selected source parameter, for example: 2 * ${source} + 1")
        )
        self.advanced_help.setWordWrap(True)
        form.addRow(self.tr("Source spectrum"), self.source_curve)
        form.addRow(self.tr("Source component"), self.source_component)
        form.addRow(self.tr("Source parameter"), self.source_parameter)
        form.addRow(self.tr("Relationship"), self.mode)
        form.addRow(self.tr("Expression"), self.advanced)
        form.addRow("", self.advanced_help)
        layout.addLayout(form)

        for curve in project.curves:
            self.source_curve.addItem(curve.name, curve.id)
        self.source_curve.currentIndexChanged.connect(self._populate_components)
        self.source_component.currentIndexChanged.connect(self._populate_parameters)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self._populate_components()
        self._load_current(current_link)
        self._update_mode()

        action_row = QHBoxLayout()
        remove = QPushButton(self.tr("Remove link"))
        remove.clicked.connect(self._remove_link)
        action_row.addWidget(remove)
        action_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        action_row.addWidget(buttons)
        layout.addLayout(action_row)

    def _populate_components(self) -> None:
        curve_id = self.source_curve.currentData()
        previous = self.source_component.currentData()
        self.source_component.clear()
        if curve_id:
            for component in self.project.model_for(str(curve_id)).components:
                self.source_component.addItem(component.name, component.id)
        index = self.source_component.findData(previous)
        if index >= 0:
            self.source_component.setCurrentIndex(index)
        self._populate_parameters()

    def _populate_parameters(self) -> None:
        curve_id = self.source_curve.currentData()
        component_id = self.source_component.currentData()
        previous = self.source_parameter.currentData()
        self.source_parameter.clear()
        if not curve_id or not component_id:
            return
        component = self.project.model_for(str(curve_id)).component(str(component_id))
        for name in component.parameters:
            if (
                str(curve_id) == self.target_curve_id
                and str(component_id) == self.target_component_id
                and name == self.target_parameter
            ):
                continue
            self.source_parameter.addItem(name, name)
        index = self.source_parameter.findData(previous)
        if index >= 0:
            self.source_parameter.setCurrentIndex(index)

    def _source_path(self) -> str | None:
        curve_id = self.source_curve.currentData()
        component_id = self.source_component.currentData()
        parameter = self.source_parameter.currentData()
        if not curve_id or not component_id or not parameter:
            return None
        return f"{curve_id}.{component_id}.{parameter}"

    def _select_source_path(self, path: str) -> bool:
        parts = path.split(".", 2)
        if len(parts) != 3:
            return False
        curve_id, component_id, parameter = parts
        curve_index = self.source_curve.findData(curve_id)
        if curve_index < 0:
            return False
        self.source_curve.setCurrentIndex(curve_index)
        component_index = self.source_component.findData(component_id)
        if component_index < 0:
            return False
        self.source_component.setCurrentIndex(component_index)
        parameter_index = self.source_parameter.findData(parameter)
        if parameter_index < 0:
            return False
        self.source_parameter.setCurrentIndex(parameter_index)
        return True

    def _load_current(self, current_link: str | None) -> None:
        if not current_link:
            return
        try:
            expression = SafeExpression.compile(current_link)
        except Exception:
            self.mode.setCurrentIndex(self.mode.findData("advanced"))
            self.advanced.setText(current_link)
            return
        references = expression.references
        if references:
            self._select_source_path(references[0])
        exact = len(references) == 1 and current_link.strip() == f"${{{references[0]}}}"
        if exact:
            self.mode.setCurrentIndex(self.mode.findData("equal"))
        else:
            self.mode.setCurrentIndex(self.mode.findData("advanced"))
            if references:
                self.advanced.setText(current_link.replace(f"${{{references[0]}}}", "${source}", 1))
            else:
                self.advanced.setText(current_link)

    def _update_mode(self) -> None:
        advanced = self.mode.currentData() == "advanced"
        self.advanced.setVisible(advanced)
        self.advanced_help.setVisible(advanced)

    def link_expression(self) -> str | None:
        source = self._source_path()
        if source is None:
            return None
        reference = f"${{{source}}}"
        if self.mode.currentData() == "equal":
            return reference
        expression = self.advanced.text().strip() or "${source}"
        return expression.replace("${source}", reference)

    def selected_link(self) -> str | None:
        return self._result_link

    def _remove_link(self) -> None:
        self._result_link = None
        self.accept()

    def _accept(self) -> None:
        link = self.link_expression()
        if not link:
            QMessageBox.warning(
                self,
                self.tr("Link parameter"),
                self.tr("Choose a source parameter or use Remove link."),
            )
            return
        try:
            SafeExpression.compile(link)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("Link parameter"), str(exc))
            return
        self._result_link = link
        self.accept()
'''
replace_once(
    "src/curvemole/gui/dialogs.py",
    "\n\nclass FitPlanDialog(QDialog):\n",
    parameter_link_dialog + "\n\nclass FitPlanDialog(QDialog):\n",
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    "        self.curves.resizeColumnsToContents()\n        layout.addWidget(self.curves)\n        self.equal_contribution",
    '''        self.curves.resizeColumnsToContents()\n        layout.addWidget(self.curves)\n        curve_buttons = QHBoxLayout()\n        self.select_all_curves_button = QPushButton(self.tr("Select all"))\n        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))\n        self.select_all_curves_button.clicked.connect(lambda: _set_table_checked(self.curves, 0, True))\n        self.deselect_all_curves_button.clicked.connect(lambda: _set_table_checked(self.curves, 0, False))\n        curve_buttons.addWidget(self.select_all_curves_button)\n        curve_buttons.addWidget(self.deselect_all_curves_button)\n        curve_buttons.addStretch(1)\n        layout.addLayout(curve_buttons)\n        self.equal_contribution''',
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    '''    def _accept(self) -> None:\n        try:\n            self.plan().validate()\n        except Exception as exc:\n            QMessageBox.warning(self, self.tr("Fit plan"), str(exc))\n            return\n        self.accept()\n\n\nclass CopyFitDialog''',
    '''    def _validate_link_scope(self, plan: FitPlan) -> None:\n        selected = set(plan.curve_ids)\n        for curve_id in plan.curve_ids:\n            model = self.project.model_for(curve_id)\n            for component in model.components:\n                for parameter in component.parameters.values():\n                    if not parameter.link:\n                        continue\n                    for reference in SafeExpression.compile(parameter.link).references:\n                        source_curve_id = reference.split(".", 1)[0]\n                        if source_curve_id == curve_id:\n                            continue\n                        if source_curve_id not in selected:\n                            raise ValueError(\n                                self.tr(\n                                    "A linked parameter depends on another spectrum that is not selected. "\n                                    "Select both the source and target spectra."\n                                )\n                            )\n                        if plan.mode != FitMode.GLOBAL:\n                            raise ValueError(\n                                self.tr(\n                                    "This fit contains parameter links between different spectra. "\n                                    "Choose Global simultaneous mode to apply those constraints."\n                                )\n                            )\n\n    def _accept(self) -> None:\n        try:\n            plan = self.plan()\n            plan.validate()\n            self._validate_link_scope(plan)\n        except Exception as exc:\n            QMessageBox.warning(self, self.tr("Fit plan"), str(exc))\n            return\n        self.accept()\n\n\nclass CopyFitDialog''',
)
replace_once(
    "src/curvemole/gui/dialogs.py",
    "        layout.addWidget(self.targets)\n        self.structure = QCheckBox",
    '''        layout.addWidget(self.targets)\n        target_buttons = QHBoxLayout()\n        self.select_all_targets_button = QPushButton(self.tr("Select all"))\n        self.deselect_all_targets_button = QPushButton(self.tr("Deselect all"))\n        self.select_all_targets_button.clicked.connect(lambda: _set_list_checked(self.targets, True))\n        self.deselect_all_targets_button.clicked.connect(lambda: _set_list_checked(self.targets, False))\n        target_buttons.addWidget(self.select_all_targets_button)\n        target_buttons.addWidget(self.deselect_all_targets_button)\n        target_buttons.addStretch(1)\n        layout.addLayout(target_buttons)\n        self.structure = QCheckBox''',
)

# panels.py: replace raw link editing with a readable button.
replace_once(
    "src/curvemole/gui/panels.py",
    "from curvemole.core.expressions import expression_parameters\n",
    "from curvemole.core.expressions import SafeExpression, expression_parameters\n",
)
replace_once(
    "src/curvemole/gui/panels.py",
    "    parameterChangeRequested = Signal(str, str, str, object)\n    copyFitRequested = Signal()\n",
    "    parameterChangeRequested = Signal(str, str, str, object)\n    parameterLinkRequested = Signal(str, str)\n    copyFitRequested = Signal()\n",
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''                link = QTableWidgetItem(parameter.link or "")\n                link.setData(Qt.ItemDataRole.UserRole, (component.id, name, "link"))\n                self.parameters.setItem(row, 6, link)\n''',
    '''                link_button = QPushButton(self._link_button_text(parameter.link))\n                link_button.setToolTip(parameter.link or self.tr("Choose a source parameter"))\n                link_button.clicked.connect(\n                    lambda checked=False, component_id=component.id, parameter_name=name: (\n                        self.parameterLinkRequested.emit(component_id, parameter_name)\n                    )\n                )\n                self.parameters.setCellWidget(row, 6, link_button)\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    "    def _component_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:\n",
    '''    def _link_button_text(self, link: str | None) -> str:\n        if not link:\n            return self.tr("Set link…")\n        if self.project is None:\n            return self.tr("Linked…")\n        try:\n            expression = SafeExpression.compile(link)\n            references = expression.references\n            if len(references) != 1:\n                return self.tr("Linked (advanced)…")\n            curve_id, component_id, parameter_name = references[0].split(".", 2)\n            curve = self.project.dataset.curve(curve_id)\n            component = self.project.model_for(curve_id).component(component_id)\n            exact = link.strip() == f"${{{references[0]}}}"\n            prefix = self.tr("Linked → ") if exact else self.tr("Linked (advanced) → ")\n            return prefix + f"{curve.name} / {component.name} / {parameter_name}"\n        except Exception:\n            return self.tr("Linked (advanced)…")\n\n    def _component_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:\n''',
)
replace_once(
    "src/curvemole/gui/panels.py",
    '''            if field == "fixed":\n                value: Any = item.checkState() == Qt.CheckState.Checked\n            elif field == "link":\n                value = item.text().strip() or None\n            elif field == "minimum":\n''',
    '''            if field == "fixed":\n                value: Any = item.checkState() == Qt.CheckState.Checked\n            elif field == "minimum":\n''',
)

# main_window.py: curve selection controls, graphical link editor, PySide network enum fix.
replace_once(
    "src/curvemole/gui/main_window.py",
    "from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest\n",
    "from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest\n",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "    QFileDialog,\n    QInputDialog,\n",
    "    QFileDialog,\n    QHBoxLayout,\n    QInputDialog,\n",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "    QProgressBar,\n    QStyle,\n",
    "    QProgressBar,\n    QPushButton,\n    QStyle,\n",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "    ImportMappingDialog,\n    PluginManagerDialog,\n",
    "    ImportMappingDialog,\n    ParameterLinkDialog,\n    PluginManagerDialog,\n",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "    def _active_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:\n",
    '''    def select_all_curves(self) -> None:\n        self.clearSelection()\n        for top_index in range(self.topLevelItemCount()):\n            parent = self.topLevelItem(top_index)\n            if parent.isHidden():\n                continue\n            for child_index in range(parent.childCount()):\n                child = parent.child(child_index)\n                if not child.isHidden():\n                    child.setSelected(True)\n\n    def deselect_all_curves(self) -> None:\n        self.clearSelection()\n\n    def _active_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    '''        self.curve_tree = CurveTree()\n        left_layout.addWidget(self.curve_filter)\n        left_layout.addWidget(self.curve_tree)\n''',
    '''        self.curve_tree = CurveTree()\n        left_layout.addWidget(self.curve_filter)\n        selection_row = QHBoxLayout()\n        self.select_all_curves_button = QPushButton(self.tr("Select all"))\n        self.deselect_all_curves_button = QPushButton(self.tr("Deselect all"))\n        self.select_all_curves_button.clicked.connect(self.curve_tree.select_all_curves)\n        self.deselect_all_curves_button.clicked.connect(self.curve_tree.deselect_all_curves)\n        selection_row.addWidget(self.select_all_curves_button)\n        selection_row.addWidget(self.deselect_all_curves_button)\n        selection_row.addStretch(1)\n        left_layout.addLayout(selection_row)\n        left_layout.addWidget(self.curve_tree)\n''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n        self.model_panel.copyFitRequested.connect(self.copy_fit)\n",
    "        self.model_panel.parameterChangeRequested.connect(self.change_parameter)\n        self.model_panel.parameterLinkRequested.connect(self.edit_parameter_link)\n        self.model_panel.copyFitRequested.connect(self.copy_fit)\n",
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "\n    def copy_fit(self) -> None:\n",
    r'''
    def edit_parameter_link(self, component_id: str, name: str) -> None:
        if not self.active_curve_id:
            return
        parameter = self.project.model_for(self.active_curve_id).component(component_id).parameters[name]
        dialog = ParameterLinkDialog(
            self.project,
            self.active_curve_id,
            component_id,
            name,
            parameter.link,
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.change_parameter(component_id, name, "link", dialog.selected_link())

    def copy_fit(self) -> None:
''',
)
replace_once(
    "src/curvemole/gui/main_window.py",
    "            if int(reply.error()) != 0:\n",
    "            if reply.error() != QNetworkReply.NetworkError.NoError:\n",
)

# Tests.
replace_once(
    "tests/test_gui_smoke.py",
    "from PySide6.QtCore import QPointF, Qt\nfrom PySide6.QtWidgets import QApplication, QFileDialog\n",
    "from PySide6.QtCore import QPointF, Qt\nfrom PySide6.QtNetwork import QNetworkReply\nfrom PySide6.QtWidgets import QApplication, QFileDialog\n",
)
replace_once(
    "tests/test_gui_smoke.py",
    "from curvemole.core.fitting import FitPlan\n",
    "from curvemole.core.fitting import FitMode, FitPlan, FitSettings\n",
)
replace_once(
    "tests/test_gui_smoke.py",
    "from curvemole.gui.main_window import (\n",
    "from curvemole.gui.dialogs import CopyFitDialog, FitPlanDialog, ImportMappingDialog, ParameterLinkDialog\nfrom curvemole.gui.main_window import (\n",
)
append_once(
    "tests/test_gui_smoke.py",
    "def test_bulk_selection_controls",
    r'''
def test_bulk_selection_controls(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Bulk selection")
    curves = [
        Curve(f"curve {index}", [0.0, 1.0, 2.0], [0.0, float(index), 0.0])
        for index in range(1, 4)
    ]
    for curve in curves:
        project.add_curve(curve)
    project.dirty = False

    window = MainWindow(project)
    window.curve_tree.select_all_curves()
    assert window.curve_tree.selected_curve_ids() == {curve.id for curve in curves}
    window.curve_tree.deselect_all_curves()
    assert window.curve_tree.selected_curve_ids() == set()

    fit = FitPlanDialog(project, set(), FitSettings())
    fit.deselect_all_curves_button.click()
    assert all(
        fit.curves.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(fit.curves.rowCount())
    )
    fit.select_all_curves_button.click()
    assert all(
        fit.curves.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(fit.curves.rowCount())
    )

    copy_dialog = CopyFitDialog(project, curves[0].id)
    copy_dialog.select_all_targets_button.click()
    assert len(copy_dialog.choices()[0]) == 2
    copy_dialog.deselect_all_targets_button.click()
    assert copy_dialog.choices()[0] == []

    data = tmp_path / "multi.csv"
    data.write_text("x,y1,y2\n0,1,2\n1,2,3\n", encoding="utf-8")
    importer = ImportMappingDialog(data)
    importer.select_all_y_button.click()
    assert all(
        importer.y_columns.item(index).checkState() == Qt.CheckState.Checked
        for index in range(importer.y_columns.count())
    )
    importer.deselect_all_y_button.click()
    assert all(
        importer.y_columns.item(index).checkState() == Qt.CheckState.Unchecked
        for index in range(importer.y_columns.count())
    )

    project.dirty = False
    window.close()
    app.processEvents()


def test_parameter_link_picker_and_global_fit_requirement() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Links")
    first = Curve("Spectrum A", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    second = Curve("Spectrum B", [0.0, 1.0, 2.0], [0.0, 1.2, 0.0])
    project.add_curve(first)
    project.add_curve(second)
    first_peak = Component.create("gaussian", name="Peak A")
    second_peak = Component.create("gaussian", name="Peak B")
    project.model_for(first.id).add(first_peak)
    project.model_for(second.id).add(second_peak)

    dialog = ParameterLinkDialog(project, first.id, first_peak.id, "center")
    dialog.source_curve.setCurrentIndex(dialog.source_curve.findData(second.id))
    dialog.source_component.setCurrentIndex(dialog.source_component.findData(second_peak.id))
    dialog.source_parameter.setCurrentIndex(dialog.source_parameter.findData("center"))
    expected = f"${{{second.id}.{second_peak.id}.center}}"
    assert dialog.link_expression() == expected

    dialog.mode.setCurrentIndex(dialog.mode.findData("advanced"))
    dialog.advanced.setText("2 * ${source} + 1")
    assert dialog.link_expression() == f"2 * {expected} + 1"

    first_peak.parameters["center"].link = expected
    fit_dialog = FitPlanDialog(project, {first.id, second.id}, FitSettings())
    independent = fit_dialog.plan()
    independent.mode = FitMode.INDEPENDENT
    with pytest.raises(ValueError, match="Global simultaneous"):
        fit_dialog._validate_link_scope(independent)
    independent.mode = FitMode.GLOBAL
    fit_dialog._validate_link_scope(independent)
    app.processEvents()


def test_update_check_accepts_qnetworkreply_error_enum() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class FakeReply:
        deleted = False

        def error(self):
            return QNetworkReply.NetworkError.ConnectionRefusedError

        def errorString(self) -> str:
            return "offline"

        def deleteLater(self) -> None:
            self.deleted = True

    reply = FakeReply()
    window._update_reply = reply
    window._update_check_finished(reply, False)
    assert reply.deleted
    assert window._update_reply is None
    window.close()
    app.processEvents()
''',
)

# Manual: make the new selection and link workflows explicit.
replace_once(
    "docs/manual.md",
    "- Use Ctrl-click or Shift-click for a multi-selection.\n",
    "- Use Ctrl-click or Shift-click for a multi-selection, or use **Select all** and **Deselect all** above the tree.\n",
)
replace_once(
    "docs/manual.md",
    "Choose exactly one x column and one or more y columns. Each selected y column becomes\na separate curve sharing the selected x column. The Python API additionally supports\nexplicit x-y column pairs.\n",
    "Choose exactly one x column and one or more y columns. Each selected y column becomes\na separate curve sharing the selected x column. Use **Select all Y columns** or\n**Deselect all Y columns** when importing tables with many signals. The Python API\nadditionally supports explicit x-y column pairs.\n",
)
replace_once(
    "docs/manual.md",
    "| Link | Restricted expression controlling this parameter |\n\nAn edit is validated immediately.",
    "| Link | Graphical **Set link…** control; linked parameters show their source in readable form |\n\nPress **Set link…** to choose a source spectrum, component, and parameter. The default\nrelationship is **Equal to source**. Choose **Advanced expression** for relationships such\nas `2 * ${source} + 1`. Use **Remove link** to make the parameter independent again.\n\nAn edit is validated immediately.",
)
replace_once(
    "docs/manual.md",
    '''Internal curve and component identifiers are preserved in `.fitproj`, YAML-derived\nobjects, Python objects, and machine-readable exports. In Preview 0.2.3, the GUI does\nnot yet provide a dedicated path picker. Complex cross-curve links are therefore\nmost reliably prepared through the Python API or a reproducible workflow and then\ninspected in the GUI.\n''',
    '''The graphical **Set link…** dialog creates these paths automatically, so normal GUI\nuse does not require knowing curve or component identifiers. The canonical expression is\nstill shown as a tooltip and remains available to advanced workflows, Python code, and\nmachine-readable exports. For a link between different spectra, select both spectra and\nuse **Global simultaneous** mode; CurveMole blocks incompatible fit modes with an explicit\nmessage.\n''',
)
replace_once(
    "docs/manual.md",
    "**Model > Copy fit** copies selected information from the active curve. Options\ninclude:\n",
    "**Model > Copy fit** copies selected information from the active curve. Use **Select all**\nor **Deselect all** when choosing many target curves. Options include:\n",
)
replace_once(
    "docs/manual.md",
    "1. confirm the active and selected curves;\n",
    "1. confirm the active and selected curves; use **Select all** / **Deselect all** when appropriate;\n",
)

print("CurveMole UX patch applied")
