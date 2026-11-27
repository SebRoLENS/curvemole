"""HTML and PDF analysis reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from curvemole.core.fitting import FitResult
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry
from curvemole.identifiers import CONCEPT_DOI, CONCEPT_DOI_URL, RRID, RRID_URL
from curvemole.version import __version__

if TYPE_CHECKING:
    pass
from curvemole.core.export.common import _escape
from curvemole.core.export.tables import fit_settings_dataframe, parameter_dataframe


def generate_html_report(
    project: Project,
    path: str | Path,
    *,
    result: FitResult | None = None,
    title: str | None = None,
    notes: str = "",
    full: bool = False,
    registry: FunctionRegistry | None = None,
) -> Path:
    import pandas as pd

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parameters = parameter_dataframe(project, result, registry=registry)
    statistics = result.statistics if result else {}
    warnings = result.warnings if result else []
    fitted_ids = list(result.curve_outputs) if result else []
    curve_names = {curve.id: curve.name for curve in project.curves}
    fit_scope = "; ".join(f"{curve_names.get(identity, 'Removed spectrum')} ({identity})" for identity in fitted_ids)
    sections = [
        f"<h1>{_escape(title or project.name)}</h1>",
        f'<p><strong>CurveMole {__version__}</strong> (<a href="{RRID_URL}">RRID:{RRID}</a>; <a href="{CONCEPT_DOI_URL}">Concept DOI: {CONCEPT_DOI}</a>) — generated {_escape(datetime.now(UTC).isoformat())}</p>',
        '<p><strong>Software citation:</strong> cite the Zenodo DOI of the exact CurveMole version used in your bibliography. '
        f'Methods: CurveMole {__version__} (RRID:{RRID}). '
        'The Concept DOI is a general project reference and may resolve to a beta. '
        '<a href="https://github.com/SebRoLENS/curvemole/blob/main/docs/citing.md">Citation guide and BibTeX</a>.</p>',
        f"<p>{_escape(notes)}</p>" if notes else "",
        "<h2>Data and models</h2>",
        f"<p>{len(project.curves)} curve(s), {sum(len(model.components) for model in project.models.values())} component(s).</p>",
        "<h2>Recorded last-fit statistics</h2>",
        (f"<p>Timestamp: {_escape(result.timestamp)}. Scope: {_escape(fit_scope)}. "
         "These statistics cover only this recorded fit, which may contain a subset of the project spectra.</p>") if result else "",
        pd.DataFrame([statistics]).to_html(index=False, border=0) if statistics else "<p>No fit result.</p>",
        "<h2>Parameters</h2>",
        "<p>Current resolved model values. Recorded errors can be stale for modified or unfitted models; check curve_state.</p>",
        parameters.to_html(index=False, border=0, float_format=lambda value: f"{value:.12g}"),
        "<h2>Warnings</h2>",
        "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in warnings) + "</ul>" if warnings else "<p>None.</p>",
    ]
    if full:
        sections.extend(
            [
                "<h2>Recorded solver and loss settings</h2>",
                fit_settings_dataframe(result).to_html(index=False, border=0),
                "<h2>Reproducibility</h2>",
                f"<pre>{_escape(json.dumps(project.to_metadata(), indent=2, default=str))}</pre>",
            ]
        )
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>body{font-family:Arial,sans-serif;max-width:1100px;margin:2rem auto;color:#17212b}
table{border-collapse:collapse;width:100%;font-size:.86rem}th,td{border:1px solid #ccd6df;padding:.35rem;text-align:left}
th{background:#e9f4f2}h1,h2{color:#185c5a}pre{white-space:pre-wrap;font-size:.75rem}</style>
</head><body>""" + "\n".join(sections) + "</body></html>\n"
    destination.write_text(html, encoding="utf-8")
    return destination


def generate_pdf_report(
    project: Project, path: str | Path, *, result: FitResult | None = None,
    title: str | None = None, registry: FunctionRegistry | None = None, **kwargs,
) -> Path:
    """Write vector PDF pages for individual curves with their own fit scope."""
    from curvemole.core.figure_export import generate_pdf_report as render
    return render(project, path, result=result, title=title, registry=registry, **kwargs)

