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

from curvemole.core.errors import DataValidationError
from curvemole.core.expressions import SafeExpression


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _array(values: Iterable[float] | np.ndarray | None, *, length: int | None = None) -> np.ndarray | None:
    if values is None:
        return None
    result = np.asarray(values, dtype=np.float64).reshape(-1).copy()
    if length is not None and len(result) != length:
        raise DataValidationError(f"Expected {length} values, received {len(result)}.")
    return result


class ImmutableColumns(dict):
    """Owned, read-only numeric table shared by curves; transformations replace columns."""

    def __init__(self, columns):
        def owned(value):
            array = np.asarray(value, dtype=np.float64).reshape(-1)
            owner = array
            while isinstance(owner.base, np.ndarray):
                owner = owner.base
            if isinstance(owner.base, bytes):
                return value if isinstance(value, np.ndarray) and value.ndim == 1 else array
            return np.frombuffer(array.tobytes(), dtype=np.float64)
        super().__init__((key, owned(value)) for key, value in columns.items())

    def __deepcopy__(self, memo):
        for value in self.values():
            memo[id(value)] = value
        return ImmutableColumns(self)


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


def _scale_interval(minus, plus, factor):
    magnitude = np.abs(factor)
    return (np.where(factor < 0, plus, minus) * magnitude,
            np.where(factor < 0, minus, plus) * magnitude)


def _normalization(x, y, operation):
    coefficients = np.zeros_like(y)
    if operation == "normalize_max":
        peak = int(np.nanargmax(np.abs(y))) if not np.all(np.isnan(y)) else 0
        scale = abs(y[peak])
        coefficients[peak] = np.sign(y[peak])
    else:
        finite = np.isfinite(x) & np.isfinite(y)
        steps = np.diff(x[finite]) / 2
        coefficients[finite] = np.r_[steps, 0.] + np.r_[0., steps] if np.any(finite) else []
        scale = float(np.dot(coefficients[finite], y[finite]))
    if not np.isfinite(scale) or scale == 0:
        raise DataValidationError("Cannot normalise a curve with a zero or invalid denominator.")
    return scale, coefficients


def _normalized_errors(minus, plus, normalized, scale, coefficients):
    # J = I / scale - outer(normalized, coefficients) / scale.
    # Sum the off-diagonal contribution without subtracting nearly equal variances.
    diagonal = (1 - normalized * coefficients) / scale
    own_minus, own_plus = _scale_interval(minus, plus, diagonal)
    low, high = _scale_interval(minus, plus, coefficients)
    low[coefficients == 0] = high[coefficients == 0] = 0.

    def other_norm(values):
        prefix = np.hypot.accumulate(np.r_[0., values])[:-1]
        suffix = np.hypot.accumulate(np.r_[0., values[::-1]])[:-1][::-1]
        return np.hypot(prefix, suffix)

    other_minus, other_plus = _scale_interval(other_norm(low), other_norm(high), -normalized / scale)
    return np.hypot(own_minus, other_minus), np.hypot(own_plus, other_plus)


