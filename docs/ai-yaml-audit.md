# AI YAML automation audit - CurveMole 1.1.0

**Verified against CurveMole 1.1.0 on 2026-10-29.** Current workflow schema is 2;
schema 1 is also accepted. This file is a standalone, downloadable context document
for an AI creating CurveMole workflows. All core YAML contracts, defaults and
limitations needed for the supported workflow stages are included below. The
source repository and main manual are not prerequisites for using this audit.

This is an implementation/authoring audit, not a security certification. It does
not certify AI-generated scripts, plugins, or scientific results. Keep this file
with the software version it describes; verify compatibility before using another
release. Executable plugins need their own API documentation and explicit trust.

## Instructions to an AI author

1. Use the contracts below as the complete built-in workflow vocabulary. Do not
   invent keys, interpolation, processing stages or CLI flags. Use declared
   `curve_ids` and explicit component IDs for parameter links; display aliases
   alone are not parameter-reference identities.
2. Ask for missing input columns, units, uncertainty interpretation, model,
   initial values, parameter limits and output locations. Never infer physical
   assumptions merely to make the workflow run.
3. Return a complete schema-2 YAML document, matching validate/run commands,
   expected outputs and stated assumptions. Use unique aliases and explicit
   header/delimiter settings when known.
4. Respect path resolution and project-versus-bundle overwrite behaviour. Check
   JSON `success` as well as the process exit code.
5. For masks, transformations, links beyond the documented identity mechanism,
   explicit uncertainty analyses,
   repeated/conditional operations or existing-project editing, request the
   companion AI Python audit and write Python using its documented API.
6. Include a representative-data trial before recommending a batch run. Separate
   fit convergence from scientific validation of the result.

## Prompt to use with this file

> Create a CurveMole 1.1.0 workflow using only the attached YAML audit. My input
> files and column layout are: [describe or attach]. The scientific model and
> constraints are: [describe]. Save outputs to: [location]. Ask for missing
> assumptions. Return the complete YAML, validation/execution commands and any
> limitations. If YAML cannot perform a required step, tell me what the Python
> companion audit is needed for rather than inventing an unsupported field.

## Complete implementation contract

**Software: CurveMole 1.1.0. Workflow schema: 2 (schema 1 also accepted).**
This reference was checked against the implementation on 2026-10-29. It describes
the workflow runner, rather than every action offered by the desktop application.
Use the matching software version when reproducing an analysis.

## W1. What a workflow can do

A workflow imports explicitly listed data files into one new project and one
series, constructs models, optionally runs one fit plan, and optionally saves a
project and an analysis bundle. The scientific engine is the same engine used by
Python and the desktop application. YAML is a declarative recipe, not Python code
or a general task scheduler.

The execution order is fixed:

1. Parse and check the YAML root and supported schema.
2. Register custom formula functions, then load explicitly trusted plugins.
3. Create a fresh project and series; import files in their listed order.
4. Add components/constraints, remap declared curve identities in links, and
   resolve the complete parameter graph (even when no fit is requested).
5. Run the single optional fit plan.
6. Save `export.project`, then write `export.bundle`, when requested.

There are no YAML stages for masks, data transformations, background subtraction,
calculator operations, repeated fits, conditional branches, loops, glob expansion,
folder monitoring, opening an existing `.fitproj`, explicit Monte Carlo/bootstrap/
profile analyses, or graphical interaction. Loading a plugin registers its
extensions; it does not automatically invoke a plugin command, transformation,
import processor, or workflow. Use the Python API for operations outside this
contract. A plugin can register a fit solver usable through `fit.settings.solver`.

## W2. Run, validate, and inspect

Install the Python package in a Python 3.12+ environment for command-line use:

```bash
python -m pip install ./curvemole-1.1.0-py3-none-any.whl
curvemole --version
curvemole inspect spectrum.csv --json
curvemole functions list --json
curvemole validate workflow.yml --json
curvemole run workflow.yml --json
```

`python -m curvemole` is an alternative to the `curvemole` executable. The global
`--json` option may also appear before the subcommand. `run` accepts only the
workflow path, repeated `--trust-plugin IDENTIFIER` options, and `--json` beyond
the global options; it does not accept fit or export overrides.

Validation is intentionally limited in 1.1.0: it checks the schema value, a
nonempty `imports` list, and whether optional `models` and `fit` have the expected
outer container types. It does **not** load the data or check nested fields,
function identifiers, columns, constraints, convergence, plugin trust, or output
collisions. Successful validation is a preliminary check. Run the recipe on
representative input and examine results before batch use.

Normal JSON output from `run` has these keys:

```json
{"project": "Example", "success": true, "statistics": {}, "outputs": []}
```

`success` and `statistics` are `null` when no fit ran. `outputs` contains paths to
saved projects and created/updated bundle files; it omits unchanged bundle files.
The actual statistics object contains the fit statistics. `run` returns exit
code 0 when it returns normally, **even if `success` is false**. Batch callers must
check both the process status and the JSON `success` value. A failed fit can still
produce exports for inspection.

