"""A stable publication includes stable-edition API contracts and matching manual."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'.github/scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_removes_beta_only_claims_and_synchronizes_every_contract(tmp_path):
    module = script('promote_documentation')
    for name in module.FILES:
        target = tmp_path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    module.promote(tmp_path, '1.2.0')
    for name in module.FILES:
        text = (tmp_path/name).read_text()
        assert '1.2.0 beta' not in text, name
        assert '; beta only' not in text, name
        assert 'Testing edition for CurveMole' not in text, name
        assert 'current testing edition' not in text, name
    api = (tmp_path/'docs/python-api.md').read_text()
    workflow = (tmp_path/'docs/workflows.md').read_text()
    manual = (tmp_path/'docs/manual.md').read_text()
    assert 'Stable API baseline: CurveMole 1.2.0.' in api
    assert 'Install the 1.2.0 wheel' in api
    assert 'In 1.1.0, validation checks only' in workflow  # Historic behavior is preserved.
    assert 'Stable edition for CurveMole 1.2.0.' in manual
    assert '/curvemole/v1.2.0/docs/ai-python-audit.md' in manual
    assert module.appendix(api, '## Appendix F. Python scripting reference') in manual
    assert module.appendix(workflow, '## Appendix G. YAML workflow reference') in manual
    assert api.split('\n', 1)[1].strip() in (tmp_path/'docs/ai-python-audit.md').read_text()
    assert workflow.split('\n', 1)[1].strip() in (tmp_path/'docs/ai-yaml-audit.md').read_text()
    snapshots = {name: (tmp_path/name).read_bytes() for name in module.FILES}
    module.promote(tmp_path, '1.2.0')
    assert snapshots == {name: (tmp_path/name).read_bytes() for name in module.FILES}


def test_prepared_archive_includes_every_promoted_document():
    promoted = script('promote_documentation')
    state = script('release_state')
    assert set(promoted.FILES) <= set(state.FILES)
