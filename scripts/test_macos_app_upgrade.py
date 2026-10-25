"""Build two DMGs and test replacing an installed app on an isolated Mac runner.

Both builds contain the same test-only event-loop probe. Release sources are
restored after building; this does not add instrumentation to shipped apps.
Apple signing/notarization and quarantine are deliberately outside this test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

PROBE = '''
    def upgrade_test_probe():
        import json
        from PySide6.QtCore import QSettings
        settings = QSettings("CurveMole", "CurveMole")
        stage = os.environ["CURVEMOLE_UPGRADE_STAGE"]
        if stage == "baseline":
            settings.setValue("upgrade_test/sentinel", "keep-this-setting")
            settings.sync()
        record = {
            "stage": stage,
            "setting": settings.value("upgrade_test/sentinel"),
            "project": window.project.name,
            "curves": [{"name": c.name, "x": c.x.tolist(), "y": c.y.tolist()}
                       for c in window.project.curves],
            "visible": window.isVisible(),
        }
        Path(os.environ["CURVEMOLE_UPGRADE_REPORT"]).write_text(json.dumps(record))
    QTimer.singleShot(0, upgrade_test_probe)
'''


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, timeout=900, **kwargs)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, env: dict[str, str], dmg: Path) -> None:
    icon = root / 'generated-icons' / 'curvemole.icns'
    icon.parent.mkdir(exist_ok=True)
    run(sys.executable, '-c',
        "from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2])",
        str(root / 'src/curvemole/resources/curvemole.png'), str(icon))
    build_env = dict(env, CURVEMOLE_ICON=str(icon), CURVEMOLE_ONEFILE='0')
    entry = root / 'src/curvemole/gui/app.py'
    original = entry.read_text()
    anchor = '    window.show()\n'
    assert original.count(anchor) == 1, 'Desktop entry point changed; review test probe'
    try:
        entry.write_text(original.replace(anchor, anchor + PROBE))
        run(sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
            'packaging/curvemole.spec', cwd=root, env=build_env)
    finally:
        entry.write_text(original)
    run('bash', 'packaging/macos/package_and_notarize.sh',
        str(root / 'dist/CurveMole.app'), str(dmg), 'CurveMole Upgrade Test',
        cwd=root, env=env)


def install(dmg: Path, destination: Path) -> None:
    mounted = run('hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(dmg),
                  capture_output=True)
    entities = plistlib.loads(mounted.stdout)['system-entities']
    mount = next(Path(item['mount-point']) for item in entities if 'mount-point' in item)
    try:
        # Finder's Replace operation replaces the app bundle, not user data.
        if destination.exists():
            shutil.rmtree(destination)
        run('ditto', str(mount / 'CurveMole.app'), str(destination))
    finally:
        run('hdiutil', 'detach', str(mount))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This integration test requires a disposable macOS runner')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', CURVEMOLE_SMOKE_TEST='1',
               CURVEMOLE_PACKAGING_SMOKE='1', MPLCONFIGDIR=str(work / 'matplotlib'))
    # These tests never require repository signing credentials.
    for key in ('MACOS_CERTIFICATE', 'MACOS_CERTIFICATE_PASSWORD', 'APPLE_ID',
                'APPLE_APP_SPECIFIC_PASSWORD', 'APPLE_TEAM_ID'):
        env.pop(key, None)
    project = work / 'existing project.fitproj'
    run(sys.executable, '-c', '''
import sys
sys.path.insert(0, sys.argv[1])
from curvemole import Curve, Project
from curvemole.core.serialization import save_project
p = Project("Existing upgrade project")
p.add_curve(Curve("preserved curve", [1., 2., 3.], [4., 7., 5.]))
save_project(p, sys.argv[2])
''', str(baseline / 'src'), str(project), env=env)
    project_digest = digest(project)
    application = work / 'Applications' / 'CurveMole.app'
    application.parent.mkdir()
    reports = []
    old_executable_digest = None
    for stage, root in [('baseline', baseline), ('candidate', candidate)]:
        dmg = work / (stage + '.dmg')
        build(root, env, dmg)
        install(dmg, application)
        executable = application / 'Contents/MacOS/CurveMole'
        current_digest = digest(executable)
        if stage == 'baseline':
            old_executable_digest = current_digest
        else:
            assert current_digest != old_executable_digest, 'App executable was not replaced'
        report_path = work / (stage + '-probe.json')
        probe_env = dict(env, CURVEMOLE_UPGRADE_STAGE=stage,
                         CURVEMOLE_UPGRADE_REPORT=str(report_path))
        run(str(executable), str(project), env=probe_env)
        record = json.loads(report_path.read_text())
        assert record['stage'] == stage
        assert record['setting'] == 'keep-this-setting', record
        assert record['project'] == 'Existing upgrade project', record
        assert record['curves'] == [{'name': 'preserved curve',
                                    'x': [1., 2., 3.], 'y': [4., 7., 5.]}], record
        assert record['visible'], record
        assert digest(project) == project_digest, 'Existing project was modified'
        reports.append(record)
    result = {'passed': True, 'architecture': os.uname().machine,
              'project_sha256': project_digest, 'launches': reports,
              'limitations': 'Test-instrumented, unsigned apps; no Gatekeeper/quarantine test.'}
    output = candidate / 'macos-upgrade.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
