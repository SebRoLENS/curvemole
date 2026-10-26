"""Native open events, live mapping choices and requests during a running task."""
from types import SimpleNamespace

from PySide6.QtCore import QObject
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

from curvemole.gui.external_files import ExternalFileController, ExternalImportBatch
from curvemole.single_instance import NativeFileOpenFilter


def test_native_events_and_early_ipc_are_queued_until_gui_is_ready(tmp_path):
    file_filter = NativeFileOpenFilter()
    watched = QObject()
    paths = [str(tmp_path / f'file {index}.xy') for index in range(100)]
    for path in paths[:50]:
        assert file_filter.eventFilter(watched, QFileOpenEvent(path))
    file_filter.enqueue(paths[50:75])  # IPC can arrive during GUI construction.
    received = []
    file_filter.set_file_open_handler(received.append)
    for path in paths[75:]:
        assert file_filter.eventFilter(watched, QFileOpenEvent(path))
    assert received == paths
    assert not file_filter._pending_file_opens


def test_late_paths_preserve_mapping_choice_and_sort_only_unprocessed_tail(tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = [str(tmp_path / f'file {index}.xy') for index in (1, 10, 2, 3)]
    batch = ExternalImportBatch(paths[:1])
    batch.index = 0
    checkbox = QCheckBox()
    checkbox.hide()
    batch.dialog = SimpleNamespace(apply_all=checkbox, tr=lambda text: text)
    batch.add(paths[1:3])
    assert batch.paths == [paths[0], paths[2], paths[1]]
    assert checkbox.isChecked() and not checkbox.isHidden()
    checkbox.setChecked(False)  # A user can still choose per-file mappings.
    batch.add([paths[3], paths[1]])
    assert not checkbox.isChecked()
    assert batch.paths == [paths[0], paths[2], paths[3], paths[1]]
    checkbox.close()
    app.processEvents()


def test_external_requests_wait_for_busy_window_and_keep_late_files(tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = [tmp_path / name for name in ('project.fitproj', 'first.xy', 'second.xy')]
    for path in paths:
        path.touch()
    window = QWidget()
    window._session_finished = False
    window._startup_pending = True
    window._thread = None
    window.automation_runner = SimpleNamespace(process=None)
    projects, imported = [], []
    window.open_project = projects.append
    window._show_error = lambda *_: None
    controller = ExternalFileController(window, delay_ms=500)
    def import_data(values):
        imported.append(list(values))
        # Native/argv duplicates arriving during an active batch are ignored.
        controller.enqueue([str(paths[0]), str(paths[1])])
        window._external_import_batch.accepting = False
        # A new file arriving after iteration finished must form the next batch.
        controller.enqueue([str(paths[2])])
    window.import_data = import_data
    controller.enqueue(list(map(str, paths[:2])))
    controller.flush()
    assert not imported and not projects
    assert controller.timer.interval() == 100
    window._startup_pending = False
    controller.flush()
    assert projects == [str(paths[0])]
    assert imported == [[str(paths[1])]]
    assert controller.pending == [str(paths[2])]
    assert controller.timer.interval() == 500
    controller.timer.stop()
    window.close()
    app.processEvents()
