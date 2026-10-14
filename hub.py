"""Sizing and operation model of the community energy hub (Pyomo, hourly, representative weeks).

Carriers: electricity, district cooling (chilled water) and hydrogen. Sizes (decision variables): PV
(kWp), battery (kWh), chiller (kW cold), chilled-water storage (kWh cold), electrolyser (kW, searched in an
outer loop at level E1), hydrogen tank (kg). Objective (USD/year): annualised investment and fixed O&M,
plus grid imports minus exports, plus bought-in hydrogen and comfort penalties (both zero in optimal
designs; they keep a fixed design feasible when it is re-run with more detailed models).

Every component has a simple and a detailed model (`fid`); all numbers come from params.py.

  PV           P0 no temperature effect           P1 NOCT cell temperature, datasheet coefficient
  battery      S0 ideal (lossless)                S1 85 % round trip, 4 h, 5 % reserve   S2 S1 + cycle wear cost
  chiller      C0 constant COP (ASHRAE 90.1 rating point)   C1 Carnot-based COP vs outdoor temperature,
                                                                calibrated to the same rating point
  chilled water T0 ideal                          T1 90 % storage efficiency
  electrolyser E0 constant system energy 56.7 kWh/kg, any load
               E1 stack energy 53.2 kWh/kg plus balance-of-plant drawn whenever on, 10 % minimum load
  building     B0 load from the thermostat simulation   B1 2R2C model inside the optimisation, comfort band
"""
import numpy as np
import pyomo.environ as pyo
from pyomo.contrib.appsi.base import TerminationCondition

import building as bld
import params as p

KEYS = ["pv", "battery", "chiller", "cold_storage", "electrolyser", "h2_tank"]
_CAPEX = dict(pv="pv_capex", battery="bat_capex", chiller="chiller_capex", cold_storage="tes_capex",
              electrolyser="el_capex", h2_tank="h2_tank_capex")
_LIFE = dict(pv="pv_life", battery="bat_life", chiller="chiller_life", cold_storage="tes_life",
             electrolyser="el_life", h2_tank="h2_tank_life")
_OM = dict(pv=p.v("pv_om"), battery=p.v("bat_om"), chiller=0.03, cold_storage=0.01, electrolyser=0.03, h2_tank=0.01)


def annual_cost(k, overrides=None):
    o = overrides or {}
    capex = o.get(_CAPEX[k], p.v(_CAPEX[k]))
    r, n = p.v("discount_rate"), p.v(_LIFE[k])
    return capex * (r / (1 - (1 + r) ** -n) + _OM[k])


def h2_demand(hour):
    d = np.zeros(24)
    d[[22, 23, 0, 1]] = p.v("h2_demand_kg_day") / 4
    return d[hour]


def chiller_cop(T_ext, level):
    rated = p.v("chiller_cop_rated")
    if level == 0:
        return np.full(len(T_ext), rated)
    te = p.v("chiller_t_evap") + 273.15
    carnot = lambda ta: te / (ta + p.v("chiller_approach") + 273.15 - te)
    eta2 = rated / carnot(35.0)                    # second-law efficiency fixed at the AHRI rating point
    return eta2 * carnot(np.asarray(T_ext))


def pv_roof_limit():
    """kWp that fits on the villa roofs: roof area x usable share x module efficiency (kW per m2 at STC)."""
    return bld.N_VILLAS * p.v("villa_floor") / 2 * p.v("roof_usable") * p.v("pv_module_eff")


def default_fid(level=0):
    return dict(pv=level, battery=2 * level, chiller=level, cold_storage=level, electrolyser=level, building=level)


