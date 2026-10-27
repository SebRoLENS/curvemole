from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def target_script():
    spec = importlib.util.spec_from_file_location("target_test", ROOT / ".github/scripts/release_target.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_target(root, version):
    (root / ".github").mkdir(exist_ok=True)
    (root / ".github/release-target.json").write_text(json.dumps({"version": version}) + "\n")


def test_minor_target_is_independent_of_stable_metadata(tmp_path):
    module = target_script()
    write_target(tmp_path, "1.1.0")
    before = (tmp_path / module.TARGET_FILE).read_bytes()
    assert module.beta_target("1.0.1", tmp_path) == "1.1.0"
    assert module.promotion_target("", tmp_path) == "1.1.0"
    assert module.promotion_target("1.1.0", tmp_path) == "1.1.0"
    with pytest.raises(ValueError, match="must match"):
        module.promotion_target("1.0.2", tmp_path)
    assert (tmp_path / module.TARGET_FILE).read_bytes() == before


@pytest.mark.parametrize("version", ["1.1.0b1", "1.1.0-beta.1", "v1.1.0", "01.1.0", "1.1", "1.1.0\n", None, 1])
def test_invalid_final_targets_are_rejected(tmp_path, version):
    module = target_script()
    write_target(tmp_path, version)
    with pytest.raises(ValueError):
        module.read_target(tmp_path)


@pytest.mark.parametrize("target", ["1.0.0", "1.0.1"])
def test_beta_target_must_be_newer_than_stable(tmp_path, target):
    module = target_script()
    write_target(tmp_path, target)
    with pytest.raises(ValueError, match="newer"):
        module.beta_target("1.0.1", tmp_path)


def test_missing_target_is_an_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="Cannot read release target"):
        target_script().read_target(tmp_path)


def test_sync_advances_exhausted_cycle_and_preserves_newer_target(tmp_path):
    module = target_script()
    write_target(tmp_path, "1.1.0")
    assert module.advance_target("1.1.0", tmp_path)
    assert module.read_target(tmp_path) == "1.1.1"
    assert not module.advance_target("1.1.0", tmp_path)
    write_target(tmp_path, "1.2.0")
    assert not module.advance_target("1.1.0", tmp_path)
    assert module.read_target(tmp_path) == "1.2.0"
