"""MCP prompts enforcing the workflow."""

from __future__ import annotations

_CREATE = """Create a Fritzing schematic via the restricted tools. Follow every step:

1. Understand the requested circuit.
2. List required components.
3. fritzing_search_parts for each component.
4. fritzing_get_part_connectors for each chosen part.
5. fritzing_create_project.
6. fritzing_place_part for each component.
7. fritzing_wire only verified connectors.
8. fritzing_validate_project.
9. fritzing_render.
10. fritzing_visual_report and inspect the artifacts.
11. Fix problems.
12. fritzing_validate_project again.
13. fritzing_save_project.
14. Report project ID and artifact locations.

Do not skip validation. Do not invent part IDs or connector IDs.
Do not claim success unless the tool returned success.
"""


def register(server) -> None:
    @server.prompt()
    def fritzing_create_schematic() -> str:
        return _CREATE

    @server.prompt()
    def fritzing_debug_schematic() -> str:
        return (_CREATE + "\nDEBUG MODE: first run fritzing_get_project and fritzing_validate_project, "
                "read every ERROR/WARNING, then fix only with the exposed tools.\n")

    @server.prompt()
    def fritzing_validate_schematic() -> str:
        return ("Run fritzing_validate_project on the active project, explain every diagnostic with its "
                "code and severity, and recommend the minimal fix. Do not save until validation passes.\n")

    @server.prompt()
    def fritzing_create_custom_part() -> str:
        return ("Custom parts are DISABLED by default. Check fritzing_status/policy first. "
                "If disabled, explain that an administrator must enable custom_parts before any "
                "fritzing_create_part call. Never generate arbitrary files.\n")
