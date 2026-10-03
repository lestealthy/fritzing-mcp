"""Project store: creation, lookup, lifecycle moves, save policy."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..config import config
from ..errors import McpError
from ..policy import can_transition, overwrite_enabled, transition
from ..security.audit import log_event, new_transaction_id
from ..security.paths import sanitize_name
from ..fritzing import sketch

_PROJECT_ID = re.compile(r"^WTL-FZ-\d{4}-\d{4}$")


def _year() -> int:
    return datetime.now().year


def _next_id() -> str:
    year = _year()
    best = 0
    for root in (config.projects_active, config.projects_completed, config.projects_rejected):
        for d in root.glob(f"WTL-FZ-{year}-*"):
            m = re.match(rf"WTL-FZ-{year}-(\d+)", d.name)
            if m:
                best = max(best, int(m.group(1)))
    return f"WTL-FZ-{year}-{best + 1:04d}"


def find_project_dir(project_id: str) -> Path | None:
    if not _PROJECT_ID.match(project_id or ""):
        return None
    for root in (config.projects_active, config.projects_completed, config.projects_rejected):
        cand = root / project_id
        if cand.is_dir():
            return cand
    return None


def get_project_dir(project_id: str) -> Path:
    d = find_project_dir(project_id)
    if d is None:
        raise McpError("PROJECT_NOT_FOUND", f"Unknown project '{project_id}'.")
    return d


def create_project(name: str, description: str = "", template: str | None = None) -> dict:
    safe = sanitize_name(name)
    pid = _next_id()
    pdir = config.projects_active / pid
    pdir.mkdir(parents=True, exist_ok=False)
    manifest = sketch.new_manifest(pid, safe, description, template)
    sketch.save_manifest(pdir, manifest)
    log_event(pdir, "fritzing_create_project", pid, {"name": name, "description": description, "template": template}, "success")
    return {"project_id": pid, "name": safe, "path": str(pdir), "manifest": manifest}


def get_project(project_id: str) -> dict:
    pdir = get_project_dir(project_id)
    manifest = sketch.load_manifest(pdir)
    return {
        "project_id": manifest["project_id"],
        "name": manifest["name"],
        "description": manifest.get("description", ""),
        "state": manifest["state"],
        "path": str(pdir),
        "parts": manifest["parts"],
        "connections": manifest["connections"],
        "validation": manifest.get("validation", {}),
        "artifacts": manifest.get("artifacts", {}),
        "created": manifest.get("created"),
        "modified": manifest.get("modified"),
    }


def mutation(project_id: str, tool: str, params: dict):
    """Context manager-ish helper: returns (pdir, manifest, txid); caller must save + log."""
    pdir = get_project_dir(project_id)
    manifest = sketch.load_manifest(pdir)
    txid = new_transaction_id()
    _checkpoint(pdir, manifest)
    return pdir, manifest, txid


def _checkpoint(pdir: Path, manifest: dict) -> None:
    import time

    ck = pdir / "checkpoints"
    ck.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    try:
        shutil.copy2(pdir / "project.json", ck / f"project_{stamp}.json")
        if (pdir / "circuit.fzz").exists():
            shutil.copy2(pdir / "circuit.fzz", ck / f"circuit_{stamp}.fzz")
    except OSError:
        pass


def rollback(pdir: Path, manifest: dict) -> None:
    ck = sorted((pdir / "checkpoints").glob("project_*.json"))
    if ck:
        shutil.copy2(ck[-1], pdir / "project.json")
        import json as _json

        try:
            restored = _json.loads((pdir / "project.json").read_text(encoding="utf-8"))
            manifest.clear()
            manifest.update(restored)
        except Exception:
            pass


def finalize(pdir: Path, manifest: dict, txid: str, tool: str, params: dict, result: str = "success") -> None:
    sketch.save_manifest(pdir, manifest)
    log_event(pdir, tool, manifest["project_id"], params, result, transaction_id=txid)


def save_project(project_id: str, dest: str = "completed") -> dict:
    """Save/finalize a project. Enforces the golden validation rule."""
    pdir = get_project_dir(project_id)
    manifest = sketch.load_manifest(pdir)

    validation = manifest.get("validation", {})
    status = validation.get("status")
    if not status:
        raise McpError("SAVE_DENIED", "Project has never been validated.",
                       suggestion="Call fritzing_validate_project before saving.")
    if manifest.get("dirty"):
        raise McpError("SAVE_DENIED", "Project was modified after the last validation.",
                       suggestion="Run fritzing_validate_project again before saving.")
    if status == "FAIL":
        # save as rejected/draft, never verified
        dest_root = config.projects_rejected
        status_out = "rejected"
    else:
        warnings_ok = True
        if status == "PASS_WITH_WARNINGS" and not warnings_ok:
            raise McpError("SAVE_DENIED", "Warnings present and policy forbids saving with warnings.")
        if dest == "completed":
            dest_root = config.projects_completed
        elif dest == "active":
            dest_root = config.projects_active
        else:
            raise McpError("POLICY_DENIED", "dest must be 'completed' or 'active'.")
        status_out = "verified" if status == "PASS" else "verified_with_warnings"

    # package .fzz
    fzz = sketch.pack_fzz(pdir, manifest)
    manifest["validation"] = validation
    if status_out == "rejected":
        transition(manifest, "CANCELLED") if False else None
        manifest["state"] = "SAVED"
    else:
        if manifest["state"] not in ("SAVED", "READY_TO_SAVE", "REVIEWED", "VALIDATED", "RENDERED"):
            raise McpError("PROJECT_STATE_INVALID", f"Cannot save from state {manifest['state']}.")
        manifest["state"] = "SAVED"

    dest_dir = dest_root / manifest["project_id"]
    if dest_dir.exists():
        if overwrite_enabled():
            shutil.rmtree(dest_dir)
        else:
            raise McpError("POLICY_DENIED", "A project with this ID already exists at destination; overwrite disabled.")
    if pdir.resolve() != dest_dir.resolve():
        shutil.copytree(pdir, dest_dir)
        pdir_for_manifest = dest_dir
    else:
        pdir_for_manifest = pdir
    try:
        sketch.save_manifest(pdir_for_manifest, manifest)
    except OSError:
        pass
    log_event(pdir_for_manifest, "fritzing_save_project", manifest["project_id"], {"dest": dest}, f"success:{status_out}")
    return {
        "project_id": manifest["project_id"],
        "status": status_out,
        "validation_status": status,
        "path": str(dest_dir),
        "fzz": manifest["artifacts"].get("fzz"),
        "artifacts": manifest.get("artifacts", {}),
    }
