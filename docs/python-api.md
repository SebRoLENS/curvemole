# Python scripting reference

Applies to **CurveMole 1.1.0**, Python **3.12+**. This version-pinned reference
documents the GUI-independent scientific engine: callable names, argument names,
return values, side effects, and limits. Private names beginning with `_` and GUI
classes are outside this scripting contract. Record the installed version and
scientific dependency versions with your results.

## 1. Installation and imports

Install the 1.1.0 wheel in a Python environment, or run
`python -m pip install -e .` from a source checkout. A desktop executable is not
a general Python interpreter. Run scripts with `python analysis.py`; no Qt event
loop or open CurveMole window is needed. A script creates its own objects and does
not edit a project currently open in another desktop process.

The complete package-root exports are:

```python
from curvemole import (
    Component, Curve, Dataset, FitPlan, FitResult, FitSettings, Fitter,
    FunctionRegistry, Mask, Model, Parameter, Project, Series, Transformation,
    __version__, default_registry,
)
```

Import `FitMode` and `CancellationToken` from `curvemole.core.fitting`, and
`SequentialFitPlan` from `curvemole.core.sequential_fit` (also exported by
`curvemole.core`). The additional module-level helpers below are not root exports.
`FunctionRegistry()` starts empty; `default_registry()` is a shared mutable
registry containing the eight built-ins.

Choose Python for loops, conditionals, existing-project editing, transformations,
masks, explicit uncertainty analysis, custom export selections, or acquisition
integration. YAML provides the narrower import/model/fit/export pipeline.

## 2. Complete runnable example

This script generates input and writes only to a new output directory:

```python
# example: python-end-to-end
from pathlib import Path
import numpy as np
from curvemole import Component, Curve, FitSettings, Fitter, Project
from curvemole.core.export import BundleExportSelection, export_bundle
from curvemole.core.serialization import load_project, save_project


def main():
    out = Path("python-analysis-output")
    out.mkdir(exist_ok=False)
    x = np.linspace(-5.0, 5.0, 401)
    rng = np.random.default_rng(1729)
    y = 0.4 + 8.0*np.exp(-0.5*((x-0.7)/0.6)**2)/(0.6*np.sqrt(2*np.pi))
    y += rng.normal(0.0, 0.02, x.size)
    curve = Curve("synthetic band", x, y, sigma_y=np.full(x.size, 0.02))
    project = Project("Scripted analysis")
    project.add_curve(curve)
    model = project.model_for(curve.id)
    background = Component.create("constant", initial={"offset": 0.0})
    background.is_background = True
    peak = Component.create("gaussian", initial={"area": 7.0, "center": 0.5, "sigma": 0.8})
    peak.parameters["area"].set_bounds(0.0, 20.0)
    peak.parameters["center"].set_bounds(-2.0, 2.0)
    model.add(background)
    model.add(peak)
    result = Fitter().fit_single(curve, model, FitSettings(seed=1729))
    if not result.success:
        raise RuntimeError(result.message)
    project.results["last_fit"] = result
    project.snapshot("Python fit", {"result": result.to_dict()})
    project.touch()
    summary = export_bundle(
        project, out / "bundle", result=result,
        selection=BundleExportSelection.none(
            fit_results=True, wide_tables=True, results_json=True, readme=True,
        ),
    )
    saved = save_project(project, out / "analysis.fitproj")
    reopened = load_project(saved)
    print(result.statistics)
    print("Saved", saved, "curves:", len(reopened.curves))
    print("Created", len(summary.created), "bundle files")


if __name__ == "__main__":
    main()
```

`Fitter` updates successful model parameter values/errors and curve state. It does
not receive a `Project`, store project result records, add history, or save files:
the script does these explicitly. Check `result.success`, `message`, `warnings`
and, for sequential work, `paused_curve_id`.

## 3. Importing files and columns

Import the following from `curvemole.core.importers`:

| Callable | Return/purpose |
| --- | --- |
| `detect_config(path)` | `ImportConfig`; infer numeric text layout or supported SPE format |
| `inspect_file(path, config=None, *, rows=30)` | `FileInspection(path, config, columns, preview, warnings)`; preview is a pandas DataFrame |
| `import_file(path, mapping, config=None)` | `list[Curve]`, including multiple Y columns or X/Y pairs |
| `import_many(paths, mapping, *, config=None, series_name="Imported series")` | `Series` of curves in input order |
| `ImportPreview(path, config).curves(mapping)` | `list[Curve]`; parse once for repeated preview mappings |
| `repeated_spectrum_mappings(column_count, *, y_per_x=1, error_kind="none", first_column=0)` | `list[ColumnMapping]` for repeated positional groups |

`ImportConfig` fields/defaults: `delimiter=None`, `decimal="."`,
`comment_prefixes=("#", ";", "%", "!")`, `header=None`,
`encoding="utf-8-sig"`, `skip_rows=0`. With `config=None`, detection runs; an
explicit config uses its supplied/default values. Integer column selectors are
**zero-based**; string selectors match parsed column names.

`ColumnMapping` fields/defaults are:

| Field | Default | Meaning |
| --- | --- | --- |
| `x`, `y` | `None`, `[]` | Shared X selector and list of Y selectors |
| `pairs` | `[]` | Alternative `(x_selector, y_selector)` pairs |
| `sigma_x`, `sigma_y` | `None` | Standard-deviation columns |
| `weights`, `variance`, `inverse_variance` | `None` | Alternative weighting representations |
| `error_y_minus`, `error_y_plus` | `None` | Both interval half-width columns are required |
| `error_confidence_level` | `0.95` | Central interval confidence, strictly between 0 and 1 |
| `as_separated_files` | `False` | Retained import setting |
| `spectra` | `[]` | Per-spectrum `ColumnMapping` objects, each with one X and one Y |

Choose one Y uncertainty type: `sigma_y`, interval half-widths, `weights`,
`variance`, or `inverse_variance`. `sigma_x` can coexist, but X errors do not
implement orthogonal-distance regression. Repeated `error_kind` values are
`none`, `sigma_y`, `interval`, `asymmetric`, `weights`, `variance`,
`inverse_variance`; `interval` uses one half-width for both sides.

```python
from curvemole.core.importers import ColumnMapping, ImportConfig, import_file, inspect_file
preview = inspect_file("measurements.csv")
print(preview.columns, preview.warnings)
curves = import_file(
    "measurements.csv", ColumnMapping(x=0, y=[1], sigma_y=2),
    ImportConfig(delimiter=",", header=True),
)
```

Import validity depends on contents, not only suffix. Inspect metadata/warnings,
`curve.invalid`, and `curve.effective_mask`. SPE support covers calibrated,
one-dimensional, single-ROI WinSpec SPE 2.x, not arbitrary binary/multidimensional
SPE data. Imported numeric columns are retained for column formulas.

## 4. Curves, masks, and transformations

