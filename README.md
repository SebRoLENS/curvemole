# CurveMole

[![Version](https://img.shields.io/github/v/release/SebRoLENS/curvemole)](https://github.com/SebRoLENS/curvemole/releases/latest)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22128157.svg)](https://doi.org/10.5281/zenodo.22128157)
[![CI](https://github.com/SebRoLENS/curvemole/actions/workflows/ci.yml/badge.svg)](https://github.com/SebRoLENS/curvemole/actions/workflows/ci.yml)

**Scientific curve and peak fitting for spectroscopy, diffraction, kinetics, and general x-y data.**

CurveMole is a desktop-first, scriptable scientific data-analysis application for
one-dimensional spectra and curves. It provides interactive curve fitting, peak fitting,
baseline/background modelling, and nonlinear least-squares analysis for IR and Raman
spectra, powder diffraction and XRD patterns, kinetic traces, and general x-y data.
The same scientific engine is shared by the graphical interface, Python API, command
line, and reproducible YAML workflows.

> **Status:** Version **0.7.0 Preview**. The scientific core and desktop workflow
> are usable, but this is not yet the validated 1.0 Stable release.

## Why CurveMole?

CurveMole is designed for experimental scientists who want the convenience of an
interactive desktop GUI without giving up reproducibility or scriptability. A fit can
be explored graphically and then reproduced through the Python API, CLI, or YAML
workflow using the same fitting engine and scientific conventions.

It is intended as a general-purpose open-source tool for spectroscopy, diffraction,
kinetics, peak analysis, and other one-dimensional scientific datasets rather than a
workflow tied to a single experimental technique.

## Documentation

- **[Detailed user manual (Markdown)](docs/manual.md)** - authoritative source,
  with the supported CurveMole version declared at the top
- **[User manual (PDF)](docs/CurveMole_User_Manual.pdf)** - generated automatically
  from the Markdown source
- **[User manual (LaTeX)](docs/CurveMole_User_Manual.tex)** - generated source used
  to compile the PDF
- **[Quick Start](docs/quick-start.md)** - compact first-workflow guide

The documentation workflow verifies the declared software version, local links,
LaTeX conversion, and PDF compilation. Versioned PDF and LaTeX manuals are attached
to releases.

## Highlights

- Gaussian, Lorentzian, Voigt, and pseudo-Voigt peaks parameterised by signed area
- constant, linear, arbitrary-order polynomial, and cubic-spline backgrounds
- fixed values, lower/upper bounds, intervals, and expression links across spectra
- independent, sequential, copy, and global simultaneous least-squares fitting
- reversible transformations and graphical masks with immutable original data
- click-drag peak placement, live point-by-point spline backgrounds, and direct
  right-drag interval masking
- covariance statistics, confidence intervals, profile likelihood, Monte Carlo,
  residual bootstrap, and block bootstrap
- portable, versioned `.fitproj` projects without pickle
- human-friendly Wide exports and Python-friendly Tidy exports
- Python API, CLI, YAML workflows, custom formulas, and trusted plugins

## Download

The easiest way to test CurveMole is through a pre-built desktop application:

**[Download the latest release](https://github.com/SebRoLENS/curvemole/releases/latest)**

**[Browse and download previous releases](https://github.com/SebRoLENS/curvemole/releases)**

Available packages are built automatically for:

- Linux x86_64: AppImage
- Windows x86_64: standalone `.exe`
- macOS Apple Silicon: `.dmg`
- macOS Intel x86_64: `.dmg`
- Python 3.12+: wheel and source distribution

Linux packages receive a GitHub artifact attestation. Windows and macOS packages
are currently unsigned and may show a security warning on first launch.

## Install and run from source

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
curvemole gui
```

Try the complete example:

```bash
curvemole run examples/gaussian_workflow.yml
```

Run tests:

```bash
uv sync --group dev
uv run pytest
```

The manual, Quick Start, and [plugin guide](docs/plugins.md) are included offline.
Maintainers can consult the [automated release guide](docs/releasing.md).

## Scientific conventions

Built-in peak amplitude is the signed integrated area. Widths are strictly positive;
pseudo-Voigt mixing is bounded to `[0, 1]`. Original data are never overwritten.
Masks and transformations remain visible, reversible, and serialised. CurveMole never
silently changes the solver, excludes points, or normalises global contributions.

## Author and contact

Sebastiano Romi  
European Laboratory for Non-Linear Spectroscopy (LENS)  
University of Florence (UNIFI)  
[romi@lens.unifi.it](mailto:romi@lens.unifi.it)

## Version

Current public version: **0.7.0**

## How to cite

If CurveMole contributes to published research, please cite the exact version used.
GitHub also provides a **Cite this repository** entry from [`CITATION.cff`](CITATION.cff).

> Romi, S. (2026). *CurveMole: Modular Scientific Curve Fitting* (Version 0.7.0)
> [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22128157

DOI: [**10.5281/zenodo.22128157**](https://doi.org/10.5281/zenodo.22128157)

## License

CurveMole is free software released under **GPL-3.0-or-later**. User data, projects,
results, private formulas, and unpublished private extensions remain under the user's
control. Citation metadata are provided in `CITATION.cff`.
