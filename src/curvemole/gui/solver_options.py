"""Explicit, solver-specific controls for the standard fit dialog."""
from __future__ import annotations

import json

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QWidget

from curvemole.core.fitting import FitSettings

LS = {"local", "trf", "dogbox", "lm", "differential_evolution"}
DE = {"differential_evolution"}
NM = {"nelder_mead"}
POWELL = {"powell"}
LB = {"lbfgsb"}

# Scientific notation avoids rounding small convergence tolerances to zero.
FIELDS = (
    ("local_method", "Local method", {"local", "differential_evolution"}, "auto, trf, dogbox or lm; DE uses this for local refinement."),
    ("ftol", "Objective tolerance (ftol)", LS, "Relative least-squares objective convergence tolerance."),
    ("xtol", "Step tolerance (xtol)", LS, "Relative parameter-step convergence tolerance."),
    ("gtol", "Gradient tolerance (gtol)", LS, "Least-squares gradient convergence tolerance."),
    ("x_scale", "Parameter scale (x_scale)", LS, "jac adapts to Jacobian columns; alternatively enter a positive scalar."),
    ("de_maxiter", "DE generations", DE, "Maximum generations in the initial global search."),
    ("de_popsize", "DE population multiplier", DE, "Population size multiplier per free parameter."),
    ("de_mutation_min", "DE mutation minimum", DE, "Lower mutation factor, between 0 and 2 (exclusive)."),
    ("de_mutation_max", "DE mutation maximum", DE, "Upper mutation factor; must be >= minimum and < 2."),
    ("de_recombination", "DE recombination", DE, "Crossover probability between 0 and 1."),
    ("de_tol", "DE relative tolerance", DE, "Relative population-energy convergence tolerance."),
    ("de_atol", "DE absolute tolerance", DE, "Absolute population-energy convergence tolerance."),
    ("seed", "Random seed", DE, "Fixed seed makes the global search reproducible."),
    ("minimize_maxiter", "Maximum iterations", NM | POWELL | LB, "0 keeps the algorithm's automatic iteration limit; the evaluation limit still applies."),
    ("nm_xatol", "Parameter tolerance (xatol)", NM, "Absolute simplex parameter convergence tolerance."),
    ("nm_fatol", "Objective tolerance (fatol)", NM, "Absolute simplex objective convergence tolerance."),
    ("nm_adaptive", "Adaptive simplex", NM, "Adapt simplex coefficients to the number of dimensions."),
    ("nm_initial_simplex", "Initial simplex (optional)", NM, "Leave blank for automatic initialization. JSON matrix with N+1 rows and N columns in free-parameter order; vertices must respect bounds."),
    ("powell_xtol", "Parameter tolerance (xtol)", POWELL, "Relative parameter convergence tolerance."),
    ("powell_ftol", "Objective tolerance (ftol)", POWELL, "Relative objective convergence tolerance."),
    ("lbfgsb_ftol", "Objective tolerance (ftol)", LB, "Relative objective convergence tolerance."),
    ("lbfgsb_gtol", "Projected gradient tolerance", LB, "Maximum projected gradient convergence tolerance."),
    ("lbfgsb_maxls", "Line-search steps", LB, "Maximum line-search steps per iteration."),
    ("lbfgsb_maxcor", "Correction history", LB, "Number of limited-memory Hessian corrections."),
)
INT_FIELDS = {"de_maxiter", "de_popsize", "seed", "minimize_maxiter", "lbfgsb_maxls", "lbfgsb_maxcor"}


class SolverOptions(QWidget):
    def __init__(self, settings: FitSettings, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.fields = {}
        for name, label, _, tip in FIELDS:
            if name == "local_method":
                widget = QComboBox()
                widget.addItems(["auto", "trf", "dogbox", "lm"])
            elif name == "nm_adaptive":
                widget = QCheckBox()
            else:
                widget = QLineEdit()
            widget.setToolTip(self.tr(tip))
            widget.setObjectName(name)
            self.fields[name] = widget
            self.form.addRow(self.tr(label), widget)
        self.load(settings)
        self.set_solver(settings.solver)

    def load(self, settings):
        for name, widget in self.fields.items():
            value = getattr(settings, name)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            elif name == "nm_initial_simplex":
                widget.setText("" if value is None else json.dumps(value))
            else:
                widget.setText(str(value))

    def set_solver(self, solver):
        self.solver = solver
        for name, _, solvers, _ in FIELDS:
            self.form.setRowVisible(self.fields[name], solver in solvers)

    def apply(self, settings):
        for name, label, solvers, _ in FIELDS:
            if self.solver not in solvers:
                continue
            widget = self.fields[name]
            try:
                if isinstance(widget, QCheckBox):
                    value = widget.isChecked()
                elif isinstance(widget, QComboBox):
                    value = widget.currentText()
                else:
                    text = widget.text().strip()
                    if name == "nm_initial_simplex":
                        value = json.loads(text) if text else None
                    elif name == "x_scale" and text == "jac":
                        value = text
                    else:
                        value = int(text) if name in INT_FIELDS else float(text)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid value for {label}.") from exc
            setattr(settings, name, value)
