from curvemole.gui.fit_undo import _changed_curve_ids, _restore_results


def _state(results, states=None, scope=("A",)):
    return {"results": results, "states": states or {}, "scope": set(scope)}


def test_restore_keeps_other_spectra_results_added_after_the_snapshot():
    fit_a_old, fit_a_new, report_b = object(), object(), object()
    saved = {"fit_by_curve": {"A": fit_a_old}, "last_fit": "old"}
    current = {"fit_by_curve": {"A": fit_a_new},
               "uncertainty_reports_by_curve": {"B": {"covariance": report_b}}, "last_fit": "new"}
    restored = _restore_results(current, saved, {"A"})
    assert restored["fit_by_curve"] == {"A": fit_a_old}
    assert restored["uncertainty_reports_by_curve"] == {"B": {"covariance": report_b}}
    assert restored["last_fit"] == "old"


def test_changed_ids_include_curves_touched_outside_the_fit_scope():
    shared = object()
    before = _state({"fit_by_curve": {"A": shared, "C": shared}}, {"A": 1, "C": 1})
    after = _state({"fit_by_curve": {"A": object(), "C": shared}}, {"A": 2, "C": 1})
    assert _changed_curve_ids(before, after) == {"A"}
    after["states"]["C"] = 3
    assert _changed_curve_ids(before, after) == {"A", "C"}
