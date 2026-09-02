from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QLocale

from curvemole.gui.app import _configure_gui_defaults


def test_gui_defaults_use_decimal_point() -> None:
    _configure_gui_defaults()
    assert QLocale().decimalPoint() == "."


def test_gui_defaults_use_single_button_mouse_mode() -> None:
    _configure_gui_defaults()
    assert pg.getConfigOption("leftButtonPan") is False
