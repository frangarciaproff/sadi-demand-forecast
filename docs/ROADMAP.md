# ROADMAP — lines deferred from v1

Each line was considered and deliberately left out of v1. Revisit at the review point listed.
Moving a line into scope requires a SPEC change and a DECISIONS.md entry.

## Modelling

| ID | Line | Why deferred | Revisit |
|----|------|--------------|---------|
| F1 | Spatial design B: per-area temperatures as separate features (model learns weights) | Collinear inputs, few years of data, overfitting risk; A′ covers regional climates with 2 features | After v1 test (R2) |
| F2 | Extra weather variables: apparent temperature, humidity/dew point, wind, cloud cover, shortwave radiation | Archived forecasts only from 2024-01-20; would break the clean M-obs vs M-fc comparison | After v1 test (R2); M-fc version once ≥ 3 years of archive exist (2027) |
| F3 | Hourly target (day-ahead hourly curve) | v1 is daily; hourly history in D5 to be validated first | R3 |
| F4 | Regional / provincial targets (e.g. Córdoba) | National target first; CAMMESA forecast exists for SADI only | After v1 production |
| F5 | Probabilistic forecasts (quantiles, prediction intervals) | Point forecast first; needs separate evaluation (pinball loss, coverage) | After v1 production |
| F6 | Deep learning models | Small tabular data; trees first | Only if tree models plateau |
| F7 | Alternative NWP model (ECMWF IFS) or multi-model inputs | GFS is the only archive covering 2021–2023 | When ECMWF archive ≥ 3 years |
| F8 | Latest-run-at-issue-time weather inputs (Single Runs API) instead of fixed 48 h lead | Needs archive check (C2b); fixed lead is consistent and simpler | After v1 test |
| F14 | T2: daily peak P(D) (max of hourly supplied energy) | Needs the hourly target (O16) and its own decision sequence; the test year has already been seen for T1, so a T2 test on it would not be clean (re-audit 2026-10-29) | Evaluated on the forward test only |
| F15 | Holiday check at issue time: short-notice national holidays (e.g. 2022-12-20, declared 2022-12-19) and provincial holidays on different days | The `holidays` package encodes holidays as known today; few days affected: in the package's list the only extraordinary national holidays 2018 → 2026-09 are 2022-05-18 (census, decreed months ahead) and 2022-12-20 (World Cup, decreed the day before), both in training | v2 |
| F13 | Same-information operator benchmark: CAMMESA Programación Semanal (multi-day forecasts published before the 10:00 ART D-1 issue time) | v1 compares against the day-ahead programme (B1), published after issue time | After v1 test |

## Production and tooling

| ID | Line | Why deferred | Revisit |
|----|------|--------------|---------|
| F9 | Data-drift reports (e.g. Evidently) | Next-day actuals give a direct performance signal; seasonal drift would raise false alarms | R5 (30 days live) |
| F10 | Public API (e.g. FastAPI) | No on-demand consumer for a daily batch forecast | R5, only with a real consumer |
| F11 | Conversational / agent interface over results (text-to-SQL, links to the Spider project) | Core service first | R5 |
| F12 | MLflow model registry | S3 prefix + champion.json is sufficient for one champion | If more than one model family is served |