def build(w, fid, pv_profiles, sizes=None, el_rated=None, t_set=24.0, band=(23.0, 25.0), cost_overrides=None):
    n = len(w)
    T = range(n)
    hour = w.index.hour.values
    month = w.index.month.values
    T_ext = w.T_ext.values
    block = w["block"].values if "block" in w else np.zeros(n, int)
    wt = w["weight"].values if "weight" in w else np.full(n, 8760.0 / n)
    first = np.r_[True, block[1:] != block[:-1]]
    last_of = {b: np.where(block == b)[0][-1] for b in np.unique(block)}
    prev = np.array([last_of[block[t]] if first[t] else t - 1 for t in T])     # each block is cyclic
    nv = bld.N_VILLAS
    price_imp = p.v("import_price")
    price_exp = p.export_price(w.index)

    m = pyo.ConcreteModel()
    m.T = pyo.RangeSet(0, n - 1)
    m.size = pyo.Var(KEYS, within=pyo.NonNegativeReals)
    for k, val in (sizes or {}).items():
        m.size[k].fix(val)

    # PV and grid
    pv = pv_profiles["P1" if fid["pv"] else "P0"]
    m.p_pv = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.p_imp = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.p_exp = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.pv_lim = pyo.Constraint(m.T, rule=lambda m, t: m.p_pv[t] <= pv[t] * m.size["pv"])
    # only own PV generation can be exported (Sahim scheme); this also rules out buying from the grid to
    # resell, which would be unbounded whenever a sampled export tariff exceeds the import price
    m.exp_lim = pyo.Constraint(m.T, rule=lambda m, t: m.p_exp[t] <= m.p_pv[t])
    # PV on the villa roofs only: the export tariff is above the annualised PV cost, so without this limit
    # the optimum would be unbounded
    m.pv_roof = pyo.Constraint(expr=m.size["pv"] <= pv_roof_limit())

    # battery
    m.b_ch = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.b_dis = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.b_e = pyo.Var(m.T, within=pyo.NonNegativeReals)
    if fid["battery"] == 0:
        eff, smin, crate = 1.0, 0.0, 1.0
    else:
        eff, smin, crate = np.sqrt(p.v("bat_rte")), p.v("bat_soc")[0], p.v("bat_crate")
    m.b_bal = pyo.Constraint(m.T, rule=lambda m, t: m.b_e[t] == m.b_e[prev[t]] + eff * m.b_ch[t] - m.b_dis[t] / eff)
    m.b_lo = pyo.Constraint(m.T, rule=lambda m, t: m.b_e[t] >= smin * m.size["battery"])
    m.b_hi = pyo.Constraint(m.T, rule=lambda m, t: m.b_e[t] <= m.size["battery"])
    m.b_pc = pyo.Constraint(m.T, rule=lambda m, t: m.b_ch[t] <= crate * m.size["battery"])
    m.b_pd = pyo.Constraint(m.T, rule=lambda m, t: m.b_dis[t] <= crate * m.size["battery"])

    # buildings: cooling load of the community (kW cold)
    q_air, q_mass, _ = bld.gains(w, hour)
    m.comfort_slack = pyo.Var(m.T, bounds=(0.0, 30.0))       # K above the band
    m.q_heat = pyo.Var(m.T, bounds=(0.0, 20.0))              # kW per villa; only to keep cool winter hours feasible
    if fid["building"] == 0:
        qc, _ = bld.simulate_periodic(T_ext, q_air, q_mass, block, T_set=t_set)
        m.q_load = pyo.Param(m.T, initialize=dict(enumerate(qc / 1e3 * nv)))
        m.comfort_slack.fix(0)
        m.q_heat.fix(0)
    else:
        z = bld.zone()
        # equations written in kW per villa (W / 1e3) so the matrix is well scaled for HiGHS
        z = {k: val / 1e3 for k, val in z.items()}
        a_i, a_m = z["C_i"] / bld.DT, z["C_m"] / bld.DT
        # in cool hours the unconditioned villa floats below the band (there is no heating): the lower
        # comfort bound is then the free-running temperature, computed without any cooling
        _, ti_free = bld.simulate_periodic(T_ext, q_air, q_mass, block, T_set=60.0)
        lb = np.minimum(band[0], ti_free)
        m.Ti = pyo.Var(m.T, bounds=(10.0, 40.0))
        m.Tm = pyo.Var(m.T, bounds=(5.0, 50.0))
        m.q_load = pyo.Var(m.T, within=pyo.NonNegativeReals)
        qv = lambda m, t: m.q_load[t] / nv
        m.air = pyo.Constraint(m.T, rule=lambda m, t: a_i * (m.Ti[t] - m.Ti[prev[t]]) == z["H_ie"] * (T_ext[t] - m.Ti[t])
                               + z["H_im"] * (m.Tm[t] - m.Ti[t]) + q_air[t] / 1e3 - qv(m, t) + m.q_heat[t])
        m.mass = pyo.Constraint(m.T, rule=lambda m, t: a_m * (m.Tm[t] - m.Tm[prev[t]]) == z["H_im"] * (m.Ti[t] - m.Tm[t])
                                + z["H_me"] * (T_ext[t] - m.Tm[t]) + q_mass[t] / 1e3)
        m.c_hi = pyo.Constraint(m.T, rule=lambda m, t: m.Ti[t] <= band[1] + m.comfort_slack[t])
        m.c_lo = pyo.Constraint(m.T, rule=lambda m, t: m.Ti[t] >= lb[t])

    # chiller and chilled-water storage
    cop = chiller_cop(T_ext, fid["chiller"])
    m.q_ch = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.ch_cap = pyo.Constraint(m.T, rule=lambda m, t: m.q_ch[t] <= m.size["chiller"])
    m.s_in = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.s_out = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.s_e = pyo.Var(m.T, within=pyo.NonNegativeReals)
    se = 1.0 if fid["cold_storage"] == 0 else np.sqrt(p.v("tes_rte"))
    m.s_bal = pyo.Constraint(m.T, rule=lambda m, t: m.s_e[t] == m.s_e[prev[t]] + se * m.s_in[t] - m.s_out[t] / se)
    m.s_cap = pyo.Constraint(m.T, rule=lambda m, t: m.s_e[t] <= m.size["cold_storage"])
    m.s_rin = pyo.Constraint(m.T, rule=lambda m, t: m.s_in[t] <= p.v("tes_rate") * m.size["cold_storage"])
    m.s_rout = pyo.Constraint(m.T, rule=lambda m, t: m.s_out[t] <= p.v("tes_rate") * m.size["cold_storage"])
    m.cool_short = pyo.Var(m.T, within=pyo.NonNegativeReals)     # unmet cooling, only possible for fixed designs
    m.cold = pyo.Constraint(m.T, rule=lambda m, t: m.q_ch[t] + m.s_out[t] + m.cool_short[t] == m.q_load[t] + m.s_in[t])
    m.p_chiller = pyo.Expression(m.T, rule=lambda m, t: m.q_ch[t] / cop[t])

    # electrolyser and hydrogen
    dem = h2_demand(hour)
    m.p_el = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.h2 = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.h2_buy = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.h2_e = pyo.Var(m.T, within=pyo.NonNegativeReals)
    if fid["electrolyser"] == 0:
        m.el_cap = pyo.Constraint(m.T, rule=lambda m, t: m.p_el[t] <= m.size["electrolyser"])
        m.el_conv = pyo.Constraint(m.T, rule=lambda m, t: m.h2[t] == m.p_el[t] / p.v("el_sec_system"))
    else:
        # on/off decisions make the rating bilinear, so the rating is fixed here and searched outside
        S = el_rated
        m.size["electrolyser"].fix(S)
        aux = S * (1 - p.v("el_sec_stack") / p.v("el_sec_system"))     # balance of plant at rated output, kW
        m.u = pyo.Var(m.T, within=pyo.Binary)
        m.p_stack = pyo.Var(m.T, within=pyo.NonNegativeReals)
        m.el_on = pyo.Constraint(m.T, rule=lambda m, t: m.p_stack[t] <= (S - aux) * m.u[t])
        m.el_min = pyo.Constraint(m.T, rule=lambda m, t: m.p_stack[t] >= p.v("el_min_load") * (S - aux) * m.u[t])
        m.el_tot = pyo.Constraint(m.T, rule=lambda m, t: m.p_el[t] == m.p_stack[t] + aux * m.u[t])
        m.el_conv = pyo.Constraint(m.T, rule=lambda m, t: m.h2[t] == m.p_stack[t] / p.v("el_sec_stack"))
    m.h2_bal = pyo.Constraint(m.T, rule=lambda m, t: m.h2_e[t] == m.h2_e[prev[t]] + m.h2[t] + m.h2_buy[t] - dem[t])
    m.h2_cap = pyo.Constraint(m.T, rule=lambda m, t: m.h2_e[t] <= m.size["h2_tank"])

    # electricity balance
    m.elec = pyo.Constraint(m.T, rule=lambda m, t: m.p_pv[t] + m.p_imp[t] + m.b_dis[t] ==
                            m.p_exp[t] + m.b_ch[t] + m.p_chiller[t] + m.p_el[t])

    # objective
    wear = p.v("bat_capex") / (2 * p.v("bat_cycles") * 0.8) if fid["battery"] >= 2 else 0.0   # USD per kWh cycled
    m.cost_inv = pyo.Expression(expr=sum(annual_cost(k, cost_overrides) * m.size[k] for k in KEYS))
    m.cost_energy = pyo.Expression(expr=sum(wt[t] * (price_imp * m.p_imp[t] - price_exp[t] * m.p_exp[t]) for t in T))
    m.cost_other = pyo.Expression(expr=sum(wt[t] * (wear * (m.b_ch[t] + m.b_dis[t]) + p.v("h2_backup_price") * m.h2_buy[t]
                                                    + p.v("comfort_penalty") * nv * m.comfort_slack[t]
                                                    + p.v("unmet_cooling_penalty") * m.cool_short[t]) for t in T))
    tiny = sum(wt[t] * 0.1 * m.q_heat[t] for t in T)
    m.obj = pyo.Objective(expr=m.cost_inv + m.cost_energy + m.cost_other + tiny, sense=pyo.minimize)
    m._wt, m._cop = wt, cop
    return m


