# sadi-demand-forecast

Day-ahead forecasting of electricity demand on Argentina's interconnected grid (SADI), run
as a monitored service on AWS and compared with the forecast of CAMMESA, the wholesale
market operator. This repository holds the data collection, the operator's 16-year archive,
the parsers, and the data checks that fix what is being forecast. **No forecasting model
exists yet** (see [Status](#status)).

Design: [SPEC.md](SPEC.md) (v0.8). Every decision and finding, with its evidence:
[docs/DECISIONS.md](docs/DECISIONS.md).

## Status

As of 2026-10-29.

| Component | State |
|---|---|
| Serverless collector on AWS (Terraform) | Running since 2026-10-23 |
| Archive of operator documents | Day-ahead programmes and weekly reports 2010 → present; monthly balance bases 2018 → 2026-09; daily post-operation reports 2018 → present (6,918 documents parsed) |
| Parsers | Weekly area demand, day-ahead programme (two formats), monthly balance bases, daily post-operation reports |
| Target definition | Fixed and checked against the operator's balance (below) |
| Weather inputs | Reanalysis (ERA5) and 48-hour-lead forecasts (GFS) for 15 points, downloaded |
| Feature table and baselines | Built: lags as known at the issue time, calendar, demand-weighted temperature; baseline errors in [`results/baselines.json`](results/baselines.json) |
| Models, backtests | Decision sequence on the validation year; test year evaluated once (below) |
| Forecasts, scoring, dashboard, continuous deployment | Not started |

## What is built

### Collector on AWS

[`scripts/collect_cammesa.py`](scripts/collect_cammesa.py) (standard library) runs as an
AWS Lambda function (Python 3.12, arm64), deployed with Terraform ([`infra/`](infra)):

- EventBridge Scheduler: demand snapshots four times a day, the previous day's 5-minute
  demand once a day, and the operator's published documents once a day (with a 45-day
  look-back, so reports that are re-published a month later are caught).
- Private, versioned, encrypted S3 bucket; raw responses are stored unmodified and never
  overwritten; failed downloads are kept as separate error files.
- CloudWatch alarms (function errors, missing runs) with email alerts through SNS, and an
  AWS budget on gross monthly cost.
- The same script runs locally for historical downloads (resumable) and has a `verify`
  mode that checks every attachment listed by the operator against the archive.

### Archive

| Source (CAMMESA) | Content | Coverage | Size |
|---|---|---|---|
| Programación Diaria | Day-ahead programme: hourly net demand, losses, pumping, exports | 2009-12-31 → present, 6,318 attachments | 3.1 GB |
| Parte Semanal | Weekly report: hourly demand by area | 2010-01-07 → present, 1,929 attachments | 3.4 GB |
| Informe Síntesis Mensual | Monthly consolidated bases: hourly supply by technology, imports, exports, demand by type and province | 2018-01-01 → 2026-09-30 (6 bases) | 0.3 GB |
| Parte Post Operativo | Daily post-operation report: hourly energy of every generating unit (Access database); daily version and a corrected version about a month later | 2018 → present, 6,918 documents | ≈ 1–6 MB per file |

Raw data is not committed and not redistributed (see [Data and terms](#data-and-terms)).

### Parsers

[`src/sadi_forecast/`](src/sadi_forecast): pure functions on text or workbooks, tested on
synthetic fragments ([`tests/`](tests)).

- Weekly area files are fixed-width text in which large values fill the whole field and
  touch the next one, so fields are sliced by position. Rows that the operator left
  unmarked are filled with zeros in the source: they are read as missing data, not as zero
  demand (45 such rows in a 252-file sample).
- The `balance.txt` member of the weekly reports is the same file (identical SHA-256, dated
  2016-09-21) in every sampled report from 2016 to 2025, so it is discarded.
- Day-ahead programmes switch from fixed-width text to CSV in 2024-11; both are parsed,
  including lower-case headers and archives whose internal file names do not match.
- Monthly bases change layout over time (columns dropped from 2024, an unnamed import
  column, a nested copy of the package); the parser handles each case explicitly.

### Target definition and the supply balance check

The quantity forecast is the energy the grid supplied in a day:

    generation (all units) + imports − exports  =  local demand + transmission losses + pumping

It was chosen because it can be measured without estimated conversion factors, and the
operator's forecast for the same quantity can be rebuilt from its published components
(programmed net demand + losses + pumping).

[`scripts/check_supply_balance.py`](scripts/check_supply_balance.py) checks the identity
on the operator's monthly bases that still publish the demand components: it holds on all
2,191 days from 2018-01-01 to 2023-12-31, to within floating-point rounding. This confirms that
the definition matches the operator's own accounting (internal consistency of its balance); it
does not by itself validate the measurements
([`results/eda/supply_balance.json`](results/eda/supply_balance.json)). From 2024 the bases
no longer publish losses and pumping separately, which is why the target is built from the
supply side.

Other measured findings that shaped the design (details and numbers in DECISIONS):

- The weekly area totals are not definition-stable over 2010–2025, so they are not used as
  the target.
- The operator's real-time demand feed measures a different, undocumented quantity (above
  local demand by a gap that varies by weekday; DECISIONS 2026-10-26); it is archived but not
  used as ground truth.
- Daily post-operation reports differ from their corrected versions by 0.07 % on a typical
  day, but 69 of 2,542 reports in the training period (2.7 %) are more than 2 % off
  ([`results/eda/validity_check.json`](results/eda/validity_check.json)). A validity check
  rejects the gross cases before use; the rest is carried, as published, into backtests
  (SPEC 2.2).
- From 2024-11 the daily post-operation databases list the Paraguayan share of the Yacyretá
  dam as a separate unit (YACYHIPY). Counting it overstates supply by about 4 % in the summer
  of 2024-25 and by 0.6–1 % afterwards; the monthly bases and the operator's gross-energy
  series do not count it. It is excluded from the sum, and the corrected reports match the
  monthly bases within ±0.06 % (monthly median) in every month with both sources from 2024-10 to 2026-09. The
  first backtest, run before the fix, is kept as invalid in
  [`results/backtest/invalid/`](results/backtest/invalid).

## Validation results

Validation year 2024-10-01 → 2025-09-30, forecasts issued at 10:00 on the day before, monthly
refits that only use targets already published at the refit date, weather forecast inputs
(GFS, 48-hour lead). Decisions were taken in a fixed order with rules written down before the
first fit (DECISIONS 2026-10-29).

| Step | Compared | Chosen | Validation error (MAPE) |
|---|---|---|---|
| 1. Model family | gradient-boosted trees vs linear degree-day part + trees | trees | 4.31 % vs 4.29 %; the hybrid failed the extreme-heat check (5.98 % vs 4.35 % on 65 out-of-range days, 2021–2025) |
| 2. Training window | 3 years, 5 years, all (from 2018) | 5 years | 4.44 %, 4.27 %, 4.31 % (differences not significant) |
| 3. Weather in training | reanalysis (ERA5) vs archived forecasts (GFS) | forecasts | 4.27 % vs 3.37 % (Diebold-Mariano p = 0.005) |

Final configuration against the baselines on the 358 days where all exist
([`results/backtest/`](results/backtest)):

| Forecast | MAPE | 95 % CI | Mean error (bias) | SD of error |
|---|---|---|---|---|
| Model (trees, 5 years, GFS) | 3.36 % | 3.04–3.76 % | +0.14 % | 4.41 % |
| Operator programme (B1) | 3.39 % | 3.02–3.80 % | +2.98 % | 3.05 % |
| Same weekday, median of 4 weeks (B0) | 8.68 % | 7.47–10.26 % | +0.50 % | 11.47 % |

The model matches the operator's day-ahead programme on average error (Diebold-Mariano
p = 0.89) with almost no bias, but its errors are more spread out: the programme
overestimates by about 3 % by design (security of supply) and is otherwise tighter.
The model's errors remain correlated from one day to the next (0.44, against 0.20 for the
programme), which points to information it does not yet use. Training on reanalysis and
forecasting with forecast inputs costs about 0.9 percentage points; with reanalysis inputs
on the forecast day (not available in production; step-1 configuration) the trees reach 2.81 %.

