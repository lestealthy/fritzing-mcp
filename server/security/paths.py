"""Path safety: every path the AI touches is canonicalized and root-checked."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import config
from ..errors import McpError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-\.]+")


def sanitize_name(name: str, max_len: int = 64) -> str:
    """Sanitize a user-supplied project/part name for use as a file component."""
    if re.search(r"[;|&$`<>\"'\n\r\\/]", name):
        raise McpError("POLICY_DENIED", "Name contains forbidden characters.")
    cleaned = _SAFE_NAME.sub("_", name.strip())
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise McpError("POLICY_DENIED", "Name is empty after sanitization.")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    # Reject shell-dangerous leftovers and Windows reserved names.
    if cleaned.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}:
        raise McpError("POLICY_DENIED", "Name is a reserved Windows device name.")
    return cleaned


def is_within(path: Path, root: Path) -> bool:
    try:
        path = Path(os.path.normcase(str(path)))
        root = Path(os.path.normcase(str(root)))
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except (ValueError, OSError):
        return False


def resolve_inside_root(requested: str | os.PathLike, root: Path | None = None) -> Path:
    """Resolve a path and guarantee it stays inside the controlled root."""
    root = (root or config.projects_dir).resolve()
    raw = str(requested)
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise McpError("PATH_NOT_ALLOWED", "UNC paths are not allowed.")
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate)
        resolved = candidate.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise McpError("PATH_NOT_ALLOWED", f"Invalid path: {exc}")
    # Reject obvious traversal attempts outright as well.
    if ".." in Path(raw).parts and not is_within(resolved, root):
        raise McpError("PATH_NOT_ALLOWED", "Path escapes the controlled root.")
    if not is_within(resolved, root):
        raise McpError(
            "PATH_NOT_ALLOWED",
            f"Path is outside the controlled root ({root}).",
            suggestion="Use only project IDs and server-managed paths.",
        )
    return resolved


def check_extension_allowed(path: Path) -> None:
    from ..policy import ALLOWED_ARTIFACT_EXTENSIONS

    if path.suffix.lower() not in ALLOWED_ARTIFACT_EXTENSIONS:
        raise McpError("POLICY_DENIED", f"File extension '{path.suffix}' is not allowed.")
