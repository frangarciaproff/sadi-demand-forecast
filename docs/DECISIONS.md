# DECISIONS (append-only)

## 2026-10-19 — Target country: Argentina (CAMMESA) instead of US (EIA)
- Change: data source set to CAMMESA.
- Evidence: CAMMESA publishes a hourly demand forecast (demPrevista) usable as operator benchmark; local relevance.
- Previous state: US EIA hourly demand proposed as default.

## 2026-10-19 — v1 scope: daily energy and daily peak, not hourly
- Change: v1 targets are daily energy (GWh) and daily peak (MW).
- Evidence: long history (2007–2026) exists only at daily resolution; 5-minute data available only from ~2026-03-01.
- Previous state: hourly day-ahead curve proposed.

## 2026-10-19 — Collector before modelling
- Change: P0 collector built and run before SPEC sign-off of modelling sections.
- Evidence: CAMMESA forecast is available only live; D3 retention may be rolling. Unarchived days are lost.
- Previous state: none.

## 2026-10-19 — Finding: CAMMESA forecast (demPrevista) exists only for SADI total
- Change: none to scope. B1 (operator benchmark) is SADI-only; Córdoba has actuals only.
- Evidence: snapshot 2026-10-19 00:43 ART: SADI 25 hourly forecast points; Córdoba 0.
- Previous state: assumed per-region forecasts.

## 2026-10-19 — Collector network path
- Change: collector runs on Fran's Windows PC (Task Scheduler) until P2.
- Evidence: api.cammesa.com is refused by the egress proxies of the cloud workspace and the linked VM; reachable from the desktop browser. First snapshot (2026-10-19) saved manually via browser, sha256-verified, manifest field via=browser-manual.
- Previous state: none.

## 2026-10-21 — Finding: CAMMESA API reachable from AWS sa-east-1
- Change: collector target for P2 confirmed as AWS Lambda in sa-east-1 (São Paulo).
- Evidence: CloudShell sa-east-1, 2026-10-21 23:20 ART: current-day endpoint HTTP 200, 32242 bytes, 0.40 s; by-date endpoint (2026-10-20) HTTP 200, 16482 bytes, 0.29 s.
- Previous state: AWS reachability unknown; fallback was PC or Argentine VPS.

## 2026-10-23 — Collector deployed on AWS (P0 → Lambda)
- Change: Terraform applied (20 resources, sa-east-1). Manual snapshot test OK: HTTP 200, 289 points for 1002 and 1945, objects in S3.
- Evidence: first run 6.8 s billed, max memory 100 MB of 128 MB → memory raised to 256 MB for headroom (cost stays within Lambda free tier).
- Previous state: collector only on Fran's PC. PC tasks stay active in parallel until 7 clean days on Lambda (target: 2026-10-30).

## 2026-10-23 — Tooling scope for P1–P2 (SPEC draft v0.2)
- Change: adopted CI + CD (infra via OIDC with manual approval; model via gated promotion), MLflow tracking without server, S3-based model registry, training on GitHub Actions. Deferred to R5: Evidently, public API (FastAPI), conversational interface.
- Evidence: daily batch forecasts have no on-demand consumer; next-day actuals make performance drift a direct signal; seasonal data drift would trigger false alarms; always-on servers consume credits.
- Previous state: SPEC v0.1 without tooling decisions.

## 2026-10-23 — Finding: historical hourly demand and operator day-ahead programme are public
- Change: sources D5 (Parte Semanal) and D6 (Programación Diaria) added to SPEC; B1 can be evaluated on the 2024–2025 test; email to CAMMESA reduced to authorization and revision questions.
- Evidence: pub-svc archive queried 2026-10-23. Parte Semanal SE421218.zip (week 42/2026): hourly MWh by area (SE42area.dem) and agent, daily balance with gross/net demand, losses, pumping; documents present for 2018, 2022, 2025. Programación Diaria PD261023.zip published 2026-10-22 21:34 ART for 2026-10-23: BALANCE.csv with hourly programmed net demand per region; documents present for 2019-03 and 2022-03.
- Previous state: historical forecasts and pre-2026-03 hourly demand assumed unavailable without a request.