@dataclass(slots=True)
class Transformation:
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    operand: np.ndarray | None = field(default=None, repr=False)
    operand_errors: np.ndarray | None = field(default=None, repr=False)

    def target_y_derivative(self):
        op = self.operation
        if op == "y_multiply":
            return float(self.parameters["value"])
        if op == "y_divide":
            divisor = float(self.parameters["value"])
            if divisor == 0:
                raise DataValidationError("Cannot divide y by zero.")
            return 1 / divisor
        if op == "curve_multiply":
            return self.operand
        if op == "curve_divide":
            with np.errstate(divide="ignore", invalid="ignore"):
                return 1 / self.operand
        return 1.

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
        elif op == "custom_formula":
            axis = str(p.get("axis", "")).lower()
            formula = str(p.get("formula", ""))
            if axis not in {"x", "y"}:
                raise DataValidationError("Custom formula target must be x or y.")
            values = SafeExpression.compile(formula).evaluate({axis: x_new if axis == "x" else y_new})
            result = np.asarray(values, dtype=np.float64)
            if result.ndim == 0:
                result = np.full(len(x_new), float(result), dtype=np.float64)
            if result.shape != x_new.shape:
                raise DataValidationError("Custom formula must return one value per data point.")
            if not np.all(np.isfinite(result)):
                raise DataValidationError("Custom formula returned non-finite values.")
            if axis == "x":
                x_new = result
            else:
                y_new = result
        elif op in {"normalize_max", "normalize_area"}:
            scale, coefficients = _normalization(x_new, y_new, op)
            y_new /= scale
            if sigma_new is not None:
                sigma_new, _ = _normalized_errors(sigma_new, sigma_new, y_new, scale, coefficients)
        elif op == "background_subtract":
            if self.operand is None or len(self.operand) != len(y_new):
                raise DataValidationError("Background subtraction is missing its background array.")
            y_new -= self.operand
        elif op == "replace_y":
            if self.operand is None or len(self.operand) != len(y_new):
                raise DataValidationError("Y replacement is missing its replacement array.")
            if not np.all(np.isfinite(self.operand)):
                raise DataValidationError("Y replacement contains non-finite values.")
            y_new = np.asarray(self.operand, dtype=np.float64).copy()
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
            "has_operand_errors": self.operand_errors is not None,
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
    original_columns: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    column_labels: dict[str, str] = field(default_factory=dict)
    column_axes: dict[str, str] = field(default_factory=dict)
    _columns: dict[str, np.ndarray] = field(init=False, repr=False)
    _x: np.ndarray = field(init=False, repr=False)
    _y: np.ndarray = field(init=False, repr=False)
    _sigma_y_current: np.ndarray | None = field(init=False, repr=False)
    # Half-widths of a central confidence interval, not standard deviations.
    error_y_minus: np.ndarray | None = None
    error_y_plus: np.ndarray | None = None
    error_confidence_level: float = 0.95
    _error_y_minus_current: np.ndarray | None = field(init=False, repr=False)
    _error_y_plus_current: np.ndarray | None = field(init=False, repr=False)
    _sigma_x_current: np.ndarray | None = field(init=False, repr=False)
    _correlated_y_errors: bool = field(init=False, repr=False)
    _weights_current: np.ndarray | None = field(init=False, repr=False)
    _row_indices: np.ndarray = field(init=False, repr=False)
    _mask_original_excluded: dict[str, np.ndarray] = field(init=False, default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.original_x = _array(self.original_x)  # type: ignore[assignment]
        self.original_y = _array(self.original_y, length=len(self.original_x))  # type: ignore[assignment]
        if len(self.original_x) < 2:
            raise DataValidationError("A curve requires at least two rows.")
        self.sigma_x = _array(self.sigma_x, length=len(self.original_x))
        self.sigma_y = _array(self.sigma_y, length=len(self.original_x))
        self.error_y_minus = _array(self.error_y_minus, length=len(self.original_x))
        self.error_y_plus = _array(self.error_y_plus, length=len(self.original_x))
        if (self.error_y_minus is None) != (self.error_y_plus is None):
            raise DataValidationError("Both lower and upper Y errors are required.")
        if self.error_y_minus is not None and self.sigma_y is not None:
            raise DataValidationError("Choose sigma_y or confidence-interval Y errors, not both.")
        if not np.isfinite(self.error_confidence_level) or not 0 < self.error_confidence_level < 1:
            raise DataValidationError("Data error confidence must be between zero and one.")
        self.weights = _array(self.weights, length=len(self.original_x))
        self.original_columns = ImmutableColumns(self.original_columns)
        if any(len(value) != len(self.original_x) for value in self.original_columns.values()):
            raise DataValidationError("Original column length does not match the curve.")
        for value in self.original_columns.values():
            value.setflags(write=False)
        if any(key not in self.original_columns for key in self.column_axes.values()):
            raise DataValidationError("Axis mapping refers to an unavailable column.")
        self.original_x.setflags(write=False)
        self.original_y.setflags(write=False)
        if self.sigma_x is not None:
            self.sigma_x.setflags(write=False)
        if self.sigma_y is not None:
            self.sigma_y.setflags(write=False)
        for error in (self.error_y_minus, self.error_y_plus):
            if error is not None:
                error.setflags(write=False)
        if self.weights is not None:
            self.weights.setflags(write=False)
        if hasattr(self, "_row_indices"):
            for mask in self.masks.values():
                if len(mask.excluded) != len(self.original_x) and len(mask.excluded) == len(self._row_indices):
                    expanded = self.original_mask(mask)
                    if len(expanded) == len(self.original_x):
                        mask.excluded = expanded
        self._row_indices = np.arange(len(self.original_x))
        self._mask_original_excluded = {}
        if not self.masks:
            self.masks[self.active_mask] = Mask(self.active_mask, np.zeros(len(self.original_x), dtype=bool))
        for mask in self.masks.values():
            if len(mask.excluded) != len(self.original_x):
                raise DataValidationError(f"Mask '{mask.name}' length does not match curve '{self.name}'.")
        self._recompute()

    def __len__(self) -> int:
        return len(getattr(self, "_x", self.original_x))

    @property
    def row_indices(self) -> np.ndarray:
        """Original row identities of the current points, including after deletions."""
        view = self._row_indices.view()
        view.setflags(write=False)
        return view

    @property
    def current_weights(self) -> np.ndarray | None:
        return self._readonly_error(self._weights_current)

    def original_mask(self, mask: Mask) -> np.ndarray:
        """Expand a current mask without losing flags on temporarily deleted rows."""
        full = self._mask_original_excluded.get(mask.id, np.zeros(len(self.original_x), dtype=bool)).copy()
        full[self._row_indices] = mask.excluded
        return full

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
    def columns(self) -> dict[str, np.ndarray]:
        result = {key: value.view() for key, value in self._columns.items()}
        for value in result.values():
            value.setflags(write=False)
        return result

    @property
    def current_sigma_y(self) -> np.ndarray | None:
        if self._sigma_y_current is None:
            return None
        view = self._sigma_y_current.view()
        view.setflags(write=False)
        return view

    @property
    def current_sigma_x(self) -> np.ndarray | None:
        return self._readonly_error(self._sigma_x_current)

    @property
    def invalid(self) -> np.ndarray:
        invalid = ~np.isfinite(self._x) | ~np.isfinite(self._y)
        for error in (self._sigma_y_current, self._error_y_minus_current, self._error_y_plus_current):
            if error is not None:
                invalid |= ~np.isfinite(error) | (error <= 0)
        if self._weights_current is not None:
            invalid |= ~np.isfinite(self._weights_current) | (self._weights_current < 0)
        return invalid

    @property
    def has_y_errors(self) -> bool:
        return self._sigma_y_current is not None or self._error_y_minus_current is not None

    @property
    def current_error_y_minus(self) -> np.ndarray | None:
        return self._readonly_error(self._error_y_minus_current)

    @property
    def current_error_y_plus(self) -> np.ndarray | None:
        return self._readonly_error(self._error_y_plus_current)

    @staticmethod
    def _readonly_error(array: np.ndarray | None) -> np.ndarray | None:
        if array is None:
            return None
        view = array.view()
        view.setflags(write=False)
        return view

    def y_error_scales(self, *, include_inverse_variance: bool = False) -> tuple[np.ndarray, np.ndarray] | None:
        """Gaussian tail scales; asymmetric intervals use their declared confidence."""
        if self._error_y_minus_current is not None:
            from scipy.special import ndtri
            z = ndtri((1 + self.error_confidence_level) / 2)
            return self._error_y_minus_current / z, self._error_y_plus_current / z
        if self._sigma_y_current is not None:
            return self._sigma_y_current, self._sigma_y_current
        if include_inverse_variance and self.weights_are_inverse_variance and self._weights_current is not None:
            weights = self._weights_current
            sigma = np.full_like(weights, np.nan)
            np.divide(1, np.sqrt(np.maximum(weights, 0)), out=sigma, where=weights > 0)
            return sigma, sigma
        return None

    @property
    def has_correlated_y_errors(self) -> bool:
        return self._correlated_y_errors

    def residual_scale(self, fitted: np.ndarray, indices: np.ndarray,
                       *, use_data_errors: bool = True) -> np.ndarray | None:
        """Weight predictions above/below each observation with its upper/lower error."""
        if not use_data_errors:
            return None
        scales = self.y_error_scales()
        if scales is not None:
            minus, plus = scales
            return 1 / np.where(fitted >= self._y[indices], plus[indices], minus[indices])
        if self._weights_current is not None:
            values = self._weights_current[indices]
            return np.sqrt(values) if self.weights_are_inverse_variance else values
        return None

    def _excluded_rows(self, *, use_data_errors: bool) -> np.ndarray:
        excluded = self.invalid if use_data_errors else ~np.isfinite(self._x) | ~np.isfinite(self._y)
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
    def effective_mask(self) -> np.ndarray:
        return self._excluded_rows(use_data_errors=True)

    @property
    def content_hash(self) -> str:
        return self.fit_input_hash()

    def fit_input_hash(self, schema_version: int = 2) -> str:
        """Retain the historical fingerprint for verifying archived records."""
        digest = hashlib.sha256()
        mask = self.effective_mask if schema_version == 1 else self._excluded_rows(use_data_errors=False)
        for array in (self._x, self._y, mask, self._sigma_y_current,
                      self._error_y_minus_current, self._error_y_plus_current, self._weights_current):
            if array is None:
                digest.update(b"none")
            else:
                if schema_version >= 2:
                    digest.update(repr((array.dtype.str, array.shape)).encode())
                digest.update(np.ascontiguousarray(array).tobytes())
        flags = (self.error_confidence_level, self.weights_are_inverse_variance)
        if schema_version >= 2:
            flags += (self.has_correlated_y_errors,)
        digest.update(repr(flags).encode())
        return digest.hexdigest()

    def fit_arrays(self, *, use_data_errors: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray]:
        keep = ~self._excluded_rows(use_data_errors=use_data_errors)
        if use_data_errors and not self.has_y_errors and self._weights_current is not None:
            # Zero-weight rows contribute no information, including to N and dof.
            keep &= self._weights_current > 0
        if np.count_nonzero(keep) < 2:
            raise DataValidationError(f"Curve '{self.name}' has fewer than two usable points.")
        weight_scale: np.ndarray | None = None
        if use_data_errors and self._sigma_y_current is not None:
            weight_scale = 1.0 / self._sigma_y_current[keep]
        elif use_data_errors and self._weights_current is not None:
            values = self._weights_current[keep]
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
            sorted_source = np.sort(source_x[np.isfinite(source_x)])
            if sorted_source.size:
                values = self._x[finite_target]
                positions = np.searchsorted(sorted_source, values)
                left = np.clip(positions - 1, 0, len(sorted_source) - 1)
                right = np.clip(positions, 0, len(sorted_source) - 1)
                distance = np.minimum(np.abs(values - sorted_source[left]),
                                      np.abs(values - sorted_source[right]))
                applied[finite_target] = distance <= tolerance
        target.excluded |= applied
        for lo, hi in source_mask.ranges:
            target.ranges.append((lo - tolerance, hi + tolerance))
        self._mark_modified()
        return int(np.count_nonzero(applied))

    def move_points(self, indices: Iterable[int], *, x: Iterable[float] | None = None,
                    y: Iterable[float] | None = None) -> None:
        """Move current points while recording stable original row identities."""
        rows = self._point_rows(indices)
        if x is None and y is None:
            raise DataValidationError("Choose X, Y or both to move data points.")
        parameters: dict[str, Any] = {"indices": self._row_indices[rows].tolist()}
        for axis, values in (("x", x), ("y", y)):
            if values is not None:
                array = _array(values, length=len(rows))
                if not np.all(np.isfinite(array)):
                    raise DataValidationError("Point coordinates must be finite.")
                parameters[axis] = array.tolist()
        self.apply_transformation(Transformation("move_points", parameters, "Move data points"))

    def delete_points(self, indices: Iterable[int]) -> None:
        rows = self._point_rows(indices)
        self.apply_transformation(Transformation(
            "delete_points", {"indices": self._row_indices[rows].tolist()}, "Delete data points"))

    def _point_rows(self, indices: Iterable[int]) -> np.ndarray:
        values = list(indices)
        if (not values or any(isinstance(row, (bool, np.bool_))
                              or not isinstance(row, (int, np.integer)) for row in values)):
            raise DataValidationError("Select data point row indices.")
        rows = np.asarray(values, dtype=int)
        if len(np.unique(rows)) != len(rows) or np.any(rows < 0) or np.any(rows >= len(self)):
            raise DataValidationError("Data point indices must be distinct and inside the dataset.")
        return rows

    def apply_transformation(self, transformation: Transformation) -> None:
        self.transformations.append(transformation)
        try:
            self._recompute()
        except Exception:
            self.transformations.pop()
            raise
        self.redo_transformations.clear()
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
        sigma_x = None if self.sigma_x is None else self.sigma_x.copy()
        minus = None if self.error_y_minus is None else self.error_y_minus.copy()
        plus = None if self.error_y_plus is None else self.error_y_plus.copy()
        weights = None if self.weights is None else self.weights.copy()
        weight_sigma = None
        if weights is not None and self.weights_are_inverse_variance:
            # Propagate a unit sigma factor, preserving original weights exactly
            # when no Y scaling occurs (no inverse/sqrt round-trip noise).
            weight_sigma = np.ones_like(weights)
        correlated = False
        rows = np.arange(len(x))
        original_masks = {mask.id: self.original_mask(mask) for mask in self.masks.values()}
        from curvemole.core.columns import calculator_column_axes, evaluate_columns

        columns = dict(self.original_columns)
        column_axes = calculator_column_axes(columns, self.column_axes)
        for axis, values in (("x", x), ("y", y)):
            if column_axes[axis] not in columns:
                columns[column_axes[axis]] = values
        for transformation in self.transformations:
            op, p = transformation.operation, transformation.parameters
            if op in {"move_points", "delete_points"}:
                requested = p.get("indices", [])
                if (not isinstance(requested, list) or not requested
                        or any(isinstance(row, bool) or not isinstance(row, int) for row in requested)):
                    raise DataValidationError("Point edits require original row indices.")
                positions = np.searchsorted(rows, requested)
                if (len(set(requested)) != len(requested) or np.any(positions >= len(rows))
                        or np.any(rows[positions] != requested)):
                    raise DataValidationError("Point edit refers to missing or duplicate rows.")
                if op == "move_points":
                    if not any(axis in p for axis in ("x", "y")):
                        raise DataValidationError("Point edits require new coordinates.")
                    for axis, values in (("x", x), ("y", y)):
                        if axis in p:
                            coordinates = _array(p[axis], length=len(positions))
                            if not np.all(np.isfinite(coordinates)):
                                raise DataValidationError("Point coordinates must be finite.")
                            values[positions] = coordinates
                else:
                    keep = np.ones(len(rows), dtype=bool)
                    keep[positions] = False
                    if np.count_nonzero(keep) < 2:
                        raise DataValidationError("Keep at least two data points in the dataset.")
                    rows, x, y = rows[keep], x[keep], y[keep]
                    sigma, sigma_x, minus, plus, weights = (
                        None if value is None else value[keep]
                        for value in (sigma, sigma_x, minus, plus, weights))
                    if weight_sigma is not None:
                        weight_sigma = weight_sigma[keep]
                    columns = {key: value[keep] for key, value in columns.items()}
                for axis, values in (("x", x), ("y", y)):
                    if axis in column_axes:
                        columns[column_axes[axis]] = values.copy()
                continue
            derivative = None
            target = p.get("axis") if op == "custom_formula" else p.get("target")
            if op in {"custom_formula", "column_formula"}:
                target = next((axis for axis in ("x", "y")
                               if target == axis or target == column_axes.get(axis)), target)
                errors = sigma_x if target == "x" else (sigma if sigma is not None else
                                                        minus if minus is not None else weight_sigma)
                if target in {"x", "y"} and errors is not None:
                    # Local propagation for arbitrary formulas; affine operations are exact.
                    values = x if target == "x" else y
                    from curvemole.core.numerics import local_derivative

                    def evaluate_shifted(shifted, x=x, y=y, target=target, op=op,
                                         columns=columns, p=p, transformation=transformation):
                        xx, yy = x.copy(), y.copy()
                        if target == "x":
                            xx = shifted
                        else:
                            yy = shifted
                        if op == "column_formula":
                            shifted_columns = {key: val.copy() for key, val in columns.items()}
                            if target in column_axes:
                                shifted_columns[column_axes[target]] = xx if target == "x" else yy
                            xx, yy = evaluate_columns(p["formula"], p["target"], xx, yy,
                                                      shifted_columns, self.column_labels, column_axes)
                        else:
                            xx, yy, _ = transformation.apply(xx, yy, None)
                        return xx if target == "x" else yy

                    derivative = local_derivative(evaluate_shifted, values, errors)
                    if target == "x":
                        sigma_x *= np.abs(derivative)
                    else:
                        if weight_sigma is not None:
                            weight_sigma *= np.abs(derivative)
                        if sigma is not None:
                            sigma *= np.abs(derivative)
                        if minus is not None:
                            minus, plus = (np.where(derivative < 0, plus, minus) * np.abs(derivative),
                                           np.where(derivative < 0, minus, plus) * np.abs(derivative))
            if op == "x_multiply" and sigma_x is not None:
                sigma_x *= abs(float(p["value"]))
            if transformation.operation == "column_formula":
                p = transformation.parameters
                x, y = evaluate_columns(p["formula"], p["target"], x, y, columns,
                                        self.column_labels, column_axes)
            elif op in {"normalize_max", "normalize_area"}:
                scale, coefficients = _normalization(x, y, op)
                y = y / scale
                correlated = True
                if minus is not None:
                    minus, plus = _normalized_errors(minus, plus, y, scale, coefficients)
                if sigma is not None:
                    sigma, _ = _normalized_errors(sigma, sigma, y, scale, coefficients)
                if weight_sigma is not None:
                    error = np.full_like(weights, np.nan)
                    np.divide(weight_sigma, np.sqrt(np.maximum(weights, 0)), out=error, where=weights > 0)
                    error, _ = _normalized_errors(error, error, y, scale, coefficients)
                    weight_sigma = error * np.sqrt(np.maximum(weights, 0))
            else:
                x, next_y, next_sigma = transformation.apply(x, y, sigma)
                if derivative is None:
                    factor = transformation.target_y_derivative()
                    if p.get("same_measurement"):
                        # Differentiate both appearances of the same Y value.
                        factor = 2 * y if op == "curve_multiply" else 2. if op == "curve_add" else 0.
                        if sigma is not None:
                            next_sigma = sigma * np.abs(factor)
                    if minus is not None:
                        minus, plus = _scale_interval(minus, plus, factor)
                    if weight_sigma is not None:
                        weight_sigma = weight_sigma * np.abs(factor)
                if transformation.operand_errors is not None:
                    if transformation.operand_errors.shape != (2, len(y)):
                        raise DataValidationError("Aligned operand uncertainties do not match the curve.")
                    if op == "curve_add":
                        operand_factor = 1.
                    elif op == "curve_subtract":
                        operand_factor = -1.
                    elif op == "curve_multiply":
                        operand_factor = y
                    else:
                        with np.errstate(divide="ignore", invalid="ignore"):
                            operand_factor = -next_y / transformation.operand
                    other_minus, other_plus = _scale_interval(*transformation.operand_errors, operand_factor)
                    correlated |= p.get("correlated_operand", False)
                    if minus is not None or p.get("asymmetric_operand", False):
                        from scipy.special import ndtri
                        z = ndtri((1 + self.error_confidence_level) / 2)
                        if minus is None:
                            if weight_sigma is not None:
                                next_sigma = np.full_like(weights, np.nan)
                                np.divide(weight_sigma, np.sqrt(np.maximum(weights, 0)), out=next_sigma, where=weights > 0)
                                weight_sigma = weights = None
                            minus = plus = 0. if next_sigma is None else z * next_sigma
                        minus = np.hypot(minus, z * other_minus)
                        plus = np.hypot(plus, z * other_plus)
                        next_sigma = None
                    elif weight_sigma is not None:
                        weight_sigma = np.hypot(weight_sigma, other_minus * np.sqrt(np.maximum(weights, 0)))
                    else:
                        next_sigma = np.hypot(0. if next_sigma is None else next_sigma, other_minus)
                y, sigma = next_y, next_sigma
            for axis, values in (("x", x), ("y", y)):
                if axis in column_axes:
                    columns[column_axes[axis]] = values.copy()
        self._columns = columns
        self._correlated_y_errors = correlated
        self._x, self._y, self._sigma_y_current = x, y, sigma
        self._error_y_minus_current, self._error_y_plus_current = minus, plus
        self._sigma_x_current = sigma_x
        if weight_sigma is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                weights = weights / weight_sigma**2
            # A zero derivative supplies no usable variance information.
            weights[weight_sigma == 0] = np.nan
        self._weights_current = weights
        self._row_indices = rows
        self._mask_original_excluded = original_masks
        for mask in self.masks.values():
            mask.excluded = original_masks[mask.id][rows].copy()

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
            "error_confidence_level": self.error_confidence_level,
            "column_keys": list(self.original_columns),
            "column_labels": self.column_labels,
            "column_axes": self.column_axes,
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
        Dataset([*self.series, series]).validate_unique_ids()
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
    return align_operand_with_errors(target_x, source_x, source_y, method=method,
                                     extrapolate=extrapolate)[0]


def align_operand_with_errors(
    target_x: np.ndarray, source_x: np.ndarray, source_y: np.ndarray, *,
    method: str, extrapolate: bool, errors: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Apply interpolation and propagate independent source errors by its weights."""
    indices = np.flatnonzero(np.isfinite(source_x) & np.isfinite(source_y))
    indices = indices[np.argsort(source_x[indices], kind="stable")]
    sx, positions = np.unique(source_x[indices], return_index=True)
    indices = indices[positions]
    sy = source_y[indices]
    if len(sx) < 2:
        raise DataValidationError("The operand curve has fewer than two distinct usable X points.")
    if errors is not None:
        errors = errors[:, indices]
    outside = ~np.isfinite(target_x)
    if not extrapolate:
        outside |= (target_x < sx[0]) | (target_x > sx[-1])
    interpolated_errors = None
    if method == "linear":
        right = np.clip(np.searchsorted(sx, target_x), 1, len(sx) - 1)
        left = right - 1
        fraction = (target_x - sx[left]) / (sx[right] - sx[left])
        values = (1 - fraction) * sy[left] + fraction * sy[right]
        if errors is not None:
            left_errors = _scale_interval(*errors[:, left], 1 - fraction)
            right_errors = _scale_interval(*errors[:, right], fraction)
            interpolated_errors = np.hypot(left_errors, right_errors)
    elif method == "nearest":
        right = np.clip(np.searchsorted(sx, target_x), 1, len(sx) - 1)
        left = right - 1
        nearest = np.where(np.abs(target_x - sx[left]) <= np.abs(target_x - sx[right]), left, right)
        values = sy[nearest]
        if errors is not None:
            interpolated_errors = errors[:, nearest]
    elif method == "cubic":
        from scipy.interpolate import CubicSpline

        if len(sx) < 4:
            raise DataValidationError("Cubic interpolation requires at least four unique x values.")
        values = CubicSpline(sx, sy, extrapolate=extrapolate)(target_x)
        if errors is not None:
            # Cubic splines are linear in the ordinates. Evaluate the response
            # to unit basis vectors in batches to bound peak memory.
            interpolated_errors = np.zeros((2, len(target_x)))
            for start in range(0, len(sx), 32):
                indices = np.arange(start, min(start + 32, len(sx)))
                basis = np.zeros((len(sx), len(indices)))
                basis[indices, np.arange(len(indices))] = 1
                weights = CubicSpline(sx, basis, extrapolate=extrapolate)(target_x)
                contributions = _scale_interval(*errors[:, None, indices], weights)
                interpolated_errors = np.hypot(
                    interpolated_errors, np.hypot.reduce(contributions, axis=-1))
    else:
        raise DataValidationError(f"Unknown interpolation method: {method}")
    values[outside] = np.nan
    if interpolated_errors is not None:
        interpolated_errors[:, outside] = np.nan
    return values, interpolated_errors