| Exit code | Meaning |
| --- | --- |
| 0 | Command returned normally; inspect fit success separately |
| 2 | Command-line usage error |
| 3 | Data/import failure; failed YAML validation reported as a result |
| 4 | Raised fit failure |
| 5 | Project archive failure |
| 6 | Other CurveMole domain error, including plugin/workflow errors |
| 10 | Unexpected failure, including some malformed nested YAML or file collisions |

For desktop use, select **Run automation** in the bottom **Automations** toolbar.
The first run asks for a `.yml` or `.yaml`; subsequent runs remember that file.
The adjacent menu provides **Choose automation…** and **Stop automation**. The
runner starts a separate process with its own fresh project and imported data.
It does not fit or change the currently open desktop project. Set `export` to
retain results. Stopping kills the worker; files already written remain. Only one
automation runs through this control at a time. The desktop application reports
nonconvergence separately from execution failure.

## W3. Complete runnable recipe

Save the following as `workflow.yml` beside the repository's
`examples/gaussian.csv` (or download that example into the same directory).

```yaml
# example: yaml-end-to-end
schema_version: 2
name: Reproducible Gaussian fit
series_name: Reference spectra

imports:
  - path: gaussian.csv
    config:
      delimiter: ","
      decimal: "."
      header: true
    columns:
      x: x
      y: [y]
      sigma_y: sigma_y
    aliases: [reference]

models:
  - curve: reference
    name: Background and Gaussian
    components:
      - function: constant
        id: baseline
        name: Baseline
        is_background: true
        parameters: {offset: 0.0}
      - function: gaussian
        id: peak
        name: Main band
        parameters: {area: 3.0, center: 0.3, sigma: 1.0}
        constraints:
          sigma: {minimum: 0.001, maximum: 5.0}

fit:
  mode: independent
  curves: [reference]
  settings:
    solver: local
    loss: linear
    max_nfev: 1000
    seed: 1729
    use_data_errors: true

export:
  project: outputs/gaussian.fitproj
  bundle: outputs/analysis
  versioned: true
```

Initial numbers must be appropriate for the actual data. Peak `area` is signed
integrated area, not peak height; `sigma` is a Gaussian standard deviation.
`is_background` marks a component for background-specific exports; it is not
automatically inferred from `function: constant`.

## W4. YAML and path rules

The document root must be a mapping. Use a single YAML document, spaces for
indentation, and literal field names from this reference. YAML is read with
`yaml.safe_load`. Use YAML booleans (`true`, `false`), `null`, integers and numeric
values rather than quoted versions of them. For example, `fixed: "false"` is a
nonempty string and is converted to true by the runner. Prefer ordinary decimal
notation such as `0.00000001` when a parser might read an exponent as a string.
YAML `.inf`/`-.inf` can represent unbounded limits; `null` cannot replace a numeric
bound.

All relative input paths, plugin manifest paths, project output paths and bundle
paths resolve against the **workflow file's directory**, regardless of the
terminal working directory. Absolute paths are also accepted. Paths are literal:
`~`, environment variables such as `$HOME`, and wildcard expressions such as
`*.csv` are not expanded. Quote Windows paths with single quotes or use forward
slashes. Each `imports` entry names one actual file. Extensions alone do not
determine whether the text importer can read a file; supported calibrated WinSpec
SPE 2.x spectra also use the importer.

Unknown keys are not uniformly rejected. Unused top-level/model/component keys
can be silently ignored; unknown keys passed to `ImportConfig`, `ColumnMapping`
or `FitSettings` raise errors. Unknown entries in `parameters` are ignored because
only a function's declared parameter names are constructed. Do not treat YAML
acceptance as proof that every intended operation occurred.

## W5. Top-level fields

| Key | Type/default | Contract |
| --- | --- | --- |
| `schema_version` | Required integer | Use `2`; `1` is accepted with the current global composition semantics |
| `name` | String; workflow filename stem | New project name |
| `series_name` | String; `Workflow data` | Name of the single imported series |
| `custom_functions` | List; `[]` | Formula function definitions; registered before plugins and models |
| `plugins` | List of manifest paths; `[]` | Local `.curvemole-plugin.json` files; explicit trust required |
| `imports` | Required nonempty list | File specifications, expanded in order |
| `models` | List; `[]` | Model/component specifications attached to imported curves |
| `fit` | Mapping; absent | One fit plan. Absent or `{}` skips fitting |
| `export` | Mapping; `{}` | Optional project and/or bundle output |

For independent/global fitting, each selected curve needs a usable model. In
sequential mode, the first curve instead needs a prepared source model whose
components propagate to later targets. Multiple model entries targeting the same
curve add to the existing model. The runner creates new curve IDs on every import,
even for identical inputs.

## W6. Import specification and column mapping

Each `imports` item supports:

| Key | Type/default | Contract |
| --- | --- | --- |
| `path` | Required path string | One input data file |
| `columns` | Required mapping | Passed to `ColumnMapping(**columns)` |
| `config` | Optional mapping | Passed to `ImportConfig(**config)`; omit the whole key to auto-detect |
| `aliases` | List of strings; `[]` | Replaces imported curve names, in output order |
| `curve_ids` | List of strings; `[]` | Stable workflow identities mapped to newly imported runtime curve IDs, in output order |

