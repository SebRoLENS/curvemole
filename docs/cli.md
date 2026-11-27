# Command-line interface

List functions:

```bash
curvemole functions list
```

Fit one file and save a project:

```bash
curvemole fit spectrum.csv --x wavenumber --y absorbance \
  --function gaussian --background linear --output result.fitproj
```

Run a reproducible workflow:

```bash
curvemole run workflow.yml --json
```

`fit` and `fit-series` initialise peaks from the automatic suggestions. Use
`--peaks N` to fit the N most prominent peaks (a warning reports additional
candidates), and `--sigma-y COLUMN` to weight the fit with Y standard
uncertainties. The text output lists parameters as `spectrum / function / parameter:
value ± standard error`; `--json` adds the same readable `label` to every parameter.

Other commands are `gui`, `export`, `inspect`, and `validate`. Run
`curvemole <command> --help` for every option.

Automation mode never prompts. Data go to stdout, logs and actionable errors go to
stderr, and exit codes distinguish:

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Usage error, including an output that already exists without `--force` |
| 3 | Data error, including a missing or unreadable input file |
| 4 | The fit did not succeed (`"success": false`, e.g. a paused sequential fit) |
| 5 | Project or model file error |
| 6 | Plugin or other domain error |
| 10 | Unexpected failure (add `--verbose` for the traceback) |

JSON output is standard JSON: non-finite numbers such as infinite parameter bounds
are written as `null`.

Exported YAML workflows include an optional `curve_ids` list alongside each
import's display `aliases`. Models refer to these unique identities, and loading
remaps every parameter-link reference to the newly imported curves, including
absolute references. A display name may therefore be repeated without ambiguity.
Older workflows without these fields still load; ambiguous display names must be
replaced with unique aliases. Regenerate an older exported workflow with links
if it lacks the original curve identities needed for remapping.
