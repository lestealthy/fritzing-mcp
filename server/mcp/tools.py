"""MCP tool definitions. Every capability is narrow; no generic execute/run tools."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import config
from ..errors import McpError, error_dict
from ..policy import (can_transition, custom_parts_enabled, invalidate_validation,
                      part_allowed_for_placement, transition)
from ..security.audit import log_event, new_transaction_id
from ..storage import projects
from ..fritzing import installation, parts, render, sketch, validation


def _summarize_parts(manifest: dict) -> dict:
    return manifest


def register(server) -> None:  # noqa: C901 - registration table
    # ---------------- discovery ----------------
    @server.tool()
    def fritzing_status() -> dict:
        f = installation.detect_fritzing()
        p = installation.detect_parts()
        return {
            "fritzing_installed": f["installed"],
            "version": f["version"],
            "parts_database": p["available"],
            "part_count": p["part_count"],
            "server_version": config.server_version,
            "policy_version": config.policy_version,
        }

    @server.tool()
    def fritzing_search_parts(query: str, category: str = "", limit: int = 20) -> dict:
        if not query or len(query) > 100:
            return error_dict("INVALID_CONNECTION", "query must be non-empty and <= 100 chars.")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return error_dict("INVALID_CONNECTION", "limit must be an integer.")
        if limit > 50:
            limit = 50
        results = parts.search_parts(query, category or None, limit)
        return {"query": query, "count": len(results), "parts": results}

    @server.tool()
    def fritzing_get_part(part_id: str) -> dict:
        try:
            return parts.get_part(part_id)
        except McpError as e:
            return e.to_dict()

    @server.tool()
    def fritzing_get_part_connectors(part_id: str) -> dict:
        try:
            connectors = parts.get_connectors(part_id)
            return {"part_id": part_id, "connectors": connectors}
        except McpError as e:
            return e.to_dict()

    # ---------------- project lifecycle ----------------
    @server.tool()
    def fritzing_create_project(project_name: str, description: str = "", template: str = "") -> dict:
        try:
            return projects.create_project(project_name, description, template or None)
        except McpError as e:
            return e.to_dict()

    @server.tool()
    def fritzing_get_project(project_id: str) -> dict:
        try:
            return projects.get_project(project_id)
        except McpError as e:
            return e.to_dict()

    @server.tool()
    def fritzing_save_project(project_id: str) -> dict:
        try:
            return projects.save_project(project_id, dest="completed")
        except McpError as e:
            return e.to_dict()

    # ---------------- placement ----------------
    @server.tool()
    def fritzing_place_part(project_id: str, part_id: str, view: str = "breadboard",
                            x: float = 0, y: float = 0, rotation: int = 0) -> dict:
        try:
            pdir, manifest, txid = projects.mutation(project_id, "fritzing_place_part",
                                                     {"part_id": part_id, "view": view, "x": x, "y": y, "rotation": rotation})
            part = parts.get_part(part_id)
            trust = part["trust"]
            if not part_allowed_for_placement(trust):
                projects.rollback(pdir, manifest, txid)
                return error_dict("PART_NOT_TRUSTED", f"Part trust level '{trust}' is not allowed by policy.",
                                  suggestion="Use OFFICIAL or VERIFIED parts, or ask an administrator to change policy.")
            invalidate_validation(manifest, "place_part")
            inst = sketch.add_instance(manifest, part_id, part["title"], view, x, y, rotation, trust)
            if manifest["state"] in ("CREATED", "DISCOVERED"):
                if manifest["state"] == "CREATED":
                    transition(manifest, "DISCOVERED")
                transition(manifest, "PLACED")
            elif manifest["state"] in ("PLACED", "WIRED", "SAVED"):
                pass
            elif manifest["state"] in ("VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE"):
                manifest["state"] = "PLACED"  # force re-validation
            projects.finalize(pdir, manifest, txid, "fritzing_place_part",
                              {"part_id": part_id, "instance_id": inst["instance_id"]})
            return {"instance_id": inst["instance_id"], "part_id": part_id, "title": part["title"], "state": manifest["state"]}
        except McpError as e:
            return e.to_dict()

    @server.tool()
    def fritzing_move_part(project_id: str, instance_id: str, x: float = 0, y: float = 0,
                           rotation: int = -1) -> dict:
        try:
            pdir, manifest, txid = projects.mutation(project_id, "fritzing_move_part",
                                                     {"instance_id": instance_id, "x": x, "y": y})
            inst = sketch.move_instance(manifest, instance_id, x, y, None if rotation == -1 else rotation)
            invalidate_validation(manifest, "move_part")
            projects.finalize(pdir, manifest, txid, "fritzing_move_part", {"instance_id": instance_id})
            return {"instance_id": instance_id, "x": inst["x"], "y": inst["y"], "rotation": inst["rotation"]}
        except McpError as e:
            return e.to_dict()

    # ---------------- wiring ----------------
    @server.tool()
    def fritzing_wire(project_id: str, from_instance: str, from_connector: str,
                      to_instance: str, to_connector: str) -> dict:
        try:
            pdir, manifest, txid = projects.mutation(project_id, "fritzing_wire",
                                                     {"from_instance": from_instance, "from_connector": from_connector,
                                                      "to_instance": to_instance, "to_connector": to_connector})
            try:
                conn = sketch.add_connection(manifest, from_instance, from_connector, to_instance, to_connector)
            except McpError as e:
                projects.rollback(pdir, manifest, txid)
                return e.to_dict()
            invalidate_validation(manifest, "wire")
            try:
                if manifest["state"] == "PLACED":
                    transition(manifest, "WIRED")
                elif manifest["state"] in ("VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE"):
                    manifest["state"] = "WIRED"  # force re-validation before next save
            except McpError:
                pass
            projects.finalize(pdir, manifest, txid, "fritzing_wire",
                              {"from_instance": from_instance, "to_instance": to_instance,
                               "from_connector": from_connector, "to_connector": to_connector})
            return {"connection_id": conn["connection_id"], "state": manifest["state"],
                    "from": {"instance": from_instance, "connector": from_connector},
                    "to": {"instance": to_instance, "connector": to_connector}}
        except McpError as e:
            return e.to_dict()

    # ---------------- validation ----------------
    @server.tool()
    def fritzing_validate_project(project_id: str) -> dict:
        try:
            pdir = projects.get_project_dir(project_id)
            manifest = sketch.load_manifest(pdir)
            result = validation.run_validation(pdir, manifest)
            manifest["dirty"] = False
            if manifest["state"] in ("WIRED", "PLACED", "RENDERED"):
                try:
                    transition(manifest, "VALIDATED")
                except McpError:
                    pass
            sketch.save_manifest(pdir, manifest)
            log_event(pdir, "fritzing_validate_project", project_id, {}, result["status"])
            return result
        except McpError as e:
            return e.to_dict()

    # ---------------- render / visual ----------------
    @server.tool()
    def fritzing_render(project_id: str, view: str = "all") -> dict:
        try:
            pdir = projects.get_project_dir(project_id)
            manifest = sketch.load_manifest(pdir)
            if view not in ("breadboard", "schematic", "pcb", "all"):
                return error_dict("INVALID_CONNECTION", "view must be breadboard|schematic|pcb|all")
            # render requires a validated, non-stale project
            validation = manifest.get("validation", {})
            if manifest.get("dirty") or validation.get("stale"):
                return error_dict("PROJECT_NOT_VALIDATED",
                                  "Project must be validated after the last mutation before rendering.",
                                  suggestion="Call fritzing_validate_project and ensure it does not FAIL.")
            status = validation.get("status")
            if not status:
                return error_dict("PROJECT_NOT_VALIDATED",
                                  "Project has never been validated.",
                                  suggestion="Call fritzing_validate_project before rendering.")
            if status == "FAIL":
                return error_dict("RENDER_DENIED",
                                  "Validation FAILED; render denied.",
                                  suggestion="Fix validation errors, then validate again.")
            if manifest.get("state") not in ("VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE"):
                return error_dict("PROJECT_NOT_VALIDATED",
                                  f"Render requires state VALIDATED; current state is {manifest.get('state')}.")
            # ensure an up-to-date .fzz exists
            sketch.pack_fzz(pdir, manifest)
            result = render.render_project(pdir, manifest, view)
            try:
                if manifest["state"] == "VALIDATED":
                    transition(manifest, "RENDERED")
            except McpError:
                pass
            sketch.save_manifest(pdir, manifest)
            log_event(pdir, "fritzing_render", project_id, {"view": view}, result["status"])
            return result
        except McpError as e:
            return e.to_dict()

    @server.tool()
    def fritzing_visual_report(project_id: str) -> dict:
        try:
            pdir = projects.get_project_dir(project_id)
            manifest = sketch.load_manifest(pdir)
            artifacts = manifest.get("artifacts", {}).get("render")
            if not artifacts:
                return error_dict("RENDER_FAILED", "No render artifacts yet.",
                                  suggestion="Call fritzing_render first.")
            try:
                if manifest["state"] == "RENDERED":
                    transition(manifest, "REVIEWED")
            except McpError:
                pass
            sketch.save_manifest(pdir, manifest)
            log_event(pdir, "fritzing_visual_report", project_id, {}, "success")
            return {
                "state": manifest["state"],
                "artifacts": artifacts,
                "inspection_guidance": [
                    "overlapping parts",
                    "confusing wire crossings",
                    "unreadable labels",
                    "disconnected-looking wires",
                    "components outside workspace",
                    "missing symbols",
                    "malformed custom parts",
                ],
                "note": "Visual inspection does not replace electrical validation.",
            }
        except McpError as e:
            return e.to_dict()

    # ---------------- custom parts (policy-gated) ----------------
    @server.tool()
    def fritzing_create_part(title: str = "") -> dict:
        if not custom_parts_enabled():
            return error_dict("CUSTOM_PARTS_DISABLED",
                              "Custom part creation is disabled by policy.",
                              suggestion="Ask an administrator to enable custom_parts in policy/policy.json.")
        return error_dict("NOT_IMPLEMENTED", "Custom part generation is not enabled in this build.")

    @server.tool()
    def fritzing_validate_part(part_path: str = "") -> dict:
        if not custom_parts_enabled():
            return error_dict("CUSTOM_PARTS_DISABLED", "Custom part validation is disabled by policy.")
        return error_dict("NOT_IMPLEMENTED", "Custom part validation requires an uploaded part, not enabled here.")


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name="wattlab-fritzing", version=config.server_version)
    register(server)
    from .resources import register as reg_res
    from .prompts import register as reg_prompts

    reg_res(server)
    reg_prompts(server)
    return server
