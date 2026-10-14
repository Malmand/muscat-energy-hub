# Input data

Status: datasheet, standard, report, derived (computed here from cited data), assumption (scenario choice; the uncertain economic ones are varied in step 3).

| Parameter | Value | Unit | Status | Source |
|---|---|---|---|---|
| `lat` | 23.59 | deg | report | Muscat; weather: PVGIS 5.2 TMY, EC JRC, https://re.jrc.ec.europa.eu/pvg_tools/ |
| `lon` | 58.41 | deg | report | as above |
| `pv_gamma` | -0.0029 | 1/K | datasheet | LONGi Hi-MO 6 LR5-72HTH datasheet: temp. coeff. of Pmax -0.29 %/K |
| `pv_noct` | 45.0 | C | datasheet | LONGi Hi-MO 6 LR5-72HTH datasheet: NOCT 45 C |
| `pv_system_loss` | 0.14 | - | report | PVGIS default system loss 14 % (cables, inverter, soiling, mismatch) |
| `pv_module_eff` | 0.221 | - | derived | LONGi Hi-MO 6 LR5-72HTH-570M: 570 W on 1134 x 2278 mm |
| `roof_usable` | 0.5 | - | assumption | share of each villa roof usable for PV (parapets, tanks, shading) |
| `pv_tilt` | 23.0 | deg | assumption | latitude tilt, south facing |
| `eur_usd` | 1.13 | USD/EUR | report | approximate 2025 average reference rate (ECB); used to convert EUR-2025 cost data |
| `pv_capex` | 1021.6329999999999 | USD/kW | report | PyPSA technology-data (master, commit fa9645b, 20 Aug 2026) outputs/costs_2025.csv (EUR-2025), from the Danish Energy Agency technology catalogues: 'solar-rooftop commercial' 904 EUR/kW |
| `pv_life` | 25 | y | assumption | kept at 25 y (DEA gives 37.5 y for new rooftop systems; 25 y is conservative for a hot climate) |
| `pv_om` | 0.01 | 1/y | assumption | 1 % of capex per year |
| `bat_rte` | 0.85 | - | report | NREL ATB 2024, utility-scale and commercial battery storage: round-trip efficiency 85 % |
| `bat_life` | 15 | y | report | NREL ATB 2024: 15-year lifetime |
| `bat_capex` | 363.744175 | USD/kWh | report | PyPSA technology-data (master, commit fa9645b, 20 Aug 2026) outputs/costs_2025.csv (EUR-2025), from the Danish Energy Agency technology catalogues: 'battery storage' 250 EUR/kWh plus 'battery inverter' 287 EUR/kW at 4 h |
| `bat_crate` | 0.25 | 1/h | derived | 4-hour system: power = capacity / 4 |
| `bat_soc` | (0.05, 1.0) | - | assumption | 5 % reserve |
| `bat_om` | 0.025 | 1/y | report | NREL ATB 2024: fixed O&M about 2.5 % of capex |
| `chiller_cop_rated` | 2.96 | - | standard | ASHRAE 90.1-2019 minimum full-load EER 10.1 Btu/Wh (COP 2.96) for air-cooled chillers, AHRI 550/590: 35 C air, 6.7 C water; range up to EER 11.8 (COP 3.46) of a premium air-cooled chiller (HTS) |
| `chiller_t_evap` | 2.0 | C | assumption | evaporating temperature for 6.7 C leaving chilled water |
| `chiller_approach` | 11.0 | K | report | ACHR News, Choosing the right air-cooled condenser: design TD example 20 F (11 K) |
| `chiller_capex` | 252.06141597952802 | USD/kW_th | derived | HTS, Air-cooled vs water-cooled chillers: premium 385-ton air-cooled screw chiller 591 USD/ton, equipment only; x1.5 for installation (assumption) |
| `chiller_life` | 20 | y | assumption |  |
| `tes_rte` | 0.9 | - | report | HPAC Engineering, Evaluating chilled-water storage for district cooling: storage efficiency 90 % |
| `tes_capex` | 29.653318749999997 | USD/kWh_th | derived | PyPSA technology-data (master, commit fa9645b, 20 Aug 2026) outputs/costs_2025.csv (EUR-2025), from the Danish Energy Agency technology catalogues: 'central water tank storage' 3.82 EUR/kWh at a 55 K temperature difference, rescaled to an 8 K chilled-water difference (same tank volume). Range up to the ~250 USD/kWh_th of an HPAC district-cooling example |
| `tes_rate` | 0.25 | 1/h | assumption | charge or discharge in 4 h |
| `tes_life` | 25 | y | assumption |  |
| `el_sec_system` | 56.7 | kWh/kg | datasheet | Nel PEM 100 datasheet: 5.0 kWh/Nm3 system (stack, BoS, BoP, cooling) |
| `el_sec_stack` | 53.2 | kWh/kg | datasheet | Nel PEM 100 datasheet: 4.72 kWh/Nm3 stack |
| `el_min_load` | 0.1 | - | datasheet | Nel PEM 100 datasheet: 10-100 % operating range |
| `el_capex` | 2450.0 | USD/kW | report | IEA Global Hydrogen Review 2024: installed PEM cost, non-Chinese systems, 2023 |
| `el_life` | 15 | y | assumption | stack replacement not modelled separately |
| `h2_pressure` | 30.0 | barg | datasheet | Nel PEM 100 outlet pressure 30 barg, stored without compression |
| `h2_tank_capex` | 639.2900645999999 | USD/kg | report | PyPSA technology-data (master, commit fa9645b, 20 Aug 2026) outputs/costs_2025.csv (EUR-2025), from the Danish Energy Agency technology catalogues: 'hydrogen storage tank type 1' 17 EUR/kWh_H2 (Stoeckl et al. 2021); range from the US DOE target (500) to the FY2015 status (850 USD/kg) of low-pressure stationary tanks |
| `h2_tank_life` | 25 | y | assumption |  |
| `villa_floor` | 480.0 | m2 | report | Sustainable Cities and Society 46 (2019), Energy saving potential for residential buildings in hot climates: the case of Oman. Two storeys of 240 m2 (12.5 x 19.2 m), 3.35 m storey height |
| `villa_window_ratio` | 0.15 | - | report | same paper: 15 % of gross wall area, 4 mm single tinted glass |
| `villa_infiltration` | 0.75 | 1/h | report | same paper: 0.75 ACH |
| `villa_setpoint` | 24.0 | C | report | same paper: cooling set-point 24 C |
| `villa_occupants` | 6 | - | report | same paper |
| `villa_lighting` | 5.0 | W/m2 | report | same paper |
| `villa_equipment` | 8.5 | W/m2 | report | same paper |
| `villa_measured_kwh_m2` | 113.0 | kWh/m2/y | report | same paper: mean of 50 measured Muscat homes (range 53-199) |
| `u_wall` | 2.4 | W/m2K | derived | 200 mm hollow concrete block with 15 mm plaster both sides (paper), ISO 6946 with Rsi 0.13, Rse 0.04 and block R 0.20 m2K/W (CIBSE Guide A typical value) |
| `u_roof` | 3.6 | W/m2K | derived | 150 mm concrete slab, mortar, tiles, plaster (paper), ISO 6946, no insulation |
| `u_window` | 5.8 | W/m2K | report | single glazing in an aluminium frame without thermal break, ASHRAE Fundamentals typical |
| `shgc_window` | 0.6 | - | report | single 4 mm green-tinted glass, ASHRAE Fundamentals typical |
| `villa_c_mass` | 370000.0 | J/m2K | standard | ISO 13790 class 'very heavy': 370 kJ/(m2 K) of floor area |
| `villa_c_air` | 10000.0 | J/m2K | assumption | air and furniture |
| `n_villas` | 60 | - | assumption | community size |
| `villa_cooled_fraction` | 0.461 | - | derived | share of the villa cooled at a time, calibrated in calibrate_villa.py so that annual electricity (cooling at the paper's COP 2.6, plus lighting and equipment) matches the measured mean of 113 kWh/m2; written to data/villa_calibration.json |
| `ac_cop_split` | 2.6 | - | report | same paper: split units, COP 2.6 (used only for the calibration) |
| `bat_cycles` | 6000 | cycles | assumption | typical LFP datasheet value at 80 % depth of discharge; only used at battery level S2 |
| `import_price` | 0.174 | USD/kWh | report | GlobalPetrolPrices, Oman business electricity price, June 2025 (0.067 OMR/kWh); the same source gives 0.036 USD/kWh (0.014 OMR) for subsidised households, run as a separate scenario |
| `export_bst` | {'Jan-Mar': (12, 12, 12, 12), 'Apr': (13, 13, 13, 13), 'May-Jul': (19, 45, 35, 32), 'Aug-Sep': (15, 27, 18, 17), 'Oct': (13, 13, 13, 13), 'Nov-Dec': (12, 12, 12, 12)} | OMR/MWh (off-peak, night peak, weekday day peak, weekend day peak) | report | Oman PWP Main Interconnected System bulk supply tariff 2026 (https://omanpwp.om/BST); bands: off-peak 03:00-12:59 and 16:00-21:59, night peak 22:00-02:59, day peak 13:00-15:59 (weekend Friday-Saturday). Exports under the Sahim scheme are compensated at the bulk supply tariff |
| `export_scale` | 1.0 | - | assumption | multiplier on the bulk supply tariff for exports |
| `omr_usd` | 2.6 | USD/OMR | report | fixed peg |
| `discount_rate` | 0.06 | - | assumption | real |
| `h2_demand_kg_day` | 20.0 | kg/day | assumption | small fleet of fuel-cell vehicles, refuelled 22:00-02:00 |
| `h2_backup_price` | 12.0 | USD/kg | assumption | trucked-in hydrogen |
| `unmet_cooling_penalty` | 1.0 | USD/kWh_th | assumption | only active when a fixed design is re-run |
| `comfort_penalty` | 2.0 | USD/(K h villa) | assumption | only active when a fixed design is re-run |
