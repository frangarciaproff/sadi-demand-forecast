> Superseded in part (2026-10-29): written before SPEC v0.6. Targets, information set
> (actuals ≤ D-2 and the single D-7 reference below are outdated), data sources and the
> validity check are defined in SPEC v0.7, which wins where the two disagree.

# Method notes — open decisions for SPEC section 4

Source: Fran's method discussion (2026-10-23), with review comments marked [Review].
Status: working document. Decisions move to SPEC section 4 when closed; changes logged in DECISIONS.md.

## Context

Weather source: Open-Meteo.
- Historical Weather API (ERA5 reanalysis, 1940 →): "observed" temperature.
- Previous Runs API (fixed lead 1–7 days): archived forecasts. Most models from 2024-01; GFS 2 m
  temperature from 2021-03 (Open-Meteo documentation, checked 2026-10-23).
- Historical Forecast API (~2021 →): stores only the initial hours of each run (near-analysis).
  It is NOT a day-ahead forecast and must not be used as one.
- SMN discarded (request-based, PDF, possible charges).

Planned comparison: two models that differ only in training weather input.
- M-obs: trained on ERA5.
- M-fc: trained on Previous Runs forecasts.
Both are always evaluated with forecasts.

## Decisions to make

### Weather
- W1. Lead offset: previous_day2 (every run initialised before 10:00 ART on D-1, for all hours of D).
  previous_day1 leaks for valid hours after ~10:00 of D. Confirm in UTC (ART = UTC-3).
  - [Review] previous_dayN is a fixed-lead slice, not "latest run available at issue time". At 10:00
    ART (13:00 UTC) on D-1 the 06 UTC run of D-1 is available in production, fresher than day2.
    Either production applies the same ≥ 48 h rule as the backtest (consistent, ~20 h of information
    unused), or the latest-run-at-issue-time series is reconstructed from the Single Runs API (check C2b).
    Training/evaluating on day2 and serving the freshest run is not allowed (train/serve mismatch).
- W2. Pin one NWP model (e.g. ECMWF IFS or GFS), not best_match (model switching makes inputs
  non-stationary).
  - [Review] GFS 2 m temperature archived from 2021-03 makes GFS the candidate that gives M-fc a
    multi-year training set (see M2).
- W3. Daily aggregation: day boundaries in ART; statistics (mean, max, min); max likely matters more for T2.
- W4. City set and weights (O3): cities, weight source (population or D5 area demand share), fixed or time-varying.
- W5. Temperature features: CDD/HDD vs raw vs both; bases T_c, T_h estimated on training data only;
  changes vs D-7 (ΔCDD, ΔHDD) since the target is relative to D-7.
- W6. Source of past temperature in production (e.g. for D-7); ERA5 latency ~5 days (check C3).
  - [Review] Symmetric option: use the same archived day2 forecast for D-7 as for D. Removes the ERA5
    latency issue and any source mixing in the Δ features. ERA5 then serves only M-obs.

### Splits and M-obs vs M-fc
- M1. Test inputs are always archived forecasts (previous_day2). Observed-weather results labelled
  "oracle (upper bound)".
- M2. M-fc leakage/coverage problem. Options: (a) train M-fc on 2024, test 2025; (b) ERA5 + noise
  matched to forecast error; (c) M-fc forward test only.
  - [Review] Option (d), if C2 confirms GFS previous_day2 from 2021-03: M-fc trains on GFS day2
    2021-03 → 2023, validation 2024, test 2025; M-obs trains on ERA5 → 2023, same validation/test with
    forecast inputs. Cost: M-fc limited to variables archived since 2021 (likely temperature only, O7).
  - [Review] Against (b): forecast error is biased at extremes, autocorrelated and regime-dependent;
    i.i.d. noise underestimates heat-wave error, where the peak target matters most.
- M3. Validation period must be consistent with M2 (2023 has no archived day2 forecasts for most models).
- M4. Comparison protocol: same features except weather source; same hyperparameter search budget;
  Diebold-Mariano (HAC variance, Harvey-Leybourne-Newbold correction) on the shared test period;
  decision rule fixed before results.
- M5. Report forecast error (forecast − ERA5: MAE, bias per city, test period) as a result.

### Target and model
- T1. Target transform y_D = ln E(D) − ln E(D−7), or another reference. Reason: trees do not extrapolate.
  - [Review] D−7 may be a holiday. Robust reference: mean of the same weekday over the last k weeks
    (all ≤ D−2), holidays excluded; k chosen on validation.
- T2. Peak definition: instantaneous (D1) vs max of hourly averages (B1). One definition end to end.
  - [Review] D5 (Parte Semanal, hourly by area, 2010 →) can replace D1 as the target source: hourly
    energy gives the max-of-hourly-averages peak, identical in training, B1 comparison and forward
    scoring. D1 becomes a cross-check. Requires choosing the definitive (not provisional) weekly version.