Use distinct aliases for imported curves you intend to select by name. Curve
selectors in `models`, `fit.curves`, and `fit.spectrum_weights` resolve a declared
workflow identity or unambiguous alias/name first, and an actual runtime curve ID
second. Repeated imported names are removed from the alias lookup instead of
silently choosing one: give those curves distinct `aliases` or `curve_ids`.

`curve_ids` does not assign the real curve IDs. Each listed string becomes a
stable workflow identity that the runner maps to the newly generated runtime ID.
Identities must be unique across all import items; duplicates raise an error.
Use simple nonempty strings without dots, such as `sample_a` and `sample_b`, so
canonical parameter references can split the identity from component/parameter
names. These identities can select curves and, unlike display aliases alone,
can occur inside `${identity.component_id.parameter_name}` links. The runner
remaps only the first dotted segment of each reference, not arbitrary text or
component display names. Identity entries take precedence over aliases with the
same spelling; avoid accidental collisions.

Both lists follow the order returned by the importer. Shorter lists leave the
remaining curve names/IDs autogenerated; extra entries are unused. For repeatable
linked workflows, provide a `curve_ids` entry for every referenced curve and
explicit component `id` values. Aliases remain optional human-readable labels.

`config` fields and dataclass defaults:

| Key | Default | Meaning |
| --- | --- | --- |
| `delimiter` | `null` | Whitespace when explicitly null; otherwise delimiter string such as `","`, `";"`, or `"\t"` |
| `decimal` | `"."` | Decimal separator, typically `"."` or `","` |
| `comment_prefixes` | `["#", ";", "%", "!"]` | Leading comment markers after left whitespace is stripped |
| `header` | `null` | Truthy means first retained row supplies column names; false/null means no header when config is explicit |
| `encoding` | `utf-8-sig` | Text encoding; decoding replaces invalid characters |
| `skip_rows` | `0` | Number of physical leading rows to skip before comments/blank filtering |

Omitting `config` performs delimiter, decimal, header and leading-row detection.
Supplying `config: {}` constructs the defaults above, including whitespace and no
header; it does **not** request full auto-detection. Specify `header: true` to
select columns by a file's heading names.

`columns` fields and defaults:

| Key | Default | Meaning |
| --- | --- | --- |
| `x` | `null` | Shared X selector; required with a nonempty `y` unless using `pairs` |
| `y` | `[]` | Y selector list; produces one curve per Y column |
| `pairs` | `[]` | Explicit `[[x1, y1], [x2, y2]]` list; overrides shared `x`/`y` |
| `sigma_x` | `null` | Optional X uncertainty selector |
| `sigma_y` | `null` | Optional Y standard-deviation selector |
| `weights` | `null` | Optional residual-multiplier selector; objective contribution is multiplier squared times residual squared |
| `variance` | `null` | Optional Y variance selector, converted to `sigma_y = sqrt(variance)` |
| `inverse_variance` | `null` | Optional inverse-variance selector |
| `error_y_plus` | `null` | Upper Y error interval selector; requires `error_y_minus` |
| `error_y_minus` | `null` | Lower Y error interval selector; requires `error_y_plus` |
| `error_confidence_level` | `0.95` | Confidence represented by the error intervals; strictly between 0 and 1 |
| `as_separated_files` | `false` | Separate-spectrum naming/column-role checks; not an output-file operation |
| `spectra` | `[]` | Python-only nested `ColumnMapping` objects; leave empty in YAML |

Selectors are exact heading strings or **zero-based integer** positions. `x: 0`
selects the first column; `x: "0"` asks for a heading literally named `0`.
`y` must always be a list, even for one curve. In no-header files the displayed
names are `Column 1`, `Column 2`, etc., while integer positions remain zero-based.

Choose at most one Y-error representation from `sigma_y`, `weights`, `variance`,
`inverse_variance`, or the paired asymmetric interval fields. Both asymmetric
fields can select the same column for symmetric intervals. `sigma_x` may coexist
with a Y-error representation, but the fit is a Y-residual least-squares fit;
importing `sigma_x` does not enable orthogonal-distance regression. `weights`
values multiply residuals directly; `inverse_variance` values multiply residuals
by their square root. `sigma_y` divides residuals by its standard deviation;
asymmetric confidence intervals are converted to Gaussian tail scales using
`error_confidence_level`, choosing the upper/lower scale according to the fitted
prediction's side of the observed value. Nonfinite X/Y, nonfinite or nonpositive
Y-error scales, and nonfinite or negative weights are excluded through the
curve's effective mask. Zero weights remain valid but contribute zero to the
objective. Imported X errors do not determine the fit mask. Check retained point
counts in results.

The dataclass accepts `spectra`, but the YAML loader does not turn nested mappings
into `ColumnMapping` instances, so a nonempty YAML `spectra` list fails. Use shared
`x`/`y`, `pairs`, or several `imports` entries for different error mappings.

