from curvemole.core.fitting import FitMode, FitResult, FitSettings
from curvemole.gui.app import _normalise_fit_result_mode


def test_gui_fit_result_string_mode_is_normalised_before_serialisation() -> None:
    result = FitResult(
        success=True,
        mode="independent",  # type: ignore[arg-type]
        message="ok",
        status=1,
        evaluations=1,
        parameters={},
        curve_outputs={},
        statistics={},
        warnings=[],
        settings=FitSettings(),
        free_parameter_paths=[],
    )

    _normalise_fit_result_mode(result)

    assert result.mode is FitMode.INDEPENDENT
    assert result.to_dict()["mode"] == "independent"
