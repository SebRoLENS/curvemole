"""Figure rendering for exports (matplotlib, loaded on demand)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from curvemole.core.data import Curve
from curvemole.core.models import Model

if TYPE_CHECKING:
    pass


# The renderer owns figure creation; these names remain importable here.
from curvemole.core.figure_export import _export_figure, _release_export_figure  # noqa: E402,F401


def export_figure(
    curves: Iterable[Curve], models: Mapping[str, Model], path: str | Path, **kwargs,
) -> Path:
    """Render a standalone scientific figure without loading pyplot."""
    from curvemole.core.figure_export import export_figure as render

    return render(curves, models, path, **kwargs)