import os


def _lp(m, threads, time_limit, load=False, extra=None):
    """Solve m (no free binaries) as an LP; returns the objective or None. Tries dual simplex, then dual
    and primal simplex, then interior point, each without presolve: in a few cases HiGHS solves the presolved LP but
    its postsolve breaks down."""
    from pyomo.contrib.appsi.solvers import Highs
    for opts in ({}, {"presolve": "off"}, {"presolve": "off", "simplex_strategy": 4}, {"solver": "ipm", "presolve": "off"}):
        lp = Highs()
        lp.config.time_limit = time_limit
        lp.config.load_solution = False
        lp.highs_options = {"threads": threads, **opts, **(extra or {})}
        lp.config.stream_solver = bool(os.environ.get("HUB_DEBUG"))
        res = lp.solve(m)
        if os.environ.get("HUB_DEBUG"):
            print("LP", opts, res.termination_condition)
        if res.termination_condition == TerminationCondition.optimal:
            if load:
                lp.load_vars()
            return res.best_feasible_objective
    return None


def _with_fixed(m, bins, values, fn):
    """Fix the binaries and make them continuous, so HiGHS treats the problem as a pure LP (with fixed
    integer columns it would still go through its MIP presolve, which is what failed in the first place)."""
    for var, val in zip(bins, values):
        var.domain = pyo.Reals
        var.fix(val)
    try:
        return fn()
    finally:
        for var in bins:
            var.unfix()
            var.domain = pyo.Binary


