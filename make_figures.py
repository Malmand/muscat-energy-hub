"""Figures from results/ (run after run_all.py)."""
from pathlib import Path

import numpy as np
import pandas as pd

import hub
import params as p
import weather
from plotstyle import C, panel, save, subplots

RES = Path(__file__).parent / "results"
FIG = Path(__file__).parent / "figures"
FIG.mkdir(exist_ok=True)
NAMES = {"pv": "PV", "battery": "Battery", "chiller": "Chiller", "cold_storage": "Chilled-water tank",
         "electrolyser": "Electrolyser", "building": "Building"}


def fig1():
    """Simple and detailed models of three components."""
    w = weather.load_tmy()
    fig, ax = subplots(1, 3, figsize=(7.4, 2.5))
    T = np.linspace(20, 46, 50)
    ax[0].plot(T, hub.chiller_cop(T, 0), color=C["black"], ls="--", lw=1, label="C0 constant")
    ax[0].plot(T, hub.chiller_cop(T, 1), color=C["blue"], lw=1.2, label="C1 Carnot-based")
    ax[0].plot([35], [p.v("chiller_cop_rated")], "o", color=C["vermillion"], ms=4, label="ASHRAE 90.1 rating")
    ax[0].set(xlabel="Outdoor temperature (°C)", ylabel="Chiller COP (-)")
    ax[0].legend(frameon=False, fontsize=6)
    x = np.linspace(0.1, 1.0, 50)
    aux = 1 - p.v("el_sec_stack") / p.v("el_sec_system")
    sec1 = (x * (1 - aux) + aux) / (x * (1 - aux) / p.v("el_sec_stack"))
    ax[1].plot(x * 100, np.full_like(x, p.v("el_sec_system")), color=C["black"], ls="--", lw=1, label="E0 constant")
    ax[1].plot(x * 100, sec1, color=C["blue"], lw=1.2, label="E1 with balance of plant")
    ax[1].set(xlabel="Electrolyser load (% of rated)", ylabel="Energy per kg H$_2$ (kWh/kg)", ylim=(50, 100))
    ax[1].legend(frameon=False, fontsize=6)
    p0, p1 = weather.pv_per_kwp(w, "P0"), weather.pv_per_kwp(w, "P1")
    mon = w.index.month
    r = pd.Series(p1).groupby(mon).sum() / pd.Series(p0).groupby(mon).sum()
    ax[2].bar(r.index, (1 - r) * 100, color=C["orange"], edgecolor="k", lw=0.4)
    ax[2].set(xlabel="Month", ylabel="PV output lost to heat (%)", xticks=range(1, 13, 2))
    for a, l in zip(ax, "ABC"):
        panel(a, l, x=-0.3)
    save(fig, FIG / "fig1_model_detail.png")


def fig2():
    d = pd.read_csv(RES / "step1_model_detail.csv").set_index("case")
    base = d.loc["all simple", "total_cost"]
    comps = list(NAMES)
    delta = [d.loc[f"detailed {c} only", "total_cost"] - base for c in comps]
    regret = [d.loc[f"simple design, detailed {c} in operation", "total_cost"] - d.loc[f"detailed {c} only", "total_cost"]
              for c in comps]
    fig, ax = subplots(1, 3, figsize=(7.6, 2.8))
    y = np.arange(len(comps))
    ax[0].barh(y, np.array(delta) / 1e3, color=C["blue"], edgecolor="k", lw=0.4)
    ax[0].set_yticks(y, [NAMES[c] for c in comps]); ax[0].invert_yaxis()
    ax[0].axvline(0, color="k", lw=0.6)
    ax[0].set_xlabel("Change in optimal annual cost\n(kUSD/y, detailed vs simple)")
    ax[1].barh(y, np.array(regret) / 1e3, color=C["vermillion"], edgecolor="k", lw=0.4)
    ax[1].set_yticks(y, []); ax[1].invert_yaxis()
    ax[1].set_xlabel("Regret of the simple design\n(kUSD/y)")
    keys = ["chiller", "cold_storage", "electrolyser"]
    wbar = 0.25
    for i, k in enumerate(keys):
        b = d.loc["all simple", f"size_{k}"]
        ch = [(d.loc[f"detailed {c} only", f"size_{k}"] - b) / max(b, 1e-9) * 100 for c in comps]
        ax[2].barh(y + (i - 1) * wbar, ch, wbar, color=[C["sky"], C["green"], C["orange"]][i], edgecolor="k", lw=0.3,
                   label=NAMES[k])
    ax[2].set_yticks(y, []); ax[2].invert_yaxis()
    ax[2].axvline(0, color="k", lw=0.6)
    ax[2].set_xlabel("Change in size (%)")
    ax[2].legend(frameon=False, fontsize=6, loc="upper left")
    for a, l in zip(ax, "ABC"):
        panel(a, l, x=-0.12 if l != "A" else -0.55)
    save(fig, FIG / "fig2_which_detail_matters.png")


def fig3():
    d = pd.read_csv(RES / "step2_flexibility.csv")
    b = d[d.case.str.startswith("building")].copy()
    b["low"] = b.case.str.extract(r"band (\d+)-").astype(float)
    b = b.sort_values("low", ascending=False)
    ref = d[d.case.str.startswith("thermostat")].iloc[0]
    fig, ax = subplots(1, 2, figsize=(6.4, 2.6))
    ax[0].plot(b.low, (b.total_cost - ref.total_cost) / 1e3, "o-", color=C["blue"], lw=1, ms=4)
    ax[0].axhline(0, color="k", lw=0.5, ls=":")
    ax[0].set(xlabel="Lower comfort limit (°C, upper 25 °C)", ylabel="Cost change (kUSD/y)")
    ax[0].invert_xaxis()
    ax[1].plot(b.low, b.size_cold_storage, "s-", color=C["orange"], lw=1, ms=4, label="Chilled-water tank (kWh)")
    ax[1].plot(b.low, b.size_chiller, "^--", color=C["green"], lw=1, ms=4, label="Chiller (kW)")
    ax[1].set(xlabel="Lower comfort limit (°C, upper 25 °C)", ylabel="Optimal size")
    ax[1].invert_xaxis()
    ax[1].legend(frameon=False, fontsize=6)
    for a, l in zip(ax, "AB"):
        panel(a, l, x=-0.25, y=1.08)
    save(fig, FIG / "fig3_thermal_mass.png")


if __name__ == "__main__":
    fig1(); fig2(); fig3()