- T3. Training loss and the functional it estimates, consistent with MAPE.
  - [Review] L1 on the log-ratio estimates the median ratio, approximately MAPE-optimal for small
    relative errors; L2 on logs estimates the geometric mean. State which and why.
- T4. Feature list frozen at R1; every feature checked against the information set (actuals ≤ D−2,
  calendar of D, weather forecast issued ≤ 10:00 ART D−1). No rolling window includes D−1.
- T5. Calendar: holiday source (national, movable, bridge days), day-before/after flags, Fourier order K.
- T6. Seeds meaningful only with bagging/feature subsampling; otherwise deterministic runs, uncertainty
  from bootstrap/CV.
- T7. Structural breaks (2020 lockdown, load shedding, tariff/subsidy changes): flag, exclude or
  indicator; list frozen at R1.

### Metrics and tests
- E1. Skill = 1 − MAE_model / MAE_B0 (proposed). S1 threshold depends on it.
- E2. Bootstrap: block length 7, B = 2000, paired resampling.
- E3. DM test: loss (absolute vs squared), HAC bandwidth, small-sample correction.
- E4. Issue-time asymmetry vs CAMMESA (~21:30 ART D−1). Decided 2026-10-23: model issues before
  CAMMESA publishes; the information gap is reported. If issue time moves, recheck W1.
- E5. Promotion gate (56-day DM): accept low power as conservative design, or lengthen the window.

## Checks before code
- C1. Open-Meteo licence and terms. DONE 2026-10-23: CC BY 4.0, attribution, free non-commercial
  ≤ 10,000 calls/day.
- C2. Previous Runs API: start date for the pinned model at Argentine coordinates; gaps; exact meaning
  of previous_day2 (init vs valid time); whether GFS previous_day2 exists from 2021-03.
  - DONE 2026-10-23 (probe at Buenos Aires, -34.61/-58.38, previous_day2, ART):
    - gfs_global (identical to gfs_seamless here): temperature_2m from 2021-03-24 21:00 to present;
      one gap 2023-12-29 21:00 → 2024-01-20 08:00 (22 days, summer). All other variables
      (relative humidity, dew point, apparent temperature, wind, cloud cover, shortwave radiation)
      from 2024-01-20.
    - ecmwf_ifs025: temperature, wind, cloud cover present on 2024-02-10, absent on 2023-06-10;
      humidity, dew point, apparent temperature, radiation absent on 2024-02-10, present on 2025-06-10
      (exact start dates not probed).
    - Consequence: option (d) of M2 is feasible for temperature only (M-fc training 2021-03-25 →
      2023-12-28). Other variables can enter M-obs (ERA5 in training) and are evaluated with GFS
      forecasts from 2024-01-20; they cannot enter M-fc before 2024. Validation 2024 lacks
      forecasts for 2024-01-01 → 2024-01-19.
    - Other cities not probed (global model; check with C5).
- C2b. Single Runs API: archive coverage (needed only for the latest-run-at-issue-time option in W1).
- C3. ERA5 latency in Open-Meteo (needed only if W6 keeps ERA5 in production).
- C4. D6 (CAMMESA programme) coverage for 2024–2025. In progress (historical download 2026-10-23).
- C5. Cities resolve to sensible grid points (coast/elevation, e.g. Mendoza).
- C6. ERA5 vs station sanity check for at least one city (FAMAF for Córdoba, optional).
- C7. Success criteria S1–S3 restated against the final split table, before any results.

## Updates 2026-10-23 (afternoon)

- C2 extended: Córdoba (-31.42/-64.18 → grid -31.45/-64.22, 394 m) has identical gfs_global coverage to
  Buenos Aires (temperature 2021-03-24 →, gap 2023-12-29 → 2024-01-20; other variables 2024-01-20 →).
  Values differ between cities (local data, not a copy).
- M4 decided (Fran): clean comparison with temperature only. M-obs and M-fc differ only in the
  temperature source. Other weather variables are evaluated separately, as an extension of M-obs.
