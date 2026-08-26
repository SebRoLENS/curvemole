from __future__ import annotations

from curvemole.gui.external import host_environment


def test_host_environment_removes_appimage_and_bundled_library_paths() -> None:
    environment = host_environment(
        {
            "PATH": "/usr/bin",
            "LD_LIBRARY_PATH": "/tmp/.mount_CurveMole/usr/lib/curvemole/_internal",
            "LD_LIBRARY_PATH_ORIG": "/usr/local/lib",
            "QT_PLUGIN_PATH": "/tmp/.mount_CurveMole/qt/plugins",
            "APPIMAGE": "/tmp/CurveMole.AppImage",
        }
    )

    assert environment["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in environment
    assert "QT_PLUGIN_PATH" not in environment
    assert "APPIMAGE" not in environment


def test_host_environment_removes_library_path_without_original() -> None:
    environment = host_environment({"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/bundled"})
    assert "LD_LIBRARY_PATH" not in environment