Examples of alternative mappings:

```yaml
# Several curves sharing one X axis and uncertainty column:
columns: {x: 0, y: [1, 2], sigma_y: 3}
aliases: [sample_A, sample_B]
```

```yaml
# Independent X/Y pairs in the same file:
columns:
  pairs: [[0, 1], [2, 3]]
  as_separated_files: true
aliases: [scan_A, scan_B]
```

```yaml
# Decimal-comma data with explicitly skipped instrument metadata:
config: {delimiter: ";", decimal: ",", header: true, skip_rows: 4}
columns: {x: wavelength, y: [intensity]}
aliases: [measurement]
```

These snippets replace the corresponding fields within an import item; they are
not complete workflow documents.

## W7. Models, components, and function catalogue

Each `models` entry supports:

| Key | Default | Meaning |
| --- | --- | --- |
| `curve` | Required | Declared workflow identity, unambiguous alias/name or actual curve ID |
| `name` | Existing model name, initially `Model for <curve name>` | Model label |
| `components` | `[]` | Components to append in order |
| `operation_order` | `[]` | Component IDs ordering Multiply/Divide/Convolve operations |

Each component supports:

| Key | Default | Meaning |
| --- | --- | --- |
| `function` | Required | Exact registered function identifier |
| `name` | Function display name | Human-readable component label; never a parameter path |
| `id` | Generated `component_…` ID | Explicit stable component ID, unique within its model |
| `parameters` | Function defaults | Mapping of exact parameter names to initial numeric values |
| `metadata` | Function configuration defaults | Function-specific options validated by the function definition; notably polynomial/spline settings |
| `operator` | `add` | `add`, `subtract`, `multiply`, `divide`, or `convolve` |
| `enabled` | `true` | Disabled components do not contribute to model evaluation |
| `is_background` | `false` | Marks background components for relevant operations/exports |
| `constraints` | `{}` | Parameter-specific bounds/fixed/link rules |

Built-in function identifiers and parameters:

| Identifier | Parameters and defaults | Special rules |
| --- | --- | --- |
| `gaussian` | `area: 1`, `center: 0`, `sigma: 1` | `sigma > 0`; FWHM = `2.354820045 * sigma` |
| `lorentzian` | `area: 1`, `center: 0`, `gamma: 1` | `gamma > 0`; gamma is HWHM; FWHM = `2 * gamma` |
| `voigt` | `area: 1`, `center: 0`, `sigma: 1`, `gamma: 1` | Both widths positive; area-normalised convolution |
| `pseudo_voigt` | `area: 1`, `center: 0`, `fwhm: 1`, `eta: 0.5` | `fwhm > 0`; `eta` in `[0, 1]`; eta is Lorentzian fraction |
| `constant` | `offset: 0` | Constant function |
| `linear` | `intercept: 0`, `slope: 0` | `intercept + slope*x` |
| `polynomial` | `c0 … cN: 0` | `metadata: {order: N}`; default N=2, allowed integer range 0-50 |
| `cubic_spline` | `y0 … yN: 0` | `metadata.x_nodes` supplies at least two finite strictly increasing X nodes |

Peak areas and centers are unbounded by default. Positive built-in width lower
bounds are machine epsilon. `Component.create` clamps initial values to the
function's default bounds; explicit constraint bounds are subsequently validated
against the resulting value. Set sensible positive initial widths and physically
appropriate bounds explicitly. All eight functions are usable as any component
role. Construction options are distinct from fitted parameters: polynomial
`metadata.order` must be an actual integer from 0 through 50 (not `2.0`, a string,
or a Boolean). Function-declared option defaults are inserted by
`Component.create`; declared option types/ranges are validated before parameter
construction. Python/plugin point-initialization callbacks are not YAML stages.
Two spline nodes use linear interpolation between the nodes and constant
endpoint values outside that interval; three or more use a natural cubic spline
with extrapolation.

Global composition first sums all Add functions and subtracts all Subtract
functions. Multiply, Divide and Convolve then act on that complete sum. Their
fallback order is Multiply, Divide, Convolve, with component ID as a tie-breaker;
use explicit IDs and `operation_order` for a chosen order. This is not a nested
expression language. The legacy `composition_mode` key is ignored; schemas 1 and
2 both use the current global roles. A component's position in the YAML list does
not create parentheses. FFT convolution requires a finite, uniformly spaced,
strictly monotonic X grid; ascending and descending axes are supported. Irregular
or nonmonotonic grids raise a data-validation error: resample them beforehand
using Python or another data-preparation tool. Integration uses absolute uniform
X spacing. Fitting evaluates convolution on the full current grid before masks
or fit ranges select residual rows, so excluding points does not alter the
convolved model itself. Choose a sufficient window width; consecutive
convolutions are evaluated together and cropped once.

For example, this model evaluates `(constant + gaussian) * response`:

