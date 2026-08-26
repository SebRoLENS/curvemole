# Architecture

Dependency direction is strict:

```text
GUI / CLI / Python API / YAML workflow
                 ↓
      core project and services
                 ↓
data · parameters · models · fitting · uncertainty
                 ↓
     NumPy · SciPy · pandas
```

`curvemole.core` does not import Qt. Optimisers and functions are registries. Project,
fit-model, workflow, and export formats are schema-versioned and use the same domain
objects. This keeps scripting and reproducibility structural rather than additions to
the GUI.
