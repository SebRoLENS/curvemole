"""Correct background subtraction controls while preserving the 0.12 display behaviour."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.calculator import apply_background_subtraction
from curvemole.core.data import Curve, CurveState, Transformation
from curvemole.gui import background_navigation as _background_navigation  # noqa: F401
from curvemole.gui.dialogs import BackgroundComponentsDialog
from curvemole.gui.main_window import CallbackCommand, MainWindow

_BACKGROUND_METHODS = {"model_components", "model_components_global"}


def _is_background_button_transformation(transformation: Transformation) -> bool:
    return (
        transformation.operation == "background_subtract"
        and str(transformation.parameters.get("method", "")) in _BACKGROUND_METHODS
    )


def _states_payload(states: dict[str, tuple[bool, bool]]) -> dict[str, dict[str, bool]]:
    return {
        component_id: {"is_background": marked, "enabled": enabled}
        for component_id, (marked, enabled) in states.items()
    }


def _restore_component_states(model: Any, states: dict[str, tuple[bool, bool]]) -> None:
    for component_id, (marked, enabled) in states.items():
        with suppress(KeyError):
            component = model.component(component_id)
            component.is_background = marked
            component.enabled = enabled


def _touch_and_refresh(window: MainWindow, operation: Any) -> None:
    operation()
    try:
        window.project.touch()
    except PermissionError as exc:
        window._show_error(window.tr("Read-only project"), exc)
    window.refresh_all()


def _install_apply_all_checkbox() -> None:
    if getattr(BackgroundComponentsDialog, "_curvemole_apply_all_checkbox", False):
        return

    original_init = BackgroundComponentsDialog.__init__

    def init(
        dialog: BackgroundComponentsDialog,
        project: Any,
        curve_id: str,
        registry: Any,
        parent: QWidget | None = None,
    ) -> None:
        original_init(dialog, project, curve_id, registry, parent)
        checkbox = QCheckBox(dialog.tr("Apply to all spectra"), dialog)
        checkbox.setChecked(False)
        checkbox.setToolTip(
            dialog.tr(
                "Off: subtract the selected background functions only from the current spectrum. "
                "On: apply subtraction to every spectrum using every enabled function already marked "
                "as background on that spectrum."
            )
        )
        dialog.apply_to_all_spectra = checkbox
        layout = dialog.layout()
        if isinstance(layout, QVBoxLayout):
            layout.insertWidget(max(0, layout.count() - 1), checkbox)

        def update_mode(enabled: bool) -> None:
            # When backgrounds are already marked, global mode intentionally uses all of them,
            # so the per-component checklist is not meaningful. In first-use marking mode the
            # checklist stays enabled so the current spectrum can designate its backgrounds.
            if not dialog.marking_mode:
                dialog.components.setEnabled(not enabled)

        checkbox.toggled.connect(update_mode)

    BackgroundComponentsDialog.__init__ = init
    BackgroundComponentsDialog._curvemole_apply_all_checkbox = True


def _subtract_current_background(window: MainWindow) -> None:
    if not window._ensure_editable():
        return
    if not window.active_curve_id:
        window._notify(window.tr("Activate a curve first."), warning=True)
        return

    curve_id = window.active_curve_id
    curve = window.project.dataset.curve(curve_id)
    model = window.project.model_for(curve_id)
    if not model.components:
        window._notify(
            window.tr("Add at least one model function before subtracting a background."),
            warning=True,
        )
        return

    dialog = BackgroundComponentsDialog(window.project, curve_id, window.registry, window)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return

    component_ids = dialog.selected_component_ids()
    apply_all = bool(dialog.apply_to_all_spectra.isChecked())
    if apply_all:
        # If this is the first background subtraction on the current spectrum, its checked
        # functions become background-designated as part of the same global undoable action.
        mark_current = component_ids if dialog.marking_mode else None
        window.subtract_all_backgrounds(mark_current)
        return

    if not component_ids:
        window._notify(window.tr("Select at least one background function."), warning=True)
        return

    selected = [model.component(component_id) for component_id in component_ids]
    try:
        background = model.background(
            curve.x,
            curve_id=curve_id,
            values=window.project.resolved_parameter_values(),
            registry=window.registry,
            component_ids=set(component_ids),
        )
    except Exception as exc:
        window._show_error(window.tr("Subtract background"), exc)
        return
    if not np.all(np.isfinite(background)):
        window._notify(
            window.tr("The selected background functions produce non-finite values."),
            warning=True,
        )
        return

    states_before = {
        component.id: (component.is_background, component.enabled) for component in selected
    }
    states_after = {component.id: (True, False) for component in selected}
    state_before = curve.state
    transformation = apply_background_subtraction(
        curve,
        background,
        method="model_components",
        description=window.tr("Subtract marked model background"),
        parameters={
            "component_ids": list(component_ids),
            "component_names": [component.name for component in selected],
            "source": "background_button",
            "component_states_before": _states_payload(states_before),
            "curve_state_before": state_before.value,
        },
    )
    curve.undo_transformation()

    def redo() -> None:
        if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
            curve.redo_transformation()
        elif transformation not in curve.transformations:
            curve.apply_transformation(transformation)
        _restore_component_states(model, states_after)

    def undo() -> None:
        if curve.transformations and curve.transformations[-1] is transformation:
            curve.undo_transformation()
        _restore_component_states(model, states_before)
        curve.state = state_before

    window._push_change(window.tr("Subtract background"), redo, undo)
    window._notify(
        window.tr(
            "Background subtracted. Selected background functions were disabled to avoid double-counting."
        )
    )


def _subtract_all_backgrounds(
    window: MainWindow,
    mark_current_component_ids: list[str] | None = None,
) -> None:
    if not window._ensure_editable():
        return

    try:
        global_values = window.project.resolved_parameter_values()
    except Exception as exc:
        window._show_error(window.tr("Subtract backgrounds"), exc)
        return

    active_id = window.active_curve_id
    mark_current_ids = set(mark_current_component_ids or ())
    prepared: list[
        tuple[Curve, Any, list[Any], np.ndarray, dict[str, tuple[bool, bool]], CurveState]
    ] = []

    for curve in window.project.curves:
        model = window.project.models.get(curve.id)
        if model is None:
            continue
        marked = [
            component
            for component in model.components
            if component.enabled
            and (
                component.is_background
                or (curve.id == active_id and component.id in mark_current_ids)
            )
        ]
        if not marked:
            continue
        component_ids = {component.id for component in marked}
        try:
            background = np.asarray(
                model.background(
                    curve.x,
                    curve_id=curve.id,
                    values=global_values,
                    registry=window.registry,
                    component_ids=component_ids,
                ),
                dtype=float,
            )
        except Exception as exc:
            window._show_error(window.tr("Subtract backgrounds"), exc)
            return
        usable = np.isfinite(curve.x) & np.isfinite(curve.y)
        if background.shape != curve.y.shape or np.any(usable & ~np.isfinite(background)):
            window._notify(
                window.tr("A marked background contains invalid values; no spectrum was changed."),
                warning=True,
            )
            return
        states_before = {
            component.id: (component.is_background, component.enabled) for component in marked
        }
        prepared.append((curve, model, marked, background, states_before, curve.state))

    if not prepared:
        window._notify(
            window.tr("No enabled function marked as background was found."),
            warning=True,
        )
        return

    records: list[
        tuple[
            Curve,
            Any,
            Transformation,
            dict[str, tuple[bool, bool]],
            dict[str, tuple[bool, bool]],
            CurveState,
        ]
    ] = []
    try:
        for curve, model, marked, background, states_before, state_before in prepared:
            component_ids = [component.id for component in marked]
            transformation = apply_background_subtraction(
                curve,
                background,
                method="model_components_global",
                description=window.tr("Subtract marked model background (all spectra)"),
                parameters={
                    "component_ids": component_ids,
                    "component_names": [component.name for component in marked],
                    "source": "background_button",
                    "component_states_before": _states_payload(states_before),
                    "curve_state_before": state_before.value,
                },
            )
            curve.undo_transformation()
            states_after = {component.id: (True, False) for component in marked}
            records.append(
                (curve, model, transformation, states_before, states_after, state_before)
            )
    except Exception as exc:
        window._show_error(window.tr("Subtract backgrounds"), exc)
        return

    def redo() -> None:
        for curve, model, transformation, _before, after, _state_before in records:
            if curve.redo_transformations and curve.redo_transformations[-1] is transformation:
                curve.redo_transformation()
            elif transformation not in curve.transformations:
                curve.apply_transformation(transformation)
            _restore_component_states(model, after)

    def undo() -> None:
        for curve, model, transformation, before, _after, state_before in reversed(records):
            if curve.transformations and curve.transformations[-1] is transformation:
                curve.undo_transformation()
            _restore_component_states(model, before)
            curve.state = state_before

    window.undo_stack.push(
        CallbackCommand(
            window.tr("Subtract backgrounds from all spectra"),
            lambda: _touch_and_refresh(window, redo),
            lambda: _touch_and_refresh(window, undo),
        )
    )
    window._notify(
        window.tr("Background subtracted from ")
        + str(len(records))
        + window.tr(" spectrum/spectra. Marked background functions were disabled.")
    )


def _eligible_revert_curves(window: MainWindow) -> list[Curve]:
    return [
        curve
        for curve in window.project.curves
        if any(_is_background_button_transformation(item) for item in curve.transformations)
    ]


class RevertBackgroundDialog(QDialog):
    def __init__(
        self,
        curves: list[Curve],
        active_curve_id: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Revert background"))
        self.resize(520, 430)
        layout = QVBoxLayout(self)
        message = QLabel(
            self.tr(
                "Select the spectra whose background subtraction should be reverted. "
                "Only spectra previously changed by Subtract background are shown."
            )
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        self.spectra = QListWidget()
        for curve in curves:
            item = QListWidgetItem(curve.name)
            item.setData(Qt.ItemDataRole.UserRole, curve.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if curve.id == active_curve_id
                else Qt.CheckState.Unchecked
            )
            self.spectra.addItem(item)
        layout.addWidget(self.spectra, 1)

        row = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"))
        deselect_all = QPushButton(self.tr("Deselect all"))
        select_all.clicked.connect(lambda: self._set_all(True))
        deselect_all.clicked.connect(lambda: self._set_all(False))
        row.addWidget(select_all)
        row.addWidget(deselect_all)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.spectra.itemChanged.connect(lambda _item: self._update_ok())
        self._update_ok()

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.spectra.count()):
            self.spectra.item(index).setCheckState(state)

    def _update_ok(self) -> None:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        button.setEnabled(bool(self.selected_curve_ids()))

    def selected_curve_ids(self) -> list[str]:
        return [
            str(self.spectra.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.spectra.count())
            if self.spectra.item(index).checkState() == Qt.CheckState.Checked
        ]


def _states_before_backgrounds(
    transformations: list[Transformation],
) -> dict[str, tuple[bool, bool]]:
    restored: dict[str, tuple[bool, bool]] = {}
    for transformation in transformations:
        payload = transformation.parameters.get("component_states_before")
        if isinstance(payload, dict):
            for component_id, state in payload.items():
                if component_id in restored or not isinstance(state, dict):
                    continue
                restored[str(component_id)] = (
                    bool(state.get("is_background", True)),
                    bool(state.get("enabled", True)),
                )
            continue
        # Compatibility with 0.12.0 transformations, which did not yet persist
        # the exact pre-subtraction component state.
        for component_id in transformation.parameters.get("component_ids", []):
            restored.setdefault(str(component_id), (True, True))
    return restored


def _state_before_backgrounds(
    current: CurveState,
    removed: list[Transformation],
    remaining: list[Transformation],
) -> CurveState:
    if remaining:
        return current
    for transformation in removed:
        value = transformation.parameters.get("curve_state_before")
        if value is None:
            continue
        with suppress(ValueError):
            return CurveState(str(value))
    return current


def _apply_curve_snapshot(
    curve: Curve,
    transformations: list[Transformation],
    redo_transformations: list[Transformation],
    state: CurveState,
) -> None:
    curve.transformations = list(transformations)
    curve.redo_transformations = list(redo_transformations)
    curve._recompute()
    curve.state = state


def _revert_backgrounds(
    window: MainWindow,
    curve_ids: list[str] | None = None,
) -> None:
    if not window._ensure_editable():
        return

    eligible = _eligible_revert_curves(window)
    if not eligible:
        window._notify(
            window.tr("No spectrum has a background subtraction to revert."),
            warning=True,
        )
        return

    if curve_ids is None:
        dialog = RevertBackgroundDialog(eligible, window.active_curve_id, window)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        curve_ids = dialog.selected_curve_ids()
    selected_ids = set(curve_ids or ())
    selected = [curve for curve in eligible if curve.id in selected_ids]
    if not selected:
        return

    records: list[dict[str, Any]] = []
    for curve in selected:
        model = window.project.models.get(curve.id)
        if model is None:
            continue
        removed = [
            item for item in curve.transformations if _is_background_button_transformation(item)
        ]
        if not removed:
            continue
        remaining = [
            item for item in curve.transformations if not _is_background_button_transformation(item)
        ]
        component_after = _states_before_backgrounds(removed)
        component_before: dict[str, tuple[bool, bool]] = {}
        for component_id in component_after:
            with suppress(KeyError):
                component = model.component(component_id)
                component_before[component_id] = (
                    component.is_background,
                    component.enabled,
                )
        records.append(
            {
                "curve": curve,
                "model": model,
                "before_transformations": list(curve.transformations),
                "before_redo": list(curve.redo_transformations),
                "before_state": curve.state,
                "before_components": component_before,
                "after_transformations": remaining,
                "after_redo": [],
                "after_state": _state_before_backgrounds(curve.state, removed, remaining),
                "after_components": component_after,
            }
        )

    if not records:
        return

    def redo() -> None:
        for record in records:
            _apply_curve_snapshot(
                record["curve"],
                record["after_transformations"],
                record["after_redo"],
                record["after_state"],
            )
            _restore_component_states(record["model"], record["after_components"])

    def undo() -> None:
        for record in records:
            _apply_curve_snapshot(
                record["curve"],
                record["before_transformations"],
                record["before_redo"],
                record["before_state"],
            )
            _restore_component_states(record["model"], record["before_components"])

    window.undo_stack.push(
        CallbackCommand(
            window.tr("Revert background subtraction"),
            lambda: _touch_and_refresh(window, redo),
            lambda: _touch_and_refresh(window, undo),
        )
    )
    window._notify(
        window.tr("Background subtraction reverted for ")
        + str(len(records))
        + window.tr(" spectrum/spectra.")
    )


def _find_menu(window: MainWindow, title: str) -> QMenu | None:
    wanted = window.tr(title)
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and menu.title().replace("&", "") == wanted:
            return menu
    return None


def _remove_action_everywhere(window: MainWindow, action: QAction) -> None:
    for menu in window.menuBar().findChildren(QMenu):
        menu.removeAction(action)
    for toolbar in window.findChildren(QToolBar):
        toolbar.removeAction(action)
    action.setVisible(False)


def _install_corrected_window_controls(window: MainWindow) -> None:
    old_global = getattr(window, "subtract_all_backgrounds_action", None)
    if isinstance(old_global, QAction):
        _remove_action_everywhere(window, old_global)

    window.subtract_background_action.setToolTip(
        window.tr(
            "Subtract background…\nCurrent spectrum by default. Tick ‘Apply to all spectra’ "
            "inside the dialog to use all marked background functions globally."
        )
    )

    visual = getattr(window, "background_subtracted_view_action", None)
    if isinstance(visual, QAction):
        visual.setText(window.tr("Visual only — background-subtracted"))
        visual.setToolTip(
            window.tr(
                "Visual only: show every spectrum with its enabled marked background removed. "
                "No data are modified; turn this off to restore the normal display."
            )
        )

    window.revert_background_action = QAction(
        window.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack),
        window.tr("Revert background…"),
        window,
    )
    window.revert_background_action.setToolTip(
        window.tr(
            "Choose one or more spectra previously changed by Subtract background and restore "
            "their data before that subtraction. Other transformations are preserved."
        )
    )
    window.revert_background_action.triggered.connect(window.revert_backgrounds)

    data_menu = _find_menu(window, "Data")
    if data_menu is not None:
        data_menu.insertAction(window.calculator_action, window.revert_background_action)

    toolbar = window.findChild(QToolBar, "Main_toolbar")
    if toolbar is not None:
        before_action = visual if isinstance(visual, QAction) else window.add_component_action
        toolbar.insertAction(before_action, window.revert_background_action)
        button = toolbar.widgetForAction(window.revert_background_action)
        if isinstance(button, QToolButton):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


def _install_window_fix() -> None:
    if getattr(MainWindow, "_curvemole_correct_background_controls", False):
        return

    original_init = MainWindow.__init__

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        _install_corrected_window_controls(window)

    MainWindow.__init__ = init
    MainWindow.subtract_background = _subtract_current_background
    MainWindow.subtract_all_backgrounds = _subtract_all_backgrounds
    MainWindow.revert_backgrounds = _revert_backgrounds
    MainWindow._curvemole_correct_background_controls = True


_install_apply_all_checkbox()
_install_window_fix()
