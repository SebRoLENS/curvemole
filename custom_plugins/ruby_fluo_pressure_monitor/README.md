# ruby_fluo_pressure_monitor

**[Download the latest validated plugin ZIP](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/ruby_fluo_pressure_monitor.zip)**

Extract the ZIP and select the enclosed plugin folder in CurveMole’s Plugin Manager.

Version 0.5.0. Fits ruby fluorescence spectra with **two pseudo-Voigt peaks,
independent free FWHM values and a fixed mixing parameter η = 0.5**. It estimates
a linear background, refines the doublet and calculates pressure from R1, the
peak at the longer wavelength. All processing is local.

## Requirements and installation

Requires **CurveMole 0.25.2 or later** with the existing generic panel services.
This version changes only the plugin; an app that already has these services does
not need another desktop rebuild.
1. In **File > Plugin Manager > Choose plugin folder…**, choose this directory.
2. Select `ruby_fluo_pressure_monitor`, review its source and choose
   **Review and trust selected plugin…**.
3. The monitor opens automatically as a docked CurveMole panel when enabled.
   Reopen it from **View > Panels > Ruby fluorescence: monitor — temperature / Start / Stop**.
4. Choose the acquisition folder and set **Filename contains**, e.g. `ruby`.
5. **Sample temperature** defaults to **296 K (22.85 °C)**. With a ruby spectrum
   selected it shows that spectrum's saved temperature. Editing it saves to that
   spectrum on Enter or focus loss, and marks its pressure as needing recalculation.
6. **Calibration and fit settings…** edits the selected spectrum's settings.
   The most recently edited settings are also defaults for subsequent acquisitions;
   merely selecting an older spectrum does not change those acquisition defaults.
7. Click **Start**. Enable **Also import existing matching files** if needed.
   The panel displays running status and the active ruby spectrum's pressure.
8. Click **Stop** to stop acquisition processing. Existing spectra remain editable.

For custom column mappings, settle delay, changed-file imports or retrying failures,
use **File > Automatic folder import…**, selecting the ruby workflow and the same
filename substring. The monitor panel also controls a ruby session started there.
The panel's direct Start uses columns 1/2 and a two-second stable-file delay.

### Manual corrections while monitoring

Select a spectrum and edit its masks and model using CurveMole's normal tools.
The background parameters are unlocked after automatic fitting. There is no
special mask button, temperature-apply button, or selection-apply checkbox.
Monitoring continues throughout manual review. By default, new acquisitions do
not steal the spectrum being edited; the first acquisition is shown if no spectrum
was active. **Show new spectra automatically** is optional.

Each spectrum owns its temperature, calibration, model, masks, and **last calculated
pressure with uncertainty**. Selecting an earlier spectrum restores its temperature
in the field and shows its own pressure prominently:

- **Green:** the saved calculation matches this spectrum's current inputs.
- **Amber + warning:** settings, data, masks or model changed. The previous value
  remains visible, with its original calculation temperature, until recalculated.
- **Recalculate:** evaluates pressure from the current R1 center and displayed
  temperature/calibration, and saves the updated result for this spectrum only.

Run CurveMole's normal **Fit** after changing masks/model parameters if you want a
new optimized fit. Recalculate does not rerun peak detection, reinstall a mask or
perform a fit. It can also evaluate a manually adjusted center; in that case fit
uncertainty is unavailable until a fresh fit. A temperature-only change needs no
spectral refit. Even after a manual Fit, pressure remains flagged until Recalculate.

New files are automatically fitted and get their initial pressure without pressing
Recalculate. Existing spectra and their edits are never overwritten. Save the
`.fitproj` project to retain all per-spectrum edits, last calculations and pending
recalculation states. Undo/redo restores settings/calculations too.

Reports and CSV exports contain the last explicit calculation, with
`needs_recalculation` and `pending_temperature_K` fields so an old result cannot
silently pass as current. Legacy measurements without a calculation fingerprint
are conservatively flagged until Recalculate is pressed.

The filename match is a case-insensitive **substring**: `ruby` accepts `ruby.0`,
`ruby_0.spe`, `test_RUBY_47.spe` and `myruby.spe`, but excludes `sample.spe`.
Only the chosen directory is scanned; subdirectories, temporary files and symbolic
links are excluded. The plugin independently checks the configured name filter.

Monitoring never starts by default. Closing the control panel keeps a started
session running; switching projects stops it. Files must remain stable for the
configured delay (default 2 seconds). Failures appear in the log and are retried
when the file changes or when **Retry failed files** is pressed. Changed-file
import is opt-in and adds a new spectrum instead of overwriting previous data.
Each acquisition is undoable.

## Fitting workflow

The X axis must be increasing wavelength in **nm**. Search limits, prominence,
allowed peak separation and width limits are configurable.

1. Detect a candidate doublet and estimate initial widths from the data.
2. Exclude neighborhoods around both peaks (default ±2 estimated FWHM,
   clipped by the outer margin) and fit a straight background to **all remaining
   valid points in the search interval**.
3. **Invert that band mask within the search interval**: include the previously
   excluded band neighborhoods and exclude the background points. Originally
   invalid/user-masked samples stay excluded. Fit the two pseudo-Voigt peaks on
   top of the fitted line; widths remain free and η is fixed (default 0.5).
