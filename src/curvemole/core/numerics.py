"""Scale-aware numerical operations shared by fitting and error propagation."""
from __future__ import annotations

import numpy as np


def characteristic_scale(values):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return 1.0
    span = float(np.ptp(finite))
    return span if span > 0 else float(np.max(np.abs(finite))) or 1.0


def parameter_scales(parameters, free_paths, curves, coordinates=None):
    data = {curve.id: (characteristic_scale(curve.x), characteristic_scale(curve.y))
            for curve in curves}
    result = []
    for path in free_paths:
        parameter = parameters[path]
        xs, ys = data[path.split('.', 1)[0]]
        name = parameter.name.casefold()
        if coordinates is not None and coordinates.coordinate_kinds[path] == 'fraction':
            scale = 1.0
        elif name in {'center', 'centre', 'position', 'x0', 'mu'}:
            scale = xs
        elif parameter.value:
            scale = abs(parameter.value)
        elif name in {'sigma', 'gamma', 'fwhm', 'width'}:
            scale = xs
        elif name == 'area':
            scale = xs * ys
        elif name == 'slope':
            scale = ys / xs
        elif np.isfinite(parameter.minimum) and np.isfinite(parameter.maximum):
            scale = parameter.maximum - parameter.minimum
        else:
            scale = ys
        result.append(max(float(scale), np.finfo(float).tiny))
    return np.asarray(result)


def derivative_steps(vector, scales):
    vector = np.asarray(vector, dtype=float)
    # Respect both the physical scale and representability at a large origin.
    return np.maximum(np.cbrt(np.finfo(float).eps) * np.asarray(scales),
                      4 * np.abs(np.spacing(vector)))


def local_derivative(evaluate, values, errors=None):
    """Elementwise first derivative, with Richardson cancellation of O(h**2)."""
    values = np.asarray(values, dtype=float)
    nonzero = np.abs(values[np.isfinite(values) & (values != 0)])
    fallback = float(np.median(nonzero)) if nonzero.size else 1.0
    zero_scale = fallback if errors is None else np.where(
        np.isfinite(errors) & (np.asarray(errors) > 0), np.asarray(errors), fallback)
    scales = np.where(values != 0, np.abs(values), zero_scale)
    h = derivative_steps(values, scales)
    coarse = (evaluate(values + h) - evaluate(values - h)) / (2 * h)
    half = h / 2
    fine = (evaluate(values + half) - evaluate(values - half)) / (2 * half)
    result = (4 * fine - coarse) / 3
    if not np.all(np.isfinite(result)):
        from curvemole.core.errors import DataValidationError
        raise DataValidationError('The formula uncertainty derivative is not finite.')
    return result


def scale_jacobian(jacobian, scales):
    return jacobian.multiply(scales).tocsr() if hasattr(jacobian, 'multiply') else jacobian * scales


def compensated_sum(arrays, template):
    total = np.zeros_like(template, dtype=float)
    correction = np.zeros_like(total)
    for value in arrays:
        updated = total + value
        correction += np.where(np.abs(total) >= np.abs(value),
                               (total - updated) + value, (value - updated) + total)
        total = updated
    return total + correction
