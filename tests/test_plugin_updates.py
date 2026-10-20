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
    PluginUpdateLocationError,
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
    assert json.loads((original / "plugin.curvemole-plugin.json").read_text())["version"] == "1.1.0"
    installed_path = Path(manager.installed[update.identifier]["reference"])
    assert installed_path.parent == original
    assert (installed_path.parent / "README.md").read_text() == "Plugin-specific manual"
    assert available_updates(manager, catalog)[0] == []
    symbol = manager.symbol(update.identifier)
    extensions.entries.clear()
    restarted = PluginManager(FunctionRegistry(), storage=manager.storage)
    restarted.autoload()
    assert restarted.loaded[update.identifier].version == "1.1.0"
    assert restarted.symbol(update.identifier) == symbol
    assert "Updated" in extensions.entries["test.plugin:test"].label


def test_update_replaces_owned_files_and_preserves_unrelated_user_files(update_case):
    manager, _, update, data, original = update_case
    (original / 'obsolete.py').write_text('old implementation')
    (original / 'notes.txt').write_text('user notes')
    (original / '__pycache__').mkdir(exist_ok=True)
    (original / '__pycache__' / 'stale.pyc').write_bytes(b'old bytecode')
    manager.installed[update.identifier]['files'] = ['plugin.py', 'obsolete.py']
    stage_update(manager, update, data)
    assert not (original / 'obsolete.py').exists()
    assert not (original / '__pycache__').exists()
    assert (original / 'notes.txt').read_text() == 'user notes'
    assert (original / 'LICENSE').read_text() == 'MIT'
    assert not list(original.parent.glob('.curvemole-plugin-update-*'))
    assert not list(manager.storage.rglob('*.py'))


@pytest.mark.parametrize('relocate', [False, True])
def test_disable_restart_and_manager_scan_keep_the_updated_version(
    update_case, tmp_path, monkeypatch, relocate
):
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.dialogs import PluginManagerDialog

    app = QApplication.instance() or QApplication([])
    manager, _, update, data, original = update_case
    selected = tmp_path / 'chosen-plugin-folder'
    selected.mkdir()
    if relocate:
        rename = Path.rename

        def protected(path, target):
            if path == original:
                raise PermissionError('Original plugin directory is protected')
            return rename(path, target)

        monkeypatch.setattr(Path, 'rename', protected)
        with pytest.raises(PluginUpdateLocationError, match='another writable folder'):
            stage_update(manager, update, data)
        assert manager.installed[update.identifier]['metadata']['version'] == '1.0.0'
        stage_update(manager, update, data, destination=selected)
        assert json.loads((original / 'plugin.curvemole-plugin.json').read_text())['version'] == '1.0.0'
    else:
        stage_update(manager, update, data)
    installed = Path(manager.installed[update.identifier]['reference'])
    assert installed.parent == (selected / update.folder if relocate else original)
    assert manager.installed[update.identifier]['metadata']['source'] == str(installed)
    files = manager.installed[update.identifier]['files']
    manager.disable(update.identifier)
    restarted = PluginManager(FunctionRegistry(), storage=manager.storage)
    assert restarted.autoload() == set() and not restarted.loaded
    monkeypatch.setattr(restarted, 'discover_entry_points', lambda: [])
    dialog = PluginManagerDialog(restarted, original)
    try:
        candidate = dialog.candidates[0]
        assert candidate.metadata.version == update.latest
        assert Path(candidate.reference) == installed
        restarted.load(candidate, trust=True)
        assert restarted.loaded[update.identifier].version == update.latest
        assert extensions.entries['test.plugin:test'].label.endswith('Updated')
        assert restarted.installed[update.identifier]['files'] == files
        assert not list(manager.storage.rglob('*.py'))
    finally:
        restarted.disable(update.identifier)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_failed_directory_swap_restores_original_before_requesting_a_new_location(update_case, monkeypatch):
    manager, _, update, data, original = update_case
    before = copy.deepcopy(manager.installed)
    rename = Path.rename

    def fail_replacement(path, target):
        if path.name == 'replacement' and Path(target) == original:
            raise PermissionError('Cannot install replacement')
        return rename(path, target)

    monkeypatch.setattr(Path, 'rename', fail_replacement)
    with pytest.raises(PluginUpdateLocationError):
        stage_update(manager, update, data)
    assert manager.installed == before
    assert json.loads((original / 'plugin.curvemole-plugin.json').read_text())['version'] == '1.0.0'
    assert not list(original.parent.glob('.curvemole-plugin-update-*'))


def test_failed_relocated_install_does_not_leave_an_unregistered_copy(update_case, tmp_path, monkeypatch):
    manager, _, update, data, original = update_case
    destination = tmp_path / 'chosen'
    destination.mkdir()
    before = copy.deepcopy(manager.installed)

    def fail():
        raise OSError('Disk full')

    monkeypatch.setattr(manager, '_save', fail)
    with pytest.raises(OSError, match='Disk full'):
        stage_update(manager, update, data, destination=destination)
    assert manager.installed == before
    assert not list(destination.iterdir())
    assert json.loads((original / 'plugin.curvemole-plugin.json').read_text())['version'] == '1.0.0'