```yaml
models:
  - curve: reference
    operation_order: [response]
    components:
      - {function: constant, id: baseline, parameters: {offset: 0.1}}
      - {function: gaussian, id: band, parameters: {area: 3, center: 0.3, sigma: 1}}
      - function: linear
        id: response
        operator: multiply
        parameters: {intercept: 1, slope: 0}
        constraints:
          intercept: {fixed: true}
          slope: {fixed: true}
```

## W8. Parameter constraints and links

For a component's `constraints`, keys must be existing parameter names:

```yaml
constraints:
  center: {minimum: -1.0, maximum: 2.0}
  sigma: {minimum: 0.001, maximum: 5.0, fixed: false}
  area: {fixed: true}
```

| Rule | Default when omitted | Contract |
| --- | --- | --- |
| `minimum` | Retain the function parameter's lower bound | Numeric inclusive lower bound |
| `maximum` | Retain the function parameter's upper bound | Numeric inclusive upper bound |
| `fixed` | `false` | Exclude the parameter from optimisation when true |
| `link` | `null` | Restricted mathematical expression with canonical parameter references |
| `link_scope` | `relative` | `relative` or `absolute`; copy behaviour, not expression shorthand |
| `link_reference_scopes` | `[]` | Per-reference copy behaviour; if nonempty must match expression reference occurrences |
| `link_relation` | `equal` | `equal`, `lower`, `upper`, or `similar` |
| `link_tolerance` | `0.0` | Nonnegative finite tolerance; must be positive for `similar` |
| `link_tolerance_mode` | `absolute` | `absolute` or `percent`; percentage must be less than 100 |

The initial parameter must lie inside its final minimum/maximum interval, and
minimum must not exceed maximum. Equality-linked parameters are computed from
their source expression; they are not free. Bound-linked parameters remain free
unless fixed. `lower` means target at least source; `upper` means target at most
source; `similar` keeps target within source ± tolerance. Percentage tolerance
uses `abs(source)*percentage/100`. Dynamic and static bounds are intersected;
empty intersections and link cycles are errors. Non-equality links require one
direct `${curve_id.component_id.parameter_name}` reference, without arithmetic.
Equality links may combine several canonical references in a formula.

**Stable links on fresh imports:** declare `imports[].curve_ids` to give every
referenced curve a stable workflow identity, and explicit component `id` values.
The runner replaces the identity prefix in each `${...}` reference with the
actual imported curve ID before resolving links. For example, with
`curve_ids: [sample_a]` and component `id: peak`, `${sample_a.peak.center}` is a
valid reference. A display alias alone is not expanded inside a parameter
expression. Do not substitute component names for IDs or invent a template
language. The entire project parameter graph is resolved before fitting or
exporting; unknown references, invalid links and cycles therefore fail even when
`fit` is absent. Use global mode when the linked source and target need joint
optimization; a global plan does not create links automatically.

### W8.1 Complete linked global-fit example

Save this as `linked.yml` beside `gaussian.csv` from the repository example. It
imports that file twice to keep the demonstration immediately runnable; for a
real replicate analysis, replace the second path with the second measurement.
Both peak centers are fitted through the source parameter. Background offsets,
areas and widths remain separate.

```yaml
# example: yaml-linked-global
schema_version: 2
name: Linked Gaussian centers
imports:
  - path: gaussian.csv
    config: {delimiter: ",", header: true}
    columns: {x: x, y: [y], sigma_y: sigma_y}
    aliases: [Reference spectrum]
    curve_ids: [sample_a]
  - path: gaussian.csv
    config: {delimiter: ",", header: true}
    columns: {x: x, y: [y], sigma_y: sigma_y}
    aliases: [Second spectrum]
    curve_ids: [sample_b]
models:
  - curve: sample_a
    components:
      - {function: constant, id: background, is_background: true}
      - function: gaussian
        id: peak
        parameters: {area: 3.0, center: 0.3, sigma: 1.0}
        constraints:
          sigma: {minimum: 0.001, maximum: 5.0}
  - curve: sample_b
    components:
      - {function: constant, id: background, is_background: true}
      - function: gaussian
        id: peak
        parameters: {area: 3.0, center: 0.3, sigma: 1.0}
        constraints:
          center: {link: "${sample_a.peak.center}"}
          sigma: {minimum: 0.001, maximum: 5.0}
fit:
  mode: global
  curves: [sample_a, sample_b]
  settings: {solver: local, loss: linear, seed: 1729}
export:
  project: outputs/linked.fitproj
  bundle: outputs/linked-analysis
  versioned: true
```

Run `curvemole validate linked.yml`, then `curvemole run linked.yml --json`.
Inspect `success` and the saved result parameters. The two resolved center values
must agree, and the target estimate is equality-linked rather than free. This
example requires CurveMole 1.1.0: 1.0.1 did not remap workflow curve identities.

`link_scope` and `link_reference_scopes` govern retargeting when a model is copied
through the corresponding Python/desktop operations. They do not change how a
reference is resolved during this YAML runner.

## W9. Custom formula functions

Define formulas before using their identifier as a component `function`:

