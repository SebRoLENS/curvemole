"""Focused dialogs used by the single-window CurveMole interface.

One module per dialog; every name stays importable from ``curvemole.gui.dialogs``.
"""

# Names historically importable from this module.
from curvemole.core.data import Curve  # noqa: F401
from curvemole.core.export import BundleExportSelection  # noqa: F401
from curvemole.core.expressions import SafeExpression  # noqa: F401
from curvemole.core.fitting import (
    FitMode,  # noqa: F401
    FitPlan,  # noqa: F401
    FitSettings,  # noqa: F401
)
from curvemole.core.importers import (
    ColumnMapping,  # noqa: F401
    ImportConfig,  # noqa: F401
    inspect_file,  # noqa: F401
)
from curvemole.core.models import Component  # noqa: F401
from curvemole.core.plugin_identity import (
    contribution_tooltip,  # noqa: F401
    function_tooltip,  # noqa: F401
    provenance,  # noqa: F401
)
from curvemole.core.plugins import (
    PluginCandidate,  # noqa: F401
    PluginManager,  # noqa: F401
)
from curvemole.core.project import Project  # noqa: F401
from curvemole.core.registry import FunctionRegistry  # noqa: F401
from curvemole.gui.dialogs._shared import (  # noqa: F401
    _name_accept,
    _set_list_checked,
    _set_table_checked,
    np_median,
)
from curvemole.gui.dialogs.about_dialog import AboutDialog  # noqa: F401
from curvemole.gui.dialogs.add_component_dialog import AddComponentDialog  # noqa: F401
from curvemole.gui.dialogs.background_components_dialog import (
    BackgroundComponentsDialog,  # noqa: F401
)
from curvemole.gui.dialogs.copy_fit_dialog import CopyFitDialog  # noqa: F401
from curvemole.gui.dialogs.export_bundle_dialog import ExportBundleDialog  # noqa: F401
from curvemole.gui.dialogs.fit_plan_dialog import FitPlanDialog  # noqa: F401
from curvemole.gui.dialogs.import_mapping_dialog import ImportMappingDialog  # noqa: F401
from curvemole.gui.dialogs.plugin_manager_dialog import PluginManagerDialog  # noqa: F401
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: F401
from curvemole.identifiers import (
    CONCEPT_DOI,  # noqa: F401
    CONCEPT_DOI_URL,  # noqa: F401
    RRID,  # noqa: F401
    RRID_URL,  # noqa: F401
)
from curvemole.version import __version__  # noqa: F401