`Curve(name, original_x, original_y, ...)` requires at least two matching rows.
Scientific options: `sigma_x=None`, `sigma_y=None`, `weights=None`,
`weights_are_inverse_variance=True`, `error_y_minus=None`, `error_y_plus=None`,
`error_confidence_level=0.95`. Labels/units default to `x_label="x"`,
`y_label="y"`, `x_unit=""`, `y_unit=""`; `source=None`, `metadata={}`, and an
autogenerated `id` preserve provenance. Other fields include `visible=True`,
`colour="#0072B2"`, `fit_ranges=[]`, `masks={}`, `active_mask="Default"`,
`original_columns={}`, `column_labels={}`, `column_axes={}`. Prefer keywords
after the first three positional arguments.

Original coordinate/error/column arrays are immutable. Properties `x`, `y`,
`columns`, `row_indices`, `current_sigma_x`, `current_sigma_y`, `current_weights`,
`current_error_y_minus`, `current_error_y_plus` expose transformed data. Coordinate
properties are read-only views: do not assign to `curve.x` or `curve.y`.

| Curve method/property | Behavior |
| --- | --- |
| `len(curve)` | Current row count |
| `invalid` | Boolean invalid-data/error flags |
| `effective_mask` | `True` means excluded; union of invalid rows, **all** masks, and points outside every fit range |
| `fit_arrays(*, use_data_errors=True)` | `(x, y, residual_scale_or_None, current_indices)`; raises with fewer than two usable rows |
| `content_hash` | SHA-256 of current scientific data/masks/errors |
| `add_mask(name)` | Create/select empty named `Mask`; return it |
| `mask_point(x_value, *, name=None)` | Exclude nearest finite X; return current row index |
| `mask_interval(lower, upper, *, name=None)` | Inclusive range; return selected row count |
| `unmask_interval(lower, upper, *, name=None)` | Clear that mask's flags; return changed row count |
| `clear_mask(name=None)` | Clear one named/active mask |
| `transfer_mask_from(source, *, tolerance, source_name=None, target_name=None)` | Match masked X positions; return count |
| `move_points(indices, *, x=None, y=None)` | Record coordinate edits for current row positions |
| `delete_points(indices)` | Record deletions for current row positions |
| `apply_transformation(transformation)` | Apply and retain replayable history |
| `undo_transformation()`, `redo_transformation()` | `bool`: whether an operation was available |
| `restore_original()` | Clear transformations/redo and recompute original data |
| `to_metadata()` | Metadata, not a complete numeric serialization |

`Mask(name, excluded, ranges=[], id=generated)` stores Boolean exclusions.
`active_mask` selects the target for edits; it does not deactivate other masks.
`curve.fit_ranges=[(lo,hi), ...]` defines a union of fitting intervals.
`row_indices` retains original identities after point deletion.

`Transformation(operation, parameters={}, description="", created_at=generated,
operand=None)` is replayable. Prefer checked helpers from
`curvemole.core.calculator`; each modifies the curve and returns `Transformation`:

| Helper | Supported options |
| --- | --- |
| `apply_scalar(curve, operation, value=None)` | `y_add`, `y_subtract`, `y_multiply`, `y_divide`, `x_add`, `x_multiply` require a finite value; `normalize_max`, `normalize_area` need no value |
| `apply_custom_formula(curve, axis, formula)` | Axis `x` or `y`; only that coordinate variable is exposed; optional matching assignment such as `Y = 2*y` |
| `apply_column_formula(curve, target, formula)` | Target `x`, `y` or retained column key such as `c3`; access `x`, `y`, one-based `c1`, `c2`, ... and `${original column label}` |
| `apply_curve_operation(target, operand, operation, *, interpolation="linear", extrapolate=False)` | `curve_add`, `curve_subtract`, `curve_multiply`, `curve_divide`; interpolation `linear` or `nearest` |
| `apply_background_subtraction(curve, background, *, method, description, parameters=None)` | Subtract supplied array from all rows, including masked rows |

Curve arithmetic stores the interpolated operand as a snapshot. Without
extrapolation, out-of-range points become invalid; enabled linear interpolation
extends endpoint values. Formula output must be finite and match the row count;
scalars broadcast. Coordinate/column formulas propagate existing uncertainty
using a numerical first-order local derivative with respect to the target axis.
Affine scaling is exact; nonlinear propagation is a local approximation.
Asymmetric Y sides swap for a negative derivative. Uncertainty in other input
columns, correlations, and operand-curve errors are not jointly propagated.
Explicit weights are retained rather than recomputed by arbitrary formulas;
review their interpretation after changing Y. Normalization uses current data,
including masked rows.

```python
from curvemole.core.calculator import apply_scalar
curve.mask_interval(1.2, 1.3)
curve.fit_ranges = [(-4.0, 4.0)]
apply_scalar(curve, "y_multiply", 2.0)
curve.undo_transformation()
```

## 5. Projects, series, and datasets

`Series(name, curves=[], id=generated, metadata={})` offers `add(curve,
index=None)`, `remove(curve_id) -> Curve`, `move(curve_id, index)`.
`Dataset(series=[])` offers flattened `.curves`, `add_series(series)`,
`curve(curve_id) -> Curve`, `series_for(curve_id) -> Series`,
`transfer_curve(curve_id, target_series_id, index=None)`, `validate_unique_ids()`.

`Project(name="Untitled", ...)` owns `dataset`, `models` keyed by curve ID,
`results`, `fit_history`, `custom_functions`, `custom_formulas`, `notebook`,
`ui_state`, `export_config`, `path`, `read_only`, `dirty`, `revision`, and
timestamps/version metadata.

| Method/property | Result/side effect |
| --- | --- |
| `curves` | Flattened curve list |
| `add_series(series)` | Add series and create missing empty models |
| `add_curve(curve, series=None)` | Add to specified/default series, create model; return target `Series` |
| `validate_curve_removal(curve_ids)` | Check IDs and links before deleting; return None or raise |
| `remove_curves(curve_ids)` | Deduplicate ordered IDs, validate the entire selection, return removed curves |
| `remove_curve(curve_id)` | Return removed curve; validate remaining link dependencies and remove affected model/result records |
| `affected_curve_ids(curve_ids)` | Return set including transitive dependents and recorded global-fit coupling |
| `invalidate_fits(curve_ids, *, preserve=())` | Return affected IDs minus preserve; mark fitted curves Modified/outdated |
| `model_for(curve_id)` | Return/create curve's model |
| `add_component(curve_id, component)` | Add to model and mark project changed |
| `parameter_map()` | `{full_path: Parameter}` for all models |
| `resolved_parameter_values()` | Resolve links project-wide into `{path: float}` |
| `touch()` | Mark dirty, advance revision/timestamp; raises on read-only project |
| `mark_saved(path=None)` | Mark saved; normal scripts use `save_project` |
| `snapshot(reason, payload)` | Append history event; does not fit/save |
| `to_metadata()` | Metadata; serialization writes complete numeric projects |

`copy_fit(source_curve_id, target_curve_ids, *, structure=True, values=True,
bounds_and_fixed=True, links=True, background=True, masks=False,
fit_ranges=False, component_ids=None) -> None` atomically copies selected model
aspects across destinations. `component_ids` limits source functions; include
functions referenced by links. With `structure=False`, source positions match
the same destination positions. Relative links retarget to destination curves;
absolute references remain fixed.

