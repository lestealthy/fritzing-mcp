"""Headless rendering: export SVGs via the real Fritzing binary, in a temp profile."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ..config import config
from ..errors import McpError

_PROFILE_READY = False


def ensure_profile() -> Path:
    """Create an isolated Fritzing profile (parts.db + junctions) so user dirs don't interfere."""
    global _PROFILE_READY
    prof = config.render_profile
    (prof / "parts").mkdir(parents=True, exist_ok=True)
    (prof / "sketches").mkdir(parents=True, exist_ok=True)
    try:
        src_db = config.parts_db
        dst_db = prof / "parts" / "parts.db"
        if src_db.is_file() and not dst_db.exists():
            shutil.copy2(src_db, dst_db)
    except OSError:
        pass
    for name, src in (
        ("bins", config.fritzing_dir / "fritzing-parts" / "bins"),
        ("translations", config.fritzing_dir / "translations"),
        ("fritzing-parts", config.fritzing_dir / "fritzing-parts"),
    ):
        link = prof / name
        try:
            if not link.exists() and src.exists():
                import ctypes
                # directory junction avoids admin rights
                ctypes.windll.kernel32.CreateSymbolicLinkW(str(link), str(src), 1)
        except OSError:
            pass
        if not link.exists():
            try:
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(src)],
                               check=True, capture_output=True, timeout=60)
            except Exception:
                pass
    _PROFILE_READY = True
    return prof


def _dismiss_dialogs(proc: subprocess.Popen, stop: threading.Event) -> None:
    """Auto-click OK on Fritzing's modal dialogs so headless export can proceed."""
    try:
        import win32gui
    except Exception:
        return

    def _ok_click(hwnd, _extra) -> bool:
        title = win32gui.GetWindowText(hwnd) or ""
        if title.strip().lower() in ("fritzing", "oops!") or "parse error" in title.lower() or title.strip().lower() == "error":
            def _cb(child, found):
                try:
                    text = win32gui.GetWindowText(child)
                    cls = win32gui.GetClassName(child)
                    if cls.startswith("Button") and text.strip().upper() in ("OK", "CONTINUE", "YES"):
                        found.append(child)
                except Exception:
                    pass
            found: list = []
            win32gui.EnumChildWindows(hwnd, _cb, found)
            for child in found:
                try:
                    win32gui.PostMessage(child, 0x00F5, 0, 0)  # BM_CLICK
                except Exception:
                    pass
        return True

    while not stop.is_set():
        try:
            win32gui.EnumWindows(_ok_click, None)
        except Exception:
            pass
        time.sleep(0.5)


_VIEW_VIEWBOX = {"breadboard": "breadboard", "schematic": "schematic", "pcb": "pcb"}


def _part_svg_for_view(part_id: str, view: str):
    try:
        from .parts import find_part_file

        fzp = find_part_file(part_id)
    except Exception:
        return None
    if fzp is None:
        return None
    stem = fzp.stem
    parts_dir = config.parts_dir / "svg"
    for sub in ("core", "contrib", "user", "obsolete"):
        folder = parts_dir / sub / view
        if not folder.is_dir():
            continue
        exact = folder / f"{stem}_{view}.svg"
        if exact.is_file():
            return exact
        for f in folder.iterdir():
            if f.name.lower().endswith(f"_{view}.svg") and stem.lower().split("(")[0] in f.name.lower():
                return f
    return None


def _connector_position(part_id: str, connector_id: str, view: str):
    """Approximate connector position within a part's own view SVG (from connectorlayers/fzp)."""
    import re
    import sqlite3
    import xml.etree.ElementTree as ET

    try:
        conn = sqlite3.connect(str(config.parts_db))
        row = conn.execute(
            "SELECT cl.svgid FROM connectors c JOIN connectorlayers cl ON cl.connector_id=c.id "
            "JOIN parts p ON p.id=c.part_id WHERE p.moduleID=? AND c.connectorid=? LIMIT 1",
            (part_id, connector_id),
        ).fetchone()
        conn.close()
    except Exception:
        return None
    if not row:
        return None
    svgid = row[0]
    svg_file = _part_svg_for_view(part_id, view)
    if svg_file is None or not svg_file.is_file():
        return None
    try:
        for elem in ET.iterparse(str(svg_file)):
            pass
        root = ET.fromstring(svg_file.read_text(encoding="utf-8", errors="ignore"))
        for elem in root.iter():
            if elem.get("id") == svgid:
                x = elem.get("x") or elem.get("cx")
                y = elem.get("y") or elem.get("cy")
                if x is not None and y is not None:
                    return (float(x), float(y))
                tr = elem.get("transform")
                if tr:
                    m = re.search(r"translate\(([-\d.]+)[, ]([-\d.]+)\)", tr)
                    if m:
                        return (float(m.group(1)), float(m.group(2)))
    except Exception:
        return None
    return None


