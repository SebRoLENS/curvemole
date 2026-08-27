from pathlib import Path

path = Path('tests/test_gui_smoke.py')
text = path.read_text(encoding='utf-8')
old = '''def test_spline_bulk_lock_controls_and_background_subtraction() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Background")
    curve = Curve(
        "curve",
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [2.0, 3.0, 5.0, 3.0, 2.0],
    )
    curve.mask_interval(1.0, 3.0)
    project.add_curve(curve)
    spline = Component.create("cubic_spline", metadata={"x_nodes": [0.0, 4.0]})
    initialise_spline_component = pytest.importorskip(
        "curvemole.core.initialization"
    ).initialise_spline_component
    initialise_spline_component(spline, [(0.0, 2.0), (4.0, 2.0)])
    project.model_for(curve.id).add(spline)
    project.dirty = False
    window = MainWindow(project)
    window._set_component(spline.id)

    assert all(parameter.fixed for parameter in spline.parameters.values())
    window.model_panel.unlock_all_parameters_button.click()
    assert all(not parameter.fixed for parameter in spline.parameters.values())
    window.model_panel.lock_all_parameters_button.click()
    assert all(parameter.fixed for parameter in spline.parameters.values())

    mask_before = curve.effective_mask.copy()
    window._pending_background_subtraction_curve_id = curve.id
    window._graphical_spline_placed([(0.0, 2.0), (4.0, 2.0)])
    assert curve.y.tolist() == pytest.approx([0.0, 1.0, 3.0, 1.0, 0.0])
    assert curve.effective_mask.tolist() == mask_before.tolist()
    assert curve.transformations[-1].operation == "background_subtract"

    project.dirty = False
    window.close()
    app.processEvents()
'''
new = '''def test_spline_bulk_lock_controls_and_background_subtraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Background")
    curve = Curve(
        "curve",
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [2.0, 3.0, 5.0, 3.0, 2.0],
    )
    curve.mask_interval(1.0, 3.0)
    project.add_curve(curve)
    spline = Component.create("cubic_spline", metadata={"x_nodes": [0.0, 4.0]})
    initialise_spline_component = pytest.importorskip(
        "curvemole.core.initialization"
    ).initialise_spline_component
    initialise_spline_component(spline, [(0.0, 2.0), (4.0, 2.0)])
    project.model_for(curve.id).add(spline)
    project.dirty = False
    window = MainWindow(project)
    window._set_component(spline.id)

    assert all(parameter.fixed for parameter in spline.parameters.values())
    window.model_panel.unlock_all_parameters_button.click()
    assert all(not parameter.fixed for parameter in spline.parameters.values())
    window.model_panel.lock_all_parameters_button.click()
    assert all(parameter.fixed for parameter in spline.parameters.values())

    class FakeBackgroundDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def exec(self) -> int:
            return self.DialogCode.Accepted

        def selected_component_ids(self) -> list[str]:
            return [spline.id]

    monkeypatch.setattr(
        "curvemole.gui.main_window.BackgroundComponentsDialog",
        FakeBackgroundDialog,
    )

    mask_before = curve.effective_mask.copy()
    window.subtract_background()
    assert curve.y.tolist() == pytest.approx([0.0, 1.0, 3.0, 1.0, 0.0])
    assert curve.effective_mask.tolist() == mask_before.tolist()
    assert curve.transformations[-1].operation == "background_subtract"
    assert spline.is_background is True
    assert spline.enabled is False

    window.undo_stack.undo()
    assert curve.y.tolist() == pytest.approx([2.0, 3.0, 5.0, 3.0, 2.0])
    assert spline.is_background is False
    assert spline.enabled is True

    window.undo_stack.redo()
    assert curve.y.tolist() == pytest.approx([0.0, 1.0, 3.0, 1.0, 0.0])
    assert spline.is_background is True
    assert spline.enabled is False

    project.dirty = False
    window.close()
    app.processEvents()
'''
if old not in text:
    raise SystemExit('Legacy background test block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('Legacy background regression test updated')
