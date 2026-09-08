"""Keep sequential-fit resume controls visible while a sequence is paused."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QPushButton

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
    original_theme = MainWindow.apply_theme

    def style_button(window: MainWindow) -> None:
        button = getattr(window, "sequential_resume_button", None)
        if button is None:
            return
        dark = QApplication.palette().color(QPalette.ColorRole.Button).lightness() < 128
        background, foreground, border, hover, pressed = (
            ("#5EEAD4", "#083B36", "#B5FFF1", "#99F6E4", "#2DD4BF") if dark else
            ("#0F766E", "#FFFFFF", "#0B5F59", "#115E59", "#134E4A")
        )
        disabled_bg, disabled_fg = ("#475569", "#CBD5E1") if dark else ("#E2E8F0", "#64748B")
        button.setStyleSheet(
            "QPushButton#sequential_resume_button {"
            f"background-color: {background}; color: {foreground}; border: 2px solid {border};"
            "border-radius: 7px; padding: 6px 18px; font-weight: bold; }"
            f"QPushButton#sequential_resume_button:hover {{ background-color: {hover}; }}"
            f"QPushButton#sequential_resume_button:pressed {{ background-color: {pressed}; }}"
            "QPushButton#sequential_resume_button:disabled {"
            f"background-color: {disabled_bg}; color: {disabled_fg}; border-color: {disabled_fg}; }}"
        )
        stop = getattr(window, "sequential_stop_button", None)
        if stop is not None:
            stop.setStyleSheet(button.styleSheet().replace("sequential_resume_button", "sequential_stop_button")
                .replace(background, "#FDA4AF" if dark else "#BE123C")
                .replace(foreground, "#4C0519" if dark else "#FFFFFF")
                .replace(border, "#FFE4E6" if dark else "#881337")
                .replace(hover, "#FECDD3" if dark else "#9F1239")
                .replace(pressed, "#FB7185" if dark else "#881337"))

    def theme(window: MainWindow, selected: str) -> None:
        original_theme(window, selected)
        style_button(window)

    def set_resume_available(window: MainWindow, available: bool) -> None:
        enabled = available and window._thread is None
        window.resume_action.setEnabled(enabled)
        button = getattr(window, "sequential_resume_button", None)
        if button is not None:
            button.setVisible(available)
            button.setEnabled(enabled)
        stop = getattr(window, "sequential_stop_button", None)
        if stop is not None:
            stop.setVisible(available)
            stop.setEnabled(enabled)

    def terminate_sequence(window: MainWindow) -> None:
        if window._thread is not None:
            return
        window._sequential_resume_plan = None
        window._sequential_pause_result = None
        window._paused_result = None
        window._sequential_pause_source_ids = ()
        set_resume_available(window, False)
        window._notify(window.tr("Sequential fit terminated. Existing fits and model edits were retained."))

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
        stop = QPushButton("■  " + window.tr("Terminate sequential fit"), window)
        stop.setObjectName("sequential_stop_button")
        stop.setMinimumHeight(38)
        stop.setToolTip(window.tr("Discard the paused sequence while keeping all existing fits and model edits."))
        stop.clicked.connect(window.terminate_sequence)
        window.sequential_stop_button = stop
        window.statusBar().addPermanentWidget(stop)
        style_button(window)
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
    MainWindow.terminate_sequence = terminate_sequence
    MainWindow.refresh_all = refresh
    MainWindow._task_done = done
    MainWindow._run_background = background
    MainWindow.apply_theme = theme
    MainWindow._set_sequential_resume_available = set_resume_available
    MainWindow._curvemole_visible_sequential_resume = True


install_sequential_resume_button()