Add a `Series` to the project before passing it explicitly to `add_curve`.
The default `ui_state` is `{"autoscale_enabled": True, "autoscale_mode": "all"}`.
Direct edits to contained objects do not call `Project.touch()` or refresh old
fit records. After edits, use `invalidate_fits([curve.id])`, call `touch()`, refit,
and replace stale result records. Invalidation changes fitted states, not result
payloads or project dirty state; dependent curves and recorded coupled global
fits are included. `preserve` excludes explicitly preserved IDs from that set.

Curve removal rejects any remaining parameter that refers to a removed curve,
raising `ConstraintError` before the removal starts; unknown IDs raise `KeyError`.
Selecting all mutually linked curves for `remove_curves` is allowed when no
remaining curve depends on them. Removal also marks coupled fits outdated and
cleans affected stored model/analysis records. Do not delete series/curves through
raw list manipulation when dependency validation is required.

## 6. Functions, components, and models

`Component.create(function_id, *, registry=None, name=None, initial=None,
metadata=None, operator="add") -> Component`. **`initial` is the Python keyword**,
not `parameters`. Creation uses only valid function parameter specs: missing keys
use defaults, unknown initial keys are ignored, and values are clipped to spec
bounds. Later explicit parameter validation rejects invalid values.

| Built-in ID | Parameters/defaults | Convention/metadata |
| --- | --- | --- |
| `gaussian` | `area=1`, `center=0`, `sigma=1` | Signed integrated area; Gaussian standard deviation; FWHM = `2.354820045*sigma` |
| `lorentzian` | `area=1`, `center=0`, `gamma=1` | `gamma` is HWHM; FWHM = `2*gamma` |
| `voigt` | `area=1`, `center=0`, `sigma=1`, `gamma=1` | Area-normalized Gaussian/Lorentzian convolution |
| `pseudo_voigt` | `area=1`, `center=0`, `fwhm=1`, `eta=0.5` | Common FWHM; Lorentzian fraction `eta` in `[0,1]` |
| `constant` | `offset=0` | Constant value |
| `linear` | `intercept=0`, `slope=0` | `intercept + slope*x` |
| `polynomial` | `c0=0` ... `cN=0` | `metadata={"order": N}`, default 2, allowed 0-50; ascending powers |
| `cubic_spline` | `y0=0` ... | Required `metadata={"x_nodes": [...]}`; at least two finite increasing nodes |

Peak widths have lower bound `np.finfo(np.float64).eps`; area/center may be
negative. Two-node splines use `np.interp` linear interpolation with constant
endpoint tails. Splines with three or more nodes use natural cubic boundaries
and cubic extrapolation. Components are not automatically marked as
background: set `.is_background=True`. Other component fields: `enabled=True`,
`group=None`, `metadata`, `id`, `name`, `function_id`, `parameters`, `operator`.
`to_dict()` / `Component.from_dict(value)` preserve state.

`Model(name="Model", components=[], ...)` offers:

| Method | Return/purpose |
| --- | --- |
| `add(component, index=None)` | Insert component; reject duplicate IDs |
| `remove(component_id)` | Return removed component |
| `delete_components(component_ids: set[str])` | Delete without changing surviving roles |
| `component(component_id)` | Look up component |
| `duplicate(component_id)` | Insert/return copy with new component ID |
| `move(component_id, index)` | Change list order |
| `set_component_operator(component_id, operator)` | Validate operator/background restrictions |
| `parameter_path(curve_id, component_id, name)` | Static method: `curve_id.component_id.parameter_name` |
| `parameter_map(curve_id)` | Full-path parameter mapping |
| `evaluate(x, *, curve_id=None, values=None, registry=None, components=False)` | Total ndarray; with `components=True`, `(total, {component_id: ndarray})` |
| `evaluate_for_curve(curve, indices, *, values=None, registry=None)` | Fit-row model values; evaluate convolution on the full curve before selecting indices |
| `background(x, *, curve_id=None, values=None, registry=None, component_ids=None, evaluated_components=None)` | Marked/selected background array |
| `derived_quantities(*, curve_id=None, values=None, registry=None)` | `{component_id: {quantity: float_or_None}}` |
| `calculation_expression()` | Human-readable composition |
| `validate(registry=None)`, `validate_composition()` | Check scientific parameter sets/operators |
| `clone()` | Deep model copy retaining IDs |
| `to_dict()`, `from_dict(value)` | Model state serialization |

Models use global roles: sum enabled `add` and subtract enabled `subtract`
components, then apply `multiply`, `divide`, `convolve` to the total.
`operation_order` contains operation component IDs; unspecified operations sort
by multiply/divide/convolve and ID. `display_order` / `display_components` control
presentation. Convolution uses FFT integration, absolute uniform X spacing, and a
centered crop. An actual convolution of two or more arrays requires a finite,
strictly monotonic, uniformly spaced X axis (increasing or decreasing); irregular
sampling, duplicates or invalid X raise `DataValidationError`. Resample explicitly
before convolution. Fitting evaluates convolution on the **full current curve
grid**, then selects unmasked/in-range residual rows, so masking does not change
the convolution grid. `evaluate_for_curve` implements this selection; for local
models it evaluates only selected X values. Its wrapper forwards `values`,
`registry`, and other compatible `evaluate` keywords, but `components=True` is
not a supported result-selection mode for convolution. Use `evaluate` directly
for component arrays.

For project-linked models, use
`model.evaluate(curve.x, curve_id=curve.id,
values=project.resolved_parameter_values())`. Without a `curve_id`, evaluation
uses the model ID prefix and cannot independently resolve other curves' links.
`curvemole.core.models.component_height(component, *, registry=None)` evaluates
a peak at its center; `area_for_height(component, height, *, registry=None)`
converts height to area for a component having an `area` parameter.

## 7. Parameters, bounds, and expression links

```python
Parameter(name, value, minimum=-math.inf, maximum=math.inf, fixed=False,
          link=None, unit="", standard_error=None, ci_low=None, ci_high=None,
          link_scope="relative", link_reference_scopes=[], link_relation="equal",
          link_tolerance=0.0, link_tolerance_mode="absolute")
```

`set_bounds(minimum=-math.inf, maximum=math.inf)` sets and validates bounds;
`validate()` rechecks fields. An invalid `set_bounds` raises and restores both
previous bounds atomically. Set the parameter value inside proposed bounds before
applying them; failed bounds do not clamp the value. `.is_free` excludes fixed and
equality-linked parameters; `.status` reports free/fixed/bounded/linked states.
`to_dict()` / `Parameter.from_dict(value)` preserve fields.

Full link paths use **IDs, not display names**, with `${...}` references:

```python
source = source_model.parameter_path(source_curve.id, source_peak.id, "sigma")
target_peak.parameters["sigma"].link = "${" + source + "}"
target_peak.parameters["sigma"].validate()
values = project.resolved_parameter_values()
```

`curvemole.core.parameters.resolve_parameter_values(parameters, *, paths=None)`
returns `{path: float}`, checking missing references, cycles and bounds. Equality
expressions can combine references, e.g. `2*${curve_id.component_id.sigma}+0.1`.

Relations `lower`, `upper`, `similar` keep targets free and require one direct
`${path}`. `lower`: target >= source; `upper`: target <= source; `similar`:
source +/- tolerance, intersected with static bounds. Similar tolerance must be
positive. `link_tolerance_mode="percent"` uses `abs(source)*tolerance/100`, with
tolerance < 100. Set target starting value inside the feasible interval.
`link_bounds(source_value)` returns intersected bounds or raises `ConstraintError`.

