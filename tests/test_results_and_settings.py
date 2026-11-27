import numpy as np

from curvemole import Project
from curvemole.core.results_store import RESULT_MAPS, ResultKey, ResultsStore


def test_results_store_is_a_typed_view_without_changing_the_saved_format():
    project = Project("p")
    store = project.results_store
    assert isinstance(store, ResultsStore)
    store.fit_by_curve["curve_1"] = "fit"
    store.uncertainty_reports_by_curve.setdefault("curve_1", {})["block_bootstrap"] = "report"
    store.uncertainty_display_method = "block_bootstrap"
    assert project.results == {
        "fit_by_curve": {"curve_1": "fit"},
        "uncertainty_reports_by_curve": {"curve_1": {"block_bootstrap": "report"}},
        "uncertainty_display_method": "block_bootstrap",
    }
    assert store.uncertainty_report("curve_1", "block_bootstrap") == "report"
    assert store.uncertainty_report("missing", "block_bootstrap") is None
    assert ResultKey.FIT_BY_CURVE in RESULT_MAPS


def test_no_results_key_is_spelled_as_a_literal_in_the_code():
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src" / "curvemole"
    keys = [value for name, value in vars(ResultKey).items() if name.isupper()]
    pattern = re.compile(r"results(?:_snapshot)?\s*(?:\[|\.get\(|\.setdefault\(|\.pop\()\s*\"("
                         + "|".join(map(re.escape, keys)) + r")\"")
    offenders = [f"{path.name}" for path in source.rglob("*.py")
                 if path.name != "results_store.py" and pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_settings_follow_the_owning_window(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QWidget

    from curvemole.gui.app_settings import settings_for

    QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.settings = QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat)
    child = QWidget(owner)
    assert settings_for(child) is owner.settings
    assert settings_for(None).organizationName() == "CurveMole"


def test_application_paths_are_resolved_through_platformdirs(monkeypatch, tmp_path):
    import platformdirs

    from curvemole import app_paths

    monkeypatch.setattr(platformdirs, "user_config_path", lambda name: tmp_path / "config" / name)
    monkeypatch.setattr(platformdirs, "user_cache_path", lambda name: tmp_path / "cache" / name)
    assert app_paths.plugin_storage() == tmp_path / "config" / "CurveMole" / "plugins"
    assert app_paths.recovery_dir() == tmp_path / "cache" / "CurveMole" / "recovery"
    assert np.isfinite(len(str(app_paths.data_dir())))
