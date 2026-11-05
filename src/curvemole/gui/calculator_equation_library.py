"""Connect the calculator's reusable equation library to desktop settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from curvemole.core.calculator_equations import load_equations, save_equation
from curvemole.gui.data_directories import (
    LIBRARY_FOLDERS,
    library_directory,
    prepare_library_directory,
)

_FOLDER = LIBRARY_FOLDERS["equations"]
_SETTING = "custom_equation_directory"


class CalculatorEquationLibrary:
    def __init__(self, window) -> None:
        self.window = window
        self._fingerprint = None
        window.calculator.equationLibraryRequested.connect(self.choose_directory)

    @property
    def directory(self) -> Path:
        return library_directory(self.window.settings, "equations")

    def refresh(self, *, force: bool = False) -> None:
        directory = self.directory
        try:
            from curvemole.core.calculator_equations import EQUATION_SUFFIX
            fingerprint = (str(directory), tuple(
                (str(path), path.stat().st_mtime_ns, path.stat().st_size)
                for path in sorted(directory.glob(f"*{EQUATION_SUFFIX}"))))
            if not force and fingerprint == self._fingerprint:
                return
            equations, failures = load_equations(directory)
        except OSError as exc:
            fingerprint = None
            equations, failures = [], [str(exc)]
        self._fingerprint = fingerprint
        self.window.calculator.set_equation_library(equations, directory, failures)

    def save(self, equation) -> Path:
        directory = prepare_library_directory(self.window.settings, "equations")
        destination = save_equation(directory, equation)
        self.window.settings.setValue(_SETTING, str(directory))
        self.refresh(force=True)
        return destination

    def choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self.window, self.window.tr("Choose the formula library folder"), str(self.directory))
        if not selected:
            return
        directory = Path(selected)
        if directory.name.casefold() != _FOLDER.casefold():
            directory /= _FOLDER
        self.window.settings.setValue(_SETTING, str(directory))
        self.refresh(force=True)
        self.window.refresh_all()
