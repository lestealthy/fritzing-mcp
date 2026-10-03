# Golden fixture: uno_led_resistor

Deterministic semantic fixture exercising the full engineering workflow:

- Arduino Uno Rev3
- Generic resistor
- 805 Red LED

Connections (verified against the installed `parts.db`):

| From | To | Meaning |
| --- | --- | --- |
| Arduino connector64 (D3 PWM) | Resistor connector0 | GPIO → series resistor |
| Resistor connector1 | LED connector1 (anode) | resistor → LED anode |
| LED connector0 (cathode) | Arduino connector88 (GND) | LED cathode → GND |

Expected outcomes:

- `state` reaches `WIRED`, then `VALIDATED`.
- `validation.status` is `PASS` or `PASS_WITH_WARNINGS` (missing VCC-pin warning is a
  known heuristic limitation on this library part).
- `.fz`, `.fzz`, `validation.json`, `manifest` exist and agree.
- A render can be produced (native or `builtin-engineering-preview`).

The fixture is verified *semantically*, not byte-for-byte: module IDs, connection
endpoints, artifact presence, and validator status are checked. The exact SVG and FZZ
bytes legitimately vary between machines/Fritzing versions.
