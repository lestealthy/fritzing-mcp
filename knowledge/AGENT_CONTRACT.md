# WattLab Fritzing MCP — Agent Contract

You are operating a restricted engineering MCP.

## Hard rules

- Search the parts library before selecting parts.
- Inspect connector definitions before wiring.
- Never invent part IDs or connector IDs.
- Never request shell access, arbitrary filesystem access, file read/write tools, HTTP tools, or any non-engineering capability.
- Validate after every structural change (place / move / wire / property change).
- Never bypass validation.
- Never save an unvalidated project.
- Render only after a valid, non-stale validation.
- Treat warnings seriously. `NEEDS_HUMAN_REVIEW` means a human should check.
- Never claim electrical correctness beyond the evidence the validator returns.
- Never modify artifacts outside the MCP workflow.
- Report the actual validation status returned by the validator verbatim.
- If a render reports `engine: "builtin-engineering-preview"`, describe it as an approximate engineering preview, not a final Fritzing render.

## Lifecycle contract

`CREATED → DISCOVERED → PLACED → WIRED → VALIDATED → RENDERED → REVIEWED → READY_TO_SAVE → SAVED`

Mutations reset you to the editing state (`WIRED`/`PLACED`) and invalidate prior validation. Always re-validate after a mutation before rendering or saving.

## Error handling contract

- `PART_NOT_FOUND` / `CONNECTOR_NOT_FOUND`: stop and rediscover via search/inspect.
- `PART_NOT_TRUSTED`: switch part or escalate to a human for policy change.
- `PROJECT_STATE_INVALID` / `VALIDATION_STALE` / `RENDER_DENIED` / `SAVE_DENIED`: follow the suggestion field; do not retry blindly.
- `PATH_NOT_ALLOWED`: never attempt to craft a path around the controlled root.
