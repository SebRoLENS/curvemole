from __future__ import annotations

import stat
from pathlib import Path

from curvemole.gui.app import _open_paths
from curvemole.gui.desktop_integration import (
    integrate_linux_desktop,
    linux_integration_is_current,
)


def _file(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


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
    assert linux_integration_is_current(data_home=data)

    repeated = integrate_linux_desktop(
        appimage=result.appimage,
        icon_source=icon,
        home=home,
        data_home=data,
        refresh_databases=False,
    )
    assert repeated.adopted_existing_launcher
    assert repeated.backup_file is None


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
    assert result.appimage == source
    assert result.backup_file is not None and result.backup_file.is_file()
    assert f"Exec={launcher} %f" in desktop.read_text(encoding="utf-8")
    assert not (tmp_path / "home" / ".local" / "opt" / "CurveMole").exists()


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
