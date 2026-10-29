# SPEC — sadi-demand-forecast

Status: v1.0 (2026-10-29). v1.0: v2 design for the hourly curve and the daily peak (section 11).
v0.9 (2026-10-29): production design (section 7).
v0.8 (2026-10-29). v0.8: D8 summation excludes YACYHIPY; validation decision sequence
run (family F-tree, window 5 years, weather M-fc; DECISIONS 2026-10-29); O15 narrowed; S1/S2
thresholds fixed; test evaluated once (S1 passed, S2 failed; DECISIONS 2026-10-29). Re-audit:
post-hoc checks replaced F-tree by F-hyb (v1 = F-hyb, 5 years, M-fc; its test score is on a test
year already seen); T2 deferred to v2.
v0.7 (2026-10-29), frozen until backtest results. v0.7 applies the 2026-10-29 audit
(label embargo in refits, backtest start, four-week reference level, scoring caveats, S4).
v0.6: target definition and source, live data handling. Where docs/method_notes.md (written
before v0.6) disagrees with this file, this file wins. Deferred lines in docs/ROADMAP.md.
Owner: Francisco J. García Soriano. License (code only): MIT.

## 1. Problem

Forecast next-day electricity demand of Argentina's interconnected grid (SADI) and run the
forecaster in production on AWS at near-zero cost: published daily, scored automatically against
actuals and against the operator's (CAMMESA) day-ahead programme, retrained under a statistical gate.

v1 targets, for calendar day D (Argentina time, ART = UTC-03:00), on supplied energy:

  supplied energy = generation (all units) + imports − exports
                  = local demand + transmission losses + pumping   (exact; DECISIONS 2026-10-26)

- T1: daily supplied energy E(D), GWh.
- T2: daily peak P(D), MW, defined as the maximum of the 24 hourly supplied energies. Deferred to
  v2 (ROADMAP F14, DECISIONS 2026-10-29); all v1 results are T1.

Pumping is included (Fran, 2026-10-26): it is energy the system supplied, and from 2024 it is not
published separately, so excluding it would require an estimate.

Issue time: 10:00 ART on D-1, before CAMMESA publishes its programme (~21:30 ART on D-1), so the
operator's forecast cannot leak into the model.

Information set at issue time:
- Actuals published before the issue time, by archived publication timestamp. The daily report for
  day X usually appears on X+1 between 18:00 and 21:00 ART, but Friday–Sunday reports often
  appear together on Monday or Tuesday, and holidays delay them too. The newest actual is
  therefore D-3 at best and up to D-6 after weekends; the rule that runs is the timestamp, not
  the weekday. Backtests reproduce this from the archived listings (horizon ≥ 3; lag features
  lag_3 … lag_28, each the latest valid version published before the issue time).
- Calendar of D: national holidays, decreed bridge days, Holy Thursday and 24/31 December
  (package `holidays`, Argentina), plus the categories of D-1 and D+1.
- Weather forecasts from runs initialised at least 48 h before each valid hour of D (previous_day2).

## 2. Data

