"""Persistent user functions and function-aware Quick Add/peak search.

This module intentionally follows CurveMole's established GUI compatibility-patch
pattern.  It keeps the existing public action/method names for backwards
compatibility while presenting the feature as Quick Add Function in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QToolBar,
)

from curvemole.core.functions import formula_definition
from curvemole.core.initialization import find_peak_suggestions, initialise_peak_component
from curvemole.core.models import Component, Model
from curvemole.core.plugins import export_custom_function, import_custom_function
from curvemole.gui.main_window import MainWindow
from curvemole.gui.panels import FunctionBuilderPanel

_LIBRARY_FOLDER_NAME = "my_curvemole_functions"
_LIBRARY_SETTING = "custom_function_directory"
_FUNCTION_SUFFIX = ".curvemole-function.json"


def _library_directory(window: MainWindow) -> Path | None:
    value = str(window.settings.value(_LIBRARY_SETTING, "") or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


def _choose_library_directory(window: MainWindow) -> Path | None:
    """Ask once where the persistent user-function library should live."""
    existing = _library_directory(window)
    if existing is not None:
        return existing

    box = QMessageBox(window)
    box.setWindowTitle(window.tr("CurveMole function library"))
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(
        window.tr(
            "Reusable functions are stored in a dedicated my_curvemole_functions folder. "
            "Create one where you want, or open an existing one."
        )
    )
    create_button = box.addButton(
        window.tr("Create my_curvemole_functions…"), QMessageBox.ButtonRole.ActionRole
    )
    open_button = box.addButton(
        window.tr("Open existing my_curvemole_functions…"), QMessageBox.ButtonRole.ActionRole
    )
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()

    clicked = box.clickedButton()
    directory: Path | None = None
    if clicked is create_button:
        parent = QFileDialog.getExistingDirectory(
            window,
            window.tr("Choose where to create my_curvemole_functions"),
        )
        if not parent:
            return None
        selected = Path(parent).expanduser()
        directory = (
            selected
            if selected.name.casefold() == _LIBRARY_FOLDER_NAME.casefold()
            else selected / _LIBRARY_FOLDER_NAME
        )
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(window, window.tr("Function library"), str(exc))
            return None
    elif clicked is open_button:
        selected_value = QFileDialog.getExistingDirectory(
            window,
            window.tr("Open my_curvemole_functions"),
        )
        if not selected_value:
            return None
        selected = Path(selected_value).expanduser()
        if selected.name.casefold() == _LIBRARY_FOLDER_NAME.casefold():
            directory = selected
        elif (selected / _LIBRARY_FOLDER_NAME).is_dir():
            directory = selected / _LIBRARY_FOLDER_NAME
        else:
            QMessageBox.warning(
                window,
                window.tr("Function library"),
                window.tr("Select the existing my_curvemole_functions folder."),
            )
            return None
    else:
        return None

    if directory is None or not directory.is_dir():
        return None
    window.settings.setValue(_LIBRARY_SETTING, str(directory.resolve()))
    return directory


def _refresh_quick_function_selector(
    window: MainWindow,
    *,
    preferred: str | None = None,
) -> None:
    selector = getattr(window, "quick_function_selector", None)
    if not isinstance(selector, QComboBox):
        return

    current = str(selector.currentData() or "")
    remembered = str(
        window.settings.value(
            "last_quick_function",
            window.settings.value("last_peak_function", "gaussian"),
        )
        or ""
    )
    wanted = preferred or current or remembered

    selector.blockSignals(True)
    try:
        selector.clear()
        for definition in window.registry.values():
            selector.addItem(definition.display_name, definition.identifier)
        index = selector.findData(wanted)
        if index < 0 and selector.count():
            index = 0
        selector.setCurrentIndex(index)
    finally:
        selector.blockSignals(False)


def _remember_quick_function(window: MainWindow, function_id: str) -> None:
    definition = window.registry.get(function_id)
    window.last_quick_function_id = definition.identifier
    window.settings.setValue("last_quick_function", definition.identifier)
    if definition.kind == "peak":
        # Keep the historical setting in sync for projects/tests that still use it.
        window.last_peak_function_id = definition.identifier
        window.settings.setValue("last_peak_function", definition.identifier)
    selector = getattr(window, "quick_function_selector", None)
    if isinstance(selector, QComboBox):
        index = selector.findData(definition.identifier)
        if index >= 0 and selector.currentIndex() != index:
            selector.blockSignals(True)
            selector.setCurrentIndex(index)
            selector.blockSignals(False)


def _selected_quick_function(window: MainWindow) -> str:
    selector = getattr(window, "quick_function_selector", None)
    if isinstance(selector, QComboBox) and selector.currentData():
        identifier = str(selector.currentData())
        window.registry.get(identifier)
        return identifier

    remembered = str(
        window.settings.value(
            "last_quick_function",
            window.settings.value("last_peak_function", "gaussian"),
        )
        or ""
    )
    if remembered:
        try:
            window.registry.get(remembered)
            return remembered
        except Exception:
            pass
    definitions = window.registry.values()
    if definitions:
        return definitions[0].identifier
    raise ValueError(window.tr("No function is available in the current registry."))


def _selector_changed(window: MainWindow, *_: Any) -> None:
    selector = getattr(window, "quick_function_selector", None)
    if isinstance(selector, QComboBox) and selector.currentData():
        _remember_quick_function(window, str(selector.currentData()))


def _load_user_function_library(window: MainWindow) -> None:
    directory = _library_directory(window)
    if directory is None:
        return
    for source in sorted(directory.glob(f"*{_FUNCTION_SUFFIX}")):
        try:
            definition = import_custom_function(source)
            window.registry.register(definition, replace=True)
        except Exception as exc:
            window._log(f"User function skipped ({source.name}): {exc}")
    _refresh_quick_function_selector(window)


def _quick_add_function(window: MainWindow) -> None:
    if not window._ensure_editable():
        return
    if not window.active_curve_id:
        window._notify(window.tr("Activate a curve first."), warning=True)
        return
    window.plot_workspace.cancel_placement()
    try:
        function_id = _selected_quick_function(window)
        definition = window.registry.get(function_id)
        _remember_quick_function(window, function_id)

        if definition.kind == "peak":
            component = Component.create(function_id, registry=window.registry)
            window._pending_component = component
            window._pending_component_curve_id = window.active_curve_id
            window.plot_workspace.begin_peak_placement(definition.display_name)
            window._notify(
                window.tr("Quick Add Function: click the peak centre and drag horizontally to set its initial FWHM.")
            )
            return

        if function_id == "cubic_spline":
            # Cubic-spline parameters depend on user-selected x nodes, so create the
            # shell first and let the existing graphical placement initialise it.
            component = Component(
                function_id=function_id,
                name=definition.display_name,
                parameters={},
            )
            window._pending_component = component
            window._pending_component_curve_id = window.active_curve_id
            window.plot_workspace.begin_spline_placement(definition.display_name)
            window._notify(
                window.tr(
                    "Quick Add Function: click spline points on the graph and finish after at least two points."
                )
            )
            return

        component = Component.create(function_id, registry=window.registry)
        window._commit_component(component, window.active_curve_id)
        window._notify(
            window.tr("Quick Add Function: added ") + definition.display_name + "."
        )
    except Exception as exc:
        window._show_error(window.tr("Quick Add Function"), exc)


def _find_peaks(window: MainWindow) -> None:
    if not window._ensure_editable():
        return
    if not window.active_curve_id:
        return
    curve = window.project.dataset.curve(window.active_curve_id)

    labels = [window.tr("Positive (default)"), window.tr("Negative"), window.tr("Both signs")]
    selected_sign, accepted = QInputDialog.getItem(
        window,
        window.tr("Find Peaks — Advanced"),
        window.tr("Peak sign:"),
        labels,
        0,
        False,
    )
    if not accepted:
        return
    sign = {
        labels[0]: "positive",
        labels[1]: "negative",
        labels[2]: "both",
    }[selected_sign]

    peak_definitions = [definition for definition in window.registry.values() if definition.kind == "peak"]
    if not peak_definitions:
        window._notify(window.tr("No peak function is available in the current registry."), warning=True)
        return
    current_id = _selected_quick_function(window)
    default_index = next(
        (index for index, definition in enumerate(peak_definitions) if definition.identifier == current_id),
        0,
    )
    function_names = [definition.display_name for definition in peak_definitions]
    selected_name, accepted = QInputDialog.getItem(
        window,
        window.tr("Find Peaks — Function"),
        window.tr("Function to use for detected peaks:"),
        function_names,
        default_index,
        False,
    )
    if not accepted:
        return
    selected_index = function_names.index(selected_name)
    function_id = peak_definitions[selected_index].identifier
    _remember_quick_function(window, function_id)

    suggestions = find_peak_suggestions(curve, sign=sign)
    if not suggestions:
        window._notify(window.tr("No peak suggestion met the automatic threshold."), warning=True)
        return
    count, ok = QInputDialog.getInt(
        window,
        window.tr("Find Peaks"),
        window.tr("Suggested peaks found: ")
        + f"{len(suggestions)}\n"
        + window.tr("How many should be added?"),
        min(1, len(suggestions)),
        1,
        len(suggestions),
    )
    if not ok:
        return

    model = window.project.model_for(window.active_curve_id)
    before = model.to_dict()
    try:
        for suggestion in suggestions[:count]:
            component = Component.create(function_id, registry=window.registry)
            initialise_peak_component(component, suggestion, registry=window.registry)
            window._assign_component_name(component, model)
            model.add(component)
        after = model.to_dict()
    except Exception as exc:
        window.project.models[window.active_curve_id] = Model.from_dict(before)
        window._show_error(window.tr("Find Peaks"), exc)
        return

    window.project.models[window.active_curve_id] = Model.from_dict(before)
    window._push_model_state(
        window.active_curve_id,
        before,
        after,
        window.tr("Add suggested peaks"),
    )


def _builder_add(panel: FunctionBuilderPanel) -> None:
    if not panel._validate():
        return
    identifier = re.sub(r"[^a-z0-9_]+", "_", panel.identifier.text().strip().lower()).strip("_")
    if not identifier:
        QMessageBox.warning(panel, panel.tr("Function Builder"), panel.tr("Enter an identifier."))
        return

    derived: dict[str, str] = {}
    if panel.derived_area.text().strip():
        derived["area"] = panel.derived_area.text().strip()
    if panel.derived_fwhm.text().strip():
        derived["FWHM"] = panel.derived_fwhm.text().strip()

    try:
        definition = formula_definition(
            identifier,
            panel.display_name.text().strip() or identifier,
            panel.formula.toPlainText(),
            kind=str(panel.kind.currentData()),
            derived_formulas=derived,
        )
    except Exception as exc:
        QMessageBox.warning(panel, panel.tr("Function Builder"), str(exc))
        return

    host = panel.window()
    if not isinstance(host, MainWindow):
        # The normal desktop path always has a MainWindow. Preserve the historical
        # behaviour for isolated/embed use where no persistent settings host exists.
        _ORIGINAL_BUILDER_ADD(panel)
        return

    directory = _choose_library_directory(host)
    if directory is None:
        return
    destination = directory / f"{identifier}{_FUNCTION_SUFFIX}"
    try:
        # Save first: a function must never appear to have been added successfully
        # if its reusable on-disk representation could not be written.
        export_custom_function(definition, destination)
        panel.registry.register(definition, replace=True)
        if panel.project is not None:
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
        panel.functionAdded.emit(identifier)
        _refresh_quick_function_selector(host)
        QMessageBox.information(
            panel,
            panel.tr("Function Builder"),
            panel.tr("Function added and saved in the reusable library:")
            + f"\n{destination}",
        )
    except Exception as exc:
        QMessageBox.warning(panel, panel.tr("Function Builder"), str(exc))


def _install() -> None:
    if getattr(MainWindow, "_curvemole_quick_function_library", False):
        return

    original_build_actions = MainWindow._build_actions
    original_build_toolbar = MainWindow._build_toolbar
    original_connect_signals = MainWindow._connect_signals
    original_load_custom_functions = MainWindow._load_custom_functions
    original_add_component = MainWindow.add_component
    original_show_plugin_manager = MainWindow.show_plugin_manager

    def build_actions(window: MainWindow) -> None:
        original_build_actions(window)
        window.quick_peak_action.setText(window.tr("Quick Add Function"))
        window.quick_peak_action.setToolTip(
            window.tr(
                "Quick Add Function\nAdd the function selected in the adjacent list without reopening the component dialog."
            )
        )
        window.quick_add_function_action = window.quick_peak_action

    def build_toolbar(window: MainWindow) -> None:
        original_build_toolbar(window)
        toolbar = window.findChild(QToolBar, "Main_toolbar")
        if toolbar is None:
            return
        selector = QComboBox(toolbar)
        selector.setObjectName("quick_function_selector")
        selector.setMinimumWidth(150)
        selector.setMaximumWidth(240)
        selector.setToolTip(window.tr("Function used by Quick Add Function"))
        window.quick_function_selector = selector
        _refresh_quick_function_selector(window)
        selector.currentIndexChanged.connect(lambda *_: _selector_changed(window))
        toolbar.insertWidget(window.fit_action, selector)

    def connect_signals(window: MainWindow) -> None:
        original_connect_signals(window)
        window.function_builder.functionAdded.connect(
            lambda *_: _refresh_quick_function_selector(window)
        )

    def load_custom_functions(window: MainWindow) -> None:
        original_load_custom_functions(window)
        _load_user_function_library(window)
        _refresh_quick_function_selector(window)

    def add_component(window: MainWindow) -> None:
        previous_pending = window._pending_component
        previous_selected = window.selected_component_id
        original_add_component(window)
        function_id: str | None = None
        pending = window._pending_component
        if pending is not None and pending is not previous_pending:
            function_id = pending.function_id
        elif (
            window.active_curve_id
            and window.selected_component_id
            and window.selected_component_id != previous_selected
        ):
            try:
                function_id = window.project.model_for(window.active_curve_id).component(
                    window.selected_component_id
                ).function_id
            except KeyError:
                function_id = None
        if function_id:
            _remember_quick_function(window, function_id)

    def show_plugin_manager(window: MainWindow) -> None:
        original_show_plugin_manager(window)
        _refresh_quick_function_selector(window)

    MainWindow._build_actions = build_actions
    MainWindow._build_toolbar = build_toolbar
    MainWindow._connect_signals = connect_signals
    MainWindow._load_custom_functions = load_custom_functions
    MainWindow.add_component = add_component
    MainWindow.quick_peak = _quick_add_function
    MainWindow._quick_peak_function_id = _selected_quick_function
    MainWindow.find_peaks = _find_peaks
    MainWindow.show_plugin_manager = show_plugin_manager
    MainWindow._refresh_quick_function_selector = _refresh_quick_function_selector
    MainWindow._remember_quick_function = _remember_quick_function
    MainWindow._load_user_function_library = _load_user_function_library
    MainWindow._curvemole_quick_function_library = True


_ORIGINAL_BUILDER_ADD = FunctionBuilderPanel._add
_install()
FunctionBuilderPanel._add = _builder_add
