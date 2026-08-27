"""Complete in-memory CurveMole workspace."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from curvemole.core.data import Curve, Dataset, Mask, Series
from curvemole.core.models import Component, Model
from curvemole.core.parameters import Parameter, resolve_parameter_values
from curvemole.version import __version__


@dataclass(slots=True)
class Project:
    name: str = "Untitled"
    dataset: Dataset = field(default_factory=Dataset)
    models: dict[str, Model] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    fit_history: list[dict[str, Any]] = field(default_factory=list)
    custom_functions: list[dict[str, Any]] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    export_config: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"project_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    application_version: str = __version__
    path: Path | None = None
    read_only: bool = False
    dirty: bool = False
    revision: int = 0

    @property
    def curves(self) -> list[Curve]:
        return self.dataset.curves

    def add_series(self, series: Series) -> None:
        self.dataset.add_series(series)
        for curve in series.curves:
            self.models.setdefault(curve.id, Model(name=f"Model for {curve.name}"))
        self.touch()

    def add_curve(self, curve: Curve, series: Series | None = None) -> Series:
        if series is None:
            if not self.dataset.series:
                self.dataset.add_series(Series("Imported data"))
            series = self.dataset.series[-1]
        series.add(curve)
        self.models[curve.id] = Model(name=f"Model for {curve.name}")
        self.touch()
        return series

    def remove_curve(self, curve_id: str) -> Curve:
        series = self.dataset.series_for(curve_id)
        curve = series.remove(curve_id)
        self.models.pop(curve_id, None)
        self.results.pop(curve_id, None)
        self.touch()
        return curve

    def model_for(self, curve_id: str) -> Model:
        if curve_id not in self.models:
            curve = self.dataset.curve(curve_id)
            self.models[curve_id] = Model(name=f"Model for {curve.name}")
        return self.models[curve_id]

    def parameter_map(self) -> dict[str, Parameter]:
        return {
            path: parameter
            for curve_id, model in self.models.items()
            for path, parameter in model.parameter_map(curve_id).items()
        }

    def resolved_parameter_values(self) -> dict[str, float]:
        return resolve_parameter_values(self.parameter_map())

    def add_component(self, curve_id: str, component: Component) -> None:
        self.model_for(curve_id).add(component)
        self.touch()

    def copy_fit(
        self,
        source_curve_id: str,
        target_curve_ids: list[str],
        *,
        structure: bool = True,
        values: bool = True,
        bounds_and_fixed: bool = True,
        links: bool = True,
        background: bool = True,
        masks: bool = False,
        fit_ranges: bool = False,
    ) -> None:
        source_model = self.model_for(source_curve_id)
        source_curve = self.dataset.curve(source_curve_id)
        for target_id in target_curve_ids:
            if target_id == source_curve_id:
                continue
            target_curve = self.dataset.curve(target_id)
            if structure:
                existing = self.models.get(target_id)
                selected = []
                for component in source_model.components:
                    if component.is_background and not background:
                        continue
                    clone = Component.from_dict(copy.deepcopy(component.to_dict()))
                    matching = None
                    if existing:
                        matching = next(
                            (
                                item
                                for item in existing.components
                                if item.id == component.id or item.name == component.name
                            ),
                            None,
                        )
                    for name, parameter in clone.parameters.items():
                        source_parameter = component.parameters[name]
                        target_parameter = matching.parameters.get(name) if matching else None
                        if not values and target_parameter is not None:
                            parameter.value = target_parameter.value
                        if not bounds_and_fixed and target_parameter is not None:
                            parameter.minimum = target_parameter.minimum
                            parameter.maximum = target_parameter.maximum
                            parameter.fixed = target_parameter.fixed
                        if not links:
                            parameter.link = target_parameter.link if target_parameter else None
                        elif parameter.link:
                            parameter.link = parameter.link.replace(
                                "${" + source_curve_id + ".", "${" + target_id + "."
                            )
                        parameter.value = min(max(parameter.value, parameter.minimum), parameter.maximum)
                    selected.append(clone)
                target_model = Model(name=f"Model for {target_curve.name}", components=selected)
                self.models[target_id] = target_model
            else:
                target_model = self.model_for(target_id)
                for source_component, target_component in zip(
                    source_model.components, target_model.components, strict=False
                ):
                    if source_component.is_background and not background:
                        continue
                    if background:
                        target_component.is_background = source_component.is_background
                    for name, source_parameter in source_component.parameters.items():
                        if name not in target_component.parameters:
                            continue
                        target = target_component.parameters[name]
                        if values:
                            target.value = min(max(source_parameter.value, target.minimum), target.maximum)
                        if bounds_and_fixed:
                            target.minimum = source_parameter.minimum
                            target.maximum = source_parameter.maximum
                            target.fixed = source_parameter.fixed
                        if links:
                            target.link = (
                                source_parameter.link.replace(
                                    "${" + source_curve_id + ".", "${" + target_id + "."
                                )
                                if source_parameter.link
                                else None
                            )
                        target.value = min(max(target.value, target.minimum), target.maximum)
            if masks:
                tolerance = float(self.ui_state.get("mask_transfer_tolerance", 0.0))
                target_curve.masks = {}
                for name, source_mask in source_curve.masks.items():
                    target_mask = Mask(name, np.zeros(len(target_curve), dtype=bool))
                    for lower, upper in source_mask.ranges:
                        lo, hi = sorted((lower, upper))
                        target_mask.excluded |= (
                            np.isfinite(target_curve.x)
                            & (target_curve.x >= lo - tolerance)
                            & (target_curve.x <= hi + tolerance)
                        )
                        target_mask.ranges.append((lo - tolerance, hi + tolerance))
                    for value in source_curve.x[source_mask.excluded & np.isfinite(source_curve.x)]:
                        distances = np.abs(target_curve.x - value)
                        finite = np.isfinite(distances)
                        if not np.any(finite):
                            continue
                        indices = np.flatnonzero(finite)
                        index = int(indices[np.argmin(distances[finite])])
                        if distances[index] <= tolerance:
                            target_mask.excluded[index] = True
                    target_curve.masks[name] = target_mask
                target_curve.active_mask = source_curve.active_mask
            if fit_ranges:
                target_curve.fit_ranges = list(source_curve.fit_ranges)
        self.touch()

    def touch(self) -> None:
        if self.read_only:
            raise PermissionError("This project is open read-only. Use Save As to create an editable copy.")
        self.dirty = True
        self.revision += 1
        self.modified_at = datetime.now(UTC).isoformat()

    def mark_saved(self, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        self.dirty = False

    def snapshot(self, reason: str, payload: dict[str, Any]) -> None:
        self.fit_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "reason": reason,
                "application_version": __version__,
                **payload,
            }
        )
        self.touch()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "application_version": self.application_version,
            "series": [
                {
                    "id": series.id,
                    "name": series.name,
                    "metadata": series.metadata,
                    "curve_ids": [curve.id for curve in series.curves],
                }
                for series in self.dataset.series
            ],
            "curves": {curve.id: curve.to_metadata() for curve in self.curves},
            "models": {curve_id: model.to_dict() for curve_id, model in self.models.items()},
            "results": self.results,
            "fit_history": self.fit_history,
            "custom_functions": self.custom_functions,
            "ui_state": self.ui_state,
            "export_config": self.export_config,
        }
