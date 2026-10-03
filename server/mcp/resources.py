"""Read-only MCP resources: rules, tutorials, guides."""

from __future__ import annotations

from pathlib import Path

RESOURCES = {
    "fritzing://rules": """You are operating Fritzing through a restricted engineering interface.

You may only use the exposed Fritzing MCP tools.
You may not request arbitrary shell execution.
You may not manipulate files directly.
You must search the parts library before using parts.
You must inspect connector definitions before wiring.
You must validate after structural changes.
You must render before declaring visual completion.
You must not claim electrical correctness unless the server explicitly reports it.
You must report warnings.
You must never bypass failed validation.
""",
    "fritzing://tutorial/create-schematic": """Fritzing schematic creation tutorial.

USER REQUEST: Create an LED circuit using Arduino Uno.

1. fritzing_search_parts("Arduino Uno")
2. fritzing_search_parts("resistor")
3. fritzing_search_parts("LED")
4. fritzing_get_part_connectors for each chosen part
5. fritzing_create_project(project_name="led_circuit", description="...")
6. fritzing_place_part for Arduino, resistor, LED
7. fritzing_wire: Arduino digital pin -> resistor -> LED anode; LED cathode -> Arduino GND
8. fritzing_validate_project
9. fritzing_render(project_id, view="schematic")
10. fritzing_visual_report
11. Fix any problems, then validate again
12. fritzing_save_project

Do NOT skip validation. Do NOT invent part IDs or connector IDs.
Do NOT claim validation succeeded unless the tool returned success.
""",
    "fritzing://tutorial/validation": """Validation tutorial.

Run fritzing_validate_project after any structural change. Read the structured
diagnostics. Address every ERROR. Review every WARNING and NEEDS_HUMAN_REVIEW.
A project can only be saved as verified when validation status is PASS or
PASS_WITH_WARNINGS (warnings allowed by policy).
""",
    "fritzing://parts/policy": """Part trust policy.

OFFICIAL and VERIFIED parts may be placed without approval.
COMMUNITY parts require administrator policy.
GENERATED parts require validation.
REJECTED and UNKNOWN parts are denied.
""",
    "fritzing://project-schema": """Every project has project.json with:

{project_id, name, description, state, parts[], connections[], validation{}, artifacts{}}

States: CREATED -> DISCOVERED -> PLACED -> WIRED -> VALIDATED -> RENDERED -> REVIEWED -> READY_TO_SAVE -> SAVED
""",
    "fritzing://tool-guide": """Tools are narrow operations: search, inspect, create, place, move, wire, validate, render, save.
There is no generic execute/run/shell tool.
All paths are server-managed; you cannot choose arbitrary output paths.
""",
    "fritzing://troubleshooting": """Common issues:
- PART_NOT_FOUND: re-run search; IDs are case-sensitive module IDs.
- CONNECTOR_NOT_FOUND: call fritzing_get_part_connectors.
- PATH_NOT_ALLOWED: you cannot supply arbitrary paths; use project IDs.
- SAVE_DENIED: run validate first; fix ERRORs.
- RENDER_FAILED: Fritzing could not open the file; generate again via save.
""",
}

# Also serve knowledge markdown files as resources when present.
KNOWLEDGE = [
    ("fritzing://knowledge/workflow", "knowledge/FRITZING_WORKFLOW.md"),
    ("fritzing://knowledge/parts", "knowledge/PARTS_GUIDE.md"),
    ("fritzing://knowledge/schematic", "knowledge/SCHEMATIC_GUIDE.md"),
    ("fritzing://knowledge/validation", "knowledge/VALIDATION_GUIDE.md"),
    ("fritzing://knowledge/rules", "knowledge/MCP_AGENT_RULES.md"),
    ("fritzing://knowledge/troubleshooting", "knowledge/TROUBLESHOOTING.md"),
]


def register(server) -> None:
    from mcp.types import TextResourceContents  # noqa: F401

    for uri, text in RESOURCES.items():
        def _make(t):
            def _read():
                return t
            return _read

        server.resource(uri, name=uri.split("://")[-1], description="WattLab Fritzing MCP resource")(_make(text))

    base = Path(__file__).resolve().parents[2]
    for uri, rel in KNOWLEDGE:
        path = base / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            def _make2(t):
                def _read():
                    return t
                return _read
            server.resource(uri, name=rel, description="Knowledge document")(_make2(text))
