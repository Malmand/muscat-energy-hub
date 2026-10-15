"""New OMEGAlpes units, written against OMEGAlpes 0.5 (energy units are assemblies of production and
consumption units linked by dynamic constraints, exactly as the built-in conversion units are).

AirCooledChiller
    Electricity in, heat removed from a chilled-water loop, heat rejected to ambient.
    q_cold[t] = COP[t] * p_elec[t],   q_reject[t] = q_cold[t] + p_elec[t],   q_cold[t] <= capacity
    COP[t] may be a constant or a time series, e.g. from `carnot_cop` with the outdoor temperature, so
    the chiller gets less efficient on hot afternoons. OMEGAlpes's HeatPump only accepts a scalar COP and
    its conversion units require efficiency <= 1, which is why a dedicated unit is needed.

PEMElectrolyser
    Electricity in, hydrogen out (kg/h), with on/off decisions:
    p_stack[t] <= (P_rated - P_aux) * u[t]
    p_stack[t] >= min_load * (P_rated - P_aux) * u[t]
    p_elec[t]  = p_stack[t] + P_aux * u[t]           (balance of plant drawn whenever the unit is on)
    h2[t]      = p_stack[t] / sec_stack
    with u[t] binary and P_aux = P_rated * (1 - sec_stack / sec_system), from the datasheet's stack and
    system specific energies. At full load this gives exactly the datasheet system specific energy.
"""
from pulp import LpBinary

from omegalpes.energy.units.consumption_units import VariableConsumptionUnit
from omegalpes.energy.units.conversion_units import ConversionUnit
from omegalpes.energy.units.production_units import VariableProductionUnit
from omegalpes.general.optimisation.elements import DefinitionDynamicConstraint, Quantity, TechnicalDynamicConstraint


def carnot_cop(t_ext, cop_rated=2.96, t_rated=35.0, t_evap=2.0, approach=11.0):
    """COP of an air-cooled chiller from a fixed second-law efficiency, anchored at the rating point
    (AHRI 550/590: 35 C outdoor air). t_ext: iterable of outdoor temperatures (C)."""
    te = t_evap + 273.15

    def carnot(ta):
        return te / (ta + approach + 273.15 - te)

    eta = cop_rated / carnot(t_rated)  # second-law efficiency at the rating point
    return [eta * carnot(float(ta)) for ta in t_ext]


class AirCooledChiller(ConversionUnit):
    def __init__(self, time, name, cop, capacity=1e5, cold_energy_type="Thermal", reject_energy_type="Thermal"):
        """
        :param time: TimeUnit
        :param name: unit name
        :param cop: float, or list of length time.LEN (cooling COP, may be > 1)
        :param capacity: maximum heat removed from the chilled-water loop (kW)
        """
        cop = list(cop) if not isinstance(cop, (int, float)) else [float(cop)] * time.LEN
        if len(cop) != time.LEN:
            raise IndexError("cop must have one value per time step")
        if min(cop) <= 0:
            raise ValueError("cop must be positive")
        self.elec_consumption_unit = VariableConsumptionUnit(time, name + "_elec", energy_type="Electrical")
        self.cold_unit = VariableConsumptionUnit(time, name + "_cold", p_max=capacity, energy_type=cold_energy_type)
        self.reject_unit = VariableProductionUnit(time, name + "_reject", energy_type=reject_energy_type)
        ConversionUnit.__init__(self, time, name, prod_units=[self.reject_unit],
                                cons_units=[self.cold_unit, self.elec_consumption_unit])
        self.cop_values = cop                    # kept as data; the constraint below carries the values
        self.conversion = DefinitionDynamicConstraint(
            exp_t="{0}_p[t] == {1}[t] * {2}_p[t]".format(self.cold_unit.name, cop, self.elec_consumption_unit.name),
            t_range="for t in time.I", name="conversion", parent=self)
        self.rejection = DefinitionDynamicConstraint(
            exp_t="{0}_p[t] == {1}_p[t] + {2}_p[t]".format(self.reject_unit.name, self.cold_unit.name,
                                                          self.elec_consumption_unit.name),
            t_range="for t in time.I", name="rejection", parent=self)


class PEMElectrolyser(ConversionUnit):
    def __init__(self, time, name, p_rated, sec_stack=53.2, sec_system=56.7, min_load=0.10, h2_energy_type="Gas"):
        """
        :param p_rated: rated electrical power (kW) at full load, including balance of plant
        :param sec_stack, sec_system: specific energy of the stack and of the whole system at full load (kWh/kg)
        :param min_load: minimum stack load as a share of rated stack power
        Hydrogen output in kg/h.
        """
        if not 0 < sec_stack <= sec_system:
            raise ValueError("need 0 < sec_stack <= sec_system")
        if not 0 <= min_load < 1:
            raise ValueError("min_load must be in [0, 1)")
        self.p_rated, self.p_aux = p_rated, p_rated * (1 - sec_stack / sec_system)  # full load gives sec_system
        p_stack_max = p_rated - self.p_aux
        self.elec_consumption_unit = VariableConsumptionUnit(time, name + "_elec", p_max=p_rated, energy_type="Electrical")
        self.h2_production_unit = VariableProductionUnit(time, name + "_h2", energy_type=h2_energy_type)
        ConversionUnit.__init__(self, time, name, prod_units=[self.h2_production_unit],
                                cons_units=[self.elec_consumption_unit])
        self.p_stack = Quantity(name="p_stack", unit="kW", vlen=time.LEN, lb=0, ub=p_stack_max, parent=self)
        self.on = Quantity(name="on", vtype=LpBinary, vlen=time.LEN, parent=self)
        self.stack_max = TechnicalDynamicConstraint(
            exp_t="{0}_p_stack[t] <= {1} * {0}_on[t]".format(name, p_stack_max),
            t_range="for t in time.I", name="stack_max", parent=self)
        self.stack_min = TechnicalDynamicConstraint(
            exp_t="{0}_p_stack[t] >= {1} * {0}_on[t]".format(name, min_load * p_stack_max),
            t_range="for t in time.I", name="stack_min", parent=self)
        self.electricity = DefinitionDynamicConstraint(
            exp_t="{1}_p[t] == {0}_p_stack[t] + {2} * {0}_on[t]".format(name, self.elec_consumption_unit.name, self.p_aux),
            t_range="for t in time.I", name="electricity", parent=self)
        self.hydrogen = DefinitionDynamicConstraint(
            exp_t="{1}_p[t] == {2} * {0}_p_stack[t]".format(name, self.h2_production_unit.name, 1.0 / sec_stack),
            t_range="for t in time.I", name="hydrogen", parent=self)
