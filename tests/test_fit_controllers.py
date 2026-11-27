def test_window_fit_and_uncertainty_entry_points_delegate_to_controllers():
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import CurveMoleMainWindow
    from curvemole.gui.fit_controller import FitController
    from curvemole.gui.uncertainty_controller import UncertaintyController

    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow()
    try:
        assert isinstance(window.fit_controller, FitController)
        assert isinstance(window.uncertainty_controller, UncertaintyController)
        for name in ("start_fit", "_run_fit", "_fit_finished_core", "_apply_fit_result_to_project"):
            assert callable(getattr(FitController, name))
        for name in ("start_uncertainty", "_uncertainty_finished", "delete_uncertainty_analysis"):
            assert callable(getattr(UncertaintyController, name))
        # The status-bar sequence controls exist but stay hidden without a paused sequence.
        assert window.sequential_resume_button.isHidden()
        assert window.sequential_stop_button.isHidden()
        window.terminate_sequence()
        assert not window.resume_action.isEnabled()
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()
