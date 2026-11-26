"""Vertical markers for CurveMole 1.4.2 (plugin API "1").

Registered contributions (see README.md):

* ``panels``      "Vertical markers": a compact control panel. Its *marker mode*
                  (toggled with Ctrl+Shift+M) lets you insert and remove markers
                  by clicking samples on the **main graph** through a plot
                  session (audit Section 9); markers are drawn on the main graph
                  as vertical bars.
* ``plot_layers`` "Vertical markers": exact vertical bars on the main graph.
* ``analysis``    "Marker list": text table of the markers.

Markers are stored per spectrum in ``curve.metadata["<identifier>.markers"]``
through ``services.save_settings`` (undoable, does not invalidate fits).
Qt is imported only when the panel is created.
"""

from __future__ import annotations

import contextlib
import html
import math
import re

import numpy as np

# Okabe-Ito colours, readable on light and dark backgrounds.
PALETTE = ("#d55e00", "#0072b2", "#009e73", "#cc79a7", "#e69f00", "#56b4e9")
SIGNIFICANT_DIGITS = 6
MAX_LABEL_LENGTH = 80
MARKER_MODE_SHORTCUT = "Ctrl+Shift+M"
_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------
# Pure logic (no Qt): used by the panel, plot layer, analysis and tests
# --------------------------------------------------------------------------

def meta_key(owner):
    """``curve.metadata`` key holding this plugin's markers."""
    return f"{owner}.markers"


def finite_float(value):
    """Convert to a finite float, otherwise ``None`` (never raises)."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def parse_x(text):
    """Parse an abscissa typed by the user (a decimal comma is accepted)."""
    if not isinstance(text, str):
        return finite_float(text)
    return finite_float(text.strip().replace(",", "."))


def same_x(a, b):
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def clean_label(label):
    """Single-line label: tabs, newlines and repeated spaces collapse to one space."""
    if label is None:
        return ""
    text = label if isinstance(label, str) else str(label)
    return " ".join(text.split())[:MAX_LABEL_LENGTH]


def _free_colour(markers):
    used = {m["colour"] for m in markers}
    for colour in PALETTE:
        if colour not in used:
            return colour
    return PALETTE[len(markers) % len(PALETTE)]


def normalise_markers(raw):
    """Return a clean, sorted list of ``{x, label, colour}`` markers.

    Accepts the stored value (``{"version": 1, "markers": [...]}``) or a list;
    invalid entries are silently skipped instead of raising.
    """
    if isinstance(raw, dict):
        raw = raw.get("markers", [])
    if not isinstance(raw, (list, tuple)):
        return []
    markers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        x = finite_float(item.get("x"))
        if x is None or any(same_x(x, m["x"]) for m in markers):
            continue
        label = clean_label(item.get("label", ""))
        colour = item.get("colour")
        if not (isinstance(colour, str) and _COLOUR_RE.match(colour)):
            colour = _free_colour(markers)
        markers.append({"x": x, "label": label, "colour": colour.lower()})
    markers.sort(key=lambda m: m["x"])
    return markers


def stored_value(markers):
    """JSON value stored in ``curve.metadata``."""
    return {"version": 1, "markers": [dict(m) for m in normalise_markers(markers)]}


def markers_of(curve, owner):
    metadata = getattr(curve, "metadata", None) or {}
    return normalise_markers(metadata.get(meta_key(owner)))


def add_marker(markers, x, label="", colour=None):
    """New list with one more marker; ``None`` if ``x`` is invalid or already used."""
    x = finite_float(x)
    if x is None or any(same_x(x, m["x"]) for m in markers):
        return None
    if not (isinstance(colour, str) and _COLOUR_RE.match(colour)):
        colour = _free_colour(markers)
    return normalise_markers([*markers, {"x": x, "label": clean_label(label), "colour": colour}])


def index_at(markers, x):
    """Index of the marker exactly at ``x`` (``None`` if there is none)."""
    x = finite_float(x)
    if x is None:
        return None
    return next((i for i, m in enumerate(markers) if same_x(m["x"], x)), None)


def remove_index(markers, index):
    return [m for i, m in enumerate(markers) if i != index]


def rename_index(markers, index, label):
    if not 0 <= index < len(markers):
        return None
    updated = [dict(m) for m in markers]
    updated[index]["label"] = clean_label(label)
    return updated


def format_x(x, unit=""):
    text = f"{x:.{SIGNIFICANT_DIGITS}g}"
    return f"{text} {unit}".strip() if unit else text


def marker_text(marker, unit=""):
    """Label text: optional name and abscissa."""
    value = f"x = {format_x(marker['x'], unit)}"
    return f"{marker['label']} — {value}" if marker.get("label") else value


def y_extent(y):
    """``(low, high)`` covering the finite y values with a 5 % margin, or ``None``."""
    y = np.asarray(y, dtype=float)
    finite = y[np.isfinite(y)]
    low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    span = high - low
    if not math.isfinite(span) or span <= 0.0:
        span = abs(high) if math.isfinite(high) and high != 0.0 else 1.0
    low, high = low - 0.05 * span, high + 0.05 * span
    return (low, high) if math.isfinite(low) and math.isfinite(high) else None


def layer_lines(curve, markers):
    """Vertical bars (plot-layer dictionaries) spanning the spectrum's y range."""
    extent = y_extent(curve.y) if markers else None
    if extent is None:
        return []
    low, high = extent
    return [{"x": np.array([m["x"], m["x"]], dtype=float),
             "y": np.array([low, high], dtype=float),
             "colour": m["colour"]} for m in markers]


