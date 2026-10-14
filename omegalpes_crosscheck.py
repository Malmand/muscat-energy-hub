"""OMEGAlpes cross-check, part 2: the same week rebuilt in OMEGAlpes (G2Elab's open-source linear
energy-system modeller) and compared with the Pyomo model. Run in a separate environment with omegalpes,
PuLP 2.x and pandas < 3 (requirements-omegalpes.txt), after crosscheck_inputs.py.

Mapping:
  electricity node   PV (fixed profile x rating), grid import and export, battery, chiller and electrolyser
  chilled-water loop heat removed from the villas (fixed), chiller evaporator, chilled-water tank
                     (energies counted as heat taken out of the loop, so the tank sees the same balance)
  chiller            OMEGAlpes HeatPump with COP_heating = COP_cooling + 1, so the evaporator draws
                     COP_cooling x the electrical power; condenser heat goes to an ambient node
  hydrogen node      electrolyser (constant specific energy), tank, night-time demand, trucked-in backup

Two cases: simple models with OMEGAlpes's built-in units, and the detailed chiller and electrolyser with
the new units of omegalpes_ext (temperature-dependent COP; on/off with minimum load and balance of plant).
"""
import json
from pathlib import Path

from omegalpes.energy.energy_nodes import EnergyNode
from omegalpes.energy.units.consumption_units import FixedConsumptionUnit, VariableConsumptionUnit
from omegalpes.energy.units.conversion_units import HeatPump, SingleConversionUnit
from omegalpes.energy.units.production_units import FixedProductionUnit, VariableProductionUnit
from omegalpes.energy.units.storage_units import StorageUnit
from omegalpes.general.optimisation.model import OptimisationModel
from omegalpes.general.time import TimeUnit

from omegalpes_ext import AirCooledChiller, PEMElectrolyser

OUT = Path(__file__).parent / "results"
d = json.load(open(OUT / "crosscheck_input.json"))
n, wgt, fx = d["n"], d["weight"], d["fixed"]
def solve_week(detailed):
    time = TimeUnit(periods=n, dt=1)

    # electricity
    pv = FixedProductionUnit(time, "pv", p=[fx["pv"] * x for x in d["pv_per_kwp"]], energy_type="Electrical")
    imp = VariableProductionUnit(time, "grid_import", energy_type="Electrical", operating_cost=[d["import_price"] * wgt] * n)
    exp = VariableConsumptionUnit(time, "grid_export", energy_type="Electrical", operating_cost=[-x * wgt for x in d["export_price"]])
    exp.operating_cost.lb = -1e9      # OMEGAlpes bounds operating costs at zero; export revenue is a negative cost
    bat = StorageUnit(time, "battery", capacity=None, energy_type="Electrical", ef_is_e0=True)
    # cooling: heat removed from the chilled-water loop
    loads = FixedProductionUnit(time, "villa_heat", p=d["cooling_kw"], energy_type="Thermal")
    if detailed:
        chiller = AirCooledChiller(time, "chiller", cop=d["cop_series"], capacity=fx["chiller"])
        ch_cold, ch_elec, ch_rej = chiller.cold_unit, chiller.elec_consumption_unit, chiller.reject_unit
    else:
        chiller = HeatPump(time, "chiller", cop=d["cop"] + 1, pmax_in_therm=fx["chiller"])
        ch_cold, ch_elec, ch_rej = chiller.thermal_consumption_unit, chiller.elec_consumption_unit, chiller.thermal_production_unit
    tank = StorageUnit(time, "cw_tank", capacity=None, energy_type="Thermal", ef_is_e0=True)
    ambient = VariableConsumptionUnit(time, "ambient", energy_type="Thermal")
    # hydrogen
    if detailed:
        el = PEMElectrolyser(time, "electrolyser", p_rated=fx["electrolyser"], sec_stack=d["sec_stack"],
                             sec_system=d["sec"], min_load=d["min_load"])
        el_in, el_out = el.elec_consumption_unit, el.h2_production_unit
    else:
        el = SingleConversionUnit(time, "electrolyser", pmax_in=fx["electrolyser"], energy_type_in="Electrical",
                                  energy_type_out="Gas", efficiency_ratio=1 / d["sec"])
        el_in, el_out = el.consumption_unit, el.production_unit
    h2_tank = StorageUnit(time, "h2_tank", capacity=None, energy_type="Gas", ef_is_e0=True)
    h2_dem = FixedConsumptionUnit(time, "h2_demand", p=d["h2_demand"], energy_type="Gas")
    h2_buy = VariableProductionUnit(time, "h2_backup", energy_type="Gas", operating_cost=[d["h2_backup"] * wgt] * n)

    for u in (imp, exp, h2_buy):
        u.minimize_operating_cost()
    bat.minimize_capacity(weight=d["annual"]["battery"], pc_max_ratio=1.0, pd_max_ratio=1.0)
    tank.minimize_capacity(weight=d["annual"]["cold_storage"], pc_max_ratio=d["tes_rate"], pd_max_ratio=d["tes_rate"])
    h2_tank.minimize_capacity(weight=d["annual"]["h2_tank"])

    n_el = EnergyNode(time, "elec", energy_type="Electrical")
    n_el.connect_units(pv, imp, exp, bat, ch_elec, el_in)
    n_cw = EnergyNode(time, "cw_loop", energy_type="Thermal")
    n_cw.connect_units(loads, ch_cold, tank)
    n_amb = EnergyNode(time, "ambient_node", energy_type="Thermal")
    n_amb.connect_units(ch_rej, ambient)
    n_h2 = EnergyNode(time, "h2", energy_type="Gas")
    n_h2.connect_units(el_out, h2_tank, h2_dem, h2_buy)

    model = OptimisationModel(time, "muscat_week_" + ("detailed" if detailed else "simple"))
    model.add_nodes(n_el, n_cw, n_amb, n_h2)
    model.solve_and_update()
    return model, bat, tank, h2_tank, imp, exp


def results(model, bat, tank, h2_tank, imp, exp):
    val = lambda q: float(q.value) if not isinstance(q.value, dict) else sum(q.value.values())
    return dict(storage_and_operation_cost=float(model.objective.value()), battery=val(bat.capacity),
                cold_storage=val(tank.capacity), h2_tank=val(h2_tank.capacity),
                import_MWh=sum(imp.p.value.values()) * wgt / 1e3, export_MWh=sum(exp.p.value.values()) * wgt / 1e3)


out = {}
for detailed, ref in ((False, "pyomo"), (True, "pyomo_detailed")):
    res = results(*solve_week(detailed))
    out["detailed" if detailed else "simple"] = {k: dict(pyomo=d[ref][k], omegalpes=res[k]) for k in res}
json.dump(out, open(OUT / "crosscheck_result.json", "w"), indent=1)
for case, cmp in out.items():
    print(case)
    for k, v in cmp.items():
        print(f"  {k:28s} Pyomo {v['pyomo']:12.2f}  OMEGAlpes {v['omegalpes']:12.2f}")
