// Diagnostic: daily energy per unit (GRUPO) of one Post Operativo database.
// Usage: node units_by_group.mjs file.mdb > units.json (tables and columns on stderr).
import { readFileSync } from "node:fs";
import MDBReader from "mdb-reader";
const r = new MDBReader(readFileSync(process.argv[2]));
const t = r.getTable("VALORES_GENERADORES");
console.error(JSON.stringify({tables: r.getTableNames(), cols: t.getColumnNames()}));
const by = {};
for (const x of t.getData()) { const k = x.GRUPO; by[k] = (by[k] ?? 0) + Number(x.ENERGIA ?? 0); }
console.log(JSON.stringify(by));
