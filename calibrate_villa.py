"""Calibrate the one uncertain building input against measured data.

With the whole 480 m2 villa cooled to 24 C all year, the model gives about 200 kWh/m2 of electricity,
at the top of the 53-199 kWh/m2 range measured in 50 Muscat homes (mean 113). Omani villas are not cooled
everywhere at once (bedrooms at night, living rooms by day), so the cooled share of the villa is fitted
so that cooling electricity at the paper's split-unit COP of 2.6, plus lighting and equipment, matches
the measured mean. Cooling scales linearly with that share, so the fit is direct.
"""
import json
from pathlib import Path

import building as b
import params as p
import weather

OUT = Path(__file__).parent / "data" / "villa_calibration.json"

if __name__ == "__main__":
    w = weather.load_tmy()
    h = w.index.hour.values
    qa, qm, el_int = b.gains(w, h, cooled_fraction=1.0)
    qc, _ = b.simulate_setpoint(w.T_ext.values, qa, qm, cooled_fraction=1.0)
    af = p.v("villa_floor")
    e_int = el_int.sum() / 1e3                       # kWh
    e_cool_full = (qc / p.v("ac_cop_split")).sum() / 1e3
    target = p.v("villa_measured_kwh_m2") * af
    frac = (target - e_int) / e_cool_full  # cooling scales linearly with the share
    res = dict(cooled_fraction=frac, full_villa_kwh_m2=(e_cool_full + e_int) / af,
               calibrated_kwh_m2=(frac * e_cool_full + e_int) / af, lighting_equipment_kwh_m2=e_int / af,
               cooling_kwh_th_per_villa=frac * qc.sum() / 1e3, peak_cooling_kw_per_villa=frac * qc.max() / 1e3)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
