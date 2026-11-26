# Vertical markers

Plugin for CurveMole 1.4.2 (plugin API `"1"`) that inserts **vertical markers**
on spectra by clicking the **main graph**. Each marker is a vertical bar at a
chosen abscissa, identified by a label showing its value (`x = 532.25 nm`) and an
optional name.

## Where to find it

| Contribution | Menu |
| --- | --- |
| **Vertical markers** control panel (opens automatically when the plugin is enabled) | View > Plugins: Panels |
| **Vertical markers** exact bars on the main graph | View > Plugins: Plot Layers |
| **Marker list** (text table and TSV) | Tools > Plugins: Analysis |

## Usage

1. Make the spectrum you want to annotate active and visible.
2. Press **Ctrl+Shift+M** (or the **Marker mode on the main graph** button in
   the panel). CurveMole shows the picking instruction on the main graph.
3. **Click a sample on the main graph**: a marker is inserted at its abscissa
   and drawn as a vertical bar with a diamond on the sample. Click a sample
   that already has a marker to remove it.
4. Press **Esc** or **Ctrl+Shift+M** again to leave marker mode and return to
   normal zooming and panning.

The panel lists the markers with their labels (`Raman — x = 532.25 nm`):
double-click to rename, **Delete** or **Remove selected** to remove,
**Remove all** to clear the spectrum. Clicking a marker on the main graph selects
it in the list. Further options:

- **Ask for a label when inserting**: prompts for a name at every click.
- **Show markers on the main graph**: vertical bars and diamonds on the main graph.
- **Exact x** + **Add**: insert a marker at a typed abscissa (decimal comma
  accepted), e.g. a tabulated line position between two samples.

Every insertion, rename or removal is one CurveMole **Undo** step (Ctrl+Z) and
does **not** invalidate fits.

## Stored data

Markers are saved in the project, per spectrum, in
`curve.metadata["<identifier>.markers"]`:

```json
{"version": 1, "markers": [{"x": 532.25, "label": "Raman", "colour": "#d55e00"}]}
```

## Limitations (CurveMole plugin API 1)

- Plugins cannot add entries to the **right-click menu of the main graph**; the
  supported way to interact with the main graph is the host's sample picking,
  used by marker mode (left click on a sample).
- Marker mode works on measured samples: a marker inserted by clicking sits
  exactly on a sample's abscissa. Use **Exact x** for positions between samples;
  on the main graph such markers are shown at the nearest sample, while the
  Plot Layers command draws them at the exact abscissa.
- Plugins cannot draw **text** on the main graph: labels are shown in the panel
  list and in the Marker list analysis, not next to the bars.
- The panel must be **visible** (docked in front or floating, it can be made
  small) for marker mode, the main-graph bars and the Ctrl+Shift+M shortcut to
  work: when the panel is hidden the plot session is closed, as required by
  CurveMole. If Ctrl+Shift+M is already used by CurveMole, the panel says so;
  use the button instead.
- If the host does not accept vertical preview segments, only the diamonds are
  shown on the main graph; the Plot Layers command still draws the bars (they
  are removed at the next native redraw of the graph and do not follow waterfall
  offsets or background subtraction).
- After Undo/Redo the panel updates within about 2 seconds.

## Installation

Once published in the validated catalog: **File > Plugin Manager > Browse
validated plugins…** and install "Vertical markers".

Manual installation: copy the `vertical_markers/` folder to a permanent
location, then **File > Plugin Manager > Choose folder… > Scan**, select
"Vertical markers", review the source and choose **Review and trust selected
plugin…**. Every change to the files requires trusting the plugin again (source
fingerprint).

## Tests

With a Python installation of CurveMole 1.4.2 (PowerShell):

```bash
QT_QPA_PLATFORM=offscreen python -m pytest custom_plugins/by_community/vertical_markers/test_plugin.py
python scripts/validate_community_plugins.py
```

## Security

No network access, no external processes, no file writes: markers are stored
only in the project through CurveMole's services.

## Citation

Mattia Merlo, *Vertical markers*, plugin for CurveMole, version 1.1.0 (2026),
`io.github.mattiamerlo-bot.vertical-markers`.
