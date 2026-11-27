"""Dockable model, calculator, formula, worksheet, diagnostics, and uncertainty panels.

One module per panel; every name stays importable from ``curvemole.gui.panels``.
"""

# Names historically importable from this module.
from curvemole.core.background_status import background_component_status  # noqa: F401
from curvemole.core.calculator_equations import normalize_equation  # noqa: F401
from curvemole.core.columns import calculator_column_axes  # noqa: F401
from curvemole.core.data import CurveState  # noqa: F401
from curvemole.core.diagnostics import residual_diagnostics  # noqa: F401
from curvemole.core.expressions import (
    SafeExpression,  # noqa: F401
    expression_parameters,  # noqa: F401
)
from curvemole.core.functions import formula_definition  # noqa: F401
from curvemole.core.plugin_identity import function_tooltip  # noqa: F401
from curvemole.core.project import Project  # noqa: F401
from curvemole.core.registry import FunctionRegistry  # noqa: F401
from curvemole.core.results_store import ResultKey  # noqa: F401
from curvemole.core.uncertainty import (
    DEFAULT_BLOCK_BOOTSTRAP_REPLICATES,  # noqa: F401
    AdaptiveReplicateSettings,  # noqa: F401
)
from curvemole.gui.background_role import BackgroundSwitch  # noqa: F401
from curvemole.gui.calculator_columns import (
    ColumnSelector,  # noqa: F401
    choose_column,  # noqa: F401
)
from curvemole.gui.model_selection import COMPONENT_CURVE_ROLE  # noqa: F401
from curvemole.gui.panels.calculator_panel import (
    CalculatorPanel,  # noqa: F401
    _CalculatorValue,  # noqa: F401
)
from curvemole.gui.panels.diagnostics_panel import DiagnosticsPanel  # noqa: F401
from curvemole.gui.panels.function_builder_panel import FunctionBuilderPanel  # noqa: F401
from curvemole.gui.panels.model_panel import (
    FunctionList,  # noqa: F401
    ModelPanel,  # noqa: F401
)
from curvemole.gui.panels.uncertainty_panel import UncertaintyPanel  # noqa: F401
from curvemole.gui.panels.worksheet_panel import WorksheetPanel  # noqa: F401
from curvemole.gui.parameter_limits import (
    POSITIVE_BOUND_ROLE,  # noqa: F401
    positive_width_bound,  # noqa: F401
)
from curvemole.gui.row_drag import (
    RowDragMixin,  # noqa: F401
    RowDrop,  # noqa: F401
)
from curvemole.gui.worksheet import WorksheetModel  # noqa: F401
