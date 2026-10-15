"""Optimal sizing at a chosen level of model detail. With the detailed electrolyser model (on/off
decisions) the rating is searched in an outer loop; every other size is a decision variable."""
import math

import hub

KEYS = hub.KEYS


def run(w, fid, pv, sizes=None, el=None, gap=0.002, time_limit=900, log=None, **kw):
    m = hub.build(w, fid, pv, sizes=sizes, el_rated=el, **kw)
    ok = hub.solve(m, time_limit=time_limit, gap=gap, log=log)
    if not ok:
        if log:
            log.error("no solution for fid=%s el=%s", fid, el)
        return m, {"total_cost": math.inf}
    return m, hub.summary(m)


def optimize(w, fid, pv, sizes=None, el_start=60.0, log=None, **kw):
    """Returns (model, summary). With sizes given, only the operation is optimised."""
    if fid["electrolyser"] == 0 or (sizes and "electrolyser" in sizes):
        return run(w, fid, pv, sizes=sizes, el=(sizes or {}).get("electrolyser"), log=log, **kw)
    tried = {}

    def cost(s):
        s = max(round(float(s)), 10)  # integer kW, at least 10
        if s not in tried:
            tried[s] = run(w, fid, pv, el=s, log=log, **kw)
            if log:
                log.info("    electrolyser %4d kW -> %.0f USD/y", s, tried[s][1]["total_cost"])
        return tried[s][1]["total_cost"]

    best = max(round(el_start), 10)
    for step in (16, 8, 4, 2):        # local search; the cost is smooth and unimodal in the rating
        while True:
            cand = min([best - step, best, best + step], key=cost)
            if cand == best:
                break
            best = max(cand, 10)
    return tried[max(round(best), 10)]


def sizes_of(s):
    return {k: s[f"size_{k}"] for k in KEYS}
