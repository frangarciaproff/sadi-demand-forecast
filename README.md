# sadi-demand-forecast

Day-ahead forecasting of electricity demand on Argentina's interconnected grid (SADI), run
as a monitored service on AWS and compared with the forecast of CAMMESA, the wholesale
market operator. This repository holds the data collection, the operator's 16-year archive,
the parsers, and the data checks that fix what is being forecast. **No forecasting model
exists yet** (see [Status](#status)).

Design: [SPEC.md](SPEC.md) (draft v0.6). Every decision and finding, with its evidence:
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
| Models, backtests | Not started |
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
| Parte Post Operativo | Daily post-operation report: hourly energy of every generating unit (Access database); daily version and a corrected version about a month later | 2018 → present (in progress) | ≈ 1–6 MB per file |

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

## Repository layout

    SPEC.md                    design (draft)
    docs/DECISIONS.md          append-only log of decisions and findings
    docs/data_inventory.md     source formats and parsing rules
    infra/                     Terraform for the AWS collector
    scripts/                   collector, downloads, table builders, data checks
    src/sadi_forecast/         parsers and table construction
    tests/                     pytest suite (fake CAMMESA server for the collector)
    results/eda/               aggregate results of the data checks (no raw values)

## Running it

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

    uv sync
    make check                                          # ruff, mypy, pytest
    uv run python scripts/collect_cammesa.py snapshot   # local archive under data/raw
    uv run python scripts/get_sintesis.py               # monthly balance bases
    uv run python scripts/check_supply_balance.py

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
