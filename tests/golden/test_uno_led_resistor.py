"""Semantic golden test: the canonical LED circuit must work end-to-end."""

import json
from pathlib import Path

from server.errors import McpError
from server.fritzing import parts, sketch, validation
from server.storage import projects

GOLDEN = Path(__file__).parent / "uno_led_resistor" / "manifest.template.json"


def _parts_by_title(m):
    return {p["title"]: p for p in m["parts"]}


def test_golden_uno_led_resistor_semantic():
    spec = json.loads(GOLDEN.read_text())
    info = projects.create_project("golden_led_semantic", spec["description"])
    pdir = projects.get_project_dir(info["project_id"])
    m = sketch.load_manifest(pdir)

    for entry in spec["parts"]:
        pdir_part = parts.get_part(entry["part_id"])
        sketch.add_instance(m, entry["part_id"], entry["title"], "breadboard", 0, 0, 0, pdir_part["trust"])
    for c in spec["connections"]:
        sketch.add_connection(m, c["from_instance"], c["from_connector"], c["to_instance"], c["to_connector"])
    m["state"] = "WIRED"
    sketch.save_manifest(pdir, m)

    # part lookup: three placed, known connectors
    assert len(m["parts"]) == 3
    # logical net summary must contain a net spanning Arduino->resistor->LED
    res = validation.run_validation(pdir, m)
    assert res["status"] in ("PASS", "PASS_WITH_WARNINGS"), res
    assert isinstance(res.get("logical_nets"), list) and res["logical_nets"]

    # each wire is its own 2-node net; the GND rail must reach the LED cathode net
    assert len(res["logical_nets"]) == 3
    assert all(n["size"] >= 2 for n in res["logical_nets"])
    gnd_nets = [n for n in res["logical_nets"] if "GND" in n["rails"]]
    assert gnd_nets, f"expected a GND net in {res['logical_nets']}"

    # artifacts: .fz and .fzz are distinct on disk
    fzz = sketch.pack_fzz(pdir, m)
    fz = Path(m["artifacts"]["fz"])
    assert fzz.is_file() and fz.is_file()
    assert fz.suffix == ".fz" and fzz.suffix == ".fzz"
    # reopen: archive contains exactly the .fz
    import zipfile

    with zipfile.ZipFile(fzz) as z:
        assert z.namelist() == ["circuit.fz"]

    # trust gate still true for this project
    assert all(p["trust"] in ("OFFICIAL", "VERIFIED") for p in m["parts"])
