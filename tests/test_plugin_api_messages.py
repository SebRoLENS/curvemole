import pytest

from curvemole.core.errors import CurveMoleError
from curvemole.core.extensions import PluginAPI


class _Manager:
    registry = None
    source_fingerprints = {}

    def symbol(self, owner):
        return "◆"

    def plugin_name(self, owner):
        return owner


def test_unknown_extension_kind_names_the_problem_and_the_valid_kinds():
    api = PluginAPI(_Manager(), "example")
    with pytest.raises(CurveMoleError, match="Unknown extension kind 'exporter'. Did you mean 'exporters'"):
        api.add("exporter", "csv", "CSV", lambda: None)
    with pytest.raises(CurveMoleError, match="non-empty string"):
        api.add("exporters", " ", "CSV", lambda: None)
    with pytest.raises(CurveMoleError, match="callable"):
        api.add("exporters", "csv", "CSV", None)
