# Troubleshooting

- PART_NOT_FOUND: search again; module IDs come from parts.db.
- CONNECTOR_NOT_FOUND: inspect `fritzing_get_part_connectors`.
- INSTANCE_NOT_FOUND: use the instance_id returned by place/get_project.
- PROJECT_STATE_INVALID: follow CREATED -> DISCOVERED -> PLACED -> WIRED -> VALIDATED -> RENDERED -> REVIEWED -> SAVED.
- SAVE_DENIED: run validation; fix ERRORs.
- RENDER_FAILED: the stored .fzz may be stale; save again to regenerate, then render.
- If Fritzing seems to hang while exporting, stale dialog windows may be up; the server's watchdog normally dismisses them.
