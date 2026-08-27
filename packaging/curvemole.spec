# PyInstaller specification for native CurveMole onedir bundles.
import os
import re
from pathlib import Path
import sys

root = Path(SPEC).resolve().parents[1]
version_text = (root / "src" / "curvemole" / "version.py").read_text(encoding="utf-8")
version = re.search(r'^__version__\s*=\s*"([^"]+)"', version_text, re.M).group(1)
icon = Path(os.environ.get(
    "CURVEMOLE_ICON",
    root / "src" / "curvemole" / "resources" / "curvemole.png",
))
datas = [
    # Bundle the directory rather than an icon allow-list so future resources
    # are automatically present in every frozen desktop application.
    (str(root / "src" / "curvemole" / "resources"), "curvemole/resources"),
    (str(root / "docs"), "curvemole/resources/docs"),
]

a = Analysis(
    [str(root / "src" / "curvemole" / "gui" / "app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "scipy.special._ufuncs_cxx",
        "scipy.optimize",
        "scipy.signal",
        "scipy.interpolate",
        "pandas",
        "matplotlib.backends.backend_agg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CurveMole",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon),
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="CurveMole",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="CurveMole.app",
        icon=str(icon),
        bundle_identifier="it.unifi.lens.curvemole",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
        },
    )
