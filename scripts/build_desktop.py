"""Build and smoke-test the native PyInstaller bundle on the current OS."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    distribution = root / "dist"
    build = root / "build"
    for directory in (distribution, build):
        if directory.exists():
            shutil.rmtree(directory)
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment.setdefault("MPLCONFIGDIR", str(build / "matplotlib"))
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/curvemole.spec"],
        cwd=root,
        env=environment,
        check=True,
    )
    executable = distribution / "CurveMole" / ("CurveMole.exe" if os.name == "nt" else "CurveMole")
    if sys.platform == "darwin":
        executable = distribution / "CurveMole.app" / "Contents" / "MacOS" / "CurveMole"
    if not executable.exists():
        raise SystemExit(f"Bundle executable was not created: {executable}")
    environment["CURVEMOLE_SMOKE_TEST"] = "1"
    # A fresh macOS runner may spend over 20 seconds creating Matplotlib's font
    # cache before CurveMole reaches its smoke-test exit path.  Leave enough
    # headroom for slower Intel runners while still detecting a hung bundle.
    subprocess.run([str(executable)], env=environment, timeout=90, check=True)
    print(distribution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
