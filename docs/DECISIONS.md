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

## 2026-10-25 — Finding: weekly balance.txt is stale; O9/O10 need other sources
- Change: D5 balance.txt discarded. O9 (net demand) checked against D1 gross energy instead; O10 (load shedding / FALLAS) has no source yet. Parsing rules for SEwwarea.dem recorded in docs/data_inventory.md (section boundaries, fixed-width slicing, overflow fields).
- Evidence: identical balance.txt (same sha256, file date 2016-09-21) in all 98 sampled weekly zips 2016–2025. Area-sum / D1-gross ratio medians 0.93–0.95 but with tails > 1, unresolved.
- Previous state: balance.txt assumed to hold weekly net/gross demand and FALLAS (statement made 2026-10-23, incorrect).

## 2026-10-25 — Parsers for D5 and D6; B1 source switch date (proposed)
- Change: src/sadi_forecast/parsing.py with tests on synthetic fragments. Rules: fixed-width slicing, section boundaries, overflow fields, unmarked rows treated as missing (never summed), weekly files split at month boundaries. Proposed for B1: balance.txt through target day 2024-11-12, BALANCE.csv from 2024-11-13; the definitional step (~+0.15 %) falls in validation and is documented; the test period is CSV only.
- Evidence: 252/252 weekly files consistent with their day range; 45 unmarked zero-filled rows; CSV vs txt overlap differences documented in data_inventory.md.
- Previous state: no parsers; B1 format rule undefined.

## 2026-10-25 — Programme (D6) source anomalies handled in the parsers
- Change: corrupt archives are skipped with a warning (3: PD170925 member-name mismatch, PD180105 and PD230324 not zip files); BALANCE.csv headers read case-insensitively (7 files with lower-case headers, 2025-08 onward); balance.txt files whose printed daily total differs from the sum of the hours are kept, with the difference stored in total_mismatch_mwh (2 files: +3511 MWh PD211008, +202 MWh PD240722; rounding alone gives at most 12).
- Evidence: first full build_tables run, 2026-10-25 (12 warnings over ~6,300 programme archives).
- Previous state: a single corrupt member aborted the build; files with total mismatch were rejected.

## 2026-10-25 — Finding: missing D5 coverage, two causes
- Change: (1) collector gap: two Parte Semanal listing windows (2022-06-03, 2022-07-01) failed after retries during the historical download; recovery re-run requested (expected to restore May–July 2022 coverage, since files are stored by publication date). Collector to print a summary of failed windows at the end of a run. (2) source gap: some weeks lack one area in every available version (LITORAL 22 days in 2021-08, NOA 20 days in 2022-02); handling tracked as O12.
- Evidence: monthly_coverage.png (EDA run 2026-10-25); manifest entries with status None for those windows; parser counts of unmarked area rows.
- Previous state: coverage assumed complete after the download.

## 2026-10-25 — Finding: D5 area sum is not definition-stable over time and differs from programmed net demand (O13)
- Change: none yet; target source decision open (O13). Options: (1) D5 target from 2020 only; (2) D1 gross for long history (does not cover the test period unless updated); (3) calibrating D5 against B1 (not recommended: mixes target and benchmark). B1 comparison must use a target with the same definition as programmed net demand, or report the definitional bias separately.
- Evidence (data ≤ 2025-09-30): D1 gross / B1 programme stable every year (median 1.025–1.046, p05–p95 ≈ 0.98–1.08). D5 / B1 moves: 0.946–0.952 in 2010–2012, up to 1.003–1.014 in 2016–2017 (p95 1.15), 0.966–0.991 in 2020–2025. D5 / D1: 0.91–0.93 in 2010–2012, up to 0.976 in 2017 with 60 % outlier days, 0.93–0.94 in 2020–2025. Persistent level increases in several areas in 2016–2017 (GBA +9–11 % vs 2014 and 2019). No parsing duplicates, no missing-area effect, ±1-day shifts explain < 10 % of outliers.
- Previous state: D5 area sum assumed to be SADI net demand, consistent over 2010–2026.

## 2026-10-26 — O13: Informe Síntesis Mensual bases (D7) adopted as candidate target source
- Change: D7 added as the candidate target source for national net demand, subject to the definition check (scripts/check_sintesis.py: D7 "demanda local" vs B1, D1 gross and D5, per year, data ≤ 2025-09-30). Parte Post Operativo (daily, .mdb, 2010 →) not adopted: Access parsing, 2–3 versions per day and 16 years of possible schema changes, for no gain over D7 within the planned training window. D5 kept as area reference only, pending the check. Weather download started for 15 candidate points (ERA5 2015 →, GFS previous runs 2021-03-24 →).
- Evidence (structure only, no values read): each December base holds the four calendar years ending in it. 2021-12 base, "Base de datos Horaria-Diaria 2021-12.xlsx", sheet DEMANDA: 2018-01-01 → 2021-12-31, 1461 days × 24 hours, columns Gran Usuario MEM, Distribuidor, Demanda local, Exportación, Bombeo, Pérdidas, Demanda total. 2022-12 base: "Demanda Horaria por Tipo.xlsx" and "Demanda Horaria por Provincia.xlsx", 35,064 hourly rows each (2019–2022). 2018-12 and 2015-12 bases: no hourly sheet. CAMMESA staff (2026-10-26) pointed to these bases; their team does not produce the Parte Semanal.
- Open: D7 is published monthly with ~1 month lag, so production monitoring needs a daily source with the same definition (D2/D3 integrated), reconciled monthly against D7. Training would start 2018-01-01 (≤ 6.75 years before validation).
- Previous state: target source open between D5 from 2020, D1 gross and D5 calibrated on B1.

## 2026-10-26 — Finding: D7 layout changes from the 2024-12 base
- Change: parser requires only "demanda local"; total demand, exports, pumping and losses are optional. Nested duplicate packages are read once. The check takes total demand from the latest base that still has it (bases ≤ 2023-12, days ≤ 2023-12-31).
- Evidence: all six bases parsed (structure only): 2021-12 → 2026-09 cover 2018-01-01 → 2026-09-30, every day 24 hours; by-type sheets of the 2024-12, 2025-12 and 2026-09 bases have only Gran Usuario MEM, Distribuidor and Demanda local; the 2023-12 package contains a nested copy of itself; province sheets: 22 provinces plus total, 2019 onward.
- Previous state: total demand assumed present in every base.

