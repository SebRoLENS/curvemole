"""Exercise Windows installer/portable and Linux AppImage upgrades with real data.

Uses the same frozen event-loop probe as the macOS migration test. Network
download and modal confirmations are bypassed; the old app's installation code
and Windows detached PowerShell helper are executed, not simulated.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from test_macos_app_upgrade import PROBE, digest, run

UPDATE_PROBE = PROBE.replace(
    '"stage": stage,', '"stage": stage, "pid": os.getpid(),',
).replace(
    '        import json\n',
    '''        import json
        project_path = os.environ.get("CURVEMOLE_UPGRADE_PROJECT")
        if project_path and window.project.path != Path(project_path):
            window.open_project(project_path)
''',
).replace(
    '    QTimer.singleShot(0, upgrade_test_probe)',
    '''    if os.environ.get("CURVEMOLE_UPGRADE_STAGE"):
        QTimer.singleShot(0, upgrade_test_probe)''',
).replace(
    '        Path(os.environ["CURVEMOLE_UPGRADE_REPORT"]).write_text(json.dumps(record))',
    '''        report = Path(os.environ["CURVEMOLE_UPGRADE_REPORT"])
        temporary_report = report.with_suffix(".tmp")
        temporary_report.write_text(json.dumps(record))
        os.replace(temporary_report, report)
        payload = os.environ.pop("CURVEMOLE_UPGRADE_PAYLOAD", "")
        if payload:
            from curvemole.gui.updates import ReleaseAsset
            # A portable updater restarts the candidate without command-line args.
            os.environ["CURVEMOLE_UPGRADE_STAGE"] = "candidate"
            os.environ["CURVEMOLE_UPGRADE_REPORT"] = os.environ["CURVEMOLE_UPGRADE_NEXT_REPORT"]
            QMessageBox.information = lambda *args, **kwargs: QMessageBox.StandardButton.Ok
            window._confirm_discard_or_save = lambda: True
            asset = ReleaseAsset(os.environ["CURVEMOLE_UPGRADE_ASSET"], "https://example.invalid/local-test")
            window._release_update_controller._install_download(Path(payload), asset, "999.0.0")''',
)


def build(root: Path, env: dict[str, str], *, onefile: bool) -> Path:
    windows = sys.platform == 'win32'
    extension = 'ico' if windows else 'png'
    icon = root / 'generated-icons' / ('curvemole.' + extension)
    icon.parent.mkdir(exist_ok=True)
    run(sys.executable, '-c',
        "from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2])",
        str(root / 'src/curvemole/resources/curvemole.png'), str(icon))
    entry = root / 'src/curvemole/gui/app.py'
    source = entry.read_text()
    anchor = '    window.show()\n'
    assert source.count(anchor) == 1
    try:
        entry.write_text(source.replace(anchor, anchor + UPDATE_PROBE))
        run(sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
            'packaging/curvemole.spec', cwd=root,
            env=dict(env, CURVEMOLE_ICON=str(icon), CURVEMOLE_ONEFILE=str(int(onefile))))
    finally:
        entry.write_text(source)
    return root / 'dist' / ('CurveMole.exe' if onefile else 'CurveMole')


def assert_report(path: Path, stage: str) -> dict:
    record = json.loads(path.read_text())
    assert record['stage'] == stage, record
    assert record['setting'] == 'keep-this-setting', record
    assert record['project'] == 'Existing upgrade project', record
    assert record['curves'] == [{'name': 'preserved curve', 'x': [1., 2., 3.],
                                'y': [4., 7., 5.]}], record
    assert record['visible'], record
    return record


def wait_for_report(path: Path) -> None:
    deadline = time.monotonic() + 300
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.25)
    assert path.is_file(), f'Updated app did not produce a report: {path}'


def wait_windows() -> None:
    run('powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "Get-Process -Name CurveMole* -ErrorAction SilentlyContinue | Wait-Process -Timeout 300")


def fixture(baseline: Path, work: Path, env: dict[str, str]) -> Path:
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
    return project


def updater_case(kind: str, old: Path, new: Path, work: Path, project: Path,
                 env: dict[str, str], *, canonical: bool) -> dict:
    case = work / (kind + ('-canonical' if canonical else '-versioned'))
    case.mkdir()
    windows = kind == 'portable'
    suffix = '-windows-x86_64.exe' if windows else '-linux-x86_64.AppImage'
    filename = ('CurveMole.exe' if windows else 'CurveMole.AppImage') if canonical else 'CurveMole-0.0.1' + suffix
    current = case / filename
    shutil.copy2(old, current)
    current.chmod(current.stat().st_mode | 0o111)
    payload = case / 'download.part'
    if windows:
        asset = 'CurveMole-999.0.0-windows-x86_64-portable.zip'
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(new, 'CurveMole.exe')
    else:
        asset = 'CurveMole-999.0.0' + suffix
        shutil.copy2(new, payload)
    destination = current if canonical else case / ('CurveMole-999.0.0' + suffix)
    before, after = case / 'baseline.json', case / 'candidate.json'
    project_hash = digest(project)
    test_env = dict(env, CURVEMOLE_UPGRADE_STAGE='baseline',
                    CURVEMOLE_UPGRADE_REPORT=str(before),
                    CURVEMOLE_UPGRADE_NEXT_REPORT=str(after),
                    CURVEMOLE_UPGRADE_PAYLOAD=str(payload),
                    CURVEMOLE_UPGRADE_ASSET=asset,
                    CURVEMOLE_UPGRADE_PROJECT=str(project))
    run(str(current), str(project), env=test_env)
    if windows:
        # The real helper waits for the old bootloader and restarts the new app.
        try:
            wait_for_report(after)
        except AssertionError:
            baseline_record = assert_report(before, 'baseline')
            helper_log = Path(tempfile.gettempdir()) / f"CurveMole-update-{baseline_record['pid']}.log"
            diagnostic = {
                'kind': case.name, 'passed': False, 'baseline': baseline_record,
                'error': 'Automatic restart did not produce a candidate report',
                'helper_log': helper_log.read_text(encoding='utf-8-sig', errors='replace')
                if helper_log.exists() else 'No helper log',
                'candidate_installed': destination.exists() and digest(destination) == digest(new),
                'project_unchanged': digest(project) == project_hash,
            }
            # Separately test a fresh user launch; never count it as a successful
            # automatic restart. This distinguishes replacement from restart bugs.
            manual = case / 'manual-candidate.json'
            if diagnostic['candidate_installed']:
                try:
                    run(str(destination), str(project), env=dict(
                        env, CURVEMOLE_UPGRADE_STAGE='candidate',
                        CURVEMOLE_UPGRADE_REPORT=str(manual)))
                    diagnostic['manual_launch'] = assert_report(manual, 'candidate')
                except Exception as exc:
                    diagnostic['manual_launch_error'] = str(exc)
            print(json.dumps(diagnostic, indent=2), flush=True)
            return diagnostic
        wait_windows()
    else:
        # Linux intentionally asks the user to close and reopen after replacing.
        run(str(destination), str(project), env=dict(
            env, CURVEMOLE_UPGRADE_STAGE='candidate', CURVEMOLE_UPGRADE_REPORT=str(after)))
    reports = [assert_report(before, 'baseline'), assert_report(after, 'candidate')]
    assert digest(destination) == digest(new), 'Update did not install the candidate binary'
    assert digest(project) == project_hash, 'Update changed the existing project'
    assert os.access(destination, os.X_OK)
    if not canonical:
        assert not current.exists(), 'Old versioned executable was left behind'
    result = {'kind': case.name, 'passed': True, 'launches': reports,
              'project_sha256': project_hash}
    print(json.dumps(result, indent=2), flush=True)
    return result


def installer_case(baseline: Path, candidate: Path, old: Path, new: Path,
                   work: Path, project: Path, env: dict[str, str]) -> dict:
    iscc = Path(os.environ['PROGRAMFILES(X86)']) / 'Inno Setup 6/ISCC.exe'
    installed = work / 'installed application'
    executable = installed / 'CurveMole.exe'
    reports = []
    project_hash = digest(project)
    old_digest = None
    for stage, root, bundle, version in [('baseline', baseline, old, '0.0.1'),
                                          ('candidate', candidate, new, '0.0.2')]:
        output = work / (stage + '-installer')
        output.mkdir()
        source = f'/DSourceExe={bundle}' if stage == 'baseline' else f'/DSourceDir={bundle}'
        run(str(iscc), f'/DMyAppVersion={version}', source, f'/DRootDir={root}',
            f'/DOutputDir={output}', str(root / 'packaging/windows/curvemole.iss'), env=env)
        setup = next(output.glob('*setup.exe'))
        arguments = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
        if stage == 'baseline':
            arguments.append(f'/DIR={installed}')
        run(str(setup), *arguments, env=env)
        wait_windows()
        report = work / (stage + '-installed.json')
        run(str(executable), str(project), env=dict(
            env, CURVEMOLE_UPGRADE_STAGE=stage, CURVEMOLE_UPGRADE_REPORT=str(report)))
        reports.append(assert_report(report, stage))
        if stage == 'baseline':
            old_digest = digest(executable)
        else:
            assert digest(executable) != old_digest
            assert (installed / '_internal').is_dir()
        assert (installed / 'curvemole-installed.marker').is_file()
        assert digest(project) == project_hash
    result = {'kind': 'installer', 'passed': True, 'launches': reports,
              'project_sha256': project_hash}
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform not in ('win32', 'linux'):
        parser.error('Use the dedicated macOS migration test on Mac')
    baseline, candidate, work = args.baseline.resolve(), args.candidate.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', CURVEMOLE_SMOKE_TEST='1',
               CURVEMOLE_PACKAGING_SMOKE='1', MPLCONFIGDIR=str(work / 'matplotlib'))
    env.pop('APPIMAGE_EXTRACT_AND_RUN', None)
    if sys.platform == 'linux':
        env.update(XDG_CONFIG_HOME=str(work / 'config'), XDG_CACHE_HOME=str(work / 'cache'))
    project = fixture(baseline, work, env)
    results = []
    if sys.platform == 'win32':
        old = build(baseline, env, onefile=True)
        installed_bundle = build(candidate, env, onefile=False)
        results.append(installer_case(baseline, candidate, old, installed_bundle, work, project, env))
        new = build(candidate, env, onefile=True)
        for canonical in (False, True):
            results.append(updater_case('portable', old, new, work, project, env, canonical=canonical))
    else:
        images = []
        for label, root in [('baseline', baseline), ('candidate', candidate)]:
            build(root, env, onefile=False)
            image = work / (label + '.AppImage')
            run('bash', 'scripts/build_appimage.sh', 'generated-icons/curvemole.png', str(image),
                cwd=root, env=env)
            images.append(image)
        for canonical in (True, False):
            results.append(updater_case('appimage', *images, work, project, env, canonical=canonical))
    output = {'platform': sys.platform, 'passed': all(r['passed'] for r in results), 'cases': results,
              'limitations': 'Test-instrumented builds; downloads and modal confirmations bypassed. No signing test.'}
    (candidate / 'desktop-data-upgrade.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))
    if not output['passed']:
        raise SystemExit('At least one upgrade case failed; see desktop-data-upgrade.json')


if __name__ == '__main__':
    main()
