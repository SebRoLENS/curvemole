"""Only the explicitly authorized old beta becomes a draft, after replacement."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD = 'v1.1.1-beta.86'
NEW = 'v1.2.0-beta.88'
OLD_SHA = 'f'*40
NEW_SHA = 'a'*40


@pytest.fixture
def withdrawal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('withdraw_beta', ROOT/'.github/scripts/withdraw_beta.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path/'.github').mkdir()
    (tmp_path/'.github/beta-withdrawals.json').write_text(json.dumps([
        {'tag': OLD, 'source': OLD_SHA, 'replacement_target': '1.2.0'}]))
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/testing')
    monkeypatch.setenv('GITHUB_SHA', NEW_SHA)
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/example')
    return module, tmp_path


def release(tag, source, **changes):
    return dict(id=101 if tag == OLD else 202, tag_name=tag, target_commitish=source,
                prerelease=True, draft=False, **changes)


def test_withdrawal_is_reversible_idempotent_and_only_edits_the_old_beta(withdrawal, monkeypatch):
    module, root = withdrawal
    old = release(OLD, OLD_SHA)
    calls = []
    monkeypatch.setattr(module, 'read_json', lambda repo, path, **kw:
                        release(NEW, NEW_SHA) if path.endswith(NEW) else old.copy())
    def run(command, **kwargs):
        assert command == ['gh', 'release', 'edit', OLD, '--repo', 'owner/example', '--draft']
        assert kwargs == {'check': True}
        calls.append(command)
        old['draft'] = True
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert module.withdraw('1.2.0b88', root) == [OLD]
    assert module.withdraw('1.2.0b88', root) == []
    assert len(calls) == 1


@pytest.mark.parametrize('change', [{'draft': True}, {'prerelease': False}, {'target_commitish': 'b'*40}])
def test_replacement_must_already_be_published_and_have_the_exact_source(withdrawal, monkeypatch, change):
    module, root = withdrawal
    replacement = release(NEW, NEW_SHA)
    replacement.update(change)
    monkeypatch.setattr(module, 'read_json', lambda *a, **kw: replacement)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('Unsafe write'))
    with pytest.raises(ValueError, match='identity'):
        module.withdraw('1.2.0b88', root)


@pytest.mark.parametrize('change', [{'prerelease': False}, {'target_commitish': 'b'*40}, {'tag_name': 'v1.1.0'}])
def test_old_release_changes_or_stable_status_prevent_withdrawal(withdrawal, monkeypatch, change):
    module, root = withdrawal
    old = release(OLD, OLD_SHA)
    old.update(change)
    monkeypatch.setattr(module, 'read_json', lambda repo, path, **kw:
                        release(NEW, NEW_SHA) if path.endswith(NEW) else old)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('Unsafe write'))
    with pytest.raises(ValueError, match='identity'):
        module.withdraw('1.2.0b88', root)


def test_other_targets_and_missing_old_releases_do_not_write(withdrawal, monkeypatch):
    module, root = withdrawal
    monkeypatch.setattr(module, 'read_json', lambda repo, path, **kw:
                        release(NEW, NEW_SHA) if path.endswith(NEW) else None)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('Unnecessary write'))
    assert module.withdraw('1.2.0b88', root) == []
    assert module.withdraw('1.3.0b89', root) == []


@pytest.mark.parametrize('ref,version', [('refs/heads/main','1.2.0b88'),
                                       ('refs/heads/testing','1.2.0')])
def test_only_testing_beta_publication_can_withdraw(withdrawal, monkeypatch, ref, version):
    module, root = withdrawal
    monkeypatch.setenv('GITHUB_REF', ref)
    with pytest.raises(ValueError, match='testing beta'):
        module.withdraw(version, root)


def test_draft_confirmation_uses_immutable_id_when_tag_lookup_disappears(withdrawal, monkeypatch):
    module, root = withdrawal
    old = release(OLD, OLD_SHA)
    def read(repo, path, **kwargs):
        if path.endswith(NEW):
            return release(NEW, NEW_SHA)
        if path == 'releases/101':
            return old.copy()
        assert old['draft'] is False, 'A draft may no longer resolve through its tag URL'
        return old.copy()
    def edit(*args, **kwargs):
        old.update(draft=True, tag_name='untagged-123abc')
    monkeypatch.setattr(module, 'read_json', read)
    monkeypatch.setattr(module.subprocess, 'run', edit)
    assert module.withdraw('1.2.0b88', root) == [OLD]


@pytest.mark.parametrize('change', [{'id': 999}, {'target_commitish': 'b'*40},
                                  {'draft': False}, {'prerelease': False}])
def test_draft_confirmation_rejects_changed_release_identity(withdrawal, monkeypatch, change):
    module, root = withdrawal
    def read(repo, path, **kwargs):
        if path.endswith(NEW):
            return release(NEW, NEW_SHA)
        old = release(OLD, OLD_SHA)
        if path == 'releases/101':
            old.update(draft=True)
            old.update(change)
        return old
    monkeypatch.setattr(module, 'read_json', read)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match='could not be verified'):
        module.withdraw('1.2.0b88', root)
