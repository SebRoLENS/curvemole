"""The window's fit flow: starting fits, applying results, sequential pause/resume.

FitController runs fits (Fit dialog, Quick Fit, sequential propagation) on the
TaskRunner, streams partial results, applies completed results to the project
and records fit Undo. It also holds behaviour that used to wrap MainWindow
methods from several modules:

* Sequential propagation pause/resume: the paused plan and result survive
  manual fits of the paused spectrum, and Resume continues from the corrected
  spectrum (formerly ``sequential_fit_ui``).
* The always-visible Continue / Terminate / Last pause reason buttons in the
  status bar (formerly ``sequential_resume_button``).
* Quick Fit keeps the zoom the user reaches with the mouse wheel while it runs
  (formerly ``quick_fit_zoom_fix``).

MainWindow calls :class:`FitController` at fixed points (fit completion, task
start/end, refresh, theme changes) instead of having these behaviours stacked
as wrappers whose order depended on import order.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from curvemole.core.data import CurveState
from curvemole.core.fitting import CancellationToken, FitMode, FitPlan, FitResult, Fitter
from curvemole.core.parameters import resolve_parameter_values
from curvemole.core.state import restore_model
from curvemole.gui.dialogs import FitPlanDialog
from curvemole.gui.plot_view import _capture_view_range, _restore_view_range
from curvemole.gui.windowing import transient_widget


# -- Quick Fit view -------------------------------------------------------
class _QuickFitWheelZoomFilter(QObject):
    """Guarantee wheel zoom on the main plot while Quick Fit is active."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched: QObject, event: Any) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        window = self.window
        if not getattr(window, "_curvemole_quick_fit_running", False):
            return False
        workspace = window.plot_workspace
        if getattr(workspace, "_view_locked", False):
            return False
        viewport = workspace.graphics.viewport()
        if watched is not viewport:
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False

        scene_pos = workspace.graphics.mapToScene(event.position().toPoint())
        main_view = workspace.view_box
        if not main_view.sceneBoundingRect().contains(scene_pos):
            return False

        centre = main_view.mapSceneToView(scene_pos)
        # One ordinary wheel notch zooms by 15%; fractional/high-resolution wheel
        # deltas scale smoothly using the same exponential rule.
        factor = 0.85 ** (delta / 120.0)
        main_view.disableAutoRange()
        main_view.scaleBy((factor, factor), center=centre)
        event.accept()
        return True


def _ensure_wheel_filter(window: Any) -> None:
    if getattr(window, "_curvemole_quick_fit_wheel_filter", None) is not None:
        return
    event_filter = _QuickFitWheelZoomFilter(window)
    window.plot_workspace.graphics.viewport().installEventFilter(event_filter)
    window._curvemole_quick_fit_wheel_filter = event_filter


def _prepare_interactive_quick_fit_view(window: Any) -> None:
    """Make Quick Fit redraws unable to suppress manual wheel navigation."""
    ranges = _capture_view_range(window)
    workspace = window.plot_workspace
    main_view = workspace.view_box
    residual_view = workspace.residual_plot.getViewBox()

    # Re-apply the normal interaction state in case a previous redraw left the
    # pyqtgraph ViewBox mouse flags stale, then freeze linked auto-ranging.
    workspace._update_interaction_state()
    main_view.disableAutoRange()
    residual_view.disableAutoRange()
    _restore_view_range(window, ranges)
    _ensure_wheel_filter(window)


