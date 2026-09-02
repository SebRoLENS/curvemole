"""Keep sequential-fit resume controls visible while a sequence is paused."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QPushButton

from curvemole.core.fitting import FitMode
from curvemole.gui.main_window import MainWindow


def install_sequential_resume_button() -> None:
    if getattr(MainWindow, "_curvemole_visible_sequential_resume", False):
        return

    original_init = MainWindow.__init__
    original_fit_finished = MainWindow._fit_finished
    original_resume_sequence = MainWindow.resume_sequence

    def set_resume_available(window: MainWindow, available: bool) -> None:
        window.resume_action.setEnabled(available)
        button = getattr(window, "sequential_resume_button", None)
        if button is not None:
            button.setVisible(available)
            button.setEnabled(available)

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        button = QPushButton(window.tr("Continue sequential fit"), window)
        button.setToolTip(
            window.tr(
                "Continue the paused sequential refinement using the current spectrum as the new source."
            )
        )
        button.setVisible(False)
        button.setEnabled(False)
        button.clicked.connect(window.resume_sequence)
        window.sequential_resume_button = button
        window.statusBar().addPermanentWidget(button)

    def fit_finished(window: MainWindow, result: Any) -> None:
        original_fit_finished(window, result)
        paused = getattr(window, "_sequential_pause_result", None) or getattr(
            window, "_paused_result", None
        )
        if paused is not None and getattr(paused, "paused_curve_id", None):
            set_resume_available(window, True)
        elif result.mode == FitMode.SEQUENTIAL and result.success:
            set_resume_available(window, False)

    def resume_sequence(window: MainWindow) -> None:
        # Hide the control while the sequence is running. If it pauses again,
        # _fit_finished() will make the button visible again automatically.
        set_resume_available(window, False)
        original_resume_sequence(window)

    MainWindow.__init__ = init
    MainWindow._fit_finished = fit_finished
    MainWindow.resume_sequence = resume_sequence
    MainWindow._set_sequential_resume_available = set_resume_available
    MainWindow._curvemole_visible_sequential_resume = True


install_sequential_resume_button()
