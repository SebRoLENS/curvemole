from __future__ import annotations

from pathlib import Path

import pytest

from curvemole.core.errors import CurveMoleError
from curvemole.core.workflow_inputs import (
    format_import_name,
    resolve_import_paths,
    validate_import_source,
    validate_name_template,
)


def _file(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x,y\n0,1\n1,2\n", encoding="utf-8")
    return path.resolve()


def test_directory_defaults_and_natural_or_lexical_order(tmp_path):
    files = [_file(tmp_path, f"data/scan{number}.csv") for number in (10, 2, 1)]
    _file(tmp_path, "data/readme.txt")
    _file(tmp_path, "data/nested/scan0.csv")
    spec = {"directory": "data"}
    assert resolve_import_paths(spec, tmp_path) == [files[2], files[1], files[0]]
    assert resolve_import_paths(spec | {"sort": "lexical"}, tmp_path) == [files[2], files[0], files[1]]
    assert set(resolve_import_paths(spec | {"sort": "none"}, tmp_path)) == set(files)


def test_recursive_directory_patterns_and_relative_exclusions(tmp_path):
    keep = _file(tmp_path, "data/day1/sample2.csv")
    _file(tmp_path, "data/day1/calibration.csv")
    _file(tmp_path, "data/day2/sample1.csv")
    top = _file(tmp_path, "data/sample1.csv")
    assert resolve_import_paths({
        "directory": "data", "recursive": True,
        "exclude": ["calibration.csv", "day2/*.csv"],
    }, tmp_path) == [keep, top]


def test_glob_is_relative_to_workflow_and_explicit_depth_is_supported(tmp_path, monkeypatch):
    expected = _file(tmp_path, "spectra/day1/spectrum.csv")
    _file(tmp_path, "spectra/day1/deeper/other.csv")
    monkeypatch.chdir(tmp_path.parent)
    assert resolve_import_paths({"glob": "spectra/day*/*.csv"}, tmp_path) == [expected]
    assert resolve_import_paths({"glob": str(tmp_path / "spectra/day*/*.csv")}, tmp_path) == [expected]


def test_recursive_glob_exclusions_and_duplicate_matches(tmp_path):
    first = _file(tmp_path, "scan.csv")
    second = _file(tmp_path, "sub/scan.csv")
    _file(tmp_path, "sub/deep/calibration.csv")
    spec = {"glob": "**/**/scan.csv", "recursive": True}
    assert resolve_import_paths(spec, tmp_path) == [first, second]
    assert resolve_import_paths(spec | {"exclude": ["sub/**/*.csv"]}, tmp_path) == [first]


def test_hidden_entries_and_symlinks_are_not_implicitly_discovered(tmp_path):
    visible = _file(tmp_path, "data/scan.csv")
    hidden = _file(tmp_path, "data/.hidden.csv")
    _file(tmp_path, "data/.hidden_dir/secret.csv")
    outside = _file(tmp_path, "outside/elsewhere.csv")
    try:
        (tmp_path / "data/linked.csv").symlink_to(outside)
        (tmp_path / "data/linked-dir").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert resolve_import_paths({"directory": "data", "recursive": True}, tmp_path) == [visible]
    assert resolve_import_paths({"directory": "data", "pattern": ".*.csv"}, tmp_path) == [hidden]
    assert resolve_import_paths({"path": "data/linked.csv"}, tmp_path) == [outside]


def test_literal_path_preserves_brackets_and_does_not_expand_wildcards(tmp_path):
    literal = _file(tmp_path, "measurement[1].csv")
    assert resolve_import_paths({"path": literal.name}, tmp_path) == [literal]
    with pytest.raises(CurveMoleError, match="use glob"):
        resolve_import_paths({"path": "measurement*.csv"}, tmp_path)
    with pytest.raises(CurveMoleError, match="use directory"):
        resolve_import_paths({"path": "."}, tmp_path)


@pytest.mark.parametrize("source", [{"glob": "absent/*.csv"}, {"directory": "empty"}])
def test_unmatched_sources_require_explicit_allow_empty(tmp_path, source):
    (tmp_path / "empty").mkdir()
    with pytest.raises(CurveMoleError, match="matched no files"):
        resolve_import_paths(source, tmp_path)
    assert resolve_import_paths(source | {"allow_empty": True}, tmp_path) == []


def test_allow_empty_does_not_hide_missing_directory(tmp_path):
    with pytest.raises(CurveMoleError, match="directory does not exist"):
        resolve_import_paths({"directory": "missing", "allow_empty": True}, tmp_path)


@pytest.mark.parametrize("source", [
    {}, {"path": "x", "glob": "x"}, {"directory": None}, {"glob": []},
    {"directory": "x", "recursive": "true"}, {"directory": "x", "sort": "mtime"},
    {"directory": "x", "exclude": "*.csv"}, {"directory": "x", "pattern": "../*.csv"},
    {"glob": "**/*.csv"}, {"directory": "x", "pattern": "**/*.csv"},
    {"glob": "*.csv", "pattern": "*.txt"}, {"path": "x", "allow_empty": True},
    {"directory": "x", "exclude": ["../*.csv"]},
    {"directory": "x", "alias_template": "{stem.upper}"},
    {"directory": "x", "sort": []}, {"directory": "\x00"},
    {"directory": "x", "sort": {}},
    {"directory": "x", "pattern": "\x00"}, {"glob": "\x00"},
])
def test_invalid_source_options_have_domain_errors(tmp_path, source):
    assert validate_import_source(source)
    with pytest.raises(CurveMoleError, match="Invalid workflow import source"):
        resolve_import_paths(source, tmp_path)


def test_templates_have_all_documented_fields_and_one_based_indices(tmp_path):
    path = _file(tmp_path, "data/day1/scan2.csv")
    assert format_import_name(
        "{parent}/{stem}:{curve_name}:{file_index}:{curve_index}:{filename}:{relative_path}:{relative_stem}",
        path, tmp_path, file_index=2, curve_index=1, curve_name="signal",
    ) == "day1/scan2:signal:2:1:scan2.csv:data/day1/scan2.csv:data/day1/scan2"
    assert format_import_name("{{literal}}_{stem}", path, tmp_path,
                              file_index=1, curve_index=1, curve_name="y") == "{literal}_scan2"


@pytest.mark.parametrize("template", ["", " ", None, "{", "{}", "{unknown}",
                                        "{stem.upper}", "{stem[0]}", "{file_index:03d}", "{stem!r}"])
def test_unsupported_template_syntax_is_rejected(template, tmp_path):
    assert validate_name_template(template)
    with pytest.raises(CurveMoleError, match="Invalid workflow name template"):
        format_import_name(template, tmp_path / "x.csv", tmp_path,
                           file_index=1, curve_index=1, curve_name="y")


@pytest.mark.parametrize("index", [0, -1, True, 1.5])
def test_template_indices_must_be_one_based(index, tmp_path):
    with pytest.raises(CurveMoleError, match="positive integers"):
        format_import_name("{file_index}_{curve_index}", tmp_path / "x.csv", tmp_path,
                           file_index=index, curve_index=1, curve_name="y")


@pytest.mark.parametrize("source", [
    {"glob": "data/link/sub/*.csv"}, {"directory": "data/link/sub"},
    {"glob": "data/link/*.csv"}, {"directory": "data/link"},
])
def test_batch_static_prefix_cannot_follow_directory_symlink(tmp_path, source):
    actual = _file(tmp_path, "actual/sub/scan.csv")
    (tmp_path / "data").mkdir()
    try:
        (tmp_path / "data/link").symlink_to(actual.parent.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(CurveMoleError, match="symbolic link"):
        resolve_import_paths(source, tmp_path)
