"""Compatibility alias kept for older imports; it no longer patches MainWindow.

MainWindow.subtract_background resolves ``curvemole.gui.main_window.BackgroundComponentsDialog``
at call time, so substituting that name still selects the dialog.
"""
