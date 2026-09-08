"""Keep sequential-fit resume controls visible while a sequence is paused."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QPushButton

from curvemole.gui.main_window import MainWindow


def install_sequential_resume_button() -> None:
    if getattr(MainWindow, "_curvemole_visible_sequential_resume", False):
        return

    original_init = MainWindow.__init__
    original_fit_finished = MainWindow._fit_finished
    original_resume_sequence = MainWindow.resume_sequence
    original_refresh = MainWindow.refresh_all
    original_done = MainWindow._task_done
    original_background = MainWindow._run_background

    def set_resume_available(window: MainWindow, available: bool) -> None:
        enabled = available and window._thread is None
        window.resume_action.setEnabled(enabled)
        button = getattr(window, "sequential_resume_button", None)
        if button is not None:
            button.setVisible(available)
            button.setEnabled(enabled)

    def sync(window: MainWindow) -> None:
        if not hasattr(window, "resume_action"):
            return
        paused = getattr(window, "_sequential_pause_result", None) or getattr(window, "_paused_result", None)
        set_resume_available(window, bool(paused and paused.paused_curve_id))

    def init(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_init(window, *args, **kwargs)
        button = QPushButton("▶  " + window.tr("Continue sequential fit"), window)
        button.setObjectName("sequential_resume_button")
        button.setMinimumHeight(38)
        button.setStyleSheet(
            "QPushButton#sequential_resume_button {"
            "background-color: #0F766E; color: #FFFFFF; border: 2px solid #5EEAD4;"
            "border-radius: 7px; padding: 6px 18px; font-weight: bold; }"
            "QPushButton#sequential_resume_button:hover { background-color: #115E59; }"
            "QPushButton#sequential_resume_button:pressed { background-color: #134E4A; }"
            "QPushButton#sequential_resume_button:disabled {"
            "background-color: #475569; color: #CBD5E1; border-color: #64748B; }"
        )
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
        sync(window)

    def fit_finished(window: MainWindow, result: Any) -> None:
        original_fit_finished(window, result)
        sync(window)

    def resume_sequence(window: MainWindow) -> None:
        original_resume_sequence(window)
        sync(window)

    def refresh(window: MainWindow) -> None:
        original_refresh(window)
        sync(window)

    def done(window: MainWindow, *args: Any) -> None:
        original_done(window, *args)
        sync(window)

    def background(window: MainWindow, *args: Any, **kwargs: Any) -> None:
        original_background(window, *args, **kwargs)
        sync(window)

    MainWindow.__init__ = init
    MainWindow._fit_finished = fit_finished
    MainWindow.resume_sequence = resume_sequence
    MainWindow.refresh_all = refresh
    MainWindow._task_done = done
    MainWindow._run_background = background
    MainWindow._set_sequential_resume_available = set_resume_available
    MainWindow._curvemole_visible_sequential_resume = True


install_sequential_resume_button()
