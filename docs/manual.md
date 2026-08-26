# CurveMole User Manual — Preview 0.1.0

**Current manual version: 0.1.0**

CurveMole is a general one-dimensional curve fitter with a spectrum-first workflow.
It is not a crystallographic refinement program. The same engine serves the desktop
GUI, Python API, command line, and YAML workflows.

## Workspace

The main window contains the Series/Curve tree, central plot with collapsible
residuals, Model/Parameters panel, and optional dockable panels. Multiple curves can
be displayed as Single, Overlay, or Waterfall with arbitrary display-only offsets.
The active curve is distinct from selected and visible curves.

The coordinate readout follows the pointer and also reports the nearest data point.
Original arrays are float64 and immutable. Screen rendering may be downsampled by
PyQtGraph, but fitting and export use all valid, unmasked points.

## Import

Supported formats are TXT, DAT, CSV, and TSV. CurveMole detects common delimiters,
headers, comments, decimal points, and decimal commas, then displays the detected
interpretation before import. Supported organisations are a single x-y pair, one x
with multiple y columns, and multiple x-y pairs through the Python API.

`sigma_y` is interpreted as an absolute one-standard-deviation uncertainty.
Inverse variance is converted to residual scaling through its square root. A generic
weight column directly scales residuals. `sigma_x` is stored but not used by the
version 1 optimiser.

## Data Calculator

The non-modal calculator performs addition, subtraction, multiplication, division,
x scaling, and y normalisation. Curve-to-curve operations use linear interpolation
by default; nearest and cubic are optional. Extrapolation is off by default and
outside values become missing. Every operation is recorded and undoable; **Restore
original data** is always available.

## Functions and parameters

Built-in peaks are area normalised. Their analytical area and FWHM are reported.
Backgrounds include constant, linear, arbitrary-order polynomial, and cubic spline.
Spline x nodes are fixed metadata by default; y nodes are ordinary parameters and
can therefore be fitted, fixed, bounded, and linked.

Each parameter may be free, fixed, lower-bounded, upper-bounded, interval-bounded,
or linked. Intrinsic bounds are always active: widths are positive and pseudo-Voigt
`eta` lies in `[0, 1]`. Links use restricted expressions and `${parameter.path}`
references. Cycles and infeasible constraints are rejected before fitting.

The Function Builder interprets a restricted expression tree and never executes
unrestricted `eval`. Available functions include `abs`, `sqrt`, `exp`, `log`,
trigonometric functions, `erf`, `minimum`, `maximum`, `clip`, and `where`.

## Fitting

CurveMole version 1 uses nonlinear least squares only. The local solver is the
default. Levenberg–Marquardt is used only for an unbounded ordinary least-squares
problem. Differential Evolution is an optional initial search and never invents
scientific bounds; every free parameter must have finite user bounds.

Global fits concatenate explicitly weighted residuals from all selected spectra.
Equal contribution is optional and never silently enabled. Different spectra may
have different models, and expression links can cross spectra. A failed sequential
fit pauses at the failing curve for manual correction.

## Statistics and uncertainty

Automatic results include N, free parameter count, degrees of freedom, RSS, RMSE,
chi-square, reduced chi-square, descriptive R², standard errors, confidence
intervals, covariance, and correlation. AIC/AICc/BIC are displayed only for ordinary
least-squares results. Absolute `sigma_y` leaves covariance unscaled; relative or
absent weights estimate residual variance. Robust losses use a sandwich covariance
and clearly recommend resampling.

Advanced analyses are explicit: profile likelihood, parametric Monte Carlo,
residual bootstrap, and block bootstrap. Every stochastic result records requested,
completed, and failed replicates, seed, settings, and empirical intervals.

## Project and recovery

`.fitproj` is a documented ZIP container containing a versioned JSON manifest,
NumPy `.npy` arrays, and SHA-256 checksums. It never contains pickle. Saves are
atomic. Modified projects autosave every ten minutes; inactivity does not rotate a
recovery. Only the three newest distinct recovery files are retained.

Projects are not encrypted. Use operating-system permissions or encrypted storage
when confidentiality is required.

## Privacy and support

CurveMole operates locally, has no telemetry, and uploads nothing automatically.
Diagnostic bundles exclude spectra, projects, and results unless explicitly added.

Author: Sebastiano Romi, European Laboratory for Non-Linear Spectroscopy (LENS),
University of Florence (UNIFI), romi@lens.unifi.it.