```yaml
custom_functions:
  - identifier: exponential_decay
    display_name: Exponential decay
    formula: "amplitude * exp(-x / tau)"
    kind: generic
    defaults: {amplitude: 1.0, tau: 2.0}
    bounds:
      tau: [0.001, 1000.0]
    derived:
      half_life: "tau * log(2)"
```

Required keys are `identifier` and `formula`. `display_name` defaults to the
identifier; `kind` defaults to `generic`; `defaults`, `bounds` and `derived`
default to empty mappings. `kind: peak` classifies a function as a peak but does
not rename parameters or automatically establish graphical parameter roles.
Formula variables other than `x` become parameters in alphabetical order;
unspecified defaults are 1.0 and unspecified bounds are unbounded. Each bounds
entry is a two-number `[minimum, maximum]` list. `derived` maps result names to
scalar parameter formulas; derived formulas have no X array. A nonfinite derived
result is reported as unavailable. Invalid symbols or expressions can raise an
expression error and fail an operation; use only parameters declared by the main
formula and check each derived formula on representative parameter values.
Registration uses replacement, so do not reuse a built-in identifier accidentally.
Formula definitions are not arbitrary Python and need no executable-plugin
approval.

**Version 1.1.0 persistence limitation:** the YAML runner registers
`custom_functions` in its function registry but does not copy those definitions
into `Project.custom_functions`. Consequently, a `.fitproj` or reusable model
export from this runner does not embed the recipe's custom formula definitions.
The same process can still evaluate them through its populated registry, which
can hide the problem until restart. Retain the original YAML and re-register the
same identifiers/formulas through Python or the Function Builder before
evaluating or refitting in a fresh session. Saved numerical fit results and
arrays remain available for inspection. Use the Python API's documented custom
function registration and persistence steps when a self-contained custom-formula
project is required.

The exact expression vocabulary is:

- Arithmetic `+`, `-`, `*`, `/`, `**`, `%`; unary `+`, `-`, `not`.
- Comparisons `==`, `!=`, `<`, `<=`, `>`, `>=`; `and`, `or`; conditional
  `a if condition else b` (also works elementwise).
- Constants `pi`, `e`, `inf`.
- Functions `abs`, `sqrt`, `exp`, `log`, `log10`, `sin`, `cos`, `tan`, `arcsin`,
  `arccos`, `arctan`, `sinh`, `cosh`, `tanh`, `erf`, `erfc`, `minimum`, `maximum`,
  `clip`, `where`, `heaviside`.

Use `**` for powers, never `^`. Calls use positional arguments only, for example
`where(x > 0, amplitude * exp(-x/tau), 0)`. Attribute access (`np.exp`), subscripts,
imports, comprehensions, arbitrary function calls, string literals and Python
execution are rejected. Keep formulas finite across the actual X domain.

## W10. Fit plan

| Key in `fit` | Default | Meaning |
| --- | --- | --- |
| `mode` | `independent` | `independent`, `sequential`, `global`, or legacy `copy` |
| `curves` | All imported curves, in import order | Nonempty list of workflow identities, unambiguous aliases/names or runtime IDs; no duplicates |
| `settings` | `{}` | `FitSettings` keyword arguments, listed below |
| `spectrum_weights` | `{}` | Curve selector → finite positive weight |
| `equal_contribution` | `false` | Divide each curve's weighted residual by the square root of its retained point count |

Independent fits use each curve's own model and starting parameters.

**Sequential mode uses the first selected curve as an already prepared source;
it does not fit that source.** The source must have a nonempty model with values
already suitable for propagation. Later curves are processed in `fit.curves`
order. The preceding model is cloned with its function identities, values,
structural metadata, bounds, fixed state, links, enabled/background flags and
composition. Source component IDs select which functions continue to propagate.
Missing components are added to each target by ID; an existing target component
with that ID is retained, rather than overwritten, and target-local components
remain. For the usual propagate-and-fit case, define the model only on the source
and leave target models empty. A one-curve sequential plan succeeds with no fit
outputs because there are no subsequent curves.

Default sequential safeguards are active even for the plain `FitPlan` created
by YAML. Residual monitoring pauses when normalized RMSE exceeds the previous
value by both a factor of 2.5 and an absolute increase of 0.02. Parameter monitoring
pauses at a normalized free-parameter change of at least 0.75; its denominator
uses the larger value magnitude or a parameter-specific scale near zero, not
simply the starting value. Failures and nonconvergence also pause. Propagation
flags, monitoring thresholds, exclusions and durable pause/resume are not YAML
fields; use Python `SequentialFitPlan` or desktop sequential controls to configure
them. A pause returns `success: false`; the saved project can retain copied/fitted
state for review, but the YAML runner cannot interactively continue. Inspect the
project or use Python before continuing the sequence. `copy` is an accepted
legacy mode but follows the independent execution branch; use `sequential` for
actual propagation.

Global fits solve all selected curves together. This alone does not make their
parameters shared; sharing requires canonical links using declared stable curve
identities as shown in W8. Spectrum weight multiplies residuals by `sqrt(weight)`;
the default weight is 1.0. `equal_contribution` is point-count scaling, not
automatic noise estimation. Use `use_data_errors: false` to ignore imported
uncertainties/weights during fitting, including their exclusion of unusable
uncertainty rows; intrinsically invalid X/Y remain excluded.

