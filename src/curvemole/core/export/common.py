"""Selections, summaries and small helpers shared by the exporters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from curvemole.core.errors import CurveMoleError
from curvemole.core.models import Model
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry, default_registry

if TYPE_CHECKING:
    pass


@dataclass(slots=True)
class ExportSelection:
    original_x: bool = False
    x: bool = True
    y: bool = True
    total_fit: bool = True
    residual: bool = True
    background: bool = True
    components: bool = True
    sigma_y: bool = True
    weights: bool = True
    mask_flag: bool = True


@dataclass(slots=True)
class BundleExportSelection:
    """Contents of a complete analysis export; use ``none`` for a subset."""

    fit_results: bool = True
    fit_settings: bool = True
    wide_tables: bool = True
    tidy_table: bool = True
    results_json: bool = True
    fitmodel: bool = True
    project_copy: bool = True
    main_plot_png: bool = True
    main_plot_svg: bool = True
    html_summary: bool = True
    html_reproducibility: bool = True
    pdf_summary: bool = True
    uncertainty: bool = True
    diagnostics: bool = True
    readme: bool = True
    laboratory_notebook: bool = True
    spectra: bool = True
    function_parameters: bool = True
    parameter_covariances: bool = True
    current_view: bool = True

    @classmethod
    def none(cls, **enabled: bool) -> BundleExportSelection:
        """Create an explicit subset, independent of complete-bundle defaults."""
        return cls(**(dict.fromkeys(cls.__dataclass_fields__, False) | enabled))

    def any_selected(self) -> bool:
        return any(self.to_dict().values())

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(slots=True)
class ExportSummary:
    directory: Path
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    preserved_external: list[Path] = field(default_factory=list)


class _BundleRollbackError(CurveMoleError):
    """Keep staged backups available if a filesystem refuses rollback."""


def _registry_for_project(project: Project) -> FunctionRegistry:
    registry = default_registry().copy()
    registry.set_project_functions([v for v in project.custom_functions if v.get("formula")])
    return registry


def _resolved_values(models: Mapping[str, Model]) -> dict[str, float]:
    from curvemole.core.parameters import resolve_parameter_values

    parameters = {
        path: parameter
        for curve_id, model in models.items()
        for path, parameter in model.parameter_map(curve_id).items()
    }
    return resolve_parameter_values(parameters)


def _tidy_column(column: str) -> tuple[str, str]:
    if column.startswith("Component | "):
        parts = column.split(" | ")
        return parts[1], "component"
    return "", column


def _label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")


def _normalise_owned_path(value: object) -> str:
    """Return a platform-independent key for an export-manifest path."""
    return str(value).replace("\\", "/")


def _escape(value: str) -> str:
    import html

    return html.escape(value)


def _sha256(path: Path) -> str:
    import hashlib

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(type(value).__name__)


def _curve_export_stems(project: Project) -> dict[str, str]:
    import hashlib

    return {
        curve.id: f"{(_safe_name(curve.name) or 'spectrum')[:64]}__{hashlib.sha256(curve.id.encode()).hexdigest()[:12]}"
        for curve in project.curves
    }


def _spectrum_export_names(project: Project) -> dict[str, str]:
    from curvemole.core.spectrum_export import _deduplicate_filename, spectrum_export_filename

    names: dict[str, str] = {}
    used: set[str] = set()
    for curve in project.curves:
        filename = _deduplicate_filename(spectrum_export_filename(curve), used)
        names[curve.id] = filename
        used.add(filename.casefold())
    return names