| ID | Source | Content | Resolution | Coverage | Role |
|----|--------|---------|-----------|----------|------|
| D1 | CAMMESA "Máximos Históricos de Energía y Potencia" (manual xlsx) | SADI gross energy (undocumented definition), instantaneous peak, GBA temperature | daily | 2007-01-01 → 2026-01-31 | Cross-check only; not a pipeline input |
| D2 | api.cammesa.com demanda-svc, ObtieneDemandaYTemperaturaRegion | actual 5-min demand today/yesterday/week before; demPrevista (SADI only, 25 hourly instantaneous points) | 5 min / hourly | current day; archived from 2026-10-19 | Archived only; definition undocumented (≈ 7 % above local demand), not a target or input |
| D3 | api.cammesa.com demanda-svc, ObtieneDemandaYTemperaturaRegionByFecha | actual demand for a date | 5 min | archived 2026-03-01 → present | Archived only; same definition as D2 |
| D5 | CAMMESA Parte Semanal (pub-svc, PARTE_SEMANAL_UNIF) | hourly demand by area and agent | hourly | 2010-01-07 → present | Area reference only (≈ local demand from 2018) |
| D6 | CAMMESA Programación Diaria (pub-svc, PROGRAMACION_DIARIA) | operator day-ahead programme: hourly net demand, losses, pumping and exports per region | hourly | 2010-01-01 → present (28 isolated missing days) | B1; programmed exports for provisional live actuals; validity check |
| D7 | CAMMESA Informe Síntesis Mensual bases (cammesaweb, scripts/get_sintesis.py) | hourly supply by technology incl. imports; hourly exports; hourly demand by type and province | hourly | 2018-01-01 →; monthly, ~1 month lag | Definitive exports; arbiter for multiple complements; independent check of D8 sums |
| D8 | CAMMESA Parte Post Operativo (pub-svc, PARTE_POST_OPERATIVO_UNIF): daily report (PARTE_POST_OPERATIVO, D+1) and complement (PARTE_POST_OPERATIVO_COMP, ~1 month later); Access database inside each zip | hourly energy per generating unit, imports included (VALORES_GENERADORES); no exports | hourly | 2010 → present; archived 2018 → | Target source (supply); provisional actuals and lag features |
| D4a | Open-Meteo Historical Weather API (ERA5) | hourly weather at demand-centre coordinates | hourly | 1940 → present | M-obs training input; oracle evaluation only |
| D4b | Open-Meteo Previous Runs API, model gfs_global, previous_day2 | 48-h-lead forecasts | hourly | temperature 2021-03-24 → (gap 2023-12-29 → 2024-01-20); other variables 2024-01-20 → | Evaluation and production input; M-fc training input |

D8 summation rule: supply = sum of VALORES_GENERADORES.ENERGIA over all units and hours (imports
are units of the table). CONTROL_VALORES_CC repeats the combined-cycle units and is never added.
Unit YACYHIPY (Paraguayan share of Yacyretá, listed from 2024-11) is not supply to the SADI and is
excluded (DECISIONS 2026-10-29).
Validated against D7 supply on 41 sample days 2018–2024: complement within 0.00–0.18 % (2018–2019)
and 0.00–0.07 % (2020 →).

### 2.1 Terms

- CAMMESA: published information may be used and derived results published (CAMMESA email,
  2026-10-24). Raw data is not redistributed (project choice); CI logs never print it.
- Open-Meteo: CC BY 4.0, attribution in README and dashboard; free non-commercial use ≤ 10,000
  calls/day.
- Collection volume: ~10 demand-API requests/day plus ~20 document listings and new attachments/day
  (~40–50 requests/day, about 12 MB/day of D8 zips), ≤ 1 request/s.

### 2.2 Version rules (leakage control)

- Definitive target (training, definitive scoring): D7 supply − D7 exports (the operator's
  consolidated balance; Fran 2026-10-28). The D8 complement is a quality check of it
  (median difference 0.003 % on training days).
- Provisional actual (live scoring, lag features): latest D8 daily report that passes the validity
  check − D6 programmed exports for that day. Marked "provisional" wherever it is shown.
- Replacement: when the D8 complement for a day is published, it replaces the provisional supply;
  when the D7 base covering the day is published, D7 exports replace programmed exports. Every
  stored value keeps its source and publication time; scores are recomputed and both provisional
  and definitive scores are kept.
- Multiple complements for one day (only matters before D7 covers the day): the complement
  closest to the latest valid daily report is used provisionally and flagged. Publication
  order is not used. The operating day of a D8 file is read from its database (table
  FECHA), not from the listing: 24 of 6,926 files sit under another day's listing entry.
- Validity check of a daily report (before it is used anywhere; O14 closed 2026-10-28):
  with provisional value v = daily-report supply − programmed exports, the report is valid
  if it has 24 hours, positive supply and |v / B1 total − 1| ≤ 0.10 (the 99th percentile of
  the same ratio with definitive values on training days, 0.0995; Fran chose 10 %). On the
  training days this rejects 44 of 2,542 daily reports and catches 16 of the 69 reports
  that are more than 2 % off their complement; the remaining report errors are not
  detectable before the complement and are carried, as published, into backtest lags.
  An invalid report is treated as missing until a later version passes.
- Features: the version available at issue time, from archived publication timestamps.
- B1: the last D6 file for target day D published before 00:00 ART on D. Re-publications on D or
  later are excluded. The "latest publication" rule never applies to D6.
- D6 files are stored by publication date; the target date is encoded in the file name
  (PDyymmdd). Empty zips, AT*, .7z and .xls attachments are skipped.

