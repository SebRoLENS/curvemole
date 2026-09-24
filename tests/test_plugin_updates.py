import copy
import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from curvemole.core.errors import CurveMoleError
from curvemole.core.extensions import extensions
from curvemole.core.plugin_updates import (
    available_updates,
    community_plugins,
    install_community_plugin,
    stage_update,
)
from curvemole.core.plugins import PluginManager
from curvemole.core.registry import FunctionRegistry


@pytest.fixture
def update_case(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "entries", {})
    original = tmp_path / "original"
    original.mkdir()
    manifest = dict(identifier="test.plugin", name="Test plugin", description="A test plugin",
                    author="Test author", version="1.0.0",
                    api_compatibility="1", licence="MIT", capabilities=["actions"], module="plugin.py")
    (original / "plugin.curvemole-plugin.json").write_text(json.dumps(manifest))
    (original / "plugin.py").write_text('def register(api):\n api.add("actions", "test", "Test", lambda ctx: None)\n')
    manager = PluginManager(FunctionRegistry(), storage=tmp_path / "storage")
    manager.load(manager.discover_local(original)[0], trust=True)
    manifest["version"] = "1.1.0"
    files = {"plugin.curvemole-plugin.json": json.dumps(manifest).encode(),
             "plugin.py": b'def register(api):\n api.add("actions", "test", "Updated", lambda ctx: None)\n',
             "README.md": b"Plugin-specific manual", "LICENSE": b"MIT"}
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + content)
    catalog = {"plugins": [{**manifest, "folder": "test_plugin", "sha256": digest.hexdigest()}]}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr("test_plugin/" + name, content)
    update = available_updates(manager, catalog)[0][0]
    return manager, catalog, update, output.getvalue(), original


def test_checks_only_loaded_local_plugins(update_case):
    manager, catalog, update, _, _ = update_case
    unloaded = dict(catalog["plugins"][0], identifier="unloaded")
    catalog["plugins"].append(unloaded)
    manager.installed["unloaded"] = {"enabled": False}
    updates, unsupported = available_updates(manager, catalog)
    assert updates == [update]
    assert unsupported == []
    manager.disable(update.identifier)
    assert available_updates(manager, catalog) == ([], [])


def test_unknown_and_package_plugins_are_not_replaced(update_case):
    manager, catalog, _, _, _ = update_case
    assert available_updates(manager, {"plugins": []}) == ([], ["test.plugin"])
    manager.installed["test.plugin"]["kind"] = "entry_point"
    assert available_updates(manager, catalog) == ([], ["test.plugin"])


def test_stage_preserves_running_code_and_loads_update_next_start(update_case):
    manager, catalog, update, data, original = update_case
    callback = extensions.entries["test.plugin:test"].callback
    stage_update(manager, update, data)
    assert manager.loaded[update.identifier].version == "1.0.0"
    assert extensions.entries["test.plugin:test"].callback is callback
    assert json.loads((original / "plugin.curvemole-plugin.json").read_text())["version"] == "1.0.0"
    installed_path = Path(manager.installed[update.identifier]["reference"])
    assert (installed_path.parent / "README.md").read_text() == "Plugin-specific manual"
    assert available_updates(manager, catalog)[0] == []
    symbol = manager.symbol(update.identifier)
    extensions.entries.clear()
    restarted = PluginManager(FunctionRegistry(), storage=manager.storage)
    restarted.autoload()
    assert restarted.loaded[update.identifier].version == "1.1.0"
    assert restarted.symbol(update.identifier) == symbol
    assert "Updated" in extensions.entries["test.plugin:test"].label


@pytest.mark.parametrize("fault", ["checksum", "identity", "api", "disabled", "save", "truncated"])
def test_failed_update_retains_previous_installation(update_case, monkeypatch, fault):
    manager, _, update, data, _ = update_case
    if fault == "disabled":
        manager.disable(update.identifier)
    before = copy.deepcopy(manager.installed)
    persisted = (manager.storage / "installed.json").read_bytes()
    if fault == "checksum":
        update = replace(update, sha256="0" * 64)
    elif fault == "identity":
        update = replace(update, capabilities=("exporters",))
    elif fault == "api":
        update = replace(update, api="999")
    elif fault == "save":
        def fail():
            raise OSError("Disk full")
        monkeypatch.setattr(manager, "_save", fail)
    elif fault == "truncated":
        data = data[:30]
    with pytest.raises((CurveMoleError, OSError, zipfile.BadZipFile)):
        stage_update(manager, update, data)
    assert manager.installed == before
    assert (manager.storage / "installed.json").read_bytes() == persisted
    assert not list((manager.storage / "updates").glob("plugin-*"))