## 2026-10-26 — Finding: D7 definition check (O13), data ≤ 2025-09-30
- Change: none yet (proposal pending Fran: target = D7 demanda local; B1 converted to the same definition).
- Evidence: D7 revisions between bases negligible (2,465 overlap days: median 0 %, p95 0.019 %, max 0.64 %, 3 days > 0.1 %). D7 local / D5 national median 0.994–1.003 every year 2018–2025 (p05–p95 0.935–1.066 in 2018–19, 0.95–1.02 from 2020). D7 local / D1 gross 0.929–0.941. Province sum = D7 local (median 1.000). D7 local / B1 median 0.958–0.985, drifting by year; (local + losses) / B1 median 1.001–1.003 in 2018–2020, 1.007–1.016 in 2021–2023 (losses 3.2–4.1 % of local; not published from the 2024-12 base). Daily IQR of local / B1 ≈ 3 %.
- Interpretation: B1 (programme DEMANDA NETA) includes transmission losses; D7 local does not. Comparing a local-demand model with raw B1 would credit the model with ~3–4 % definitional bias.
- Previous state: B1 assumed to share the target definition.

## 2026-10-26 — Finding: live demand (D3) is not on the target definition (post-test days only)
- Change: none yet; target = D7 demanda local confirmed by Fran (2026-10-26). Live-source definitions are checked on days after TEST_END (from 2026-10-01; scripts/check_live_definition.py), never on test days.
- Evidence (2026-10-01 → 2026-10-19): D3 daily energy / D5 national median 1.069 (1.059–1.086), higher on Sundays (≈ 1.083) than on weekdays (≈ 1.06); with D7 local ≈ D5 (2018–2025), D3 ≈ 1.07 × local, close to D1 gross / D7 local ≈ 1.072 (2018–2025), so D3 is most likely gross demand. Subtracting programmed pumping removes part of the Sunday excess (1.083 → ≈ 1.07). D3 / B1 1.052 (1.018–1.087); D5 / B1 0.980 (0.941–1.012). D2 demPrevista (CAMMESA intraday forecast) / B1 1.044–1.054 (5 days): on the D3 scale. Programmed losses 2.2–3.5 % of B1; B1 = DEMANDA NETA excludes them (balance: DEMANDA = NETA + BOMBEO + PERDIDAS).
- Consequences: (1) the actual observed daily in production (D3) differs from the target by a varying, not constant, ≈ 6–9 %; production lag features from D3 cannot be used unconverted; (2) daily live scoring against D3 needs a conversion, definitive scoring is monthly against D7; (3) B1 needs conversion to the target definition (trailing ratio).
- Pending: direct D3 / D7 local check when the 2026-10 Síntesis base is published (~late November).
- Previous state: D3 assumed to measure the target quantity (SPEC D3 role: production lag features).

## 2026-10-26 — Finding: target can be built exactly from the Síntesis supply balance; daily source and comparator by addition
- Change: proposed to Fran (not yet decided): target = energy supplied to the domestic system = Síntesis "Oferta Total Horaria" (generation by technology + imports) minus exports ("Import-Export Horaria"); this equals local demand + transmission losses + pumping. Comparator = programmed DEMANDA NETA + PERDIDAS + DEMANDA BOMBEO (Programación Diaria), built by addition, no estimated factors. Daily actuals for production from the Parte Post Operativo (generation per unit incl. imports; published D+1 ≈ 19:00, complement ≈ 1 month later). Ratio-based conversions between sources are discarded (Fran, 2026-10-26: ratios are not guaranteed stable day to day).
- Evidence: 2020–2023 (base 2023-12): supply / total demand = 1.00000 every day; (supply − exports) / (local + losses + pumping) = 1.00000 every day. Supply and export sheets exist in every base 2022-12 → 2026-09 (in the 2023-12 base the import column header is empty and a TOTAL column follows; in 2025-12 the last column is "Importación"). Pumping / local median 0.26–0.52 %, up to 3.9 % on single days, and not published separately from the 2024-12 base, so local + losses alone cannot be built after 2023. Parte Post Operativo 2023-06-14: sum of VALORES_GENERADORES.ENERGIA 479,017 MWh vs Síntesis supply 479,686 MWh (−0.14 %); CONTROL_VALORES_CC duplicates the combined-cycle units and must not be added; the .mdb has no demand or loss table. Programme sum / target 2018–2023: median 1.013–1.021 per year, absolute daily error median 2.2 %, p90 5.6 % (programmed net demand ≈ +3 % over real local demand, programmed losses ≈ 30 % below real losses; extreme days include the 2019-06-16 blackout).
- Pending: Post Operativo vs Síntesis on a sample of days per year (with exports) and on October 2026; difference between daily and complement versions; publication-time distribution (newest actual at 10:00 on D-1 is likely D-3).
- Previous state: target = D7 demanda local (2026-10-26, earlier today); B1 = programmed net demand only.

## 2026-10-26 — Target definition: supplied energy including pumping; Parte Post Operativo as the single source
- Change (Fran): target = energy supplied to the domestic system = generation + imports − exports (= local demand + transmission losses + pumping); pumping included. Source for training, live and evaluation: Parte Post Operativo. Síntesis supply balance is used only as an independent check of the summation rules. Comparator: programme sum NETA + PERDIDAS + BOMBEO; reported as bias (mean error) and spread separately, because CAMMESA's programme may overestimate on purpose (security of supply), which a plain absolute-error comparison would count against it. Only the sum is compared: the split into net demand and losses may follow different allocation rules in each document.
- Evidence: 2023-06-14, sum of VALORES_GENERADORES.ENERGIA: daily version (published 2023-06-15 18:54) 479,017 MWh; complement version (2023-07-11) 479,685 MWh; Síntesis supply 479,686 MWh. The Síntesis reproduces the complement version; the daily version differs by −0.14 % on that day. Export tables (EXPORTACION_ENTREGADA, INTERCAMBIO_INTERNACIONAL) empty on that day: export location still to be verified on a day with exports. October 2026: Friday–Sunday reports published together on the following Tuesday (2026-10-13); weekday reports the next day 18:30–20:45.
- Previous state: target = Síntesis demanda local; comparator = programmed net demand.

