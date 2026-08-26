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