## 2026-10-23 — Issue time before the operator publishes; download all history, choose window in validation
- Change: model forecasts are issued before CAMMESA publishes its day-ahead programme (~21:30 ART on D-1), so the operator's forecast can never leak into the model. All available history of D5/D6 is downloaded; the training window length (e.g. 3, 5, 10, all years) is selected on validation, not fixed a priori.
- Evidence: Fran's decision (issue time). Window: competing effects — slow climate trend vs faster structural changes (AC penetration, 2024 tariff changes, 2020 COVID) vs tree models' inability to extrapolate beyond extremes seen in training. Fran's hypothesis (recent decade suffices) is tested, not assumed.
- Previous state: issue time 10:00 D-1 provisional; history limited to D1 daily file.

## 2026-10-23 — Daily collection of CAMMESA documents on AWS; history from PC
- Change: Lambda mode "docs" (schedule 23:30 ART, 8-day look-back) archives new Programación Diaria and Parte Semanal attachments into S3, skipping keys already present. Historical download (2010 →) runs once on the PC and is uploaded with aws s3 sync (same key layout).
- Evidence: Programación Diaria published ~21:30 ART on D-1; weekly reports re-published ~1 month later (e.g. se530103.zip on 2010-01-07 and 2010-02-08), so a look-back window is required. Splitting the one-off history into < 15-min Lambda runs adds orchestration code for no lasting benefit.
- Previous state: documents downloaded only manually from the PC.

## 2026-10-23 — Weather source: Open-Meteo reanalysis (train) and archived forecasts (backtest)
- Change: D4 split into D4a (ERA5 reanalysis, 1940 →) and D4b (Previous Runs API: day-1 forecasts; most models 2024-01 →, GFS 2 m temperature 2021-03 →). O2 resolved: CC BY 4.0, free non-commercial ≤ 10,000 calls/day.
- Evidence: Open-Meteo documentation and site, checked 2026-10-23. Fran's manual reanalysis download (Río Cuarto, 2000 →) confirmed access; Río Cuarto is not a demand centre, so locations follow demand centres.
- Previous state: D4 license and coverage unknown.

## 2026-10-23 — SMN discarded as weather source
- Change: SMN station data not used.
- Evidence: Fran checked: little data online, formal request required, possible charges.
- Previous state: SMN proposed for station cross-checks.

## 2026-10-23 — Historical Forecast API rejected as day-ahead input
- Change: Open-Meteo Historical Forecast API not used as a forecast input.
- Evidence: it assembles the initial hours of each run (near-analysis), not day-ahead forecasts.
- Previous state: not decided.

## 2026-10-23 — Weather design: ERA5 for training/oracle, Previous Runs day2 for evaluation and production
- Change: test and production inputs are archived forecasts (previous_day2, pinned model); ERA5 used for M-obs training and oracle results only. Lead-time vs latest-run consistency to be resolved (method_notes W1).
- Evidence: previous_day1 leaks for valid hours after ~10:00 ART of D given a 10:00 ART D−1 issue time.
- Previous state: generic "archived forecasts" rule.

## 2026-10-23 — M-obs vs M-fc comparison added
- Change: two models differing only in training weather source (ERA5 vs archived forecasts), both evaluated with forecasts; Diebold-Mariano with HLN correction on the shared test period. Split table depends on M2 (option (d) with GFS 2021-03 pending check C2).
- Evidence: Fran's method discussion; GFS 2 m temperature archive from 2021-03.
- Previous state: single model, weather source unspecified.

## 2026-10-23 — Email sent to CAMMESA (contact form)
- Change: O1/O5 request sent: authorization to publish derived metrics and plots (no raw data), definitive vs provisional Parte Semanal versions, and no-objection to low-volume automated queries.
- Evidence: sent by Fran 2026-10-23 ~15:00 ART. Follow-up if no answer by 2026-11-20; without answer, publish code and aggregated metrics only, risk accepted and logged.
- Previous state: no contact with CAMMESA.

