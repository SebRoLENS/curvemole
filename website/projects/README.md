# Experimental fluorescence project

`experimental-fluorescence.fitproj` is a public, portable copy of a real working
project provided by its owner for the CurveMole website. This is measured data,
not a synthetic demonstration. It contains 14 series, 98 curves, 66 saved fit
records, block-bootstrap results for 47 curves and residual-bootstrap results for
32 curves, along with 1,432 history entries. Saved records include warnings,
failed or modified states and a sequential-fit pause requiring review; their
presence is not evidence of model validity or experimental validation of CurveMole.

Sample, series and measurement names have been replaced and local source paths
removed throughout the manifest and history. All numerical arrays (including
original data, masks, transformation operands, fit results and uncertainty
samples) are byte-for-byte preserved from the owner-supplied archive. The four
object descriptions are translated to English; the renamed original Italian
laboratory log is retained below an English overview. These editorial changes
do not alter numerical results.

The notebook documents saturation, repeat acquisitions, optical filtering and
an explicit modelling assumption: band centres in Sample I were imposed from
Sample G at matching pressures or extrapolated trends, with only areas fitted.
The selected screenshot fit is Sample G, measurement 09. Its saved block
bootstrap used 2,500 successful replicates, zero failed replicates and 95%
intervals. Attention flags remain visible. Interval endpoint stability does not
validate a model or guarantee confidence-interval accuracy.

## Rebuild screenshots

With the repository's runtime dependencies installed, from the repository root:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_project_screenshots.py
```

This opens the saved project in the actual CurveMole GUI and captures dark-mode
fit, overlay, waterfall, derived trends, notebook and uncertainty views. A matched
light-mode fit capture is used only in the website's light/dark comparison.
No fit or resampling is rerun. Settings and caches are isolated in a temporary
directory; the committed project is read, never overwritten.

`.github/workflows/website-screenshots.yml` regenerates these views when the
application source, public project or capture script changes, and supports manual
runs. It commits generated assets and dispatches the website deployment.

`website/scripts/prepare_experimental_project.py` documents how the owner-supplied
archive was renamed. Its input is intentionally absent from this repository.
The public project was saved using CurveMole 0.46.0. Scientific interpretation
should consult the original experiment; this public copy illustrates a workflow.
