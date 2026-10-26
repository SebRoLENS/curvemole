"""Exercise the actual desktop startup path, trust checks and layout ordering."""
import json

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QObject, QSettings, Qt, QThread, QTimer
from PySide6.QtWidgets import QApplication

from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.gui.app import _open_paths, create_main_window
from curvemole.gui.plugin_host import PluginHost


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    monkeypatch.setattr("platformdirs.user_config_path", lambda *args: tmp_path / "config")
    monkeypatch.delenv("CURVEMOLE_DISABLE_PLUGINS", raising=False)
    monkeypatch.setenv("CURVEMOLE_SMOKE_TEST", "1")
    monkeypatch.setattr(extensions, "entries", {})
    notices = []
    monkeypatch.setattr(PluginHost, "startup_notice", lambda self, recovered, failures:
                        notices.append((recovered, failures)))
    manager = PluginManager(storage=tmp_path / "config" / "plugins")
    for identifier in ("first", "second"):
        source = tmp_path / f"{identifier}.py"
        source.write_text('''from PySide6.QtWidgets import QWidget
def register(api):
    api.add("panels", "panel", "Panel", lambda context: QWidget(), auto_show=True)
''')
        manifest = tmp_path / f"{identifier}.curvemole-plugin.json"
        manifest.write_text(json.dumps(dict(identifier=identifier, version="1", api_compatibility="1",
                                             licence="MIT", capabilities=["panels"], module=source.name)))
    for candidate in manager.discover_local(tmp_path):
        manager.load(candidate, trust=True)
    extensions.entries.clear()
    windows = []

    def create(**kwargs):
        window = create_main_window(**kwargs)
        windows.append(window)
        return window

    yield app, manager, settings, notices, create
    for window in windows:
        window.project.dirty = False
        window.close()
    app.processEvents()


def finish_startup(window):
    loop = QEventLoop()
    window.plugins_ready.connect(loop.quit)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(5000)
    loop.exec()
    assert not window._startup_pending, "Deferred startup did not complete"


