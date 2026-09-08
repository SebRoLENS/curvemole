# CurveMole Quick Start

Use **View all** in the main icon toolbar (also in the plot context menu and **View > Axes**)
to frame all experimental samples, including masked regions. **View active**,
alongside it, frames only unmasked samples. Neither command includes model
functions, spline extrapolation, labels, or handles in the limits. Bounds use
full-resolution data regardless of adaptive rendering, respecting Waterfall
offsets and visual background subtraction. With no usable samples, View active
leaves the current view unchanged.

## 1. Import curves

Press the **Import data** toolbar button (or choose **File → Import Data**) and
select one or many text-based numeric files.
The import dialog includes **Series name**: it proposes **Series 1**, **Series 2**,
and so on, and you can replace it with your own name. All files selected in the
same import belong to that series. Later, double-click its name in **Series /
Curve**, or right-click it and choose **Rename series…**.
Common `.txt`, `.dat`, `.csv`, and `.tsv` extensions are shown directly; use
**All files** for formats such as `.xy`. CurveMole validates the contents rather
than relying on the suffix. Confirm the automatically detected delimiter, decimal
separator, header, and number of leading rows to ignore. Then choose the x column,
one or more y columns, and any available `sigma_x`, `sigma_y`, weight, variance, or
inverse-variance column.
Use **Apply this mapping to all files in this batch** only when the files share the
same layout.

Rows are never reordered or merged. Invalid numeric cells remain stored and are
visibly excluded from calculations.

## 2. Add one or more backgrounds

Activate the curve in the left panel. For a graphical spline background:

1. choose **Cubic-spline background** in the toolbar selector;
2. press **Quick Add Function**;
3. left-click successive points that follow the experimental background;
4. inspect the live dashed preview, then right-click or press **Finish** after at
   least two points;
5. select the new spline in **Model and parameters** and enable **Mark as
   background**.

New spline y nodes are fixed by default, so the drawn baseline will not drift during
the next fit. Uncheck **Fixed** for selected nodes, or use **Unlock all**, only when
the background should be refined by the optimizer.

To combine several background contributions, add further spline, constant, linear,
polynomial, or custom functions and enable **Mark as background** on each one. All
enabled marked functions contribute to the combined background. Ordinary peak
functions must remain unmarked.

## 3. Inspect or subtract the background

There are two distinct workflows:

- **Visual only - background-subtracted** removes the enabled marked background from
  the displayed spectrum. It does not modify the data, the fit, the project arrays,
  or exports. Turn it off to restore the normal display. When fitting in this mode,
  the background functions remain part of the model and the fit still uses the
  original spectrum.
- **Data → Subtract background...** performs a real, reversible subtraction. Select
  the spline (and any other background functions to combine), leave **Apply to all
  spectra** off for this example, and confirm. CurveMole subtracts the current
  background values from the curve and disables those functions to avoid counting
  them twice. This changes the data supplied to subsequent fits and normal exports.

For this Quick Start, use the second workflow and subtract the spline. If the result
is unsatisfactory, press **Ctrl+Z** immediately or choose **Data → Revert
background...** later. The imported original data remain retained.

## 4. Add the peaks

Choose a peak shape in the toolbar selector and press **Quick Add Function** once for
each visible peak. Click its centre and drag horizontally to either half-height edge;
the highlighted width is the complete initial FWHM. Repeat to add as many peaks as
needed. The selected Quick Add function is remembered.

Built-in peaks use signed integrated area:

- Gaussian: `area`, `center`, `sigma`
- Lorentzian: `area`, `center`, `gamma` (HWHM)
- Voigt: `area`, `center`, `sigma`, `gamma`
- pseudo-Voigt: `area`, `center`, `fwhm`, `eta`

Edit values directly in the parameter table. Empty lower/upper cells mean unbounded.
Check **Fixed** to hold a parameter. A link such as
`${curve_id.component_id.center}` can connect parameters in the same or another
spectrum.

For automatic starting values, choose **Model → Find Peaks**, select the peak sign,
then select any registered peak shape. Detected peaks are suggestions that should be
checked scientifically before fitting.

## 5. Adjust and mask graphically

Select a peak component. Drag its apex to change centre and area-derived height;
drag either side handle to change width. A fixed value shows a lock: hold **Ctrl**
while dragging to change the value while leaving it fixed. Use **Ctrl+Z** to undo.

Click the graphical **Mask** toolbar button; it becomes grey while active. Single
view acts on the displayed spectrum. Overlay/Waterfall asks whether to use the
active spectrum or all visible spectra. **Right-drag masks; left-drag unmasks.**
Click Mask again to resume normal navigation. Masked intervals are shaded and data
are faded. Point-transfer tolerance is under **Data → Mask transfer tolerance**.
Undo/Redo also restore fits; the latest 20 operations are retained.

## 6. Fit

When a sequential fit pauses, you can edit the model, lock/unlock parameters,
or run a manual fit. **Quick Fit** repairs only the active spectrum using
independent fitting while the sequential queue stays suspended. The prominent
**Continue sequential fit** button stays visible (teal in light mode, bright mint
in dark mode). Press it when ready:
the active, corrected spectrum becomes the source for the remaining spectra;
the saved sequential monitoring and propagation settings are retained.

With the spline actually subtracted, confirm that it is disabled and that only the
new peak functions contribute to the model. Press **F5**, select the active curve,
choose **Single / independent**, and start the fit. During optimization CurveMole
updates the trial model periodically without resetting a zoom chosen by the user.

Alternatively, press **Quick Fit**. On first use it fits the selected curves (or
the active curve when nothing is selected) independently with the default solver
settings, without opening a dialog. Once a fit has been configured, Quick Fit
reuses those settings. Use **Fit…** whenever you want to change them.

The other available modes are:

- Sequential
- Global simultaneous

Copy fit is available separately under **Model → Copy fit**. Ordinary constrained
least squares is the default. Robust losses and Differential Evolution are in the
advanced portion of the Fit dialog. Differential Evolution requires finite bounds.

In **Sequential** mode, the chosen initial source is treated as already approved and
is not re-fitted. Its model is propagated along the selected spectra. Choose which
constraints and component states to preserve, and configure residual/parameter-change
pause safeguards. If the sequence pauses, adjust the current spectrum and use the
visible **Continue sequential fit** button.

If you used only the visual background-subtracted view instead, leave the marked
background functions enabled: CurveMole fits the original data using background plus
peaks even though the plot is displayed with the background visually removed.

## 7. Inspect and export

Residuals appear under the curve. Open **View → Diagnostics** for interpretable
warnings and **Fit → Uncertainty Analysis** for explicit resampling.

Choose **File → Export analysis bundle**. Root files are intended for quick use in
Origin/QtiPlot and human inspection; `python/` contains Tidy data and versioned JSON.
The first export records its directory. Later updates overwrite only files owned by
the CurveMole export manifest and only after confirmation.

For directly replottable numeric tables, choose **File → Export spectra and fit
curves**. CurveMole writes one file per selected spectrum and can include the measured
data, individual functions, combined background, total fit, and residuals.

Save the complete workspace as `.fitproj`. Original values, masks, transformations,
models, custom functions, results, and history are embedded without pickle.