4. The straight background is **fixed by default** after its first fit. Legacy
   settings are migrated to this default. Advanced settings can explicitly enable
   joint background refinement if desired. **After the final automatic fit, the
   line parameters are always unlocked** for manual refinement.
5. Use the longer-wavelength center, R1, for pressure calculation. The final band
   mask remains active and editable; it is never reinstalled over manual edits.

### Pressure uncertainty

The panel, import log, report and CSV include pressure and its **1σ fit uncertainty**.
For wavelength-corrected center `L = R1 − thermal_shift`, the propagation is

`u(P) = abs((A / lambda_ref) * (L / lambda_ref) ** (B − 1)) * u(R1)`.

`u(R1)` is the center's standard error from CurveMole's fit covariance, including
its correlations with other free fit parameters. This is first-order uncertainty
propagation ([NIST](https://physics.nist.gov/cuu/Uncertainty/combination.html)).
It excludes temperature, wavelength/reference calibration and pressure-scale
uncertainties; a fixed background is treated as exact, so its first-stage fit
uncertainty is not propagated. Thus it is **not a total measurement uncertainty**.
If R1 is fixed or covariance is unavailable, the UI says uncertainty unavailable
and the CSV field is blank; it never invents a zero uncertainty. After mask/model
edits, the saved pressure and uncertainty remain visible with a stale warning.
Recalculate after a fresh fit updates both; without a refit, the new pressure
can be evaluated but no fit uncertainty is claimed.

Unresolved doublets or failed fits retain the raw acquisition and an error without
a pressure. Strong overlap, parameters at bounds and solver diagnostics are flagged
for inspection. No imported spectrum is used to determine a reference calibration
or an unknown temperature.

## Temperature corrections and pressure scale

| Correction | Allowed range | Form |
|---|---|---|
| Ragan et al. (1992) | 15–600 K | Cubic R1 wavenumber converted to wavelength |
| Datchi et al. (2007), piecewise | 15–600 K | Plateau below 50 K; cubic to 296 K; linear above 296 K |
| Datchi et al. (2007), high-temperature cubic | 296–600 K | Cubic in T−296; original source extends to 900 K |

Both sample and reference temperatures must be in the selected correction's range.
This plugin limits operation to 600 K and does not extrapolate temperature.
These choices are not an exhaustive catalog of historical ruby calibrations.

The default ambient-pressure reference is **694.281 nm at 296 K**, from Datchi
et al. (2007). Room temperature (296 K) is a default assumption, not a temperature measurement;
enter the actual temperature when known. The pressure scale is **Mao–Xu–Bell (1986)**,
with A = 1904 GPa and B = 7.665. All reference values and coefficients are editable.

```text
thermal_shift = f(sample_temperature) − f(reference_temperature)
corrected_wavelength = R1_center − thermal_shift
P = A/B × [(corrected_wavelength/reference_wavelength)^B − 1]
```

This implementation assumes additive thermal and pressure shifts in wavelength;
it does not introduce a pressure–temperature cross term. It flags thermally
corrected pressures above 20 GPa, where separability is not guaranteed, and
pressures above 80 GPa, beyond the Mao–Xu–Bell calibration range. Free widths do
not eliminate ambiguity from overlapping lines at high temperature.

The **All coefficients (JSON)** tab exposes every setting. Polynomial coefficients
are ordered constant, linear, quadratic, cubic. The independent variable is T for
Ragan and T−296 for Datchi. Settings are stored in the project; save the `.fitproj`
to reuse them. Choosing a correction does not silently change the reference values.

Sources:

- Mao, Xu & Bell (1986), [doi:10.1029/JB091iB05p04673](https://doi.org/10.1029/JB091iB05p04673).
- Ragan, Gustavsen & Schiferl (1992), [doi:10.1063/1.351951](https://doi.org/10.1063/1.351951), Eq. (3).
- Datchi et al. (2007), [doi:10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593), Eqs. (1)–(4).

## Results and compatibility

Models, masks, results and the settings used for each acquisition are stored in
its project. **Tools > Analysis > Ruby fluorescence: results and references** shows
the report; **File > Exporters > Ruby fluorescence: export pressures as CSV** exports
the table. Results describe the last automatic or explicitly requested pressure calculation.
Later edits are flagged until Recalculate is pressed.

CurveMole supports calibrated, one-dimensional, single-ROI WinSpec **SPE 2.x**
files. SPE 3.x/XML and CCD images require export to calibrated X/Y text first.
In multi-frame SPE files each frame is a Y column; choose the desired frame in
the automatic import dialog.

The old private `local.ruby_monitor` plugin should be disabled before installing
this renamed community plugin. It has a new identifier; configure its settings
again. Existing spectrum metadata retains the `ruby_monitor` key so previously
saved analyses remain readable and exportable.

## Tests

From the repository root, with development dependencies installed:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest custom_plugins/ruby_fluo_pressure_monitor/test_plugin.py -q
python scripts/validate_community_plugins.py
```

Tests use synthetic spectra with known centers/widths, published coefficients,
round-trip project persistence, asynchronous import, undo/redo, settings,
report/CSV output and plugin load/unload. No experimental acquisitions are bundled.

License: GPL-3.0-or-later; see LICENSE.
