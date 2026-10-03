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


_COUNTER = None


def _next_id() -> str:
    import contextlib
    import time

    lock_path = config.projects_dir / ".alloc.lock"
    config.projects_dir.mkdir(parents=True, exist_ok=True)
    # Windows-compatible atomic lock via msvcrt-style open with exclusive create loop
    import msvcrt

    fd = open(lock_path, "a+b")
    try:
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            # another process holds the lock; spin briefly
            for _ in range(50):
                time.sleep(0.1)
                try:
                    msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    continue
        year = _year()
        best = 0
        for root in (config.projects_active, config.projects_completed, config.projects_rejected):
            for d in root.glob(f"WTL-FZ-{year}-*"):
                m = re.match(rf"WTL-FZ-{year}-(\d+)", d.name)
                if m:
                    best = max(best, int(m.group(1)))
        return f"WTL-FZ-{year}-{best + 1:04d}"
    finally:
        fd.close()


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
    _checkpoint(pdir, manifest, txid)
    return pdir, manifest, txid


def _checkpoint(pdir: Path, manifest: dict, txid: str | None = None) -> None:
    import time

    ck = pdir / "checkpoints"
    ck.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    name = f"project_{stamp}_tx_{txid}.json" if txid else f"project_{stamp}.json"
    try:
        shutil.copy2(pdir / "project.json", ck / name)
        if (pdir / "circuit.fzz").exists():
            shutil.copy2(pdir / "circuit.fzz", ck / name.replace("project_", "circuit_").replace(".json", ".fzz"))
    except OSError:
        pass


def rollback(pdir: Path, manifest: dict, txid: str | None = None) -> None:
    """Restore the latest checkpoint associated with a transaction (or newest when omitted)."""
    if txid:
        candidates = sorted((pdir / "checkpoints").glob(f"project_*_tx_{txid}.json"))
        if not candidates:
            candidates = sorted((pdir / "checkpoints").glob("project_*.json"))
        ck = candidates
    else:
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
    if not isinstance(validation, dict):
        validation = {}
    status = validation.get("status")
    if validation.get("stale"):
        raise McpError("SAVE_DENIED", f"VALIDATION_STALE: project changed ({validation.get('stale_reason')}).",
                       suggestion="Run fritzing_validate_project again before saving.")
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
        from ..policy import save_policy

        sp = save_policy()
        if status == "PASS_WITH_WARNINGS" and not sp.get("allow_warnings", False):
            raise McpError("SAVE_DENIED", "Warnings present and policy forbids saving with warnings.",
                           suggestion=f"Fix warnings or enable policy 'save.allow_warnings'.")
        if dest == "completed":
            dest_root = config.projects_completed
        elif dest == "active":
            dest_root = config.projects_active
        else:
            raise McpError("POLICY_DENIED", "dest must be 'completed' or 'active'.")
        status_out = "verified" if status == "PASS" else "verified_with_warnings"

    # package .fzz
    if status_out != "rejected" and manifest.get("state") not in (
        "VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE",
    ):
        raise McpError(
            "PROJECT_STATE_INVALID",
            f"Cannot save a project in state {manifest.get('state')}.",
            suggestion="Validate (and render/review) first, then save.",
        )
    fzz = sketch.pack_fzz(pdir, manifest)
    if manifest.get("state") not in ("SAVED",):
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