## W11. Complete solver settings and defaults

Only the following built-in settings are passed to `FitSettings`; spell names
exactly. An unrecognised setting raises `TypeError`. Do not add GUI-only controls
such as propagation thresholds or Monte Carlo replicate counts here.

| Setting | Default | Meaning/accepted values |
| --- | --- | --- |
| `solver` | `local` | `local`, `trf`, `dogbox`, `lm`, `differential_evolution`, `nelder_mead`, `powell`, `lbfgsb`, or an enabled registered plugin solver ID |
| `local_method` | `auto` | `auto`, `trf`, `dogbox`, `lm`; local solve/refinement method |
| `loss` | `linear` | `linear`, `soft_l1`, `huber`, `cauchy` |
| `f_scale` | `1.0` | Finite positive robust-loss residual scale |
| `max_nfev` | `1000` | Positive integer evaluation limit |
| `ftol` | `0.0000000001` | Positive least-squares cost tolerance, above machine precision |
| `xtol` | `0.00000001` | Positive least-squares step tolerance, above machine precision |
| `gtol` | `0.0000000001` | Positive least-squares gradient tolerance, above machine precision |
| `x_scale` | `jac` | `jac` or a finite positive scalar |
| `seed` | `1729` | Integer from 0 through 4294967295 |
| `workers` | `1` | Positive integer; multiple processes for independent multi-curve fits |
| `confidence_level` | `0.95` | Parameter interval confidence, strictly between 0 and 1 |
| `absolute_sigma` | `null` | Auto-select absolute covariance scaling from imported Y-error availability; explicit true/false overrides when data errors are used |
| `use_data_errors` | `true` | Boolean: use imported errors/weights; false forces residual-scaled covariance |
| `de_maxiter` | `400` | Positive integer DE generation limit |
| `de_popsize` | `15` | Positive integer DE population multiplier |
| `de_lower_percent` | `50.0` | Finite positive percentage for automatic lower search limits |
| `de_upper_percent` | `50.0` | Finite positive percentage for automatic upper search limits |
| `de_mutation_min` | `0.5` | Minimum mutation factor; `0 <= min <= max < 2` |
| `de_mutation_max` | `1.0` | Maximum mutation factor |
| `de_recombination` | `0.7` | Recombination fraction in `[0, 1]` |
| `de_tol` | `0.01` | Finite nonnegative relative DE tolerance |
| `de_atol` | `0.0` | Finite nonnegative absolute DE tolerance |
| `nm_xatol` | `0.0001` | Finite positive Nelder-Mead X tolerance |
| `nm_fatol` | `0.0001` | Finite positive Nelder-Mead objective tolerance |
| `nm_adaptive` | `false` | Adaptive Nelder-Mead option |
| `nm_initial_simplex` | `null` | Finite `(N+1) × N` numeric list for N free parameters; do not include fixed/equality-linked parameters |
| `minimize_maxiter` | `0` | Nonnegative integer; 0 keeps the minimizer's automatic iteration limit |
| `powell_xtol` | `0.0001` | Finite positive Powell X tolerance |
| `powell_ftol` | `0.0001` | Finite positive Powell objective tolerance |
| `lbfgsb_ftol` | `0.000000002220446049250313` | Finite positive L-BFGS-B objective tolerance |
| `lbfgsb_gtol` | `0.00001` | Finite positive L-BFGS-B gradient tolerance |
| `lbfgsb_maxls` | `20` | Positive integer maximum line-search steps |
| `lbfgsb_maxcor` | `10` | Positive integer stored correction pairs |

`local` with `auto` chooses an appropriate least-squares method. Explicit LM is
incompatible with bounds and robust loss. Differential Evolution finds an initial
solution then locally refines it. Finite user bounds take priority over its
automatic search intervals; set scientifically meaningful finite bounds for
difficult searches. Minimisers and local methods have different convergence
properties; inspect results rather than relying only on solver termination.
Multiple-worker independent fits support built-ins and safe custom formulas;
executable plugin model functions cannot be reconstructed automatically in worker
processes. `workers` is not a general parallelisation switch for every mode.

## W12. Output contract and reruns

| Key in `export` | Default | Meaning |
| --- | --- | --- |
| `project` | Absent | Save the generated project; parent directories are created and suffix becomes `.fitproj` |
| `bundle` | Absent | Export the standard analysis bundle with its default selections |
| `versioned` | `false` | Add UTC `export-YYYYMMDD-HHMMSS` subdirectory under the bundle directory |
| `overwrite` | `false` | Request updating existing bundle files, subject to ownership checks |

These are the only YAML export keys. Controls such as delimiter, selected bundle
items, portable project copies, saved uncertainty samples, and current-view plot
exports are Python/desktop features, not accepted YAML options.

**Project and bundle replacement differ.** `export.project` saves directly with
`save_project`; it can replace an existing project without consulting
`export.overwrite`. Use a distinct project path when a previous file must be kept.
`versioned` applies only to the bundle, not to the project filename.

