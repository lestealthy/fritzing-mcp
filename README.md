# WattLab Controlled Fritzing MCP

A strictly controlled local MCP server that lets an AI agent perform *narrow, validated Fritzing engineering operations* — search parts, inspect connectors, place, wire, validate, render, save — while the AI gets **no shell, no arbitrary filesystem access, no generic process execution, no direct Fritzing control**. The MCP server is the security boundary; the AI is not trusted.

## What this is / is not

- **Is**: a Windows MCP server (Python 3.11+, `mcp` 2.x) over a standard Fritzing install.
- **Is not**: a general-purpose AI-computer-control tool; a formal electrical simulator; a nice way to bypass the user’s Fritzing library.

## Architecture

```text
AI AGENT
   │ MCP (stdio, tool calls only)
   ▼
server/mcp/tools.py     # narrow tools: search / inspect / create / place / move / wire / validate / render / visual_report / save
   │
   ▼
server/policy.py        # trust levels, lifecycle state machine, save policy
   ▼
server/fritzing/        # parts.db integration, .fz/.fzz generation, validation, rendering
   ▼
artifact manager        # projects/active|completed|rejected/<WTL-FZ-...>/
```

Everything the AI can touch is a JSON-manifest-authoritative project under `C:\Users\...\fritzing_mcp\projects`. There is no download/HTTP tool, no file-path tool, no shell tool.

## Project lifecycle (enforced)

```text
CREATED → DISCOVERED → PLACED → WIRED → VALIDATED → RENDERED → REVIEWED → READY_TO_SAVE → SAVED
```

- `fritzing_render` **requires** a validated, non-stale project (`dirty == false`, `status != FAIL`).
- Every structural mutation invalidates validation and reverts state (`WIRED/PLACED`), forces re-validation.
- `fritzing_save_project` **requires** fresh validation; `PASS` saves as verified, `PASS_WITH_WARNINGS` saves only if policy allows warnings, `FAIL` saves only to the rejected store, and stale/never-validated projects are denied.

## Part trust model

```text
OFFICIAL / VERIFIED  -> placeable
COMMUNITY            -> requires policy enablement
GENERATED            -> requires validation
UNKNOWN / REJECTED   -> denied
```

A client cannot bypass trust by supplying an arbitrary part ID; unknown IDs and connector lookups fail hard.

## Project manifest

```json
{
  "project_id": "WTL-FZ-2026-0001",
  "state": "…",
  "parts": [{ "instance_id": "inst_0001", "part_id": "…", "x": 0, "y": 0, "rotation": 0, "view": "breadboard" }],
  "connections": [{ "connection_id": "wire_0001", "from_instance": "…", "from_connector": "…", "to_instance": "…", "to_connector": "…" }],
  "validation": { "status": "PASS | PASS_WITH_WARNINGS | FAIL", "errors": [...], "warnings": [...], "needs_human_review": [...] },
  "artifacts": { "fz": "…/circuit.fz", "fzz": "…/circuit.fzz", "render": { "engine": "…", "svgs": [...] } }
}
```

- `.fz` and `.fzz` are regenerated from the manifest at save time.
- Audit log: `projects/<id>/audit.jsonl` with `timestamp`, `request_id`, `transaction_id`, `tool`, `project`, `actor`, `parameters` (secrets scrubbed), `result`.

## Security

