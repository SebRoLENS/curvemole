from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

from curvemole.core.release_channels import ReleaseVersion, default_channel, select_release

ROOT = Path(__file__).resolve().parents[1]


def release(version, *, prerelease=False, draft=False):
    return {"tag_name": version, "prerelease": prerelease, "draft": draft, "assets": []}


def test_beta_versions_are_ordered_numerically_and_before_the_matching_stable():
    versions = ["1.0.1", "1.0.2b1", "v1.0.2-beta.2", "1.0.2b10", "1.0.2", "1.1.0b1"]
    parsed = [ReleaseVersion.parse(version) for version in versions]
    assert all(version is not None for version in parsed)
    assert sorted(parsed) == parsed
    assert parsed[1] == ReleaseVersion.parse("v1.0.2-beta.1")
    assert parsed[1].label == "1.0.2 Beta 1"
    assert parsed[1].text == "1.0.2-beta.1"


@pytest.mark.parametrize("version", ["", "1.0", "bad", "1.0.1-rc.1", "1.0.1garbage", "1.0.2b"])
def test_unsupported_versions_are_not_offered(version):
    assert ReleaseVersion.parse(version) is None


def test_stable_never_selects_a_beta_even_if_github_metadata_is_wrong():
    stable = release("v1.0.1")
    candidates = [release("v1.0.2-beta.1"), release("v2.0.0", prerelease=True),
                  release("v3.0.0", draft=True), stable]
    assert select_release(candidates, "stable") is stable
    assert select_release(candidates, "beta")["tag_name"] == "v1.0.2-beta.1"
    assert select_release(candidates[:-1], "stable") is None


def test_beta_channel_follows_newest_stable_or_beta_not_api_order():
    stable = release("v1.0.2")
    candidates = [release("v1.0.2-beta.10", prerelease=True), stable,
                  release("v1.0.2-beta.2", prerelease=True)]
    assert select_release(candidates, "beta") is stable
    candidates.append(release("v1.1.0-beta.1", prerelease=True))
    assert select_release(candidates, "beta")["tag_name"] == "v1.1.0-beta.1"
    assert default_channel("1.0.2b1") == "beta"
    assert default_channel("1.0.2") == "stable"


