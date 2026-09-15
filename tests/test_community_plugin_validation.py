import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("community_validator", ROOT / "scripts/validate_community_plugins.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_rejects_invalid_manifest_and_paths(tmp_path):
    source = ROOT / "custom_plugins/tsv_exporter/tsv_exporter.curvemole-plugin.json"
    data = json.loads(source.read_text())
    for key, value in (("module", "../outside.py"), ("capabilities", ["invented"]),
                       ("version", "bad"), ("author", "")):
        path = tmp_path / "bad.curvemole-plugin.json"
        path.write_text(json.dumps({**data, key: value}))
        with pytest.raises(ValueError):
            validator.inspect_manifest(path)


def test_failed_validation_removes_stale_catalog(tmp_path):
    root = tmp_path / "plugins"
    (root / "broken").mkdir(parents=True)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"plugins": ["stale"]}')
    with pytest.raises(ValueError, match="exactly one manifest"):
        validator.validate(root, catalog)
    assert not catalog.exists()


def test_example_manifest_and_fingerprint():
    folder = ROOT / "custom_plugins/tsv_exporter"
    data = validator.inspect_manifest(next(folder.glob("*.curvemole-plugin.json")))
    assert data["capabilities"] == ["exporters"]
    assert len(validator.fingerprint(folder)) == 64