## Test results

The test year 2025-10-01 → 2026-09-30 was evaluated once, after the configuration and the two
success thresholds were fixed ([`results/test/test_evaluation.json`](results/test/test_evaluation.json)).
The thresholds were set to be demanding.

| Forecast (362 days) | MAPE | 95 % CI | Mean error (bias) | SD of error |
|---|---|---|---|---|
| Model | 3.41 % | 3.06–3.75 % | −0.05 % | 4.39 % |
| Operator programme | 3.09 % | 2.76–3.45 % | +2.72 % | 2.90 % |
| Same weekday, median of 4 weeks | 8.26 % | 7.27–9.34 % | +0.12 % | 10.36 % |

| Criterion | Target | Result | |
|---|---|---|---|
| Skill against the 4-week median (1 − MAE ratio) | ≥ 0.50, CI above 0 | 0.59 (CI 0.54–0.65) | passed |
| Not worse than the operator's programme by more than 0.5 points of MAPE | CI upper bound < +0.50 | +0.32 (CI −0.10 to +0.68) | failed |

The model is unbiased and 59 % better than the seasonal baseline. Against the operator's
programme it is 0.32 points worse on average; the difference is not statistically
significant (Diebold-Mariano p = 0.11), but the data cannot rule out a gap larger than the
0.5-point margin, so the non-inferiority target is not met. The programme's errors are
tighter (SD 2.90 % against 4.39 %) once its deliberate overestimate is set aside. The model
beat the programme in one quarter of four (July–September 2026: 2.88 % against 3.18 %).
Errors on the 9 out-of-range hot days: model 5.29 %, programme 4.41 %. Days with load
shedding are not reported separately yet (no source list).

## Repository layout

    SPEC.md                    design
    docs/DECISIONS.md          append-only log of decisions and findings
    docs/data_inventory.md     source formats and parsing rules
    infra/                     Terraform for the AWS collector
    scripts/                   collector, downloads, table builders, data checks
    src/sadi_forecast/         parsers, tables, features, models, evaluation
    tests/                     pytest suite (fake CAMMESA server for the collector)
    results/eda/               aggregate results of the data checks (no raw values)
    results/backtest/          validation scores and decisions (no raw values)
    results/test/              the single test evaluation

## Running it

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

    uv sync
    make check                                          # ruff, mypy, pytest
    uv run python scripts/collect_cammesa.py snapshot   # local archive under data/raw
    uv run python scripts/get_sintesis.py               # monthly balance bases
    uv run python scripts/check_supply_balance.py
    uv run python scripts/build_features.py
    uv run python scripts/backtest.py --step family    # then --step window, --step weather
    uv run python scripts/evaluate_test.py             # once; refuses if its output exists

Deploying the collector: `terraform -chdir=infra init`, `plan`, `apply` with an AWS
profile and the variables in `infra/terraform.tfvars.example`.

CI (GitHub Actions) runs lint, formatting, type checks, tests and Terraform validation on
every push.

## Data and terms

- CAMMESA: published information, used with the operator's confirmation (2026-10-24) that
  it may be used and derived results published. Raw files are not redistributed.
- Weather: [Open-Meteo](https://open-meteo.com/) (ERA5 reanalysis and GFS previous runs),
  CC BY 4.0.

## License

Code: MIT ([LICENSE](LICENSE)).
