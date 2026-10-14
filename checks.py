"""Consistency checks run before the study (and on their own: python checks.py). Each one guards a
specific way the results could silently go wrong."""
import numpy as np
import pyomo.environ as pyo

import building as bld
import hub
import params as p
import weather


def check_weather(w):
    assert len(w) == 8760, f"TMY should have 8760 hours, got {len(w)}"
    assert w.index.is_monotonic_increasing and not w.index.has_duplicates, "TMY index not clean"
    assert 5 < w.T_ext.min() and w.T_ext.max() < 50, "outdoor temperature out of range for Muscat"
    ghi = w.ghi.sum() / 1e3
    assert 1900 < ghi < 2500, f"annual GHI {ghi:.0f} kWh/m2 is not plausible for Muscat"
    return f"weather ok: {len(w)} h, T {w.T_ext.min():.1f}-{w.T_ext.max():.1f} C, GHI {ghi:.0f} kWh/m2"


def check_pv(pv_y):
    y0, y1 = pv_y["P0"].sum(), pv_y["P1"].sum()
    assert 1600 < y1 < 2200, f"specific yield {y1:.0f} kWh/kWp is not plausible"
    assert 0.85 < y1 / y0 < 0.97, "temperature loss outside the expected 3-15 % in Muscat"
    return f"pv ok: {y0:.0f} kWh/kWp without and {y1:.0f} with temperature effects"


def check_calibration():
    f = bld.cooled_fraction()
    assert 0.2 < f < 1.0, f"calibrated cooled fraction {f:.2f} is not plausible"
    return f"villa calibration ok: cooled fraction {f:.2f}"


def check_building_in_optimisation(rw, pv):
    """The 2R2C equations inside the optimisation must reproduce the thermostat simulation: with the
    cooling fixed to the simulated load, the optimised indoor temperature must follow the simulated one."""
    lo = {c: 0 for c in hub.default_fid(0)}
    hour = rw.index.hour.values
    qa, qm, _ = bld.gains(rw, hour)
    qc, ti_sim = bld.simulate_periodic(rw.T_ext.values, qa, qm, rw.block.values, T_set=24.0)
    m = hub.build(rw, {**lo, "building": 1}, pv, sizes={"electrolyser": 50.0}, band=(10.0, 40.0))
    for t in m.T:
        m.q_load[t].fix(qc[t] / 1e3 * bld.N_VILLAS)
    assert hub.solve(m), "check model did not solve"
    ti = np.array([pyo.value(m.Ti[t]) for t in m.T])
    err = np.abs(ti - ti_sim)
    cooled = qc > 0
    assert np.percentile(err[cooled], 99) < 0.1, f"indoor temperature differs by up to {err[cooled].max():.2f} K"
    return (f"building model ok: optimisation follows the simulation within {np.percentile(err[cooled], 99):.3f} K "
            f"(99th percentile, cooled hours)")


def check_balance(m):
    """Electricity balance residual of a solved model."""
    res = max(abs(pyo.value(m.p_pv[t] + m.p_imp[t] + m.b_dis[t] - m.p_exp[t] - m.b_ch[t] - m.p_chiller[t] - m.p_el[t]))
              for t in m.T)
    assert res < 1e-3, f"electricity balance residual {res:.2e} kW"
    return f"energy balance ok (max residual {res:.1e} kW)"


def check_representative_weeks(w, rw, pv_full, pv_rw):
    """Simple-model cost on the representative weeks against the full year."""
    lo = hub.default_fid(0)
    mf = hub.build(w, lo, pv_full)
    mr = hub.build(rw, lo, pv_rw)
    assert hub.solve(mf) and hub.solve(mr)
    cf, cr = hub.summary(mf)["total_cost"], hub.summary(mr)["total_cost"]
    assert abs(cr / cf - 1) < 0.03, f"representative weeks differ from the full year by {100 * (cr / cf - 1):.1f} %"
    return f"representative weeks ok: {100 * (cr / cf - 1):+.2f} % against the full year", check_balance(mr)


if __name__ == "__main__":
    import experiments
    w, rw, pv = experiments.inputs()
    pv_y = {"P0": weather.pv_per_kwp(w, "P0"), "P1": weather.pv_per_kwp(w, "P1")}
    for msg in (check_weather(w), check_pv(pv_y), check_calibration(), check_building_in_optimisation(rw, pv),
                *check_representative_weeks(w, rw, pv_y, pv)):
        print(msg)
