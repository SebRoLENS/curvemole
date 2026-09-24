# X-axis calibration

A standalone CurveMole plugin for reference-peak calibration. **No CurveMole core
changes and no automatic import interception.** Tested with CurveMole 0.28.4.

## Workflow

1. Enable this plugin in the Plugin Manager. Its dock opens automatically and can
   be reopened from View > Plugins: Panels > X-axis calibration.
2. **Load calibrant spectrum…** opens the ordinary CurveMole importer. Fit the
   calibrant's peaks with CurveMole's normal tools.
3. Select the calibrant in the plugin and **Read fitted peak centres**. Enter each
   corresponding **Known position**, the profile name and output unit. Alternatively,
   type measured centres and reference positions manually with **Add reference**.
4. Choose offset, linear, quadratic or cubic correction and **Calculate and save
   calibration**. Inspect RMS and individual residuals (predicted minus reference).
   Use more references than the minimum and distribute them across the target range.
5. Select a saved calibration and apply it to **ALL project spectra**, **selected
   spectra**, or the **active spectrum's series**. ALL includes the calibrant;
   choose selected/series if it should remain uncalibrated. Different groups may use
   different profiles. The panel summarises assignments.
6. **Export calibration…** writes a portable `.cmcal.json` file; **Import calibration…**
   adds a separate profile. Profiles and per-spectrum assignments also persist in
   `.fitproj` files, independently of plugin availability.

Newly imported data always retain their supplied X values. Calibration is exclusively
an explicit plugin operation. No import dialogs or native behaviour are replaced.

## Data and numerical behaviour

- Uses the same reversible `custom_formula` X transformation as the calculator.
  Original X/Y arrays remain unchanged. No interpolation/resampling of intensities.
- Reapplying/replacing a calibration starts from the axis before calibration, not
  from already corrected X. **Restore original X of selected spectra** removes the
  calibration and retains preceding transformations. Thus "original" means the
  pre-calibration axis, including any earlier intentional calculator edits.
- If transformations were added after calibration, undo those first before replacing
  or removing it. This avoids silently changing the meaning of later operations.
- A batch validates completely before it is committed, and has native Undo/Redo.
  Masks stay attached to points; mask/fit-range annotations follow the new axis.
  X uncertainties are scaled by the derivative (local first-order propagation).
  Uncertainty of the fitted calibration itself is not included.
- Existing fit results are invalidated and removed for affected spectra. Model
  parameters/bounds/backgrounds retain their old values: the plugin asks for
  confirmation, and they must be reviewed before refitting. Undo restores results.
- Increasing calibrations only; nonmonotonic polynomials are rejected across the
  entire target interval. Extrapolation requires explicit confirmation.
- Offset needs 1 reference, linear 2, quadratic 3, cubic 4. Exact interpolation of
  the minimum number of references does not demonstrate calibration accuracy.
- Units are explicit labels, not automatic unit conversion. Use profiles only with
  the input axis and instrument configuration they were constructed for.
- Imported JSON contains reference pairs, never executable code or file-supplied
  expressions. Coefficients are recomputed and validated locally.

## Compatibility and limitations

The plugin uses API-1 panel settings persistence and existing native import/undo
commands through the GUI services' window adapter. It does not monkey-patch classes,
replace commands or edit application files. This small GUI integration depends on
CurveMole's current `PluginServices._window` and `_push_change` interfaces; test it
when upgrading to incompatible future versions.

Disable/unload removes the dock and stops its child timer. Saved profiles and
calculator transformations remain readable even without the plugin.

## Tests

From the repository root:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest custom_plugins/x_axis_calibration/test_plugin.py
python scripts/validate_community_plugins.py
```
