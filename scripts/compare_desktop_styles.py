"""Capture the current desktop style and Fusion on the actual host platform.

Each style runs in a fresh process with isolated preferences. Unlike the README
screenshot generator, this keeps the platform font and its native Qt backend.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def capture(style: str, output: Path, profile: Path) -> None:
    os.environ["CURVEMOLE_DISABLE_UPDATE_CHECK"] = "1"
    os.environ["CURVEMOLE_DISABLE_PLUGINS"] = "1"
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[key] = str(profile / key)
    os.environ["MPLCONFIGDIR"] = str(profile / "matplotlib")

    from generate_screenshots import build_example_project
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QCoreApplication, QLocale, QSettings, Qt, qVersion
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QStyleFactory

    from curvemole.gui.app import create_main_window
    from curvemole.version import __version__

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(profile))
    QLocale.setDefault(QLocale.c())
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["curvemole-style-comparison"])
    QCoreApplication.setOrganizationName("CurveMole style comparison")
    QCoreApplication.setApplicationName("CurveMole style comparison")
    default_style = app.style().objectName()
    if style == "fusion" and (app.setStyle("Fusion") is None or app.style().objectName().lower() != "fusion"):
        raise RuntimeError("Fusion could not be selected")
    # CurveMole's tooltip stylesheet later wraps this in QStyleSheetStyle, whose
    # objectName is empty. Record the selected platform style before that wrapper.
    selected_style = app.style().objectName()
    backend = app.platformName()
    expected_backend = {"Windows": "windows", "Darwin": "cocoa", "Linux": "xcb"}[platform.system()]
    if backend != expected_backend:
        raise RuntimeError(f"Expected native backend {expected_backend}, got {backend}")

    project, selected_peak_id = build_example_project()
    window = create_main_window(project)
    window.autosave_timer.stop()
    window.reset_layout()
    window.setFixedSize(1440, 900)
    window.selected_component_id = selected_peak_id
    window.refresh_all()
    window.plot_workspace.plot.getAxis("bottom").enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis("bottom").enableAutoSIPrefix(False)
    window.plot_workspace.residual_plot.getAxis("left").enableAutoSIPrefix(False)
    window.show()
    output.mkdir(parents=True, exist_ok=True)
    themes = {}
    try:
        for theme in ("light", "dark"):
            window.apply_theme(theme)
            window.statusBar().showMessage("Fit completed · Gaussian + Lorentzian peaks with linear background")
            window.plot_workspace.auto_range()
            QTest.qWait(750)
            app.processEvents()
            pixmap = window.grab()
            filename = f"{style}-{theme}.png"
            if pixmap.isNull() or not pixmap.save(str(output / filename), "PNG"):
                raise RuntimeError(f"Could not capture {filename}")
            themes[theme] = {
                "file": filename,
                "font": app.font().toString(),
                "logical_size": [window.width(), window.height()],
                "pixel_size": [pixmap.width(), pixmap.height()],
                "device_pixel_ratio": pixmap.devicePixelRatio(),
                "window_colour": app.palette().window().color().name(),
            }
        metadata = {
            "platform": platform.platform(),
            "runner": os.environ.get("RUNNER_OS"),
            "runner_image": os.environ.get("CURVEMOLE_SCREENSHOT_RUNNER"),
            "source_sha": os.environ.get("GITHUB_SHA"),
            "curvemole": __version__,
            "qt": qVersion(),
            "pyside": pyside_version,
            "backend": backend,
            "requested_style": style,
            "default_style": default_style,
            "actual_style": selected_style,
            "available_styles": QStyleFactory.keys(),
            "themes": themes,
        }
        (output / f"{style}-environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(json.dumps(metadata, indent=2), flush=True)
    finally:
        project.dirty = False
        window.close()
        app.processEvents()


def comparisons(output: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    current = json.loads((output / "current-environment.json").read_text(encoding="utf-8"))
    fusion = json.loads((output / "fusion-environment.json").read_text(encoding="utf-8"))
    if current["backend"] != fusion["backend"] or current["source_sha"] != fusion["source_sha"]:
        raise RuntimeError("The captures do not describe the same source and native backend")
    for theme in ("light", "dark"):
        if current["themes"][theme]["font"] != fusion["themes"][theme]["font"]:
            raise RuntimeError("Fusion unexpectedly changed the platform font")
        images = [Image.open(output / f"{style}-{theme}.png").convert("RGB") for style in ("current", "fusion")]
        # Keep source pixels intact; allow a host's native backing-store DPI.
        widths = [image.width for image in images]
        header = 76
        combined = Image.new("RGB", (sum(widths), max(image.height for image in images) + header), "#e9edf2")
        draw = ImageDraw.Draw(combined)
        font = ImageFont.load_default(size=22)
        small = ImageFont.load_default(size=16)
        offset = 0
        for image, title in zip(images, (f"Current - {current['actual_style']}", f"Fusion - {fusion['actual_style']}"), strict=True):
            draw.text((offset + 18, 10), title, fill="#172735", font=font)
            draw.text((offset + 18, 42), f"{platform.system()} | {theme} | native font | Qt {current['qt']}", fill="#43546a", font=small)
            combined.paste(image, (offset, header))
            offset += image.width
        combined.save(output / f"comparison-{theme}.png")
    (output / "README.txt").write_text(
        "CurveMole: current style versus Fusion\n\n"
        f"Host: {current['platform']}\n"
        f"Runner image: {current['runner_image']}\n"
        f"Source: {current['source_sha']}\n"
        f"Qt backend: {current['backend']}\n"
        f"Current style: {current['actual_style']}; Fusion: {fusion['actual_style']}\n\n"
        "Open comparison-light.png and comparison-dark.png for side-by-side views.\n"
        "Each pair uses the same fitted data, logical window size and platform font.\n"
        "The only style change is QApplication.setStyle('Fusion').\n"
        "Light and dark are CurveMole's existing theme implementations.\n"
        "These are real QWidget captures on each host's native Qt backend, not mockups.\n"
        "They show window contents, without OS title bars or the macOS global menu.\n"
        "Windows Server/macOS/Ubuntu runner defaults can differ from your own desktop.\n"
        "Linux uses Xvfb/X11 and its default Qt style, without a desktop theme plugin.\n"
        "Original PNGs and environment JSON files are included.\n"
        "No application changes, releases, prereleases or beta version stamping.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", choices=("current", "fusion"))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.capture:
        with tempfile.TemporaryDirectory(prefix="curvemole-style-profile-") as directory:
            capture(args.capture, output, Path(directory))
    else:
        environment = os.environ.copy()
        # Never inherit a style override into the current/default-style capture.
        for key in ("QT_STYLE_OVERRIDE", "QT_QPA_PLATFORMTHEME"):
            environment.pop(key, None)
        environment["QT_SCALE_FACTOR"] = "1"
        environment["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
        for style in ("current", "fusion"):
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--output", str(output), "--capture", style],
                env=environment, check=True, timeout=90,
            )
        comparisons(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
