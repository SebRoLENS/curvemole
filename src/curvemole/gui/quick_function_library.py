"""Persistent user functions and function-aware Quick Add/peak search.

This module intentionally follows CurveMole's established GUI compatibility-patch
pattern. It keeps the existing public action/method names for backwards
compatibility while presenting the feature as Quick Add Function in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.functions import formula_definition
from curvemole.core.initialization import find_peak_suggestions, initialise_peak_component
from curvemole.core.models import Component, Model
from curvemole.core.plugin_identity import function_tooltip
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
            selector.setItemData(selector.count() - 1, function_tooltip(definition), Qt.ItemDataRole.ToolTipRole)
        index = selector.findData(wanted)
        if index < 0 and selector.count():
            index = 0
        selector.setCurrentIndex(index)
        selector.setToolTip(selector.itemData(index, Qt.ItemDataRole.ToolTipRole) or "")
    finally:
        selector.blockSignals(False)
    _sync_quick_add_options(window)


def _remember_quick_function(window: MainWindow, function_id: str) -> None:
    definition = window.registry.get(function_id)
    if hasattr(window, "quick_function_selector"):
        window.quick_function_selector.setToolTip(function_tooltip(definition))
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
    _sync_quick_add_options(window, definition.identifier)


def _selected_quick_function(window: MainWindow) -> str:
    # Before the first use of the new selector, honour the historical peak setting.
    # This migrates existing installations cleanly and preserves callers that set
    # last_peak_function_id directly.
    if not window.settings.contains("last_quick_function"):
        legacy = str(getattr(window, "last_peak_function_id", "") or "")
        if legacy:
            try:
                window.registry.get(legacy)
                return legacy
            except Exception:
                pass

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
        identifier = str(selector.currentData())
        _remember_quick_function(window, identifier)
        if window.plot_workspace._placement_mode is not None:
            window.plot_workspace.cancel_placement()
            definition = window.registry.get(identifier)
            if definition.kind == "peak" or identifier == "cubic_spline":
                window.quick_peak()


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


def _quick_add_option(window: MainWindow, function_id: str, option: str) -> bool:
    """Recall only explicit choices from Quick Add; both options default off."""
    value = window.settings.value(f"quick_add_controls/{function_id}/{option}", False)
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return bool(value)


def _sync_quick_add_options(window: MainWindow, function_id: str | None = None) -> None:
    background = getattr(window, "quick_add_background", None)
    points = getattr(window, "quick_add_manual_points", None)
    if background is None or points is None:
        return
    identifier = function_id or window.quick_function_selector.currentData()
    background.setEnabled(bool(identifier))
    points.setEnabled(bool(identifier))
    if not identifier:
        return
    with QSignalBlocker(background), QSignalBlocker(points):
        background.setChecked(_quick_add_option(window, str(identifier), "background"))
        points.setChecked(_quick_add_option(window, str(identifier), "manual_points"))


def _quick_add_option_changed(window: MainWindow, option: str, checked: bool) -> None:
    identifier = window.quick_function_selector.currentData()
    if not identifier:
        return
    window.settings.setValue(f"quick_add_controls/{identifier}/{option}", checked)
    workspace = window.plot_workspace
    if not getattr(workspace, "_quick_add_placement", False):
        return
    if option == "background":
        if window._pending_component is not None:
            window._pending_component.is_background = checked
    else:
        # Placement modes have different point requirements. Restart the pending
        # insertion when that choice changes, retaining already completed peaks.
        window.quick_peak()


def _quick_add_function(window: MainWindow) -> None:
    if not window._ensure_editable():
        return
    if not window.active_curve_id:
        window._notify(window.tr("Activate a curve first."), warning=True)
        return
    window.plot_workspace.cancel_placement()
    window._pending_manual_points = False
    try:
        function_id = _selected_quick_function(window)
        definition = window.registry.get(function_id)
        _remember_quick_function(window, function_id)

        if definition.kind == "peak":
            component = Component.create(function_id, registry=window.registry)
            component.is_background = _quick_add_option(window, function_id, "background")
            window._pending_component = component
            window._pending_component_curve_id = window.active_curve_id
            from curvemole.gui.manual_points import minimum_manual_points

            if _quick_add_option(window, function_id, "manual_points"):
                window._pending_manual_points = True
                window.plot_workspace.begin_manual_point_placement(
                    definition.display_name, function_id, minimum_manual_points(component)
                )
                window.plot_workspace.mark_quick_add_placement()
                window._notify(window.tr("Quick Add Function: select points on the graph, then press Finish."))
                return
            window.plot_workspace.begin_peak_placement(definition.display_name)
            window.plot_workspace.mark_quick_add_placement()
            window._notify(
                window.tr(
                    "Quick Add Function: click the peak centre and drag horizontally to set its initial FWHM."
                )
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
            component.is_background = _quick_add_option(window, function_id, "background")

            if not _quick_add_option(window, function_id, "manual_points"):
                curve = window.project.dataset.curve(window.active_curve_id)
                finite = np.isfinite(curve.x) & np.isfinite(curve.y)
                if not np.any(finite):
                    raise ValueError(window.tr("The active curve has no usable points."))
                xs = curve.x[finite]
                ys = curve.y[finite]
                nodes = sorted({float(np.min(xs)), float(np.median(xs)), float(np.max(xs))})
                if len(nodes) < 2:
                    raise ValueError(window.tr("The spline needs at least two distinct x values."))
                order = np.argsort(xs)
                component = Component.create(
                    function_id, registry=window.registry, metadata={"x_nodes": nodes}
                )
                for index, node in enumerate(nodes):
                    component.parameters[f"y{index}"].value = float(np.interp(node, xs[order], ys[order]))
                component.is_background = _quick_add_option(window, function_id, "background")
                window._commit_component(component, window.active_curve_id)
                return
            window._pending_component = component
            window._pending_component_curve_id = window.active_curve_id
            window.plot_workspace.begin_spline_placement(definition.display_name)
            window.plot_workspace.mark_quick_add_placement()
            window._notify(
                window.tr(
                    "Quick Add Function: click spline points on the graph and finish after at least two points."
                )
            )
            return

        component = Component.create(function_id, registry=window.registry)
        component.is_background = _quick_add_option(window, function_id, "background")
        from curvemole.gui.manual_points import minimum_manual_points

        if _quick_add_option(window, function_id, "manual_points"):
            window._pending_component = component
            window._pending_component_curve_id = window.active_curve_id
            window._pending_manual_points = True
            window.plot_workspace.begin_manual_point_placement(
                definition.display_name, function_id, minimum_manual_points(component)
            )
            window.plot_workspace.mark_quick_add_placement()
            window._notify(
                window.tr("Quick Add Function: select points on the graph, then press Finish.")
            )
            return
        window._commit_component(component, window.active_curve_id)
        window._notify(window.tr("Quick Add Function: added ") + definition.display_name + ".")
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

    peak_definitions = [
        definition for definition in window.registry.values() if definition.kind == "peak"
    ]
    if not peak_definitions:
        window._notify(
            window.tr("No peak function is available in the current registry."), warning=True
        )
        return
    current_id = _selected_quick_function(window)
    default_index = next(
        (
            index
            for index, definition in enumerate(peak_definitions)
            if definition.identifier == current_id
        ),
        0,
    )
    function_names = [definition.display_name for definition in peak_definitions]
    chooser = QInputDialog(window)
    chooser.setWindowTitle(window.tr("Find Peaks — Function"))
    chooser.setLabelText(window.tr("Function to use for detected peaks:"))
    chooser.setComboBoxItems(function_names)
    chooser.setComboBoxEditable(False)
    chooser.setTextValue(function_names[default_index])
    combo = chooser.findChild(QComboBox)
    if combo is not None:
        for index, definition in enumerate(peak_definitions):
            combo.setItemData(index, function_tooltip(definition), Qt.ItemDataRole.ToolTipRole)
        combo.currentIndexChanged.connect(
            lambda index: combo.setToolTip(combo.itemData(index, Qt.ItemDataRole.ToolTipRole) or ""))
        combo.setToolTip(function_tooltip(peak_definitions[default_index]))
    accepted = chooser.exec()
    selected_name = chooser.textValue()
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
    identifier = re.sub(
        r"[^a-z0-9_]+", "_", panel.identifier.text().strip().lower()
    ).strip("_")
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
            panel.tr("Function added and saved in the reusable library:") + f"\n{destination}",
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
                "Quick Add Function\nReplaces Quick Peak and adds the function selected in the adjacent list."
            )
        )
        window.quick_add_function_action = window.quick_peak_action

    def build_toolbar(window: MainWindow) -> None:
        original_build_toolbar(window)
        toolbar = window.findChild(QToolBar, "Main_toolbar")
        if toolbar is None:
            return
        reference = toolbar.widgetForAction(window.add_component_action)
        toolbar.removeAction(window.quick_peak_action)
        group = QFrame(toolbar)
        group.setObjectName("quick_add_group")
        group.setFrameShape(QFrame.Shape.StyledPanel)
        group.setStyleSheet(
            "QFrame#quick_add_group { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        if reference is not None:
            group.setMaximumHeight(reference.sizeHint().height())
        group_layout = QHBoxLayout(group)
        group_layout.setContentsMargins(2, 0, 2, 0)
        group_layout.setSpacing(2)
        launch = QWidget(group)
        launch_layout = QVBoxLayout(launch)
        launch_layout.setContentsMargins(0, 0, 0, 0)
        launch_layout.setSpacing(0)
        title = QLabel(window.tr("Quick Add"), launch)
        title_font = title.font()
        title_font.setBold(True)
        if title_font.pointSizeF() > 0:
            title_font.setPointSizeF(max(8.0, title_font.pointSizeF() - 1.0))
        title.setFont(title_font)
        launch_layout.addWidget(title)
        button = QToolButton(launch)
        button.setObjectName("quick_add_button")
        button.setDefaultAction(window.quick_peak_action)
        button.setText(window.tr("Add"))
        # Icon/theme updates propagate QAction's longer menu title to its
        # buttons. Keep the compact label while sharing the canonical action.
        window.quick_peak_action.changed.connect(lambda: button.setText(window.tr("Add")))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(16, 16))
        launch_layout.addWidget(button)
        group_layout.addWidget(launch)
        choices = QWidget(group)
        layout = QVBoxLayout(choices)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        selector = QComboBox(choices)
        selector.setObjectName("quick_function_selector")
        selector.setMinimumWidth(150)
        selector.setMaximumWidth(240)
        selector.setToolTip(window.tr("Function used by Quick Add Function"))
        window.quick_function_selector = selector
        layout.addWidget(selector)
        window.quick_add_background = QCheckBox(window.tr("Background"), choices)
        window.quick_add_background.setObjectName("quick_add_background")
        window.quick_add_background.setToolTip(window.tr("Mark the function added by Quick Add as background."))
        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(2)
        option_row.addWidget(window.quick_add_background)
        window.quick_add_manual_points = QCheckBox(window.tr("Initialize with points"), choices)
        window.quick_add_manual_points.setObjectName("quick_add_manual_points")
        window.quick_add_manual_points.setToolTip(window.tr("Initialize Quick Add functions from selected graph points."))
        option_row.addWidget(window.quick_add_manual_points)
        layout.addLayout(option_row)
        group_layout.addWidget(choices)
        window.quick_add_group = group
        window.quick_add_button = button
        window.quick_add_title = title
        window.quick_add_options = choices
        _refresh_quick_function_selector(window)
        selector.currentIndexChanged.connect(lambda *_: _selector_changed(window))
        window.quick_add_background.toggled.connect(
            lambda checked: _quick_add_option_changed(window, "background", checked))
        window.quick_add_manual_points.toggled.connect(
            lambda checked: _quick_add_option_changed(window, "manual_points", checked))
        toolbar.insertWidget(window._fit_toolbar_separator, group)

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
