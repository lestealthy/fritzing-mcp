"""Validation pipeline: structural -> parts -> connectors -> wiring -> electrical -> render."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..config import config
from ..errors import McpError
from .parts import get_connectors, get_part

RAIL_PATTERNS = [
    (re.compile(r"^\s*\+?5v\b", re.I), "5V"),
    (re.compile(r"^\s*\+?(3v3|3\.3v|3,3v|3v3)", re.I), "3V3"),
    (re.compile(r"^\s*gnd\b", re.I), "GND"),
    (re.compile(r"^\s*vcc\b", re.I), "VCC"),
    (re.compile(r"^\s*vin\b", re.I), "VIN"),
]


def _classify_rail(name: str) -> str | None:
    if not name:
        return None
    for pat, rail in RAIL_PATTERNS:
        if pat.search(name):
            return rail
    return None


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def electrical_check(manifest: dict) -> list[dict]:
    """Return structured diagnostics. ERROR/WARNING/NEEDS_HUMAN_REVIEW."""
    diagnostics: list[dict] = []

    uf = _UnionFind()
    node_rails: dict[str, set[str]] = {}
    connector_name: dict[str, str] = {}

    # map (instance_id, connector_id) nodes; union wires
    for c in manifest["connections"]:
        a = f"{c['from_instance']}:{c['from_connector']}"
        b = f"{c['to_instance']}:{c['to_connector']}"
        uf.union(a, b)

    # gather rail classification per node
    for p in manifest["parts"]:
        try:
            connectors = get_connectors(p["part_id"])
        except McpError:
            continue
        by_id = {c["connector_id"]: c for c in connectors}
        for c in connectors:
            rail = _classify_rail(c["name"] or "")
            node = f"{p['instance_id']}:{c['connector_id']}"
            connector_name[node] = c["name"] or ""
            if rail:
                node_rails.setdefault(node, set()).add(rail)

    # group nodes into nets
    nets: dict[str, list[str]] = {}
    for node in set(connector_name) | {f"{c['from_instance']}:{c['from_connector']}" for c in manifest["connections"]} | {f"{c['to_instance']}:{c['to_connector']}" for c in manifest["connections"]}:
        root = uf.find(node)
        nets.setdefault(root, []).append(node)

    has_gnd = False
    has_power = False
    for root, nodes in nets.items():
        rails: set[str] = set()
        for n in nodes:
            rails.update(node_rails.get(n, ()))
        if "GND" in rails:
            has_gnd = True
        if rails & {"5V", "3V3", "VCC", "VIN"}:
            has_power = True
        rail_set = rails - {"VCC", "VIN"}
        if "5V" in rail_set and "3V3" in rail_set:
            diagnostics.append({
                "severity": "ERROR",
                "code": "POWER_CONFLICT",
                "message": "5V rail connected to 3.3V rail.",
                "net_nodes": sorted(nodes),
            })
        if "GND" in rail_set and rail_set & {"5V", "3V3"}:
            diagnostics.append({
                "severity": "ERROR",
                "code": "POWER_SHORT",
                "message": "Power rail connected directly to GND.",
                "net_nodes": sorted(nodes),
            })

    # missing power/ground on module-like parts
    for p in manifest["parts"]:
        try:
            connectors = get_connectors(p["part_id"])
        except McpError:
            continue
        names = {(c["name"] or "").lower() for c in connectors}
        looks_powered = any(n in names for n in ("vcc", "5v", "vin", "3v3", "3.3v")) and "gnd" in names
        if looks_powered:
            connected = {f"{p['instance_id']}:{c['from_connector']}" for c in manifest["connections"] if c["from_instance"] == p["instance_id"]}
            connected |= {f"{p['instance_id']}:{c['to_connector']}" for c in manifest["connections"] if c["to_instance"] == p["instance_id"]}
            pwr_connected = any(
                any(r in node_rails.get(n, ()) for r in ("5V", "3V3", "VCC", "VIN")) or
                _classify_rail(connector_name.get(n, "")) in ("5V", "3V3", "VCC", "VIN")
                for n in connected)
            gnd_connected = any("GND" in node_rails.get(n, ()) or connector_name.get(n, "").lower().startswith("gnd") for n in connected)
            if connectors and not pwr_connected:
                diagnostics.append({"severity": "WARNING", "code": "MISSING_POWER",
                                    "message": f"Part '{p['title']}' appears unpowered.", "part": p["instance_id"]})
            if connectors and not gnd_connected:
                diagnostics.append({"severity": "WARNING", "code": "MISSING_GROUND",
                                    "message": f"Part '{p['title']}' has no GND connection.", "part": p["instance_id"]})

    # output-output conflicts (heuristic on pin names)
    for root, nodes in nets.items():
        outputs = []
        for n in nodes:
            for c in manifest["connections"]:
                pass
        names = [connector_name.get(n, "") for n in nodes]
        digital_out = [n for n in names if re.match(r"^(D?\d+|GPIO|IO)\d*$", (n or "").strip(), re.I)]
        if len(digital_out) >= 2:
            diagnostics.append({
                "severity": "NEEDS_HUMAN_REVIEW",
                "code": "POSSIBLE_OUTPUT_OUTPUT",
                "message": "Two digital-looking signals are wired together; verify neither is a driven output pair.",
                "net_nodes": sorted(nodes),
            })

    # floating / dangling: connector with no connection on a placed part
    for p in manifest["parts"]:
        connected_ids = set()
        for c in manifest["connections"]:
            if c["from_instance"] == p["instance_id"]:
                connected_ids.add(c["from_connector"])
            if c["to_instance"] == p["instance_id"]:
                connected_ids.add(c["to_connector"])
        try:
            connectors = get_connectors(p["part_id"])
        except McpError:
            continue
        floating = [c["connector_id"] for c in connectors if c["connector_id"] not in connected_ids]
        if floating and len(floating) == len(connectors):
            diagnostics.append({"severity": "WARNING", "code": "ORPHAN_PART",
                                "message": f"Part '{p['title']}' has no connections.", "part": p["instance_id"]})
        # NOTE: unconnected GPIO pins are normal; we intentionally do not fail on them.

    return diagnostics


def validate_manifest_structure(manifest: dict) -> list[dict]:
    errs = []
    if not manifest.get("project_id"):
        errs.append({"severity": "ERROR", "code": "SCHEMA", "message": "missing project_id"})
    seen_ids = set()
    for p in manifest.get("parts", []):
        if p["instance_id"] in seen_ids:
            errs.append({"severity": "ERROR", "code": "DUPLICATE_INSTANCE", "message": p["instance_id"]})
        seen_ids.add(p["instance_id"])
    seen_pairs = set()
    for c in manifest.get("connections", []):
        key = tuple(sorted([(c["from_instance"], c["from_connector"]), (c["to_instance"], c["to_connector"])]))
        if key in seen_pairs:
            errs.append({"severity": "ERROR", "code": "DUPLICATE_CONNECTION", "message": str(key)})
        seen_pairs.add(key)
    return errs


def validate_fz_xml(fzz_path: Path) -> list[dict]:
    errs = []
    import zipfile

    try:
        with zipfile.ZipFile(fzz_path) as z:
            fz_names = [n for n in z.namelist() if n.endswith(".fz")]
            if not fz_names:
                errs.append({"severity": "ERROR", "code": "FZ_MISSING", "message": "No .fz inside .fzz"})
                return errs
            for name in fz_names:
                try:
                    ET.fromstring(z.read(name))
                except ET.ParseError as exc:
                    errs.append({"severity": "ERROR", "code": "FZ_XML", "message": str(exc)})
    except zipfile.BadZipFile:
        errs.append({"severity": "ERROR", "code": "FZZ_BADZIP", "message": "Bad zip"})
    return errs


def run_validation(project_dir: Path, manifest: dict) -> dict:
    stages: dict[str, list[dict]] = {}
    stages["schema"] = validate_manifest_structure(manifest)
    stages["electrical"] = electrical_check(manifest)
    stages["structure"] = []
    fzz = manifest.get("artifacts", {}).get("fzz")
    if fzz and Path(fzz).is_file():
        stages["structure"] = validate_fz_xml(Path(fzz))
    all_diags = [d for diags in stages.values() for d in diags]
    errors = [d for d in all_diags if d["severity"] == "ERROR"]
    warnings = [d for d in all_diags if d["severity"] == "WARNING"]
    review = [d for d in all_diags if d["severity"] == "NEEDS_HUMAN_REVIEW"]
    if errors:
        status = "FAIL"
    elif warnings or review:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    result = {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "needs_human_review": review,
        "stages": {k: len(v) for k, v in stages.items()},
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    manifest["validation"] = result
    try:
        (project_dir / "validation.json").write_text(__import__("json").dumps(result, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result