def preview_items(x, y, markers, selected=None):
    """Plot-session preview of the markers on the main graph.

    Returns ``(segments, symbols, owners)``: one vertical two-point segment and
    one symbol per marker inside the data range, placed on the nearest
    measured sample; ``owners[i]`` is the marker index of ``symbols[i]``.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y) if x.shape == y.shape else np.zeros(0, bool)
    if not markers or not valid.any():
        return [], [], []
    rows = np.flatnonzero(valid)
    xs = x[rows]
    low, high = y_extent(y[rows])
    segments, symbols, owners = [], [], []
    for position, marker in enumerate(markers):
        if not xs.min() <= marker["x"] <= xs.max():
            continue
        row = int(rows[np.argmin(np.abs(xs - marker["x"]))])
        segments.append({"indices": [row, row], "y": [low, high], "colour": marker["colour"]})
        symbols.append({"index": row, "colour": marker["colour"], "symbol": "d",
                        "selected": position == selected})
        owners.append(position)
    return segments, symbols, owners


def _target_ids(context):
    ids = tuple(context.selected_curve_ids or ())
    active = context.active_curve_id
    if active is not None and active not in ids:
        ids = (active, *ids)
    return ids


def _curves(context):
    curves = []
    for curve_id in _target_ids(context):
        try:
            curves.append(context.project.dataset.curve(curve_id))
        except Exception:  # stale ID in the snapshot: skip it
            continue
    return curves


# --------------------------------------------------------------------------
# Hosted callbacks (must never raise for ordinary situations)
# --------------------------------------------------------------------------

def plot_markers_layer(context):
    """plot_layers: vertical bars for the active and selected spectra."""
    lines = []
    for curve in _curves(context):
        lines.extend(layer_lines(curve, markers_of(curve, context.owner)))
    return lines


def list_markers(context):
    """analysis: list the markers of the active and selected spectra."""
    curves = _curves(context)
    if not curves:
        return "No active or selected spectrum: select a spectrum first."
    blocks = []
    for curve in curves:
        unit = getattr(curve, "x_unit", "") or ""
        markers = markers_of(curve, context.owner)
        rows = [curve.name]
        if not markers:
            rows.append("  (no markers)")
        for number, marker in enumerate(markers, start=1):
            label = f"  {marker['label']}" if marker["label"] else ""
            rows.append(f"  {number:>3}. x = {format_x(marker['x'], unit)}{label}")
        blocks.append("\n".join(rows))
    tsv = [f"{curve.name}\t{m['x']!r}\t{m['label']}"
           for curve in curves for m in markers_of(curve, context.owner)]
    if tsv:
        blocks.append("TSV (spectrum, x, label):\n" + "\n".join(tsv))
    return "\n\n".join(blocks)


def create_panel(context):
    """panels: build the control panel (Qt imported only here)."""
    return _panel_class()(context.services, context.owner)


# --------------------------------------------------------------------------
# Qt control panel
# --------------------------------------------------------------------------

_PANEL_CLASS = None


def _panel_class():
    global _PANEL_CLASS
    if _PANEL_CLASS is None:
        _PANEL_CLASS = _build_panel_class()
    return _PANEL_CLASS


def _build_panel_class():  # noqa: C901 - Qt class built lazily
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QCheckBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class MarkerPanel(QWidget):
        POLL_MS = 500
        # content_hash ignores curve.metadata, so Undo/Redo of a marker does not
        # change active_spectrum_state(): the metadata is re-read every 2 s.
        RESYNC_TICKS = 4
        PICK_INSTRUCTION = ("Marker mode: click a sample to insert a marker, click a marked "
                            f"sample to remove it. Esc or {MARKER_MODE_SHORTCUT} ends.")

        def __init__(self, services, owner):
            super().__init__()
            self._services = services
            self._owner = owner
            self._key = meta_key(owner)
            self._state = None
            self._curve_id = None
            self._unit = ""
            self._x = np.empty(0)
            self._y = np.empty(0)
            self._markers = []
            self._session = None
            self._segments_ok = True
            self._preview_owners = []
            self._ticks = 0
            self._dead = False
            self._build_ui()
            self._timer = QTimer(self)
            self._timer.setInterval(self.POLL_MS)
            self._timer.timeout.connect(self._guard(self._poll))
            self._guard(self._poll)()

        # ---- infrastructure -------------------------------------------------
        def _guard(self, function):
            """The panel's own Qt slots are not guarded by the host (Section 5)."""
            def wrapped(*args):
                try:
                    return function(*args)
                except Exception as exc:  # noqa: BLE001 - shown to the user
                    self._set_status(f"Error: {exc}")
                    return None
            return wrapped

        def _set_status(self, text):
            self._status.setText(text)

        # ---- user interface -------------------------------------------------
        def _build_ui(self):
            has_session = hasattr(self._services, "plot_session")

            self._title = QLabel("No active spectrum", self)
            self._title.setWordWrap(True)

            self._mode_button = QPushButton(f"Marker mode on the main graph ({MARKER_MODE_SHORTCUT})", self)
            self._mode_button.setCheckable(True)
            self._mode_button.setEnabled(has_session)
            self._mode_button.setToolTip(self.PICK_INSTRUCTION)
            self._mode_button.toggled.connect(self._guard(lambda *_: self._sync_session()))

            self._show_main = QCheckBox("Show markers on the main graph", self)
            self._show_main.setChecked(has_session)
            self._show_main.setEnabled(has_session)
            self._show_main.toggled.connect(self._guard(lambda *_: self._sync_session()))

            self._ask_label = QCheckBox("Ask for a label when inserting", self)

            help_label = QLabel(
                f"Press <b>{MARKER_MODE_SHORTCUT}</b> (or the button) and click a sample on the main "
                "graph to insert a marker; click a marked sample to remove it. "
                "<b>Esc</b> ends marker mode. Undo with Ctrl+Z.", self)
            help_label.setWordWrap(True)

            self._list = QListWidget(self)
            self._list.setToolTip("Double-click: rename · Delete: remove")
            self._list.itemDoubleClicked.connect(self._guard(lambda item: self._rename_dialog(self._list.row(item))))
            self._list.currentRowChanged.connect(self._guard(lambda *_: self._update_preview()))

            remove_button = QPushButton("Remove selected", self)
            remove_button.clicked.connect(self._guard(lambda *_: self.remove_selected()))
            clear_button = QPushButton("Remove all", self)
            clear_button.clicked.connect(self._guard(lambda *_: self.clear_markers()))
            buttons = QHBoxLayout()
            buttons.addWidget(remove_button)
            buttons.addWidget(clear_button)

            self._x_edit = QLineEdit(self)
            self._x_edit.setPlaceholderText("Exact x")
            self._label_edit = QLineEdit(self)
            self._label_edit.setPlaceholderText("Label (optional)")
            self._label_edit.setMaxLength(MAX_LABEL_LENGTH)
            add_button = QPushButton("Add", self)
            for widget in (self._x_edit, self._label_edit):
                widget.returnPressed.connect(self._guard(self._add_from_fields))
            add_button.clicked.connect(self._guard(lambda *_: self._add_from_fields()))
            entry_row = QHBoxLayout()
            entry_row.addWidget(self._x_edit, 1)
            entry_row.addWidget(self._label_edit, 2)
            entry_row.addWidget(add_button)

            self._status = QLabel(self)
            self._status.setWordWrap(True)
            if not has_session:
                self._status.setText("This CurveMole version offers no plot sessions: "
                                     "main-graph interaction is unavailable.")

            # Application-wide shortcut, owned by this panel (active while the panel is shown).
            self._mode_shortcut = QShortcut(QKeySequence(MARKER_MODE_SHORTCUT), self)
            self._mode_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            self._mode_shortcut.activated.connect(self._guard(self.toggle_marker_mode))
            self._mode_shortcut.activatedAmbiguously.connect(self._guard(lambda: self._set_status(
                f"{MARKER_MODE_SHORTCUT} is also used by CurveMole: use the button instead.")))
            self._list_delete = QShortcut(QKeySequence("Delete"), self._list)
            self._list_delete.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._list_delete.activated.connect(self._guard(self.remove_selected))

            layout = QVBoxLayout(self)
            layout.addWidget(self._title)
            layout.addWidget(self._mode_button)
            layout.addWidget(self._show_main)
            layout.addWidget(self._ask_label)
            layout.addWidget(help_label)
            layout.addWidget(self._list, 1)
            layout.addLayout(buttons)
            layout.addLayout(entry_row)
            layout.addWidget(self._status)

        # ---- life cycle -----------------------------------------------------
        def showEvent(self, event):  # noqa: N802
            super().showEvent(event)
            if not self._dead:
                self._timer.start()
                self._guard(self._poll)()
                self._guard(self._sync_session)()

        def hideEvent(self, event):  # noqa: N802
            self._timer.stop()
            self._close_session()  # audit Section 9: close the session while hidden
            super().hideEvent(event)

        def poll_now(self):
            self._poll()

        def _poll(self):
            if self._dead:
                return
            try:
                state = self._services.active_spectrum_state()
            except ValueError:  # plugin disabled or unloaded
                self._dead = True
                self._timer.stop()
                self._close_session()
                self._set_status("Plugin unavailable: re-enable it in Plugin Manager.")
                return
            self._ticks += 1
            if state != self._state:
                self._reload(state)
            elif self._ticks % self.RESYNC_TICKS == 0 and self._curve_id is not None:
                self._resync_markers()

        def _active_curve(self):
            snapshot = self._services.spectrum_snapshot()
            if snapshot.active_curve_id is None:
                return None
            return snapshot.project.dataset.curve(snapshot.active_curve_id)

        def _reload(self, state):
            curve = self._active_curve()
            self._state = state
            previous = self._curve_id
            if curve is None:
                self._curve_id, self._unit, self._markers = None, "", []
                self._x, self._y = np.empty(0), np.empty(0)
                self._title.setText("No active spectrum")
            else:
                self._curve_id = curve.id
                self._unit = getattr(curve, "x_unit", "") or ""
                self._x = np.asarray(curve.x, dtype=float)
                self._y = np.asarray(curve.y, dtype=float)
                self._title.setText(f"<b>{html.escape(curve.name)}</b>")
                self._markers = markers_of(curve, self._owner)
            if previous != self._curve_id:
                self._close_session()
            self._refresh_list()
            self._sync_session()

        def _resync_markers(self):
            curve = self._active_curve()
            if curve is not None and curve.id == self._curve_id:
                markers = markers_of(curve, self._owner)
                if markers != self._markers:
                    self._markers = markers
                    self._refresh_list()

        def _refresh_list(self):
            row = self._list.currentRow()
            self._list.blockSignals(True)
            self._list.clear()
            for marker in self._markers:
                item = QListWidgetItem(marker_text(marker, self._unit))
                item.setForeground(QBrush(QColor(marker["colour"])))
                self._list.addItem(item)
            if 0 <= row < self._list.count():
                self._list.setCurrentRow(row)
            self._list.blockSignals(False)
            self._update_preview()

        # ---- marker operations ----------------------------------------------
        @property
        def markers(self):
            return [dict(m) for m in self._markers]

        def _commit(self, markers, message):
            if self._curve_id is None:
                self._set_status("Select a spectrum first.")
                return False
            try:
                self._services.save_settings(self._services.settings(), metadata_key=self._key,
                                             curve_metadata={self._curve_id: stored_value(markers)})
            except ValueError as exc:  # read-only project, running fit, stale ID...
                self._set_status(f"Cannot save the markers: {exc}")
                return False
            self._markers = normalise_markers(markers)
            self._refresh_list()
            self._set_status(message)
            return True

        def insert_marker(self, x, label=""):
            if self._curve_id is None:
                self._set_status("Select a spectrum first.")
                return False
            x = finite_float(x)
            if x is None:
                self._set_status("Invalid abscissa.")
                return False
            markers = add_marker(self._markers, x, label)
            if markers is None:
                self._set_status(f"There is already a marker at x = {format_x(x, self._unit)}.")
                return False
            return self._commit(markers, f"Marker inserted at x = {format_x(x, self._unit)}.")

        def remove_marker(self, index):
            if not 0 <= index < len(self._markers):
                self._set_status("No marker selected.")
                return False
            removed = self._markers[index]
            return self._commit(remove_index(self._markers, index),
                                f"Marker removed (x = {format_x(removed['x'], self._unit)}).")

        def remove_selected(self):
            return self.remove_marker(self._list.currentRow())

        def clear_markers(self):
            if not self._markers:
                self._set_status("No markers to remove.")
                return False
            return self._commit([], "All markers of this spectrum removed (Ctrl+Z restores them).")

        def rename_marker(self, index, label):
            markers = rename_index(self._markers, index, label)
            return False if markers is None else self._commit(markers, "Label updated.")

        def _rename_dialog(self, index):
            if not 0 <= index < len(self._markers):
                return
            text, ok = QInputDialog.getText(self, "Rename marker", "Label:",
                                            text=self._markers[index]["label"])
            if ok:
                self.rename_marker(index, text)

        def _add_from_fields(self):
            x = parse_x(self._x_edit.text())
            if x is None:
                self._set_status("Type a numeric abscissa in the x field.")
                return
            if self.insert_marker(x, self._label_edit.text()):
                self._x_edit.clear()
                self._label_edit.clear()

        # ---- main graph (plot session, audit Section 9) --------------------
        def toggle_marker_mode(self):
            if not self._mode_button.isEnabled():
                self._set_status("Main-graph interaction is unavailable in this CurveMole version.")
                return
            self.set_marker_mode(not self._mode_button.isChecked())

        def set_marker_mode(self, active):
            self._mode_button.setChecked(bool(active))

        def marker_mode(self):
            return self._mode_button.isChecked()

        def _wants_session(self):
            return self._show_main.isChecked() or self._mode_button.isChecked()

        def _close_session(self):
            session, self._session = self._session, None
            if session is not None and not getattr(session, "closed", False):
                with contextlib.suppress(Exception):  # already expired
                    session.close()

        def _uncheck_mode(self):
            self._mode_button.blockSignals(True)
            self._mode_button.setChecked(False)
            self._mode_button.blockSignals(False)

        def _sync_session(self):
            if not self._wants_session() or self._dead or not self.isVisible():
                self._close_session()
                return
            if self._curve_id is None:
                self._close_session()
                if self._mode_button.isChecked():
                    self._uncheck_mode()
                    self._set_status("Select a spectrum first.")
                return
            if self._session is None or getattr(self._session, "closed", False):
                try:
                    session = self._services.plot_session(self._curve_id)
                except ValueError as exc:  # hidden spectrum, running fit...
                    self._uncheck_mode()
                    self._set_status(f"Main graph unavailable: {exc}")
                    return
                session.sampleClicked.connect(self._guard(self._on_sample_clicked))
                session.markerClicked.connect(self._guard(self._on_main_marker_clicked))
                session.pickingChanged.connect(self._guard(self._on_picking_changed))
                session.invalidated.connect(self._guard(self._on_session_invalidated))
                self._session = session
            self._session.set_picking(self._mode_button.isChecked(), instruction=self.PICK_INSTRUCTION)
            if self._mode_button.isChecked():
                self._set_status("Marker mode active: click a sample on the main graph.")
            self._update_preview()

        def _update_preview(self):
            session = self._session
            if session is None or getattr(session, "closed", False):
                return
            if not self._show_main.isChecked():
                self._preview_owners = []
                session.set_preview()
                return
            segments, symbols, self._preview_owners = preview_items(
                self._x, self._y, self._markers, selected=self._list.currentRow())
            if self._segments_ok and segments:
                try:
                    session.set_preview(segments=segments, markers=symbols)
                    return
                except (ValueError, TypeError):
                    if getattr(session, "closed", False):
                        return
                    self._segments_ok = False  # host refuses vertical segments: symbols only
            session.set_preview(markers=symbols)

        def _on_sample_clicked(self, row):
            curve = self._active_curve()
            if curve is None or curve.id != self._curve_id:
                return
            x = np.asarray(curve.x, dtype=float)
            row = int(row)
            if not 0 <= row < x.size or not math.isfinite(x[row]):
                return
            existing = index_at(self._markers, x[row])
            if existing is not None:
                self.remove_marker(existing)
                return
            label = ""
            if self._ask_label.isChecked():
                label, ok = QInputDialog.getText(
                    self, "Insert marker", f"Label of the marker at x = {format_x(x[row], self._unit)}:")
                if not ok:
                    return
            self.insert_marker(float(x[row]), label)

        def _on_main_marker_clicked(self, position):
            position = int(position)
            if 0 <= position < len(self._preview_owners):
                self._list.setCurrentRow(self._preview_owners[position])

        def _on_picking_changed(self, active):
            if active:
                return
            session = self._session

            def user_stopped():
                # Esc pressed by the user: the session is still alive, so marker
                # mode is switched off. If the host invalidated the session
                # instead (active spectrum, visibility or data changed), the
                # invalidated handler recreates it and marker mode stays on.
                # Saving markers only changes metadata, which does not
                # invalidate the session.
                if (session is not None and self._session is session
                        and not getattr(session, "closed", False) and self._mode_button.isChecked()):
                    self._uncheck_mode()
                    self._set_status("Marker mode ended.")

            QTimer.singleShot(0, self._guard(user_stopped))

        def _on_session_invalidated(self, *_):
            self._session = None
            if self._wants_session():
                QTimer.singleShot(250, self._guard(self._recreate_session))

        def _recreate_session(self):
            self._poll()           # pick up a new active spectrum first
            self._sync_session()

    return MarkerPanel


# --------------------------------------------------------------------------
# Registration: registrations only, no computation, I/O or dialogs
# --------------------------------------------------------------------------

def register(api):
    api.add("panels", "markers_panel", "Vertical markers", create_panel,
            description=f"Insert vertical markers by clicking the main graph (marker mode: {MARKER_MODE_SHORTCUT})",
            auto_show=True)
    api.add("plot_layers", "markers_layer", "Vertical markers", plot_markers_layer,
            description="Draw the markers of the active and selected spectra on the main graph")
    api.add("analysis", "markers_list", "Marker list", list_markers,
            description="List the marker abscissae of the active and selected spectra")
