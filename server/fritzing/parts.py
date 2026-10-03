"""Indexed parts search and connector normalization backed by parts.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import config
from ..errors import McpError
from ..policy import community_parts_enabled

_CONN_TYPE_NAMES = {0: "connector", 1: "terminal", 2: "bus", 3: "power", 4: "unspecified"}


def _conn() -> sqlite3.Connection:
    if not config.parts_db.is_file():
        raise McpError("PART_NOT_FOUND", f"parts.db not found at {config.parts_db}")
    conn = sqlite3.connect(str(config.parts_db))
    conn.row_factory = sqlite3.Row
    return conn


def fritzing_version_from_db() -> str | None:
    # parts.db stores commits, not version; fall back to install metadata.
    f = config.fritzing_dir / "swidtag"
    try:
        for p in config.fritzing_dir.glob("*.swidtag"):
            text = p.read_text(errors="ignore")
            import re
            m = re.search(r"product_version>\s*<swid:name>\s*([^<]+)", text, re.S)
            if m:
                return m.group(1).strip()
            m = re.search(r'version[^>]*>\s*([^<]+)', text)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return None


def classify_trust(module_id: str, path: str, family: str) -> str:
    p = (path or "").lower()
    f = (family or "").lower()
    if p.startswith("core/"):
        return "OFFICIAL"
    if p.startswith("obsolete/") or "obsolete" in f:
        return "REJECTED"
    if p.startswith("contrib/"):
        return "COMMUNITY"
    if p.startswith("user/"):
        return "COMMUNITY"
    return "UNKNOWN"


def search_parts(query: str, category: str | None = None, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 50))
    results = []
    try:
        conn = _conn()
        sql = (
            "SELECT moduleID, title, description, family, path, author FROM parts "
            "WHERE (title LIKE ? OR moduleID LIKE ? OR description LIKE ? OR family LIKE ?)"
        )
        params: list = [f"%{query}%"] * 4
        if category:
            sql += " AND family LIKE ?"
            params.append(f"%{category}%")
        sql += f" LIMIT {limit}"
        for r in conn.execute(sql, params):
            results.append({
                "part_id": r["moduleID"],
                "title": r["title"],
                "description": (r["description"] or "")[:300],
                "category": r["family"],
                "author": r["author"],
                "source": "fritzing-parts",
                "trust": classify_trust(r["moduleID"], r["path"], r["family"]),
                "verified": classify_trust(r["moduleID"], r["path"], r["family"]) in ("OFFICIAL", "VERIFIED"),
            })
        conn.close()
    finally:
        pass
    return results


def get_part(part_id: str) -> dict:
    conn = _conn()
    try:
        r = conn.execute(
            "SELECT id, moduleID, title, description, family, path, author, fritzingversion FROM parts WHERE moduleID = ? LIMIT 1",
            (part_id,),
        ).fetchone()
        if r is None:
            raise McpError("PART_NOT_FOUND", f"No part with id '{part_id}'.",
                           suggestion="Call fritzing_search_parts to discover valid IDs.")
        views = [dict(v) for v in conn.execute(
            "SELECT viewid, image, layers FROM viewimages WHERE part_id = ?", (r["id"],)).fetchall()]
        connectors = _fetch_connectors(conn, r["id"])
        buses = [dict(b) for b in conn.execute(
            "SELECT name FROM buses WHERE part_id = ?", (r["id"],)).fetchall()]
        tags = [t[0] for t in conn.execute("SELECT tag FROM tags WHERE part_id = ?", (r["id"],))]
        return {
            "part_id": r["moduleID"],
            "title": r["title"],
            "description": r["description"],
            "category": r["family"],
            "author": r["author"],
            "fritzing_version": r["fritzingversion"],
            "source": "fritzing-parts",
            "path": r["path"],
            "trust": classify_trust(r["moduleID"], r["path"], r["family"]),
            "views": [v["viewid"] for v in views],
            "tags": tags,
            "buses": [b["name"] for b in buses],
            "connectors": connectors,
            "validation_status": "indexed",
        }
    finally:
        conn.close()


def _fetch_connectors(conn: sqlite3.Connection, part_db_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.connectorid, c.type, c.name, c.description, cl.view, cl.layer, cl.svgid "
        "FROM connectors c LEFT JOIN connectorlayers cl ON cl.connector_id = c.id "
        "WHERE c.part_id = ? ORDER BY c.connectorid",
        (part_db_id,),
    ).fetchall()
    by_id: dict[str, dict] = {}
    for r in rows:
        cid = r["connectorid"]
        entry = by_id.setdefault(cid, {
            "connector_id": cid,
            "name": r["name"],
            "description": r["description"],
            "type": _CONN_TYPE_NAMES.get(r["type"], "unknown"),
            "views": [],
        })
        if r["view"] and r["view"] not in entry["views"]:
            entry["views"].append(r["view"])
    return list(by_id.values())


def get_connectors(part_id: str) -> list[dict]:
    return get_part(part_id)["connectors"]


def find_part_file(part_id: str) -> Path | None:
    try:
        conn = _conn()
        try:
            r = conn.execute("SELECT path FROM parts WHERE moduleID = ? LIMIT 1", (part_id,)).fetchone()
            if r and r["path"]:
                p = config.parts_dir / r["path"]
                if p.is_file():
                    return p
        finally:
            conn.close()
    except McpError:
        pass
    return None
