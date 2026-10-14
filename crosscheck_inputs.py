"""OMEGAlpes cross-check, part 1 (main environment): one contiguous representative week (July), simple
component models, the PV, chiller and electrolyser ratings fixed at the Pyomo optimum. Writes the inputs and
the Pyomo reference; omegalpes_crosscheck.py rebuilds the same problem in OMEGAlpes."""
import json
from pathlib import Path

import building as bld
import experiments as ex
import hub
import params as p

OUT = Path(__file__).parent / "results"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    w, rw, pv = ex.inputs()
    sel = (rw.block == 6).values
    wk = rw[sel].drop(columns=["block", "weight"])
    pvw = {k: v[sel] for k, v in pv.items()}
    m = hub.build(wk, ex.LOW, pvw)
    assert hub.solve(m)
    s = hub.summary(m)
    fixed = {k: s[f"size_{k}"] for k in ("pv", "chiller", "electrolyser")}
    m = hub.build(wk, ex.LOW, pvw, sizes=fixed)
    assert hub.solve(m)
    ref = hub.summary(m)
    hour, month = wk.index.hour.values, wk.index.month.values
    qa, qm, _ = bld.gains(wk, hour)
    qc, _ = bld.simulate_periodic(wk.T_ext.values, qa, qm, wk.index.hour.values * 0)
    inv_fixed = sum(hub.annual_cost(k) * fixed[k] for k in fixed)
    inp = dict(n=len(wk), weight=8760 / len(wk), fixed=fixed, pv_per_kwp=list(pvw["P0"]),
               cooling_kw=list(qc / 1e3 * bld.N_VILLAS), h2_demand=list(hub.h2_demand(hour)),
               annual={k: hub.annual_cost(k) for k in ("battery", "cold_storage", "h2_tank")},
               import_price=p.v("import_price"),
               export_price=[p.v("export_price_monthly")[mo - 1] / 1000 * p.v("omr_usd") for mo in month],
               h2_backup=p.v("h2_backup_price"), cop=p.v("chiller_cop_rated"), sec=p.v("el_sec_system"),
               tes_rate=p.v("tes_rate"),
               pyomo=dict(storage_and_operation_cost=ref["total_cost"] - inv_fixed, battery=ref["size_battery"],
                          cold_storage=ref["size_cold_storage"], h2_tank=ref["size_h2_tank"],
                          import_MWh=ref["import_MWh"], export_MWh=ref["export_MWh"]))
    (OUT / "crosscheck_input.json").write_text(json.dumps(inp))
    print(json.dumps(inp["pyomo"], indent=1), fixed)
