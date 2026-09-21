from __future__ import annotations

import platform
import stat
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Project
from curvemole.gui import app as app_module
from curvemole.gui.app import CurveMoleMainWindow, NativeFileOpenFilter, _open_paths
from curvemole.gui.desktop_integration import (
    integrate_linux_desktop,
    linux_integration_is_current,
)


def _file(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux desktop integration")
def test_linux_integration_installs_stable_appimage_and_is_idempotent(tmp_path: Path) -> None:
    source = _file(tmp_path / "downloads" / "CurveMole-1.2.3.AppImage")
    icon = _file(tmp_path / "curvemole.png", "png")
    home = tmp_path / "home"
    data = home / ".local" / "share"

    result = integrate_linux_desktop(
        appimage=source,
        icon_source=icon,
        home=home,
        data_home=data,
        refresh_databases=False,
    )

    assert result.appimage == home / ".local" / "opt" / "CurveMole" / "CurveMole.AppImage"
    assert result.appimage.read_text(encoding="utf-8") == "data"
    assert result.appimage.stat().st_mode & stat.S_IXUSR
    desktop = result.desktop_file.read_text(encoding="utf-8")
    assert f'Exec="{result.appimage}" %f' in desktop
    assert "MimeType=application/x-curvemole-project;" in desktop
    assert result.mime_file.is_file()
    assert result.icon_file.is_file()
    assert linux_integration_is_current(data_home=data, home=home)

    repeated = integrate_linux_desktop(
        appimage=result.appimage,
        icon_source=icon,
        home=home,
        data_home=data,
        refresh_databases=False,
    )
    assert repeated.adopted_existing_launcher
    assert repeated.backup_file is None


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux desktop integration")
def test_linux_integration_adopts_and_backs_up_manual_launcher(tmp_path: Path) -> None:
    source = _file(tmp_path / "opt" / "CurveMole.AppImage")
    launcher = _file(tmp_path / "bin" / "curvemole", "#!/bin/sh\n")
    launcher.chmod(0o755)
    icon = _file(tmp_path / "curvemole.png", "png")
    data = tmp_path / "data"
    desktop = _file(
        data / "applications" / "curvemole.desktop",
        f"[Desktop Entry]\nName=CurveMole\nExec={launcher}\n",
    )

    result = integrate_linux_desktop(
        appimage=source,
        icon_source=icon,
        home=tmp_path / "home",
        data_home=data,
        refresh_databases=False,
    )

    assert result.adopted_existing_launcher
    assert result.appimage == tmp_path / "home" / ".local" / "opt" / "CurveMole" / "CurveMole.AppImage"
    assert result.appimage.read_text(encoding="utf-8") == "data"
    assert result.backup_file is not None and result.backup_file.is_file()
    assert f'Exec="{result.appimage}" %f' in desktop.read_text(encoding="utf-8")
    assert launcher.read_text(encoding="utf-8") == "#!/bin/sh\n"
    assert linux_integration_is_current(data_home=data, home=tmp_path / "home")


def test_open_paths_opens_project_and_imports_data(tmp_path: Path) -> None:
    project = _file(tmp_path / "experiment.fitproj")
    first = _file(tmp_path / "first.csv")
    second = _file(tmp_path / "second.dat")

    class Window:
        def __init__(self) -> None:
            self.project = None
            self.data: list[str] = []

        def open_project(self, path: Path) -> None:
            self.project = path

        def import_data(self, paths: list[str]) -> None:
            self.data = paths

    window = Window()
    _open_paths(window, [str(project), str(first), str(second), str(tmp_path / "missing")])

    assert window.project == project
    assert window.data == [str(first), str(second)]


def test_native_file_open_filter_queues_events_until_window_is_ready(tmp_path: Path) -> None:
    project = _file(tmp_path / "experiment.fitproj")
    file_filter = NativeFileOpenFilter()

    assert file_filter.eventFilter(QObject(), QFileOpenEvent(str(project)))

    opened: list[str] = []
    file_filter.set_file_open_handler(opened.append)

    assert opened == [str(project)]


def test_accepting_desktop_integration_prompt_records_choice_and_integrates(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow(Project())
    window.settings = QSettings(str(tmp_path / "prompt.ini"), QSettings.Format.IniFormat)
    integrated = []
    monkeypatch.setattr(window, "integrate_linux_desktop", lambda: integrated.append(True))

    class FakeMessageBox:
        Icon = QMessageBox.Icon
        ButtonRole = QMessageBox.ButtonRole

        def __init__(self, parent):
            self.accepted = object()

        def setWindowTitle(self, title):
            pass

        def setIcon(self, icon):
            pass

        def setText(self, text):
            pass

        def addButton(self, text, role):
            return self.accepted if role == QMessageBox.ButtonRole.AcceptRole else object()

        def exec(self):
            pass

        def clickedButton(self):
            return self.accepted

    monkeypatch.setattr(app_module, "QMessageBox", FakeMessageBox)

    window._offer_linux_desktop_integration()

    assert integrated == [True]
    assert window.settings.value(
        "desktop/linux_integration_prompted_v2", False, type=bool
    )
    window.project.dirty = False
    window.close()
    app.processEvents()
