# SPEC — sadi-demand-forecast

Status: DRAFT v0.6 (2026-10-27). Not agreed. v0.6: target definition and source (O13 closed),
live data handling (validity check, replacement, multiple complements). v0.5 was rewritten after
the 2026-10-24 audit to remove contradictions with docs/DECISIONS.md. Open method decisions are tracked in docs/method_notes.md;
deferred lines in docs/ROADMAP.md. No modelling code until sections 1, 4 and 5 are agreed.
Owner: Francisco J. García Soriano. License (code only): MIT.

## 1. Problem

Forecast next-day electricity demand of Argentina's interconnected grid (SADI) and run the
forecaster in production on AWS at near-zero cost: published daily, scored automatically against
actuals and against the operator's (CAMMESA) day-ahead programme, retrained under a statistical gate.

v1 targets, for calendar day D (Argentina time, ART = UTC-03:00), on supplied energy:

  supplied energy = generation (all units) + imports − exports
                  = local demand + transmission losses + pumping   (exact; DECISIONS 2026-10-26)

- T1: daily supplied energy E(D), GWh.
- T2: daily peak P(D), MW, defined as the maximum of the 24 hourly supplied energies.

Pumping is included (Fran, 2026-10-26): it is energy the system supplied, and from 2024 it is not
published separately, so excluding it would require an estimate.

Issue time: 10:00 ART on D-1, before CAMMESA publishes its programme (~21:30 ART on D-1), so the
operator's forecast cannot leak into the model.

Information set at issue time:
- Actuals published before the issue time, by archived publication timestamp. The daily report for
  day X appears on X+1 between 18:00 and 21:00 ART, and Friday–Sunday reports on Monday or Tuesday,
  so the newest actual is D-3 on Tuesday–Friday issue days and older on Saturday–Monday issue days.
  Backtests reproduce this from the archived listings (horizon ≥ 3).
- Calendar of D.
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

- Definitive target (training, definitive scoring): D8 complement supply − D7 actual exports.
- Provisional actual (live scoring, lag features): latest D8 daily report that passes the validity
  check − D6 programmed exports for that day. Marked "provisional" wherever it is shown.
- Replacement: when the D8 complement for a day is published, it replaces the provisional supply;
  when the D7 base covering the day is published, D7 exports replace programmed exports. Every
  stored value keeps its source and publication time; scores are recomputed and both provisional
  and definitive scores are kept.
- Multiple complements for one day (e.g. 2020-03-10 for 2020-02-15: 398,161 and 410,255 MWh):
  once D7 covers the day, the complement closest to D7 supply is used (it must be within 0.2 %,
  otherwise the day is flagged and excluded from targets); before that, the complement closest to
  the latest valid daily report is used provisionally and flagged. Publication order is not used
  (in the 2020-02-15 case the later complement is the wrong one).
- Validity check of a daily report (before it is used anywhere): with provisional value
  v = daily-report supply − programmed exports, the day is valid if |v / B1 total − 1| ≤ k1 and
  |v / median of the same weekday in the previous 4 valid weeks − 1| ≤ k2. k1 and k2 are set on the training period as the 99.5th percentiles of the same
  ratios computed with complements, and frozen before validation. Observed gross errors of daily
  reports: 2022-05-15 +6.8 %, 2022-08-15 +32 % (re-issued next morning), 2023-11-14 +2.7 %.
  An invalid day is treated as missing until a later version passes the check. Backtests apply
  the same check to the archived daily reports.
- Features: the version available at issue time, from archived publication timestamps.
- B1: the last D6 file for target day D published before 00:00 ART on D. Re-publications on D or
  later are excluded. The "latest publication" rule never applies to D6.
- D6 files are stored by publication date; the target date is encoded in the file name
  (PDyymmdd). Empty zips, AT*, .7z and .xls attachments are skipped.

### 2.3 Known data issues

- D8 daily report vs complement: median absolute difference ≈ 0.13 %, up to ~1 % on ordinary days,
  gross errors on 3 of 41 sample days (2.2). Measured on the full archive in P1 and reported.
- D6 programmed vs D7 actual exports, as a share of supply (2018 → 2026-09): median 0, p90 ≤ 0.62 %,
  max 12.2 % (2021). This is the error of provisional actuals on export days.
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