`link_scope` is `relative` (default) or `absolute` and governs copying.
`link_reference_scopes` can specify each reference occurrence's scope in order.
`effective_link_reference_scopes()` returns explicit/inherited scopes;
`copied_link(source_curve_id, target_curve_id, component_ids=None)` returns a
retargeted expression. Cross-curve links require a **global** fit including source
dependencies; independent fits cannot optimize another curve in their objective.

## 8. Safe expression vocabulary

`curvemole.core.expressions.SafeExpression.compile(source)` validates an
expression. `.variables` / `.references` are tuples; `.evaluate(variables=None,
references=None)` returns scalar/array values. `expression_parameters(source,
*, independent="x")` lists inferred parameter names.

Allowed functions are exactly `abs`, `sqrt`, `exp`, `log`, `log10`, `sin`, `cos`,
`tan`, `arcsin`, `arccos`, `arctan`, `sinh`, `cosh`, `tanh`, `erf`, `erfc`,
`minimum`, `maximum`, `clip`, `where`, `heaviside`. Constants: `pi`, `e`, `inf`.
Arithmetic: `+`, `-`, `*`, `/`, `**`, `%`, unary signs. Comparisons, `and`, `or`,
`not`, conditional expressions are supported. Use `**` for powers; advanced
column formulas also normalize `^`. Calls accept positional arguments only.
Attribute access (`np.exp`), imports, subscripting, comprehensions, arbitrary
calls/statements are unavailable. Write `exp(x)`, not `np.exp(x)`.

`curvemole.core.expressions.formula_source(formula, target) -> str` strips an
optional leading assignment to the matching target (case-insensitive), while
preserving comparisons such as `y == 1` and keyword-free conditional expressions.
An assignment to a different target raises `ExpressionError`. Coordinate and
column calculator helpers use this parser; it does not execute Python.

## 9. Custom formulas and function registry

Registry methods: `register(definition, *, replace=False)`,
`unregister(identifier)`, `get(identifier)`, `values() -> tuple`,
`identifiers() -> tuple`, `extend(definitions)`. Duplicate registration without
`replace=True` raises `DataValidationError`.

```python
from curvemole import Component, FunctionRegistry
from curvemole.core.functions import builtin_definitions, formula_definition
registry = FunctionRegistry()
registry.extend(builtin_definitions())
registry.register(formula_definition(
    "exponential_decay", "Exponential decay", "amplitude*exp(-x/tau)+offset",
    defaults={"amplitude": 3.0, "tau": 2.0, "offset": 0.0},
    bounds={"tau": (1e-6, 100.0)},
    derived_formulas={"half_life": "tau*log(2)"},
))
component = Component.create("exponential_decay", registry=registry)
# Supply the same registry to model evaluation and Fitter(registry).
```

`formula_definition(identifier, display_name, formula, *, kind="generic",
defaults=None, bounds=None, derived_formulas=None) -> FunctionDefinition` is in
`curvemole.core.functions`. Variables except `x` become parameters in sorted
order; missing defaults are 1, missing bounds unbounded. Derived formulas use
parameter names. `kind="peak"` does not convert arbitrary functions into built-in
area profiles.

Executable definitions from the same module use
`ParameterSpec(name, default, minimum=-math.inf, maximum=math.inf, unit="")` and
`FunctionDefinition(identifier, display_name, kind, evaluator,
parameter_specs=(), parameter_factory=None, derived={}, description="",
custom_metadata={}, configuration_specs=(), point_initializer=None,
minimum_points=None)`. Evaluator protocol: `(x_array, values_mapping,
metadata_mapping) -> shape-compatible numeric output`.
Methods: `specs(metadata=None)`, `make_parameters(initial=None, metadata=None)`,
`evaluate(x, parameters, metadata=None)`, `derived_values(parameters,
metadata=None)`. Nonfinite derived values and `ArithmeticError`, `ValueError`,
`TypeError` become `None`; other errors, including `ExpressionError` from an
invalid derived formula, can propagate.

Construction options are distinct from optimizable parameters:
`FunctionOptionSpec(name, label, default, kind="integer", minimum=None,
maximum=None, choices=(), description="", from_points=None)` from
`curvemole.core.functions`. `kind` is `integer`, `number`, `boolean`, `text`, or
`choice`; `.validate(value)` returns the accepted value or raises
`DataValidationError`. Numeric options require finite values and inclusive
bounds; integers exclude booleans. Choice values must belong to `choices`.

`FunctionDefinition.configuration(metadata=None)` returns a new dictionary with
validated supplied/default option values, preserving other metadata keys.
`specs` validates configuration before calling `parameter_factory`; component
creation stores the configured metadata. This makes polynomial `order` an actual
integer construction option, default 2, from 0 through 50, rather than a fitted
coefficient or silently converted string.

`has_point_configuration` reports whether any option supplies `from_points`.
`configuration_from_points(x_array, y_array, metadata)` infers such option values
with each `from_points(x,y)` callback, validates them, then fills other option
defaults. An optional `point_initializer(x_array, y_array, configured_metadata)`
returns an initial parameter mapping. `minimum_points` supplies host guidance;
these direct methods do not enforce the minimum by themselves. Check point
count/finiteness and callable presence before using them in scripts.

Built-in polynomial point configuration infers `order = point_count - 1` from
distinct X points, rejects degree above 50, and estimates coefficients in the
public ascending `c0 + c1*x + ...` basis. Its `minimum_points` is 2. Numerically
unreliable interpolation raises `DataValidationError` instead of silently
installing bad coefficients:

```python
import numpy as np
from curvemole import Component, default_registry
poly = default_registry().get("polynomial")
xp, yp = np.array([0.0, 1.0, 2.0]), np.array([1.0, 3.0, 7.0])
metadata = poly.configuration_from_points(xp, yp, {})
initial = poly.point_initializer(xp, yp, metadata)
component = Component.create("polynomial", metadata=metadata, initial=initial)
# order=2; c0=1, c1=1, c2=1, within numerical precision.
```

Option callbacks and point initializers are Python callables, not executable
syntax accepted by YAML or safe formulas. Persist their configured numeric
metadata/parameters; installed plugin source supplies custom callback code.

Registration does not persist executable source. Store safe specifications in
`project.custom_functions` with keys `identifier`, `display_name`, `formula`,
`kind`, `defaults`, `bounds`, `derived_formulas`. This project key differs from
YAML custom function specifications, which use `derived`.
After loading a project/model in a fresh process, explicitly rebuild/register
those formulas; loading data does not execute plugins:

```python
from curvemole import FunctionRegistry
from curvemole.core.functions import builtin_definitions, formula_definition
registry = FunctionRegistry()
registry.extend(builtin_definitions())
for spec in project.custom_functions:
    registry.register(formula_definition(
        spec["identifier"], spec.get("display_name", spec["identifier"]), spec["formula"],
        kind=spec.get("kind", "generic"), defaults=spec.get("defaults"),
        bounds={name: tuple(pair) for name, pair in spec.get("bounds", {}).items()},
        derived_formulas=spec.get("derived_formulas", {}),
    ))
```

