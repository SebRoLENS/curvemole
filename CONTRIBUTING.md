# Contributing to CurveMole

Corrections, functions, translations, tests, and plugins are welcome. Open an issue
before a large change, keep scientific behaviour covered by reference tests, and do
not mix GUI dependencies into `curvemole.core`.

Contributions must be licensed under GPL-3.0-or-later and include a Developer
Certificate of Origin sign-off:

```text
Signed-off-by: Your Name <your.email@example.org>
```

Run `ruff check .` and `pytest` before submitting a pull request. New numerical
features must document conventions, units, bounds, expected failure modes, and
tolerances.
