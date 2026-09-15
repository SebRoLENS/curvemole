"""Occasional-use Run automation control with a remembered YAML file."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QToolBar, QToolButton

from curvemole.core.automation_job import prepare_job
from curvemole.gui.icons import vector_icon


class AutomationRunner:
    def __init__(self, window):
        self.window = window
        self.process = None
        self.temporary = None
        self.stopping = False
        self.run_action = QAction(vector_icon("run-automation.svg"), "Run automation", window)
        self.run_action.triggered.connect(self.run)
        self.choose_action = QAction("Choose automation…", window)
        self.choose_action.triggered.connect(self.choose)
        self.stop_action = QAction("Stop automation", window)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop)
        menu = QMenu(window)
        menu.addActions([self.choose_action, self.stop_action])
        button = QToolButton(window)
        button.setDefaultAction(self.run_action)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar = QToolBar("Automations", window)
        toolbar.setObjectName("Automation_toolbar")
        toolbar.setIconSize(QSize(26, 26))
        toolbar.addWidget(button)
        # A separate bottom toolbar keeps this specialist command away from fitting tools.
        window.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)
        self.toolbar = toolbar
        self.update_tooltip()

    def update_tooltip(self):
        path = str(self.window.settings.value("automation/file", "") or "")
        self.run_action.setToolTip("Run automation\n" + (path or "Choose a YAML automation on first run"))

    def choose(self):
        if self.process is not None:
            return False
        current = str(self.window.settings.value("automation/file", "") or "")
        path, _ = QFileDialog.getOpenFileName(self.window, "Choose automation", current,
                                             "CurveMole automation (*.yml *.yaml)")
        if not path:
            return False
        try:
            prepare_job(path, self.window.plugin_manager)
        except Exception as exc:
            QMessageBox.warning(self.window, "Invalid automation", str(exc))
            return False
        self.window.settings.setValue("automation/file", str(Path(path).resolve()))
        self.update_tooltip()
        return True

    def run(self):
        if self.process is not None:
            return
        path = str(self.window.settings.value("automation/file", "") or "")
        if not path or not Path(path).is_file():
            if not self.choose():
                return
            path = str(self.window.settings.value("automation/file"))
        try:
            request = prepare_job(path, self.window.plugin_manager)
            self.temporary = tempfile.TemporaryDirectory(prefix="curvemole-automation-")
            self.request_path = Path(self.temporary.name) / "job.json"
            self.request_path.write_text(json.dumps(request), encoding="utf-8")
            process = QProcess(self.window)
            self.process = process
            self.stopping = False
            self.run_action.setEnabled(False)
            self.choose_action.setEnabled(False)
            self.stop_action.setEnabled(True)
            self.run_action.setText("Automation running…")
            process.setStandardOutputFile(QProcess.nullDevice())
            process.setStandardErrorFile(QProcess.nullDevice())
            process.finished.connect(self.finished)
            process.errorOccurred.connect(self.failed_start)
            args = ["--run-automation-job", str(self.request_path)]
            if not getattr(sys, "frozen", False):
                args = ["-m", "curvemole.gui.app", *args]
            process.start(sys.executable, args)
        except Exception as exc:
            self.cleanup()
            QMessageBox.critical(self.window, "Automation failed", str(exc))

    def stop(self):
        if self.process is not None:
            self.stopping = True
            self.stop_action.setEnabled(False)
            self.process.kill()

    def failed_start(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process is not None:
            message = self.process.errorString()
            self.cleanup()
            QMessageBox.critical(self.window, "Automation could not start", message)

    def finished(self, exit_code, exit_status):
        if self.process is None:
            return
        try:
            if self.stopping:
                self.window._notify("Automation stopped. Files already written are retained.")
                return
            result_path = self.request_path.with_suffix(".result.json")
            result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
            if exit_code != 0 or not result.get("ok"):
                raise RuntimeError(result.get("error", "The automation process terminated unexpectedly."))
            paths = result.get("outputs", [])
            text = f"Processed spectra: {result['spectra']}\n"
            if result.get("fit_success") is False:
                text += "The fit did not converge. Review its results.\n"
            text += "\n" + ("\n".join(paths) if paths else "No output files configured in this automation.")
            QMessageBox.information(self.window, "Automation completed", text)
        except Exception as exc:
            QMessageBox.critical(self.window, "Automation failed", str(exc))
        finally:
            self.cleanup()

    def cleanup(self):
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        self.run_action.setText("Run automation")
        self.run_action.setEnabled(True)
        self.choose_action.setEnabled(True)
        self.stop_action.setEnabled(False)