## 2026-10-23 — Finding: archived-forecast coverage (check C2)
- Change: none yet (input to M2/M3). Option (d) feasible for temperature only.
- Evidence: Open-Meteo Previous Runs API probe, Buenos Aires, previous_day2. gfs_global temperature_2m 2021-03-24 → present with a 22-day gap 2023-12-29 → 2024-01-20; other GFS variables from 2024-01-20; ecmwf_ifs025 from 2024 (variable-dependent).
- Previous state: coverage assumed "most models from 2024-01, GFS temperature from 2021-03" (documentation only).

## 2026-10-23 — M-obs vs M-fc: temperature-only clean comparison; validation 2025, test 2026 (proposed)
- Change: M-obs and M-fc differ only in temperature source; other weather variables evaluated separately. Proposed splits: validation 2025, test 2026-01-01 → 2026-09-30 (end fixed before any result), forward test afterwards. Final confirmation in SPEC section 4.
- Evidence: Fran's decision; GFS temperature archive 2021-03-24 → (gap 2023-12-29 → 2024-01-20); other variables only from 2024-01-20; 2025 has complete forecast inputs. Disclosure: 2026-01 mean daily energy seen during inspection (descriptive only).
- Previous state: validation 2023 or 2024, test 2024–2025; comparison scope undefined.

## 2026-10-23 — Test end date fixed; EDA rule for setting success thresholds
- Change: test period ends 2026-09-30 (fixed now; later days belong to the forward test). Success thresholds are derived from EDA and validation-period measurements (e.g. B0 and B1 errors in 2025), not from priors. EDA is unrestricted on training and validation data (≤ 2025-12-31); on the test period only data-quality checks are allowed (gaps, units, duplicates), never feature–target relationships or baseline errors.
- Evidence: Fran's decision (test end; EDA before fixing numbers). v0.1 thresholds were priors without data.
- Previous state: test end open; thresholds S1–S3 set as priors in SPEC v0.1.

## 2026-10-23 — v1 scope: spatial design A′ and experiment budget; deferred lines in ROADMAP
- Change: v1 weather input = degree days per CAMMESA area (area-specific bases), demand-weighted into national CDD/HDD. Experiment budget: M-obs vs M-fc × ≤ 3 training windows. Deferred lines (per-area features, extra weather variables, hourly, regional, probabilistic, ECMWF, drift reports, API, agent interface, MLflow registry) recorded in docs/ROADMAP.md.
- Evidence: Fran's decision to limit branching; collinearity and short archive for richer designs.
- Previous state: designs A/B and extra variables open.

## 2026-10-23 — Finding: historical CAMMESA documents downloaded (check C4)
- Change: C4 resolved; B1 (CAMMESA day-ahead programme) available for validation 2025 and test 2026. Attachment validation tightened (zip files must start with the zip signature; other files > 100 bytes).
- Evidence: PC download finished 2026-10-23. Programación Diaria 2010-01-01 → 2026-10-22: 6,315 files, 6,111 of 6,139 days (28 isolated missing days, no run ≥ 3 days), 3.1 GB; 1 error (PD241022, 72 bytes) and 1 invalid 22-byte file (PD230629) accepted by the previous check. Parte Semanal 2010-01-07 → 2026-10-22: 1,910 files, 0 errors, 3.4 GB.
- Previous state: archive start and coverage unknown; size estimated 2–3 GB (actual 6.5 GB).

## 2026-10-23 — Correction: PD230629 22-byte file is an empty zip, not a download error
- Change: none to the collector. P1 cleaning must skip zip archives with zero entries.
- Evidence: forced re-download of 2023-06-28 returned two documents named PD230629.zip with different doc ids: 22 bytes (empty zip, end-of-central-directory record only) and 480,409 bytes (valid). The day is complete.
- Previous state: the 22-byte file was attributed to a collector validation bug (entry above).

