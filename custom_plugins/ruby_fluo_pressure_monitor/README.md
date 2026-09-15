# ruby_fluo_pressure_monitor

Version 0.3.0. Fits ruby fluorescence spectra with **two pseudo-Voigt peaks,
independent free FWHM values and a fixed mixing parameter η = 0.5**. It estimates
a linear background, refines the doublet and calculates pressure from R1, the
peak at the longer wavelength. All processing is local.

## Requirements and installation

Requires CurveMole with automatic folder import and `PluginContext.services`
(nonmodal panel services), supplied with this update. Update **both CurveMole and
the plugin** to use the monitor panel. The older File-menu workflow remains available.

1. In **File > Plugin Manager > Choose plugin folder…**, choose this directory.
2. Select `ruby_fluo_pressure_monitor`, review its source and choose
   **Review and trust selected plugin…**.
3. Open **View > Panels > Ruby fluorescence: monitor — temperature / Start / Stop**.
4. Choose the acquisition folder and set **Filename contains**, e.g. `ruby`.
5. Enter **Sample temperature (K)** and tick **Confirm sample temperature**.
   **Apply temperature** saves it; **Start** also saves the displayed settings.
   Without confirmation, fitting still runs but pressure is not calculated.
6. Use **Advanced settings / calibration…** to choose the temperature correction
   and edit literature reference values, coefficients and fitting settings.
7. Click **Start**. Enable **Also import existing matching files** if needed.
   The panel displays running status and the active ruby spectrum's pressure.
8. Click **Stop** to stop acquisition processing. Existing spectra remain editable.

For custom column mappings, settle delay, changed-file imports or retrying failures,
use **File > Automatic folder import…**, selecting the ruby workflow and the same
filename substring. The monitor panel also controls a ruby session started there.
The panel's direct Start uses columns 1/2 and a two-second stable-file delay.

### Manual corrections while monitoring

Uncheck **Follow newest spectrum** in the monitor (or the File import panel),
select a spectrum and adjust its masks, component parameters and bounds using
CurveMole's normal tools. New spectra continue to be processed in the background;
your selected spectrum and its edits remain in place. Run **Fit** in CurveMole
after editing. The monitor, report and CSV derive pressure from the **current
fitted model**, using the longer-wavelength of exactly two enabled pseudo-Voigt peaks.
Until the fit is current, no pressure is reported. Automatic detection/masking is
only applied to new acquisitions, so it does not overwrite your manual corrections.

Temperature/calibration changes normally affect **new acquisitions only**.
To correct existing measurements, select their spectra, check **Also apply
temperature/calibration to selected spectra**, and click **Apply temperature**.
This update is undoable and does not invalidate the spectral fit. It applies the
currently configured calibration as well as temperature. Earlier measurements
otherwise retain their own temperature and reference settings.

The live panel, report and CSV recompute pressure after a manual fit. Saved
acquisition metadata retains the initial analysis; current models and masks are
saved in the project and used to derive updated results when it is reopened.
The original acquisition log is historical and does not change after manual edits.

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
2. Temporarily exclude neighborhoods around both peaks (default ±2 estimated
   FWHM) and fit a straight background to the remaining local points.
3. Restore both peaks, exclude data outside their shared local region (default
   margin 3 nm on either side), and fit the background plus both pseudo-Voigt peaks.
   The two widths remain free; η stays fixed at its configured value (default 0.5).
   η = 0 is Gaussian; η = 1 is Lorentzian.
4. Optionally hold the background fixed after step 2. By default it is refined
   jointly with the peaks. Center bounds prevent R1/R2 from exchanging identities.
5. Use the longer-wavelength center, R1, for pressure calculation.

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
et al. (2007). The initial sample-temperature field is not a measurement: pressure
is withheld until the user confirms it. The pressure scale is **Mao–Xu–Bell (1986)**,
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
the table. Results describe the automatic fit at import time: later manual model
changes do not automatically recalculate pressure.

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