## 2026-10-27 — Finding: Parte Post Operativo validated against the Síntesis; exports come from elsewhere; daily versions have gross errors
- Change: Parte Post Operativo added to the collector (`docs --doc postoperativo`; attachments requested with each publication's own nemo; daily job look-back 45 days so complements are caught). Historical download 2018 → started 2026-10-27 on the PC. Target construction: complement supply (sum of VALORES_GENERADORES.ENERGIA, imports included) − exports. Exports: actual values from the Síntesis (hourly, monthly publication); for live provisional values, programmed exports from the Programación Diaria.
- Evidence (41 sample days 2018-02 → 2024-08, chosen per quarter plus high-export days): complement supply vs Síntesis supply within 0.00–0.18 % in 2018–2019 and 0.00–0.07 % from 2020 (exact to the MWh on most days). The Post Operativo has no export values: export tables empty or zero on days with 27–55 GWh of exports (2018-09-30, 2020-11-15/19, 2021-08-21); the "Exportaciones" HTML pages are empty too. Programmed exports (Programación Diaria: balance.txt "EXP." lines, BALANCE.csv "Exportacion") vs Síntesis actual exports, 2018 → 2026-09, error as share of supply: median 0, p90 ≤ 0.62 %, max 12.2 % (2021). Daily vs complement: median absolute difference ≈ 0.13 %, typical up to ~1 %; gross errors in 3 of 41 days (2022-05-15 +6.8 %; 2022-08-15 first daily +32 %, re-issued the next morning at −0.3 %; 2023-11-14 +2.7 %); 2020-02-15 has two complements (398,161 and 410,255 MWh; Síntesis 398,170). Publication: daily report D+1 18:00–21:00; Friday–Sunday reports on Monday or Tuesday. Zip size ≈ 1 MB/day in 2018, ≈ 6 MB in 2023.
- Consequences: live values need validity checks (against the programme and the previous days) and must be replaced by the complement when published; a rule is needed for days with several complements; backtest lag features must use the version available at issue time, including its errors.
- Pending: sample 2024-11 → 2026-10 (requests timed out during the concurrent historical download); full comparison once the download finishes.
- Previous state: Post Operativo checked on one day (2023-06-14).

## 2026-10-27 — SPEC v0.6: targets on supplied energy; live data handling rules
- Change: SPEC sections 1, 2, 2.2, 2.3, 4.2, 4.5, 6 and 10 updated. Targets T1/T2 on supplied energy (D8 complement supply − D7 exports). Information set by archived publication timestamps (newest actual D-3 on Tuesday–Friday issue days; horizon ≥ 3, was 2). B1 = programmed NETA + PERDIDAS + BOMBEO. Live handling (Fran, 2026-10-27): validity check of daily reports against B1 and the same weekday of the previous 4 weeks (thresholds O14, from training data); automatic replacement by the complement and by D7 exports, keeping provisional and definitive scores; multiple complements resolved against D7 supply, never by publication order. Bias and spread reported separately. D2/D3/D5 demoted to archive/reference. O8, O9, O12, O13 closed; O14–O16 opened. Lambda docs job also archives D8 (45-day look-back).
- Evidence: DECISIONS 2026-10-26 and 2026-10-27 entries above.
- Previous state: SPEC v0.5 (net-demand targets from D5, D3 lag features, horizon 2).

## 2026-10-28 — Access reader switched to mdb-reader (Node)
- Change: Post Operativo databases are read with the Node package mdb-reader 3.1.0 (tools/mdb, pinned with package-lock.json) called in batches from Python; access-parser removed. Node.js becomes a local requirement for building the d8 table.
- Evidence: access-parser 0.0.6 (PyPI) and its master branch (2025-01-21) fail on every row of VALORES_GENERADORES in a 2024 database (15,936 of 15,936 rows), and log a warning per numeric field in older ones. mdb-reader reproduces the browser totals: 2018-02-15 426,600 / 426,325 MWh (daily / complement), 2019-05-15 complement 356,336, 2024-05-15 daily 444,819. The first O14 run (same day) therefore lacked the 2024 databases.
- Previous state: access-parser (2026-10-27).

## 2026-10-28 — Finding: Post Operativo archive anomalies (full parse)
- Change: none; the parser skips them with a warning.
- Evidence: full parse of 6,926 files → 6,918 documents, 3,222 days (3,315 daily reports, 3,603 complements). Skipped: 1 truncated daily report from the source (2023-05-08, published 2023-05-09; its bytes start with a 2020 member, PO200901.chm; the complement of that day is valid) and 7 PDF notices "CAMBIOS BASE DE PUBLICACION POSOP" (listed 2025-11-13 → 2025-11-20). The notice (Res. 400/25) adds tables CVP and PRECIO_NODO and new columns to VALORES_GENERADORES (fuel management flags, remuneration percentage, factor kP); GRUPO, HORA and ENERGIA are not mentioned as changed. To verify: supply before/after 2025-11 against D7.
- Previous state: archive assumed homogeneous.

## 2026-10-28 — O14 second run (dates from the databases): findings; definitive target from D7 (proposed)
- Change (proposed, pending Fran): definitive target = D7 supply − D7 exports for every day D7 covers (2018-01-01 → 2026-09-30); the D8 complement becomes a quality check, not the value. Validity check redesigned: structural rules (24 hours present, positive supply, units reported ≥ 1st percentile of units / median of complements in the previous 28 days) plus r1 (vs programme); r2 dropped from the rule. check_validity.py scores each rule against the report's own error (daily supply vs complement) and separates programmed-vs-actual export errors.
- Evidence (training days, 2,465 dates, 2,542 daily reports): complement vs D7 supply median 0.0034 %, 72 days above 0.2 % (mostly 0.2–0.4 % in 2018), max 10.2 %; with D7 as reference these days no longer lose their target. The four −100 % reports (2020-06-23, 26, 27, 28) are files named BKPO*.zip listed as daily reports, with empty tables and no FECHA. Other large report errors are partial or wrong reports: 2018-07-20/21 −17/−26 % (551/541 units vs 565 in the complement), 2023-06-24 −11 % (669 vs 671 units), 2022-05-13/16 and 2023-07-11 +10 to +14 % (same units, inflated values). 2021-11-10 (+13.8 % vs definitive) is a programmed-export miss, not a report error (report within 0.01 % of its complement). Daily/complement unit-count ratio over 3,134 days: q0.1 % 0.952, q1 % 0.984, median 0.998.
- Previous state: definitive target = chosen complement − D7 exports; days with complement > 0.2 % from D7 excluded.

## 2026-10-28 — Target from D7; validity check fixed (O14); point weights (O3); calendar; feature table; baselines
- Change (Fran): definitive target = D7 supply − D7 exports; D8 complements are a quality check. Validity check of daily reports: 24 hours, supply > 0, |provisional / programme − 1| ≤ 0.10 (O14 closed). Point weights (O3 closed), rule fixed before any model: province shares of local demand (D7 province sheet, 2019-01-01 → 2024-09-30); each province → weather point nearest to its main demand centre; Buenos Aires split by Parte Semanal area shares (GBA 0.759 → caba; BAS → mar_del_plata and bahia_blanca equally). Calendar from the `holidays` package (holiday, bridge, Holy Thursday, 24/31 Dec, neighbours). Feature table (scripts/build_features.py): target, lag_3 … lag_14 as known at 10:00 on D-1 (D-1 and D-2 are never published by then), calendar, demand-weighted temperature and degree days (HDD bases 14/16/18 °C, CDD 20/22/24 °C, per point before weighting) from ERA5 and GFS previous_day2. EDA target figures moved to eda/eda_target.py with output in data/eda/figures (local, Fran).
- Evidence: weights caba 0.376, rosario 0.093, cordoba 0.075, bahia_blanca 0.066, mar_del_plata 0.060, mendoza 0.056, resistencia 0.054, tucuman 0.046, comodoro 0.042, neuquen 0.031, san_juan 0.028, santa_fe 0.028, salta 0.024, posadas 0.019, la_plata 0 (results/point_weights.csv). Feature table 2018-01-01 → 2026-09-30, 3,195 days; missing: GFS 37.6 % (starts 2021-03-24), lag_3 35.7 %, lag_4 20.4 %, lag_7 1.7 % (reports of weekends and holidays come late). GFS − ERA5 weighted daily mean temperature: mean +0.78 °C, SD 0.67 °C. Baselines (results/baselines.json), validation 2024-10-01 → 2025-09-30: B0 (lag_7, else lag_14) MAPE 9.20 %, bias +2.49 %, SD 13.0 %; B1 (programme) MAPE 3.39 %, bias +2.98 %, SD 3.05 % (358 days). Training: B0 MAPE 8.81 %; B1 MAPE 2.80 %, bias +2.06 %, SD 3.21 %.
- Previous state: definitive target from D8 complements; thresholds open; weights open.

## 2026-10-29 — Audit 2026-10-29 applied; SPEC v0.7 frozen until backtest results
- Change (Fran): label embargo in refits (labels only up to targets.definitive_available_until(refit date); Síntesis of month M taken as published on day 20 of M+1); extremes backtest moved to 2021-01-01 → 2025-09-30; reference level = median of lag_7, lag_14, lag_21, lag_28 as known at the issue time (≥ 2 values; Fran chose four weeks), with the mean weather of the same days, used by B0 and by the model's relative target; version mix stated in SPEC 4.2; provisional scores flagged as biased towards B1 and reported with and without rejected days; S4 measures D6/D8 archiving; one challenger in shadow at a time; units rule removed from check_validity.py (it used complements not yet published at the issue time; it was never in the adopted check); missing export cells read as missing, not zero; groupby().last() replaced by whole-row selection (it could mix versions); point weights asserted to sum to 1; Post Operativo builder tested with a fake reader; EDA figures back in results/eda/figures; README and method_notes marked; a CAMMESA staff member's first name removed from the 2026-10-26 entry (privacy; the only edit to a past entry).
- Evidence: export-error statistic recomputed on 2018-01-01 → 2025-09-30: median 0, p90 0.26 %, p99 1.83 %, max 13.8 % (2021-11-10), 2,811 days. No missing export cells in the 2021-12, 2023-12 and 2026-09 bases (the fix is preventive). B0 with the four-week reference, validation: MAPE 9.07 %, bias +2.28 %, SD 12.2 % (lag_7 alone: 9.20 %). Reference available on 99.5 % of days (4 values on 3,035 of 3,195).
- Previous state: SPEC v0.6.

## 2026-10-29 — Backtest protocol details fixed before any model is run
- Change: details SPEC 4.3 leaves open, fixed before the first fit (no validation result seen):
  - Relative target y = ln E(D) − ln ref(D); forecast = ref · exp(ŷ). Days without ref are not forecast (none in validation).
  - Features (both families, all steps): dow; day_kind, prev_day_kind, next_day_kind (categorical); off_day; doy_sin, doy_cos; temperature of D; Δ temperature and Δ degree days (HDD 14/16/18, CDD 20/22/24) of D minus the reference days; ln(lag_k / ref) for k = 3–6 (missing allowed); number of off days among the reference days. No trend term (trees do not extrapolate it; the relative target carries growth).
  - Trees: scikit-learn HistGradientBoostingRegressor, absolute-error loss, learning_rate 0.05, max_iter 400, max_leaf_nodes 15, min_samples_leaf 20, l2 1.0, no early stopping, random_state 0. No hyperparameter search for any model (same budget, zero, for every comparison).
  - F-hyb linear part: non-negative least squares of y on the six Δ degree days plus a free intercept (demand cannot fall when heating or cooling need rises; the constraint also handles the collinearity of the bases). Trees as above on the residual.
  - Weather inputs: M-obs trains on ERA5 (day D and reference days) and is evaluated with GFS for D and ERA5 for the reference days (observed by then). M-fc uses GFS for both. ERA5 evaluation reported only as "oracle".
  - Monthly refits on the first day of each month; training labels up to definitive_available_until(refit date).
  - Step 1 rule (SPEC 4.3): F-hyb kept if (a) the one-sided Diebold-Mariano test that F-hyb has larger absolute percentage errors than F-tree on validation is not significant at 5 %, and (b) its MAPE on out-of-range days of the rolling-origin backtest is lower. Otherwise F-tree.
  - Diebold-Mariano: loss = absolute percentage error; Newey-West variance with Bartlett kernel, lag floor(4 (n/100)^(2/9)); Harvey-Leybourne-Newbold correction with h = 2 (issue 14 h before D starts); Student t with n − 1 degrees of freedom.
  - Out-of-range day (extremes backtest): ERA5 weighted temperature of D, or ΔCDD22 vs the reference days, above the 99th percentile of the same calendar month in all previous years (2018 onward, the start of the feature table). Rolling origin: refit on 1 January of 2021…2025 with all labels available then; evaluation days need GFS, so the backtest runs 2021-03-25 → 2025-09-30 (GFS archive start). Cold days (below the 1st percentile) are reported, not used for the decision.
  - Steps 2 and 3: lowest validation MAPE wins; the Diebold-Mariano test against the runner-up is reported. Window candidates: 3 years, 5 years, all (from 2018).
- Evidence: SPEC 4.3–4.5; method_notes X1/X3 (monotone response, extrapolation only along degree days).
- Previous state: SPEC 4.3 without implementation details.

## 2026-10-29 — Post Operativo: Paraguayan share of Yacyretá excluded from supply
- Change: tools/mdb/supply.mjs drops unit YACYHIPY from the sum (cache version 4; all 6,918 documents re-read). tools/mdb/units_by_group.mjs added as a diagnostic (energy per unit of one database). The first step-1 backtest, run with the old sums, is kept in results/backtest/invalid/ and not used.
- Evidence: first backtest had validation errors correlated 0.81 from one day to the next and a +3.6 % bias. Provisional values (lags) exceeded the definitive target by a median of 1–2 % in 2025 vs 0.0 % in 2018–2024. Complement vs Síntesis supply, monthly median: 0.00 % until 2024-10; +4.9 % 2024-11, +4.2 % 2024-12, +4.4 % 2025-01, +4.8 % 2025-02, +3.1 % 2025-03, +0.6 to +1.0 % 2025-04 → 09. D1 gross energy vs Síntesis stayed at +2.4 to +3.6 % across the break, while D1 vs Post Operativo fell to −2 %: the Síntesis is consistent, the Post Operativo moved. Unit lists of 2024-09-15, 2024-12-15 and 2025-07-15: YACYHIPY first appears in 2024-11 (13,983 MWh of 367,467 on 2024-12-15, 3.8 %; 2,511 MWh on 2025-07-15); first day with the unit in the archive 2024-11-01. After the fix the complement vs Síntesis monthly median is within ±0.06 % in every month 2024-10 → 2026-09 (data-quality check; the test-period part of it is a source check, not a model result). This also covers the daily-total part of O15.
- Previous state: supply = sum of all VALORES_GENERADORES units.

## 2026-10-29 — Step 1 (family): F-tree
- Change: family = F-tree (rule of the backtest protocol entry above).
- Evidence (results/backtest/step1_family.json; M-obs, all history, monthly refits, GFS inputs, 365 validation days): MAPE F-tree 4.31 % (95 % CI 3.60–5.18), F-hyb 4.29 %, B0 8.68 %, B1 3.39 % (358 common days). Rule (a): one-sided Diebold-Mariano for F-hyb worse, p = 0.56 → not worse. Rule (b): extremes backtest 2021-03-25 → 2025-09-30 (1,628 days, 65 out-of-range days): out-of-range MAPE F-hyb 5.98 % vs F-tree 4.35 % (F-hyb bias +5.1 %: the linear part overshoots on hot days) → fails. In-range MAPE F-hyb 4.35 % vs 4.44 %. Oracle with ERA5 inputs: F-tree 2.81 %, F-hyb 2.65 % (upper bound, not a result). Error autocorrelation at lag 1: 0.72 (Ljung-Box p < 0.001).
- Previous state: family open.

## 2026-10-29 — Steps 2 (window) and 3 (weather source): 5 years, M-fc
- Change: window L = 5 years; weather source M-fc (GFS in training and evaluation). Final configuration: F-tree, 5 years, M-fc. Next: success thresholds S1/S2 from validation, then the single test evaluation.
- Evidence (results/backtest/step2_window.json, step3_weather.json; 365 validation days): step 2 MAPE 3 years 4.44 %, 5 years 4.27 %, all 4.31 % (5 years vs all, two-sided Diebold-Mariano p = 0.59; chosen by the lowest-MAPE rule). Step 3 MAPE M-obs 4.27 % (bias +1.60 %), M-fc 3.37 % (bias +0.10 %, 95 % CI 3.05–3.76), p = 0.005. Final vs baselines on 358 common days: model 3.36 % (bias +0.14 %, SD 4.41 %), B1 3.39 % (bias +2.98 %, SD 3.05 %), B0 8.68 %; model vs B1 two-sided Diebold-Mariano p = 0.89. Error autocorrelation at lag 1: model 0.44, B1 0.20. M-fc training data start 2021-03-25 (GFS archive), so the 5-year window holds 3.5 years for M-fc.
- Process note: step 2 was recorded in results/backtest/step2_window.json, which step 3 reads, before step 3 ran; this DECISIONS entry was written after both ran. Both choices follow the lowest-MAPE rule fixed in the protocol entry above.
- Previous state: window and weather source open.

## 2026-10-29 — Success thresholds S1 and S2 fixed before the test
- Change (Fran): S1 = skill vs B0 ≥ 0.50 with the 95 % CI lower bound > 0; S2 = upper bound of the 95 % CI of MAPE_model − MAPE_B1 < +0.50 percentage points (non-inferiority). Thresholds are deliberately demanding; if S2 fails, the result is reported as failing a demanding target, with the measured difference, and the model is not discarded for that reason alone. Test to be evaluated once with F-tree, 5 years, M-fc, monthly refits with the label embargo (scripts/evaluate_test.py).
- Evidence: validation skill 0.62 (CI 0.55–0.67), quarterly 0.53–0.69 (computed on MAPE); validation MAPE difference vs B1 −0.03 (CI −0.46 to +0.39), 358 days. A margin of 0.75 points was offered as the less demanding option and not chosen.
- Previous state: S1 and S2 thresholds open.

## 2026-10-29 — Test year evaluated once: S1 passed, S2 failed
- Change: none to the model. The configuration F-tree, 5 years, M-fc is the v1 model; results/test/test_evaluation.json is final and is not re-run (the script refuses if the file exists).
- Evidence (2025-10-01 → 2026-09-30, 362 days with model, B0 and B1; definitive targets): MAPE model 3.41 % (95 % CI 3.06–3.75), B1 3.09 % (2.76–3.45), B0 8.26 %. Bias: model −0.05 %, B1 +2.72 %; SD of error: model 4.39 %, B1 2.90 %. S1: skill vs B0 0.59 (CI 0.54–0.65) ≥ 0.50 → pass. S2: MAPE difference model − B1 +0.32 points (CI −0.10 to +0.68); upper bound above +0.50 → fail. Two-sided Diebold-Mariano vs B1 p = 0.11 (difference not significant either way). By quarter the model beat B1 only in 2026-Q3 (2.88 % vs 3.18 %). Out-of-range hot days: 9 (model 5.29 %, B1 4.41 %). Error autocorrelation: 0.51 at lag 1, 0.18 at lag 2. Provisional scores (first daily report): model 3.39 %, B1 3.16 %; 2 days rejected by the validity check, without them B1 3.09 %. Load-shedding days not reported (O10 open).
- Reading (Fran, before the run): S2 was set as a demanding target; failing it means the model is not shown to be within 0.5 points of the operator, not that it is worse than the operator by a significant margin.
- Previous state: test not evaluated.

## 2026-10-29 — Re-audit: post-hoc checks and the rule for replacing v1 (written before running them)
- Change (Fran): two post-hoc checks on validation only: (a) step 1 repeated under M-fc (F-tree vs F-hyb, 5 years; extremes backtest with yearly refits 2022 → 2025-09-30, since GFS training data start 2021-03-25); (b) bias-corrected M-obs: GFS temperature of D corrected per point by its mean GFS − ERA5 difference over 2021-03-25 → 2024-09-30, degree days recomputed per point, both families, 5 years. A variant replaces v1 (F-tree, 5 years, M-fc) only if its validation MAPE is lower with a two-sided Diebold-Mariano p < 0.05 against v1, and, for F-hyb, it also passes the extremes rule. If v1 is replaced, the new model's test-year score is reported as "test year already seen" and its clean evaluation is the forward test (S3).
- Evidence: re-audit 2026-10-29: the family was chosen under M-obs, whose evaluation inputs carry the GFS warm offset (+0.80 °C on 2021-03-25 → 2024-09-30, +0.75 °C on validation; data ≤ 2025-09-30), which inflates the linear degree-day part of F-hyb.
- Previous state: v1 frozen without these checks.

## 2026-10-29 — Re-audit checks: F-hyb under M-fc replaces F-tree; v1 = F-hyb, 5 years, M-fc
- Change: by the rule written before the checks (entry above), v1 becomes F-hyb, 5 years, M-fc. The test-year score of the new v1 is computed once and labelled "test year already seen" (results/test/test_evaluation_seen_hyb.json); the F-tree test result stays as the clean test of the pre-audit decision sequence. The clean evaluation of the new v1 is the forward test (S3).
- Evidence (results/backtest/sensitivity_reaudit.json; validation, 365 days, 5 years): MAPE F-tree M-fc (old v1) 3.37 %, F-hyb M-fc 3.11 % (95 % CI 2.80–3.51; bias +0.05 %, SD 4.09 %), F-tree bias-corrected M-obs 3.53 %, F-hyb bias-corrected M-obs 3.40 %. Diebold-Mariano vs old v1, two-sided: F-hyb M-fc p = 0.003 (mean |error| 0.26 points lower); F-tree bc M-obs p = 0.31; F-hyb bc M-obs p = 0.86. Extremes backtest under M-fc (yearly refits, 2022-01-01 → 2025-09-30, 1,332 days, 49 out-of-range days): out-of-range MAPE F-hyb 4.26 % (bias −0.58 %) vs F-tree 6.11 % (bias −3.13 %); all days 3.78 % vs 4.63 %. Per-point GFS − ERA5 offsets (2021-03-25 → 2024-09-30) range from −0.38 °C (Posadas) to +2.66 °C (San Juan).
- Reading: the step-1 choice of F-tree was an artefact of the GFS warm offset under M-obs (re-audit point 2). With the offset removed by bias correction, M-obs is still not better than M-fc (point 3: the step-3 gain is partly, not only, the offset). Under M-fc, 5 years equals all GFS data (point 4): window and weather choices are confounded.
- Previous state: v1 = F-tree, 5 years, M-fc.

## 2026-10-29 — Re-audit: T2 deferred; disclosures
- Change: (1) T2 (daily peak) deferred to v2 (ROADMAP F14); every v1 result is T1 (daily energy). Because the test year has been seen for T1, T2 will be evaluated on the forward test only. (2) Short-notice and provincial holidays: holiday check at issue time deferred to v2 (ROADMAP F15); the only short-notice national holiday found, 2022-12-20 (declared 2022-12-19 after the 10:00 issue), falls in training, so validation and test are unaffected. (3) Skill vs B1 (1 − MAE_model / MAE_B1) reported, not a criterion: test −0.10 (F-tree), −0.06 (F-hyb, test year already seen). S1 limitation stated in SPEC 5. (4) GFS − ERA5 offset statistics are quoted from data ≤ 2025-09-30 (+0.80 °C training, +0.75 °C validation); the earlier full-table figure (+0.78 °C) used test-period inputs (input-only statistic, disclosed). (5) Out-of-range hot-day comparisons are provisional until load-shedding days are listed (O10). (6) SPEC 9 R1 wording corrected: no days are excluded; the 2019-06-16 blackout is in the training targets. (7) README: the operator's programme is issued about 11 h after the model's issue time, with real-time operating data; the stale "no model" sentence removed.
- Evidence: re-audit 2026-10-29 (minor items and remedies 1, 4, 5, 6).
- Previous state: T2 in v1 scope; items undisclosed.

## 2026-10-29 — Calendar: two holidays on one date
- Change: calendar_ar.day_kind classifies each holiday of a date separately and keeps the strongest (holiday > bridge > non_working). Before, a date whose names included "Jueves Santo" was non_working even when it was also a national holiday.
- Evidence: found while checking the holiday list for the re-audit. Dates with two holidays 2018 → 2026: 2021-04-02 (Malvinas + Good Friday; holiday before and after the fix) and 2026-04-02 (Malvinas + Holy Thursday; non_working before, holiday after). Validation and the re-audit checks are unaffected; the test-year runs (both families) used the old category for 2026-04-02 and its neighbours' prev/next categories. Not re-run.
- Previous state: first matching name decided the category.

## 2026-10-29 — Production pipeline, local stage
- Change: (1) Live weather = Open-Meteo Previous Runs API, temperature_2m_previous_day2 (forecast 48 h before each valid hour), the input the model was trained and tested on (Fran); the fresher runs available at issue time are not used (ROADMAP F8). scripts/get_weather.py --live stores one file per point and issue date. (2) scripts/train_model.py trains v1 (F-hyb, 5 years, M-fc) on the labels published by a date and saves models/<date>/ (model.joblib, meta.json; not committed). A forecast uses the newest model trained on or before its issue date. (3) scripts/forecast.py builds the target day's features from the current tables with the same code as the training table (live_features.features_for), writes data/forecasts/<day>.json and never overwrites a day's first forecast (reruns are kept as <day>_rerun_<time>.json, flagged late if after the issue time). (4) Point weights are written with full precision (results/point_weights.csv); rounded to 5 decimals they changed the weighted temperature by up to 1e-4 °C. (5) scripts/get_sintesis.py --discover reads the yearly Síntesis pages for new monthly bases (registry.json), so definitive labels for monthly refits no longer need a code change. (6) build_features.py builds up to today.
- Evidence: scripts/check_live_parity.py: 40 random days 2021-05 → 2026-10, 0 differences between forecast-time and training-table model inputs (277 before the weights fix). End-to-end: a model trained as of 2026-09-01 reproduces the backtest refit of that date exactly (2026-09-02, -15, -30). Changing the calendar category of 3 training days (2026-04-01/02/03, calendar fix) moved those forecasts by 0.3–0.4 %: tree fits are sensitive to small training changes, which bounds how far single-day differences between model versions can be read. Model as of 2026-10-29: 1,789 training days, 2021-10-01 → 2026-09-30.
- Not yet checked: whether the Previous Runs API returns previous_day2 values for the future target day (not reachable from the development environment; first live run on the PC answers it).
- Previous state: no production code.

## 2026-10-29 — Calendar names fixed to Spanish (system-locale bug)
- Change: calendar_ar.day_kind asks the holidays package for Spanish names explicitly (language="es"); a test sets an English locale and checks the categories.
- Evidence: on Fran's PC two calendar tests failed (Holy Thursday classified as holiday). Without a language, holidays 0.107 translates names from LANGUAGE/LC_ALL/LC_MESSAGES/LANG; with an English locale "Jueves Santo" becomes "Maundy Thursday" and "Feriado con fines turísticos" becomes "Bridge Public Holiday", so Holy Thursday and every bridge day fell into "holiday". Every table behind the reported results (features, baselines, backtests, test, re-audit checks) was built in an environment without those variables, so with Spanish names; results unchanged. The first live forecast (2026-10-30, run on the PC) is unaffected: no bridge day or Holy Thursday in its 28-day window.
- Previous state: holiday names in the system language.

## 2026-10-29 — Production design (SPEC 7, v0.9)
- Change (Fran): forecasts and scores as one JSON file per day in S3 (DynamoDB dropped); monthly retraining inside the forecaster Lambda (GitHub Actions dropped for training); one Lambda container image with daily and monthly events; state tables in S3 updated incrementally; extra collector documents run at 09:00 ART; monthly refits of the champion configuration are routine, the shadow gate applies to challenger configurations only.
- Evidence: training v1 takes seconds on 1,789 rows; training on GitHub Actions would download the raw archive or tables from S3 every month (egress about USD 0.09/GB against the USD 1.00 budget); a JSON file per day needs no extra service and the static dashboard reads it directly.
- Previous state: SPEC 7 with DynamoDB and training on GitHub Actions.

## 2026-10-29 — Production service built (local and AWS code paths)
- Change: src/sadi_forecast/service.py (daily: state update, live weather, forecast once, scores; monthly: Síntesis, supply and feature tables, retrain, champion) on a Store (store.py: local folder or S3, same keys); scripts/run_service.py runs it on the PC; infra/forecaster/forecaster_handler.py runs it in Lambda; Dockerfile (Lambda Python 3.12 base, Node + mdb-reader, dependencies exported from uv.lock to infra/forecaster/requirements.txt, checked in CI); infra/forecaster.tf (ECR with immutable tags and a 3-image lifecycle, Lambda 3,008 MB / 900 s / 4 GB ephemeral, schedules daily 09:30 and monthly day 21 03:00 ART, error and missing-run alarms); collector docs run added at 09:00 ART; scripts/seed_state.py builds data/state/ and data/models/ for the first upload. Point weights ship inside the package (src/sadi_forecast/data/point_weights.csv, written by build_features.py). The newest weather fetch overrides earlier values on the days it covers (an earlier fetch can hold hours whose 48-h run did not exist yet).
- Evidence: in the development environment, with a fake weather fetch built from the archived previous runs, service.daily for issue 2026-10-22 forecast 2026-10-23 at 367,195.5 MWh, identical to the forecast from the training table; scoring wrote provisional and definitive errors for 2026-09-15 and provisional ones for 2026-10-10, and a second pass wrote nothing. The image and Terraform could not be built or validated there (no Docker daemon, no Terraform); first build, terraform validate and first run are on the PC.
- Previous state: local scripts only.

## 2026-10-29 — Forecaster deployed on AWS
- Change: image sadi-forecaster:2026-10-29-1 in ECR; Terraform added the forecaster Lambda, its role and policies, daily (09:30 ART) and monthly (day 21, 03:00 ART) schedules, error and missing-run alarms, the ECR lifecycle policy and the collector's 09:00 documents run (12 resources added, none changed or destroyed). State, champion model 2026-10-29 and the first forecast (2026-10-30) uploaded from the PC.
- Evidence: first invocation by hand (2026-10-29 07:42 ART): status 200; 6 programme documents archived on S3 and absent from the PC table were added to the state; no new Post Operativo documents; the existing 2026-10-30 forecast (373,937.8 MWh, issued 06:47 on the PC) returned unchanged. First scheduled forecast: 2026-10-31, issued 2026-10-30 09:30.
- Previous state: forecaster not deployed.

## 2026-10-29 — Public page design
- Change (Fran: publishing derived daily values is covered by CAMMESA's confirmation of 2026-10-24; caution on security): static page (site/: index.html, app.js, style.css; no external code, chart drawn in SVG by the page's own script, data inserted as text only) in a separate private bucket behind CloudFront with origin access control; response headers: Content-Security-Policy limited to the page's own files, no framing, nosniff, no referrer, HSTS; HTTPS only; cache 5 minutes; price class 100; no WAF (USD 5+/month, five times the budget; the free tier covers about 10 million views of a 100 KB page and the budget alarm covers the rest). The daily run writes data.json (last 90 days: forecasts, provisional and definitive actuals, operator programme, errors; live error summary on the days where both the model and the operator programme exist). The offline evaluation table on the page shows the hybrid's test-year number with the "already seen" note.
- Evidence: page checked in a headless browser with the same Content-Security-Policy, light and dark schemes, 1,100 and 390 px widths: no console errors, no horizontal scroll.
- Previous state: SPEC 7 named a dashboard without a design.

## 2026-10-29 — Public page deployed
- Change: image sadi-forecaster:2026-10-29-2 (writes data.json); Terraform added the site bucket, origin access control, cache and security-header policies, the CloudFront distribution, the bucket policy and the forecaster's data.json permission (10 added, 2 changed, 0 destroyed); page files uploaded; data.json written by a "site" invocation. Address: https://d32m7h2zphotl6.cloudfront.net.
- Evidence: the page responds 200 through CloudFront with Content-Security-Policy, Strict-Transport-Security, X-Frame-Options DENY, X-Content-Type-Options nosniff and Referrer-Policy no-referrer; a direct request to the site bucket returns 403.
- Previous state: page not deployed.

## 2026-10-29 — Operator programme on the page the evening before
- Change: the page shows the operator's programme for a day as soon as the state holds it (from the programme table, not only from scores); a new "evening" event at 23:50 ART (after the collector's 23:30 documents run) adds the documents published that day and refreshes the page, so tomorrow's programme appears about two hours after CAMMESA publishes it (about 21:30).
- Evidence: on 2026-10-29 at noon the page showed no operator value for 2026-10-30: the programme for a day is published the evening before, and the page took it only from scores, which need the day's actual.
- Previous state: operator value visible only after the day was scored (two days later).

