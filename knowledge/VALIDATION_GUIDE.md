# Validation Guide

`fritzing_validate_project` returns structured diagnostics grouped into stages:

- schema: manifest integrity, duplicate instances/connections.
- structure: the .fzz/.fz XML must parse.
- electrical: rail conflicts (5V vs 3V3, rail shorted to GND), missing power/ground, floating pins, orphan parts.

Status: PASS | PASS_WITH_WARNINGS | FAIL.

A project can only be saved as verified when validation is PASS or PASS_WITH_WARNINGS.