Plugin modules expose `register(api)` (the legacy entry point can accept a
registry-compatible facade). `api.version == "1"`;
`api.register(FunctionDefinition)` adds a function;
`api.add(kind, identifier, label, callback, *, description="", auto_show=False)`
returns `<plugin_identifier>:<local_id>`; local IDs must be unique across kinds.
Plugins cannot replace existing functions. A local plugin consists of a manifest
ending `.curvemole-plugin.json` plus a Python module. Minimal manifest:

```json
{"identifier":"org.example.tools","version":"1.0.0","api_compatibility":"1",
 "licence":"MIT","capabilities":["workflows"],"module":"tools.py"}
```

`curvemole.core.plugins.PluginManager(registry=None, *,
trusted_identifiers=None, storage=None)` offers
`discover_local(directory) -> list[PluginCandidate]`,
`discover_entry_points() -> list[PluginCandidate]`,
`load(candidate, *, trust=False, expected_fingerprint=None) -> PluginMetadata`,
`disable(identifier, reason=None)`, `remove(identifier)`. A supplied fingerprint
must match the current source before it is loaded; a mismatch raises
`CurveMoleError` and requires review/trust of the changed source. Loading requires
explicit trust or a trusted identifier; code runs with normal user permissions.
`autoload() -> set[str]` synchronously loads enabled installed plugins and returns
failed identifiers. `autoload_steps() -> Iterator[tuple[str,bool]]` performs one
enabled plugin load per iteration, yielding identifier/success. Disabled or
already-loaded plugins are skipped; source fingerprints are rechecked. Setting
`CURVEMOLE_DISABLE_PLUGINS=1` suppresses autoload. `load_timings` records elapsed
seconds for iterated loads; iterators must be consumed to perform their work. Python entry-point discovery
uses group `curvemole.functions`. For a script using trusted plugin functions,
load the reviewed candidate, then use the same registry with `Fitter`.

| Extension kind | Callback/result |
| --- | --- |
| `importers`, `transformations`, `actions`, `workflows` | `callback(context)`; edit detached project snapshot; desktop commits successful return as one Undo step |
| `exporters` | `callback(context)`; chosen path is `context.path`; own external file write |
| `analysis` | `callback(context)`; return readable result text |
| `panels` | `callback(context)`; return new QWidget, requires desktop Qt host |
| `plot_layers` | `callback(context)`; return list of `{x, y, colour}` line mappings |
| `hooks` | `callback(event, context)`; events startup/project_refreshed/shutdown |
| `fit_solvers` | `callback(request)`; return solver result protocol below |
| `import_processors` | `callback(context)`; process only the new acquisition in a background worker |

Desktop context fields are `project` (detached snapshot), `project_id`,
`active_curve_id`, `selected_curve_ids` (tuple), `path`, `owner`, and `data`
(plugin-owned JSON dictionary saved in `project.ui_state["plugin_data"]`). Empty
projects may have no active curve. Read-only callbacks (analysis, exporter,
panels, plot layers, hooks) do not commit snapshot changes. General mutating
commands conservatively invalidate fits. These host semantics require the
extension host; manually invoking a callback does not create a desktop commit.

An import processor instead receives a fresh acquisition project, owner settings
and `context.cancellation`; pass that token to fits. It must not access Qt or
shared GUI objects. The host merges completed acquisition series/models/results;
acquisition UI state/notebook changes are not merged. Plugin loading does not
start folder monitoring or execute a workflow automatically.

Solver request fields: `initial`, `bounds` (lower/upper arrays),
`residual(vector)`, `jacobian(vector)`, copied `settings`, `cancellation`.
Return an object with `x`, `success`, `status`, `message`, nonnegative integer
`nfev`, e.g. SciPy OptimizeResult. Respect bounds/evaluation budget, use supplied
residual to retain masks/weights/constraints, and check cancellation in long
loops. The host recomputes residual/Jacobian and statistics, without applying a
second built-in optimizer. Registered solver IDs work in `FitSettings.solver`.
Plugin errors quarantine their owner at hosted boundaries; plugins are not
sandboxed. This reference does not make arbitrary internal GUI methods stable.

## 10. Initialization helpers

Import from `curvemole.core.initialization`:

| Callable | Return |
| --- | --- |
| `find_peak_suggestions(curve, *, sign="positive", prominence=None, distance=None, max_peaks=50)` | Prominence-sorted list; sign positive/negative/both |
| `PeakSuggestion(x, height, fwhm, prominence, sign)` | Center, signed height, FWHM estimate, prominence, sign +/-1 |
| `component_from_suggestion(suggestion, function_id="gaussian", *, registry=None)` | Estimated Gaussian/Lorentzian/Voigt/pseudo-Voigt |
| `initialise_peak_component(component, suggestion, *, registry=None)` | Modify/return peak, including recognized custom peak roles |
| `initialise_spline_component(component, points, *, registry=None)` | Modify/return spline; sorted unique finite `(x,y)` nodes, Y parameters fixed |
| `estimate_background(curve, function_id="constant")` | Constant or linear estimate; mark background yourself |

Suggestions respect effective masking and may be empty. Inspect them before
accepting their starting values as physical parameters.

## 11. Fitting, plans, callbacks, and concurrency

```text
Fitter(registry=None)
Fitter.fit_single(curve, model, settings=None, *, cancellation=None, progress=None)
Fitter.fit(plan, curves, models, *, cancellation=None, progress=None,
           on_curve_result=None)
FitPlan(curve_ids, mode=FitMode.INDEPENDENT, settings=FitSettings(),
        spectrum_weights={}, equal_contribution=False)
```

Both fitting methods return `FitResult`; `curves` is an ID mapping or sequence,
`models` maps curve IDs to models. `FitMode.INDEPENDENT`, `.SEQUENTIAL`, `.GLOBAL`
have string values `independent`, `sequential`, `global`. Legacy `.COPY`/`copy`
is accepted by the enum but does not copy structure in `Fitter.fit`; explicitly
call `Project.copy_fit` first.

Independent fits use each existing curve/model separately; global fits jointly
optimize selected curves and cross-curve links. The core package installs the
propagating sequential implementation automatically. Its **first selected curve
is a prepared seed and is not fitted again**. Prepare/fit that curve explicitly
before the sequential call. Subsequent curves receive copied source functions
by component ID; existing functions with those IDs are retained, not overwritten.
An initially empty target model is usually appropriate for full propagation.
The models collection must be mutable because targets may be replaced.
Prefer `SequentialFitPlan` for the controls below.

`SequentialFitPlan` extends `FitPlan` with defaults:
`monitor_residuals=True`, `residual_ratio_limit=2.5`, `residual_nrmse_delta=0.02`,
`monitor_parameters=True`, `parameter_change_limit=0.75`,
`propagate_bounds=True`, `propagate_fixed=True`, `propagate_links=True`,
`propagate_background=True`, `propagate_enabled=True`,
`propagate_composition=True`, `ignored_component_ids=()`,
`excluded_copy_component_ids=()`, `copied_component_ids=None`,
`progress_completed=0`, `progress_total=None`.
**Pass `mode=FitMode.SEQUENTIAL`**; the inherited mode default is independent.
Anomalies may pause a series. Inspect `paused_curve_id`, correct and explicitly
refit that model, then submit a new ordered sequential plan beginning with that
corrected curve as its seed, followed by the remaining curves. A plan containing
only its seed returns success with zero fits and no curve outputs.
There is no `Fitter.resume()`.