def test_first_paint_precedes_loading_and_events_run_between_plugins(plugins, monkeypatch, tmp_path):
    app, _, _, notices, create = plugins
    window = create()
    painted = []
    events = []

    class Observer(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                painted.append(True)
            return False

    observer = Observer(window)
    window.installEventFilter(observer)
    real_load = window.plugin_manager.load

    def load(candidate, **kwargs):
        assert painted
        assert QThread.currentThread() == app.thread()
        events.append(candidate.metadata.identifier)
        QTimer.singleShot(0, lambda: events.append("event turn"))
        return real_load(candidate, **kwargs)

    monkeypatch.setattr(window.plugin_manager, "load", load)
    assert window._startup_pending and not window.plugin_manager.loaded
    assert not window.centralWidget().isEnabled()
    assert not window.plugin_update_controller.startup_timer.isActive()
    assert not window._release_update_controller.startup_timer.isActive()
    path = tmp_path / "spectrum.txt"
    path.write_text("0 1\n1 2\n2 3\n")
    opened = []
    monkeypatch.setattr(window, "import_data", lambda paths: opened.extend(paths))
    _open_paths(window, [str(path)])
    assert not opened
    window.show()
    finish_startup(window)
    assert events.index("event turn") < events.index("second")
    assert set(window.plugin_manager.loaded) == {"first", "second"}
    assert window.centralWidget().isEnabled()
    assert set(window.plugin_host.dialogs) == {"first:panel", "second:panel"}
    assert notices == [(False, set())]
    assert opened == [str(path)]
    assert window.plugin_update_controller.startup_timer.isActive()
    assert window._release_update_controller.startup_timer.isActive()


def test_saved_plugin_docks_exist_before_layout_restore(plugins, monkeypatch):
    app, _, _, _, create = plugins
    first = create(defer_plugins=False)
    first.show()
    dock = first.plugin_host.dialogs["first:panel"]
    first.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    app.processEvents()
    first.close()
    extensions.entries.clear()
    second = create()
    restore = second._restore_layout
    calls = []

    def restore_layout():
        assert set(second.plugin_host.dialogs) == {"first:panel", "second:panel"}
        calls.append(True)
        restore()

    monkeypatch.setattr(second, "_restore_layout", restore_layout)
    assert not calls
    second.show()
    finish_startup(second)
    assert calls == [True]
    assert second.dockWidgetArea(second.plugin_host.dialogs["first:panel"]) == Qt.DockWidgetArea.BottomDockWidgetArea


def test_close_before_first_paint_preserves_plugins_and_layout(plugins):
    app, manager, settings, _, create = plugins
    original = b"saved layout before startup"
    settings.setValue("window_state", original)
    window = create()
    marker = window.plugin_manager.session_path
    assert marker.exists()
    window.close()
    app.processEvents()
    assert not marker.exists()
    assert not window.plugin_manager.loaded
    assert settings.value("window_state") == original
    assert all(record["enabled"] for record in PluginManager(storage=manager.storage).installed.values())


def test_changed_plugin_is_quarantined_and_other_plugins_finish(plugins, monkeypatch):
    _, manager, _, notices, create = plugins
    source = manager.storage.parents[1] / "first.py"
    source.write_text("raise RuntimeError('changed source must never execute')")
    window = create()
    window.show()
    finish_startup(window)
    assert set(window.plugin_manager.loaded) == {"second"}
    assert "source changed" in window.plugin_manager.installed["first"]["error"]
    assert notices == [(False, {"first"})]


def test_clean_autoload_hashes_each_plugin_once_and_does_not_rewrite(plugins, monkeypatch):
    _, original, _, _, _ = plugins
    installed = original.storage / "installed.json"
    timestamp = installed.stat().st_mtime_ns
    manager = PluginManager(storage=original.storage)
    fingerprint = manager._fingerprint
    hashed = []

    def record(candidate):
        hashed.append(candidate.metadata.identifier)
        return fingerprint(candidate)

    monkeypatch.setattr(manager, "_fingerprint", record)
    assert manager.autoload() == set()
    assert hashed == ["first", "second"]
    assert installed.stat().st_mtime_ns == timestamp
    assert set(manager.load_timings) == {"first", "second"}


def test_disable_between_steps_prevents_pending_plugin_execution(plugins):
    _, original, _, _, _ = plugins
    manager = PluginManager(storage=original.storage)
    steps = manager.autoload_steps()
    assert next(steps) == ("first", True)
    manager.disable("second")
    assert list(steps) == []
    assert set(manager.loaded) == {"first"}


def test_close_between_plugins_stops_loading_and_keeps_pending_plugin_enabled(plugins, monkeypatch):
    app, _, _, _, create = plugins
    window = create()
    original = window.plugin_manager.load
    loop = QEventLoop()

    def close():
        window.close()
        loop.quit()

    def load(candidate, **kwargs):
        result = original(candidate, **kwargs)
        QTimer.singleShot(0, close)
        return result

    monkeypatch.setattr(window.plugin_manager, "load", load)
    window.show()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(5000)
    loop.exec()
    app.processEvents()
    assert window._session_finished
    assert set(window.plugin_manager.loaded) == {"first"}
    assert window.plugin_manager.installed["second"]["enabled"]
    assert not window.plugin_manager.session_path.exists()


def test_persistence_failure_during_quarantine_does_not_lock_the_desktop(plugins, monkeypatch):
    _, manager, _, _, create = plugins
    (manager.storage.parents[1] / "first.py").write_text("changed source")
    window = create()

    def fail_save():
        raise OSError("Plugin storage is read-only")

    monkeypatch.setattr(window.plugin_manager, "_save", fail_save)
    window.show()
    finish_startup(window)
    assert window.centralWidget().isEnabled()
    assert "Plugin storage is read-only" in window.log.toPlainText()
