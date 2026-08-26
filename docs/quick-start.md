# CurveMole Quick Start

## 1. Import curves

Choose **File → Import Data** and select one or many `.txt`, `.dat`, `.csv`, or
`.tsv` files. In the preview, choose the x column, one or more y columns, and any
available `sigma_x`, `sigma_y`, weight, variance, or inverse-variance column.
Use **Apply this mapping to all files in this batch** only when the files share the
same layout.

Rows are never reordered or merged. Invalid numeric cells remain stored and are
visibly excluded from calculations.

## 2. Build the model

Activate one curve in the left panel. In **Model and parameters**, press **+** and
add a background and one or more peaks. Built-in peaks use signed integrated area:

- Gaussian: `area`, `center`, `sigma`
- Lorentzian: `area`, `center`, `gamma` (HWHM)
- Voigt: `area`, `center`, `sigma`, `gamma`
- pseudo-Voigt: `area`, `center`, `fwhm`, `eta`

Edit values directly in the parameter table. Empty lower/upper cells mean unbounded.
Check **Fixed** to hold a parameter. A link such as
`${curve_id.component_id.center}` can connect parameters in the same or another
spectrum.

## 3. Adjust and mask graphically

Select a peak component. Drag its apex to change centre and area-derived height;
drag either side handle to change width. A fixed value shows a lock: hold **Ctrl**
while dragging to change the value while leaving it fixed. Use **Ctrl+Z** to undo.

Enable **Mask** above the graph. Click a point or drag an x interval. Choose Active,
Selected, or All visible as the target. Masked intervals are shaded and masked data
are faded. Set the explicit cross-curve x tolerance under **Data → Mask transfer
tolerance**. The worksheet never opens automatically during masking.

## 4. Fit

Press **F5** and explicitly choose:

- Single / independent
- Sequential
- Global simultaneous

Copy fit is available separately under **Model → Copy fit**. Ordinary constrained
least squares is the default. Robust losses and Differential Evolution are in the
advanced portion of the Fit dialog. Differential Evolution requires finite bounds.

## 5. Inspect and export

Residuals appear under the curve. Open **View → Diagnostics** for interpretable
warnings and **Fit → Uncertainty Analysis** for explicit resampling.

Choose **File → Export analysis bundle**. Root files are intended for quick use in
Origin/QtiPlot and human inspection; `python/` contains Tidy data and versioned JSON.
The first export records its directory. Later updates overwrite only files owned by
the CurveMole export manifest and only after confirmation.

Save the complete workspace as `.fitproj`. Original values, masks, transformations,
models, custom functions, results, and history are embedded without pickle.
