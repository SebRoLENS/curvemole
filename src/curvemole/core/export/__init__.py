"""Human-friendly and automation-friendly exports and analysis bundles.

The implementation is split by responsibility (common, tables, figures,
reports, bundle); every name stays importable from ``curvemole.core.export``.
"""

from curvemole.core.data import (
    Curve,  # noqa: F401
    CurveState,  # noqa: F401
)
from curvemole.core.diagnostics import residual_diagnostics  # noqa: F401
from curvemole.core.errors import CurveMoleError  # noqa: F401
from curvemole.core.export.bundle import (
    _bundle_curve_index,  # noqa: F401
    _bundle_file_description,  # noqa: F401
    _bundle_paths,  # noqa: F401
    _bundle_readme,  # noqa: F401
    _bundle_readme_inventory,  # noqa: F401
    _bundle_readme_table,  # noqa: F401
    _bundle_readme_text,  # noqa: F401
    _curve_export_stems,  # noqa: F401
    _publish_bundle,  # noqa: F401
    _replot_script,  # noqa: F401
    _spectrum_export_names,  # noqa: F401
    _write_bundle_files,  # noqa: F401
    export_bundle,  # noqa: F401
)
from curvemole.core.export.common import (
    BundleExportSelection,  # noqa: F401
    ExportSelection,  # noqa: F401
    ExportSummary,  # noqa: F401
    _BundleRollbackError,  # noqa: F401
    _escape,  # noqa: F401
    _json_default,  # noqa: F401
    _label,  # noqa: F401
    _normalise_owned_path,  # noqa: F401
    _registry_for_project,  # noqa: F401
    _resolved_values,  # noqa: F401
    _safe_name,  # noqa: F401
    _sha256,  # noqa: F401
    _tidy_column,  # noqa: F401
)
from curvemole.core.export.figures import (
    _export_figure,  # noqa: F401
    _release_export_figure,  # noqa: F401
    export_figure,  # noqa: F401
)
from curvemole.core.export.reports import (
    generate_html_report,  # noqa: F401
    generate_pdf_report,  # noqa: F401
)
from curvemole.core.export.tables import (
    _write_labeled_matrix,  # noqa: F401
    analysis_dataframes,  # noqa: F401
    export_dataframe,  # noqa: F401
    export_function_parameters,  # noqa: F401
    export_parameter_covariances,  # noqa: F401
    fit_settings_dataframe,  # noqa: F401
    parameter_dataframe,  # noqa: F401
    tidy_dataframe,  # noqa: F401
    uncertainty_dataframe,  # noqa: F401
    value_with_error,  # noqa: F401
    wide_dataframe,  # noqa: F401
)
from curvemole.core.export_columns import ExportColumns  # noqa: F401
from curvemole.core.fitting import (
    FitMode,  # noqa: F401
    FitResult,  # noqa: F401
)
from curvemole.core.matrices import (
    BlockDiagonalMatrix,  # noqa: F401
    matrix_from_value,  # noqa: F401
)
from curvemole.core.models import Model  # noqa: F401
from curvemole.core.notebook import export_notebook  # noqa: F401
from curvemole.core.project import Project  # noqa: F401
from curvemole.core.registry import (
    FunctionRegistry,  # noqa: F401
    default_registry,  # noqa: F401
)

# Names historically importable from this module.
from curvemole.core.results_store import ResultKey  # noqa: F401
from curvemole.core.serialization import (
    save_fitmodel,  # noqa: F401
    save_project,  # noqa: F401
)
from curvemole.identifiers import (
    CONCEPT_DOI,  # noqa: F401
    CONCEPT_DOI_URL,  # noqa: F401
    RRID,  # noqa: F401
    RRID_URL,  # noqa: F401
)
from curvemole.version import __version__  # noqa: F401
