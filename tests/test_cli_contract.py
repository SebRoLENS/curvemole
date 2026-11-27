import json
from pathlib import Path

import numpy as np

from curvemole import cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "gaussian.csv"


def _two_peaks(tmp_path):
    x = np.linspace(0, 100, 801)
    y = 50 * np.exp(-0.5 * ((x - 30) / 2) ** 2) + 30 * np.exp(-0.5 * ((x - 70) / 3) ** 2) + 1
    path = tmp_path / "two.csv"
    np.savetxt(path, np.c_[x, y], delimiter=",", header="x,y", comments="")
    return path


def test_missing_input_is_a_data_error_without_traceback(capsys, tmp_path):
    assert cli.main(["fit", str(tmp_path / "missing.csv"), "--x", "0", "--y", "1"]) == cli.EXIT_DATA
    assert "Traceback" not in capsys.readouterr().err


def test_existing_output_is_a_usage_error(tmp_path):
    output = tmp_path / "result.fitproj"
    output.write_text("keep")
    code = cli.main(["fit", str(EXAMPLE), "--x", "0", "--y", "1", "--output", str(output)])
    assert code == cli.EXIT_USAGE
    assert output.read_text() == "keep"


def test_unsuccessful_fit_returns_fit_exit_code(monkeypatch, capsys):
    from curvemole.core.fitting import Fitter

    original = Fitter.fit

    def failing(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result.success = False
        return result

    monkeypatch.setattr(Fitter, "fit", failing)
    assert cli.main(["fit", str(EXAMPLE), "--x", "0", "--y", "1"]) == cli.EXIT_FIT


def test_json_output_is_standard_json_and_labels_parameters(capsys):
    assert cli.main(["--json", "fit", str(EXAMPLE), "--x", "0", "--y", "1", "--sigma-y", "sigma_y"]) == 0
    text = capsys.readouterr().out
    assert "Infinity" not in text and "NaN" not in text
    payload = json.loads(text)
    labels = {item["label"] for item in payload["parameters"].values()}
    assert "gaussian / Gaussian / center" in labels
    assert payload["statistics"]["reduced_chi_square"] is not None  # sigma_y was used


def test_peaks_option_fits_several_peaks_and_warns_when_more_are_found(tmp_path, capsys):
    path = _two_peaks(tmp_path)
    assert cli.main(["--json", "fit", str(path), "--x", "0", "--y", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("--peaks" in warning for warning in payload["warnings"])
    assert cli.main(["--json", "fit", str(path), "--x", "0", "--y", "1", "--peaks", "2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    centres = sorted(item["value"] for item in payload["parameters"].values() if item["label"].endswith("center"))
    assert np.allclose(centres, [30, 70], atol=0.1)
    assert payload["statistics"]["R_squared"] > 0.999
