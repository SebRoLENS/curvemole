"""Compatibility alias: the sequential resume controls live in ``gui.fit_controller``."""
from curvemole.gui.fit_controller import (  # noqa: F401
    install_status_controls,
    set_resume_available,
    style_buttons,
    sync_resume_controls,
    terminate_sequence,
)
