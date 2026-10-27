# October beta audit — implementation ledger

All eleven functional findings and all five maintenance interventions from the
27 October 2026 report have an implementation below. Work is confined to
`testing`; stable source/citation versions and the stable publication branch are
unchanged. The implementation starts from `b153f94`, retaining the user's shortcut
corrections. The previously failed build is outside the audit scope.

## Functional corrections

| ID | Status | Implementation and verification |
| --- | --- | --- |
| F01 | Applied | `Model.evaluate_for_curve` evaluates convolutions on the complete current X grid before selecting residual indices. The fitter and sequential monitoring use it. Explicit sampling validation supports ascending/descending regular grids and rejects nonfinite, duplicate, nonmonotonic or irregular grids with an actionable error. Regression cases cover even/odd grid sizes, masks and disjoint fit ranges. |
| F02 | Applied | `Project.validate_curve_removal` checks external parameter references before any removal. `remove_curves` validates the entire group once, allowing links wholly inside a group removed together. GUI curve and series actions explain blocked removals; no links are silently converted to constants. |
| F03 | Applied | Curve and series Undo snapshot all result maps, per-method uncertainty maps and curve states, including other members of a global fit. Completed numerical results remain shared. Repeated remove/Undo cycles preserve baseline/array identity and analysis records. |
| F04 | Applied | `Project.invalidate_fits` expands transitively through equality/bound links and recorded global-fit groups. Manual edits and newly committed fits use it; recorded analyses remain historical rather than silently current. |
| F05 | Applied | Independent baselines extract `BlockDiagonalMatrix.submatrix` directly. Submatrix extraction visits only selected blocks. A regression object whose dense conversion raises still supports extraction. The global-fit path retains covariance coupling. |
| F06 | Applied | Duplicated components deeply detach nested metadata while retaining the existing background-history detachment rules. Tests mutate both original and copied nested lists. |
| F07 | Applied | Point reconstruction receives resolved project values. Linked peak previews use the constrained parameter context; commit preserves links and stores their resolved values. Cancel/no-op preserves the original component, and Undo restores it. Spline point reconstruction also uses effective node values. |
| F08 | Applied | Model-state commands pass their actual destination IDs to the shared edit invalidation path, independently of tree selection. |
| F09 | Applied | Simple and column formulas share an anchored assignment recognizer that distinguishes assignments from `==`, `!=`, `<=` and `>=`, retaining each entry point's variable restrictions. |
| F10 | Applied | Bound conversion and validation are atomic: every rejected update preserves both original bounds. |
| F11 | Applied | Exported workflow imports carry unique original curve identities. Model references and every occurrence inside link expressions are remapped on load, preserving reference scopes and relations. The final graph is validated even without a requested fit. Tests cover duplicate display names and repeated local/external references. |

## Maintenance interventions

| ID | Status | Scope and compatibility |
| --- | --- | --- |
| M01 | Applied to the two groups proposed for initial migration | Fit/Undo now uses explicit `FitLifecycleController` hooks instead of four dynamically installed completion/task wrappers. `RenderController` replaces the refresh wrappers for background display, masked samples and viewport preservation, with one ordered lifecycle. Static assignments to the seven audited GUI classes drop from 159 to 150. Other historical GUI extensions remain; the approved proposal was gradual consolidation, not wholesale removal of every wrapper. |
| M02 | Applied | `core.state.copy_result_maps` and `restore_model` centralize snapshot/restoration policy. Worker completion, fit Undo, curve removal and series removal use these utilities, preserving numerical arrays and live editor identities. |
| M03 | Applied with compatibility preserved | The historical ten-day notification helper and old single-suffix asset helper are isolated in `gui.legacy_updates`, with old import paths retained for external integrations. Application notification/asset policy remains in the modern controller. The obsolete masked-sample rendering implementation becomes a compatibility delegate to the canonical renderer. Format migrations and useful recovery compatibility are retained. |
| M04 | Applied | Formula assignment parsing is shared. `core.process_pool.bounded_results` supplies bounded submission, cancellation polling and pending-future cleanup to both independent fits and uncertainty jobs. Replica timing/activity checks remain explicit in the uncertainty layer. A regression stops consumption early and verifies cancellation without queuing the entire batch. |
| M05 | Applied | `RenderController.errors` records actionable evaluation failures per curve; notifications are deduplicated until recovery and rate-limited when messages change. The scene builder does not retry a failed evaluator during the same refresh. Both raised plugin exceptions and nonfinite model outputs leave rendering responsive; a successful evaluation clears the diagnostic. |

No functional finding F01–F11 has been omitted. No maintenance intervention has
been left without an implementation. M01 intentionally retains unrelated wrappers;
M03 intentionally retains isolated compatibility entry points, rather than breaking
external imports. These are compatibility boundaries of the proposed interventions.

## Local measurements

Reproduce from the repository root with:

```sh
PYTHONPATH=src python scripts/benchmark_audit.py
```

One Linux/offscreen sample, CPython 3.14.8, NumPy 2.4.6, SciPy 1.16.2 and
PySide6 6.11.2, with Python allocation tracing enabled:

| Synthetic workload | Elapsed | Peak traced allocations |
| --- | ---: | ---: |
| Extract all 200 independent baselines, 4 parameters each, legacy dense conversion | 0.422 s | 20,492,592 bytes |
| Same baseline workload, selected block extraction | 0.122 s | 1,098,913 bytes |
| Replay an edited background through 51 recorded operations, 10,001 points | 0.0041 s | 1,120,106 bytes |
| Serialize 100 retained worker payloads, 506,733 bytes each | 0.0380 s | 50,833,314 bytes |
| Submit/consume 2,000 trivial jobs, queue limit 8 | 0.0473 s | 59,481 bytes |
| Five overlay refreshes, 10 convolved curves of 10,001 points | 0.392 s | 16,616,864 bytes |

The baseline comparison includes equivalent baseline-copy work. Other rows are
workload measurements, not before/after speedup claims. These are single local
samples, not medians or native desktop measurements; traced allocations are not
process RSS. `audit-2026-10-27-benchmarks.json` preserves the measured values.

## Validation and release

The new regression module covers all eleven findings and queue/transaction/render
behavior. Existing coverage also exercises fit Undo, progressive/sequential fits,
viewport interaction, masks, GUI lifecycle, platform updates and workflow behavior.
The legacy workflow test now expects the destination curve ID while requiring all
relation/reference metadata to remain unchanged.

Final local validation: **1,617 passed, 1 skipped**, two known warnings, in
246.86 seconds. The skipped test executes the native Windows PowerShell helper.
The new regression module has 44 cases; additional targeted checks cover the
workflow's global fit and platform-independent rendering failure handling. Ruff,
Git whitespace validation and the repository's actionlint wrapper pass. An
offscreen GUI inspection also verifies masked convolutions with numerically zero
residuals on synthetic data. Native platform validation runs in the release CI.

The beta URL and CI outcome are recorded in the delivery message. Only a
successful `testing` pipeline may publish this change as a beta. Stable metadata
is not relabeled as beta in tracked sources.
