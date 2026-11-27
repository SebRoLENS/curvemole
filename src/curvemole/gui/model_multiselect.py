"""Function multi-selection and cross-spectrum model editing (historical module).

Multi-selection is native to ``ModelPanel`` and the model-editing commands live
in ``ModelEditController`` (``window.model_edit``). This module only keeps the
names other code historically imported from here.
"""

from __future__ import annotations

from curvemole.gui.model_edit_controller import (  # noqa: F401 - compatibility re-exports
    ModelEditController,
    _push_multi_model_change,
    _refs_for_request,
    _restore_models,
)
from curvemole.gui.model_selection import (  # noqa: F401 - compatibility re-exports
    _BATCH,
    _current_ref,
    _find_component_curve,
    _item_ref,
    _selected_refs,
)


def install_model_multiselect_support() -> None:
    """Kept for compatibility: multi-selection no longer needs installing."""
