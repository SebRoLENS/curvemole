# Data Calculator and restoring original data

The Data Calculator uses the same native controls and theme as the rest of
CurveMole, grouped into three sections:

1. **Spectra to modify** — choose the active spectrum, the selected spectra, or a
   group to choose separately. The selected-spectra option shows its current count.
2. **Operation** — only the inputs relevant to the operation are shown. Saved
   formulas can be expanded when using custom or column formulas.
3. **Result** — review the destination/expression and the affected spectrum count
   before applying the operation. The Apply and Restore buttons remain accessible
   while scrolling through a long formula form.

**Selected spectra** means highlighted rows in the main spectrum list, including
all spectra belonging to a highlighted series. A spectrum's visibility checkbox
controls the graph and is independent of operation selection. An empty selection
disables Apply/Restore; it never falls back to modifying the active spectrum.

**Choose multiple spectra…** retains the separate selection window. It opens when
applying an operation or restoring data. The window supports the active series or
all series, a scrollable spectrum list, and selecting/deselecting all shown rows.
Cancelling it leaves the data and Undo history unchanged. Spectra are never listed
inline inside the Calculator.

## Restore original

A dedicated **Restore original data** icon sits directly beside **View options**
in the same toolbar group. Its menu offers the active spectrum, the selected
spectra, and the separate multiple-spectrum chooser. Restore remains available
inside the Calculator and uses the scope selected there.

Restoration uses the same operation as the existing Calculator: it removes recorded
data transformations and recomputes the original imported data. A batch is one
Undo action, so Undo restores the previous processing state for all affected
spectra. View options changes only the graph display; it does not restore data.

## Autoscale for new projects

New projects start with **Autoscale** enabled in **All points** mode. Turning it off
is saved with that project. Opening an existing project retains its saved choice;
older projects without an Autoscale setting retain their previous manual-view
behavior. Creating another new project starts with Autoscale enabled again.
