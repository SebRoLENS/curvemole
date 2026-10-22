#!/usr/bin/env python3
"""Capture the original Raman example in dark mode and a matching theme pair.

Uses the existing screenshot generator's original project and real GUI.
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_demo_screenshots.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'website' / 'dist' / 'assets' / 'demo'


def render():
    # Screenshot generation must not start network update checks.
    os.environ["CURVEMOLE_DISABLE_UPDATE_CHECK"] = "1"

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.main_window import MainWindow
    sys.path.insert(0, str(ROOT / 'scripts'))
    from generate_screenshots import build_example_project

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(['curvemole-demo-screenshots'])
    app.setStyle('Fusion')
    app.setFont(QFont('DejaVu Sans', 10))
    QCoreApplication.setOrganizationName('CurveMole website screenshots')
    QCoreApplication.setApplicationName('Original Raman example')
    project, peak = build_example_project()
    window = MainWindow(project)
    window.autosave_timer.stop()
    window.reset_layout()
    window.resize(1440, 900)
    window.selected_component_id = peak
    window.refresh_all()
    window.plot_workspace.plot.getAxis('bottom').enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis('bottom').enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis('left').enableAutoSIPrefix(False)
    window.show()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    def capture(name):
        window.plot_workspace.auto_range()
        for _ in range(15):
            app.processEvents()
        assert window.grab().save(str(OUTPUT / name), 'PNG')
        print(name, flush=True)

    # Hold selection, viewport and window geometry fixed across both themes.
    window.apply_theme('dark')
    window.statusBar().showMessage('Single-spectrum fit · Original Raman example')
    capture('fit-dark.png')
    window.apply_theme('light')
    capture('fit-light.png')
    window.apply_theme('dark')
    window.selected_component_id = None
    window.curve_tree.select_all_curves()
    window.plot_workspace.display_mode.setCurrentIndex(1)
    window.plot_workspace.set_component_labels_visible(False)
    window.statusBar().showMessage('Three fitted Raman-like spectra · Overlay comparison · Dark mode')
    capture('overlay-dark.png')
    window.plot_workspace.display_mode.setCurrentIndex(2)
    window.plot_workspace.x_offset.setValue(0.0)
    window.plot_workspace.y_offset.setValue(0.55)
    window.statusBar().showMessage('Three fitted Raman-like spectra · Waterfall view · Dark mode')
    capture('waterfall-dark.png')
    project.dirty = False
    window.close()
    app.processEvents()


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_SCALE_FACTOR', '1')
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '0')
    with tempfile.TemporaryDirectory(prefix='curvemole-demo-') as temp:
        os.environ['XDG_CONFIG_HOME'] = temp
        os.environ['XDG_CACHE_HOME'] = temp
        os.environ['MPLCONFIGDIR'] = temp
        render()
