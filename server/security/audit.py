"""Append-only audit log per project; every mutation is recorded."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SENSITIVE_KEYS = {"password", "token", "secret", "api_key"}


def _scrub(value):
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def new_transaction_id() -> str:
    return uuid.uuid4().hex[:16]


def log_event(project_dir: Path | None, tool: str, project: str, parameters: dict,
              result: str, actor: str = "mcp-agent", transaction_id: str | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": new_request_id(),
        "transaction_id": transaction_id or new_transaction_id(),
        "tool": tool,
        "project": project,
        "actor": actor,
        "parameters": _scrub(parameters or {}),
        "result": result,
    }
    line = json.dumps(entry, ensure_ascii=False)
    if project_dir is not None:
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            with open(project_dir / "audit.jsonl", "a", encoding="utf-8", newline="") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
    # Server-level audit too.
    try:
        from ..config import config

        log_dir = config.projects_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "server_audit.jsonl", "a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
