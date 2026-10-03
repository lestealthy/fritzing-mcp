"""Project manifest (authoritative) and .fzz/.fz generation with zip safety."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from ..config import config
from ..errors import McpError
from ..policy import zip_limits

MANIFEST_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_manifest(project_id: str, name: str, description: str, template: str | None = None) -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "project_id": project_id,
        "name": name,
        "description": description,
        "template": template,
        "created": now_iso(),
        "modified": now_iso(),
        "server_version": config.server_version,
        "policy_version": config.policy_version,
        "state": "CREATED",
        "steps": {"searched": False, "inspected_connectors": False},
        "parts": [],       # [{instance_id, part_id, title, x, y, rotation, view, trust}]
        "connections": [],  # [{connection_id, from_instance, from_connector, to_instance, to_connector}]
        "validation": {},
        "artifacts": {},
        "next_instance_seq": 1,
        "next_wire_seq": 1,
    }


def load_manifest(project_dir: Path) -> dict:
    path = project_dir / "project.json"
    if not path.is_file():
        raise McpError("PROJECT_NOT_FOUND", f"No project manifest in {project_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpError("VALIDATION_FAILED", f"Corrupt project manifest: {exc}")


def save_manifest(project_dir: Path, manifest: dict) -> None:
    manifest["modified"] = now_iso()
    path = project_dir / "project.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# --- model operations -------------------------------------------------------

VALID_ROTATIONS = (0, 90, 180, 270)
VALID_VIEWS = ("breadboard", "schematic", "pcb")


def add_instance(manifest: dict, part_id: str, title: str, view: str, x: float, y: float,
                 rotation: int, trust: str) -> dict:
    if view not in VALID_VIEWS:
        raise McpError("INVALID_CONNECTION", f"Unknown view '{view}'.")
    if rotation not in VALID_ROTATIONS:
        raise McpError("INVALID_CONNECTION", "rotation must be one of 0, 90, 180, 270.")
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        raise McpError("INVALID_CONNECTION", "x and y must be finite numbers.")
    import math

    if not (math.isfinite(x) and math.isfinite(y)):
        raise McpError("INVALID_CONNECTION", "x and y must be finite numbers.")
    seq = manifest["next_instance_seq"]
    manifest["next_instance_seq"] += 1
    inst = {
        "instance_id": f"inst_{seq:04d}",
        "part_id": part_id,
        "title": title,
        "x": x,
        "y": y,
        "rotation": rotation,
        "view": view,
        "trust": trust,
    }
    manifest["parts"].append(inst)
    return inst


def find_instance(manifest: dict, instance_id: str) -> dict:
    for p in manifest["parts"]:
        if p["instance_id"] == instance_id:
            return p
    raise McpError("INSTANCE_NOT_FOUND", f"No instance '{instance_id}'.")


def move_instance(manifest: dict, instance_id: str, x: float, y: float, rotation: int | None) -> dict:
    inst = find_instance(manifest, instance_id)
    import math

    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        raise McpError("INVALID_CONNECTION", "x and y must be finite numbers.")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise McpError("INVALID_CONNECTION", "x and y must be finite numbers.")
    inst["x"] = x
    inst["y"] = y
    if rotation is not None:
        if rotation not in VALID_ROTATIONS:
            raise McpError("INVALID_CONNECTION", "rotation must be one of 0, 90, 180, 270.")
        inst["rotation"] = rotation
    return inst


def add_connection(manifest: dict, from_instance: str, from_connector: str,
                   to_instance: str, to_connector: str) -> dict:
    find_instance(manifest, from_instance)
    find_instance(manifest, to_instance)
    from .parts import get_connectors, get_part

    src = {c["connector_id"] for c in get_connectors(_instance_part(manifest, from_instance))}
    dst = {c["connector_id"] for c in get_connectors(_instance_part(manifest, to_instance))}
    if not src or not dst:
        raise McpError("PART_NOT_FOUND", "A referenced part has no resolved connectors.")
    if src and from_connector not in src:
        raise McpError("CONNECTOR_NOT_FOUND", f"Connector '{from_connector}' not on source instance.",
                       suggestion="Call fritzing_get_part_connectors to list valid connector IDs.")
    if dst and to_connector not in dst:
        raise McpError("CONNECTOR_NOT_FOUND", f"Connector '{to_connector}' not on target instance.",
                       suggestion="Call fritzing_get_part_connectors to list valid connector IDs.")
    for c in manifest["connections"]:
        same = {c["from_instance"], c["from_connector"]} == {from_instance, from_connector} and \
               {c["to_instance"], c["to_connector"]} == {to_instance, to_connector}
        dup = (c["from_instance"] == from_instance and c["from_connector"] == from_connector and
               c["to_instance"] == to_instance and c["to_connector"] == to_connector) or \
              (c["from_instance"] == to_instance and c["from_connector"] == to_connector and
               c["to_instance"] == from_instance and c["to_connector"] == from_connector)
        if dup or same:
            raise McpError("DUPLICATE_CONNECTION", "Connection already exists.", recoverable=False)
    seq = manifest["next_wire_seq"]
    manifest["next_wire_seq"] += 1
    conn = {
        "connection_id": f"wire_{seq:04d}",
        "from_instance": from_instance,
        "from_connector": from_connector,
        "to_instance": to_instance,
        "to_connector": to_connector,
    }
    manifest["connections"].append(conn)
    return conn


def _instance_part(manifest: dict, instance_id: str) -> str:
    return find_instance(manifest, instance_id)["part_id"]


# --- .fz / .fzz generation ---------------------------------------------------

def _model_index(manifest: dict, instance_id: str) -> int:
    for i, p in enumerate(manifest["parts"]):
        if p["instance_id"] == instance_id:
            return 1000 + i
    raise McpError("INSTANCE_NOT_FOUND", instance_id)


def build_fz_xml(manifest: dict) -> str:
    from .parts import find_part_file

    parts = manifest["parts"]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(f'<module fritzingVersion="1.0.8" icon="{manifest["project_id"]}.png">')
    lines.append("    <project_properties>")
    lines.append('        <simulator_animation_time_s value="5s"/>')
    lines.append('        <simulator_number_of_steps value="400"/>')
    lines.append('        <simulator_spice_options value=""/>')
    lines.append('        <simulator_time_step_mode value="false"/>')
    lines.append('        <simulator_time_step_s value="1us"/>')
    lines.append("    </project_properties>")
    lines.append("    <boards>")
    lines.append('        <board moduleId="pcb-arduino-r3-shield" title="Arduino Shield PCB" instance="PCB1" width="6.88566cm" height="5.36311cm"/>')
    lines.append("    </boards>")
    lines.append("    <views>")
    lines.append('        <view name="breadboardView" backgroundColor="#ffffff" gridSize="0.1in" showGrid="1" alignToGrid="0" viewFromBelow="0" colorWiresByLength="0"/>')
    lines.append('        <view name="schematicView" backgroundColor="#ffffff" gridSize="0.1in" showGrid="1" alignToGrid="1" viewFromBelow="0"/>')
    lines.append('        <view name="pcbView" backgroundColor="#333333" gridSize="0.05in" showGrid="1" alignToGrid="1" viewFromBelow="0" DRC_Keepout="0.01in" autorouteViaRingThickness="0.3mm" GPG_Keepout="" autorouteTraceWidth="24" autorouteViaHoleSize="0.4mm"/>')
    lines.append("    </views>")
    lines.append("    <instances>")

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    for p in parts:
        pf = find_part_file(p["part_id"])
        path = pf.name if pf else (p["part_id"] + ".fzp")
        lines.append(f'        <instance moduleIdRef="{esc(p["part_id"])}" modelIndex="{_model_index(manifest, p["instance_id"])}" path="{esc(path)}">')
        lines.append(f"            <title>{esc(p['title'])}</title>")
        lines.append("            <views>")
        lines.append('                <breadboardView layer="breadboard">')
        lines.append(f'                    <geometry z="1.0" x="{p["x"]}" y="{p["y"]}" x1="0" y1="0" x2="0" y2="0"/>')
        lines.append("                </breadboardView>")
        lines.append('                <schematicView layer="schematic">')
        lines.append(f'                    <geometry z="1.0" x="{p["x"]}" y="{p["y"]}" x1="0" y1="0" x2="0" y2="0"/>')
        lines.append("                </schematicView>")
        lines.append('                <pcbView layer="copper1">')
        lines.append(f'                    <geometry z="1.0" x="{p["x"]}" y="{p["y"]}" x1="0" y1="0" x2="0" y2="0"/>')
        lines.append("                </pcbView>")
        lines.append("            </views>")
        lines.append("        </instance>")

    layer_map = {"breadboard": "breadboardbreadboard", "schematic": "schematicschematic", "pcb": "copper1"}
    for i, c in enumerate(manifest["connections"]):
        from_idx = _model_index(manifest, c["from_instance"])
        to_idx = _model_index(manifest, c["to_instance"])
        lines.append(f'        <instance moduleIdRef="WireModuleID" modelIndex="{5000 + i}" path="wire.fzp">')
        lines.append(f"            <title>{c['connection_id']}</title>")
        lines.append("            <views>")
        for view, layer, wl in (("breadboardView", "breadboardWire", "breadboardbreadboard"),
                                ("schematicView", "schematicWire", "schematicschematic"),
                                ("pcbView", "copper1trace", "copper1")):
            lines.append(f"                <{view} layer=\"{layer}\">")
            lines.append('                    <geometry z="3.5" x="0" y="0" x1="0" y1="0" x2="100" y2="0" wireFlags="64"/>')
            lines.append('                    <wireExtras mils="22.2222" color="#cc1414" opacity="1" banded="0"/>')
            lines.append("                    <connectors>")
            lines.append(f'                        <connector connectorId="connector1" layer="{layer}">')
            lines.append('                            <geometry x="0" y="0"/>')
            lines.append("                            <connects>")
            lines.append(f'                                <connect connectorId="{esc(c["from_connector"])}" modelIndex="{from_idx}" layer="{wl}"/>')
            lines.append("                            </connects>")
            lines.append("                        </connector>")
            lines.append(f'                        <connector connectorId="connector0" layer="{layer}">')
            lines.append('                            <geometry x="0" y="0"/>')
            lines.append("                            <connects>")
            lines.append(f'                                <connect connectorId="{esc(c["to_connector"])}" modelIndex="{to_idx}" layer="{wl}"/>')
            lines.append("                            </connects>")
            lines.append("                        </connector>")
            lines.append("                    </connectors>")
            lines.append(f"                </{view}>")
        lines.append("            </views>")
        lines.append("        </instance>")

    lines.append("    </instances>")
    lines.append("</module>")
    xml = "\n".join(lines)
    # Structural sanity: it must parse.
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        raise McpError("VALIDATION_FAILED", f"Generated FZ is not well-formed: {exc}")
    return xml


def pack_fzz(project_dir: Path, manifest: dict) -> Path:
    fz_xml = build_fz_xml(manifest)
    fz_path = project_dir / "circuit.fz"
    fz_path.write_text(fz_xml, encoding="utf-8")
    fzz_path = project_dir / "circuit.fzz"
    if fzz_path.exists():
        from ..policy import overwrite_enabled
        if not overwrite_enabled():
            # version it instead of overwriting silently
            fzz_path = project_dir / f"circuit_{datetime.now().strftime('%Y%m%d%H%M%S')}.fzz"
    with zipfile.ZipFile(fzz_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("circuit.fz", fz_xml)
    manifest["artifacts"]["fzz"] = str(fzz_path)
    manifest["artifacts"]["fz"] = str(fz_path)
    return fzz_path


def safe_extract_fzz(fzz_path: Path, dest: Path) -> Path:
    limits = zip_limits()
    try:
        zf = zipfile.ZipFile(fzz_path)
    except zipfile.BadZipFile:
        raise McpError("UNSAFE_ARCHIVE", "Not a valid zip/fzz archive.")
    names = zf.namelist()
    if len(names) > int(limits["max_files"]):
        raise McpError("UNSAFE_ARCHIVE", "Too many files in archive.")
    total = sum(i.file_size for i in zf.infolist())
    if total > int(limits["max_total_bytes"]):
        raise McpError("UNSAFE_ARCHIVE", "Archive too large (possible zip bomb).")
    allowed_ext = {".fz", ".fzp", ".svg", ".fzz", ".fzpz", ".png", ".json", ".txt", ".md", ".css", ".html"}
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or name.startswith("~"):
            raise McpError("UNSAFE_ARCHIVE", f"Unsafe member path: {name}")
        if re.match(r"^[A-Za-z]:[\\/]", name) or name.startswith("\\\\") or ".." in Path(name).parts:
            raise McpError("UNSAFE_ARCHIVE", f"Unsafe member path: {name}")
        # Windows-style traversal / device paths
        low = name.lower()
        if low.startswith(("\\\\", "//", "~")) or low.startswith("\\\\?\\") or low.startswith("\\\\.\\"):
            raise McpError("UNSAFE_ARCHIVE", f"Unsafe member path: {name}")
        if ".." in name.replace("\\", "/").split("/"):
            raise McpError("UNSAFE_ARCHIVE", f"Traversal in member: {name}")
        if Path(name).is_absolute() or re.match(r"^[A-Za-z]:", name):
            raise McpError("UNSAFE_ARCHIVE", f"Absolute member path: {name}")
        if info.file_size > int(limits["max_member_bytes"]):
            raise McpError("UNSAFE_ARCHIVE", f"Member too large: {name}")
        if Path(name).suffix.lower() not in allowed_ext:
            raise McpError("UNSAFE_ARCHIVE", f"Unexpected file type in archive: {name}")
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve(strict=False)
    for info in zf.infolist():
        target = (dest / info.filename).resolve(strict=False)
        if not str(target).lower().startswith(str(dest_resolved).lower()):
            raise McpError("UNSAFE_ARCHIVE", f"Extraction would escape target: {info.filename}")
    zf.extractall(dest)
    zf.close()
    return dest