# -- sequential pause/resume ----------------------------------------------
def resume_sequence(window: Any) -> None:
    if not window._ensure_editable() or window.task_running:
        return
    result = getattr(window, "_sequential_pause_result", None) or window._paused_result
    plan_template = getattr(window, "_sequential_resume_plan", None) or window.last_fit_plan
    if not result or not result.paused_curve_id or not plan_template:
        return
    try:
        start = plan_template.curve_ids.index(result.paused_curve_id)
    except ValueError:
        return
    plan = copy.deepcopy(plan_template)
    # The manually approved paused spectrum becomes the new source. The
    # propagating fitter deliberately skips the first curve and starts at the next one.
    source_id = window.active_curve_id or result.paused_curve_id
    existing_ids = {curve.id for curve in window.project.curves}
    if source_id not in existing_ids:
        window._notify(window.tr("Activate the corrected source spectrum first."), warning=True)
        return
    remaining = [
        curve_id for curve_id in plan.curve_ids[start + 1:]
        if curve_id in existing_ids and curve_id != source_id
    ]
    if not remaining:
        window._sequential_resume_plan = None
        window._sequential_pause_result = None
        window._paused_result = None
        window._notify(window.tr("Sequential fit completed: no remaining spectra."))
        window.refresh_all()
        return
    if hasattr(plan, "progress_completed"):
        plan.progress_completed += start
        # Removed targets no longer consume a budget; retain completed work.
        plan.progress_total = plan.progress_completed + len(remaining)
    plan.curve_ids = [source_id, *remaining]
    if getattr(plan, "copied_component_ids", None) is not None:
        current_ids = {item.id for item in window.project.model_for(source_id).components}
        previous_ids = set(getattr(window, "_sequential_pause_source_ids", current_ids))
        # Include functions added during the repair, while preserving the
        # exclusion of functions already local to the paused target.
        copied = set(plan.copied_component_ids) | (current_ids - previous_ids)
        if source_id != result.paused_curve_id:
            copied = current_ids
        plan.copied_component_ids = tuple(sorted(
            (copied & current_ids) - set(getattr(plan, "excluded_copy_component_ids", ()))
        ))
    plan.spectrum_weights = {
        curve_id: plan.spectrum_weights.get(curve_id, 1.0)
        for curve_id in plan.curve_ids
    }
    window.last_fit_plan = copy.deepcopy(plan)
    window._run_fit(plan)


# -- status-bar controls ---------------------------------------------------
def style_buttons(window: Any) -> None:
    button = getattr(window, "sequential_resume_button", None)
    if button is None:
        return
    dark = QApplication.palette().color(QPalette.ColorRole.Button).lightness() < 128
    background, foreground, border, hover, pressed = (
        ("#5EEAD4", "#083B36", "#B5FFF1", "#99F6E4", "#2DD4BF") if dark else
        ("#0F766E", "#FFFFFF", "#0B5F59", "#115E59", "#134E4A")
    )
    disabled_bg, disabled_fg = ("#475569", "#CBD5E1") if dark else ("#E2E8F0", "#64748B")
    button.setStyleSheet(
        "QPushButton#sequential_resume_button {"
        f"background-color: {background}; color: {foreground}; border: 2px solid {border};"
        "border-radius: 7px; padding: 6px 18px; font-weight: bold; }"
        f"QPushButton#sequential_resume_button:hover {{ background-color: {hover}; }}"
        f"QPushButton#sequential_resume_button:pressed {{ background-color: {pressed}; }}"
        "QPushButton#sequential_resume_button:disabled {"
        f"background-color: {disabled_bg}; color: {disabled_fg}; border-color: {disabled_fg}; }}"
    )
    stop = getattr(window, "sequential_stop_button", None)
    if stop is not None:
        stop.setStyleSheet(button.styleSheet().replace("sequential_resume_button", "sequential_stop_button")
            .replace(background, "#FDA4AF" if dark else "#BE123C")
            .replace(foreground, "#4C0519" if dark else "#FFFFFF")
            .replace(border, "#FFE4E6" if dark else "#881337")
            .replace(hover, "#FECDD3" if dark else "#9F1239")
            .replace(pressed, "#FB7185" if dark else "#881337"))


def set_resume_available(window: Any, available: bool) -> None:
    enabled = available and not window.task_running
    window.resume_action.setEnabled(enabled)
    button = getattr(window, "sequential_resume_button", None)
    if button is not None:
        button.setVisible(available)
        button.setEnabled(enabled)
    stop = getattr(window, "sequential_stop_button", None)
    if stop is not None:
        stop.setVisible(available)
        stop.setEnabled(enabled)
    reason = getattr(window, "sequential_pause_reason_button", None)
    if reason is not None:
        has_reason = available and bool(window.project.results.get("last_sequential_pause_message"))
        reason.setVisible(has_reason)
        reason.setEnabled(has_reason)


def terminate_sequence(window: Any) -> None:
    if window.task_running:
        return
    window._sequential_resume_plan = None
    window._sequential_pause_result = None
    window._paused_result = None
    window._sequential_pause_source_ids = ()
    set_resume_available(window, False)
    window._notify(window.tr("Sequential fit terminated. Existing fits and model edits were retained."))