def _builtin_view_svg(project_dir: Path, manifest: dict, view: str, render_dir: Path):
    """Deterministic engineering preview: parts at real positions, wires between connectors."""
    import xml.etree.ElementTree as ET

    elements: list[tuple[float, float, str, str, str]] = []
    connector_pos: dict[tuple[str, str], tuple[float, float]] = {}
    max_x = 200.0
    max_y = 200.0
    for p in manifest["parts"]:
        svg_file = _part_svg_for_view(p["part_id"], view)
        if svg_file is None:
            continue
        elements.append((p["x"], p["y"], p["instance_id"], p["title"], str(svg_file)))
        max_x = max(max_x, p["x"] + 900)
        max_y = max(max_y, p["y"] + 900)

    if not elements:
        return None

    # resolve connector endpoints (approximate, from part SVG geometry)
    for c in manifest["connections"]:
        for inst_key, conn_key in (("from_instance", "from_connector"), ("to_instance", "to_connector")):
            inst_id = c[inst_key]
            conn_id = c[conn_key]
            for p in manifest["parts"]:
                if p["instance_id"] == inst_id:
                    pos = _connector_position(p["part_id"], conn_id, view)
                    if pos:
                        connector_pos[(inst_id, conn_id)] = (p["x"] + pos[0], p["y"] + pos[1])
                    break

    out_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(max_x)}" height="{int(max_y)}">',
        '<desc>engine: builtin-engineering-preview; precision: approximate; connections: labeled-wires</desc>',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for x, y, inst_id, title, svg_path in elements:
        try:
            root = ET.fromstring(Path(svg_path).read_text(encoding="utf-8", errors="ignore"))
            vb = root.get("viewBox")
            wa, ha = 700.0, 500.0
            if vb:
                pvb = vb.split()
                if len(pvb) == 4:
                    wa, ha = float(pvb[2]), float(pvb[3])
            import re as _re

            inner = _re.sub(r"^<\?xml[^>]*\?>", "", ET.tostring(root, encoding="unicode"))
            out_lines.append(f'<g transform="translate({x},{y})"><svg width="{wa}" height="{ha}" viewBox="0 0 {wa} {ha}">{inner}</svg></g>')
        except Exception:
            continue

    # connector markers + wires
    for c in manifest["connections"]:
        a = connector_pos.get((c["from_instance"], c["from_connector"]))
        b = connector_pos.get((c["to_instance"], c["to_connector"]))
        for (p_inst, p_conn), pt in (
            ((c["from_instance"], c["from_connector"]), a),
            ((c["to_instance"], c["to_connector"]), b),
        ):
            if pt:
                out_lines.append(f'<circle cx="{pt[0]}" cy="{pt[1]}" r="4" fill="#c33"/>')
                out_lines.append(f'<text x="{pt[0] + 5}" y="{pt[1] - 5}" font-size="10" fill="#333">{p_inst}:{p_conn}</text>')
        if a and b:
            mx = (a[0] + b[0]) / 2
            out_lines.append(
                f'<polyline points="{a[0]},{a[1]} {mx},{a[1]} {mx},{b[1]} {b[0]},{b[1]}" fill="none" stroke="#c31" stroke-width="3"/>')
        else:
            # fallback marker line across instance origins (labeled as approximate)
            for p1 in manifest["parts"]:
                if p1["instance_id"] == c["from_instance"]:
                    for p2 in manifest["parts"]:
                        if p2["instance_id"] == c["to_instance"]:
                            out_lines.append(
                                f'<line x1="{p1["x"] + 350}" y1="{p1["y"] + 250}" x2="{p2["x"] + 350}" y2="{p2["y"] + 250}" stroke="#c31" stroke-width="3" stroke-dasharray="6,4"/>')
    out_lines.append("</svg>")
    out_path = render_dir / f"circuit_{view}.svg"
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    return out_path