## 2026-10-24 — CAMMESA reply: publication allowed; definitive values after DTE (O1, O5 resolved)
- Change: O1 resolved — publishing derived metrics and plots from information published on the CAMMESA website is allowed (raw data still not redistributed, by project choice). O5 resolved — provisional values are revised when the monthly economic transactions document (DTE) is issued; the later publication holds the definitive values and is the reference. Rule for P1: use the latest publication per week/day; use provisional values only for days without a definitive version, and flag them. Question on automated queries not answered (follow-up optional).
- Evidence: email from CAMMESA, Estadísticas y Control area (Gerencia de Análisis y Control Global), received 2026-10-24. Copy kept privately by Fran; names and addresses not recorded in the repository.
- Previous state: O1 and O5 open; email sent 2026-10-23.

## 2026-10-24 — FAMAF station data: original station destroyed; alternatives identified (C6)
- Change: C6 stays optional. Candidate sources: new FAMAF station (period unknown), Observatorio Hidro-Meteorológico de Córdoba station (Ciudad Universitaria), and the OHMC station viewer for Córdoba province.
- Evidence: reply from FAMAF contact, 2026-10-24: the former FAMAF station was destroyed by lightning years ago; a new one was installed recently.
- Previous state: FAMAF station assumed to have a continuous record.

## 2026-10-24 — Splits moved one year; no ARIMA; decision sequence and extremes rule
- Change: test 2025-10-01 → 2026-09-30 (full year); validation 2024-10-01 → 2025-09-30; training ends 2024-09-30; unrestricted EDA only ≤ 2025-09-30. Model families: gradient-boosted trees vs hybrid (linear on degree days + trees); ARIMA-type models excluded. Decisions taken sequentially on validation: family → window length → weather source (M-obs vs M-fc). Threshold p* replaced by a pre-registered comparison: hybrid kept if not worse on validation (one-sided DM, 5 %) and better on out-of-range days (seasonal P99, year-by-year) of a rolling-origin backtest 2016 → 2025-09-30.
- Evidence: Fran's decisions (full-year test; no ARIMA). A P99 subset of a 273-day test has ~3 days (no power), so extremes are evaluated on the rolling backtest. A fixed p* threshold would almost always reject the hybrid (records are rare by construction).
- Previous state: test 2026-01-01 → 2026-09-30, validation 2025; threshold p* proposed.

## 2026-10-24 — Audit fixes (SPEC v0.5)
- Change: (1) production lags come from D3; backtests use provisional D5 as the D3 proxy, accepted only if D3–D5 daily differences have median ≤ 0.5 %, else lags restricted to data published by issue time. (2) Targets use definitive D5; features use the version available at issue time. (3) B1 = last D6 file published before 00:00 ART on D. (4) Targets are net demand; peak = max of hourly averages; demPrevista energy by trapezoidal integration. (5) SPEC rewritten consistent with DECISIONS; issue time fixed at 10:00 ART D-1. (6) Promotion by 56-day shadow mode instead of in-sample comparison. (7) Remote Terraform state required before CD. Minor: personal name removed from method_notes; .gitignore data/logs anchored to repo root; Lambda timeout 900 s; drift alarm relative to B0; GFS upgrades noted; request counts corrected.
- Evidence: audit of 2026-10-24 (D5 published ~4 days after week end; 627 of 709 weekly attachments re-published; 159 target days with several D6 files, 33 re-published on D or later; promotion compared a challenger on its own training data; local Terraform state blocks S7 and CD).
- Previous state: SPEC v0.4 with contradictions listed in the audit.

## 2026-10-24 — Issue time 10:00 ART D-1 and net-demand targets confirmed
- Change: SPEC v0.5 values confirmed by Fran: issue time 10:00 ART on D-1; T1/T2 defined on net demand.
- Evidence: CAMMESA forecasts are never model inputs, so issue time affects comparison fairness, not leakage. The day-ahead programme for D appears ~21:30 ART on D-1, after the issue time. Net demand matches what CAMMESA programmes (B1).
- Previous state: both set provisionally in SPEC v0.5.
