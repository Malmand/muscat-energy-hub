"""Run the whole study: checks, then steps 1-3 of experiments.py, writing results/ and a log.

    python run_all.py --quick     # about 5-10 min: two weeks only, to test the installation
    python run_all.py             # full study on 12 representative weeks (see README for run times)

Interrupted runs resume: finished cases are read back from results/*.csv and skipped. Delete a CSV to
recompute its step. Everything printed is also written to results/run.log.
"""
import argparse
import logging
import sys
import time
import traceback
from pathlib import Path

import checks
import experiments
import weather

ROOT = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="two representative weeks only (installation test)")
    ap.add_argument("--skip-checks", action="store_true")
    ap.add_argument("--steps", default="1,2,3")
    a = ap.parse_args()
    out = ROOT / ("results_quick" if a.quick else "results")
    out.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out / "run.log"), logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("hub")
    for noisy in ("pyomo", "pyomo.contrib.appsi", "highspy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    t0 = time.time()
    try:
        w, rw, pv = experiments.inputs(quick=a.quick)
        log.info("inputs: %d hours in %d blocks", len(rw), rw.block.nunique())
        if not a.skip_checks:
            pv_y = {"P0": weather.pv_per_kwp(w, "P0"), "P1": weather.pv_per_kwp(w, "P1")}
            for msg in (checks.check_weather(w), checks.check_pv(pv_y), checks.check_calibration(),
                        checks.check_scaling(rw, pv), checks.check_building_in_optimisation(rw, pv)):
                log.info("check: %s", msg)
            if not a.quick:
                for msg in checks.check_representative_weeks(w, rw, pv_y, pv):
                    log.info("check: %s", msg)
        steps = [s.strip() for s in a.steps.split(",")]
        el = None
        if "1" in steps:
            high = experiments.step1(rw, pv, out, log)
            el = high["size_electrolyser"]
        if el is None:
            import pandas as pd
            el = float(pd.read_csv(out / "step1_model_detail.csv").set_index("case").loc["all detailed", "size_electrolyser"])
        if "2" in steps:
            experiments.step2(rw, pv, out, log, el)
        if "3" in steps:
            experiments.step3(rw, pv, out, log, el)
        log.info("done in %.1f min", (time.time() - t0) / 60)
    except Exception:
        log.error("stopped with an error after %.1f min:\n%s", (time.time() - t0) / 60, traceback.format_exc())
        log.error("finished cases are kept; fix the problem and run the same command again to resume")
        sys.exit(1)


if __name__ == "__main__":
    main()
