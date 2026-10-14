"""Writes docs/parameters.md: every input value with its unit, status and source."""
from pathlib import Path

import json
import params as p

if __name__ == "__main__":
    calib = Path(__file__).parent / "data" / "villa_calibration.json"
    if calib.exists():
        p.P["villa_cooled_fraction"]["value"] = round(json.loads(calib.read_text())["cooled_fraction"], 3)
    lines = ["# Input data\n", "Status: datasheet, standard, report, derived (computed here from cited data), assumption "
             "(scenario choice; the uncertain economic ones are varied in step 3).\n",
             "| Parameter | Value | Unit | Status | Source |", "|---|---|---|---|---|"]
    for k, d in p.P.items():
        lines.append(f"| `{k}` | {d['value']} | {d['unit']} | {d['status']} | {d['source']} |")
    out = Path(__file__).parent / "docs"
    out.mkdir(exist_ok=True)
    (out / "parameters.md").write_text("\n".join(lines) + "\n")
    print(f"{len(p.P)} parameters written to docs/parameters.md")
