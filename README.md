# Muscat Energy Hub: How Much Model Detail Does a Multi-Energy Sizing Study Need?

A cooling-led community energy hub in Muscat, Oman: 60 villas on district cooling, rooftop PV, a battery, an air-cooled chiller plant with a chilled-water tank, and a PEM electrolyser with a hydrogen tank supplying a small fuel-cell vehicle fleet. The question is methodological: **every component is modelled at two levels of detail, and the study measures which levels change the optimal design and which do not.**

| Component | Simple model | Detailed model |
|---|---|---|
| PV | irradiance x (1 - system loss) | plus cell temperature from the module NOCT and its power coefficient |
| Battery | lossless | 85 % round trip, 4 h, 5 % reserve; and a cycle-wear cost |
| Chiller | constant COP at the ASHRAE 90.1 rating point | Carnot-based COP vs outdoor temperature, anchored at the same point |
| Chilled-water tank | lossless | 90 % storage efficiency |
| Electrolyser | constant 56.7 kWh/kg, any load | stack 53.2 kWh/kg plus balance of plant whenever on, 10 % minimum load (on/off decisions, MILP) |
| Buildings | load from a thermostat simulation | 2R2C villa model inside the optimisation, comfort band (thermal mass usable as storage) |

Every device property comes from a datasheet, a standard or an agency report, and every value has its source in `params.py` (rendered in [`docs/parameters.md`](docs/parameters.md)). Scenario choices are labelled as assumptions; the uncertain costs are varied in step 3.

![Simple and detailed models](figures/fig1_model_detail.png)

*A: chiller COP, constant vs temperature-dependent, both through the ASHRAE 90.1 rating point. B: electrolyser energy per kg; balance-of-plant power drawn whenever the stack is on makes part load expensive. C: share of PV output lost to cell heating in Muscat (LONGi Hi-MO 6 datasheet coefficient).*

## Data

- **Weather:** PVGIS 5.2 typical meteorological year for Muscat (European Commission JRC), fetched by a GitHub Actions job (`.github/workflows/fetch_weather.yml`) into `data/`.
- **Villa:** geometry, construction, glazing, infiltration, set-point and internal gains of the base-case villa in *Energy saving potential for residential buildings in hot climates: the case of Oman* (Sustainable Cities and Society, 2019). Cooling the whole villa all year gives about 200 kWh/m2 of electricity, at the top of the 53-199 kWh/m2 range the same paper measured in 50 Muscat homes. `calibrate_villa.py` fits the one uncertain input, the share of the villa cooled at a time, to the measured mean of 113 kWh/m2 (result: 46 %).
- **Devices and costs:** LONGi Hi-MO 6 datasheet, Nel PEM 100 datasheet, ASHRAE 90.1, NREL ATB 2024, IRENA 2023, IEA Global Hydrogen Review 2024, US DOE hydrogen targets; tariffs from GlobalPetrolPrices (import) and the Oman PWP bulk supply tariff (export).

## Method

- **Time series:** one representative week per month (the week closest to the monthly mean temperature and irradiation), weighted to a year, each week cyclic. Checked against the full 8,760-hour year with the simple models (within 3 %, asserted in `checks.py`).
- **Optimisation:** Pyomo with HiGHS. Sizes and hourly operation are optimised together; with the detailed electrolyser the on/off decisions make the rating bilinear, so the rating is searched in an outer loop.
- **Regret:** the design found with simple models is re-run with detailed models (sizes fixed, operation re-optimised) and compared with the design optimised with the detailed models. This is the cost of having designed with the wrong level of detail.
- **Cross-check with OMEGAlpes:** the same week and simple models rebuilt in OMEGAlpes, the open-source energy-system modeller of G2Elab; storage sizes, cost and energy flows match the Pyomo model exactly (`results/crosscheck_result.json`).

## Results

All on 12 representative weeks; costs are annualised investment and O&M plus net grid cost, USD per year (`results/`).

**Detail changes the cost estimate a lot, but the design only where storage is involved.**