| Capability | Allowed? |
| --- | --- |
| `run_shell`, `exec_python`, `read_file`, `write_file`, `http_request` | **No** — no such tools exist |
| Search / inspect / place / wire / validate / render / save | Yes, narrowly |
| Relative paths, `..`, UNC, `\\?\`, `\\.\`, absolute paths outside controlled root | Rejected at `PATH_NOT_ALLOWED` |
| Path traversal inside `.fzz` extraction | Rejected; zip bounded (`max_files`, `max_total_bytes`, `max_member_bytes`) |
| Project-name shell injection / reserved names | Rejected |
| Overwriting other projects | Blocked |

Trust is enforced server-side; the AI cannot escalate with prompt text.

## Rendering

Two engines, always truthful:

```json
{ "engine": "fritzing-native" }
```
or
```json
{ "engine": "builtin-engineering-preview", "precision": "approximate" }
```

- **fritzing-native**: runs the real `Fritzing.exe -svg` headless against an isolated profile with a dialog-dismissal watchdog.
- **builtin-engineering-preview**: draws component SVGs at manifest positions, plus connector markers, labeled endpoints, and explicit wire polylines for every connection. This is an **engineering preview**, not an authoritative Fritzing render — it is labeled `approximate`.

If the native export is blank/missing the engine falls back to the preview; the mcp never silently calls a fallback render `fritzing-native`.

## FZZ portability

`circuit.fzz` is a zip containing `circuit.fz`, referencing parts by the module IDs from the stock `fritzing-parts` installation. The artifact:

- is structurally validated (must parse as XML zip),
- contains no absolute paths,
- opens in the installed Fritzing (verified on 1.0.8.0).

For portability beyond the current install, the receiving Fritzing must have the same `fritzing-parts`-family access (core/contributed modules). The manifest and render artifacts are versioned alongside it.

## Validation behavior

`fritzing_validate_project` produces structured diagnostics and a status:

| Checks | Type |
| --- | --- |
| manifest schema, duplicate parts/wires | structural |
| 5V↔3V3 rails, rail⇄ground, missing VCC/GND, orphaned part, possible driven-output short | electrical **heuristic** |
| duplicate module ID, unknown connector reference | structural |

These heuristics are surfaced as `ERROR`/`WARNING`/`NEEDS_HUMAN_REVIEW` and are the basis for saving. They are **not** a substitute for SPICE/electrical review.

## Configuration

- `policy/policy.json` — feature flags: `filesystem`, `shell` (always off), `custom_parts` (off by default), `community_parts`, `overwrite`, `network`, `save.require_valid_validation`, `save.allow_warnings`, `zip` limits.
- Environment overrides: `FRITZING_DIR`, `FRITZING_EXE`, `FRITZING_PARTS_DIR`, `FRITZING_DOCUMENTS_DIR`.

## Running

```powershell
python -m server.main doctor          # environment diagnostic
python -m server.main serve           # start the MCP server (stdio)
pytest
```

Open an MCP client (JSON-RPC over stdio). Point it at:

```json
{
  "mcpServers": {
    "fritzing": {
      "command": "python",
      "args": ["-m", "server.main", "serve"],
      "cwd": "C:\\Users\\Stealthy\\Desktop\\MCP\\fritzing_mcp"
    }
  }
}
```

## Tools

| Tool | Purpose |
| --- | --- |
| `fritzing_status` | environment + version + policy summary |
| `fritzing_search_parts` | indexed search (max 50) |
| `fritzing_get_part` | full metadata, trust, views, connectors |
| `fritzing_get_part_connectors` | normalized connector table |
| `fritzing_create_project` | new `WTL-FZ-YYYY-NNNN` project |
| `fritzing_get_project` | manifest view |
| `fritzing_place_part` | add instance (trust/rotation/coordinate validated) |
| `fritzing_move_part` | move existing instance |
| `fritzing_wire` | add a connection between validated connector IDs (no duplicates) |
| `fritzing_validate_project` | run validation pipeline → status |
| `fritzing_render` | gated render (native → fallback) |
| `fritzing_visual_report` | inspect render artifacts |
| `fritzing_save_project` | lifecycle-gated save; forced path (never accepts arbitrary output path) |
| `fritzing_create_part` | gated OFF (NOT_IMPLEMENTED) unless custom parts enabled |
| `fritzing_validate_part` | custom-part validation hook |

## Rules for agents

See `knowledge/AGENT_CONTRACT.md`. Summary: search before wiring, don't invent IDs, validate before render/save, never request shell/filesystem access, treat `NEEDS_HUMAN_REVIEW` seriously, and never claim electrical correctness beyond what the validator reports.

## MCP resources

- `fritzing://rules`
- `fritzing://tutorial/create-schematic`
- `fritzing://tutorial/validation`
- `fritzing://parts/policy`
- `fritzing://project-schema`
- `fritzing://tool-guide`
- `fritzing://troubleshooting`
- `fritzing://knowledge/{workflow,parts,schematic,validation,rules,troubleshooting}`

## MCP prompts

- `fritzing_create_schematic`
- `fritzing_debug_schematic`
- `fritzing_validate_schematic`
- `fritzing_create_custom_part`

## Known limitations

1. **Native headless render is unreliable on this machine** — the isolated profile's installer parts-db lookup does not resolve (`Application folder fritzing-parts not found`), so native export yields blank canvases on some runs. The fallback engineering preview is deterministic but approximate.
2. **FZZ dependencies** — the artifact references stock `fritzing-parts` module IDs; move it between identical Fritzing installs only.
3. **Heuristic electrical checks** are advisory, not proof.
4. **No PNG export** — native SVG export only; no Windows multi-format conversion hook yet.
5. User parts (`Documents\Fritzing\parts`) currently contain duplicates/`__MACOSX` files that cause modal Fritzing dialogs — admins should clean that directory; the server ignores arbitrary user-paths, so it is not affected functionally.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `PART_NOT_FOUND` | confirm part id via `fritzing_search_parts`; IDs are case-sensitive |
| `CONNECTOR_NOT_FOUND` | call `fritzing_get_part_connectors` |
| `PROJECT_NOT_VALIDATED` on render | run `fritzing_validate_project` first; check dirty state |
| `SAVE_DENIED` | decode `stale`/`dirty`/status and re-validate |
| `RENDER_FAILED`/engine = builtin-engineering-preview | native export unavailable; check Fritzing install / profile permissions |
| Fritzing dialogs blocking | close orphaned Fritzing processes; clean `Documents\Fritzing\parts` duplicates |

## Development / testing

```powershell
python -m pytest tests           # unit + integration + security
python -m pytest tests\integration\test_render.py   # renderer (slow, touches Fritzing.exe)
python -m server.main doctor
```

Tests are deterministic and do not depend on the polluted user-parts directory.

## License

GPL-2.0-or-later, matching the Fritzing project.