### 2.3 Known data issues

- D8 daily report vs complement: median absolute difference ≈ 0.13 %, up to ~1 % on ordinary days,
  gross errors on 3 of 41 sample days (2.2). Measured on the full archive in P1 and reported.
- D6 programmed vs D7 actual exports, as a share of the target (2018-01-01 → 2025-09-30, 2,811
  days): median 0, p90 0.26 %, p99 1.83 %, max 13.8 % (2021-11-10). This is the error of
  provisional actuals on export days.
- D8 schema change in 2025-11 (Res. 400/25: new tables and columns; GRUPO, HORA, ENERGIA not
  listed as changed). Candidate break: D8 vs D7 supply is checked across 2025-11 before use.
- D2/D3 live demand is ≈ 7 % above local demand and its ratio varies by weekday; it is not used.
- D1 quality issues (invalid temperatures, ambiguous peak times) are irrelevant once D1 is a
  cross-check only.
- Load shedding censors recorded demand on extreme days. The D5 FALLAS row is the candidate
  objective measure (to confirm in P1).
- 2019-06-16 nationwide blackout; 2020 COVID lockdown (from 2020-03-20).
- D2 demPrevista: 25 instantaneous hourly points; daily energy by trapezoidal integration
  (sum of 24 interval means), never by summing the 25 points.
- GFS is upgraded by NOAA over time; pinning the model name does not make M-fc training inputs
  homogeneous across 2021–2024. Upgrade dates are treated as candidate breaks in residual checks.

## 3. Phases

- P0 Collector — DONE (2026-10-23): Lambda + EventBridge Scheduler + private S3 (sa-east-1),
  Terraform in infra/. Historical D5/D6 (2010 →) downloaded and uploaded to S3.
- P1 Offline modelling: parsing, cleaning, reconciliation, EDA, baselines, models, backtests.
  CI (ruff, mypy, pytest) on every push; MLflow tracking (file backend, no server).
- P2 Production: daily forecast, scoring, monitoring, gated retraining, public dashboard, CD.
- P3 (conditional): see docs/ROADMAP.md.

## 4. Method

Open decisions (W, M, T, E items) and checks (C items) are tracked in docs/method_notes.md.
Fixed so far:

### 4.1 Splits (fixed 2026-10-24)

| Period | Dates | Use |
|--------|-------|-----|
| Training | start chosen on validation → 2024-09-30 | fitting |
| Validation | 2024-10-01 → 2025-09-30 | all model choices, threshold derivation |
| Test | 2025-10-01 → 2026-09-30 | evaluated once, after all choices are frozen |
| Forward test | first live forecast → | production scoring |

- Training window: sliding window of fixed length L, L ∈ {≤ 3 candidates} chosen on validation.
  Within backtests the model is refit monthly; a refit on date r uses only labels published by r:
  definitive values up to targets.definitive_available_until(r) (the Síntesis of month M is
  taken as published on day 20 of M+1), never later days. Production refits follow the same rule.
- M-fc training inputs: GFS previous_day2, 2021-03-25 → 2024-09-30 (2023-12-29 → 2024-01-20 excluded).
- EDA: unrestricted on data ≤ 2025-09-30. On the test period only data-quality checks (gaps, units,
  duplicates). Disclosures: 2026-01 mean daily energy (D1) was seen during inspection
  (descriptive only); a programmed-vs-actual export error statistic was first computed on
  2018 → 2026-09 (DECISIONS 2026-10-27) and later recomputed on ≤ 2025-09-30 (2.3); live-source
  definition checks used October 2026, after the test period. None is a model result.

### 4.2 Baselines

- B0: reference level of D = median of the available values among lag_7, lag_14, lag_21 and
  lag_28 (same weekday over the previous four weeks, versions known at the issue time, at least
  two values). The median is robust to one wrong daily report; a single reference day carries
  report errors straight into the forecast (audit 2026-10-29). The model's relative target uses
  the same reference, with the mean weather of the same reference days.
- Version mix (stated, not a defect): labels are definitive (D7); reference and lags are the
  provisional versions known at the issue time, in training, backtests and production alike.