| Component made detailed | Optimal cost | Design change | Regret of the simple design |
|---|---|---|---|
| PV (cell temperature) | +6.6 % (8.5 % less PV energy) | PV fills the available roofs either way; tank -4 % | 15 USD/y |
| Battery (losses, wear) | none | none: a battery is never economic here, even at 200 USD/kWh | 0 |
| Chiller (COP vs temperature) | -4.5 % (cooler hours run more efficiently) | sizes within 1 % | 3 USD/y |
| Chilled-water tank (losses) | +0.8 % | tank -4 % | 0.2 kUSD/y |
| Electrolyser (minimum load, balance of plant) | +0.1 % | rating +4 %, tank +7 % | 0.1 kUSD/y |
| Buildings (thermal mass in the optimisation) | -11.8 % | **chilled-water tank -79 %**, chiller -3 % | **6.0 kUSD/y** |
| All detailed together | -8.3 % | tank 1,906 to 238 kWh | **8.3 kUSD/y (3.5 %)** |

![Which detail matters](figures/fig2_which_detail_matters.png)

*A: change in the optimal annual cost when one component is modelled in detail. B: regret, the extra cost of the design found with the simple model, operated with the detailed one. C: change in the optimal sizes.*

**The buildings are the storage.** Part of the building effect in step 1 comes from the comfort band itself. Step 2 separates it: with the same 25 C upper limit, letting indoor temperature drop to 23 C before the evening cuts the annual cost by 4.2 % and the chilled-water tank from 1,707 to 238 kWh; at 22 C the tank disappears. Held at exactly 25 C, the building model inside the optimisation gives the same cost as the thermostat simulation (within 0.4 %), which checks the two implementations against each other.

![Thermal mass](figures/fig3_thermal_mass.png)

*A: annual cost against a fixed 25 C thermostat, as the lower comfort limit is relaxed. B: optimal chilled-water tank and chiller sizes.*

**Sensitivity (step 3).** At 50 USD/kWh the chilled-water tank comes back (960 kWh, cost -1 %); at 250 USD/kWh it disappears. Battery cost between 200 and 500 USD/kWh changes nothing: with exports paid at the bulk supply tariff and cold stored in the buildings, a battery has no role.

**What this means for a sizing study.** Simple linear models are adequate for PV, chiller, battery and electrolyser *sizing* here; their detail moves the cost estimate (PV and chiller by 5-7 %) but not the design. The one simplification that costs money is treating the cooling demand as fixed: it hides the thermal mass, so the design over-sizes the chilled-water tank about eight-fold.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python calibrate_villa.py          # writes data/villa_calibration.json (seconds)
python run_all.py --quick          # installation test: two weeks, about 1-2 min
python run_all.py                  # full study: about 25 min on 2 cores
python make_figures.py
python make_params_table.py        # docs/parameters.md from params.py

# optional cross-check, in a separate environment (OMEGAlpes 0.5 needs PuLP 2 and pandas 2.2)
python crosscheck_inputs.py
python -m venv .venv-omg && .venv-omg/bin/pip install -r requirements-omegalpes.txt
.venv-omg/bin/python omegalpes_crosscheck.py
```

**Safeguards.** `run_all.py` first runs `checks.py`: weather completeness and plausibility, PV yield, the building calibration, an equation-level check that the building model inside the optimisation reproduces the stand-alone thermostat simulation, and the representative weeks against the full year. Every case is written to `results/*.csv` as soon as it finishes and a rerun skips finished cases, so an interrupted run resumes where it stopped. MILP solves that stall before finding a first solution are retried with other solver seeds. Everything is logged to `results/run.log`.

## Limitations

- Representative weeks, not the full year, for the detailed cases.
- One villa type, scaled by a calibrated cooled share; no occupant diversity.
- The chiller COP curve is thermodynamic (fixed second-law efficiency) anchored at the rating point, not a manufacturer part-load map.
- Costs are recent published averages, not Omani quotations; chilled-water storage and battery costs are varied in step 3.

## Files

```
params.py               every input with unit, status and source
weather.py              PVGIS TMY, PV models, representative weeks
building.py             2R2C villa model and thermostat simulation
calibrate_villa.py      fits the cooled share of the villa to measured Muscat data
hub.py                  Pyomo model with simple and detailed component models
sizing.py               sizing, with the outer electrolyser search
experiments.py          steps 1-3, resumable
checks.py               consistency checks
run_all.py              runs everything with logging
make_figures.py         figures
crosscheck_inputs.py, omegalpes_crosscheck.py   OMEGAlpes cross-check
```