@pytest.fixture
def controller(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QMainWindow

    from curvemole.gui import updates

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "channel.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(updates, "QSettings", lambda *args: settings)
    monkeypatch.setattr(updates, "__version__", "1.0.2b2")
    window = QMainWindow()
    window.update_action = QAction(window)
    window.update_action.triggered.connect(lambda: None)
    window._log = lambda message: None
    window._notify = lambda message: None
    instance = updates.UpdateController(window)
    yield instance
    instance.timer.stop()
    window.close()
    window.deleteLater()
    app.processEvents()


class Reply:
    def __init__(self, payload):
        self.payload = payload
        self.deleted = False

    def error(self):
        from PySide6.QtNetwork import QNetworkReply
        return QNetworkReply.NetworkError.NoError

    def readAll(self):
        return json.dumps(self.payload).encode()

    def deleteLater(self):
        self.deleted = True


def test_channel_choice_persists_and_can_be_reversed_without_relabeling_installed_beta(controller, monkeypatch):
    assert controller.channel == "beta"
    assert "Beta 2" in controller.badge.text()
    calls = []
    monkeypatch.setattr(controller, "check", lambda **kwargs: calls.append(controller.channel))
    controller._latest_payload = release("v1.0.2-beta.9", prerelease=True)
    controller._latest_version = ReleaseVersion.parse("1.0.2b9")
    controller.set_channel("stable")
    assert controller.settings.value("updates/channel") == "stable"
    assert controller._latest_payload is None and controller._latest_version is None
    assert "Beta 2" in controller.badge.text()
    controller.set_channel("beta")
    assert controller.settings.value("updates/channel") == "beta"
    assert calls == ["stable", "beta"]


def test_stable_choice_waits_without_downgrading_and_accepts_matching_final(controller, monkeypatch):
    controller.set_channel("stable")
    shown = []
    monkeypatch.setattr(controller, "_show_update_available", lambda payload, version, kind: shown.append(version))
    monkeypatch.setattr(controller, "_offer_windows_installer", lambda *args: None)
    controller._release_finished(Reply(release("v1.0.1")), False)
    assert shown == []
    assert "No downgrade" in controller.badge.toolTip()
    controller._release_finished(Reply(release("v1.0.2")), False)
    assert shown == ["1.0.2"]


def test_beta_sequence_updates_and_notifications_are_separate_per_channel(controller, monkeypatch):
    shown = []
    monkeypatch.setattr(controller, "_show_update_available", lambda payload, version, kind: shown.append(version))
    candidate = release("v1.0.2-beta.10", prerelease=True)
    controller._release_finished(Reply([candidate]), False)
    controller._release_finished(Reply([candidate]), False)
    assert shown == ["1.0.2-beta.10"]
    assert controller.settings.value("updates/beta/notified_version") == "1.0.2-beta.10"
    assert controller.settings.value("updates/stable/notified_version") is None


def test_late_reply_from_previous_channel_cannot_offer_wrong_release(controller, monkeypatch):
    controller.set_channel("stable")
    shown = []
    monkeypatch.setattr(controller, "_show_update_available", lambda *args: shown.append(args))
    reply = Reply([release("v1.0.2-beta.99", prerelease=True)])
    controller._release_finished(reply, True, "beta")
    assert shown == [] and reply.deleted
    assert controller._latest_payload is None


def test_channel_cannot_change_during_download(controller):
    controller._download_reply = object()
    with pytest.raises(RuntimeError, match="download"):
        controller.set_channel("stable")
    assert controller.channel == "beta"
    controller._download_reply = None


def test_channel_dialog_keeps_selection_local_until_accepted(controller):
    from curvemole.gui.update_channel_dialog import UpdateChannelDialog

    dialog = UpdateChannelDialog("stable", controller.window)
    dialog.beta.setChecked(True)
    assert dialog.selected_channel() == "beta"
    dialog.reject()
    assert controller.settings.value("updates/channel") == "beta"


def test_beta_preference_survives_installing_a_final_package(controller, monkeypatch):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMainWindow

    from curvemole.gui import updates

    monkeypatch.setattr(updates, "__version__", "1.0.2")
    window = QMainWindow()
    window.update_action = QAction(window)
    window.update_action.triggered.connect(lambda: None)
    next_controller = updates.UpdateController(window)
    assert next_controller.channel == "beta"
    assert "Beta" not in next_controller.badge.text()
    next_controller.timer.stop()
    window.close()
    window.deleteLater()


def beta_script():
    spec = importlib.util.spec_from_file_location("beta_release_test", ROOT / ".github/scripts/beta_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_beta_stamping_preserves_dependencies_and_does_not_mutate_stable_metadata(tmp_path):
    beta = beta_script()
    for name in ("src/curvemole/version.py", "pyproject.toml", "uv.lock"):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    original_lock = tomllib.loads((tmp_path / "uv.lock").read_text())
    assert beta.beta_version("1.0.1", "10") == "1.0.2b10"
    beta.stamp("1.0.2b10", tmp_path)
    assert '__version__ = "1.0.2b10"' in (tmp_path / "src/curvemole/version.py").read_text()
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == "1.0.2b10"
    updated_lock = tomllib.loads((tmp_path / "uv.lock").read_text())
    for package in original_lock["package"]:
        if package["name"] == "curvemole":
            package["version"] = "1.0.2b10"
    assert original_lock == updated_lock
    with pytest.raises(ValueError):
        beta.stamp("1.0.2", tmp_path)


@pytest.mark.parametrize("corrupt_upload", [False, True])
def test_beta_publication_checks_all_assets_and_never_sets_latest(tmp_path, monkeypatch, corrupt_upload):
    from types import SimpleNamespace

    beta = beta_script()
    version = "1.0.2b1"
    for name in beta.expected_assets(version):
        (tmp_path / name).write_bytes(b"package")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/example")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["release", "view"]:
            return SimpleNamespace(returncode=1, stderr="release not found")
        return SimpleNamespace(returncode=0)

    def response(command, **kwargs):
        import hashlib
        assets = [{"name": name, "size": path.stat().st_size, "state": "uploaded",
                   "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}
                  for name, path in ((p.name, p) for p in tmp_path.iterdir())
                  if name != "beta-notes.md"]
        if corrupt_upload:
            assets[0]["digest"] = "sha256:bad"
        return json.dumps([{"tag_name": "v1.0.2-beta.1", "assets": assets}])

    monkeypatch.setattr(beta.subprocess, "run", run)
    monkeypatch.setattr(beta.subprocess, "check_output", response)
    if corrupt_upload:
        with pytest.raises(ValueError, match="checksum"):
            beta.publish(version, tmp_path)
        assert not any(command[1:3] == ["release", "edit"] for command in commands)
    else:
        beta.publish(version, tmp_path)
        publish = next(command for command in commands if command[1:3] == ["release", "edit"])
        assert "--prerelease" in publish and "--latest=false" in publish
    assert not any("--latest" in command or "--prerelease=false" in command for command in commands)


def test_bootstrap_is_artifacts_only_and_testing_cannot_publish_stable():
    import yaml

    workflow = yaml.load((ROOT / ".github/workflows/testing.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["push"]["branches"] == ["testing"]
    assert workflow["on"]["workflow_dispatch"]["inputs"]["publish"]["default"] == "false"
    assert "[beta artifacts only]" in workflow["jobs"]["publish"]["if"]
    assert workflow["jobs"]["plan"]["if"] == "github.ref == 'refs/heads/testing'"
    assert "automatic-release.yml" not in (ROOT / ".github/workflows/testing.yml").read_text()


def test_beta_plan_runs_before_installing_project_dependencies(tmp_path, monkeypatch):
    import sys

    script = beta_script()
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "2")
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["beta_release.py", "plan"])
    script.main()
    assert output.read_text() == "version=1.0.2b2\n"