```python
from curvemole import FitPlan, FitSettings, Fitter
from curvemole.core.fitting import FitMode
ids = [curve.id for curve in project.curves]
plan = FitPlan(ids, mode=FitMode.GLOBAL, settings=FitSettings(loss="soft_l1"))
result = Fitter().fit(plan, project.curves, project.models)
```

`progress(value, text)` receives fraction or `None` and status text.
`on_curve_result(curve_id, result)` reports independent spectra, not per-spectrum
global/sequential updates. `CancellationToken().cancel()` requests cooperative
cancellation; pass the token to fit and handle `FitCancelled`.

`workers>1` enables **independent multi-curve** process parallelism. It does not
split global/sequential objectives. Workers reconstruct built-ins and safe
formula functions, not arbitrary executable/plugin definitions; use `workers=1`
for those. Put process-launching entry points under
`if __name__ == "__main__":`; add `multiprocessing.freeze_support()` if packaging
a frozen executable. Notebook kernels may not support spawning processes.

## 12. Complete FitSettings catalogue

All names are actual constructor keywords; `settings.validate()` checks them.

| Field | Default | Meaning/choices |
| --- | --- | --- |
| `solver` | `"local"` | `local`, `trf`, `dogbox`, `lm`, `differential_evolution`, `nelder_mead`, `powell`, `lbfgsb`; loaded solver extensions may add IDs |
| `local_method` | `"auto"` | `auto`, `trf`, `dogbox`, `lm`; local/DE refinement |
| `loss` | `"linear"` | `linear`, `soft_l1`, `huber`, `cauchy` |
| `f_scale` | `1.0` | Positive robust-loss residual scale |
| `max_nfev` | `1000` | Positive function-evaluation budget |
| `ftol`, `xtol`, `gtol` | `1e-10`, `1e-8`, `1e-10` | Positive least-squares tolerances above machine precision |
| `x_scale` | `"jac"` | Jacobian scaling or positive scalar |
| `seed` | `1729` | Integer 0-4294967295 |
| `workers` | `1` | Positive process count |
| `confidence_level` | `0.95` | Strictly between 0 and 1 |
| `absolute_sigma` | `None` | Automatic covariance error scaling; `True`/`False` overrides |
| `use_data_errors` | `True` | Apply imported errors/weights; False retains invalid-error rows if X/Y finite |
| `de_maxiter`, `de_popsize` | `400`, `15` | Positive generations/population multiplier |
| `de_lower_percent`, `de_upper_percent` | `50.0`, `50.0` | Positive automatic finite search-bound percentages |
| `de_mutation_min`, `de_mutation_max` | `0.5`, `1.0` | `0 <= min <= max < 2` |
| `de_recombination` | `0.7` | Between 0 and 1 |
| `de_tol`, `de_atol` | `0.01`, `0.0` | Finite nonnegative DE tolerances |
| `nm_xatol`, `nm_fatol` | `1e-4`, `1e-4` | Positive Nelder-Mead tolerances |
| `nm_adaptive` | `False` | Adaptive simplex coefficients |
| `nm_initial_simplex` | `None` | Finite `(N+1) x N` numeric list for active free parameters |
| `minimize_maxiter` | `0` | Nonnegative iteration limit; 0 automatic |
| `powell_xtol`, `powell_ftol` | `1e-4`, `1e-4` | Positive Powell tolerances |
| `lbfgsb_ftol`, `lbfgsb_gtol` | `2.220446049250313e-9`, `1e-5` | Positive L-BFGS-B tolerances |
| `lbfgsb_maxls`, `lbfgsb_maxcor` | `20`, `10` | Positive line-search/history limits |

Auto local method selects TRF with bounds or robust loss, otherwise LM. Explicit
LM requires an unbounded ordinary least-squares problem; peak widths are bounded
by default. Differential evolution performs a finite search followed by local
refinement. Static finite bounds override automatic search percentages. Simplex
dimensions must match active free parameters; dynamic coordinates need care.

Y standard deviations scale residuals by `1/sigma_y`. A directly constructed
`Curve(weights=...)` defaults to inverse-variance weights and scales by
`sqrt(weight)`; set `weights_are_inverse_variance=False` for direct residual
multipliers. In contrast, imported `ColumnMapping.weights` already means direct
residual multipliers, while `inverse_variance` means square-root scaling and
`variance` means inverse-square-root scaling. Interval half-widths use their
confidence level and residual side. `spectrum_weights` multiplies residuals by `sqrt(spectrum_weight)`;
`equal_contribution=True` also divides each by `sqrt(usable_row_count)`.
These choices affect chi-square interpretation. `f_scale=1` does not estimate
instrument noise.

## 13. Results and diagnostics

`FitResult` fields: `success`, `mode`, `message`, `status`, `evaluations`,
`parameters`, `curve_outputs`, `statistics`, `warnings`, `settings`,
`free_parameter_paths`, `covariance`, `correlation`, `timestamp`,
`elapsed_seconds`, `cancelled`, `paused_curve_id`.

`parameters[path]` is `ParameterEstimate` with `path`, `value`, `standard_error`,
`ci_low`, `ci_high`, `minimum`, `maximum`, `status`, `link`, `at_bound`, `fixed`,
`link_relation`, `link_tolerance`, `link_tolerance_mode`, `global_minimum`,
`global_maximum`. Missing errors/limits are `None`, not zero. `.to_dict()`
returns a plain mapping.

`curve_outputs[curve_id]` is `CurveFitOutput` with `curve_id`, `indices`, `x`,
`observed`, `fitted`, `residual`, `weighted_residual`, `statistics`. Arrays contain
only fitted rows. `indices` indexes current rows;
`curve.row_indices[output.indices]` recovers original identities. Reported
residual is **observed minus fitted**; optimizer residual has opposite sign.

Global statistics: `N`, `k`, `degrees_of_freedom`, `RSS`, `RMSE`, `chi_square`,
`reduced_chi_square`, `R_squared`, `AIC`, `AICc`, `BIC`. Per-curve statistics:
`N`, `RSS`, `RMSE`, `R_squared`. AIC/AICc/BIC are unavailable for robust losses;
insufficient degrees/rank may leave covariance unavailable. Matrix rows follow
`free_parameter_paths`. Independent-batch matrices may be `BlockDiagonalMatrix`;
`np.asarray(matrix)` densifies and can require substantial memory.

`result.to_dict(arrays=False)` omits sampled curve/matrix arrays;
`to_dict(arrays=True)` includes them. `FitResult.from_dict(mapping)` restores
only outputs with complete arrays. Save full arrays for uncertainty baselines.

`curvemole.core.diagnostics.residual_diagnostics(residual, *, max_lag=None,
histogram_bins="auto") -> ResidualDiagnostics` returns standardized residuals,
histogram, Q-Q arrays, autocorrelation, Durbin-Watson statistic, outlier indices,
warnings; `.summary()` returns compact statistics.
`estimate_block_length(residual)` estimates bootstrap block length.