def solve(m, time_limit=900, gap=0.002, threads=None, log=None):
    """HiGHS through Pyomo. Returns True if a solution was loaded.

    The only binaries are the electrolyser on/off decisions. HiGHS solves most cases to the requested gap.
    When it does not (time limit with a large gap, an incumbent rejected by its final feasibility check,
    or no incumbent), a rounding heuristic takes over: the LP relaxation gives a lower bound and on/off
    patterns rounded from it, each completed by an LP with the binaries fixed; the HiGHS incumbent, if
    any, is completed the same way. The best of these is loaded and its distance to the LP bound logged."""
    import os
    from pyomo.contrib.appsi.solvers import Highs
    threads = threads or max(1, min(len(os.sched_getaffinity(0)), os.cpu_count() or 2) - 1)
    bins = [v for v in m.component_data_objects(pyo.Var, active=True) if v.is_binary() and not v.fixed]
    if not bins:
        return _lp(m, threads, time_limit, load=True) is not None
    opt = Highs()
    opt.config.time_limit = time_limit
    opt.config.load_solution = False
    opt.highs_options = {"mip_rel_gap": gap, "threads": threads}
    res = opt.solve(m)
    tc = res.termination_condition
    if tc == TerminationCondition.optimal:
        opt.load_vars()
        m._solve_note = "optimal"
        return True
    patterns = []
    sol = getattr(opt, "_sol", None)
    if sol is not None and sol.value_valid:
        cols = opt._pyomo_var_to_solver_var_map
        patterns.append(("incumbent", [round(sol.col_value[cols[id(v)]]) for v in bins]))
    for v in bins:
        v.domain = pyo.UnitInterval
    try:
        bound = _lp(m, threads, time_limit, load=True)
        relaxed = [pyo.value(v) for v in bins] if bound is not None else None
    finally:
        for v in bins:
            v.domain = pyo.Binary
    if relaxed is not None:
        for thr in (0.5, 1e-6, 0.99):
            patterns.append((f"rounded at {thr:g}", [1 if x >= thr else 0 for x in relaxed]))
    best = None
    for name, pat in patterns:
        obj = _with_fixed(m, bins, pat, lambda: _lp(m, threads, time_limit))
        if obj is not None and (best is None or obj < best[1]):
            best = (name, obj, pat)
    if best is None:
        if log:
            log.warning("HiGHS returned %s and no on/off pattern could be completed", tc.name)
        return False
    _with_fixed(m, bins, best[2], lambda: _lp(m, threads, time_limit, load=True))
    gap_lp = (best[1] - bound) / abs(bound) * 100 if bound else float("nan")
    m._solve_note = f"{best[0]}, {gap_lp:.2f} % above LP bound"
    if log:
        log.warning("HiGHS returned %s; using %s pattern, %.0f, %.2f %% above the LP relaxation bound",
                    tc.name, best[0], best[1], gap_lp)
    return True


def summary(m):
    v = lambda x: float(pyo.value(x))
    wt = m._wt
    ann = lambda x: sum(wt[t] * v(x[t]) for t in m.T)
    out = {f"size_{k}": max(v(m.size[k]), 0.0) for k in KEYS}
    out.update(total_cost=v(m.cost_inv) + v(m.cost_energy) + v(m.cost_other), cost_inv=v(m.cost_inv),
               cost_energy=v(m.cost_energy), cost_other=v(m.cost_other),
               import_MWh=ann(m.p_imp) / 1e3, export_MWh=ann(m.p_exp) / 1e3, pv_MWh=ann(m.p_pv) / 1e3,
               peak_import_kW=max(v(m.p_imp[t]) for t in m.T), cooling_MWh=ann(m.q_load) / 1e3,
               chiller_elec_MWh=ann(m.p_chiller) / 1e3, electrolyser_MWh=ann(m.p_el) / 1e3,
               h2_produced_t=ann(m.h2) / 1e3, h2_bought_kg=ann(m.h2_buy), comfort_Kh=ann(m.comfort_slack),
               unmet_cooling_MWh=ann(m.cool_short) / 1e3)
    return out
