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

Other commands are `gui`, `fit-series`, `export`, `inspect`, and `validate`.
Automation mode never prompts. Data go to stdout, logs and actionable errors go to
stderr, and exit codes distinguish usage (2), data (3), fit (4), project (5), plugin
(6), and unexpected (10) failures.

Exported YAML workflows include an optional `curve_ids` list alongside each
import's display `aliases`. Models refer to these unique identities, and loading
remaps every parameter-link reference to the newly imported curves, including
absolute references. A display name may therefore be repeated without ambiguity.
Older workflows without these fields still load; ambiguous display names must be
replaced with unique aliases. Regenerate an older exported workflow with links
if it lacks the original curve identities needed for remapping.
