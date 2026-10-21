# `.fitproj` format version 2

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

## Model composition

Version 2 records `composition_mode` and `operation_order` on each model.
`global` mode pools Add/Subtract functions, then applies the component IDs in
`operation_order`; remaining factors default to multiplication, division, then
convolution. Function insertion and display order are independent of this order.
`ordered` preserves the original accumulated-model semantics. Version 1 archives
remain readable; missing composition metadata is interpreted as `ordered`.

The same version 2 composition fields are retained in `.fitmodel` files and YAML
workflows. Older software does not implement global composition and must not be
used to recalculate these models. Legacy YAML schema 1 remains supported with its
original ordered semantics.