def sync_resume_controls(window: Any) -> None:
    if not hasattr(window, "resume_action"):
        return
    paused = getattr(window, "_sequential_pause_result", None) or getattr(window, "_paused_result", None)
    set_resume_available(window, bool(paused and paused.paused_curve_id))


def install_status_controls(window: Any) -> None:
    button = QPushButton("▶  " + window.tr("Continue sequential fit"), window)
    button.setObjectName("sequential_resume_button")
    button.setMinimumHeight(38)
    button.setToolTip(
        window.tr(
            "Continue the paused sequential refinement using the current spectrum as the new source."
        )
    )
    button.setVisible(False)
    button.setEnabled(False)
    button.clicked.connect(window.resume_sequence)
    window.sequential_resume_button = button
    window.statusBar().addPermanentWidget(button)
    stop = QPushButton("■  " + window.tr("Terminate sequential fit"), window)
    stop.setObjectName("sequential_stop_button")
    stop.setMinimumHeight(38)
    stop.setToolTip(window.tr("Discard the paused sequence while keeping all existing fits and model edits."))
    stop.clicked.connect(window.terminate_sequence)
    window.sequential_stop_button = stop
    window.statusBar().addPermanentWidget(stop)
    reason = QPushButton(window.tr("Last pause reason"), window)
    reason.setMinimumHeight(38)
    reason.setToolTip(window.tr(
        "Reopen the interruption message while the sequential fit is paused. "
        "This button disappears when the sequence finishes or is terminated."
    ))
    reason.clicked.connect(window.show_sequential_pause_reason)
    window.sequential_pause_reason_button = reason
    window.statusBar().addPermanentWidget(reason)
    style_buttons(window)
    sync_resume_controls(window)


