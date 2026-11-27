"""Explicit semantic roles for parameters of user-defined peak functions.

Function Builder peak roles are optional metadata.  They let graphical placement
and automatic peak detection initialise custom functions without guessing from
parameter names.  Older custom functions remain compatible through the legacy
name-based initialiser when no role metadata is present.
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QTableWidget, QTableWidgetItem

import curvemole.gui.quick_function_library as quick_library
from curvemole.core.expressions import expression_parameters
from curvemole.core.functions import formula_definition
from curvemole.core.peak_roles import ROLE_CHOICES as _ROLE_CHOICES  # noqa: E402
from curvemole.core.plugins import export_custom_function
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import FunctionBuilderPanel

_ORIGINAL_PANEL_INIT = FunctionBuilderPanel.__init__
_ORIGINAL_PANEL_VALIDATE = FunctionBuilderPanel._validate


def _roles_from_table(panel: FunctionBuilderPanel) -> dict[str, str]:
    table = getattr(panel, "peak_roles_table", None)
    if not isinstance(table, QTableWidget):
        return {}
    result: dict[str, str] = {}
    used: dict[str, str] = {}
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        combo = table.cellWidget(row, 1)
        if item is None or not isinstance(combo, QComboBox):
            continue
        name = item.text()
        role = str(combo.currentData() or "")
        if not role:
            continue
        if role in used:
            raise ValueError(
                panel.tr("The role '")
                + combo.currentText()
                + panel.tr("' is assigned to more than one parameter: ")
                + used[role]
                + ", "
                + name
                + "."
            )
        used[role] = name
        result[name] = role

    scale_parameters = [name for name, role in result.items() if role in {"height", "area"}]
    if len(scale_parameters) > 1:
        raise ValueError(
            panel.tr(
                "Choose either a Peak height parameter or a Peak area / integral parameter, not both."
            )
        )
    return result


def _refresh_role_table(panel: FunctionBuilderPanel, parameter_names: tuple[str, ...]) -> None:
    table = getattr(panel, "peak_roles_table", None)
    if not isinstance(table, QTableWidget):
        return

    previous: dict[str, str] = {}
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        combo = table.cellWidget(row, 1)
        if item is not None and isinstance(combo, QComboBox):
            previous[item.text()] = str(combo.currentData() or "")

    table.setRowCount(len(parameter_names))
    for row, name in enumerate(parameter_names):
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 0, item)

        combo = QComboBox(table)
        for identifier, label in _ROLE_CHOICES:
            combo.addItem(panel.tr(label), identifier)
        index = combo.findData(previous.get(name, ""))
        combo.setCurrentIndex(max(0, index))
        table.setCellWidget(row, 1, combo)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


def _update_role_visibility(panel: FunctionBuilderPanel) -> None:
    peak = str(panel.kind.currentData()) == "peak"
    note = getattr(panel, "peak_roles_note", None)
    table = getattr(panel, "peak_roles_table", None)
    if isinstance(note, QLabel):
        note.setVisible(peak)
    if isinstance(table, QTableWidget):
        table.setVisible(peak)


def _panel_init(
    panel: FunctionBuilderPanel,
    registry: FunctionRegistry,
    parent: Any | None = None,
) -> None:
    _ORIGINAL_PANEL_INIT(panel, registry, parent)

    panel.peak_roles_note = QLabel(
        panel.tr(
            "Optional — only for peak functions. Assigning a meaning to parameters helps CurveMole "
            "place the peak correctly, initialise automatic peak searches, and interpret the function. "
            "Leave a role as Not specified when it is not applicable."
        )
    )
    panel.peak_roles_note.setWordWrap(True)
    panel.peak_roles_table = QTableWidget(0, 2, panel)
    panel.peak_roles_table.setHorizontalHeaderLabels(
        [panel.tr("Parameter"), panel.tr("Meaning for CurveMole")]
    )
    panel.peak_roles_table.verticalHeader().setVisible(False)
    panel.peak_roles_table.setMinimumHeight(140)
    panel.peak_roles_table.setMaximumHeight(230)

    layout = panel.layout()
    # FunctionBuilderPanel uses QFormLayout. Insert directly after Detected parameters.
    layout.insertRow(5, panel.peak_roles_note)
    layout.insertRow(6, panel.tr("Peak parameter roles"), panel.peak_roles_table)
    panel.kind.currentIndexChanged.connect(lambda *_: _update_role_visibility(panel))
    panel._validate()
    _update_role_visibility(panel)


def _panel_validate(panel: FunctionBuilderPanel) -> bool:
    valid = _ORIGINAL_PANEL_VALIDATE(panel)
    table = getattr(panel, "peak_roles_table", None)
    if not isinstance(table, QTableWidget):
        return valid
    if not valid:
        table.setRowCount(0)
        return False
    try:
        names = expression_parameters(panel.formula.toPlainText())
    except Exception:
        table.setRowCount(0)
        return False
    _refresh_role_table(panel, names)
    return True


def _derived_formulas(panel: FunctionBuilderPanel, roles: dict[str, str]) -> dict[str, str]:
    derived: dict[str, str] = {}
    if panel.derived_area.text().strip():
        derived["area"] = panel.derived_area.text().strip()
    if panel.derived_fwhm.text().strip():
        derived["FWHM"] = panel.derived_fwhm.text().strip()

    by_role = {role: name for name, role in roles.items()}
    if "area" not in derived and "area" in by_role:
        derived["area"] = by_role["area"]
    if "FWHM" not in derived:
        if "fwhm" in by_role:
            derived["FWHM"] = by_role["fwhm"]
        elif "sigma" in by_role:
            derived["FWHM"] = f"2.354820045*{by_role['sigma']}"
        elif "hwhm" in by_role:
            derived["FWHM"] = f"2*{by_role['hwhm']}"
    return derived


def _definition_from_builder(panel: FunctionBuilderPanel, identifier: str) -> Any:
    kind = str(panel.kind.currentData())
    roles = _roles_from_table(panel) if kind == "peak" else {}
    definition = formula_definition(
        identifier,
        panel.display_name.text().strip() or identifier,
        panel.formula.toPlainText(),
        kind=kind,
        derived_formulas=_derived_formulas(panel, roles),
    )
    if kind == "peak":
        # Store the key even when empty. Its presence means the user explicitly
        # chose role-based semantics, so the legacy parameter-name heuristic is not used.
        definition.custom_metadata["peak_roles"] = dict(roles)
    return definition


def _store_in_project(panel: FunctionBuilderPanel, definition: Any) -> None:
    if panel.project is None:
        return
    identifier = definition.identifier
    panel.project.custom_functions = [
        value
        for value in panel.project.custom_functions
        if value.get("identifier") != identifier
    ]
    panel.project.custom_functions.append(
        {
            "identifier": identifier,
            "display_name": definition.display_name,
            "kind": definition.kind,
            **definition.custom_metadata,
        }
    )
    panel.project.touch()


def _builder_add(panel: FunctionBuilderPanel) -> None:
    if not panel._validate():
        return
    identifier = re.sub(
        r"[^a-z0-9_]+", "_", panel.identifier.text().strip().lower()
    ).strip("_")
    if not identifier:
        QMessageBox.warning(panel, panel.tr("Function Builder"), panel.tr("Enter an identifier."))
        return

    try:
        definition = _definition_from_builder(panel, identifier)
    except Exception as exc:
        QMessageBox.warning(panel, panel.tr("Function Builder"), str(exc))
        return

    host = panel.window()
    if not isinstance(host, MainWindow):
        try:
            panel.registry.register_custom(definition, replace=True)
            _store_in_project(panel, definition)
            panel.functionAdded.emit(identifier)
            QMessageBox.information(panel, panel.tr("Function Builder"), panel.tr("Function added."))
        except Exception as exc:
            QMessageBox.warning(panel, panel.tr("Function Builder"), str(exc))
        return

    directory = quick_library._choose_library_directory(host)
    if directory is None:
        return
    destination = directory / f"{identifier}{quick_library._FUNCTION_SUFFIX}"
    try:
        export_custom_function(definition, destination)
        panel.registry.register_custom(definition, replace=True)
        _store_in_project(panel, definition)
        panel.functionAdded.emit(identifier)
        quick_library._refresh_quick_function_selector(host)
        QMessageBox.information(
            panel,
            panel.tr("Function Builder"),
            panel.tr("Function added and saved in the reusable library:") + f"\n{destination}",
        )
    except Exception as exc:
        QMessageBox.warning(panel, panel.tr("Function Builder"), str(exc))


def _install() -> None:
    if getattr(MainWindow, "_curvemole_peak_parameter_roles", False):
        return

    FunctionBuilderPanel.__init__ = _panel_init
    FunctionBuilderPanel._validate = _panel_validate
    FunctionBuilderPanel._add = _builder_add
    FunctionBuilderPanel.peak_parameter_roles = _roles_from_table

    # Role-based initialisation, import and project loading live in
    # curvemole.core.peak_roles, so the core functions are never replaced here.
    MainWindow._curvemole_peak_parameter_roles = True


_install()
