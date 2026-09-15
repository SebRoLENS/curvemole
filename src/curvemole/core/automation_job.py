"""Isolated desktop workflow runner, also used by frozen builds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from curvemole.core.errors import CurveMoleError
from curvemole.core.plugins import PluginManager
from curvemole.core.workflow import load_workflow, run_workflow, validate_workflow


def prepare_job(path: str | Path, manager: PluginManager) -> dict:
    source = Path(path).resolve()
    workflow = load_workflow(source)
    errors = validate_workflow(workflow)
    if errors:
        raise CurveMoleError("Invalid automation: " + "; ".join(errors))
    approved = {}
    for reference in workflow.get("plugins", []):
        manifest = (source.parent / reference).resolve()
        candidate = next((c for c in manager.discover_local(manifest.parent)
                          if Path(c.reference).resolve() == manifest), None)
        if candidate is None:
            raise CurveMoleError(f"Plugin manifest not found: {manifest}")
        identifier = candidate.metadata.identifier
        fingerprint = manager._fingerprint(candidate)
        record = manager.installed.get(identifier, {})
        if not record.get("enabled") or record.get("fingerprint") != fingerprint:
            raise CurveMoleError(f"Review and enable {identifier} in File > Plugin Manager first.")
        approved[identifier] = {"fingerprint": fingerprint, "enabled": True}
    return {"workflow": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "approved": approved}


def run_job(request_path: str | Path) -> int:
    request_path = Path(request_path)
    destination = request_path.with_suffix(".result.json")
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        source = Path(request["workflow"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != request["sha256"]:
            raise CurveMoleError("Automation changed during launch; run it again.")
        manager = PluginManager()
        manager.installed = request["approved"]
        prepare_job(source, manager)  # Check plugin source again in the worker process.
        outcome = run_workflow(source, trust_plugins=set(request["approved"]))
        result = {"ok": True, "outputs": [str(path) for path in outcome.outputs],
                  "spectra": len(outcome.project.curves),
                  "fit_success": outcome.result.success if outcome.result else None}
        code = 0
    except Exception as exc:
        result, code = {"ok": False, "error": str(exc)}, 1
    destination.write_text(json.dumps(result), encoding="utf-8")
    return code
