// Renders data.json (written once a day by the forecaster). No external code; data is
// inserted with textContent / SVG attributes only (never as HTML).
"use strict";

const SVG = "http://www.w3.org/2000/svg";
const H = 320;
const PAD = { top: 12, right: 12, bottom: 28, left: 44 };

function el(tag, attrs, parent) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  if (parent) parent.appendChild(node);
  return node;
}

function html(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

const gwh = (mwh) => (mwh === null || mwh === undefined ? null : mwh / 1000);
const fmt = (x, d = 1) => (x === null || x === undefined ? "–" : x.toFixed(d));
const pct = (x) => (x === null || x === undefined ? "–" : (x > 0 ? "+" : "") + x.toFixed(1) + " %");
const day = (iso) => new Date(iso + "T12:00:00Z");
const label = (iso) =>
  day(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const longLabel = (iso) =>
  day(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });

function actual(r) {
  if (r.definitive_mwh !== null && r.definitive_mwh !== undefined) return { v: r.definitive_mwh, kind: "definitive" };
  if (r.provisional_mwh !== null && r.provisional_mwh !== undefined) return { v: r.provisional_mwh, kind: "provisional" };
  return null;
}

function hero(data) {
  const rows = data.days;
  const next = rows[rows.length - 1];
  if (!next) return;
  document.getElementById("next-date").textContent = longLabel(next.date);
  document.getElementById("next-gwh").textContent = fmt(gwh(next.forecast_mwh));
  const change = 100 * (next.forecast_mwh / next.b0_mwh - 1);
  document.getElementById("next-note").textContent =
    `${pct(change)} against the same weekday of the last four weeks · issued ${(next.issued_at_art || "").replace("T", " ").slice(0, 16)} (Argentina)`;

  const tiles = document.getElementById("tiles");
  const s = data.summary.best;
  const items = [
    ["Model error (live)", s.mape_model_pct === null ? "–" : fmt(s.mape_model_pct, 2) + " %"],
    ["Operator error", s.mape_b1_pct === null ? "–" : fmt(s.mape_b1_pct, 2) + " %"],
    ["Days scored", String(s.days)],
  ];
  for (const [k, v] of items) {
    const t = html("div", null, "tile");
    t.appendChild(html("p", k, "k"));
    t.appendChild(html("p", v, "v"));
    tiles.appendChild(t);
  }
  const note = html(
    "p",
    `Mean absolute percentage error, last 90 days, on the days with both forecasts: definitive actuals for ${s.definitive_days} days, provisional for ${s.days - s.definitive_days}.`,
    "note",
  );
  tiles.appendChild(note);
}

function legend() {
  const box = document.getElementById("legend");
  for (const [cls, text] of [["model", "Model forecast"], ["operator", "Operator programme (CAMMESA)"], ["actual", "Actual"]]) {
    const item = html("span");
    item.appendChild(html("i", null, "swatch " + cls));
    item.appendChild(document.createTextNode(text));
    box.appendChild(item);
  }
}

function chart(data) {
  const svg = document.getElementById("chart");
  const tip = document.getElementById("tooltip");
  const rows = data.days;
  while (svg.lastChild && svg.lastChild.nodeName !== "title") svg.removeChild(svg.lastChild);
  const W = Math.max(320, svg.clientWidth || 800);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (rows.length === 0) return;

  const values = [];
  for (const r of rows) {
    for (const v of [r.forecast_mwh, r.b1_mwh, actual(r) && actual(r).v]) if (v) values.push(v / 1000);
  }
  let lo = Math.min(...values), hi = Math.max(...values);
  const minSpan = 0.15 * hi; // a few days of data still get a readable scale
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
  }
  const raw = ((hi - lo) * 1.1) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((c) => c >= raw);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const n = rows.length;
  const x = (i) => PAD.left + (n === 1 ? (W - PAD.left - PAD.right) / 2 : (i * (W - PAD.left - PAD.right)) / (n - 1));
  const y = (g) => PAD.top + ((hi - g) * (H - PAD.top - PAD.bottom)) / (hi - lo);

  const grid = el("g", { class: "grid" }, svg);
  const axis = el("g", { class: "axis" }, svg);
  for (let g = lo; g <= hi + 1e-9; g += step) {
    el("line", { x1: PAD.left, x2: W - PAD.right, y1: y(g), y2: y(g) }, grid);
    const t = el("text", { x: PAD.left - 6, y: y(g) + 4, "text-anchor": "end" }, axis);
    t.textContent = Math.round(g);
  }
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(W / 90))));
  rows.forEach((r, i) => {
    if (i % every === 0 || i === n - 1) {
      const t = el("text", { x: x(i), y: H - 8, "text-anchor": "middle" }, axis);
      t.textContent = label(r.date);
    }
  });

  const path = (key) => {
    let d = "";
    rows.forEach((r, i) => {
      const v = r[key];
      if (v === null || v === undefined) return;
      d += (d && rows[i - 1] && rows[i - 1][key] ? "L" : "M") + x(i).toFixed(1) + " " + y(v / 1000).toFixed(1);
    });
    return d;
  };
  el("path", { class: "line operator", d: path("b1_mwh") }, svg);
  el("path", { class: "line model", d: path("forecast_mwh") }, svg);
  // Model markers where a day has no neighbour to draw a line to, and always for the
  // newest forecast (tomorrow).
  rows.forEach((r, i) => {
    const prev = i > 0 && rows[i - 1].forecast_mwh;
    const next = i < n - 1 && rows[i + 1].forecast_mwh;
    if (r.forecast_mwh && (i === n - 1 || (!prev && !next))) {
      el("circle", { class: "dot model", cx: x(i), cy: y(r.forecast_mwh / 1000), r: 5 }, svg);
    }
  });
  rows.forEach((r, i) => {
    const a = actual(r);
    if (a) el("circle", { class: "dot " + a.kind, cx: x(i), cy: y(a.v / 1000), r: 4 }, svg);
  });

  const cross = el("line", { class: "crosshair", y1: PAD.top, y2: H - PAD.bottom, visibility: "hidden" }, svg);
  const hit = el("rect", { x: PAD.left, y: 0, width: W - PAD.left - PAD.right, height: H, fill: "transparent" }, svg);
  const show = (evt) => {
    const box = svg.getBoundingClientRect();
    const px = ((evt.clientX - box.left) * W) / box.width;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) * (n - 1)) / (W - PAD.left - PAD.right))));
    const r = rows[i];
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    tip.replaceChildren();
    tip.appendChild(html("p", longLabel(r.date), "t"));
    const a = actual(r);
    tip.appendChild(html("p", `Model ${fmt(gwh(r.forecast_mwh))} GWh`));
    tip.appendChild(html("p", r.b1_mwh ? `Operator ${fmt(gwh(r.b1_mwh))} GWh` : "Operator not yet published"));
    tip.appendChild(html("p", a ? `Actual ${fmt(gwh(a.v))} GWh (${a.kind})` : "Actual not yet published"));
    tip.hidden = false;
    const left = (x(i) * box.width) / W;
    tip.style.left = Math.min(Math.max(0, left + 12), box.width - tip.offsetWidth) + "px";
  };
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerdown", show);
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
}

function table(data) {
  const body = document.querySelector("#table tbody");
  body.replaceChildren();
  for (const r of [...data.days].reverse()) {
    const a = actual(r);
    const kind = a ? a.kind : null;
    const tr = document.createElement("tr");
    const err = (key) => (kind ? r[`${key}_error_pct_${kind}`] : null);
    for (const v of [
      r.date,
      fmt(gwh(r.forecast_mwh)),
      fmt(gwh(r.b1_mwh)),
      a ? fmt(gwh(a.v)) + (kind === "provisional" ? " (prov.)" : "") : "–",
      pct(err("forecast")),
      pct(err("b1")),
    ]) tr.appendChild(html("td", v));
    body.appendChild(tr);
  }
}

async function main() {
  legend();
  let data;
  try {
    const resp = await fetch("data.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(String(resp.status));
    data = await resp.json();
  } catch (e) {
    document.getElementById("next-note").textContent = "Data not available right now.";
    return;
  }
  hero(data);
  chart(data);
  table(data);
  document.getElementById("generated").textContent = data.generated_at_art.replace("T", " ").slice(0, 16) + " (Argentina)";
  document.getElementById("model-version").textContent = data.model_version || "–";
  let t;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => chart(data), 150);
  });
}

main();