@pytest.mark.parametrize("name", ["../escape.py", "test_plugin/../../escape.py",
                                   "/tmp/escape.py", "test_plugin/C:/escape.py", r"test_plugin\escape.py"])
def test_archive_paths_cannot_escape(update_case, name):
    manager, _, update, _, _ = update_case
    output = io.BytesIO()
    # ZipInfo normalises backslashes on Windows. Replace the stored filename bytes
    # afterward so the archive exercises the same hostile input on every platform.
    stored_name = name.replace("\\", "/")
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(stored_name, b"bad")
    data = output.getvalue()
    if stored_name != name:
        assert len(stored_name) == len(name)
        data = data.replace(stored_name.encode(), name.encode())
        assert name.encode() in data
    # Windows also normalises raw backslashes while reading ZIP metadata. In that
    # case the path is contained, but the altered archive still fails its catalog checksum.
    expected = "Unsafe" if "\\" not in name else "Unsafe|checksum mismatch"
    with pytest.raises(CurveMoleError, match=expected):
        stage_update(manager, update, data)
    assert not list((manager.storage / "updates").glob("plugin-*"))


def test_catalog_and_archive_disagree_after_rolling_release(update_case):
    manager, _, update, data, _ = update_case
    with pytest.raises(CurveMoleError, match="checksum"):
        stage_update(manager, replace(update, sha256="1" * 64), data)
    assert manager.loaded[update.identifier].version == "1.0.0"


def test_no_downgrade_and_incompatible_updates_are_reported(update_case):
    manager, catalog, _, _, _ = update_case
    catalog["plugins"][0]["version"] = "0.9.0"
    assert available_updates(manager, catalog)[0] == []
    catalog["plugins"][0].update(version="2.0.0", api_compatibility="2")
    updates, _ = available_updates(manager, catalog)
    assert not updates[0].compatible


def test_catalog_plugin_installs_into_chosen_folder(update_case, tmp_path):
    manager, catalog, _, archive, _ = update_case
    manager.disable("test.plugin")
    manager.remove("test.plugin")
    destination = tmp_path / "downloaded_plugins"
    destination.mkdir()
    plugin = community_plugins(catalog)[0]
    metadata = install_community_plugin(manager, plugin, archive, destination)
    assert metadata.identifier == plugin.identifier
    assert Path(manager.installed[plugin.identifier]["reference"]).parent == (
        destination / plugin.folder
    )
    assert plugin.identifier in manager.loaded
    assert "test.plugin:test" in extensions.entries


def test_catalog_install_rejects_existing_destination(update_case, tmp_path):
    manager, catalog, _, archive, _ = update_case
    manager.disable("test.plugin")
    manager.remove("test.plugin")
    plugin = community_plugins(catalog)[0]
    (tmp_path / plugin.folder).mkdir()
    with pytest.raises(CurveMoleError, match="already exists"):
        install_community_plugin(manager, plugin, archive, tmp_path)