- B1: CAMMESA day-ahead programme (D6, version rule 2.2) on the target definition, built by
  addition of its own components: DEMANDA NETA + PERDIDAS + DEMANDA BOMBEO (DEMANDA in the
  balance; exports are not part of it). Daily energy and max of the hourly values. Only the sum is
  compared: the split into net demand and losses may follow different allocation rules in each
  document. The programme may overestimate on purpose (security of supply); see 4.5.

### 4.3 Models and decision sequence (fixed 2026-10-24)

Families: (F-tree) gradient-boosted trees on a relative target; (F-hyb) linear response on
degree days (area-weighted CDD/HDD, design A′) plus gradient-boosted trees on the residual.
Decisions are taken in this order, each on validation, each logged before the next:
1. Family: F-tree vs F-hyb (M-obs, longest window).
2. Window length L (≤ 3 candidates), winning family.
3. Weather source: M-obs (ERA5 training) vs M-fc (GFS training), temperature only, winning
   family and window. Both evaluated with forecast inputs.
4. Test evaluated once with the final configuration, B0 and B1.

Extremes rule (fixed 2026-10-24): "out of range" = above the seasonal 99th percentile of all
previous years, for daily temperature and for ΔCDD vs the reference day, computed year by year.
F-hyb is kept if it is not worse than F-tree on the whole validation period (one-sided
Diebold-Mariano, 5 %) and has lower error on out-of-range days of a rolling-origin backtest
2021-01-01 → 2025-09-30 (yearly refits; targets exist from 2018-01-01, so 2021 is the first year
with three years of history). The test is not used for this choice.

### 4.4 Leakage rules

- Every feature is checked against the information set (section 1); no window includes D-1.
- Evaluation inputs are always forecasts (D4b). Results with ERA5 evaluation inputs are labelled
  "oracle (upper bound)". ERA5 as a training input (M-obs) is not oracle.
- Version rules of section 2.2.

### 4.5 Metrics

- Primary: MAPE per target. Secondary: MAE, skill vs B0 = 1 − MAE_model / MAE_B0.
- Bias and spread reported separately for every model and baseline: mean percentage error and
  standard deviation of the percentage error. Comparisons with B1 are reported on both MAPE and
  spread, because a deliberate overestimate by the operator appears as bias, not as spread.
- Provisional and definitive scores are both kept (2.2); headline results use definitive scores.
  Provisional scores are biased in favour of B1: the validity check uses B1, so the days where
  the programme failed badly are dropped from provisional scoring. Provisional comparisons with
  B1 are reported with and without the days the check rejected.
- 95 % CI: paired moving-block bootstrap (block 7 days, B = 2000).
- Diebold-Mariano with HAC variance and Harvey-Leybourne-Newbold correction.
- Errors reported separately on out-of-range days and on load-shedding days.
- Residual autocorrelation (lags 1–14) checked for every model.

## 5. Success criteria

Thresholds are derived from validation-period measurements (B0 and B1 errors 2024-10 → 2025-09)
and fixed, with their derivation, before the test is evaluated. Structure:
- S1: skill vs B0 on test (1 − MAE_model / MAE_B0) ≥ 0.50 and the lower bound of its 95 % CI > 0.
  B0 is weak at a horizon of 3+ days (MAPE 8–9 %), so S1 only requires MAPE below about 4.5 %; it is
  a floor, not evidence of a good model. Skill vs B1 is reported next to it (not a criterion).
  Validation: 0.62 (CI 0.55–0.67), quarters 0.53–0.69 (MAPE-based); 0.50 sits below the worst quarter and the
  CI lower bound, leaving room for a different year (the CI covers sampling within one year only).
