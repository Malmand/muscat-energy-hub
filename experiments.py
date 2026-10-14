"""The study, as one resumable pipeline (run through run_all.py).

Step 1  How much does the level of detail of each component model change the optimal design?
        A all components simple, and all detailed; B one component at a time made detailed;
        C regret: the all-simple design operated with detailed models, against the design optimised with
          those models (each component on its own, and all together).
Step 2  Value of the villas' thermal mass: comfort bands 25-25 to 22-25 C, all components detailed.
Step 3  Sensitivity of the main design to the uncertain economic inputs (storage cost, export tariff).
"""
import json
from pathlib import Path

import pandas as pd

import hub
import params as p
import sizing
import weather

COMP = ["pv", "battery", "chiller", "cold_storage", "electrolyser", "building"]
HIGH = {"pv": 1, "battery": 2, "chiller": 1, "cold_storage": 1, "electrolyser": 1, "building": 1}
LOW = {c: 0 for c in COMP}


def inputs(quick=False):
    w = weather.load_tmy()
    pv_y = {"P0": weather.pv_per_kwp(w, "P0"), "P1": weather.pv_per_kwp(w, "P1")}
    rw = weather.representative_weeks(w)
    if quick:                                       # January and July only, each standing for half a year
        rw = rw[rw.block.isin([0, 6])].copy()
        rw["weight"] = 8760.0 / len(rw)
    sel = w.index.isin(rw.index)
    return w, rw, {k: v[sel] for k, v in pv_y.items()}


class Runner:
    """Runs cases once, stores each result as a row, and skips cases already in the file (resume)."""

    def __init__(self, path, rw, pv, log):
        self.path, self.rw, self.pv, self.log = Path(path), rw, pv, log
        self.rows = pd.read_csv(self.path).to_dict("records") if self.path.exists() else []

    def get(self, case):
        r = [x for x in self.rows if x["case"] == case]
        return r[0] if r else None

    def run(self, case, fid, sizes=None, kind="design", el_start=60.0, **kw):
        old = self.get(case)
        if old is not None:
            self.log.info("skip (done): %s", case)
            return old
        self.log.info("run: %s", case)
        _, s = sizing.optimize(self.rw, fid, self.pv, sizes=sizes, el_start=el_start, log=self.log, **kw)
        row = dict(case=case, kind=kind, **{f"lvl_{c}": fid[c] for c in COMP}, **s)
        self.rows.append(row)
        pd.DataFrame(self.rows).to_csv(self.path, index=False)
        self.log.info("  cost %.0f USD/y | %s", s["total_cost"],
                      " ".join(f"{k} {s.get('size_' + k, float('nan')):.0f}" for k in sizing.KEYS))
        return row


def step1(rw, pv, out, log):
    r = Runner(out / "step1_model_detail.csv", rw, pv, log)
    low = r.run("all simple", LOW)
    el0 = low["size_electrolyser"]
    for c in COMP:
        r.run(f"detailed {c} only", {**LOW, c: HIGH[c]}, el_start=el0)
    sz = {k: low[f"size_{k}"] for k in sizing.KEYS}
    for c in COMP:
        r.run(f"simple design, detailed {c} in operation", {**LOW, c: HIGH[c]}, sizes=sz, kind="regret")
    high = r.run("all detailed", HIGH, el_start=el0)
    r.run("simple design, all detailed in operation", HIGH, sizes=sz, kind="regret")
    return high


def step2(rw, pv, out, log, el):
    r = Runner(out / "step2_flexibility.csv", rw, pv, log)
    r.run("thermostat 25 C (simulated load)", {**HIGH, "building": 0}, sizes={"electrolyser": el}, t_set=25.0)
    for lo in (25.0, 24.0, 23.0, 22.0):
        r.run(f"building model, band {lo:.0f}-25 C", HIGH, sizes={"electrolyser": el}, band=(lo, 25.0))


def step3(rw, pv, out, log, el):
    r = Runner(out / "step3_sensitivity.csv", rw, pv, log)
    for c in (50.0, 250.0):
        r.run(f"chilled-water storage {c:.0f} USD/kWh", HIGH, sizes={"electrolyser": el},
              cost_overrides={"tes_capex": c})
    for c in (200.0, 500.0):
        r.run(f"battery {c:.0f} USD/kWh", HIGH, sizes={"electrolyser": el}, cost_overrides={"bat_capex": c})