- M2/M3 proposed resolution (Fran's direction, to confirm in SPEC section 4):
  - M-fc training: GFS previous_day2, 2021-03-25 → 2024-12-31 (gap excluded).
  - M-obs training: ERA5, start chosen on validation (window comparison) → 2024-12-31.
  - Validation: 2025 (forecast inputs complete).
  - Test: 2026-01-01 → 2026-09-30, end date fixed now; later days belong to the forward test.
  - Disclosure: 2026-01 mean daily energy (D1, 455 GWh) was computed during data inspection on
    2026-10-19. Descriptive only; no model result on 2026 has been seen.
- W4 proposal: weather at CAMMESA demand areas (D5 area codes). Candidate points: GBA (CABA);
  BAS (La Plata, Mar del Plata, Bahía Blanca); LIT (Rosario, Santa Fe); CEN (Córdoba); CUY (Mendoza,
  San Juan); NOA (Tucumán, Salta); NEA (Resistencia, Posadas); COM (Neuquén); PAT (Comodoro Rivadavia).
  Feature designs compared on validation: (A) demand-weighted national index, weights = area demand
  shares from D5 on training data only; (B) per-area temperatures as separate features.
  Area shares are computed from D5, not assumed.
- C6: email to a FAMAF contact drafted 2026-10-23 for station data (validation only).
- Test end fixed 2026-09-30 (Fran). EDA rule and threshold derivation: see DECISIONS.md 2026-10-23.
- W4 spatial design proposal [Review]: A′ = degree days (CDD/HDD) computed per CAMMESA area with
  area-specific base temperatures, then demand-weighted to two national features. B (per-area
  temperatures as separate features) proposed as non-goal (collinearity, overfitting with few years).
  Pending Fran's decision.
- Experiment budget proposal: core M-obs vs M-fc; spatial design A′ only; training window ≤ 3
  candidates; extra weather variables out of v1. About 6 configurations in total.
- Decided (Fran, 2026-10-23): v1 uses spatial design A′ and the ~6-configuration budget; deferred
  lines recorded in docs/ROADMAP.md.

## Extrapolation and records (Fran, 2026-10-23, with review)

Two ways to exceed the historical maximum, with different remedies:
- Growth: the general level rises (more users, more equipment).
- Extreme weather: inputs outside the range seen in training (e.g. 42 °C when training max is 39 °C).

Tree models predict leaf averages, so they never exceed the largest training value (no extrapolation).

Remedies, in increasing complexity:
- X1. Relative target y_D = ln E(D) − ln E(ref) (T1). Solves growth. Limit: y_D itself is bounded by
  the largest relative change seen in training.
- X2. Detrending: a simple trend fitted on training data only; trees learn deviations; the trend is
  projected forward. Alternative to X1 if the reference is too noisy.
- X3. Hybrid: piecewise-linear response on degree days (e.g. GWh per CDD) plus trees on the residual
  (calendar, interactions). The linear part extrapolates to unseen temperatures.
  - [Review] LightGBM linear_tree = True fits a linear model in every leaf on all features, so it can
    extrapolate along features where that is meaningless (e.g. day of year). The explicit hybrid
    restricts extrapolation to CDD/HDD. If linear_tree is tried: regularise (linear_lambda) and compare
    against the explicit hybrid.
  - [Review] monotone_constraints (demand non-decreasing in CDD and in HDD) prevent physically
    implausible responses where data are sparse. They do not solve extrapolation.
- X4. Out-of-range flag on forecasts (section 4). Does not fix, does not hide.

Risks:
- Linear extrapolation can overestimate: the temperature response saturates.
- Records are censored by load shedding: recorded demand is what the grid could supply. The model
  learns the underestimate; evaluation counts correct "true demand" forecasts as errors on those days.
  - [Review] D5 balance.txt has a FALLAS row (likely energy not supplied per day). If confirmed, it
    gives an objective list of censored days and an estimate of unserved energy, instead of a manual
    flag list.

EDA tasks (replace the original 2024–2025 count, which would inspect the 2026 test target):
- X-EDA1. Rolling records, per year Y = 2011 … 2025 (training + validation only): number and share of
  days with E or P above the maximum of all years < Y.
- X-EDA2. Same, for weather inputs: days with CDD (and HDD) outside the range of all years < Y, and
  days with ΔCDD vs the reference day outside the range of all years < Y (relevant for the relative
  target).
- X-EDA3. Confirm the meaning of FALLAS in D5 balance.txt; list censored days and unserved energy.

Decision rule (threshold to be fixed by Fran BEFORE running X-EDA1/2):
- If the median yearly share of out-of-range days exceeds p* (proposed p* = 5 %), the linear
  temperature component (X3) is mandatory in v1; otherwise X1 alone, with X4 and separate reporting.

Reporting (added to section 4 requirements):
- Report error separately on record days and on out-of-range days (validation; test after R2).
- Count of out-of-range days in the test period is computed from inputs only (weather), never from
  the target, until the test is evaluated once.

## Updates 2026-10-24

- Splits superseded: training → 2024-09-30, validation 2024-10-01 → 2025-09-30, test 2025-10-01 →
  2026-09-30 (SPEC 4.1). M-fc training 2021-03-25 → 2024-09-30.
- No ARIMA. Families F-tree and F-hyb; decision sequence and extremes rule in SPEC 4.3.
- Threshold p* withdrawn (replaced by the pre-registered comparison in SPEC 4.3).
- X-EDA1/2 rolling counts run on data ≤ 2025-09-30 only.
- Audit items resolved into SPEC v0.5 sections 1, 2.2, 2.3, 4, 7 (see DECISIONS 2026-10-24).
