#!/usr/bin/env python3
"""Render the real GUI from the public experimental project; never rerun fits.

QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_project_screenshots.py
User settings and caches are isolated. Requires the repository dependencies.
"""
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'projects' / 'experimental-fluorescence.fitproj'
OUTPUT = ROOT / 'dist' / 'assets' / 'experimental'
FOCUS = 'curve_01ebf2b16013'


def render():
    # Screenshot generation must not start network update checks.
    os.environ["CURVEMOLE_DISABLE_UPDATE_CHECK"] = "1"

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

    from curvemole.core.serialization import load_project
    from curvemole.gui.app import CurveMoleMainWindow, _configure_gui_defaults

    _configure_gui_defaults()
    app = QApplication.instance() or QApplication(['curvemole-website-screenshots'])
    app.setStyle('Fusion')
    app.setFont(QFont('DejaVu Sans', 10))
    QCoreApplication.setOrganizationName('CurveMole website screenshots')
    QCoreApplication.setApplicationName('Experimental project views')
    project = load_project(PROJECT)
    window = CurveMoleMainWindow(project)
    window.autosave_timer.stop()
    window.reset_layout()
    window.resize(1600, 1000)
    window.apply_theme('dark')
    window._set_active_curve(FOCUS)
    window.selected_component_id = project.model_for(FOCUS).components[2].id
    window.model_panel.show_all_functions.setChecked(False)
    window.refresh_all()
    window.show()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    def settle():
        for _ in range(15):
            app.processEvents()

    def tree_selection(ids, expanded):
        window.curve_tree.blockSignals(True)
        window.curve_tree.clearSelection()
        iterator = QTreeWidgetItemIterator(window.curve_tree)
        active = None
        while iterator.value():
            item = iterator.value()
            data = item.data(1, Qt.ItemDataRole.UserRole)
            if data:
                if data[0] == 'series':
                    item.setExpanded(data[1] in expanded)
                elif data[0] == 'curve':
                    item.setSelected(data[1] in ids)
                    if data[1] == FOCUS:
                        active = item
            iterator += 1
        if active:
            window.curve_tree.scrollToItem(active)
        window.curve_tree.blockSignals(False)
        window._selection_changed()

    def capture(widget, name):
        settle()
        if not widget.grab().save(str(OUTPUT / name), 'PNG'):
            raise RuntimeError(name)
        print(name, flush=True)

    focus_series = project.dataset.series[6]
    tree_selection({FOCUS}, {focus_series.id})
    selected = project.model_for(FOCUS).components[2].id
    window.selected_component_id = selected
    assert window.model_panel.select_component_ref(FOCUS, selected)
    window.model_panel.refresh_parameters()
    window.plot_workspace.auto_range()
    window.statusBar().showMessage('Experimental data · Saved multi-band fit · Block-bootstrap intervals')
    capture(window, 'fit-dark.png')
    project.dirty = False
    window.close()
    settle()


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_SCALE_FACTOR', '1')
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '0')
    with tempfile.TemporaryDirectory(prefix='curvemole-website-') as temp:
        os.environ['XDG_CONFIG_HOME'] = temp
        os.environ['XDG_CACHE_HOME'] = temp
        os.environ['MPLCONFIGDIR'] = temp
        render()
