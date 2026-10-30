"""Opt-in project handoff over an eventually synchronized shared folder.

This protocol does not require Syncthing, Dropbox, or another vendor's API.
It deliberately does not infer safety from a stale remote heartbeat: offline
copies and synchronization partitions cannot provide distributed mutual exclusion.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
import uuid
from pathlib import Path

from curvemole.core.serialization import _atomic_json

REQUEST_TTL_SECONDS = 24 * 60 * 60


def file_digest(path: str | Path) -> str | None:
    """Hash project bytes, not modification times (which may be preserved by sync)."""
    source = Path(path)
    try:
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def request_control(project_path: str | Path, owner_session: str) -> dict:
    """Create a unique request without overwriting another requester's files."""
    path = Path(project_path)
    request = {
        "request_id": uuid.uuid4().hex,
        "owner_session": owner_session,
        "requester_session": uuid.uuid4().hex,
        "requester_host": socket.gethostname(),
        "created_at": time.time(),
    }
    _atomic_json(request_path(path, request["request_id"]), request)
    return request


def request_path(project_path: str | Path, request_id: str) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.name}.lock.request-{request_id}.json")


def reply_path(project_path: str | Path, request_id: str) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.name}.lock.reply-{request_id}.json")


def pending_requests(project_path: str | Path, owner_session: str) -> list[dict]:
    path = Path(project_path)
    now = time.time()
    requests = []
    for file in path.parent.glob(f"{path.name}.lock.request-*.json"):
        request = _read_json(file)
        if request is None or request.get("owner_session") != owner_session:
            continue
        requested = request.get("created_at")
        if not isinstance(requested, (int, float)) or abs(now - requested) > REQUEST_TTL_SECONDS:
            continue
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id or file != request_path(path, request_id):
            continue
        if reply_path(path, request_id).exists():
            continue
        requests.append(request)
    requests.sort(key=lambda item: (item["created_at"], item["request_id"]))
    return requests


def reply_to_request(
    project_path: str | Path,
    request: dict,
    *,
    accepted: bool,
    digest: str | None = None,
    reason: str = "",
) -> None:
    response = {
        "request_id": request["request_id"],
        "owner_session": request["owner_session"],
        "requester_session": request["requester_session"],
        "accepted": accepted,
        "project_sha256": digest if accepted else None,
        "reason": reason if not accepted else "",
    }
    _atomic_json(reply_path(project_path, request["request_id"]), response)


def read_reply(project_path: str | Path, request: dict) -> dict | None:
    reply = _read_json(reply_path(project_path, request["request_id"]))
    if reply is None:
        return None
    if (
        reply.get("request_id") != request["request_id"]
        or reply.get("owner_session") != request["owner_session"]
        or reply.get("requester_session") != request["requester_session"]
        or not isinstance(reply.get("accepted"), bool)
    ):
        return None
    if reply["accepted"] and not isinstance(reply.get("project_sha256"), str):
        return None
    return reply
