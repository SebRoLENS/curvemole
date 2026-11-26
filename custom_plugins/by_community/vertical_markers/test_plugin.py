"""Functional tests of the "Vertical markers" plugin (offline, non-interactive)."""

import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from curvemole import Curve
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.project import Project
from curvemole.gui.plugin_host import PluginContext

HERE = Path(__file__).parent
MANIFEST = json.loads(next(HERE.glob("*.curvemole-plugin.json")).read_text(encoding="utf-8"))
OWNER = MANIFEST["identifier"]


def _module():
    """Module loaded directly, to test the pure logic."""
    spec = importlib.util.spec_from_file_location("vertical_markers_under_test", HERE / MANIFEST["module"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vm = _module()


def _load():
    manager = PluginManager()
    candidate = next(c for c in manager.discover_local(HERE) if c.metadata.identifier == OWNER)
    manager.load(candidate, trust=True)
    return manager, OWNER


def _project_with_curve(markers=None, unit="nm"):
    project = Project()
    curve = Curve("Spectrum A", [1.0, 2.0, 3.0, 4.0], [10.0, 30.0, 20.0, 15.0], x_unit=unit)
    project.add_curve(curve)
    if markers is not None:
        curve.metadata[vm.meta_key(OWNER)] = vm.stored_value(markers)
    return project, curve


# ---------------------------------------------------------------- registration

def test_registrations_match_manifest_and_disable_cleans_up():
    manager, owner = _load()
    try:
        keys = {f"{owner}:markers_panel", f"{owner}:markers_layer", f"{owner}:markers_list"}
        assert keys <= set(extensions.entries)
        assert set(MANIFEST["capabilities"]) == {"panels", "plot_layers", "analysis"}
    finally:
        manager.disable(owner)
    assert not any(key.startswith(owner + ":") for key in extensions.entries)


# ---------------------------------------------------------------- pure logic

def test_normalise_sorts_and_drops_invalid_entries():
    raw = {"markers": [{"x": 3}, {"x": "nan"}, {"x": 1.5, "label": "  peak  ", "colour": "#ABCDEF"},
                       "rubbish", {"x": 3.0}, {"x": float("inf")}]}
    markers = vm.normalise_markers(raw)
    assert [m["x"] for m in markers] == [1.5, 3.0]
    assert markers[0] == {"x": 1.5, "label": "peak", "colour": "#abcdef"}
    assert vm.normalise_markers(None) == [] and vm.normalise_markers("x") == []
    json.dumps(vm.stored_value(markers), allow_nan=False)  # valid JSON, no NaN


def test_add_rename_remove_and_formatting():
    markers = vm.add_marker([], 2.5, "Peak A")
    assert markers == [{"x": 2.5, "label": "Peak A", "colour": vm.PALETTE[0]}]
    assert vm.add_marker(markers, 2.5) is None           # duplicate
    assert vm.add_marker(markers, float("nan")) is None  # not finite
    markers = vm.add_marker(markers, 1.0)
    assert [m["x"] for m in markers] == [1.0, 2.5] and markers[0]["colour"] == vm.PALETTE[1]
    assert vm.index_at(markers, 2.5) == 1 and vm.index_at(markers, 2.0) is None
    assert vm.rename_index(markers, 1, " B ")[1]["label"] == "B"
    assert vm.remove_index(markers, 0) == [markers[1]]
    assert vm.parse_x(" 532,25 ") == 532.25 and vm.parse_x("abc") is None
    assert vm.marker_text({"x": 532.25, "label": ""}, "nm") == "x = 532.25 nm"
    assert vm.marker_text({"x": 532.25, "label": "Raman"}, "nm") == "Raman — x = 532.25 nm"


def test_preview_items_place_vertical_segments_on_nearest_samples():
    markers = vm.normalise_markers([{"x": 2.2, "colour": "#0072b2"}, {"x": 9.0}, {"x": 3.9}])
    segments, symbols, owners = vm.preview_items([1, 2, 3, 4, 5], [10, 30, 20, np.nan, 15], markers, selected=0)
    assert owners == [0, 1]                                  # x = 9 is outside the data
    assert segments[0] == {"indices": [1, 1], "y": [9.0, 31.0], "colour": "#0072b2"}
    assert segments[1]["indices"] == [2, 2]                  # row 3 has NaN y: nearest valid row
    assert symbols[0]["selected"] and not symbols[1]["selected"]
    assert vm.preview_items([1, 2], [1, 2], []) == ([], [], [])


# ---------------------------------------------------------------- plot layer and analysis

def test_plot_layer_draws_finite_vertical_bars_over_y_range():
    manager, owner = _load()
    try:
        project, curve = _project_with_curve([{"x": 2.5, "colour": "#0072b2"}, {"x": 3.5}])
        context = PluginContext(project, curve.id, (), owner)
        lines = extensions.entries[owner + ":markers_layer"].callback(context)
        assert len(lines) == 2
        np.testing.assert_allclose(lines[0]["x"], [2.5, 2.5])
        np.testing.assert_allclose(lines[0]["y"], [9.0, 31.0])  # 10..30 with a 5 % margin
        assert lines[0]["colour"] == "#0072b2"
        assert all(np.isfinite(line["x"]).all() and np.isfinite(line["y"]).all() for line in lines)
    finally:
        manager.disable(owner)


def test_plot_layer_and_analysis_handle_empty_project_without_raising():
    manager, owner = _load()
    try:
        context = PluginContext(Project(), None, (), owner)
        assert extensions.entries[owner + ":markers_layer"].callback(context) == []
        text = extensions.entries[owner + ":markers_list"].callback(context)
        assert "No active or selected spectrum" in text
    finally:
        manager.disable(owner)


def test_analysis_lists_markers_of_active_and_selected_spectra():
    manager, owner = _load()
    try:
        project, curve = _project_with_curve([{"x": 2.5, "label": "Peak A"}])
        other = Curve("Spectrum B", [0.0, 1.0], [1.0, 2.0])
        project.add_curve(other)
        context = PluginContext(project, curve.id, (other.id,), owner)
        text = extensions.entries[owner + ":markers_list"].callback(context)
        assert "Spectrum A" in text and "x = 2.5 nm  Peak A" in text
        assert "Spectrum B" in text and "(no markers)" in text
        assert "Spectrum A\t2.5\tPeak A" in text
    finally:
        manager.disable(owner)


# ---------------------------------------------------------------- panel and main graph

class FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class FakeSession:
    """Plot session stand-in recording previews and picking state."""

    def __init__(self, curve_id, refuse_segments=False):
        self.curve_id = curve_id
        self.refuse_segments = refuse_segments
        self.closed = False
        self.picking = False
        self.previews = []
        self.sampleClicked, self.markerClicked = FakeSignal(), FakeSignal()
        self.pickingChanged, self.invalidated = FakeSignal(), FakeSignal()

    def set_preview(self, segments=None, markers=None, selected_interval=None):
        if segments and self.refuse_segments:
            raise ValueError("segments not supported")
        self.previews.append({"segments": segments or [], "markers": markers or []})

    def set_picking(self, active, instruction=""):
        self.picking = bool(active)

    def close(self):
        self.closed = True


class FakeServices:
    """Minimal services; save_settings writes the metadata like the host does."""

    def __init__(self, project, curve_id, with_session=True, refuse_segments=False):
        self.project = project
        self.curve_id = curve_id
        self.data = {}
        self.saved = []
        self.fail = None
        self.disabled = False
        self.sessions = []
        if with_session:
            def plot_session(curve_id):
                self._check()
                session = FakeSession(curve_id, refuse_segments)
                self.sessions.append(session)
                return session
            self.plot_session = plot_session

    def _check(self):
        if self.disabled:
            raise ValueError("Plugin disabled")

    def settings(self):
        self._check()
        return copy.deepcopy(self.data)

    def active_spectrum_state(self):
        self._check()
        if self.curve_id is None:
            return ("p", None, None, None)
        curve = self.project.dataset.curve(self.curve_id)
        markers = json.dumps(curve.metadata.get(vm.meta_key(OWNER)), sort_keys=True)
        return ("p", curve.id, markers, curve.name)

    def spectrum_snapshot(self, **_):
        self._check()
        return SimpleNamespace(project=self.project, active_curve_id=self.curve_id)

    def save_settings(self, data, *, metadata_key=None, curve_metadata=None):
        self._check()
        if self.fail:
            raise ValueError(self.fail)
        json.dumps([data, curve_metadata], allow_nan=False)
        self.saved.append((metadata_key, copy.deepcopy(curve_metadata)))
        self.data = copy.deepcopy(data)
        for curve_id, value in (curve_metadata or {}).items():
            self.project.dataset.curve(curve_id).metadata[metadata_key] = copy.deepcopy(value)


def _make_panel(request, **service_options):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    manager, owner = _load()
    project, curve = _project_with_curve()
    services = FakeServices(project, curve.id, **service_options)
    context = PluginContext(project, curve.id, (), owner, services=services)
    panel = extensions.entries[owner + ":markers_panel"].callback(context)
    panel.show()
    app.processEvents()

    def cleanup():
        panel.hide()
        panel.deleteLater()
        app.processEvents()
        manager.disable(owner)

    request.addfinalizer(cleanup)
    return SimpleNamespace(app=app, panel=panel, services=services, curve=curve, owner=owner)


@pytest.fixture()
def env(request):
    return _make_panel(request)


def _stored(env):
    return vm.normalise_markers(env.curve.metadata.get(vm.meta_key(env.owner)))


def _session(env):
    live = [s for s in env.services.sessions if not s.closed]
    assert len(live) == 1
    return live[0]


def test_clicking_main_graph_in_marker_mode_inserts_and_removes(env):
    env.panel.set_marker_mode(True)
    session = _session(env)
    assert session.picking and session.curve_id == env.curve.id
    session.sampleClicked.emit(1)                      # sample x = 2.0
    assert env.services.saved[-1][0] == vm.meta_key(env.owner)
    assert [m["x"] for m in _stored(env)] == [2.0]
    assert env.panel._list.item(0).text() == "x = 2 nm"
    last = session.previews[-1]
    assert last["segments"][0]["indices"] == [1, 1] and last["markers"][0]["index"] == 1
    session.sampleClicked.emit(1)                      # same sample again: removed
    assert _stored(env) == []
    session.sampleClicked.emit(99)                     # stale row: ignored, no exception
    assert _stored(env) == []


def test_shortcut_toggles_marker_mode_application_wide(env):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence

    shortcut = env.panel._mode_shortcut
    assert shortcut.key() == QKeySequence(vm.MARKER_MODE_SHORTCUT)
    assert shortcut.context() == Qt.ShortcutContext.ApplicationShortcut
    shortcut.activated.emit()
    assert env.panel.marker_mode() and _session(env).picking
    shortcut.activated.emit()
    assert not env.panel.marker_mode() and not _session(env).picking


def test_escape_on_main_graph_ends_marker_mode(env):
    env.panel.set_marker_mode(True)
    session = _session(env)
    session.picking = False
    session.pickingChanged.emit(False)
    env.app.processEvents()
    assert not env.panel.marker_mode()


def test_expired_session_is_recreated_and_keeps_marker_mode(env):
    from PySide6.QtTest import QTest

    env.panel.set_marker_mode(True)
    old = _session(env)
    old.closed = True
    old.pickingChanged.emit(False)
    old.invalidated.emit()
    QTest.qWait(400)
    new = _session(env)
    assert new is not old and new.picking and env.panel.marker_mode()


def test_symbols_only_when_host_refuses_vertical_segments(request):
    env = _make_panel(request, refuse_segments=True)
    env.panel.insert_marker(3.0)
    last = _session(env).previews[-1]
    assert last["segments"] == [] and last["markers"][0]["index"] == 2


def test_failures_are_reported_not_raised(env):
    panel = env.panel
    env.services.fail = "The project is read-only"
    assert panel.insert_marker(2.0) is False
    assert "read-only" in panel._status.text()
    assert panel.markers == [] and _stored(env) == []
    env.services.fail = None
    assert panel.insert_marker(float("nan")) is False
    assert panel.insert_marker(2.0) and panel.insert_marker(2.0) is False  # duplicate
    assert "already a marker" in panel._status.text()
    assert panel.remove_marker(5) is False


def test_undo_in_host_is_picked_up_and_disabled_plugin_stops_polling(env):
    panel = env.panel
    panel.insert_marker(2.0)
    env.curve.metadata[vm.meta_key(env.owner)] = vm.stored_value([])  # simulated Undo
    panel.poll_now()
    assert panel.markers == []
    env.services.disabled = True
    panel.poll_now()  # must not raise
    assert "unavailable" in panel._status.text()


def test_hiding_the_panel_closes_the_session(env):
    env.panel.set_marker_mode(True)
    session = _session(env)
    env.panel.hide()
    assert session.closed


def test_main_graph_controls_disabled_without_plot_session(request):
    env = _make_panel(request, with_session=False)
    assert not env.panel._mode_button.isEnabled()
    env.panel.toggle_marker_mode()
    assert not env.panel.marker_mode() and "unavailable" in env.panel._status.text()
