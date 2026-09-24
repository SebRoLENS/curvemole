<p align="center">
  <img src="src/curvemole/resources/curvemole.png" width="112" alt="CurveMole icon">
</p>

<h1 align="center">CurveMole</h1>

<p align="center">
  <a href="https://github.com/SebRoLENS/curvemole/releases/latest"><img src="https://img.shields.io/github/v/release/SebRoLENS/curvemole" alt="Version"></a>
  <a href="https://github.com/SebRoLENS/curvemole/releases/latest"><img src="https://img.shields.io/badge/Windows-x86__64-0078D4?logo=windows" alt="Windows"></a>
  <a href="https://github.com/SebRoLENS/curvemole/releases/latest"><img src="https://img.shields.io/badge/Linux-x86__64-FCC624?logo=linux&logoColor=black" alt="Linux"></a>
  <a href="https://github.com/SebRoLENS/curvemole/releases/latest"><img src="https://img.shields.io/badge/macOS-Intel%20%7C%20Apple%20Silicon-000000?logo=apple" alt="macOS"></a>
  <a href="https://github.com/SebRoLENS/curvemole/releases/latest"><img src="https://img.shields.io/badge/DOI-pending-lightgrey" alt="DOI"></a>
  <a href="https://github.com/SebRoLENS/curvemole/actions/workflows/ci.yml"><img src="https://github.com/SebRoLENS/curvemole/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

<p align="center"><strong>Scientific curve and peak fitting for spectroscopy, diffraction, kinetics, and general x-y data.</strong></p>

CurveMole is a desktop-first, scriptable scientific data-analysis application for
one-dimensional spectra and curves. It provides interactive curve fitting, peak fitting,
baseline/background modelling, and nonlinear least-squares analysis for IR and Raman
spectra, powder diffraction and XRD patterns, kinetic traces, and general x-y data.
The same scientific engine is shared by the graphical interface, Python API, command
line, and reproducible YAML workflows.

> **Status:** Version **0.28.5 Preview**. The scientific core and desktop workflow
> are usable, but this is not yet the validated 1.0 Stable release.


## Download