## 14. Explicit uncertainty analysis

From `curvemole.core.uncertainty`, import `UncertaintyAnalyzer`,
`AdaptiveReplicateSettings`, `ResamplingResult`, `ProfileResult`.
`UncertaintyAnalyzer(fitter=None, *, replica_timeout_seconds=None)` uses a
60-second per-replica timeout by default. Supply a fitter using the baseline's
registry, successful current baseline, matching plan/data, and fitted models.

Three methods return `ResamplingResult` and share arguments
`(baseline, plan, curves, models, *, replicates=200, adaptive=None, seed=None,
workers=1, cancellation=None, progress=None)`:

- `parametric_monte_carlo(...)`: requires finite positive sigma_y or valid
  confidence-interval Y errors on fitted rows; weights alone are insufficient.
- `residual_bootstrap(...)`: resamples residuals around the fitted model.
- `block_bootstrap(..., block_length=None, ...)`: residual blocks; None estimates
  block length for each curve.

```python
from curvemole import FitPlan
from curvemole.core.uncertainty import UncertaintyAnalyzer
plan = FitPlan([curve.id], settings=result.settings)
analysis = UncertaintyAnalyzer().residual_bootstrap(
    result, plan, [curve], {curve.id: model}, replicates=200, seed=1729,
)
print(analysis.intervals, analysis.completed, analysis.failed)
project.results["bootstrap_python"] = analysis.to_dict()
project.touch()
```

Result fields: `method`, `requested`, `completed`, `failed`, `seed`,
`parameter_paths`, `samples` (replicate-by-parameter), `intervals` (path to
(low,high)), `confidence_level`, `configuration`, `failure_messages`.
`to_dict(include_samples=True)` controls stored samples. Inspect failed attempts;
`seed=None` uses the baseline settings seed. Replicas use local optimization,
including when the baseline used another solver. `replicates` must be positive;
replica failures reduce the number of accepted samples, rather than silently
counting as successful fits.

`AdaptiveReplicateSettings(initial_successes=500, batch_successes=200,
tolerance=0.05, consecutive_checks=3, maximum_attempts=10000)` stops when all
percentile endpoints stabilize for the required checks; `.validate()` checks
settings. `maximum_attempts` caps attempts.

`profile_parameter(baseline, curve, model, parameter_path, *, lower=None,
upper=None, points=31, confidence_level=0.95, spectrum_weight=1.0,
equal_contribution=False, workers=1, cancellation=None, progress=None)` returns
`ProfileResult` with `parameter_path`, `values`, `delta_chi_square`,
`confidence_level`, `interval`, `failed_points`, and `.to_dict()`. Limits must be
finite/increasing and inside parameter bounds; at least three points are needed.
Equality-linked targets and joint cross-spectrum linked profiles are unavailable;
use resampling for the linked global case.

`resampling_batch(method, jobs, *, replicates, option=None, workers=1,
adaptive=None, cancellation=None, progress=None, on_result=None)` returns a list
for jobs `(baseline, plan, curves_mapping, models_mapping)`. Method IDs:
`monte_carlo`, `residual_bootstrap`, `block_bootstrap`; option supplies block
length. Batch callbacks are `progress(completed_job_count)` and
`on_result(job_index, result)`; other uncertainty progress uses `(fraction,text)`.

Analysis calls do not create the desktop's per-curve uncertainty display records.
A custom key in `project.results` stores returned data but does not imply GUI
selection/integration.

## 15. Saving projects/models and YAML interoperability

Import from `curvemole.core.serialization`:

| Callable | Return/behavior |
| --- | --- |
| `save_project(project, path, *, include_uncertainty_samples=True, portable=False, update_project_path=True)` | `Path`; atomic `.fitproj`, creates parent and normalizes suffix |
| `load_project(path, *, partial_recovery=False)` | Restored `Project` |
| `validate_project_archive(path, *, raise_on_error=True)` | `list[str]` failures; raises by default when nonempty |
| `capture_project_snapshot(project)` | Detached `ProjectSaveSnapshot` |
| `save_fitmodel(model, path, *, custom_functions=None)` | `Path` to JSON `.fitmodel` |
| `load_fitmodel(path)` | `(Model, list_of_custom_function_specs)` |
| `ProjectLock(Path(path))` | Context manager; inspect `.acquired` before shared-file edits |

`portable=True` strips local paths. Detached snapshots require
`update_project_path=False` when saving. Project schema is **4**, model/workflow
schemas **2**. Archives contain JSON/numeric arrays, not pickle. Older project
schemas remain readable. An otherwise readable project with a newer schema opens
read-only; invalid schema numbers or damaged content raise `ProjectFormatError`.
Unsupported model-file schemas raise `ProjectFormatError`.
`load_project` does not acquire a project
lock and `save_project` does not itself honor another process's lock: coordinate
shared-file writes. `load_fitmodel` retains IDs and links; retarget links or use
`Project.copy_fit` when applying to a different curve.

`curvemole.core.workflow` exports `load_workflow(path) -> dict`,
`validate_workflow(value) -> list[str]`,
`run_workflow(path, *, trust_plugins=None, registry=None) -> WorkflowOutcome`,
`dump_workflow(project, path) -> Path`. Outcome fields are `project`, `result`,
`outputs`. Relative paths resolve against the YAML directory. Dumping references
source imports/models; it does not embed arbitrary transformed current data or
all project state. Version 1.1.0 dump includes saved `curve_ids`, which the loader
maps to newly imported curve IDs in model selectors and `${...}` references.
Ambiguous display-name aliases are not used as selectors; explicit saved curve
identities disambiguate them. Links are resolved project-wide before fitting or
export. Save `.fitproj` for full scientific state. The YAML audit details the
complete import identity and reference format.

## 16. Tables, exports, figures, and notebooks

Import from `curvemole.core.export`:

| Callable | Return |
| --- | --- |
| `wide_dataframe(curve, model=None, *, registry=None, selection=None, parameter_values=None)` | DataFrame of current data, model, residual, components/errors/mask |
| `tidy_dataframe(project, *, registry=None, selection=None)` | Long DataFrame of all curves |
| `analysis_dataframes(project, *, registry=None)` | `(observations, components, curves)` DataFrames; identity `(curve_id, point_index)` |
| `parameter_dataframe(project, result=None, *, registry=None)` | Parameter/derived-value DataFrame |
| `fit_settings_dataframe(result)`, `uncertainty_dataframe(project)` | Settings/recorded uncertainty DataFrames |
| `export_dataframe(frame, path, *, delimiter=",")` | `Path` to numeric table |
| `export_function_parameters(project, path, *, include_covariance=False)` | `Path`; one row per spectrum with parameter/error columns |
| `export_parameter_covariances(project, parameter_path)` | `list[Path]`; covariance directory derives from parameter-file path; requires per-curve fit records |
| `value_with_error(value, error)` | Formatted value/error string |
| `export_bundle(project, directory, *, result=None, delimiter=",", versioned=False, overwrite=False, include_uncertainty_samples=True, selection=None, current_view=None)` | `ExportSummary`: directory and created/updated/unchanged/preserved_external path lists |