- S2: non-inferiority to B1: upper bound of the 95 % CI of MAPE_model − MAPE_B1 on test < +0.50
  percentage points (about 15 % of B1's MAPE). Validation: −0.03 (CI −0.46 to +0.39). Demanding by
  design: with the validation CI width the model must roughly tie B1 to pass.
- Fixed 2026-10-29 (Fran), before the test was evaluated. Bias and spread vs B1 are reported
  next to S2, not as thresholds.
- S3: forward test: same S1 and S2 rules after ≥ 90 live days.
- S4: over 60 days on AWS, ≥ 95 % of the D6 programmes and D8 daily reports published by
  CAMMESA are archived within 24 h of publication (verify mode).
- S5: forecast produced and scored automatically for ≥ 95 % of days over 60 days.
- S6: monthly AWS cost, gross, credits excluded ≤ USD 1.00.
- S7: a fresh clone redeploys the service from documented commands (requires remote Terraform state).

## 6. Collector (P0) — as built

- scripts/collect_cammesa.py (standard library; boto3 in Lambda). Sinks: local files or S3.
- Modes: snapshot (D2, 00:30/06:30/12:30/18:30 ART), day (D3 for D-1 and D-7, 01:15 ART),
  docs (D5/D6 8-day look-back, D8 45-day look-back so complements are caught, 23:30 ART),
  backfill and docs history (local). D8 attachments are requested with each publication's own
  nemo (the listing nemo mixes daily reports and complements).
- Raw bodies unmodified, unique timestamped keys, never overwritten; failures stored as *.error*.
- Reliability: per-request timeout (30 s demand API, 120 s documents), 3 retries with exponential
  backoff; Lambda raises on any failure (Errors alarm); missing-run alarm (6 h). Lambda timeout 900 s.
- Tests: tests/test_collector.py against a local fake of the CAMMESA endpoints.

## 7. Production design (P2)

Fixed 2026-10-29 (Fran: JSON in S3, training in Lambda; DECISIONS 2026-10-29). No EC2,
always-on servers, API Gateway, NAT gateway, SageMaker or GPUs.

- Collector (P0 Lambda, unchanged) archives raw documents to s3://<raw bucket>/raw/cammesa/.
  An extra documents run at 09:40 ART catches reports published before the issue.
- Forecaster: one Lambda from a container image (ECR; Python, the package, Node + mdb-reader for
  the Access databases), two events:
  - daily, 09:55 ART (after the collector's 09:40 documents run; documents published in the
    last minutes before 10:00 are the only difference from the backtest's information set): (1) update the state tables with documents not yet in them (D6 and D8 listed
    in the last 45 days); (2) fetch the live GFS inputs (previous_day2, 48 h lead) and merge them
    into the weather table; (3) forecast D + 1 with the champion model (same code as
    scripts/forecast.py) and write forecasts/<day>.json once (never overwritten); (4) score every
    forecast day whose actuals exist: provisional from the first valid daily report, definitive
    from the Síntesis, with B0 and B1 next to the model (scores/<day>.json, updated when the
    definitive value arrives).
  - monthly, day 21, 03:00 ART: discover and download new Síntesis bases, rebuild the supply table
    and the feature table, retrain the champion configuration on the labels published by that date
    (label embargo, as in the backtest), write models/<date>/ and point models/champion.json to it.
    A monthly refit of the champion configuration is routine (it is what the backtest and the test
    measured) and does not go through the promotion gate.
- State: s3://<raw bucket>/state/: d6_programme_hourly, d8_postop_versions, d7_supply_hourly,
  gfs_daily (daily mean previous_day2 temperature per point) and features_daily, all parquet.
  Seeded once from the PC tables (scripts/seed_state.py); afterwards only the Lambda writes them.
  Point weights are frozen (results/point_weights.csv, inside the image).
- Outputs: forecasts/, scores/, models/ in the same bucket, private. Public page: static files
  (site/) in a separate private bucket served only through CloudFront (origin access control);
  the daily run writes data.json there (last 90 days of forecasts, actuals, operator programme and
  errors; daily totals only, no raw documents). Security: no server, API, form or credential;
  HTTPS only; Content-Security-Policy allowing only the page's own files; no framing; the
  forecaster may write data.json and nothing else in that bucket.
- Training runs inside the Lambda: a fit takes seconds and the data never leave AWS (no egress
  cost, no external credentials). GitHub Actions: tests on every push; image build and Terraform
  only after the Terraform state moves to a remote S3 backend with locking (O11).
- Promotion (shadow mode), for a challenger configuration only: one challenger at a time runs
  in shadow for 56 days, producing genuine out-of-sample forecasts next to the champion without
  being published. It replaces the champion only if its MAE over the shadow period is lower and a
  one-sided Diebold-Mariano test rejects equal accuracy at 5 %. Low power is accepted.
- Monitoring: Lambda error and missing-run alarms (email, as the collector); a run that cannot
  forecast raises. 28-day rolling MAE ratio model/B0; alert when it exceeds the test-period ratio
  by 50 %. Out-of-range flag on forecasts.
- Cost (S6): Lambda (about 3 GB × a few minutes a day) and CloudFront within the free tier; ECR
  image storage about USD 0.10 per month; S3 a few cents.

## 8. Non-goals (v1)

Deferred lines, with reasons and revisit points: docs/ROADMAP.md. In v1 specifically excluded:
regional targets, probabilistic forecasts, deep learning, ARIMA-type models,
extra weather variables, public API, conversational interface, redistribution of CAMMESA data.

## 9. Review points

- R0 (2026-10-30): PC vs AWS collection comparison; decommission PC tasks.
- R1 (end of validation decisions, 4.3 steps 1–3): freeze features and thresholds. No days are
  excluded from training or scoring (the 2019-06-16 blackout is in the training targets).
- R2 (test evaluated once).
- R5 (30 days of live forecasts): ROADMAP items F9–F11.

## 10. Open items

- O15: D8 vs D7 hourly values (daily totals checked 2026-10-29 after the YACYHIPY exclusion:
  monthly median within ±0.06 %, 2018 → 2026-09); isolated days far off (2022, 2023).
- O16: hourly target for T2: D8 hourly supply − D7 hourly exports; check D8 hourly vs D7 hourly.
- O10: FALLAS meaning (load shedding / unserved energy).
- O11: remote Terraform state before CD (design 2026-10-29: infra/bootstrap, deploy.yml; closed when the first deploy from GitHub succeeds).
- Resolved: O1 (2026-10-24), O2 (2026-10-23), O4 → method_notes, O5 (2026-10-24), O6, O7 (GFS),
  O8, O9 and O12 (obsolete: D3 and D5 are not targets), O13 (2026-10-26: supplied energy from
  D7, live values from D8), O3 (2026-10-28: point weights, src/sadi_forecast/weights.py),
  O14 (2026-10-28: validity check, 2.2).

## 11. v2: hourly curve (T3) and daily peak (T2)

Written 2026-10-29 before any hourly model was fitted (ROADMAP F3, F14).

- T3: hourly supplied energy H(D, h), h = 1..24 (MWh in hour h = mean MW), hour h covering
  [h − 1, h) ART. T2 (daily peak, MW) = max_h H(D, h). Definitive: D7 hourly supply − D7 hourly
  exports, latest base. Provisional: D8 hourly supply (s01–s24) − D6 programmed hourly exports.
  O16 check (data ≤ 2025-09-30): D8 complement vs D7 hourly supply, 2,830 days, median absolute
  difference 0.001 %, 99th percentile 0.35 %, same hour numbering (a one-hour shift gives 2.7 %).
- Forecast = daily energy from v1 (unchanged) × hourly shares s(D, h), Σ_h s = 1, so the 24 hours
  always add up to the v1 daily forecast.
- Shape baseline S0: hourly shares of the reference days (the same-weekday days D−7…D−28 that
  v1's reference level uses, in the version known at the issue time), median per hour,
  renormalised. Needs at least two days.
- Shape model S1: gradient-boosted trees (v1 settings, absolute-error loss) on one row per
  (day, hour), target ln(s / s0). Features: hour; dow; day_kind, prev_day_kind, next_day_kind;
  doy_sin, doy_cos; demand-weighted GFS temperature at the start of hour h on D; its difference
  from the mean of the reference days at the same hour; the daily Δ temperature of v1. Shares
  = s0 · exp(prediction), renormalised. Training: 5-year window, GFS days only, monthly refits
  with the label embargo of 4.1 (as v1).
- Comparators on the same days: S0 × v1 daily forecast, and B1 hourly (D6 t01–t24).
- Decision (validation 2024-10-01 → 2025-09-30, the only choice): S1 is adopted if its hourly
  MAPE is lower than S0's and a two-sided Diebold-Mariano test on the daily mean absolute
  hourly percentage error gives p < 0.05; otherwise S0.
- Metrics: hourly MAPE (all hours), T2 MAPE, peak-hour error (|predicted − actual hour of the
  maximum|, share within 1 hour), bias; every comparison on the days all three exist.
- Test year: evaluated once after the decision, labelled "daily totals already seen" (the v1
  daily model was scored on it; the shape model was not). The clean evaluation is the forward
  test: 90 live days.
- Review point R6: independent audit of this section, the code and the validation results,
  before the single test evaluation.
- Production: the forecast record adds 24 hourly values and the peak; the page adds tomorrow's
  curve next to the operator's hourly programme.