## 2026-10-29 — Continuous deployment (design)
- Change: Terraform state moves to a versioned, encrypted S3 bucket with S3-native locking (Terraform ≥ 1.10). infra/bootstrap (applied once from the PC, local state) holds the state bucket, the GitHub OIDC provider and the deploy role, so the deploy role cannot change its own permissions (explicit deny on itself and on the provider). The role can be assumed only by this repository's jobs in the GitHub environments "plan" and "production"; its permissions are limited to the project's resource names, except CloudFront and read-only calls. Workflow deploy.yml runs after ci passes on main: job "plan" builds and pushes the image tagged with the commit hash and prints terraform plan; job "apply" (environment "production", manual approval) applies and publishes the page files. alert_email is a sensitive variable (kept out of public logs) stored as a GitHub secret. Image tags are commit hashes from now on; applies from the PC are no longer the deployment path.
- Evidence: SPEC 7 (CD after remote state, OIDC, approval) and S7; O11.
- Previous state: local state on the PC, manual deployment.

## 2026-10-29 — Continuous deployment: design revised after an independent security review
- Change: (1) deploy.yml runs on push to main (only the owner can push) instead of after ci through workflow_run, which a fork pull request from a branch named "main" could have triggered with its own code. (2) Two GitHub roles: sadi-github-plan (environment "plan", no approval) can only read and runs terraform plan with -lock=false; sadi-github-deploy (environment "production", manual approval) builds and pushes the image and applies. (3) The runtime IAM roles of the Lambdas and the scheduler, and their permissions, move to infra/bootstrap (imported, not recreated; new named inline policies; the old ones are deleted by the next apply of infra/); infra/ only reads them by name. The deploy role cannot create, change or delete any IAM entity (explicit deny); it may pass the three runtime roles only to Lambda and EventBridge Scheduler. (4) Explicit action lists for the deploy role: update-only for Lambda, schedules, alarms, CloudFront and ECR push; no deletion of logs, alarms, topics or budget; explicit denies on changing the raw bucket's policy, lifecycle, versioning, ownership and public-access block, on deleting its objects or the bucket, on changing the state bucket, and on Lambda function URLs and resource permissions. Creating new resources or changing IAM is done from the PC. (5) Actions pinned to commit SHAs (checkout v7.0.1, configure-aws-credentials v6.3.0, amazon-ecr-login v2.1.7, setup-terraform v4.0.1, setup-uv v10.3.3); Terraform version pinned; image dependencies installed with hashes (pip --require-hashes from uv export); npm install without scripts; ECR push skipped when the commit's image already exists (immutable tags, safe re-runs). (6) Page Content-Security-Policy adds require-trusted-types-for 'script' (no HTML sinks in app.js; checked in a headless browser, no errors).
- Kept as is: Lambda base image by tag (automatic security patches; a digest pin would need an update bot). The OIDC subject is tied to repository and environment, not to the workflow file.
- Evidence: independent review 2026-10-29 (critical: workflow_run fork trigger; IAM privilege escalation through iam:* on the runtime roles; high: unapproved plan job with apply power; raw bucket exposure through s3:*; medium: service wildcards, tag-pinned actions).
- Previous state: design of the previous entry (not applied).

