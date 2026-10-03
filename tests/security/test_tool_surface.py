"""The exposed MCP surface must be exactly the controlled tool set; no execute/read/write/http tools."""

import asyncio

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run():
    async def go():
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "server.main", "serve"],
                                       cwd=ROOT)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                resources = await session.list_resources()
                rnames = {r.uri for r in resources.resources}
                prompts = await session.list_prompts()
                pnames = {p.name for p in prompts.prompts}
                return names, rnames, pnames, tools.tools

    return asyncio.run(go())


def test_tool_surface_is_controlled():
    names, rnames, pnames, _ = _run()
    forbidden = {"execute_command", "execute_shell", "execute_python", "execute_powershell",
                 "execute_javascript", "execute_fritzing_command", "read_file", "write_file",
                 "delete_file", "http_request", "run", "shell"}
    assert not (names & forbidden)
    expected = {
        "fritzing_status", "fritzing_search_parts", "fritzing_get_part", "fritzing_get_part_connectors",
        "fritzing_create_project", "fritzing_get_project", "fritzing_save_project", "fritzing_place_part",
        "fritzing_move_part", "fritzing_wire", "fritzing_validate_project", "fritzing_render",
        "fritzing_visual_report", "fritzing_create_part", "fritzing_validate_part",
    }
    assert expected <= names


def test_save_tool_has_no_path_parameter():
    _, _, _, tools = _run()
    save = next(t for t in tools if t.name == "fritzing_save_project")
    schema = getattr(save, "input_schema", None) or getattr(save, "inputSchema", {}) or {}
    props = (schema or {}).get("properties", {})
    assert "path" not in props
    assert "output_path" not in props


def test_resources_and_prompts_present():
    _, rnames, pnames, _ = _run()
    assert "fritzing://rules" in {str(u) for u in rnames}
    assert any(str(u).startswith("fritzing://tutorial") for u in rnames)
    assert "fritzing_create_schematic" in pnames