`ExportSelection` defaults all fields True except `original_x=False`: `x`, `y`,
`total_fit`, `residual`, `background`, `components`, `sigma_y`, `weights`,
`mask_flag`. Pass it to table functions; for linked curves, `wide_dataframe`
needs `parameter_values=project.resolved_parameter_values()`.

`BundleExportSelection` defaults every field True: `fit_results`, `fit_settings`,
`wide_tables`, `tidy_table`, `results_json`, `fitmodel`, `project_copy`,
`main_plot_png`, `main_plot_svg`, `html_summary`, `html_reproducibility`,
`pdf_summary`, `uncertainty`, `diagnostics`, `readme`, `laboratory_notebook`,
`spectra`, `function_parameters`, `parameter_covariances`, `current_view`.
`.none(**enabled)` enables only named items; `.to_dict()` / `.any_selected()`
inspect selection. Some items require results, recorded analyses or a
GUI-provided view. Pass `result` explicitly or set `project.results["last_fit"]`.
`versioned=True` uses a timestamped subdirectory. Default export refuses
collisions; `overwrite=True` updates CurveMole-owned files and preserves external
files. Keep the project's ownership metadata when rerunning.

`curvemole.core.spectrum_export` provides
`SpectrumExportOptions(subtract_background=False, unmasked_only=False,
include_background=True, include_components=True, include_total_fit=True,
include_residual=True)`, `spectrum_export_dataframe(project, curve_id, *,
options=None, registry=None) -> DataFrame`,
`export_spectra(project, directory, curve_ids, *, options=None,
registry=None) -> list[Path]`. Quick spectrum export writes destination files
directly; choose a new directory to preserve previous exports.

`export_figure(curves, models, path, *, registry=None, dpi=300, width=9.0,
height=5.5, transparent=False, include_components=True, include_residuals=True,
include_error_bars=True, parameter_values=None, theme="light") -> Path` creates
a standalone figure. Width/height are inches; theme is `light` or `dark`.
The `core.export` wrapper forwards these keywords to `core.figure_export`.

`generate_html_report(project, path, *, result=None, title=None, notes="",
full=False, registry=None) -> Path`;
`generate_pdf_report(project, path, *, result=None, title=None,
registry=None, curves=None) -> Path`. `curves=None` selects all project curves;
pass an iterable for a subset. Bundle selections avoid supplying plotting
internals. Renderers create standalone figures without importing pyplot or
changing the backend; a script using pyplot independently can choose `Agg`
before importing it.

`project.notebook.set_description(project, kind, object_id, text, curve_id="")`
sets descriptions with exact kind names `series`, `spectrum`, `function`.
For a spectrum use its curve ID as `object_id`; for a function use the component
ID and pass its curve ID separately. Free project notes go in
`project.notebook.notes`; call `project.touch()` after assigning them.
`curvemole.core.notebook.export_notebook(project, path) -> Path` exports notes
and descriptions.

## 17. Background edit and transaction helpers

These module helpers are for integrations that already manage edits explicitly;
they do not create GUI Undo commands or automatically mark/save a project.

`curvemole.core.background_edit.updated_background_history(curve, model,
component, *, values, registry)` returns a detached replay-validated
`list[Transformation]`, or `None` when that component is not a recorded subtracted
background. It replaces existing matching subtraction operands in their original
positions, including grouped backgrounds, rather than subtracting twice.
Supply current project-resolved values and the same function registry.
The input curve/history are not changed by this call. All required background
functions must be identifiable; invalid background values or an X-axis change
after subtraction raise `DataValidationError`. Subsequent processing/deletions
are replayed before a history is returned. A caller must separately commit the
returned history using its own transaction and invalidate affected fits.

`curvemole.core.state.copy_result_maps(results) -> dict` copies mutable outer
result-map containers and nested per-method map containers. Completed numerical
result payloads remain **shared**; it is not a deep clone of arrays/FitResult.
`restore_model(target, saved, refs=None) -> None` restores a saved model state
while retaining existing component/parameter objects matched by component ID and
parameter name. `refs`, when supplied, maps component ID to
`(component_object, parameter_mapping)`; missing objects are deep-copied from the
saved model. This is useful for undo/rollback with live edit references. Neither
helper validates links, invalidates fits, calls `Project.touch`, or writes files.

## 18. Other low-level utility contracts

These are module utilities, not additional YAML operations or a general desktop
job scheduler. Normal scripts should use `Fitter`/`UncertaintyAnalyzer` for worker
management.

`curvemole.core.process_pool.managed_process_pool(pool, *, drain=None)` is a
context manager yielding an owned executor, draining optional telemetry while
shutting it down and terminating remaining workers within bounded teardown.
`bounded_results(pool, inputs, submit, cancellation, stop, *, limit, tick=None)`
yields `(input_index, result)` as futures complete, with at most `max(1,limit)`
pending submissions. `submit(pool, input_value)` returns a Future; cancellation
is checked while waiting and optional `tick()` runs each cycle. On incomplete
exit it sets `stop` when supplied and cancels pending futures. Output order is
completion order; use the yielded index to recover input order.

`curvemole.core.release_channels.ReleaseVersion(major, minor, patch, final,
beta=0)` is an ordered frozen value object. `ReleaseVersion.parse(text)` accepts
`1.1.0`, `v1.1.0`, `1.1.0-beta.2`, `1.1.0b2` and returns `None` for invalid
version syntax. Properties `numbers`, `text`, `label` expose numeric tuple,
normalized tag text and readable label. `default_channel(version)` returns
`beta` for a parsed prerelease and `stable` otherwise.
`select_release(payload, channel)` selects the greatest eligible version from a
release mapping/list and returns its mapping or `None`. `channel` is stable/beta;
stable excludes prereleases and both exclude drafts or invalid tags. Invalid
payload/channel raises `ValueError`. These helpers perform no network access,
application update or release publication.

## 19. Errors and requesting a script from AI

From `curvemole.core.errors`: base `CurveMoleError`, `DataValidationError`,
`ExpressionError`, `ConstraintError`, `FitError`, `FitCancelled` (FitError
subclass), `ProjectFormatError`, `PluginTrustError`. Lookups can raise `KeyError`,
filesystem operations `OSError`. Fits may return `success=False` without raising;
inspect both errors and result diagnostics.

Specify input layout, selectors, units, model IDs, starting values/bounds,
outputs, uncertainty method and installed CurveMole version. Ask AI to use only
documented APIs, state assumptions, check success, retain warnings, preserve
input files, and provide a run command. Supply a few non-sensitive representative
rows when needed; repository source is unnecessary for this documented surface.

> Using the attached CurveMole 1.1.0 Python audit, write `analysis.py` for Python
> 3.12+. CSV has named columns `x`, `signal`, `sigma`. Fit constant background
> plus an area-normalized Gaussian near 520 with positive sigma, mask 530-532,
> report fitted values/errors/warnings, and save a new `.fitproj` plus numeric
> results in a new output directory. Use only documented APIs, guard the script
> entry point, check convergence, and state scientific assumptions.

For unsupported tasks, AI should name the missing capability rather than invent
methods. This document audits API/automation capabilities; it is not a security
certification or scientific validation of AI-generated analysis.