**[Download the latest release](https://github.com/SebRoLENS/curvemole/releases/latest)**
· [Browse previous releases](https://github.com/SebRoLENS/curvemole/releases)

Available packages are built automatically for:

- Linux x86_64: AppImage with optional per-user desktop integration
- Windows x86_64: installer (recommended) or portable `.zip`
- macOS Apple Silicon: `.dmg`
- macOS Intel x86_64: `.dmg`

The installed desktop applications register CurveMole projects (`.fitproj`) with
the operating system, so they can be opened by double-clicking or with **Open with
CurveMole**. Linux AppImage users can choose **Tools > Integrate CurveMole with the
desktop**; an existing manual launcher is adopted and backed up instead of duplicated.
- Python 3.12+: wheel and source distribution

> **Windows and macOS security notice**
>
> Windows SmartScreen or macOS Gatekeeper will probably show a warning on first
> launch because these packages are not currently code-signed or notarized with
> certificates recognised by those platforms. Obtaining and maintaining those
> certificates requires paid developer programmes. CurveMole is free, open-source,
> non-profit software, and the project currently chooses not to fund commercial,
> platform-specific signing programmes or pass those costs on to users. A warning
> caused by a missing signature is not, by itself, evidence that malware was detected.
> Download CurveMole only from the official release page and verify `SHA256SUMS.txt`.

The Linux AppImage is cryptographically signed using the free, open-source Sigstore
infrastructure through GitHub Actions. Every release includes a detached
`.sigstore.json` signature bundle. With the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify CurveMole-VERSION-linux-x86_64.AppImage \
  --repo SebRoLENS/curvemole
```

## Custom plugins: install or share yours

**[Download latest Community Plugins](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/validated-community-plugins.zip)**

Extract the ZIP, then select the plugin folder in **File > Plugin manager > Choose
plugin folder…**. Downloads open directly; no GitHub account or pull-request navigation
is needed. The link always serves the latest published, validated plugin bundle.

**[Share a plugin you created](custom_plugins/README.md#submit-a-plugin)** ·
[Browse the community folder](custom_plugins) ·
[Plugin author guide](docs/plugins.md)

- **Use it on your PC:** open **File > Plugin manager > Choose plugin folder…**,
  select the folder containing your manifest and Python module, then **Review and trust**.
- **Share it with other users:** submit a folder at **`custom_plugins/your_plugin/`**
  through a GitHub pull request. Follow the upload steps linked above. GitHub tests
  the submission; only successful main runs produce the validated catalog bundle.

The Plugin Manager also includes **Share my plugin on GitHub…**, which opens these
submission instructions. Loading a plugin locally does not upload it publicly.
## Why CurveMole?

Keep experimental notes in the **Laboratory notebook**: project notes plus
descriptions of series, individual spectra, and fit functions. Descriptions survive
deletion with a clear status, are saved in the project, and can be exported as TXT.
Overlay and Waterfall also offer one-click **All series / Active series / Selected** controls. Use Shift-click for ranges
and Ctrl-click for individual selections. Note icons open attached descriptions
directly; empty descriptions disappear. Series headers adapt their color to the
theme. **File > Recent projects** reopens recent work, and recovery is offered
automatically only after an abnormal exit. Three recovery copies are retained
per project and cleared after Save or explicit Discard.

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
- content-aware import of valid numeric text files regardless of extension, with
  automatic/manual leading-row skipping and reusable batch mappings
- fixed values, lower/upper bounds, intervals, and expression links across spectra
- independent, propagating sequential, copy, and global simultaneous least-squares
  fitting, with configurable safeguards and durable pause/resume
- reversible transformations and graphical masks with immutable original data
- function-aware Quick Add, selectable automatic peak shapes, click-drag peak
  placement, live spline backgrounds, and direct right-drag interval masking
- project-wide function selection and explicit, undoable parameter copying between
  compatible functions, including optional bounds, fixed state, and links
- reusable user-defined function libraries with explicit peak parameter roles for
  reliable graphical and automatic initialisation
- live fit refresh, adaptive rendering for dense spectra, background-subtracted
  inspection, and non-destructive viewport navigation during fitting
- covariance statistics, confidence intervals, profile likelihood, Monte Carlo,
  residual bootstrap, and block bootstrap
- portable, versioned `.fitproj` projects without pickle
- human-friendly Wide exports, Python-friendly Tidy exports, and one-file-per-spectrum
  numeric export of data, components, total fit, background, and residuals
- startup and hourly release checks with an in-app version badge and self-update for
  supported Linux AppImage and Windows installed/portable applications
- Live spectrum preview while browsing files and choosing import columns, with adaptive rendering
- Separate Run automation button with a remembered YAML workflow
- Python API, CLI, YAML workflows, custom formulas, and trusted additive plugins
- File > Plugin Manager: persistent loading, removal and crash-recovery startup;
  [write exporters, fit algorithms and other extensions](docs/plugins.md)

## Interface and real usage examples

### Multi-peak fit with background and residuals

![CurveMole fitting a Raman-like spectrum with Gaussian and Lorentzian peaks](docs/screenshots/fit-overview.png)

A deterministic Raman-like dataset fitted with a linear background, a Gaussian peak,
and a Lorentzian peak. The complete interface shows the measured curve, individual
components, model sum, residuals, fitted parameters, uncertainties, and curve state.

### Comparing a fitted series

![CurveMole comparing three fitted spectra in overlay view](docs/screenshots/multi-spectrum-overlay.png)

Three related spectra are fitted independently and inspected together in Overlay view.
All spectrum colours use CurveMole's built-in **Colourblind** palette.

### Waterfall view

![CurveMole displaying three fitted spectra in Waterfall view](docs/screenshots/waterfall-view.png)

The same fitted series displayed with a vertical offset in Waterfall view, while
preserving the model components and residual information.

### Dark mode

![CurveMole fitting interface in dark mode](docs/screenshots/dark-mode-fit.png)

The single-spectrum fit shown with CurveMole's dark interface theme and the same
colourblind-safe spectrum palette.

All four screenshots are generated from the real application by
[`scripts/generate_screenshots.py`](scripts/generate_screenshots.py) and refreshed
automatically whenever the graphical interface changes.

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

Current public version: **0.28.5**

## How to cite

If CurveMole contributes to published research, please cite the exact version used.
GitHub also provides a **Cite this repository** entry from [`CITATION.cff`](CITATION.cff).

Version **0.28.5** will be archived on Zenodo after its GitHub integration is enabled.
The release DOI will then be inserted here automatically.

> Romi, S. (2026). *CurveMole: Modular Scientific Curve Fitting* (Version 0.28.5)
> [Computer software]. GitHub. https://github.com/SebRoLENS/curvemole/releases/tag/v0.28.5

## License

CurveMole is free software released under **GPL-3.0-or-later**. User data, projects,
results, private formulas, and unpublished private extensions remain under the user's
control. Citation metadata are provided in `CITATION.cff`.

### Advanced calculator and community plugins

The green Advanced calculator supports formulas between all imported columns,
including unplotted ones, with column insertion dropdowns and a destination selector.
All calculator operations can target one spectrum or a grouped multiple-spectrum
selection. See the [quick start](docs/quick-start.md#calculator-operations-between-columns).

Contribute plugins through [custom_plugins](custom_plugins/README.md). GitHub validates
manifests, registration and functional tests on three platforms before producing a
validated catalog bundle. Plugins remain explicit, additive installations.
