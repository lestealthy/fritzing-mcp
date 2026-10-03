"""FZZ portability diagnostics: no claims about self-containment unless proven."""

from __future__ import annotations

import re
import sqlite3
import zipfile
from pathlib import Path

from ..config import config
from ..errors import McpError

_ABS_PATTERNS = [
    re.compile(r"^[A-Za-z]:[\\/]"),
    re.compile(r"^\\\\"),
    re.compile(r"^/"),
]


def check_project_portability(project_dir: Path, manifest: dict) -> dict:
    fzz = manifest.get("artifacts", {}).get("fzz")
    result = {
        "portable": False,
        "native_fritzing_compatible": False,
        "external_parts_required": True,
        "missing_parts": [],
        "absolute_paths": [],
        "fixture_fzz_valid": False,
        "part_refs": [],
        "machine_specific_paths": [],
        "verdict": "unknown",
        "deps_lock": "",
    }
    if not fzz or not Path(fzz).is_file():
        return result

    try:
        with zipfile.ZipFile(fzz) as z:
            names = z.namelist()
            fz_names = [n for n in names if n.endswith(".fz")]
            if not fz_names:
                result["verdict"] = "no .fz"
                return result
            import xml.etree.ElementTree as ET

            try:
                ET.fromstring(z.read(fz_names[0]))
                result["fixture_fzz_valid"] = True
            except Exception:
                result["verdict"] = "invalid fz"
                return result
            text = z.read(fz_names[0]).decode("utf-8", errors="ignore")
    except zipfile.BadZipFile:
        result["verdict"] = "bad zip"
        return result

    module_refs = set(re.findall(r'moduleIdRef="([^"]+)"', text))
    module_refs.discard("WireModuleID")
    machine_specific = []
    absolute = []
    present_ids = set()
    if config.parts_db.is_file():
        try:
            conn = sqlite3.connect(str(config.parts_db))
            for r in conn.execute("SELECT moduleID FROM parts"):
                present_ids.add(r[0])
            conn.close()
        except Exception:
            pass
    missing = []
    for mid in module_refs:
        if mid.startswith("pcb-"):
            continue
        if mid not in present_ids:
            missing.append(mid)
    vm = re.findall(r'(C:\\|\\\\|/Users|/home|[A-Za-z]:[\\/])([^"<>\s]+)', text)
    absolute = [a + b for a, b in vm]
    machine_specific = [p for p in module_refs if re.search(r"[\\/]", p) or p.endswith(".fzp")]
    deps = []
    for p in manifest.get("parts", []):
        deps.append({"module_id": p["part_id"], "source": "fritzing-parts", "trust": p.get("trust", "UNKNOWN")})
    lock = {"deps": deps, "count": len(deps), "note": "Deterministic part dependency list; install matching fritzing-parts to re-resolve."}

    parts_lock = project_dir / "parts.lock.json"
    parts_lock.write_text(__import__("json").dumps(lock, indent=2), encoding="utf-8")

    result.update({
        "portable": not absolute and not machine_specific,
        "native_fritzing_compatible": result["fixture_fzz_valid"],
        "external_parts_required": True,
        "missing_parts": missing,
        "absolute_paths": absolute,
        "machine_specific_paths": machine_specific,
        "part_refs": sorted(module_refs),
        "deps_lock": str(parts_lock),
        "verdict": "deterministic-deps-lock generated" if not (missing or absolute or machine_specific) else "non-deterministic",
    })
    (project_dir / "portability.json").write_text(__import__("json").dumps(result, indent=2), encoding="utf-8")
    return result
