"""Entry point: `python -m server.main [serve|doctor|index-parts]`."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"

    _configure_logging()
    logger = logging.getLogger("fritzing_mcp")

    if cmd == "doctor":
        from server.fritzing.installation import run_doctor

        report = run_doctor()
        print(report["report"])
        return 0

    if cmd == "serve":
        from server.mcp.tools import build_server

        server = build_server()
        logger.info("WattLab Fritzing MCP server starting (stdio transport)...")
        server.run(transport="stdio")
        return 0

    if cmd in ("help", "-h", "--help"):
        print("Usage: python -m server.main [serve|doctor]")
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
