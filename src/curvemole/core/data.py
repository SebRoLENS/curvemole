"""One-dimensional data, masks, series, and reversible transformations."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np
from scipy import integrate

from curvemole.core.errors import DataValidationError


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _array(values: Iterable[float] | np.ndarray | None, *, length: int | None = None) -> np.ndarray | None:
    if values is None:
        return None
    result = np.asarray(values, dtype=np.float64).reshape(-1).copy()
    if length is not None and len(result) != length:
        raise DataValidationError(f"Expected {length} values, received {len(result)}.")
    return result


class CurveState(StrEnum):
    NOT_FITTED = "Not fitted"
    READY = "Ready"
    RUNNING = "Running"
    FITTED = "Fitted"
    MODIFIED = "Modified/outdated"
    FAILED = "Failed"


@dataclass(slots=True)
class Mask:
    name: str
    excluded: np.ndarray
    ranges: list[tuple[float, float]] = field(default_factory=list)
    id: str = field(default_factory=lambda: _identifier("mask"))

    def __post_init__(self) -> None:
        self.excluded = np.asarray(self.excluded, dtype=bool).reshape(-1).copy()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "ranges": [list(item) for item in self.ranges]}


@dataclass(slots=True)
class Transformation:
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    operand: np.ndarray | None = field(default=None, repr=False)

    def apply(
        self, x: np.ndarray, y: np.ndarray, sigma_y: np.ndarray | None
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        x_new = x.copy()
        y_new = y.copy()
        sigma_new = None if sigma_y is None else sigma_y.copy()
        op = self.operation
        p = self.parameters

        if op == "y_add":
            y_new += float(p["value"])
        elif op == "y_subtract":
            y_new -= float(p["value"])
        elif op == "y_multiply":
            factor = float(p["value"])
            y_new *= factor
            if sigma_new is not None:
                sigma_new *= abs(factor)
        elif op == "y_divide":
            divisor = float(p["value"])
            if divisor == 0:
                raise DataValidationError("Cannot divide y by zero.")
            y_new /= divisor
            if sigma_new is not None:
                sigma_new /= abs(divisor)
        elif op == "x_add":
            x_new += float(p["value"])
        elif op == "x_multiply":
            x_new *= float(p["value"])
        elif op == "normalize_max":
            scale = np.nanmax(np.abs(y_new))
            if not np.isfinite(scale) or scale == 0:
                raise DataValidationError("Cannot normalise a curve with zero or invalid maximum.")
            y_new /= scale
            if sigma_new is not None:
                sigma_new /= scale
        elif op == "normalize_area":
            finite = np.isfinite(x_new) & np.isfinite(y_new)
            area = float(integrate.trapezoid(y_new[finite], x_new[finite]))
            if not np.isfinite(area) or area == 0:
                raise DataValidationError("Cannot normalise a curve with zero or invalid area.")
            y_new /= area
            if sigma_new is not None:
                sigma_new /= abs(area)
        elif op in {"curve_add", "curve_subtract", "curve_multiply", "curve_divide"}:
            if self.operand is None or len(self.operand) != len(y_new):
                raise DataValidationError(f"Transformation '{op}' is missing its aligned operand.")
            operand = self.operand
            if op == "curve_add":
                y_new += operand
            elif op == "curve_subtract":
                y_new -= operand
            elif op == "curve_multiply":
                y_new *= operand
                if sigma_new is not None:
                    sigma_new *= np.abs(operand)
            else:
                with np.errstate(divide="ignore", invalid="ignore"):
                    y_new /= operand
                    if sigma_new is not None:
                        sigma_new /= np.abs(operand)
        else:
            raise DataValidationError(f"Unknown transformation: {op}")
        return x_new, y_new, sigma_new

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "parameters": self.parameters,
            "description": self.description,
            "created_at": self.created_at,
            "has_operand": self.operand is not None,
        }


@dataclass(slots=True)
class Curve:
    name: str
    original_x: np.ndarray
    original_y: np.ndarray
    sigma_x: np.ndarray | None = None
    sigma_y: np.ndarray | None = None
    weights: np.ndarray | None = None
    weights_are_inverse_variance: bool = True
    x_label: str = "x"
    y_label: str = "y"
    x_unit: str = ""
    y_unit: str = ""
    source: str | None = None
    id: str = field(default_factory=lambda: _identifier("curve"))
    visible: bool = True
    colour: str = "#0072B2"
    state: CurveState = CurveState.NOT_FITTED
    transformations: list[Transformation] = field(default_factory=list)
    redo_transformations: list[Transformation] = field(default_factory=list)
    masks: dict[str, Mask] = field(default_factory=dict)
    active_mask: str = "Default"
    fit_ranges: list[tuple[float, float]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _x: np.ndarray = field(init=False, repr=False)
    _y: np.ndarray = field(init=False, repr=False)
    _sigma_y_current: np.ndarray | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.original_x = _array(self.original_x)  # type: ignore[assignment]
        self.original_y = _array(self.original_y, length=len(self.original_x))  # type: ignore[assignment]
        if len(self.original_x) < 2:
            raise DataValidationError("A curve requires at least two rows.")
        self.sigma_x = _array(self.sigma_x, length=len(self.original_x))
        self.sigma_y = _array(self.sigma_y, length=len(self.original_x))
        self.weights = _array(self.weights, length=len(self.original_x))
        self.original_x.setflags(write=False)
        self.original_y.setflags(write=False)
        if self.sigma_x is not None:
            self.sigma_x.setflags(write=False)
        if self.sigma_y is not None:
            self.sigma_y.setflags(write=False)
        if self.weights is not None:
            self.weights.setflags(write=False)
        if not self.masks:
            self.masks[self.active_mask] = Mask(self.active_mask, np.zeros(len(self), dtype=bool))
        for mask in self.masks.values():
            if len(mask.excluded) != len(self):
                raise DataValidationError(f"Mask '{mask.name}' length does not match curve '{self.name}'.")
        self._recompute()

    def __len__(self) -> int:
        return len(self.original_x)

    @property
    def x(self) -> np.ndarray:
        view = self._x.view()
        view.setflags(write=False)
        return view

    @property
    def y(self) -> np.ndarray:
        view = self._y.view()
        view.setflags(write=False)
        return view

    @property
    def current_sigma_y(self) -> np.ndarray | None:
        if self._sigma_y_current is None:
            return None
        view = self._sigma_y_current.view()
        view.setflags(write=False)
        return view

    @property
    def invalid(self) -> np.ndarray:
        invalid = ~np.isfinite(self._x) | ~np.isfinite(self._y)
        if self._sigma_y_current is not None:
            invalid |= ~np.isfinite(self._sigma_y_current) | (self._sigma_y_current <= 0)
        if self.weights is not None:
            invalid |= ~np.isfinite(self.weights) | (self.weights < 0)
        return invalid

    @property
    def effective_mask(self) -> np.ndarray:
        excluded = self.invalid.copy()
        for mask in self.masks.values():
            excluded |= mask.excluded
        if self.fit_ranges:
            in_range = np.zeros(len(self), dtype=bool)
            for lower, upper in self.fit_ranges:
                lo, hi = sorted((lower, upper))
                in_range |= (self._x >= lo) & (self._x <= hi)
            excluded |= ~in_range
        return excluded

    @property
    def content_hash(self) -> str:
        digest = hashlib.sha256()
        for array in (self._x, self._y, self.effective_mask):
            digest.update(np.ascontiguousarray(array).tobytes())
        return digest.hexdigest()

    def fit_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray]:
        keep = ~self.effective_mask
        if np.count_nonzero(keep) < 2:
            raise DataValidationError(f"Curve '{self.name}' has fewer than two usable points.")
        weight_scale: np.ndarray | None = None
        if self._sigma_y_current is not None:
            weight_scale = 1.0 / self._sigma_y_current[keep]
        elif self.weights is not None:
            values = self.weights[keep]
            weight_scale = np.sqrt(values) if self.weights_are_inverse_variance else values
        return self._x[keep], self._y[keep], weight_scale, np.flatnonzero(keep)

    def add_mask(self, name: str) -> Mask:
        name = name.strip()
        if not name:
            raise DataValidationError("Mask name cannot be empty.")
        if name in self.masks:
            raise DataValidationError(f"Mask '{name}' already exists on '{self.name}'.")
        mask = Mask(name, np.zeros(len(self), dtype=bool))
        self.masks[name] = mask
        self.active_mask = name
        self._mark_modified()
        return mask

    def mask_point(self, x_value: float, *, name: str | None = None) -> int:
        valid = np.isfinite(self._x)
        if not np.any(valid):
            raise DataValidationError(f"Curve '{self.name}' has no finite x value.")
        indices = np.flatnonzero(valid)
        index = int(indices[np.argmin(np.abs(self._x[valid] - x_value))])
        mask = self._mask(name)
        mask.excluded[index] = True
        mask.ranges.append((float(self._x[index]), float(self._x[index])))
        self._mark_modified()
        return index

    def mask_interval(self, lower: float, upper: float, *, name: str | None = None) -> int:
        lo, hi = sorted((float(lower), float(upper)))
        selected = np.isfinite(self._x) & (self._x >= lo) & (self._x <= hi)
        mask = self._mask(name)
        mask.excluded[selected] = True
        mask.ranges.append((lo, hi))
        self._mark_modified()
        return int(np.count_nonzero(selected))

    def unmask_interval(self, lower: float, upper: float, *, name: str | None = None) -> int:
        lo, hi = sorted((float(lower), float(upper)))
        selected = np.isfinite(self._x) & (self._x >= lo) & (self._x <= hi)
        mask = self._mask(name)
        changed = selected & mask.excluded
        mask.excluded[selected] = False
        mask.ranges = [item for item in mask.ranges if item[1] < lo or item[0] > hi]
        self._mark_modified()
        return int(np.count_nonzero(changed))

    def clear_mask(self, name: str | None = None) -> None:
        mask = self._mask(name)
        mask.excluded[:] = False
        mask.ranges.clear()
        self._mark_modified()

    def transfer_mask_from(
        self,
        source: Curve,
        *,
        tolerance: float,
        source_name: str | None = None,
        target_name: str | None = None,
    ) -> int:
        if tolerance < 0:
            raise DataValidationError("Mask-transfer tolerance cannot be negative.")
        source_mask = source._mask(source_name)
        source_x = source.x[source_mask.excluded]
        target = self._mask(target_name)
        applied = np.zeros(len(self), dtype=bool)
        if source_x.size:
            finite_target = np.isfinite(self._x)
            for value in source_x[np.isfinite(source_x)]:
                applied |= finite_target & (np.abs(self._x - value) <= tolerance)
        target.excluded |= applied
        for lo, hi in source_mask.ranges:
            target.ranges.append((lo - tolerance, hi + tolerance))
        self._mark_modified()
        return int(np.count_nonzero(applied))

    def apply_transformation(self, transformation: Transformation) -> None:
        self.transformations.append(transformation)
        self.redo_transformations.clear()
        self._recompute()
        self._mark_modified()

    def undo_transformation(self) -> bool:
        if not self.transformations:
            return False
        self.redo_transformations.append(self.transformations.pop())
        self._recompute()
        self._mark_modified()
        return True

    def redo_transformation(self) -> bool:
        if not self.redo_transformations:
            return False
        self.transformations.append(self.redo_transformations.pop())
        self._recompute()
        self._mark_modified()
        return True

    def restore_original(self) -> None:
        if self.transformations:
            self.redo_transformations.extend(reversed(self.transformations))
            self.transformations.clear()
            self._recompute()
            self._mark_modified()

    def _recompute(self) -> None:
        x = np.asarray(self.original_x).copy()
        y = np.asarray(self.original_y).copy()
        sigma = None if self.sigma_y is None else np.asarray(self.sigma_y).copy()
        for transformation in self.transformations:
            x, y, sigma = transformation.apply(x, y, sigma)
        self._x, self._y, self._sigma_y_current = x, y, sigma

    def _mask(self, name: str | None) -> Mask:
        key = name or self.active_mask
        if key not in self.masks:
            raise DataValidationError(f"Curve '{self.name}' has no mask named '{key}'.")
        return self.masks[key]

    def _mark_modified(self) -> None:
        if self.state == CurveState.FITTED:
            self.state = CurveState.MODIFIED

    def to_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
            "source": self.source,
            "visible": self.visible,
            "colour": self.colour,
            "state": self.state.value,
            "weights_are_inverse_variance": self.weights_are_inverse_variance,
            "active_mask": self.active_mask,
            "fit_ranges": [list(value) for value in self.fit_ranges],
            "metadata": self.metadata,
            "transformations": [value.to_dict() for value in self.transformations],
            "redo_transformations": [value.to_dict() for value in self.redo_transformations],
            "masks": [mask.to_dict() for mask in self.masks.values()],
        }


@dataclass(slots=True)
class Series:
    name: str
    curves: list[Curve] = field(default_factory=list)
    id: str = field(default_factory=lambda: _identifier("series"))
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, curve: Curve, index: int | None = None) -> None:
        if any(item.id == curve.id for item in self.curves):
            raise DataValidationError(f"Curve id '{curve.id}' is already in series '{self.name}'.")
        if index is None:
            self.curves.append(curve)
        else:
            self.curves.insert(index, curve)

    def remove(self, curve_id: str) -> Curve:
        for index, curve in enumerate(self.curves):
            if curve.id == curve_id:
                return self.curves.pop(index)
        raise KeyError(curve_id)

    def move(self, curve_id: str, index: int) -> None:
        curve = self.remove(curve_id)
        self.curves.insert(max(0, min(index, len(self.curves))), curve)


@dataclass(slots=True)
class Dataset:
    series: list[Series] = field(default_factory=list)

    @property
    def curves(self) -> list[Curve]:
        return [curve for group in self.series for curve in group.curves]

    def add_series(self, series: Series) -> None:
        if any(item.id == series.id for item in self.series):
            raise DataValidationError(f"Series id '{series.id}' already exists.")
        self.series.append(series)

    def curve(self, curve_id: str) -> Curve:
        for curve in self.curves:
            if curve.id == curve_id:
                return curve
        raise KeyError(curve_id)

    def series_for(self, curve_id: str) -> Series:
        for series in self.series:
            if any(curve.id == curve_id for curve in series.curves):
                return series
        raise KeyError(curve_id)

    def transfer_curve(self, curve_id: str, target_series_id: str, index: int | None = None) -> None:
        source = self.series_for(curve_id)
        target = next((item for item in self.series if item.id == target_series_id), None)
        if target is None:
            raise KeyError(target_series_id)
        curve = source.remove(curve_id)
        target.add(curve, index)

    def validate_unique_ids(self) -> None:
        ids = [series.id for series in self.series] + [curve.id for curve in self.curves]
        if len(ids) != len(set(ids)):
            raise DataValidationError("Dataset contains duplicate series or curve identifiers.")


def aligned_operand(
    target_x: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    *,
    method: str = "linear",
    extrapolate: bool = False,
) -> np.ndarray:
    """Interpolate source values onto target x without silent extrapolation."""

    finite = np.isfinite(source_x) & np.isfinite(source_y)
    sx, sy = source_x[finite], source_y[finite]
    if len(sx) < 2:
        raise DataValidationError("The operand curve has fewer than two finite points.")
    order = np.argsort(sx, kind="stable")
    sx, sy = sx[order], sy[order]
    unique, indices = np.unique(sx, return_index=True)
    sx, sy = unique, sy[indices]
    if method == "linear":
        left = sy[0] if extrapolate else np.nan
        right = sy[-1] if extrapolate else np.nan
        return np.interp(target_x, sx, sy, left=left, right=right)
    if method == "nearest":
        positions = np.searchsorted(sx, target_x, side="left")
        positions = np.clip(positions, 0, len(sx) - 1)
        previous = np.clip(positions - 1, 0, len(sx) - 1)
        choose_previous = np.abs(target_x - sx[previous]) <= np.abs(target_x - sx[positions])
        result = sy[np.where(choose_previous, previous, positions)].astype(float)
        if not extrapolate:
            result[(target_x < sx[0]) | (target_x > sx[-1])] = np.nan
        return result
    if method == "cubic":
        from scipy.interpolate import CubicSpline

        if len(sx) < 4:
            raise DataValidationError("Cubic interpolation requires at least four unique x values.")
        return CubicSpline(sx, sy, extrapolate=extrapolate)(target_x)
    raise DataValidationError(f"Unknown interpolation method: {method}")