def _run_fritzing_export(exe: Path, profile: Path, folder: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.Popen(
        [str(exe), "-f", str(profile), "-svg", str(folder)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    stop = threading.Event()
    watchdog = threading.Thread(target=_dismiss_dialogs, args=(proc, stop), daemon=True)
    watchdog.start()
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        raise McpError("RENDER_FAILED", f"Fritzing render timed out after {timeout}s.")
    finally:
        stop.set()
        try:
            watchdog.join(timeout=2)
        except Exception:
            pass


def render_project(project_dir: Path, manifest: dict, view: str = "all", timeout: int = 90) -> dict:
    fzz = manifest.get("artifacts", {}).get("fzz")
    # central render gate (tool layer also checks; defense in depth)
    validation = manifest.get("validation", {})
    if manifest.get("dirty") or validation.get("stale"):
        raise McpError("PROJECT_NOT_VALIDATED", "Project changed after last validation; validate again.")
    if not validation.get("status"):
        raise McpError("PROJECT_NOT_VALIDATED", "Project has never been validated.")
    if validation.get("status") == "FAIL":
        raise McpError("RENDER_DENIED", "Validation FAILED; render denied.")
    if manifest.get("state") not in ("VALIDATED", "RENDERED", "REVIEWED", "READY_TO_SAVE"):
        raise McpError("PROJECT_NOT_VALIDATED", f"Render requires a validated project; state is {manifest.get('state')}.")
    if not fzz or not Path(fzz).is_file():
        raise McpError("RENDER_FAILED", "No .fzz artifact yet; save the project first.")
    exe = config.fritzing_exe
    if not exe.is_file():
        raise McpError("RENDER_FAILED", "Fritzing executable not found.")
    prof = ensure_profile()

    render_dir = project_dir / "artifacts" / "render"
    render_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        shutil.copy2(fzz, td_p / "circuit.fzz")
        try:
            ok_code, out = _run_fritzing_export(exe, prof, td_p, timeout)
        except McpError:
            ok_code, out = -1, ""
        produced = list(td_p.glob("*.svg"))
        for svg in produced:
            shutil.copy2(svg, render_dir / svg.name)

    import logging

    logging.getLogger(__name__).debug("fritzing export (rc=%s): %s", ok_code, out)

    def _looks_blank(path: Path) -> bool:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            return True
        # Native headless export on some installs emits only the watermark
        # (blank canvas); detect that and fall back.
        return text.count("<g") < 10 or '"y":"0in"' in text and "viewBox" in text and text.count("path d=") < 20

    native_blank = False
    if produced and all(_looks_blank(p) for p in produced):
        native_blank = True
        for p in produced:
            try:
                (render_dir / p.name).unlink()
            except OSError:
                pass
        produced = []

    if not produced:
        # Deterministic fallback: composite per-view part SVGs ourselves.
        engine = "builtin-engineering-preview:native_blank" if native_blank else "builtin-engineering-preview"
        produced = []
        for view in ("breadboard", "schematic", "pcb"):
            try:
                out = _builtin_view_svg(project_dir, manifest, view, render_dir)
                if out:
                    produced.append(out)
            except Exception:
                continue
        if not produced:
            raise McpError(
                "RENDER_FAILED",
                "Fritzing export did not produce output and the built-in composer failed.",
                suggestion="Verify circuit.fzz opens in Fritzing.",
            )
    else:
        engine = "fritzing-native"

    result = {
        "status": "ok",
        "engine": engine,
        "precision": ("approximate" if engine.startswith("builtin") else "native"),
        "native_fritzing_export": engine == "fritzing-native",
        "electrical_authority": "project-manifest",
        "visual_authority": ("fritzing" if engine == "fritzing-native" else "approximate"),
        "view": view,
        "svgs": [str(render_dir / p.name) for p in produced],
        "render_dir": str(render_dir),
    }
    manifest.setdefault("artifacts", {})["render"] = result
    return result