def test_shared_plugin_folder_requires_a_user_selected_destination(update_case, tmp_path):
    manager, _, update, data, original = update_case
    other = original / 'another.curvemole-plugin.json'
    other.write_text('{"identifier":"another.plugin"}')
    with pytest.raises(PluginUpdateLocationError):
        stage_update(manager, update, data)
    assert other.read_text() == '{"identifier":"another.plugin"}'
    destination = tmp_path / 'chosen'
    destination.mkdir()
    stage_update(manager, update, data, destination=destination)
    assert Path(manager.installed[update.identifier]['reference']).parent == destination / update.folder
    assert other.exists()


def test_legacy_internal_installation_must_move_to_a_user_selected_folder(update_case, tmp_path):
    import shutil

    manager, _, update, data, original = update_case
    manager.disable(update.identifier)
    legacy = manager.storage / 'updates' / 'legacy'
    shutil.copytree(original, legacy)
    manager.load(manager.discover_local(legacy)[0], trust=True)
    before = copy.deepcopy(manager.installed)
    with pytest.raises(PluginUpdateLocationError):
        stage_update(manager, update, data)
    with pytest.raises(PluginUpdateLocationError, match='outside CurveMole'):
        stage_update(manager, update, data, destination=manager.storage)
    assert manager.installed == before
    destination = tmp_path / 'chosen'
    destination.mkdir()
    stage_update(manager, update, data, destination=destination)
    assert Path(manager.installed[update.identifier]['reference']).parent == destination / update.folder


def test_scanning_still_allows_a_newer_manually_downloaded_plugin(update_case, tmp_path):
    manager, _, update, data, original = update_case
    destination = tmp_path / 'chosen'
    destination.mkdir()
    stage_update(manager, update, data, destination=destination)
    path = original / 'plugin.curvemole-plugin.json'
    manifest = json.loads(path.read_text())
    manifest['version'] = '1.2.0'
    path.write_text(json.dumps(manifest))
    candidate = manager.discover_candidates(original)[0]
    assert candidate.metadata.version == '1.2.0'
    assert Path(candidate.reference) == path


@pytest.mark.parametrize("fault", ["checksum", "identity", "api", "disabled", "save", "truncated"])
def test_failed_update_retains_previous_installation(update_case, monkeypatch, fault):
    manager, _, update, data, original = update_case
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
    assert json.loads((original / 'plugin.curvemole-plugin.json').read_text())['version'] == '1.0.0'
    assert not (original / 'README.md').exists()


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
        destination / "by_community" / plugin.folder
    )
    assert plugin.identifier in manager.loaded
    assert "test.plugin:test" in extensions.entries


def test_catalog_categories_are_validated_and_preserve_community_author(update_case):
    _, catalog, _, _, _ = update_case
    assert community_plugins(catalog)[0].category == "by_community"
    catalog["plugins"][0]["category"] = "by_main_developer"
    assert community_plugins(catalog)[0].category == "by_main_developer"
    catalog["plugins"][0]["category"] = "by_unknown"
    with pytest.raises(CurveMoleError, match="Invalid community plugin catalog entry"):
        community_plugins(catalog)


def test_catalog_install_rejects_existing_destination(update_case, tmp_path):
    manager, catalog, _, archive, _ = update_case
    manager.disable("test.plugin")
    manager.remove("test.plugin")
    plugin = community_plugins(catalog)[0]
    (tmp_path / "by_community" / plugin.folder).mkdir(parents=True)
    with pytest.raises(CurveMoleError, match="already exists"):
        install_community_plugin(manager, plugin, archive, tmp_path)


@pytest.mark.parametrize('destination', ['', '   ', 'internal', 'internal-child'])
def test_catalog_install_rejects_implicit_or_internal_storage(
    update_case, tmp_path, monkeypatch, destination
):
    monkeypatch.chdir(tmp_path)
    manager, catalog, _, archive, _ = update_case
    manager.disable('test.plugin')
    manager.remove('test.plugin')
    if destination.startswith('internal'):
        destination = manager.storage if destination == 'internal' else manager.storage / 'plugins'
        destination.mkdir(exist_ok=True)
    with pytest.raises(CurveMoleError, match='folder'):
        install_community_plugin(manager, community_plugins(catalog)[0], archive, destination)
    assert not list(manager.storage.rglob('plugin.py'))
    assert 'test.plugin' not in manager.installed


