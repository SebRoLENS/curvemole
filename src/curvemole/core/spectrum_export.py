"""Per-spectrum numeric exports for data, fitted components, totals, and residuals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from curvemole.core.data import Curve
from curvemole.core.errors import CurveMoleError
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry


@dataclass(slots=True)
class SpectrumExportOptions:
    """Select the numeric traces written for each exported spectrum."""

    subtract_background: bool = False
    unmasked_only: bool = False
    include_background: bool = True
    include_components: bool = True
    include_total_fit: bool = True
    include_residual: bool = True


def spectrum_export_dataframe(
    project: Project,
    curve_id: str,
    *,
    options: SpectrumExportOptions | None = None,
    registry: FunctionRegistry | None = None,
) -> pd.DataFrame:
    """Build a wide x/y table that can be replotted directly."""
    options = options or SpectrumExportOptions()
    registry = registry or default_registry()
    curve = project.dataset.curve(curve_id)
    model = project.models.get(curve.id)
    values = project.resolved_parameter_values()

    x = np.asarray(curve.x, dtype=float)
    data = np.asarray(curve.y, dtype=float)
    background = np.zeros_like(data)
    total: np.ndarray | None = None
    components: dict[str, np.ndarray] = {}

    if model is not None and model.components:
        evaluated_total, evaluated_components = model.evaluate(
            x,
            curve_id=curve.id,
            values=values,
            registry=registry,
            components=True,
        )
        total = np.asarray(evaluated_total, dtype=float)
        components = {
            component_id: np.asarray(component_y, dtype=float)
            for component_id, component_y in evaluated_components.items()
        }
        background = np.asarray(
            model.background(
                x,
                curve_id=curve.id,
                values=values,
                registry=registry,
            ),
            dtype=float,
        )

    exported_data = data - background if options.subtract_background else data
    columns: dict[str, np.ndarray] = {
        _axis_label(curve.x_label, curve.x_unit): x,
        _data_label(curve, options.subtract_background): exported_data,
    }

    if options.include_background and model is not None and model.components:
        columns["Background"] = background

    if options.include_components and model is not None:
        for component in model.components:
            if not component.enabled or component.id not in components:
                continue
            suffix = " | background" if component.is_background else ""
            columns[
                f"Component | {component.name} | {component.function_id}{suffix}"
            ] = components[component.id]

    if total is not None and options.include_total_fit:
        displayed_total = total - background if options.subtract_background else total
        label = "Total fit - background" if options.subtract_background else "Total fit"
        columns[label] = displayed_total

    if total is not None and options.include_residual:
        columns["Residual (data - fit)"] = data - total

    frame = pd.DataFrame(columns)
    if options.unmasked_only:
        frame = frame.loc[~curve.effective_mask].reset_index(drop=True)
    return frame


def export_spectra(
    project: Project,
    directory: str | Path,
    curve_ids: list[str],
    *,
    options: SpectrumExportOptions | None = None,
    registry: FunctionRegistry | None = None,
) -> list[Path]:
    """Write one wide numeric file per selected spectrum."""
    if not curve_ids:
        raise CurveMoleError("Select at least one spectrum to export.")
    root = Path(directory).expanduser()
    if not str(root):
        raise CurveMoleError("Choose an export folder.")
    root.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    used_names: set[str] = set()
    for curve_id in curve_ids:
        curve = project.dataset.curve(curve_id)
        frame = spectrum_export_dataframe(
            project,
            curve_id,
            options=options,
            registry=registry,
        )
        filename = spectrum_export_filename(curve)
        filename = _deduplicate_filename(filename, used_names)
        used_names.add(filename.casefold())
        destination = root / filename
        frame.to_csv(
            destination,
            sep=_source_delimiter(curve),
            index=False,
            encoding="utf-8",
            lineterminator="\n",
            float_format="%.12g",
        )
        created.append(destination)
    return created


def spectrum_export_filename(curve: Curve) -> str:
    """Return '<spectrum>_curvemole.<original extension>'."""
    suffix = _source_suffix(curve) or ".txt"
    safe_name = re.sub(r"[\\/:*?\"<>|]+", "_", curve.name).strip().rstrip(".")
    safe_name = safe_name or "spectrum"
    return f"{safe_name}_curvemole{suffix}"


def _source_suffix(curve: Curve) -> str:
    if curve.source:
        suffix = Path(curve.source).suffix
        if suffix:
            return suffix
    imported = curve.metadata.get("import", {}) if isinstance(curve.metadata, dict) else {}
    filename = imported.get("file_name") if isinstance(imported, dict) else None
    return Path(str(filename)).suffix if filename else ""


def _source_delimiter(curve: Curve) -> str:
    imported = curve.metadata.get("import", {}) if isinstance(curve.metadata, dict) else {}
    delimiter = imported.get("delimiter") if isinstance(imported, dict) else None
    if delimiter in {",", ";", "\t", "|"}:
        return str(delimiter)
    suffix = _source_suffix(curve).lower()
    if suffix == ".csv":
        return ","
    return "\t"


def _axis_label(label: str, unit: str) -> str:
    return f"{label} [{unit}]" if unit else label


def _data_label(curve: Curve, background_subtracted: bool) -> str:
    base = f"Spectrum | {_axis_label(curve.y_label, curve.y_unit)}"
    return f"{base} - background" if background_subtracted else base


def _deduplicate_filename(filename: str, used_names: set[str]) -> str:
    if filename.casefold() not in used_names:
        return filename
    path = Path(filename)
    for number in range(2, 10000):
        candidate = f"{path.stem}-{number}{path.suffix}"
        if candidate.casefold() not in used_names:
            return candidate
    raise CurveMoleError(f"Too many duplicate spectrum names for '{filename}'.")
