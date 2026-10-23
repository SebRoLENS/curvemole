#!/usr/bin/env python3
"""Capture real customization controls, without loading plugins or changing projects."""
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'website/dist/assets/customization'


def render():
    os.environ['CURVEMOLE_DISABLE_UPDATE_CHECK'] = '1'
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from curvemole.core.serialization import load_project
    from curvemole.gui.app import CurveMoleMainWindow, _configure_gui_defaults
    from curvemole.gui.dialogs import PluginManagerDialog

    _configure_gui_defaults()
    app = QApplication.instance() or QApplication(['customization-screenshots'])
    app.setStyle('Fusion')
    app.setFont(QFont('DejaVu Sans', 10))
    QCoreApplication.setOrganizationName('CurveMole website screenshots')
    QCoreApplication.setApplicationName('Customization examples')
    project = load_project(ROOT / 'website/projects/experimental-fluorescence.fitproj')
    window = CurveMoleMainWindow(project)
    window.autosave_timer.stop()
    window.reset_layout()
    window.apply_theme('dark')
    window.resize(1440, 900)
    window._set_active_curve('curve_01ebf2b16013')
    window.refresh_all()
    window.show()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    def capture(widget, name):
        for _ in range(15):
            app.processEvents()
        if not widget.grab().save(str(OUTPUT / name), 'JPG', 88):
            raise RuntimeError(name)
        print(name, flush=True)

    window.model_panel.setMinimumWidth(500)
    window.plot_workspace.auto_range()
    capture(window, 'composite-model.jpg')
    window.function_dock.setFloating(True)
    window.function_dock.resize(920, 620)
    builder = window.function_builder
    builder.identifier.setText('damped_cosine')
    builder.display_name.setText('Exponentially damped cosine')
    builder.kind.setCurrentIndex(builder.kind.findData('generic'))
    builder.formula.setPlainText('offset + amplitude * exp(-x / tau) * cos(omega * x + phase)')
    builder._validate()
    window.function_dock.show()
    capture(window.function_dock, 'function-builder.jpg')
    window.function_dock.hide()
    dialog = PluginManagerDialog(window.plugin_manager, ROOT / 'custom_plugins/by_main_developer/tsv_exporter', window)
    dialog.resize(1000, 650)
    if dialog.list.count():
        dialog.list.setCurrentRow(0)
    # Display a portable relative source path; the real manager has already scanned it.
    dialog.directory.setText('custom_plugins/by_main_developer/tsv_exporter')
    dialog.details.setPlainText(dialog.details.toPlainText().replace(str(ROOT) + '/', ''))
    dialog.show()
    capture(dialog, 'plugin-manager.jpg')
    dialog.close()
    project.dirty = False
    window.close()
    app.processEvents()


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_SCALE_FACTOR', '1')
    with tempfile.TemporaryDirectory(prefix='curvemole-customization-') as temp:
        os.environ['XDG_CONFIG_HOME'] = temp
        os.environ['XDG_CACHE_HOME'] = temp
        os.environ['MPLCONFIGDIR'] = temp
        render()
