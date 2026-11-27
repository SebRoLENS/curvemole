"""Uncertainty analyses for the main window.

UncertaintyController runs and records Monte Carlo, bootstrap, block bootstrap
and profile-likelihood analyses (including background-uncertainty treatments),
stores their reports per spectrum and method, deletes them, and keeps the
displayed method in sync between the Model panel and the Uncertainty Analysis
tool. MainWindow keeps delegating methods with the historical names.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QObject,
    QSignalBlocker,
    Qt,
)
from PySide6.QtWidgets import (
    QMessageBox,
)

from curvemole.core.data import Curve, CurveState
from curvemole.core.errors import FitError
from curvemole.core.fitting import (
    CancellationToken,
    FitMode,
    FitPlan,
    FitResult,
    Fitter,
)
from curvemole.core.uncertainty import AdaptiveReplicateSettings, UncertaintyAnalyzer
from curvemole.core.uncertainty_status import uncertainty_warning
from curvemole.gui.windowing import transient_widget


class UncertaintyController(QObject):
    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def _update_uncertainty_tags(self) -> None:
        window = self.window
        window.curve_tree.set_uncertainty_method(window.uncertainty_panel.method.currentData())

    def _sync_uncertainty_method(self) -> None:
        window = self.window
        from curvemole.core.analysis_errors import display_method

        method = display_method(window.project)
        if method is not None:
            ui_method = "monte_carlo" if method == "parametric_monte_carlo" else method
            index = window.uncertainty_panel.method.findData(ui_method)
            if index >= 0 and index != window.uncertainty_panel.method.currentIndex():
                with QSignalBlocker(window.uncertainty_panel.method):
                    window.uncertainty_panel.method.setCurrentIndex(index)
                window.uncertainty_panel._update_controls()
        window._update_uncertainty_tags()

    def _uncertainty_method_changed(self, _index: int) -> None:
        window = self.window
        window._select_uncertainty_display(window.uncertainty_panel.method.currentData())

    def _fit_for_uncertainty(self, curve_id: str) -> tuple[FitResult, FitPlan] | None:
        window = self.window
        from curvemole.core.fit_records import (
            baseline_for_curve,
            individual_plan,
            plan_from_record,
        )

        window._recover_missing_fit_records()
        record = window.project.results.get("fit_by_curve", {}).get(curve_id)
        if record:
            baseline = (window.project.results.get("global_fit_baselines", {}).get(record["global_key"])
                        if "global_key" in record else record.get("baseline"))
            if baseline is None:
                return None
            if isinstance(baseline, dict):
                baseline = FitResult.from_dict(baseline)
            return baseline, plan_from_record(record["plan"])
        # Existing projects only retained the most recent fit. Do not infer
        # historical residuals or covariance from the model currently shown.
        recorded = window.project.results.get(curve_id)
        if isinstance(recorded, FitResult) and recorded.success and curve_id in recorded.curve_outputs:
            saved_plan = recorded.provenance.get("plan")
            plan = (plan_from_record(saved_plan) if saved_plan else
                    FitPlan([curve_id], settings=copy.deepcopy(recorded.settings)))
            return baseline_for_curve(recorded, curve_id), individual_plan(plan, curve_id)
        latest = window._last_fit_result()
        if latest is None or curve_id not in latest.curve_outputs:
            return None
        plan = window.last_fit_plan
        if plan is None or curve_id not in plan.curve_ids:
            plan = FitPlan(list(latest.curve_outputs), latest.mode, copy.deepcopy(latest.settings))
        if any(cid not in {curve.id for curve in window.project.curves} for cid in plan.curve_ids):
            return None
        return baseline_for_curve(latest, curve_id), individual_plan(plan, curve_id)

    def _choose_background_uncertainty(self, curves: list[Curve]) -> str | None:
        window = self.window
        from curvemole.core.background_uncertainty import joint_background_components

        unavailable = []
        for curve in curves:
            try:
                joint_background_components(curve, window.project.model_for(curve.id))
            except FitError as exc:
                unavailable.append(str(exc))
        with transient_widget(QMessageBox(window)) as dialog:
            dialog.setWindowTitle(window.tr("Background uncertainty"))
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(window.tr("An estimated background was subtracted from {spectra}.")
                           .format(spectra=", ".join(curve.name for curve in curves)))
            explanation = window.tr(
                "Keep the corrected data and report intervals conditional on the subtracted background, "
                "or fit the signal and background together on the data before subtraction. "
                "For a spline, the joint fit can adjust node heights while keeping their X positions fixed. "
                "Both choices create a separate analysis without changing the workspace fit."
            )
            if unavailable:
                explanation += "\n\n" + window.tr("Joint fitting is unavailable.") + "\n" + "\n".join(unavailable)
            dialog.setInformativeText(explanation)
            fixed = dialog.addButton(window.tr("Ignore background uncertainty"), QMessageBox.ButtonRole.ActionRole)
            joint = dialog.addButton(window.tr("Refit with background"), QMessageBox.ButtonRole.ActionRole)
            joint.setEnabled(not unavailable)
            cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.setDefaultButton(joint if joint.isEnabled() else cancel)
            dialog.exec()
            return {fixed: "fixed", joint: "joint"}.get(dialog.clickedButton())

    def start_uncertainty(self, method: str, replicates: int, option: Any,
                          scope: str = "active", workers: int = 1,
                          adaptive: AdaptiveReplicateSettings | None = None,
                          replica_timeout_seconds: float = 60.0) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        if window.task_running:
            window._notify(window.tr("Another task is already running."), warning=True)
            return
        if adaptive is not None:
            try:
                adaptive.validate()
            except Exception as exc:
                window._show_error(window.tr("Adaptive uncertainty settings"), exc)
                return
        method_index = window.uncertainty_panel.method.findData(method)
        if method_index >= 0:
            window.uncertainty_panel.method.setCurrentIndex(method_index)
        if scope == "all":
            ids = [curve.id for curve in window.project.curves if curve.state == CurveState.FITTED]
        elif scope == "selected":
            selected = window.curve_tree.selected_curve_ids()
            ids = [curve.id for curve in window.project.curves if curve.id in selected]
        else:
            ids = [window.active_curve_id] if window.active_curve_id else []
        if method == "profile_likelihood" and len(ids) != 1:
            window._notify(window.tr("Profile likelihood requires one active spectrum and parameter."), warning=True)
            return
        available = {curve.id: curve for curve in window.project.curves}
        subtracted = {cid for cid, curve in available.items()
                      if any(step.is_estimated_background for step in curve.transformations)}
        jobs = []
        missing = []
        background_ids = set()
        for curve_id in ids:
            record = window._fit_for_uncertainty(curve_id)
            if record is not None and all(cid in available for cid in record[1].curve_ids):
                baseline, plan = record
            elif curve_id in subtracted:
                baseline, plan = None, FitPlan([curve_id], settings=copy.deepcopy(window.fit_settings))
            else:
                missing.append(curve_id)
                continue
            plan_backgrounds = subtracted.intersection(plan.curve_ids)
            if not plan_backgrounds and (baseline is None or not baseline.success or any(
                available[cid].state != CurveState.FITTED
                for cid in plan.curve_ids
            )):
                missing.append(curve_id)
                continue
            if method == "profile_likelihood" and len(plan.curve_ids) != 1:
                window._notify(window.tr("Profile likelihood requires an independent single-spectrum fit."), warning=True)
                return
            if method == "monte_carlo" and not plan_backgrounds and any(
                available[cid].y_error_scales(
                    include_inverse_variance=plan.settings.absolute_sigma is not False) is None
                for cid in plan.curve_ids
            ):
                missing.append(curve_id)
                continue
            plan.settings.confidence_level = window.uncertainty_panel.confidence.value() / 100
            background_ids.update(plan_backgrounds)
            jobs.append((curve_id, baseline, plan))
        if not jobs:
            window._notify(window.tr("No usable saved fit for the requested spectra. Refit them first."), warning=True)
            return
        if missing:
            window._notify(window.tr("Skipped {count} spectra without a usable baseline or required noise data.")
                         .format(count=len(missing)), warning=True)
        treatment = window._choose_background_uncertainty(
            [curve for cid, curve in available.items() if cid in background_ids]) if background_ids else None
        if background_ids and treatment is None:
            return
        if method == "covariance" and not background_ids:
            window._uncertainty_finished([(curve_id, baseline, baseline)
                                        for curve_id, baseline, _ in jobs])
            return
        profile_points = window.uncertainty_panel.profile_points.value()
        try:
            profile_lower = float(window.uncertainty_panel.profile_lower.text()) if window.uncertainty_panel.profile_lower.text().strip() else None
            profile_upper = float(window.uncertainty_panel.profile_upper.text()) if window.uncertainty_panel.profile_upper.text().strip() else None
        except ValueError:
            if method == "profile_likelihood":
                window._notify(window.tr("Profile limits must be numeric, or blank for automatic."), warning=True)
                return
            profile_lower = profile_upper = None
        # The worker gets its own registry snapshot: disabling a plugin on the
        # GUI thread during a running task must not change the functions it uses.
        fitter = Fitter(window.registry.copy(), extensions=window.plugin_manager.extensions)
        analyzer = UncertaintyAnalyzer(fitter,
                                       replica_timeout_seconds=replica_timeout_seconds)
        needed_ids = {cid for _, _, plan in jobs for cid in plan.curve_ids}
        curve_map = {curve.id: copy.deepcopy(curve) for curve in window.project.curves
                     if curve.id in needed_ids}
        models = {cid: window.project.model_for(cid).clone() for cid in needed_ids}
        window._cancellation = CancellationToken()
        cancellation = window._cancellation
        window._task_snapshot_safe = True
        grouped: dict[tuple[Any, ...], list[str]] = {}
        unique_jobs = []
        for curve_id, baseline, plan in jobs:
            key = (("global", baseline.timestamp if baseline else None, tuple(plan.curve_ids))
                   if plan.mode == FitMode.GLOBAL else ("individual", curve_id))
            if key not in grouped:
                unique_jobs.append((curve_id, baseline, plan, key))
                grouped[key] = []
            grouped[key].append(curve_id)

        window._uncertainty_task = {
            "method": "parametric_monte_carlo" if method == "monte_carlo" else method,
            "curve_ids": {cid for cid, _, _ in jobs},
            "completed": set(),
            "background_treatment": treatment,
        }
        replica_global_search = window.uncertainty_panel.replica_global_search.isChecked()

        def prepare_inputs(baseline, plan):
            from curvemole.core.background_uncertainty import fit_background_uncertainty

            curves = {cid: curve_map[cid] for cid in plan.curve_ids}
            analysis_models = {cid: models[cid] for cid in plan.curve_ids}
            if background_ids.intersection(plan.curve_ids):
                baseline, curves, analysis_models = fit_background_uncertainty(
                    fitter, plan, curves, analysis_models, treatment, cancellation)
            if method in {"monte_carlo", "residual_bootstrap", "block_bootstrap"} and replica_global_search:
                plan = copy.deepcopy(plan)
                plan.settings.solver = "differential_evolution"
            return baseline, plan, curves, analysis_models

        def operation(progress: Callable[[float | None, str], None], publish=None) -> Any:
            completed = []
            if method not in {"profile_likelihood", "covariance"} and workers > 1 and len(unique_jobs) > 1:
                batch = [prepare_inputs(baseline, plan) for _, baseline, plan, _ in unique_jobs]
                results = analyzer.resampling_batch(
                    method, batch, replicates=replicates, option=option, adaptive=adaptive,
                    workers=workers, cancellation=cancellation,
                    progress=lambda count: progress(count / len(unique_jobs),
                                                    f"{method}: {count}/{len(unique_jobs)} spectra"),
                    on_result=(lambda index, result: publish([
                        (selected_id, batch[index][0], result)
                        for selected_id in grouped[unique_jobs[index][3]]
                    ])) if publish else None,
                )
                for (_, _, _, key), (baseline, _, _, _), result in zip(unique_jobs, batch, results, strict=True):
                    completed.extend((selected_id, baseline, result) for selected_id in grouped[key])
                return completed
            for index, (curve_id, baseline, plan, key) in enumerate(unique_jobs):
                cancellation.raise_if_cancelled()
                def step(value, message, index=index):
                    progress((index + (value or 0.0)) / len(unique_jobs), message)
                if background_ids.intersection(plan.curve_ids):
                    step(None, f"Fitting {curve_map[curve_id].name} for uncertainty analysis…")
                baseline, plan, curves, analysis_models = prepare_inputs(baseline, plan)
                if method == "covariance":
                    if not any(p.ci_low is not None and p.ci_high is not None
                               for p in baseline.parameters.values()):
                        raise FitError(" ".join(baseline.warnings) or "No parameter confidence intervals are available.")
                    result = baseline
                elif method == "profile_likelihood":
                    if not option:
                        raise RuntimeError("Choose a profile parameter.")
                    result = analyzer.profile_parameter(
                        baseline, curves[curve_id], analysis_models[curve_id],
                        str(option), confidence_level=plan.settings.confidence_level,
                        points=profile_points, lower=profile_lower, upper=profile_upper,
                        spectrum_weight=plan.spectrum_weights.get(curve_id, 1.0),
                        equal_contribution=plan.equal_contribution,
                        workers=workers,
                        cancellation=cancellation, progress=step)
                else:
                    arguments = dict(
                        baseline=baseline, plan=plan, curves=curves,
                        models=analysis_models, replicates=replicates, adaptive=adaptive,
                        workers=workers,
                        cancellation=cancellation, progress=step)
                    if method == "monte_carlo":
                        result = analyzer.parametric_monte_carlo(**arguments)
                    elif method == "block_bootstrap":
                        result = analyzer.block_bootstrap(**arguments, block_length=option)
                    else:
                        result = analyzer.residual_bootstrap(**arguments)
                completed.extend((selected_id, baseline, result) for selected_id in grouped[key])
                if publish:
                    publish([(selected_id, baseline, result) for selected_id in grouped[key]])
                progress((index + 1) / len(unique_jobs), f"Completed {curve_map[curve_id].name}")
            return completed

        if len(unique_jobs) > 1:
            window._run_background(operation, window._uncertainty_finished,
                                 window.tr("Uncertainty analysis…"),
                                 partial=window._partial_uncertainty_result)
        else:
            window._run_background(operation, window._uncertainty_finished,
                                 window.tr("Uncertainty analysis…"))

    def _partial_uncertainty_result(self, completed: list[tuple[str, FitResult, Any]]) -> None:
        window = self.window
        for curve_id, baseline, analysis_result in completed:
            window._store_uncertainty_result(curve_id, baseline, analysis_result)
        window.project.touch()
        window.curve_tree.populate(window.project, window.active_curve_id)
        if window.active_curve_id in {curve_id for curve_id, _, _ in completed}:
            window.uncertainty_panel.set_parameters(window.project, window.active_curve_id)
        window.model_panel.refresh_parameters()

    def _uncertainty_finished(self, result: Any) -> None:
        window = self.window
        if not isinstance(result, list):
            baseline = getattr(window, "_uncertainty_baseline", None) or window._last_fit_result() or result
            result = [(window.active_curve_id, baseline, result)]
        for curve_id, baseline, analysis_result in result:
            if curve_id is not None:
                window._store_uncertainty_result(curve_id, baseline, analysis_result)
        window.project.touch()
        window.curve_tree.populate(window.project, window.active_curve_id)
        window.uncertainty_panel.set_parameters(window.project, window.active_curve_id)
        window.model_panel.refresh_parameters()
        window.uncertainty_panel.results.show_method(window.uncertainty_panel.method.currentData())
        warnings = [uncertainty_warning(window.project, curve_id,
                    "covariance" if isinstance(analysis, FitResult) else getattr(analysis, "method", "profile_likelihood"))
                    for curve_id, _baseline, analysis in result if curve_id is not None]
        window._notify(window.tr("Uncertainty analysis finished with warnings. See the analysis panel.")
                     if any(warnings) else window.tr("Uncertainty analysis completed."), warning=any(warnings))

    def delete_uncertainty_analysis(self, method: str) -> None:
        window = self.window
        if not window._ensure_editable():
            return
        if window.task_running:
            window._notify(window.tr("Wait for the running task before deleting an analysis."), warning=True)
            return
        method = "parametric_monte_carlo" if method == "monte_carlo" else method
        names = {method, "monte_carlo"} if method == "parametric_monte_carlo" else {method}
        per_curve_keys = ("uncertainty_reports_by_curve", "uncertainty_by_curve", "uncertainty_failures_by_curve")
        global_keys = ("uncertainty", "uncertainty_reports")
        saved = {
            key: {curve_id: {name: value for name, value in methods.items() if name in names}
                  for curve_id, methods in window.project.results.get(key, {}).items()
                  if names.intersection(methods)} for key in per_curve_keys}
        old_global = {key: {name: value for name, value in window.project.results.get(key, {}).items() if name in names}
                      for key in global_keys}
        if not any(saved.values()) and not any(old_global.values()):
            return
        old_choice = window.project.results.get("uncertainty_display_method")

        def remove() -> None:
            for key in per_curve_keys:
                window.project.results[key] = {
                    curve_id: remaining for curve_id, methods in window.project.results.get(key, {}).items()
                    if (remaining := {name: value for name, value in methods.items() if name not in names})}
            for key in global_keys:
                window.project.results[key] = {name: value for name, value in window.project.results.get(key, {}).items()
                                             if name not in names}
            if window.project.results.get("uncertainty_display_method") in names:
                window.project.results.pop("uncertainty_display_method", None)

        def restore() -> None:
            for key, curves in saved.items():
                for curve_id, methods in curves.items():
                    window.project.results.setdefault(key, {}).setdefault(curve_id, {}).update(methods)
            for key, methods in old_global.items():
                window.project.results.setdefault(key, {}).update(methods)
            if old_choice is not None:
                window.project.results["uncertainty_display_method"] = old_choice

        window._push_change(window.tr("Delete uncertainty analysis"), remove, restore, modified_curve_ids=set())

    def _store_uncertainty_result(self, curve_id: str, baseline: FitResult, result: Any) -> None:
        window = self.window
        method = "covariance" if isinstance(result, FitResult) else getattr(result, "method", "profile_likelihood")
        window.project.results.get("uncertainty_failures_by_curve", {}).get(curve_id, {}).pop(method, None)
        task = getattr(window, "_uncertainty_task", None)
        if task and task["method"] == method:
            task["completed"].add(curve_id)
        window.project.results.setdefault("uncertainty", {})[method] = result
        window.project.results.setdefault("uncertainty_by_curve", {}).setdefault(curve_id, {})[method] = result
        analysis = (result.to_dict(include_samples=False)
                    if hasattr(result, "samples") else result.to_dict())
        if method not in {"covariance", "profile_likelihood"}:
            samples = np.asarray(result.samples)
            if samples.ndim == 2 and samples.shape[0] >= 3 and samples.shape[1] > 1:
                with np.errstate(invalid="ignore", divide="ignore"):
                    analysis["sample_correlation"] = np.corrcoef(samples, rowvar=False).tolist()
            analysis.pop("samples", None)
        window.project.results.setdefault("uncertainty_reports_by_curve", {}).setdefault(curve_id, {})[method] = {
            "baseline": baseline.to_dict(arrays=False), "analysis": analysis,
        }
        from curvemole.core.analysis_errors import DISPLAY_METHODS

        if window.project.results.get("uncertainty_display_method") not in DISPLAY_METHODS:
            window.project.results["uncertainty_display_method"] = method
            window._sync_uncertainty_method()

    def _select_uncertainty_display(self, method: str) -> None:
        window = self.window
        from curvemole.core.analysis_errors import DISPLAY_METHODS

        method = "parametric_monte_carlo" if method == "monte_carlo" else method
        if method not in DISPLAY_METHODS:
            return
        previous = window.project.results.get("uncertainty_display_method")
        window.project.results["uncertainty_display_method"] = method
        if previous != method and not window.project.read_only:
            window.project.touch()
        window._sync_uncertainty_method()
        window.uncertainty_panel.set_parameters(window.project, window.active_curve_id)
        window.model_panel.refresh_parameters()

    def _show_uncertainty_analysis(self) -> None:
        window = self.window
        curve_id = window.model_panel.display_method.curve_id
        if curve_id and curve_id != window.active_curve_id:
            window._set_active_curve(curve_id)
        window.activate_tool_dock(window.uncertainty_dock)