## 2026-10-29 — v2 pre-registration: hourly curve and daily peak (SPEC 11)
- Change (Fran: hourly forecast as the v2 line): design written before any hourly fit: forecast = v1 daily energy × hourly shares; shape baseline S0 (median shares of the reference days known at the issue time) and shape model S1 (trees on ln(s / s0) with hour, calendar and hourly GFS temperature); one decision on validation (S1 if lower hourly MAPE and two-sided Diebold-Mariano p < 0.05); test year evaluated once, labelled "daily totals already seen"; forward test is the clean evaluation; independent audit (R6) before the test run.
- Evidence: O16 hourly check on data ≤ 2025-09-30: D8 complement vs D7 hourly supply over 2,830 days, median absolute difference 0.001 %, 99th percentile 0.35 %, maximum 12.3 % (2023-05-23; 15 days above 1 %, mostly 2022-07); a one-hour shift gives 2.7 %, so hour numbering matches.
- Previous state: hourly target and peak deferred (ROADMAP F3, F14).

## 2026-10-29 — v2 validation: hourly shape model S1 adopted (SPEC 11)
- Change: shape model = S1 (rule fixed in the pre-registration entry above). Test year not evaluated yet: it waits for the R6 audit.
- Evidence (results/backtest/hourly_validation.json; 358 validation days with S0, S1 and the operator's hourly programme): hourly MAPE S1 3.91 %, S0 4.33 %, B1 4.14 %; S1 − S0 daily mean difference −0.42 points (95 % CI −0.52 to −0.33), Diebold-Mariano p < 0.001. Daily peak MAPE S1 3.42 % (bias −0.07 %), S0 3.47 %, B1 3.80 % (bias +3.12 %); peak hour within one hour of the actual: S1 89.4 %, S0 86.3 %, B1 90.5 %. S1 vs B1 on hourly error, two-sided Diebold-Mariano p = 0.19 (not significant).
- Previous state: shape model open.

## 2026-10-29 — Audit of the afternoon work: live provisional scoring fixed
- Change: live scoring takes as provisional actual the latest version published so far that passes the validity check (a later complement replaces the daily report); invalid reports count as missing; a day without a valid version has no provisional score (service.provisional_actuals, test added). Before, the first daily report was used even when invalid, and a corrected re-issue was ignored, against SPEC 2.2. Score records now carry provisional_source (daily or complement) in place of provisional_valid.
- Not changed (Fran): the public page does not repeat every caveat (provisional scores favouring the operator, validation reuse); they stay in SPEC 4.5, DECISIONS and the README.
- Evidence: audit 2026-10-29 (afternoon), material point 1; no live day had been scored yet.
- Previous state: first daily report per day, valid or not.

## 2026-10-29 — Audit follow-ups: approved-plan check, schedule times, bootstrap state, live-weather check
- Change: (1) deploy.yml: the plan job prints the plan and a SHA-256 fingerprint of terraform show -json (.resource_changes); the approved apply job plans again and applies only if the fingerprint is unchanged (the plan file is never uploaded: it holds the alert email in plain text). (2) Collector morning documents run 09:00 → 09:40 ART and forecaster daily run 09:30 → 09:55 ART, so production sees the documents archived up to 09:40 (the backtest uses everything published before 10:00; the remaining gap is documented in SPEC 7). (3) infra/bootstrap state moves to the state bucket (key bootstrap/terraform.tfstate), so a fresh clone can rebuild everything (S7). (4) scripts/check_live_weather.py compares, hour by hour, the live GFS fetch saved at the issue time with the archive fetched afterwards for the same target day; to be run for the first live days and logged here before the forward test counts.
- Evidence: audit 2026-10-29 (afternoon), material points 3 and 4 and minor items.
- Previous state: re-planned apply, 09:00/09:30 runs, local bootstrap state, live weather unchecked.

## 2026-10-29 — GitHub OIDC subject includes numeric ids
- Change: the trust policies of sadi-github-plan and sadi-github-deploy match the subject GitHub actually sends for this repository, repo:frangarciaproff@285775576/sadi-demand-forecast@1433717782:environment:<name> (owner and repository ids), instead of repo:<owner>/<repo>:environment:<name>. Matching on ids also rejects a different repository later created under the same name.
- Evidence: first deploy run failed with "Not authorized to perform sts:AssumeRoleWithWebIdentity"; a temporary workflow step printed the token claims (subject above; audience sts.amazonaws.com; environment plan; ref refs/heads/main). The diagnostic step is removed once the deploy works.
- Previous state: subject without ids (never matched).
