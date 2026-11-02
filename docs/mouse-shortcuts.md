# Mouse shortcuts

The same gesture can have different effects depending on the active mode.
Leave **Mask**, function placement or point editing to return to normal navigation.

## Normal plot navigation

| Gesture | Action |
|---|---|
| Right double-click | Frame **all experimental points**, including masked points. |
| Left double-click | Frame **unmasked experimental points** only. With no usable points, keep the current view. |
| Right-drag | Pan the plot. |
| Left-drag empty space | Pan in Pan mode, or draw a zoom rectangle in Rectangle mode (chosen in the plot context menu). |
| Mouse wheel | Zoom the plot. |
| Single right-click | Open the plot context menu after waiting for a possible double-click. |
| Left-click a data curve | Select that spectrum. With Autoscale on, apply the chosen All points / Unmasked points scope. |
| Left-click a function | Select that function. |
| Hover over the coordinate readout | Show the full pointer coordinates and nearest finite point from the active spectrum. |

Double-click resets do **not** depend on the Autoscale checkbox or its point
selector. They use experimental data, not model extrapolations or labels, and
respect Waterfall offsets and the displayed data transformations.
**Lock plot view** disables mouse pan and zoom.

## Mask mode

Activate **Mask** first. In Overlay/Waterfall, choose whether edits affect the
active spectrum or all visible spectra when entering the mode.

| Gesture | Action |
|---|---|
| Right-click | Mask the nearest point. |
| Right-drag | Mask an X interval. |
| Left-click | Unmask the nearest point. |
| Left-drag | Unmask an X interval. |

Clicks edit masks in this mode; they do not perform normal double-click resets.
Click **Mask** again to leave the mode.

## Graphical peak placement

With graphical initialization enabled, press at the peak centre, drag horizontally
to either half-height edge, and release to set the centre and width. A left-click
also places a peak with an automatically estimated width. Quick Add permits
repeated placement; right-click or press Enter to finish the current session.
Esc cancels the pending placement.

## Function control points: Add / Delete / Move

These modes edit a function's initialization/control points, not experimental data.
They are also used by **Edit points** on an existing function.

| Mode / gesture | Action |
|---|---|
| Add points: left-click | Add a point. |
| Add points: left double-click | Finish after the required minimum number of points. |
| Delete points: left-click a point | Delete that control point. |
| Move points: left-drag a point | Move that control point. |
| Left-drag empty space | Pan without adding or moving points. |
| Mouse wheel | Zoom while editing control points. |
| Right-click in a Quick Add session | Finish placement, once enough points exist. |
| Right-click in other control-point sessions | Remove the nearest control point. |

Use **Finish** to commit or Esc to cancel. Double-click does not finish in Delete
or Move mode. **Undo point** reverses the last point edit during the session.

## Function handles

| Gesture | Action |
|---|---|
| Drag the selected peak's centre/height handle | Adjust the peak position and height. |
| Drag a peak's width handle | Adjust FWHM. |
| Drag a spline node | Change its Y value; X remains fixed. |
| Hold Ctrl while dragging a handle | Change a fixed parameter without removing its fixed state. Equality-linked parameters remain controlled by their relation. |

## Edit experimental data points

| Gesture | Action |
|---|---|
| Left-click a point | Select the experimental point. |
| Left-drag a point | Move it along X, Y or XY, according to the editor's selector. |
| Right-drag / mouse wheel | Pan / zoom. |

Delete or Backspace removes the selected point; **Done** or Esc ends editing.
Data edits support Undo/Redo.

## Lists and plugin tools

| Gesture | Action |
|---|---|
| Ctrl-click items | Select individual spectra or functions. |
| Shift-click items | Select a contiguous range. |
| Double-click an editable name | Rename the series or spectrum. |
| Right-click a list item | Open the context menu for that item. |
| Left-click a plugin marker | Select the marker or invoke its plugin action. |

When a plugin starts its own point-picking mode, left-click picks a point;
right-drag pans and the wheel zooms. Follow the plugin's displayed instructions
for its additional gestures and completion controls.