class FitController(QObject):
    """Coordinates fit completion, sequential pause/resume and Quick Fit view."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def install(self) -> None:
        install_status_controls(self.window)

    # Quick Fit ------------------------------------------------------------
    def quick_fit(self, start: Any) -> None:
        window = self.window
        previously_busy = window.task_running
        start()
        # A new task means Quick Fit really started; early returns are ignored.
        if not previously_busy and window.task_running:
            window._curvemole_quick_fit_running = True
            _prepare_interactive_quick_fit_view(window)

    # Fit completion -------------------------------------------------------
    def fit_finished(self, result: Any, apply_result: Any) -> None:
        window = self.window
        existing_plan = getattr(window, "_sequential_resume_plan", None)
        existing_pause = getattr(window, "_sequential_pause_result", None)
        pause_plan = None
        if result.mode == FitMode.SEQUENTIAL and result.paused_curve_id:
            pause_plan = copy.deepcopy(getattr(window, "_running_fit_plan", None) or window.last_fit_plan)
        preserve_view = bool(getattr(window, "_curvemole_quick_fit_running", False))
        ranges = _capture_view_range(window) if preserve_view else None
        try:
            apply_result(result)
        finally:
            if ranges is not None:
                # Normal fits auto-range; Quick Fit keeps the range the user
                # reached with the mouse wheel while it ran.
                _restore_view_range(window, ranges)
            window._curvemole_quick_fit_running = False
        if result.mode == FitMode.SEQUENTIAL and result.paused_curve_id:
            window._sequential_resume_plan = pause_plan or existing_plan
            window._sequential_pause_result = result
            window._paused_result = result
            window._sequential_pause_source_ids = tuple(
                item.id for item in window.project.model_for(result.paused_curve_id).components
            )
            window.resume_action.setEnabled(True)
        elif result.mode == FitMode.SEQUENTIAL and result.success:
            window._sequential_resume_plan = None
            window._sequential_pause_result = None
            window._sequential_pause_source_ids = ()
        elif existing_plan is not None and existing_pause is not None:
            # A manual fit of the paused spectrum must not discard the suspended
            # sequence; the corrected spectrum becomes the next source on Resume.
            window._sequential_resume_plan = existing_plan
            window._sequential_pause_result = existing_pause
            window._paused_result = existing_pause
            window.resume_action.setEnabled(True)
            window.statusBar().showMessage(
                window.tr("Sequential fit is paused. Resume when the current spectrum is satisfactory."),
                8000,
            )
        sync_resume_controls(window)

    def task_done(self) -> None:
        # Also clear the Quick Fit marker on cancellation/failure.
        self.window._curvemole_quick_fit_running = False
        sync_resume_controls(self.window)

    # Sequential sequence ---------------------------------------------------
    def resume_sequence(self) -> None:
        resume_sequence(self.window)
        sync_resume_controls(self.window)

    def terminate_sequence(self) -> None:
        terminate_sequence(self.window)

    def set_resume_available(self, available: bool) -> None:
        set_resume_available(self.window, available)

    def sync(self) -> None:
        sync_resume_controls(self.window)

    def style(self) -> None:
        style_buttons(self.window)

    def start_fit(self) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        if window.task_running:
            return
        selected = window.curve_tree.selected_curve_ids()
        if not selected and window.active_curve_id:
            selected = {window.active_curve_id}
        with transient_widget(FitPlanDialog(window.project, selected, window.fit_settings, window)) as dialog:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            plan = dialog.plan()
            window.fit_settings = plan.settings
            window.last_fit_plan = plan
            window._run_fit(plan)

    def _quick_fit_core(self) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        if window.task_running:
            return
        selected = window.curve_tree.selected_curve_ids()
        if not selected and window.active_curve_id:
            selected = {window.active_curve_id}
        if not selected:
            window._notify(window.tr("Select or activate at least one curve first."), warning=True)
            return
        settings = window.last_fit_plan.settings if window.last_fit_plan is not None else window.fit_settings
        if getattr(window, "_sequential_pause_result", None) is not None:
            # Quick Fit repairs the active spectrum without consuming the saved
            # sequential queue or accidentally running a one-curve sequence.
            selected = {window.active_curve_id} if window.active_curve_id else selected
            settings = window.fit_settings
        plan = FitPlan(
            [curve.id for curve in window.project.curves if curve.id in selected],
            FitMode.INDEPENDENT,
            settings=copy.deepcopy(settings),
        )
        try:
            plan.validate()
        except Exception as exc:
            window._show_error(window.tr("Quick Fit"), exc)
            return
        window.fit_settings = copy.deepcopy(plan.settings)
        window.last_fit_plan = copy.deepcopy(plan)
        window._run_fit(plan)

    def _run_fit(self, plan: FitPlan) -> None:
        window = self.window
        if window.task_running:
            window._notify(window.tr("Another task is already running."), warning=True)
            return
        window._running_fit_plan = copy.deepcopy(plan)
        window._fit_task_active = True
        window._cancellation = CancellationToken()
        cancellation = window._cancellation
        # The worker gets its own registry snapshot: disabling a plugin on the
        # GUI thread during a running task must not change the functions it uses.
        fitter = Fitter(window.registry.copy())
        curve_map = {curve.id: copy.deepcopy(curve) for curve in window.project.curves
                     if curve.id in plan.curve_ids}
        stream = plan.mode == FitMode.INDEPENDENT and len(plan.curve_ids) > 1
        # Every mode owns its inputs, including sequential propagation. This
        # permits coherent saves and safe retirement of an unresponsive task.
        models = {cid: window.project.model_for(cid).clone() for cid in plan.curve_ids}
        plan = copy.deepcopy(plan)
        window._task_snapshot_safe = True

        from curvemole.core import live_fit_progress

        live_interval = live_fit_progress.LIVE_PREVIEW_SECONDS

        def operation(progress, publish=None):
            last_live = [-math.inf]

            def live_progress(value, text):
                if publish is not None and text.startswith("Evaluation "):
                    now = time.monotonic()
                    # Throttle previews: a full plot refresh per evaluation slows
                    # the fit and competes for the GIL.
                    if now - last_live[0] >= live_interval:
                        last_live[0] = now
                        parameters = {path: parameter for cid, model in models.items()
                                      for path, parameter in model.parameter_map(cid).items()}
                        try:
                            values = resolve_parameter_values(parameters)
                        except Exception:  # noqa: BLE001 - previews are best effort
                            # A transiently invalid link elsewhere must not fail a valid fit.
                            values = None
                        if values is not None:
                            publish({"live_values": values})
                progress(value, text)
            return fitter.fit(
                plan, curve_map, models, cancellation=cancellation,
                progress=live_progress,
                on_curve_result=(lambda cid, result: publish((cid, result))) if stream and publish else None,
            )

        def finished(result):
            window.plot_workspace._live_parameter_values = None
            # Apply worker-side propagation and states only on the GUI thread.
            for cid in plan.curve_ids:
                curve = window.project.dataset.curve(cid)
                curve.state = curve_map[cid].state
                current = window.project.model_for(cid)
                saved = models[cid]
                restore_model(current, saved)
            window._fit_finished(result)
            window.fit_lifecycle.complete(result)

        def partial(item):
            if isinstance(item, dict) and "live_values" in item:
                from curvemole.gui.live_fit_refresh import refresh_snapshot
                refresh_snapshot(window, item["live_values"])
            else:
                window._partial_fit_result(item)

        window.fit_lifecycle.begin(plan)
        try:
            window._run_background(operation, finished, window.tr("Fitting…"), partial=partial)
        except Exception:
            window.fit_lifecycle.abort()
            window.fit_lifecycle.done()
            raise

    def _partial_fit_result(self, item: tuple[str, FitResult]) -> None:
        window = self.window
        """Expose a completed independent spectrum while other fits are queued."""
        curve_id, result = item
        curve = window.project.dataset.curve(curve_id)
        if result.success:
            window._apply_fit_result_to_project(result)
            from curvemole.core.fit_records import (
                baseline_for_curve,
                individual_plan,
                plan_to_record,
            )

            plan = window._running_fit_plan
            baseline = baseline_for_curve(result, curve_id)
            baseline.success = True
            records = dict(window.project.results.get("fit_by_curve", {}))
            previous_key = records.get(curve_id, {}).get("global_key")
            affected_ids = {curve_id}
            if previous_key is not None:
                affected_ids.update(cid for cid, record in records.items()
                                    if record.get("global_key") == previous_key)
                records = {cid: record for cid, record in records.items()
                           if record.get("global_key") != previous_key}
                baselines = dict(window.project.results.get("global_fit_baselines", {}))
                baselines.pop(previous_key, None)
                window.project.results["global_fit_baselines"] = baselines
            records[curve_id] = {
                "plan": plan_to_record(individual_plan(plan, curve_id)),
                "baseline": baseline,
            }
            window.project.results["fit_by_curve"] = records
            for key in ("uncertainty_reports_by_curve", "uncertainty_by_curve"):
                updated = dict(window.project.results.get(key, {}))
                for affected_id in affected_ids:
                    updated.pop(affected_id, None)
                window.project.results[key] = updated
            window.project.results["last_fit"] = result
        else:
            curve.state = CurveState.FAILED
        window.project.results["last_attempt"] = result
        window.project.touch()
        window.refresh_all()

    def _apply_fit_result_to_project(self, result: FitResult) -> None:
        # Fitting runs in a worker thread. Commit the returned estimates explicitly
        # to the GUI-side project so the redraw never depends on worker-side mutation.
        window = self.window
        fitted_curve_ids = window._successful_fit_curve_ids(result)
        if not fitted_curve_ids:
            return

        window.project.invalidate_fits(fitted_curve_ids, preserve=fitted_curve_ids)
        parameter_map = window.project.parameter_map()
        for path, estimate in result.parameters.items():
            curve_id = path.split(".", 1)[0]
            if curve_id not in fitted_curve_ids or path not in parameter_map:
                continue
            parameter = parameter_map[path]
            parameter.value = float(estimate.value)
            parameter.standard_error = estimate.standard_error
            parameter.ci_low = estimate.ci_low
            parameter.ci_high = estimate.ci_high
        for curve_id in fitted_curve_ids:
            try:
                window.project.dataset.curve(curve_id).state = CurveState.FITTED
            except KeyError:
                continue

    def _successful_fit_curve_ids(self, result: FitResult) -> set[str]:
        window = self.window
        if result.success:
            return set(result.curve_outputs)
        if result.mode == FitMode.GLOBAL:
            return set()
        # A merged independent/sequential result fails when any one fit fails.
        # Its successful spectra are still marked FITTED by the fitter.
        return {
            curve_id for curve_id in result.curve_outputs
            if window.project.dataset.curve(curve_id).state == CurveState.FITTED
        }

    def _fit_finished_core(self, result: FitResult) -> None:
        window = self.window
        successful_ids = window._successful_fit_curve_ids(result)
        window._apply_fit_result_to_project(result)
        window.project.results["last_attempt"] = result
        if result.paused_curve_id:
            window.project.results["last_sequential_pause_message"] = result.message
        if result.success:
            window.project.results["last_fit"] = result
        if successful_ids:
            from curvemole.core.fit_records import (
                baseline_for_curve,
                individual_plan,
                plan_to_record,
            )

            plan = getattr(window, "_running_fit_plan", None)
            if plan is None:
                plan = FitPlan(list(result.curve_outputs), result.mode, copy.deepcopy(result.settings))
            # Fit undo captures the outer results mapping, so replace nested maps
            # instead of mutating its previously captured values.
            records = dict(window.project.results.get("fit_by_curve", {}))
            reports = dict(window.project.results.get("uncertainty_reports_by_curve", {}))
            analyses = dict(window.project.results.get("uncertainty_by_curve", {}))
            global_baselines = dict(window.project.results.get("global_fit_baselines", {}))
            for curve_id in successful_ids:
                previous_key = records.get(curve_id, {}).get("global_key")
                if previous_key is not None:
                    for related_id, record in list(records.items()):
                        if record.get("global_key") == previous_key:
                            records.pop(related_id, None)
                            reports.pop(related_id, None)
                            analyses.pop(related_id, None)
                    global_baselines.pop(previous_key, None)
                reports.pop(curve_id, None)
                analyses.pop(curve_id, None)
            global_key = None
            if result.mode == FitMode.GLOBAL:
                global_key = result.timestamp
                global_baselines[global_key] = result
            for curve_id in successful_ids:
                record = {"plan": plan_to_record(individual_plan(plan, curve_id))}
                if global_key is not None:
                    record["global_key"] = global_key
                else:
                    baseline = baseline_for_curve(result, curve_id)
                    baseline.success = True  # The aggregate may include failed neighbours.
                    record["baseline"] = baseline
                records[curve_id] = record
            window.project.results["fit_by_curve"] = records
            window.project.results["global_fit_baselines"] = global_baselines
            window.project.results["uncertainty_reports_by_curve"] = reports
            window.project.results["uncertainty_by_curve"] = analyses
        window.project.snapshot(
            "Fit",
            {
                "mode": result.mode.value,
                "settings": result.to_dict(arrays=False)["settings"],
                "result": result.to_dict(arrays=False),
            },
        )
        window.resume_action.setEnabled(bool(result.paused_curve_id))
        window._paused_result = result if result.paused_curve_id else None
        if result.paused_curve_id:
            window.active_curve_id = result.paused_curve_id
        window.refresh_all()
        if result.success or result.curve_outputs:
            window.plot_workspace.auto_range()
        if result.paused_curve_id:
            window.show_sequential_pause_reason()
        elif result.success:
            window._notify(window.tr("Fit completed."))
        else:
            window._notify(result.message, warning=True)

    def _recover_missing_fit_records(self) -> None:
        window = self.window
        """Recover successful spectra from an older, partially failed batch fit."""
        from curvemole.core.fit_records import baseline_for_curve, individual_plan, plan_to_record

        attempt = window.project.results.get("last_attempt")
        if not isinstance(attempt, FitResult) or attempt.mode == FitMode.GLOBAL:
            return
        records = window.project.results.setdefault("fit_by_curve", {})
        available = {curve.id for curve in window.project.curves}
        plan = FitPlan(list(attempt.curve_outputs), attempt.mode, copy.deepcopy(attempt.settings))
        recovered = False
        for curve_id in attempt.curve_outputs:
            if curve_id not in available or curve_id in records:
                continue
            if window.project.dataset.curve(curve_id).state != CurveState.FITTED:
                continue
            baseline = baseline_for_curve(attempt, curve_id)
            baseline.success = True
            records[curve_id] = {"plan": plan_to_record(individual_plan(plan, curve_id)),
                                 "baseline": baseline}
            recovered = True
        if recovered:
            window.project.touch()

    def show_sequential_pause_reason(self) -> None:
        window = self.window
        message = window.project.results.get("last_sequential_pause_message")
        if message:
            QMessageBox.warning(window, window.tr("Sequential fit — last pause reason"), str(message))
