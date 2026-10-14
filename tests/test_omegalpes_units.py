"""Tests for the OMEGAlpes extension units (run in the OMEGAlpes environment: pytest tests/)."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("omegalpes")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omegalpes.energy.energy_nodes import EnergyNode  # noqa: E402
from omegalpes.energy.units.consumption_units import FixedConsumptionUnit, VariableConsumptionUnit  # noqa: E402
from omegalpes.energy.units.conversion_units import HeatPump  # noqa: E402
from omegalpes.energy.units.production_units import FixedProductionUnit, VariableProductionUnit  # noqa: E402
from omegalpes.general.optimisation.model import OptimisationModel  # noqa: E402
from omegalpes.general.time import TimeUnit  # noqa: E402

from omegalpes_ext import AirCooledChiller, PEMElectrolyser, carnot_cop  # noqa: E402

T_EXT = [28, 31, 35, 39, 42, 44, 41, 36]
LOAD = [400, 500, 650, 800, 900, 950, 850, 600]           # kW of heat removed from the chilled-water loop


def vals(q):
    v = q.value
    return [v[k] for k in sorted(v)] if isinstance(v, dict) else list(v)


def chiller_system(chiller_factory):
    time = TimeUnit(periods=len(LOAD), dt=1)
    grid = VariableProductionUnit(time, "grid", energy_type="Electrical", operating_cost=[1.0] * len(LOAD))
    grid.minimize_operating_cost()
    villas = FixedProductionUnit(time, "villas", p=LOAD, energy_type="Thermal")
    amb = VariableConsumptionUnit(time, "amb", energy_type="Thermal")
    ch = chiller_factory(time)
    cold, elec_units = (ch.cold_unit, ch.elec_consumption_unit) if isinstance(ch, AirCooledChiller) else \
        (ch.thermal_consumption_unit, ch.elec_consumption_unit)
    reject = ch.reject_unit if isinstance(ch, AirCooledChiller) else ch.thermal_production_unit
    n1 = EnergyNode(time, "loop", energy_type="Thermal"); n1.connect_units(villas, cold)
    n2 = EnergyNode(time, "el", energy_type="Electrical"); n2.connect_units(grid, elec_units)
    n3 = EnergyNode(time, "amb_n", energy_type="Thermal"); n3.connect_units(reject, amb)
    m = OptimisationModel(time, "t"); m.add_nodes(n1, n2, n3); m.solve_and_update()
    assert m.status == 1, "model not solved to optimality"
    return ch, vals(elec_units.p), vals(reject.p)


def test_carnot_cop_anchored_and_falling():
    c = carnot_cop([25, 35, 46], cop_rated=2.96)
    assert c[1] == pytest.approx(2.96)
    assert c[0] > c[1] > c[2]


def test_chiller_time_varying_cop_energy_balance():
    cop = carnot_cop(T_EXT)
    ch, elec, rej = chiller_system(lambda t: AirCooledChiller(t, "chiller", cop=cop))
    for k, q in enumerate(LOAD):
        assert elec[k] == pytest.approx(q / cop[k], rel=1e-6)
        assert rej[k] == pytest.approx(q + elec[k], rel=1e-6)


def test_chiller_constant_cop_matches_builtin_heat_pump():
    _, e_new, _ = chiller_system(lambda t: AirCooledChiller(t, "chiller", cop=2.96))
    _, e_hp, _ = chiller_system(lambda t: HeatPump(t, "hp", cop=3.96))       # heating COP = cooling COP + 1
    assert e_new == pytest.approx(e_hp, rel=1e-6)


def test_chiller_rejects_bad_input():
    time = TimeUnit(periods=3, dt=1)
    with pytest.raises(IndexError):
        AirCooledChiller(time, "c", cop=[3.0, 3.0])
    with pytest.raises(ValueError):
        AirCooledChiller(time, "c", cop=[3.0, 0.0, 3.0])


def electrolyser_system(demand_kg, p_rated=100.0, min_load=0.10, price=None, tank=False):
    n = len(demand_kg)
    time = TimeUnit(periods=n, dt=1)
    grid = VariableProductionUnit(time, "grid", energy_type="Electrical", operating_cost=price or [1.0] * n)
    grid.minimize_operating_cost()
    el = PEMElectrolyser(time, "pem", p_rated=p_rated, min_load=min_load)
    dem = FixedConsumptionUnit(time, "dem", p=demand_kg, energy_type="Gas")
    n1 = EnergyNode(time, "el", energy_type="Electrical"); n1.connect_units(grid, el.elec_consumption_unit)
    units = [el.h2_production_unit, dem]
    if tank:
        from omegalpes.energy.units.storage_units import StorageUnit
        units.append(StorageUnit(time, "tank", capacity=50.0, energy_type="Gas", e_0=0.0))
    n2 = EnergyNode(time, "h2", energy_type="Gas"); n2.connect_units(*units)
    m = OptimisationModel(time, "t"); m.add_nodes(n1, n2); m.solve_and_update()
    assert m.status == 1, "model not solved to optimality"
    return el, vals(el.elec_consumption_unit.p), vals(el.on), vals(el.p_stack)


def test_electrolyser_full_load_matches_datasheet_system_energy():
    full = (100.0 * 53.2 / 56.7) / 53.2                  # kg/h at rated stack power
    el, p, on, _ = electrolyser_system([full] * 4)
    assert p == pytest.approx([100.0] * 4, rel=1e-6)    # 100 kW / full kg/h = 56.7 kWh/kg
    assert p[0] / full == pytest.approx(56.7, rel=1e-6)


def test_electrolyser_off_draws_nothing_and_aux_when_on():
    full = (100.0 * 53.2 / 56.7) / 53.2
    el, p, on, stack = electrolyser_system([0.0, 0.5 * full, 0.0])
    assert on[0] == 0 and on[2] == 0 and p[0] == pytest.approx(0) and p[2] == pytest.approx(0)
    assert on[1] == 1 and p[1] == pytest.approx(stack[1] + el.p_aux, rel=1e-6)


def test_electrolyser_minimum_load_is_respected():
    """A demand below the minimum load must be met by running above it and storing, then switching off."""
    full = (100.0 * 53.2 / 56.7) / 53.2
    el, p, on, stack = electrolyser_system([0.04 * full] * 10, tank=True)
    floor = 0.10 * (100.0 - el.p_aux)
    assert any(o == 0 for o in on), "unit never switches off"
    for o, s in zip(on, stack):
        assert (o == 0 and s == pytest.approx(0, abs=1e-6)) or s >= floor - 1e-6
