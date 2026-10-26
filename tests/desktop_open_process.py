"""Subprocess harness for real desktop launch/open integration tests."""
import json
import os
import sys
from pathlib import Path

mode, folder, output, *paths = sys.argv[1:]
folder, output = Path(folder), Path(output)
os.environ.update(QT_QPA_PLATFORM='offscreen', CURVEMOLE_DISABLE_UPDATE_CHECK='1')
os.environ.pop('CURVEMOLE_SMOKE_TEST', None)
for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'APPDATA', 'LOCALAPPDATA'):
    os.environ[key] = str(folder / key)

if mode == 'elect':
    from PySide6.QtCore import QCoreApplication, QTimer

    from curvemole.single_instance import DesktopInstance
    instance = DesktopInstance(folder)
    owner = instance.acquire()
    app = QCoreApplication([])
    path = str((folder / (paths[0] + '.xy')).resolve())
    if not owner:
        instance.forward([path])
    else:
        owners = output.with_suffix('.owners')
        with owners.open('a') as stream:
            stream.write(str(os.getpid()) + '\n')
        received = [path]
        instance.paths_received.connect(received.extend)
        instance.listen()
        def check():
            if len(received) == 12:
                output.write_text(json.dumps(dict(paths=received, owners=owners.read_text().splitlines())))
                QTimer.singleShot(100, app.quit)
                timer.stop()
        timer = QTimer()
        timer.timeout.connect(check)
        timer.start(10)
        QTimer.singleShot(30_000, app.quit)
        app.exec()
        instance.close()
        assert output.exists()
    sys.exit(0)

if mode == 'forward':
    from curvemole.desktop import main
    code = main([sys.argv[0], *paths], instance_directory=folder)
    assert 'numpy' not in sys.modules and 'curvemole.gui' not in sys.modules
    sys.exit(code)

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder / 'settings'))

import platformdirs  # noqa: E402

for kind in ('config', 'data', 'cache'):
    def profile_path(appname=None, *args, _kind=kind, **kwargs):
        return folder / _kind / (appname or '')
    setattr(platformdirs, f'user_{kind}_path', profile_path)

from curvemole.desktop import main  # noqa: E402
from curvemole.gui import app as gui  # noqa: E402
from curvemole.gui.dialogs import ImportMappingDialog  # noqa: E402

expected = int(paths.pop(0))
state = dict(windows=0, dialogs=0, errors=[])
original_window = gui.create_main_window


def create_window(*args, **kwargs):
    window = original_window(*args, **kwargs)
    state['windows'] += 1
    state['window'] = window
    window._show_error = lambda title, error: state['errors'].append(f'{title}: {error}')
    output.with_suffix('.ready').touch()
    return window


def dialog_exec(dialog):
    state['dialogs'] += 1
    output.with_suffix('.dialog').touch()
    poll = QTimer(dialog)
    def accept_when_complete():
        batch = state['window']._external_import_batch
        if len(batch.paths) == expected:
            dialog.apply_all.setChecked(True)
            poll.stop()
            dialog._accept()
    poll.timeout.connect(accept_when_complete)
    poll.start(20)
    return QDialog.exec(dialog)


def check_import():
    window = state.get('window')
    if window is not None and len(window.project.curves) == expected:
        result = dict(windows=state['windows'], dialogs=state['dialogs'], errors=state['errors'],
                      paths=[curve.source for curve in window.project.curves])
        output.write_text(json.dumps(result), encoding='utf-8')
        window.project.dirty = False
        window.close()
    elif state['errors']:
        output.write_text(json.dumps(dict(errors=state['errors'])), encoding='utf-8')
        QApplication.instance().quit()


gui.create_main_window = create_window
ImportMappingDialog.exec = dialog_exec
QMessageBox.warning = lambda *args: QMessageBox.StandardButton.Ok
QMessageBox.critical = lambda *args: QMessageBox.StandardButton.Ok
timer = QTimer()
timer.timeout.connect(check_import)
deadline = QTimer()
deadline.setSingleShot(True)
def expired():
    QApplication.instance().quit()
deadline.timeout.connect(expired)
original_run = gui.run_primary


def run_primary(*args):
    timer.start(20)
    deadline.start(75_000)
    return original_run(*args)


gui.run_primary = run_primary
sys.exit(main([sys.argv[0], *paths], instance_directory=folder))
