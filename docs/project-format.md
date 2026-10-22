# `.fitproj` format version 4

A project is an ordinary ZIP archive:

```text
manifest.json
history.jsonl
results/arrays/<index>.npy
data/<curve-id>/original_x.npy
data/<curve-id>/original_y.npy
data/<curve-id>/sigma_y.npy              optional
data/<curve-id>/weights.npy              optional
data/<curve-id>/masks/<mask-id>.npy
data/<curve-id>/transformations/*_operand.npy  optional
```

`manifest.json` contains `format`, `schema_version`, application version, project
metadata, model graphs, UI/export state, and a SHA-256 map for every
binary payload and the history stream. NumPy arrays are loaded with `allow_pickle=False`. A save is written
to a temporary sibling, reopened and validated, then atomically replaces the target.

## Numerical results and history

Version 3 stores fit-output arrays, covariance/correlation matrices and raw
uncertainty samples as binary NumPy payloads. JSON refers to each payload using
`{"__curvemole_array__":"results/arrays/000000.npy"}`. Repeated references to the
same array share one payload and one loaded buffer. User dictionaries with a
reserved marker key are escaped with `__curvemole_literal_dict__` so their content
is never interpreted as an array reference. Array dtypes and numeric bits are
preserved, including signed zero and non-finite numerical-array values.

Version 4 preserves independent-fit covariance and correlation as
`{"block_diagonal": [array_reference, ...]}`. Blocks follow the order of
`free_parameter_paths`; their sizes define the offsets. Off-block entries are
zero. Global fits retain a single dense matrix. Versions 1–3 remain readable,
but version 4 archives require a reader supporting block matrices. CSV matrix
exports retain the full rectangular layout and are streamed row by row.

The project's `fit_history` field contains
`{"storage":"history.jsonl","count":N}`. The referenced UTF-8 stream contains one
JSON record per line. All records are retained. The application keeps untouched
records compressed in memory and streams them when saving, instead of retaining
every historical Python object or building one large JSON string.

Version 1 and 2 projects remain readable; legacy JSON uncertainty samples are
restored into float64 arrays without reducing precision. Save a backup before
opening a project with older software: version 3 result storage requires a
CurveMole version that supports schema 3. Model and YAML workflow formats remain
at schema 2. No project archive contains or executes Python pickles.

CRC and SHA-256 checks read ZIP members in bounded chunks. Partial recovery can
retain intact experimental spectra if a numerical result or history member is
damaged; recovered archives open read-only for inspection and Save As.

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
