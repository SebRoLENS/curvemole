from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from curvemole.core.automation_job import prepare_job, run_job
from curvemole.core.plugins import PluginManager
from curvemole.gui.main_window import MainWindow


@pytest.fixture
def workflow(tmp_path):
    source = Path(__file__).parents[1] / "examples"
    shutil.copy(source / "gaussian.csv", tmp_path / "gaussian.csv")
    text = (source / "gaussian_workflow.yml").read_text().replace("overwrite: false", "overwrite: true")
    path = tmp_path / "workflow.yml"
    path.write_text(text)
    return path


def test_isolated_job_rejects_changed_source(workflow, tmp_path):
    request = prepare_job(workflow, PluginManager())
    path = tmp_path / "job.json"
    path.write_text(json.dumps(request))
    workflow.write_text(workflow.read_text() + "\n# changed")
    assert run_job(path) == 1
    result = json.loads(path.with_suffix(".result.json").read_text())
    assert "changed" in result["error"]
    assert not (tmp_path / "gaussian_result.fitproj").exists()


def test_first_run_chooses_and_subsequent_runs_reuse_file(workflow, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    calls, messages = [], []
    def choose(*args):
        calls.append(True)
        return str(workflow), ""
    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[1]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: pytest.fail(str(args)))
    runner = window.automation_runner
    original = window.project
    for _ in range(2):
        runner.run()
        assert not runner.run_action.isEnabled()
        deadline = time.monotonic() + 20
        while runner.process is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert runner.process is None
    assert len(calls) == 1
    assert messages == ["Automation completed", "Automation completed"]
    assert window.project is original
    assert window.settings.value("automation/file") == str(workflow)
    assert (tmp_path / "gaussian_result.fitproj").exists()
    assert runner.run_action.isEnabled()
    window.close()


def test_cancel_file_picker_keeps_run_ready(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    runner = window.automation_runner
    runner.run()
    assert runner.process is None
    assert runner.run_action.isEnabled()
    assert not window.settings.value("automation/file", "")
    window.close()
    app.processEvents()


def test_stop_running_automation_recovers_controls(workflow, tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.settings = QSettings(str(tmp_path / "stop.ini"), QSettings.Format.IniFormat)
    window.settings.setValue("automation/file", str(workflow))
    runner = window.automation_runner
    runner.run()
    assert runner.process.waitForStarted(5000)
    assert runner.process.state() == QProcess.ProcessState.Running
    runner.stop()
    deadline = time.monotonic() + 10
    while runner.process is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert runner.process is None
    assert runner.run_action.isEnabled()
    assert not runner.stop_action.isEnabled()
    window.close()


def test_plugin_approval_rechecked_inside_worker(workflow, tmp_path):
    from curvemole.core.errors import CurveMoleError
    module = tmp_path / "plugin.py"
    module.write_text("def register(api): pass\n")
    manifest = tmp_path / "plugin.curvemole-plugin.json"
    manifest.write_text(json.dumps({"identifier": "test", "version": "1", "api_compatibility": "1",
                                   "licence": "MIT", "capabilities": [], "module": "plugin.py"}))
    workflow.write_text(workflow.read_text() + "\nplugins: [plugin.curvemole-plugin.json]\n")
    manager = PluginManager()
    with pytest.raises(CurveMoleError, match="Review and enable"):
        prepare_job(workflow, manager)
    candidate = manager.discover_local(tmp_path)[0]
    manager.installed["test"] = {"enabled": True, "fingerprint": manager._fingerprint(candidate)}
    request = tmp_path / "job.json"
    request.write_text(json.dumps(prepare_job(workflow, manager)))
    module.write_text("raise RuntimeError('must not execute changed code')\n")
    assert run_job(request) == 1
    assert "Review and enable" in json.loads(request.with_suffix(".result.json").read_text())["error"]