Bundle exports refuse conflicting files unless updating is requested and
CurveMole can establish ownership. `overwrite: true` is not permission to replace
arbitrary existing files. Each YAML run starts a fresh project and therefore
normally lacks the ownership record from a previous run; fixed-directory reruns
may still be refused even with `overwrite: true`. A readable bundle manifest is
not sufficient proof of ownership. Prefer a new directory or `versioned: true`;
timestamp resolution is one second, so avoid simultaneous exports into the same
versioned parent. Use Python with the saved project when you need its retained
ownership state for a controlled update.

Exports are successive operations, not one transaction. If bundle export fails,
a project saved earlier can remain. If no `export` is present, the CLI/desktop
worker only retains its in-memory project for that run. `run --json` is a summary;
use the saved `.fitproj` or exported result tables/JSON for detailed parameters,
per-curve arrays, covariance, diagnostics and warnings.
For custom formulas, also retain the recipe and follow the persistence limitation
in W9 before assuming that a saved project can refit in a new session.

## W13. Trusted executable plugins

List manifest files, not Python modules or plugin directories:

```yaml
plugins:
  - plugins/lab_tools.curvemole-plugin.json
```

For the command line, supply each manifest's **plugin identifier**, not a filename:

```bash
curvemole run workflow.yml --trust-plugin org.example.lab_tools --json
```

The identifier above is a placeholder; replace it with the identifier declared
inside your actual manifest. For the desktop runner, first review and enable the
same local plugin through **File > Plugin Manager**. The worker verifies that
the approved manifest/source fingerprint still matches at launch. Merely placing
a path in `plugins` does not authorise execution. Plugins run Python with the
user's permissions. Safe formula functions are a different mechanism.

The workflow does not export plugin source. Keep manifest/source versions and
dependencies with the research record. Plugin-specific solver semantics require
that plugin's own documentation in addition to this core contract.

## W14. Python workflow functions and round-trip limits

The workflow module also exposes:

```python
from curvemole.core.workflow import (
    WorkflowOutcome, dump_workflow, load_workflow, run_workflow, validate_workflow,
)

value = load_workflow("workflow.yml")       # dict; checks root/schema
errors = validate_workflow(value)           # list[str]; shallow structural checks
if errors:
    raise ValueError("; ".join(errors))
outcome = run_workflow("workflow.yml")      # WorkflowOutcome
print(outcome.project.name)
print(outcome.result.success if outcome.result else None)
print(outcome.outputs)                      # list[pathlib.Path]
```

Exact runner signature:
`run_workflow(path, *, trust_plugins: set[str] | None = None,
registry: FunctionRegistry | None = None) -> WorkflowOutcome`.
Passing a registry permits caller-provided functions. `dump_workflow(project,
path) -> pathlib.Path` writes schema 2 YAML containing imports and model/component
specifications. `WorkflowOutcome` has `project`, `result` (`FitResult | None`),
and `outputs` (`list[Path]`).

`dump_workflow` is a starting recipe, **not a complete project round trip**. It
does not embed data arrays, transformed data, masks, results, a fit plan, exports,
custom-function definitions or plugin declarations. It uses original source paths
and saved import mappings, or a fallback `data/<curve-name>.csv` path that it does
not create. It does not export the original series structure. A curve originally
selected from one of multiple Y columns must have its dumped mapping checked:
re-importing a stored multi-Y mapping can produce additional curves. Dumped
imports include each saved curve ID in `curve_ids`, and model selectors use those
IDs; on replay the runner maps them to new runtime IDs and remaps parameter links.
This preserves link addressing for correctly matched imports, but does not embed
or guarantee the source data. Review each import mapping and identity list,
insert missing function/plugin definitions and the desired `fit` and `export`,
and check constraints before running. Use `.fitproj` for preserving the
actual project state.

## W15. Using the AI YAML audit

The downloadable **AI YAML automation audit** is a standalone copy of this
contract with instructions for an AI author. Upload `ai-yaml-audit.md` to the AI
with your requested analysis, software version, file header/column layout,
representative numeric rows, initial values/bounds and desired output paths. The
AI does not need the CurveMole source for workflows covered here. An audit is a
version-specific implementation inventory and usage contract, not a security
certification or a guarantee that generated scientific choices are correct.

Example prompt:

> Use the attached CurveMole 1.1.0 YAML audit as the API contract. Create one
> schema-2 workflow for the attached column layout. Use only documented fields
> and function names. Ask for missing scientific assumptions. Return the complete
> YAML, the validate/run commands, the expected outputs, and any limitations.
> If the task needs capabilities missing from YAML, explain why and request the
> Python audit rather than inventing keys.

For scripts, supply `ai-python-audit.md` instead. Supply both audits when the task
combines Python orchestration and YAML execution. Review the generated paths,
models, units, error interpretation and overwrite behaviour; then validate and
run on a small representative dataset. Record the actual version, YAML, input
data and output with the result. For another CurveMole version, obtain matching
audits before asking the AI to adapt a workflow.
