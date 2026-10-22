# October 2026 audit patches

Local changes against the 0.46.0 source tree, grouped by the report's finding IDs.
No application version bump, release, or remote publication is included.

| Findings | Implementation |
|---|---|
| R01 | Imported numerical columns use owned immutable buffers shared across curves and current columns. Transformations replace changed columns. Deep copies preserve immutable buffers; archive loading deduplicates identical columns. |
| R02 | Independent covariance/correlation matrices retain blocks. Explicit submatrix extraction and dense conversion are available; archive encoding keeps the blocks and CSV export streams rows. |
| R03, R19 | Desktop rendering selects lightweight mask boundaries before creating overlays. Marker identity uses explicit attributes, including manual placement; ordinary size-5 Points remain visible and interactive. |
| R04 | Worker progress publishes copied parameter values through the queued partial-result channel. The GUI uses a transient display snapshot, preserving project/save state and viewport. Completion, failure and retirement clear it. |
| R05 | Import metadata retains effective configuration and per-spectrum mapping, including uncertainty columns. Workflow dump consumes that metadata and workflow execution autodetects when configuration is absent. Legacy import metadata remains supported. |
| R06 | Negative validation preserves the JSON payload and returns a nonzero domain exit status. |
| R07 | The active release controller respects automatic-check opt-out; manual checks remain available. The old independent network checker has been replaced by compatibility delegates. The plugin catalog retains its separate update policy. |
| R08 | A bounded expression cache eliminates repeated AST compilation; dynamic-coordinate decoding is reused without resolving the graph again. Equality fits prepare dependency order once, invalidating it when expressions/topology change; numerical values and bounds remain live. No persistent cache of numerical values is used. |
| R09 | Detection stops after a numerical sample, previews stop reading at the requested row limit, full text imports filter through a bounded spool, and SPE previews read only the requested samples per frame. |
| R10 | Resampling prepares full predictions, uncertainty scales, centered residuals and immutable columns once per analysis. Trial curves detach mutable state without deep-copying all experimental columns. |
| R11, R12 | Exports skip models for data-only selections, reuse evaluated components for background, and resolve project parameters once per spectrum batch. |
| R13 | Export checksums stream from files. |
| R14 | Polynomial evaluation uses NumPy's Horner evaluator. |
| R15 | Cosmic-ray detection scans peaks once per spectrum and reuses the candidates. |
| R16 | One refresh-scoped context provides resolved values, component arrays and background. Data, totals and components are created with their final displayed values. |
| R17 | Consolidated release checking, parameter-copy dialog/handlers and global background subtraction; fit defaults/progress now live directly in the fitter. Desktop launch and integration tests share a window factory. Other feature wrappers remain deliberately incremental. |
| R18 | Dense error bars render pixel-bin interval envelopes for the visible field. Envelopes preserve interval extrema; original experimental errors are unchanged. Sparse data retain full capped bars. |
| R20 | Fit undo captures models in the fit plan, including sequential targets, and preserves model/editor identities. |
| R21 | Shared viewport, release text, menu and covariance/correlation helpers replace duplicate implementations; obsolete dialog and background implementations were removed. |
| R22 | Numerical uncertainty propagation is restricted to linked parameters needing it. |
| R23 | Removed unused raw-sample helper and unreachable composition branch; formula parameters use the already compiled expression. |
| R24 | Removed unused Pydantic runtime dependency and regenerated uv.lock. |
| R25, R26 | Windows and onedir builds share one PyInstaller spec; both Linux workflows use one parameterized AppImage script. |
| R27 | Validator, catalog verification and installation share a stdlib fingerprint contract: normalized ordered paths, streamed content, excluded caches, rejected symlinks. |
| R28 | Calibration polling stops when hidden and resumes when shown. |
| R29 | Tests redirect application profile paths and Qt settings before application imports, without changing the user's home directory. |

## Compatibility

New saves use project schema **4** for block covariance matrices. Versions 1–3
remain readable; schema-4 archives require a reader supporting the new matrix
representation. See `project-format.md`. Global fit covariance remains dense.
The application version stays 0.46.0 pending the owner's release process.

## Allocation checks

Synthetic inputs with 100 rows produced the following unique original/current
column buffer totals (X/Y, errors and Python-object overhead are excluded):

| Spectra | Numeric input bytes | Shared column bytes |
|---:|---:|---:|
| 4 | 4,000 | 4,000 |
| 8 | 7,200 | 7,200 |
| 100 | 80,800 | 80,800 |

100 independent two-parameter covariance blocks store **400 elements** instead
of a 40,000-element dense covariance. Correlation is also kept in blocks.
These are allocation checks, not end-to-end application speed benchmarks.

## Verification scope

Regression coverage checks import sharing and transformation isolation, workflow
round trips, CLI status, bounded previews, AST compilation counts, block archive
round trips, real desktop Points visibility, live snapshot contents, error-bar
envelopes, evaluator counts, export batch resolution, update opt-out and plugin
fingerprint conformance. Existing scientific, GUI, archive and plugin suites are
also run. Native PyInstaller/AppImage/Windows/macOS builds and real-data
interactive profiling are not exercised locally.

Final local verification on 22 October 2026:

- Main suite: **1,314 passed, 1 skipped** (Windows PowerShell helper), with the
  expected duplicate-ZIP-member warning from the corruption test.
- Targeted October regression file: **15 passed**, including two additional
  worker/graph-invalidation tests added after the main suite began collection.
- Plugin suites: **54 passed** (16 cosmic rays, 5 Fityk, 20 Ruby, 1 TSV, 12 calibration).
- `ruff check .`, `git diff --check`, `uv lock --check`, and shell syntax validation
  of `scripts/build_appimage.sh`: passed.

Tests used Python 3.14 and a temporary test-tool virtual environment with system
scientific/Qt packages. This is not a claim of a complete `uv sync --locked`
platform matrix or native bundle validation.
