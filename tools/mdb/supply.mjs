// Hourly supply from Parte Post Operativo Access databases.
// Usage: node supply.mjs file1.mdb [file2.mdb ...]
// Prints one JSON line per file: {path, fecha, hourly[24], n_rows, n_units,
// hours_present, bad_rows, excluded_mwh} or {path, error}.
// EXCLUDED: units that are not supply to the Argentine grid. YACYHIPY is the
// Paraguayan share of Yacyretá, listed as its own unit from 2024-11 (about 4 % of
// supply in summer 2024-25); the Síntesis (D7) and D1 do not count it.
import { readFileSync } from "node:fs";
import MDBReader from "mdb-reader";

const EXCLUDED = new Set(["YACYHIPY"]);

for (const path of process.argv.slice(2)) {
  try {
    const reader = new MDBReader(readFileSync(path));
    const rows = reader.getTable("VALORES_GENERADORES").getData({
      columns: ["GRUPO", "HORA", "ENERGIA"],
    });
    const hourly = new Array(24).fill(0);
    const hours = new Set();
    const units = new Set();
    let bad = 0;
    let excluded = 0;
    for (const r of rows) {
      const h = r.HORA;
      if (!Number.isInteger(h) || h < 1 || h > 24) {
        bad += 1;
        continue;
      }
      if (EXCLUDED.has(r.GRUPO)) {
        excluded += Number(r.ENERGIA ?? 0);
        continue;
      }
      hours.add(h);
      units.add(r.GRUPO);
      hourly[h - 1] += Number(r.ENERGIA ?? 0);
    }
    let fecha = null;
    if (reader.getTableNames().includes("FECHA")) {
      const f = reader.getTable("FECHA").getData()[0];
      const v = f ? Object.values(f)[0] : null;
      if (v instanceof Date) {
        // Access stores a local date without zone: format the UTC fields.
        fecha = v.toISOString().slice(0, 10);
      }
    }
    console.log(
      JSON.stringify({
        path,
        fecha,
        hourly,
        n_rows: rows.length,
        n_units: units.size,
        hours_present: hours.size,
        bad_rows: bad,
        excluded_mwh: excluded,
      }),
    );
  } catch (e) {
    console.log(JSON.stringify({ path, error: String(e) }));
  }
}
