# Cosmic-ray removal

An interactive CurveMole panel for finding and selectively repairing narrow,
positive cosmic-ray spikes in one-dimensional spectra. The original and cleaned
preview are overlaid before anything is changed. Every candidate has its own
**Apply** checkbox, so a suspicious correction on top of a real band can be
rejected while the other corrections are retained.

## Use

1. Select a spectrum and choose a detection method.
2. Press **Detect automatically**. Review the overlay and candidate table.
3. Uncheck corrections that should not be applied. **Select all** and **Select
   none** are available for convenience.
4. To add a missed event, enable **Indicate manually** and click it in the
   embedded plot. `Grow candidate` controls the number of neighbouring points.
5. Press **Accept modifications**. This replaces only the accepted intervals in
   the selected spectrum and creates one normal CurveMole undo step.

The panel opens automatically and remains a normal dockable CurveMole panel.
Accepted intervals and detection settings are stored in spectrum metadata.

## Detection methods

**Single spectrum — modified Z-score** follows the robust derivative/modified
Z-score approach of Whitaker and Hayes. It is appropriate for isolated, narrow
positive spikes but cannot always distinguish a cosmic ray from a genuinely
sharp sample feature.

**Selected repeated spectra — robust median reference** is recommended when
several acquisitions of the same sample are available. Select at least three
repeated spectra in CurveMole. They are interpolated to the active spectrum's
grid, robustly aligned in intensity, and combined with a median. A feature unique
to one exposure is then compared with the repeated-spectrum reference. Do not
combine spectra from different samples or experimental conditions.

Repairs preserve the x grid. Single-spectrum repairs use shape-preserving PCHIP
interpolation from adjacent unaffected points; repeated-spectrum repairs use the
aligned median reference. No correction is committed during preview.

## Parameters and limitations

- **Sensitivity threshold**: higher values are more conservative. The default 8
  is deliberately conservative.
- **Median window**: local window used to separate narrow spikes from the signal.
- **Maximum spike width**: rejects broad features, which are less likely to be a
  cosmic ray.
- **Grow candidate**: includes neighbouring affected pixels.

Always inspect events on top of bands. A single spectrum contains insufficient
information to prove whether an isolated sharp feature is instrumental or real.
This plugin therefore never silently commits automatic corrections.

## References

- D. A. Whitaker and K. Hayes, “A simple algorithm for despiking Raman spectra,”
  *Chemometrics and Intelligent Laboratory Systems* 179 (2018) 82–84.
  https://doi.org/10.1016/j.chemolab.2018.06.009
- S. J. Barton and B. Hennelly, “An Algorithm for the Detection and Removal of
  Cosmic Ray Artifacts in Spectral Data Sets,” *Applied Spectroscopy* 73 (2019)
  893–901. https://doi.org/10.1177/0003702819839098

The supplied example spectra were used only as diverse verification data. They
are not bundled, and no thresholds or x positions are fitted to them.
