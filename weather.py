"""Weather and PV inputs for Muscat (23.59 N, 58.41 E) from the PVGIS typical meteorological year.

PV output is available at two levels of detail:
  P0  plane-of-array irradiance x (1 - PVGIS default system loss), no temperature effect
  P1  as P0, with cell temperature from the module NOCT and its power temperature coefficient
      (LONGi Hi-MO 6 datasheet values, see params.py)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib

import params as p

LAT, LON, TZ = 23.59, 58.41, "Asia/Muscat"
DATA = Path(__file__).parent / "data"
AZIMUTH = 180.0


def load_tmy(path=DATA / "pvgis_tmy_muscat.json"):
    d = json.load(open(path))
    df = pd.DataFrame(d["outputs"]["tmy_hourly"])
    t = pd.to_datetime(df["time(UTC)"], format="%Y%m%d:%H%M", utc=True)
    # a TMY mixes years; put every hour on one reference year so the series is continuous
    t = t.map(lambda x: x.replace(year=2019))
    df.index = t
    df = df.sort_index()
    out = pd.DataFrame({"T_ext": df["T2m"], "ghi": df["G(h)"], "dni": df["Gb(n)"], "dhi": df["Gd(h)"],
                        "wind": df["WS10m"]}, index=df.index)
    return out.tz_convert(TZ)


def pv_per_kwp(w, level="P1"):
    """Hourly AC output per kWp (kW/kWp). P0: plane-of-array irradiance x (1 - system loss).
    P1: as P0 with cell temperature from the datasheet NOCT and the datasheet power coefficient."""
    sp = pvlib.solarposition.get_solarposition(w.index, LAT, LON)
    poa = pvlib.irradiance.get_total_irradiance(p.v("pv_tilt"), AZIMUTH, sp.apparent_zenith, sp.azimuth,
                                                w.dni, w.ghi, w.dhi, albedo=0.25)["poa_global"].fillna(0).clip(lower=0)
    base = poa / 1000 * (1 - p.v("pv_system_loss"))
    if level == "P0":
        return base.values
    t_cell = w.T_ext + (p.v("pv_noct") - 20.0) / 800.0 * poa  # NOCT model: 20 degC, 800 W/m2
    return (base * (1 + p.v("pv_gamma") * (t_cell - 25.0))).clip(lower=0).values


def representative_weeks(w):
    """One week per month: the 7-day block whose daily mean temperature and irradiation are closest to
    the monthly means. Each week is weighted by days-in-month / 7 and is cyclic on its own in the model."""
    days = w.groupby(w.index.date).agg(T=("T_ext", "mean"), G=("ghi", "sum"))
    days.index = pd.to_datetime(days.index)
    parts = []
    for b, mth in enumerate(range(1, 13)):
        d = days[days.index.month == mth]
        best, err = None, np.inf
        for i in range(len(d) - 6):
            blk = d.iloc[i:i + 7]
            # normalised distance to the monthly means
            e = abs(blk["T"].mean() - d["T"].mean()) / d["T"].std() + abs(blk["G"].mean() - d["G"].mean()) / d["G"].std()
            if e < err:
                best, err = blk.index[0], e
        idx = (w.index.normalize().tz_localize(None) >= best) & (w.index.normalize().tz_localize(None) < best + pd.Timedelta(days=7))
        part = w[idx].copy()
        part["block"] = b
        part["weight"] = len(d) / 7.0  # days in month / 7
        parts.append(part)
    return pd.concat(parts)
