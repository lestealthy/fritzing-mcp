"""Policy engine: enforces filesystem, tool-surface, trust, and lifecycle policy."""

from __future__ import annotations

import json
from pathlib import Path

from .config import config
from .errors import McpError

DEFAULT_POLICY = {
    "filesystem": {
        "controlled_root_only": True,
        "allow_arbitrary_paths": False,
        "allow_unc": False,
    },
    "shell": {"enabled": False},
    "custom_parts": {"enabled": False},
    "community_parts": {"enabled": False},
    "overwrite": {"enabled": False},
    "network": {"enabled": False},
    "parts_search": {"max_limit": 50},
    "save": {"require_valid_validation": True, "allow_warnings": True},
    "zip": {"max_files": 200, "max_total_bytes": 200_000_000, "max_member_bytes": 50_000_000},
}

_policy_cache: dict | None = None


def load_policy() -> dict:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    path = config.policy_file
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merged = {**DEFAULT_POLICY}
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            _policy_cache = merged
            return _policy_cache
        except Exception:
            pass
    _policy_cache = DEFAULT_POLICY
    return _policy_cache


def reload_policy() -> dict:
    global _policy_cache
    _policy_cache = None
    return load_policy()


def custom_parts_enabled() -> bool:
    return bool(load_policy().get("custom_parts", {}).get("enabled", False))


def community_parts_enabled() -> bool:
    return bool(load_policy().get("community_parts", {}).get("enabled", False))


def overwrite_enabled() -> bool:
    return bool(load_policy().get("overwrite", {}).get("enabled", False))


def max_search_limit() -> int:
    return int(load_policy().get("parts_search", {}).get("max_limit", 50))


def zip_limits() -> dict:
    return load_policy().get("zip", DEFAULT_POLICY["zip"])


# --- project lifecycle state machine -------------------------------------

_TRANSITIONS = {
    "CREATED": {"DISCOVERED", "CANCELLED"},
    "DISCOVERED": {"PLACED", "CANCELLED", "DISCOVERED"},
    "PLACED": {"WIRED", "PLACED", "CANCELLED", "VALIDATED"},
    "WIRED": {"VALIDATED", "WIRED", "CANCELLED"},
    "VALIDATED": {"RENDERED", "WIRED", "PLACED", "CANCELLED"},
    "RENDERED": {"REVIEWED", "VALIDATED", "WIRED", "CANCELLED"},
    "REVIEWED": {"READY_TO_SAVE", "RENDERED", "WIRED", "CANCELLED"},
    "READY_TO_SAVE": {"SAVED", "WIRED", "CANCELLED"},
    "SAVED": set(),
    "CANCELLED": set(),
}


def can_transition(state: str, target: str) -> bool:
    return target in _TRANSITIONS.get(state, set())


def transition(manifest: dict, target: str) -> None:
    current = manifest.get("state", "CREATED")
    if current == target:
        return
    if not can_transition(current, target):
        raise McpError(
            "PROJECT_STATE_INVALID",
            f"Cannot move project from {current} to {target}.",
            suggestion="Follow the tutorial workflow: discover -> place -> wire -> validate -> render -> review -> save.",
        )
    manifest["state"] = target


TRUST_LEVELS = ["OFFICIAL", "VERIFIED", "COMMUNITY", "GENERATED", "UNKNOWN", "REJECTED"]


def part_allowed_for_placement(trust: str) -> bool:
    if trust in ("OFFICIAL", "VERIFIED"):
        return True
    if trust == "COMMUNITY":
        return community_parts_enabled()
    if trust == "GENERATED":
        return custom_parts_enabled()
    return False


ALLOWED_ARTIFACT_EXTENSIONS = {".fzz", ".fz", ".fzp", ".fzpz", ".svg", ".png", ".json", ".md", ".log"}


def invalidate_validation(manifest: dict, reason: str = "mutation") -> None:
    """Centrally invalidate prior validation after any structural mutation."""
    manifest["dirty"] = True
    manifest["validation"] = {"status": None, "stale": True, "stale_reason": reason}
    if manifest.get("state") in ("VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE", "SAVED"):
        # revert to the appropriate editing state
        if manifest.get("connections"):
            manifest["state"] = "WIRED"
        elif manifest.get("parts"):
            manifest["state"] = "PLACED"
        else:
            manifest["state"] = "CREATED"


def save_policy() -> dict:
    return load_policy().get("save", DEFAULT_POLICY["save"])
