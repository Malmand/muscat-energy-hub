"""Two-node (2R2C) thermal model of a typical Omani villa, served by district cooling.

Geometry, construction, infiltration, set-point and internal gains follow the base-case villa of
'Energy saving potential for residential buildings in hot climates: the case of Oman' (Sustainable Cities
and Society, 2019); see params.py for every value and its source.

Nodes: indoor air and furniture (T_i, C_i) and building mass (T_m, C_m, ISO 13790 'very heavy').
Conductances: H_ie windows and infiltration (air to outdoors), H_im air to mass (ISO 13790:
9.1 W/m2K x 3.5 x floor area), H_me opaque walls and roof (mass to outdoors). Solar through windows and
internal gains reach the air node; solar absorbed on opaque surfaces reaches the mass node through
the sol-air temperature. Implicit Euler at 1 h: stable for these time constants and linear, so the same
equations run in the stand-alone simulation and inside the optimisation.
"""
import numpy as np
import pvlib

import params as p

DT = 3600.0
N_VILLAS = p.v("n_villas")
_AF = p.v("villa_floor")
_L, _W, _H = 19.2, 12.5, 3.35
_wall_gross = {"S": _L * 2 * _H, "N": _L * 2 * _H, "E": _W * 2 * _H, "W": _W * 2 * _H}
_win = {k: p.v("villa_window_ratio") * a for k, a in _wall_gross.items()}
_wall = {k: _wall_gross[k] - _win[k] for k in _wall_gross}
_ROOF = _AF / 2
_RSE = 0.04                                       # external surface resistance, ISO 6946
_ALPHA_WALL, _ALPHA_ROOF = 0.6, 0.6               # solar absorptance of light render and tiles (assumption)

VILLA = dict(
    C_i=p.v("villa_c_air") * _AF,
    C_m=p.v("villa_c_mass") * _AF,
    H_ie=sum(_win.values()) * p.v("u_window") + p.v("villa_infiltration") * _AF * _H * 1.2 * 1005 / 3600,
    H_im=9.1 * 3.5 * _AF,
    H_me=sum(_wall.values()) * p.v("u_wall") + _ROOF * p.v("u_roof"),
)


def facade_irradiance(w):
    sp = pvlib.solarposition.get_solarposition(w.index, p.v("lat"), p.v("lon"))
    out = {}
    for k, az in {"N": 0, "E": 90, "S": 180, "W": 270}.items():
        out[k] = pvlib.irradiance.get_total_irradiance(90, az, sp.apparent_zenith, sp.azimuth, w.dni, w.ghi, w.dhi,
                                                       albedo=0.3)["poa_global"].fillna(0).clip(lower=0).values
    return out


def cooled_fraction():
    """Calibrated cooled share of the villa. If the measured intensity is changed (uncertainty runs), the
    share is rescaled: cooling electricity is linear in it, lighting and equipment are not."""
    import json
    from pathlib import Path
    c = json.loads((Path(__file__).parent / "data" / "villa_calibration.json").read_text())
    target = p.v("villa_measured_kwh_m2")
    return c["cooled_fraction"] * (target - c["lighting_equipment_kwh_m2"]) / (c["calibrated_kwh_m2"] - c["lighting_equipment_kwh_m2"])


def gains(w, hour, cooled_fraction=None):
    """Gains for one villa (W): to the air node (windows, people, lights, equipment) and to the mass node.
    The third output is lighting and equipment electricity (W), always for the whole villa. Gains to the
    cooled zone are scaled by the calibrated cooled fraction of the villa."""
    phi = cooled_fraction if cooled_fraction is not None else globals()["cooled_fraction"]()
    irr = facade_irradiance(w)
    q_win = sum(_win[k] * p.v("shgc_window") * irr[k] for k in irr)
    q_opaque = (sum(_ALPHA_WALL * p.v("u_wall") * _RSE * _wall[k] * irr[k] for k in irr)
                + _ALPHA_ROOF * p.v("u_roof") * _RSE * _ROOF * w.ghi.values)
    home = np.where((hour >= 16) | (hour < 7), 1.0, 0.5)                   # occupancy profile (assumption)
    people = p.v("villa_occupants") * 75.0 * home                          # 75 W sensible per person
    lights = np.where((hour >= 18) & (hour < 24), p.v("villa_lighting") * _AF, 0.1 * p.v("villa_lighting") * _AF)
    equip = p.v("villa_equipment") * _AF * np.where((hour >= 16) & (hour < 24), 0.5, 0.25)   # use factors (assumption)
    return phi * (q_win + people + lights + equip), phi * q_opaque, (lights + equip)


def zone(cooled_fraction=None):
    """Capacities and conductances of the cooled zone (the villa scaled by the cooled fraction)."""
    phi = cooled_fraction if cooled_fraction is not None else globals()["cooled_fraction"]()
    return {k: phi * v for k, v in VILLA.items()}


def simulate_setpoint(T_ext, q_air, q_mass, T_set=24.0, T_heat=20.0, cooled_fraction=None):
    """Thermostat at T_set (cooling only): cooling power per villa (W) and indoor temperature."""
    pp = zone(cooled_fraction)
    n = len(T_ext)
    Ti, qc = np.zeros(n), np.zeros(n)
    ti, tm = T_set, T_set + 1
    a_i, a_m = pp["C_i"] / DT, pp["C_m"] / DT
    for k in range(n):
        tm_new = (a_m * tm + pp["H_im"] * T_set + pp["H_me"] * T_ext[k] + q_mass[k]) / (a_m + pp["H_im"] + pp["H_me"])
        q = a_i * (ti - T_set) + pp["H_ie"] * (T_ext[k] - T_set) + pp["H_im"] * (tm_new - T_set) + q_air[k]
        if q >= 0:
            ti_new, qc[k] = T_set, q
        else:
            A = np.array([[a_i + pp["H_ie"] + pp["H_im"], -pp["H_im"]],
                          [-pp["H_im"], a_m + pp["H_im"] + pp["H_me"]]])
            b = np.array([a_i * ti + pp["H_ie"] * T_ext[k] + q_air[k], a_m * tm + pp["H_me"] * T_ext[k] + q_mass[k]])
            ti_new, tm_new = np.linalg.solve(A, b)
            ti_new = max(ti_new, T_heat)
        ti, tm = ti_new, tm_new
        Ti[k] = ti
    return qc, Ti


def simulate_periodic(T_ext, q_air, q_mass, block, T_set=24.0, repeats=4):
    """simulate_setpoint applied to each representative block on its own, repeated until the building
    mass reaches its periodic state, so that it matches the cyclic blocks of the optimisation."""
    qc, ti = np.zeros(len(T_ext)), np.zeros(len(T_ext))
    for b in np.unique(block):
        i = np.where(block == b)[0]
        rep = lambda x: np.tile(x[i], repeats)
        q, t = simulate_setpoint(rep(T_ext), rep(q_air), rep(q_mass), T_set=T_set)
        qc[i], ti[i] = q[-len(i):], t[-len(i):]
    return qc, ti
