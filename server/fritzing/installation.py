"""Environment detection."""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from ..config import config


def detect_fritzing() -> dict:
    exe = config.fritzing_exe
    found = exe.is_file()
    version = None
    if found:
        m = re.search(r"(\d+\.\d+\.\d+[a-z0-9\.\-]*)", exe.parent.joinpath("README.md").read_text(errors="ignore")[:4000]) if exe.parent.joinpath("README.md").is_file() else None
        try:
            from .parts import fritzing_version_from_db
            version = fritzing_version_from_db()
        except Exception:
            pass
        if not version:
            version = "unknown"
    return {
        "installed": found,
        "exe": str(exe),
        "version": version,
        "install_dir": str(config.fritzing_dir),
    }


def detect_parts() -> dict:
    ok = config.parts_db.is_file()
    count = None
    if ok:
        try:
            conn = sqlite3.connect(str(config.parts_db))
            count = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
            conn.close()
        except Exception:
            ok = False
    return {
        "parts_db": str(config.parts_db),
        "available": ok,
        "part_count": count,
        "fzp_checker_available": config.fzp_checker.is_file(),
        "user_parts_dir": str(config.user_parts_dir),
        "user_parts_exists": config.user_parts_dir.is_dir(),
    }


def detect_python() -> dict:
    return {"version": sys.version.split()[0], "executable": sys.executable}


def detect_mcp() -> dict:
    try:
        import mcp  # noqa: F401

        return {"installed": True}
    except Exception:
        return {"installed": False}


def detect_writable() -> dict:
    out = {}
    for name, p in [("projects", config.projects_dir), ("active", config.projects_active),
                    ("parts_cache", config.parts_cache_dir)]:
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            out[name] = True
        except OSError:
            out[name] = False
    return out


def detect_renderer() -> dict:
    exe_ok = config.fritzing_exe.is_file()
    return {"available": exe_ok, "mechanism": "Fritzing -svg export" if exe_ok else None}


def run_doctor() -> dict:
    checks = {
        "fritzing": detect_fritzing(),
        "parts": detect_parts(),
        "python": detect_python(),
        "mcp": detect_mcp(),
        "writable": detect_writable(),
        "renderer": detect_renderer(),
    }
    lines = []
    def add(ok: bool, label: str):
        lines.append(f"[{'OK' if ok else 'FAIL'}] {label}")

    add(checks["fritzing"]["installed"], "Fritzing detected")
    add(bool(checks["fritzing"]["version"]), f"Version detected ({checks['fritzing']['version']})")
    add(checks["parts"]["available"], f"Parts repository detected ({checks['parts']['part_count']} parts)")
    add(checks["parts"]["user_parts_exists"], "User parts directory detected")
    add(all(checks["writable"].values()), "Project storage writable")
    add(checks["renderer"]["available"], "Renderer available")
    add(checks["parts"]["fzp_checker_available"], "FZP checker available")
    add(checks["mcp"]["installed"], "MCP server dependencies installed")
    return {"checks": checks, "report": "\n".join(lines)}
