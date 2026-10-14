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
    price_exp = np.array(p.v("export_price_monthly"))[month - 1] / 1000 * p.v("omr_usd")

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
    m.comfort_slack = pyo.Var(m.T, within=pyo.NonNegativeReals)
    m.q_heat = pyo.Var(m.T, within=pyo.NonNegativeReals)
    if fid["building"] == 0:
        qc, _ = bld.simulate_periodic(T_ext, q_air, q_mass, block, T_set=t_set)
        m.q_load = pyo.Param(m.T, initialize=dict(enumerate(qc / 1e3 * nv)))
        m.comfort_slack.fix(0)
        m.q_heat.fix(0)
    else:
        z = bld.zone()
        a_i, a_m = z["C_i"] / bld.DT, z["C_m"] / bld.DT
        # in cool hours the unconditioned villa floats below the band (there is no heating): the lower
        # comfort bound is then the free-running temperature, computed without any cooling
        _, ti_free = bld.simulate_periodic(T_ext, q_air, q_mass, block, T_set=60.0)
        lb = np.minimum(band[0], ti_free)
        m.Ti = pyo.Var(m.T, bounds=(10.0, 40.0))
        m.Tm = pyo.Var(m.T, bounds=(5.0, 50.0))
        m.q_load = pyo.Var(m.T, within=pyo.NonNegativeReals)
        qv = lambda m, t: m.q_load[t] * 1e3 / nv
        m.air = pyo.Constraint(m.T, rule=lambda m, t: a_i * (m.Ti[t] - m.Ti[prev[t]]) == z["H_ie"] * (T_ext[t] - m.Ti[t])
                               + z["H_im"] * (m.Tm[t] - m.Ti[t]) + q_air[t] - qv(m, t) + m.q_heat[t])
        m.mass = pyo.Constraint(m.T, rule=lambda m, t: a_m * (m.Tm[t] - m.Tm[prev[t]]) == z["H_im"] * (m.Ti[t] - m.Tm[t])
                                + z["H_me"] * (T_ext[t] - m.Tm[t]) + q_mass[t])
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
    tiny = sum(wt[t] * 1e-4 * m.q_heat[t] for t in T)
    m.obj = pyo.Objective(expr=m.cost_inv + m.cost_energy + m.cost_other + tiny, sense=pyo.minimize)
    m._wt, m._cop = wt, cop
    return m


def solve(m, time_limit=900, gap=0.002, threads=None, log=None):
    """HiGHS through Pyomo. MILP cases occasionally stall before a first feasible point; they are retried
    with another seed and stronger primal heuristics. Returns True if a solution was loaded."""
    import os
    threads = threads or max(1, (os.cpu_count() or 2) - 1)
    for extra in ({}, {"random_seed": 7, "mip_heuristic_effort": 0.3}, {"random_seed": 13, "mip_heuristic_effort": 0.6}):
        opt = pyo.SolverFactory("appsi_highs")
        opt.config.time_limit = time_limit
        opt.config.load_solution = True
        opt.highs_options = {"mip_rel_gap": gap, "threads": threads, **extra}
        try:
            opt.solve(m)
            return True
        except RuntimeError as e:
            if log:
                log.warning("solver did not return a solution (%s); retrying with %s", str(e)[:80], extra or "defaults")
    return False


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
