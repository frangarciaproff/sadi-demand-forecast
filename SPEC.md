# SPEC — sadi-demand-forecast

Status: DRAFT v0.5 (2026-10-24). Not agreed. Rewritten after the 2026-10-24 audit to remove
contradictions with docs/DECISIONS.md. Open method decisions are tracked in docs/method_notes.md;
deferred lines in docs/ROADMAP.md. No modelling code until sections 1, 4 and 5 are agreed.
Owner: Francisco J. García Soriano. License (code only): MIT.

## 1. Problem

Forecast next-day electricity demand of Argentina's interconnected grid (SADI) and run the
forecaster in production on AWS at near-zero cost: published daily, scored automatically against
actuals and against the operator's (CAMMESA) day-ahead programme, retrained under a statistical gate.

v1 targets, for calendar day D (Argentina time, ART = UTC-03:00):

- T1: daily net energy E(D), GWh.
- T2: daily peak P(D), MW, defined as the maximum of the 24 hourly average powers (= hourly energies).

Both targets use net demand, the quantity CAMMESA programmes (B1). To verify in P1: that the sum of
D5 area demands equals D5 balance DEMNETA.

Issue time: 10:00 ART on D-1, before CAMMESA publishes its programme (~21:30 ART on D-1), so the
operator's forecast cannot leak into the model.

Information set at issue time:
- Actuals for days ≤ D-2 (horizon 2: all backtests evaluate the 2-step-ahead forecast).
- Calendar of D.
- Weather forecasts from runs initialised at least 48 h before each valid hour of D (previous_day2).

## 2. Data

| ID | Source | Content | Resolution | Coverage | Role |
|----|--------|---------|-----------|----------|------|
| D1 | CAMMESA "Máximos Históricos de Energía y Potencia" (manual xlsx) | SADI gross energy, instantaneous peak, GBA temperature | daily | 2007-01-01 → 2026-01-31 | Cross-check only; not a pipeline input |
| D2 | api.cammesa.com demanda-svc, ObtieneDemandaYTemperaturaRegion | actual 5-min demand today/yesterday/week before; demPrevista (SADI only, 25 hourly instantaneous points) | 5 min / hourly | current day; archived from 2026-10-19 | Live B1 cross-check; live actuals |
| D3 | api.cammesa.com demanda-svc, ObtieneDemandaYTemperaturaRegionByFecha | actual demand for a date | 5 min | archived 2026-03-01 → present | Production lag features |
| D5 | CAMMESA Parte Semanal (pub-svc, PARTE_SEMANAL_UNIF) | hourly demand by area and agent; daily balance (gross/net demand, losses, pumping, FALLAS) | hourly / daily | 2010-01-07 → present; provisional, then definitive after the monthly DTE | Targets (definitive); backtest lag features (provisional, as D3 proxy) |
| D6 | CAMMESA Programación Diaria (pub-svc, PROGRAMACION_DIARIA) | operator day-ahead programme: hourly net demand and losses per region | hourly | 2010-01-01 → present (28 isolated missing days) | B1 |
| D4a | Open-Meteo Historical Weather API (ERA5) | hourly weather at demand-centre coordinates | hourly | 1940 → present | M-obs training input; oracle evaluation only |
| D4b | Open-Meteo Previous Runs API, model gfs_global, previous_day2 | 48-h-lead forecasts | hourly | temperature 2021-03-24 → (gap 2023-12-29 → 2024-01-20); other variables 2024-01-20 → | Evaluation and production input; M-fc training input |

D5 publication lag: weekly files appear on Thursday, ~4 days after the week ends. At issue time the
newest D5 day is D-5 to D-11, so D5 cannot supply D-2 in production.

### 2.1 Terms

- CAMMESA: published information may be used and derived results published (CAMMESA email,
  2026-10-24). Raw data is not redistributed (project choice); CI logs never print it.
- Open-Meteo: CC BY 4.0, attribution in README and dashboard; free non-commercial use ≤ 10,000
  calls/day.
- Collection volume: ~10 demand-API requests/day plus ~4 document listings and new attachments/day
  (~20–30 requests/day), ≤ 1 request/s.

### 2.2 Version rules (leakage control)

- Targets: latest publication (definitive, post-DTE values) of D5.
- Features: the version available at issue time. Backtests use the first (provisional) D5
  publication as the proxy for the real-time values that D3 supplies in production.
- B1: the last D6 file for target day D published before 00:00 ART on D. Re-publications on D or
  later are excluded. The "latest publication" rule never applies to D6.
- D6 files are stored by publication date; the target date is encoded in the file name
  (PDyymmdd). Empty zips, AT*, .7z and .xls attachments are skipped.

### 2.3 Known data issues

- D3 vs D5 reconciliation (blocking for the lag design): compare daily net energy and hourly values
  over the overlap (2026-03-01 → latest definitive D5). Decision rule fixed now: if the daily
  absolute percentage difference has median ≤ 0.5 %, provisional D5 is accepted as the D3 proxy;
  otherwise lag features are restricted to data published by issue time (lags ≥ D-5).
- D5 provisional vs definitive differences: measured in P1 and reported.
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
- B1: CAMMESA day-ahead programme (D6, version rule 2.2), same target definitions (net energy;
  max of hourly values).

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
  docs (D5/D6, 8-day look-back, 23:30 ART), backfill and docs history (local).
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

- O3: city set and weights (A′ weights from D5 area shares on training data).
- O8: D3 vs D5 reconciliation (2.3) → lag design.
- O9: target is net demand: verify D5 area sum = DEMNETA.
- O10: FALLAS meaning (load shedding / unserved energy).
- O11: remote Terraform state before CD.
- Resolved: O1 (2026-10-24), O2 (2026-10-23), O4 → method_notes, O5 (2026-10-24), O6, O7 (GFS).
