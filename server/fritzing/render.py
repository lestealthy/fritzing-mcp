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


def _builtin_view_svg(project_dir: Path, manifest: dict, view: str, render_dir: Path):
    """Deterministic per-view composite of the parts' own SVGs (fallback renderer)."""
    import xml.etree.ElementTree as ET

    parts_dir = config.parts_dir / "svg"
    elements = []
    max_x = 200.0
    max_y = 200.0
    W, H = 60.0, 40.0
    for i, p in enumerate(manifest["parts"]):
        fzp = None
        try:
            from .parts import find_part_file

            fzp = find_part_file(p["part_id"])
        except Exception:
            fzp = None
        if fzp is None:
            continue
        stem = fzp.stem
        candidates = []
        for sub in ("core", "contrib", "user", "obsolete"):
            folder = parts_dir / sub / view
            if folder.is_dir():
                exact = folder / f"{stem}_{view}.svg"
                if exact.is_file():
                    candidates.append(exact)
                else:
                    candidates.extend(
                        f for f in folder.iterdir()
                        if f.name.lower().endswith(f"_{view}.svg") and stem.lower().split("(")[0] in f.name.lower()
                    )
        if not candidates:
            continue
        elements.append((p["x"], p["y"], candidates[0]))
        max_x = max(max_x, p["x"] + 800)
        max_y = max(max_y, p["y"] + 800)

    if not elements:
        return None
    out_lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(max_x)}" height="{int(max_y)}">',
                 '<rect width="100%" height="100%" fill="white"/>']
    for x, y, svg_path in elements:
        try:
            root = ET.fromstring(svg_path.read_text(encoding="utf-8", errors="ignore"))
            vb = root.get("viewBox")
            wa, ha = 700.0, 500.0
            if vb:
                parts_vb = vb.split()
                if len(parts_vb) == 4:
                    wa, ha = float(parts_vb[2]), float(parts_vb[3])
            inner = ET.tostring(root, encoding="unicode")
            import re as _re

            inner = _re.sub(r"^<\?xml[^>]*\?>", "", inner)
            out_lines.append(f'<g transform="translate({x},{y})"><svg width="{wa}" height="{ha}" viewBox="0 0 {wa} {ha}">{inner}</svg></g>')
        except Exception:
            continue
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
        engine = "builtin-svg:native_blank" if native_blank else "builtin-svg"
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
        "view": view,
        "svgs": [str(render_dir / p.name) for p in produced],
        "render_dir": str(render_dir),
    }
    manifest.setdefault("artifacts", {})["render"] = result
    return result
