# MCP Agent Rules

- Use only exposed tools.
- No arbitrary shell, filesystem, or Python execution exists in this server.
- Do not invent part IDs, connector IDs, or validation results.
- Save is denied until a successful validation follows the last mutation.
- Report the real validation status returned by the server.
