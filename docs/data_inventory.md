# Data inventory — CAMMESA documents (D5, D6)

Inventory of file formats inside the archived zips, from samples per year (2026-10-25).
Describes structure only; no data values are reproduced.

## D6 — Programación Diaria (day-ahead programme)

| Period | Format | Programmed demand source |
|--------|--------|--------------------------|
| 2010-01-01 → 2024-11-12 | fixed-width text + Access DB: balance.txt, PDyymmdd.mdb, PDyymmdd.chm, precios.txt, regfrec.txt, restricciones.txt, despachocomahue.txt (cvp.txt from 2021) | balance.txt, block "SIN" (system) and per area: "DEMANDA NETA" hourly 1–24 + daily total (MWh) |
| 2024-10-23 → present | CSV set: BALANCE.csv, GENERADORES.csv, INTERCONEXIONES.csv, … , fecha_revista.csv | BALANCE.csv rows TIPO="D", VARIABLE="Demanda Neta", per region (RGE), H01–H24 |

- Overlap 2024-10-23 → 2024-11-12: both formats in the same period (first balance.csv in PD241024.zip,
  last balance.txt in PD241112.zip). The overlap allows a direct consistency check between parsers.
- Format stable within each period in the samples (2010–2023 identical member set).
- Header of balance.txt gives issue date ("Fecha") and target day ("DEL DIA").

## D5 — Parte Semanal (weekly report)

| Member | Years present (samples) | Content |
|--------|------------------------|---------|
| SEwwarea.dem | 2010 → 2026, every sample | hourly demand by area (MWh), H01–H24, daily E.Total, E.Valle, E.Resto, E.Pico, Pot.Max, hh:mm |
| SEwwddDD.dem | 2010 → 2026 | hourly demand by agent |
| balance.txt | 2016 → 2026 only | STALE: identical file (same sha256, dated 2016-09-21) in every sampled weekly zip 2016–2025. Not usable. |
| SEwwddDD.mdb, .chm, .rvl, .rvt, .sg* | 2010 → 2026 | other weekly tables (not used in v1) |
| SETMyymm (tare*.dem, tdem*.dem, …) | monthly packages, some years | monthly area/agent demand |

- Area set identical in 2010, 2018 and 2026 samples: BAS, CENTRO, COMAHUE, CUYO, GBA, LITORAL, NEA,
  NOA, PATAGONICA. Column header identical across samples.
- Each day appears with row markers A, E and S. Meaning to be determined in P1 (blocking for the
  parser: which row is the area demand used as target).

## Consequences for P1

- D6 needs two parsers (balance.txt fixed-width, BALANCE.csv), cross-checked on the 2024-10/11 overlap.
- D5 needs one parser for SEwwarea.dem (stable 2010 → 2026) and one for balance.txt (2016 →).
- Open: meaning of row markers A/E/S in SEwwarea.dem; whether area totals in SEwwarea.dem equal
  DEMNETA in balance.txt (O9).

## SEwwarea.dem parsing rules (verified 2026-10-25 on data ≤ 2025-09-30)

- Area demand = the day rows between an "AREA <name>" header and the next "Total :" line.
  Any other uppercase section header ends the area section: "COMPRA SPOT DE GENERADORES" (small,
  generators' purchases) and "JURISDICCION <code>" (sub-areas; summing them double counts).
- Row markers A/S/E are per-row flags, not the selector: in 2016 whole areas are marked S, in 2019 A.
  Meaning still unknown (possibly data source or estimation flag); kept as a column.
- Fixed width: 24 hourly fields of 8 characters starting at column 8. Values that fill the field are
  glued to the next one (e.g. "9651.3710045.50"), so whitespace splitting fails; slice by position.
  Position slicing agrees with whitespace splitting on 15,107 of 15,107 comparable rows; 27 glued rows
  are parseable only by position.
- Overflow fields print as "********" (seen in daily totals). Daily energy is computed as the sum of
  the 24 hourly values, not read from E.Total.
- Page breaks repeat the column header and the "AREA <name>" line; a day row appears once per area.

## First consistency measurements (data ≤ 2025-09-30, months 03/07/11 sampled)

- Ratio sum of 9 areas / D1 daily gross energy: yearly medians 0.916–0.978, typically 0.93–0.95
  (consistent with net < gross). Dispersion is large (yearly p5 down to 0.857, p95 up to 1.184).
  Ratios > 1 are not physically plausible for net vs gross and point to day misalignment, D1 errors
  or perimeter changes. Must be resolved at day level before D5 is accepted as target source.
- Same day, first vs later publication: |difference| median 0.39 %, p95 5.8 %, max 7.3 % (n = 86).
  The tail is too large to be settlement adjustments alone; likely the same alignment issue.

## Parser validation (2026-10-25, data ≤ 2025-09-30; module src/sadi_forecast/parsing.py)

D5 SEwwarea.dem:
- Weeks crossing a month boundary are split into separate files; the file name SEwwddDD gives
  week ww and day range dd–DD. 252 of 252 sampled files (2012, 2019, 2024) have exactly
  9 areas × (DD − dd + 1) day rows.
- Rows without a marker ("dd/mm" followed by blanks) are missing data filled with zeros by CAMMESA
  (e.g. a whole week of one area, or one day from hour 4 on). Parsed with flag "" and no values;
  never summed. 45 such rows in the sample. A naive parser would count them as zero demand.
- Markers seen per file: A and S together in most files; S only, A only in some; E seen in 2010.

D6 Programación Diaria:
- balance.txt: national "SIN" DEMANDA NETA equals the sum of the area blocks exactly. Hourly values
  are integers; the daily total differs from their sum by rounding (|diff| ≤ 1 MWh in samples).
- Overlap 2024-10-23 → 2024-11-12 (23 files with both formats): CSV sum of regions − txt SIN is
  +0.08 % to +0.20 % on most days (mostly NEA, ~800–950 MWh/day higher in the CSV; other areas
  25–50 MWh/day). Early transition days show +2.65 % to +2.92 %; on 2024-11-11 the CSV NEA value
  repeats the previous day exactly and was corrected in a re-publication. The CSV stabilises by the
  end of the overlap.