def test_catalog_install_does_not_follow_a_category_link_to_internal_storage(update_case, tmp_path):
    manager, catalog, _, archive, _ = update_case
    manager.disable('test.plugin')
    manager.remove('test.plugin')
    destination = tmp_path / 'chosen'
    destination.mkdir()
    try:
        (destination / 'by_community').symlink_to(manager.storage, target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlinks are unavailable')
    with pytest.raises(CurveMoleError, match='inside the selected folder'):
        install_community_plugin(manager, community_plugins(catalog)[0], archive, destination)
    assert not list(manager.storage.rglob('plugin.py'))


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


@pytest.mark.parametrize('choose_folder', [True, False])
def test_controller_requests_user_storage_when_source_is_not_writable(
    controller_case, tmp_path, monkeypatch, choose_folder
):
    from PySide6.QtWidgets import QFileDialog

    _, controller, requests, catalog, update, archive = controller_case
    original = Path(controller.plugins.installed[update.identifier]['reference']).parent
    selected = tmp_path / 'user-chosen-plugins'
    selected.mkdir()
    rename = Path.rename
    choices = []

    def protected(path, target):
        if path == original:
            raise PermissionError('Original folder is not writable')
        return rename(path, target)

    def choose(*args):
        choices.append(args)
        return str(selected) if choose_folder else ''

    monkeypatch.setattr(Path, 'rename', protected)
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', choose)
    requests.pop()[1](json.dumps(catalog).encode(), '')
    controller.install_selected()
    requests.pop()[1](archive, '')
    assert len(choices) == 1
    record = controller.plugins.installed[update.identifier]
    assert record['metadata']['version'] == (update.latest if choose_folder else update.current)
    assert Path(record['reference']).parent == (selected / update.folder if choose_folder else original)
    assert not list(controller.plugins.storage.rglob('*.py'))
    assert controller.plugins.loaded[update.identifier].version == update.current
    if choose_folder:
        assert controller.settings.value('community_plugins/folder') == str(selected)
    else:
        assert 'cancelled' in controller.message
        assert not list(selected.iterdir())


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
    assert controller.catalog_table.rowCount() == 2
    assert controller.catalog_table.item(0, 0).text() == "by community"
    assert controller.catalog_table.item(1, 2).text() == "by community"
    assert controller.catalog_table.item(1, 3).text() == "Test author"
    controller.catalog_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    controller.install_catalog_selected()
    assert requests[-1][0].endswith("/test_plugin.zip")
    assert not controller.catalog_folder.isEnabled()
    assert not controller.catalog_choose.isEnabled()
    queued_requests = len(requests)
    controller.install_catalog_selected()
    assert len(requests) == queued_requests
    controller.catalog_folder.setText(str(controller.plugins.storage))
    requests[-1][1](archive, "")
    assert update.identifier in controller.plugins.loaded
    assert (destination / "by_community" / "test_plugin" / "plugin.py").is_file()
    assert "installed and loaded" in controller.catalog_status.text().lower()
    assert controller.catalog_folder.isEnabled()
    assert controller.catalog_destination is None


@pytest.mark.parametrize('destination', ['', '   ', 'internal'])
def test_catalog_controller_rejects_missing_or_internal_folder(
    controller_case, monkeypatch, destination
):
    from PySide6.QtWidgets import QMessageBox

    _, controller, requests, catalog, update, _ = controller_case
    controller.plugins.disable(update.identifier)
    controller.plugins.remove(update.identifier)
    controller.browse()
    requests.pop()[1](json.dumps(catalog).encode(), '')
    requests.clear()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    if destination == 'internal':
        destination = str(controller.plugins.storage)
    controller.catalog_folder.setText(destination)
    controller.install_catalog_selected()
    assert len(warnings) == 1
    assert not requests
    assert not controller.catalog_busy


def test_catalog_uses_saved_plugin_manager_folder(controller_case, tmp_path):
    _, controller, _, _, _, _ = controller_case
    controller.settings.setValue('plugin_directory', str(tmp_path))
    controller.browse()
    assert controller.catalog_folder.text() == str(tmp_path)


def test_catalog_uses_current_plugin_manager_folder(controller_case, tmp_path):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QPushButton

    from curvemole.gui.dialogs import PluginManagerDialog

    _, controller, _, _, _, _ = controller_case
    controller.window.plugin_update_controller = controller
    controller.settings.setValue('community_plugins/folder', str(controller.plugins.storage))
    dialog = PluginManagerDialog(controller.plugins, tmp_path, controller.window)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    observed = []

    def inspect():
        observed.append(controller.catalog_folder.text())
        controller.catalog_dialog.accept()

    QTimer.singleShot(0, inspect)
    button = next(button for button in dialog.findChildren(QPushButton)
                  if button.text() == 'Browse validated plugins…')
    button.click()
    assert observed == [str(tmp_path)]
    dialog.close()


def test_catalog_groups_developer_and_community_plugins(controller_case):
    _, controller, requests, catalog, _, _ = controller_case
    developer = dict(catalog["plugins"][0], identifier="developer.plugin",
                     name="Developer plugin", category="by_main_developer")
    catalog["plugins"].append(developer)
    controller.browse()
    requests[-1][1](json.dumps(catalog).encode(), "")
    assert controller.catalog_table.rowCount() == 4
    assert controller.catalog_table.item(0, 0).text() == "by main developer"
    assert controller.catalog_table.item(1, 1).text() == "Developer plugin"
    assert controller.catalog_table.item(2, 0).text() == "by community"
    assert controller.catalog_table.item(3, 3).text() == "Test author"


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
        item = controller.catalog_table.item(1, 0)
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
