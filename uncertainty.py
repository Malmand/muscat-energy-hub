"""Uncertainty analysis: do the conclusions survive the uncertain inputs?

Every parameter with a range in params.py (costs, discount rate, chiller rating and approach, export
tariff level, import price, measured villa consumption) is sampled with a Latin hypercube (storage cost on
a log scale, since its range spans an order of magnitude). For each sample:

  simple     all simple models: optimal design
  detailed   all detailed models: optimal design (electrolyser rating taken from the simple design, as the
             rating barely moves with model detail; see step 1)
  regret     the simple design operated with detailed models, minus the detailed optimum
  thermostat detailed models but the buildings held at 25 C (no use of thermal mass)

Outputs: results/uncertainty.csv (one row per sample) and Spearman rank correlations between inputs and
the main outputs. Resumable like run_all.py.

    python uncertainty.py --n 20
"""
import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import experiments as ex
import params as p
import sizing

OUT = Path(__file__).parent / "results"
LOG_SCALE = {"tes_capex"}


def samples(n, seed=1):
    keys = [k for k, d in p.P.items() if d.get("low") is not None]
    rng = np.random.default_rng(seed)
    u = (rng.permuted(np.tile(np.arange(n), (len(keys), 1)), axis=1).T + rng.random((n, len(keys)))) / n
    rows = []
    for i in range(n):
        r = {}
        for j, k in enumerate(keys):
            lo, hi = p.P[k]["low"], p.P[k]["high"]
            r[k] = float(np.exp(np.log(lo) + u[i, j] * (np.log(hi) - np.log(lo)))) if k in LOG_SCALE else float(lo + u[i, j] * (hi - lo))
        rows.append(r)
    return keys, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(OUT / "uncertainty.log"), logging.StreamHandler(sys.stdout)])
    for noisy in ("pyomo", "pyomo.contrib.appsi", "highspy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("unc")
    w, rw, pv = ex.inputs(quick=a.quick)
    keys, rows = samples(a.n)
    path = OUT / ("uncertainty_quick.csv" if a.quick else "uncertainty.csv")
    done = pd.read_csv(path).to_dict("records") if path.exists() else []
    seen = {int(r["sample"]) for r in done}
    for i, smp in enumerate(rows):
        if i in seen:
            continue
        log.info("sample %d/%d", i + 1, a.n)
        try:
            with p.override(smp):
                _, s = sizing.optimize(rw, ex.LOW, pv, log=log, time_limit=300, gap=0.005)
                el = s["size_electrolyser"]
                sz = sizing.sizes_of(s)
                _, d = sizing.optimize(rw, ex.HIGH, pv, sizes={"electrolyser": el}, log=log, time_limit=300, gap=0.005)
                _, g = sizing.optimize(rw, ex.HIGH, pv, sizes=sz, log=log, time_limit=300, gap=0.005)
                _, th = sizing.optimize(rw, {**ex.HIGH, "building": 0}, pv, sizes={"electrolyser": el}, log=log, t_set=25.0,
                                       time_limit=300, gap=0.005)
            if not all(np.isfinite(x["total_cost"]) for x in (s, d, g, th)):
                raise RuntimeError("a case did not solve")
            row = dict(sample=i, **smp,
                       simple_cost=s["total_cost"], simple_tank=s["size_cold_storage"], simple_chiller=s["size_chiller"],
                       simple_battery=s["size_battery"],
                       detailed_cost=d["total_cost"], detailed_tank=d["size_cold_storage"],
                       detailed_chiller=d["size_chiller"], detailed_battery=d["size_battery"],
                       regret=g["total_cost"] - d["total_cost"], regret_pct=100 * (g["total_cost"] / d["total_cost"] - 1),
                       regret_unmet_cooling_MWh=g["unmet_cooling_MWh"], regret_comfort_Kh=g["comfort_Kh"],
                       regret_h2_bought_kg=g["h2_bought_kg"], regret_penalties=g["cost_other"],
                       thermostat_cost=th["total_cost"], thermostat_tank=th["size_cold_storage"],
                       flex_saving_pct=100 * (1 - d["total_cost"] / th["total_cost"]))
        except Exception as e:                          # keep going; the failed sample is logged and retried next run
            log.error("sample %d failed: %r", i, e)
            continue
        done.append(row)
        pd.DataFrame(done).to_csv(path, index=False)
        log.info("  regret %.1f %% | flexibility saving %.1f %% | tank simple %.0f, detailed %.0f, thermostat %.0f kWh",
                 row["regret_pct"], row["flex_saving_pct"], row["simple_tank"], row["detailed_tank"], row["thermostat_tank"])
    df = pd.DataFrame(done)
    outs = ["regret_pct", "flex_saving_pct", "detailed_tank", "thermostat_tank", "detailed_battery"]
    corr = df[keys + outs].corr(method="spearman").loc[keys, outs]
    corr.to_csv(OUT / ("uncertainty_correlations_quick.csv" if a.quick else "uncertainty_correlations.csv"))
    log.info("summary over %d samples:\n%s", len(df), df[outs].describe(percentiles=[0.05, 0.5, 0.95]).round(2).to_string())


if __name__ == "__main__":
    main()
