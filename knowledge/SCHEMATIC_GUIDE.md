# Schematic Guide

- The schematic must communicate the electrical design, not just look pretty.
- Name nets by their rails: 5V, 3V3, GND, SDA, SCL, TX, RX, DATA.
- Every MCU power pin needs both VCC-style power and GND.
- I2C pull-ups may be flagged; treat MISSING_GROUND/MISSING_POWER warnings as human-review items.
- NEEDS_HUMAN_REVIEW does not block saving, but never hide warnings from the user.
