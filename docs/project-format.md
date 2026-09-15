# `.fitproj` format version 1

A project is an ordinary ZIP archive:

```text
manifest.json
data/<curve-id>/original_x.npy
data/<curve-id>/original_y.npy
data/<curve-id>/sigma_y.npy              optional
data/<curve-id>/weights.npy              optional
data/<curve-id>/masks/<mask-id>.npy
data/<curve-id>/transformations/*_operand.npy  optional
```

`manifest.json` contains `format`, `schema_version`, application version, project
metadata, model graphs, histories, UI/export state, and a SHA-256 map for every
binary payload. NumPy arrays are loaded with `allow_pickle=False`. A save is written
to a temporary sibling, reopened and validated, then atomically replaces the target.

## Retained import columns

Curve metadata optionally contains `column_keys`, `column_labels` and `column_axes`.
Original arrays are stored as `data/<curve-id>/columns/<index>.npy`, in column_keys
order, covered by archive checksums. Curves without these optional keys remain
readable. `column_formula` transformations store a target and restricted expression;
replaying the transformation stack reconstructs both plotted and auxiliary columns.
Use a CurveMole build supporting this feature to reopen transformed projects.