- Training window: sliding window of fixed length L, L ∈ {≤ 3 candidates} chosen on validation;
  within backtests the model is refit monthly on the most recent L years ending ≤ D-2.
- M-fc training inputs: GFS previous_day2, 2021-03-25 → 2024-09-30 (2023-12-29 → 2024-01-20 excluded).
- EDA: unrestricted on data ≤ 2025-09-30. On the test period only data-quality checks (gaps, units,
  duplicates). Disclosure: 2026-01 mean daily energy (D1) was seen during inspection (descriptive only).

### 4.2 Baselines

- B0: seasonal naive (same weekday, reference rule as the model target; T1 in method_notes).
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
2016 → 2025-09-30 (yearly refits). The test is not used for this choice.

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
- 95 % CI: paired moving-block bootstrap (block 7 days, B = 2000).
- Diebold-Mariano with HAC variance and Harvey-Leybourne-Newbold correction.
- Errors reported separately on out-of-range days and on load-shedding days.
- Residual autocorrelation (lags 1–14) checked for every model.

## 5. Success criteria

Thresholds are derived from validation-period measurements (B0 and B1 errors 2024-10 → 2025-09)
and fixed, with their derivation, before the test is evaluated. Structure:
- S1: skill vs B0 on test above a threshold derived from validation, CI lower bound > 0.
- S2: MAPE on test vs B1's test MAPE within a margin derived from validation.
- S3: forward test: same comparison after ≥ 90 live days.
- S4: collector archives ≥ 95 % of scheduled snapshots over 60 days on AWS.
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

- EventBridge Scheduler → Lambda (collector, forecaster after issue-time data, scorer after
  actuals). Forecasts and scores in DynamoDB. Raw data in private S3. Static dashboard on
  S3 + CloudFront. No EC2, always-on servers, API Gateway, NAT gateway, SageMaker or GPUs.
- Training on GitHub Actions through OIDC (no stored keys); logs print metrics only.
- Promotion (shadow mode): a monthly challenger runs in shadow for 56 days, producing genuine
  out-of-sample forecasts next to the champion without being published. It replaces the champion
  only if its MAE over the shadow period is lower and a one-sided Diebold-Mariano test rejects
  equal accuracy at 5 %. Low power is accepted as a conservative design.
- Registry: S3 prefix models/ (immutable artifacts) + models/champion.json.
- Monitoring: 28-day rolling MAE ratio model/B0; alert when it exceeds the test-period ratio by
  50 % (relative to B0, so seasonal level changes do not trigger it). Out-of-range flag on forecasts.
- Delivery: CI on every push. CD of infrastructure only after Terraform state moves to a remote
  S3 backend with locking; plan on merge to main, apply through a protected environment with
  manual approval; OIDC role scoped to project resources.

## 8. Non-goals (v1)

Deferred lines, with reasons and revisit points: docs/ROADMAP.md. In v1 specifically excluded:
hourly target, regional targets, probabilistic forecasts, deep learning, ARIMA-type models,
extra weather variables, public API, conversational interface, redistribution of CAMMESA data.

## 9. Review points

- R0 (2026-10-30): PC vs AWS collection comparison; decommission PC tasks.
- R1 (end of validation decisions, 4.3 steps 1–3): freeze features, flagged days, thresholds.
- R2 (test evaluated once).
- R5 (30 days of live forecasts): ROADMAP items F9–F11.

## 10. Open items

- O3: city set and weights (A′ weights from D7 province demand shares on training data, 2019 →).
- O14: validity-check thresholds k1, k2 (2.2), set on training data.
- O15: D8 vs D7 on the full archive (daily totals and hourly values, all years incl. 2024-11 →
  2026-10); D8 daily vs complement distribution; days with several complements.
- O16: hourly target for T2: D8 hourly supply − D7 hourly exports; check D8 hourly vs D7 hourly.
- O10: FALLAS meaning (load shedding / unserved energy).
- O11: remote Terraform state before CD.
- Resolved: O1 (2026-10-24), O2 (2026-10-23), O4 → method_notes, O5 (2026-10-24), O6, O7 (GFS),
  O8, O9 and O12 (obsolete: D3 and D5 are not targets), O13 (2026-10-26: supplied energy from D8 + D7).
