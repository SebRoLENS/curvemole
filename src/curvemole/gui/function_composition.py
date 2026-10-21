"""Shared insertion composition for the Functions block and add dialogs."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QToolButton

from curvemole.gui.icons import PaletteIconEngine, vector_icon

OPERATORS = (
    ("add", "+", "Add"),
    ("subtract", "−", "Subtract"),
    ("multiply", "×", "Multiply"),
    ("divide", "÷", "Divide"),
    ("convolve", "∗", "Convolve"),
)
_SETTING = "function_controls/composition"


def selected_operator(window):
    value = str(window.settings.value(_SETTING, "add"))
    return value if value in {item[0] for item in OPERATORS} else "add"


def operator_available(window, operator):
    if not window.active_curve_id:
        return False
    model = window.project.model_for(window.active_curve_id)
    return model.composition_mode == "global" or operator in {"add", "subtract"} or any(
        component.enabled for component in model.components)


def ensure_insertion_operator(window):
    if operator_available(window, selected_operator(window)):
        return True
    window._notify(window.tr(
        "Multiplication, division and convolution need an existing enabled model function. "
        "Choose Add or Subtract to start the model."
    ), warning=True)
    return False


def composition_icon(operator):
    if operator == "add":
        return vector_icon("add-peak.svg")
    glyphs = {
        "subtract": '<path d="M40 13h17"/>',
        "multiply": '<path d="m42 6 13 14m0-14L42 20"/>',
        "divide": '<path d="M40 13h17"/><circle cx="48.5" cy="5" r="1.8" fill="#FF7A00" stroke="none"/><circle cx="48.5" cy="21" r="1.8" fill="#FF7A00" stroke="none"/>',
        "convolve": '<path d="M48.5 3v20M40 8l17 10M40 18l17-10"/>',
    }
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<g fill="none" stroke="#172735" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 20v36h49"/><path d="M13 48c8 0 8-29 16-29s7 29 15 29h8" stroke="#0877F9"/>'
        '<g stroke="#FF7A00">' + glyphs[operator] + '</g></g></svg>'
    )
    return QIcon(PaletteIconEngine(source))


def set_operator(window, operator):
    if operator not in {item[0] for item in OPERATORS}:
        raise ValueError("Unknown function composition: " + str(operator))
    window.settings.setValue(_SETTING, operator)
    if getattr(window.plot_workspace, "_quick_add_placement", False) and window._pending_component is not None:
        window._pending_component.operator = operator
    sync_composition(window)


def sync_composition(window):
    operator = selected_operator(window)
    _, symbol, label = next(item for item in OPERATORS if item[0] == operator)
    action = window.quick_peak_action
    action.setIcon(composition_icon(operator))
    action.setText(window.tr("Add function") if operator == "add" else window.tr("Insert function") + " (" + symbol + " " + window.tr(label) + ")")
    action.setToolTip(action.text() + " — " + symbol + " " + window.tr(label) + "\n"
        + window.tr("Set the selected function's role in the whole model. Use the arrow to change it and Calculation order to choose precedence.\n")
        + window.tr("With Initialize with points checked, place peaks by click and drag; otherwise each click inserts one initial estimate. Right-click or press Enter, Esc, or Finish to stop placement."))
    for identifier, item in getattr(window, "function_composition_actions", {}).items():
        with QSignalBlocker(item):
            item.setChecked(identifier == operator)
        item.setEnabled(operator_available(window, identifier))
    dialog = getattr(window, "_function_info_dialog", None)
    if dialog is not None:
        dialog.sync_composition()
    checkbox = getattr(window, "quick_add_background", None)
    selector = getattr(window, "quick_function_selector", None)
    if checkbox is not None and selector is not None:
        allowed = bool(selector.currentData()) and operator in {"add", "subtract"}
        checkbox.setEnabled(allowed)
        with QSignalBlocker(checkbox):
            checkbox.setChecked(allowed and window.settings.value(
                f"quick_add_controls/{selector.currentData()}/background", False, type=bool
            ))
        checkbox.setToolTip(window.tr("Mark the added function as background. Background components support Add or Subtract only."))
        if getattr(window.plot_workspace, "_quick_add_placement", False) and window._pending_component is not None:
            window._pending_component.is_background = checkbox.isChecked()


def install_composition_menu(window, button):
    menu = QMenu(button)
    menu.addSection(window.tr("Combine with the existing model"))
    group = QActionGroup(menu)
    window.function_composition_actions = {}
    for identifier, symbol, label in OPERATORS:
        action = menu.addAction(symbol + " " + window.tr(label))
        action.setCheckable(True)
        action.setData(identifier)
        action.setToolTip(window.tr("Set this function's role in the model. Use Calculation order in Model and parameters to choose precedence."))
        group.addAction(action)
        action.triggered.connect(lambda checked=False, op=identifier: set_operator(window, op))
        window.function_composition_actions[identifier] = action
    menu.setToolTipsVisible(True)
    menu.aboutToShow.connect(lambda: sync_composition(window))
    window.function_composition_menu = menu
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    sync_composition(window)


def insertion_signal(window, curve, operator):
    """Signal that the inserted factor/term should approximate before fitting."""
    model = window.project.model_for(curve.id)
    if model.composition_mode == "global" and not any(c.enabled for c in model.components):
        if operator == "multiply":
            return curve.y.copy()
        if operator == "divide":
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(curve.y != 0, 1 / curve.y, np.nan)
    existing = np.asarray(model.evaluate(curve.x, curve_id=curve.id,
        values=window.project.resolved_parameter_values(), registry=window.registry), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        if operator == "subtract":
            return existing - curve.y
        if operator == "multiply":
            return np.where(existing != 0, curve.y / existing, np.nan)
        if operator == "divide":
            return np.where(curve.y != 0, existing / curve.y, np.nan)
    return curve.y - existing if operator == "add" else curve.y.copy()


def normalize_kernel(component):
    """Area-normalized built-ins start convolution with unit kernel area."""
    if component.operator == "convolve" and component.function_id in {"gaussian", "lorentzian", "voigt", "pseudo_voigt"}:
        component.parameters["area"].value = 1.0