@pytest.fixture
def controller_case(update_case, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QMainWindow

    from curvemole.gui.plugin_updates import PluginUpdateController
    app = QApplication.instance() or QApplication([])
    manager, catalog, update, data, _ = update_case
    window = QMainWindow()
    window.plugin_manager = manager
    window.settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    window.update_action = QAction(window)
    window._log = lambda message: None
    requests = []
    monkeypatch.setattr(PluginUpdateController, "_fetch", lambda self, url, limit, callback:
                        requests.append((url, callback)))
    controller = PluginUpdateController(window)
    app.processEvents()
    yield app, controller, requests, catalog, update, data
    controller.timer.stop()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_controller_hourly_once_per_version_and_download(controller_case):
    from curvemole.core.plugin_updates import CATALOG_URL
    app, controller, requests, catalog, update, archive = controller_case
    assert controller.timer.interval() == 60 * 60 * 1000
    assert requests[0][0] == CATALOG_URL
    requests.pop()[1](json.dumps(catalog).encode(), "")
    assert controller.dialog.isVisible()
    assert controller.table.rowCount() == 1
    controller.dialog.hide()
    controller.timer.timeout.emit()
    requests.pop()[1](json.dumps(catalog).encode(), "")
    assert not controller.dialog.isVisible()
    controller.open(check=False)
    controller.install_selected()
    assert requests[-1][0] == update.url
    assert not controller.update_button.isEnabled()
    requests.pop()[1](archive, "")
    assert controller.plugins.loaded[update.identifier].version == update.current
    assert controller.table.item(0, 3).text() == "Installed — restart required"
    assert not controller.update_button.isEnabled()
    assert "restart required" in controller.badge.text()


def test_controller_offline_and_empty_loaded_set(controller_case):
    _, controller, requests, _, update, _ = controller_case
    requests.pop()[1](b"", "Offline")
    assert "Offline" in controller.message
    assert controller.dialog is None
    controller.plugins.disable(update.identifier)
    controller.check(force=True)
    assert requests == []
    assert controller.badge.isHidden()


def test_controller_does_not_install_plugin_disabled_during_download(controller_case):
    _, controller, requests, catalog, update, archive = controller_case
    requests.pop()[1](json.dumps(catalog).encode(), "")
    controller.install_selected()
    controller.plugins.disable(update.identifier)
    requests.pop()[1](archive, "")
    assert "no longer loaded" in controller.message
    assert controller.plugins.installed[update.identifier]["metadata"]["version"] == update.current


def test_browse_catalog_installs_selected_plugin_in_chosen_folder(
    controller_case, tmp_path, monkeypatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    _, controller, requests, catalog, update, archive = controller_case
    controller.plugins.disable(update.identifier)
    controller.plugins.remove(update.identifier)
    destination = tmp_path / "community"
    destination.mkdir()
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    controller.browse()
    controller.catalog_folder.setText(str(destination))
    requests[-1][1](json.dumps(catalog).encode(), "")
    assert controller.catalog_table.rowCount() == 1
    controller.catalog_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    controller.install_catalog_selected()
    assert requests[-1][0].endswith("/test_plugin.zip")
    requests[-1][1](archive, "")
    assert update.identifier in controller.plugins.loaded
    assert (destination / "test_plugin" / "plugin.py").is_file()
    assert "installed and loaded" in controller.catalog_status.text().lower()


def test_secondary_plugin_windows_follow_active_modal_parent(controller_case):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog

    app, controller, requests, catalog, _, _ = controller_case
    plugin_manager = QDialog(controller.window)
    plugin_manager.setWindowModality(Qt.WindowModality.ApplicationModal)
    plugin_manager.show()
    app.processEvents()
    observed = []
    controller.busy = False

    def interact_with_updates():
        observed.append(("updates modal", app.activeModalWidget() is controller.dialog))
        before = len(requests)
        QTest.mouseClick(controller.check_button, Qt.MouseButton.LeftButton)
        observed.append(("updates click", len(requests) == before + 1))
        controller.dialog.accept()

    QTimer.singleShot(0, interact_with_updates)
    controller.open(check=False)
    controller.plugins.disable("test.plugin")
    controller.plugins.remove("test.plugin")
    controller.catalog_entries = community_plugins(catalog)

    def interact_with_catalog():
        observed.append(("catalog modal", app.activeModalWidget() is controller.catalog_dialog))
        item = controller.catalog_table.item(0, 0)
        if item is not None:
            rect = controller.catalog_table.visualItemRect(item)
            QTest.mouseClick(controller.catalog_table.viewport(), Qt.MouseButton.LeftButton,
                             pos=rect.topLeft() + QPoint(8, rect.height() // 2))
        observed.append(("catalog click", item is not None and item.checkState() == Qt.CheckState.Checked))
        controller.catalog_dialog.accept()

    QTimer.singleShot(0, interact_with_catalog)
    controller.browse()

    assert controller.catalog_dialog.parent() is plugin_manager
    assert controller.dialog.parent() is plugin_manager
    assert plugin_manager.isVisible()
    assert all(success for _, success in observed), observed
