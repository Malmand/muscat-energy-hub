# OMEGAlpes extension units

`omegalpes_ext/` adds two energy units to [OMEGAlpes](https://omegalpes.readthedocs.io/) 0.5, written in the same way as its built-in conversion units (an assembly of production and consumption units linked by dynamic constraints), so they connect to energy nodes like any other unit.

## AirCooledChiller

```python
from omegalpes_ext import AirCooledChiller, carnot_cop
cop = carnot_cop(t_ext, cop_rated=2.96, approach=11.0)        # one value per time step
chiller = AirCooledChiller(time, "chiller", cop=cop, capacity=1500.0)
loop_node.connect_units(villa_heat, chiller.cold_unit, cw_tank)
elec_node.connect_units(grid, chiller.elec_consumption_unit)
ambient_node.connect_units(chiller.reject_unit, ambient)
```

- `q_cold[t] = COP[t] x p_elec[t]`, `q_reject[t] = q_cold[t] + p_elec[t]`, `q_cold[t] <= capacity`.
- Why a new unit: the built-in `HeatPump` takes only a scalar COP, and the generic conversion units require an efficiency of at most 1. An air-cooled chiller in a hot climate needs a COP that changes hour by hour with the outdoor temperature.
- `carnot_cop` gives the COP from a fixed second-law efficiency, anchored at the AHRI 550/590 rating point (35 C air).

## PEMElectrolyser

```python
from omegalpes_ext import PEMElectrolyser
el = PEMElectrolyser(time, "pem", p_rated=110.0, sec_stack=53.2, sec_system=56.7, min_load=0.10)
elec_node.connect_units(grid, el.elec_consumption_unit)
h2_node.connect_units(el.h2_production_unit, h2_tank, h2_demand)
```

- Binary on/off `u[t]`; stack power between `min_load` and 100 % of the rated stack power when on, zero when off.
- Balance-of-plant power `P_aux = P_rated (1 - sec_stack / sec_system)` is drawn whenever the unit is on, so part load costs more per kg; at full load the unit reproduces the datasheet system specific energy exactly.
- Hydrogen output in kg/h. Default values from the Nel PEM 100 datasheet.

## Tests

`tests/test_omegalpes_units.py` (pytest, in the OMEGAlpes environment):

- the Carnot COP passes through the rating point and falls with temperature;
- the chiller closes its energy balance with a time-varying COP, and with a constant COP gives the same result as OMEGAlpes's own HeatPump (heating COP = cooling COP + 1);
- bad inputs (wrong length, non-positive COP) are rejected;
- the electrolyser reproduces the datasheet 56.7 kWh/kg at full load, draws nothing when off and the auxiliary power when on, and with a demand below its minimum load runs above the minimum and stores, never between zero and the minimum.

## System-level check

`omegalpes_crosscheck.py` builds one week of the Muscat hub twice in OMEGAlpes, with the built-in units (simple models) and with these units (detailed chiller and electrolyser), and compares with the Pyomo model of `hub.py`: costs, storage sizes and energy flows agree exactly in both cases (`results/crosscheck_result.json`).
