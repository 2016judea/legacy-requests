// GET /api/check?q=<maker or part number> -> { q, n, rows }
// The free search: how many open asks match, and up to three of them REDACTED (no due date, no buyer,
// no RFQ or stock number). Reads the same bundle as /api/data; never returns a full row.
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const DIR = process.env.FULL_DIR || path.join(__dirname, "_full");
let ROWS = null;
const key = (s) => String(s || "").toLowerCase().replace(/[-\s/.]/g, "");

function redact(r) {
  const a = r.approved.find((x) => x.maker) || r.approved[0] || {};
  return { part: r.part, maker: a.maker || null, pn: a.pn || null, qty: r.qty, unit: r.unit, agency: r.agency, source: r.source,
    last_paid: r.last_paid, last_paid_date: r.last_paid_date, for_sale: (r.for_sale || []).length, n_approved: r.approved.length };
}

module.exports = async (req, res) => {
  const q = String(req.query.q || "").slice(0, 80);
  const k = key(q);
  if (k.length < 2) return res.status(400).json({ error: "Type at least two characters." });
  ROWS ??= JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(DIR, "rows.json.gz")))).rows.map((r) => {
    r._h = key([r.part, ...r.approved.flatMap((a) => [a.pn, a.maker])].join(" "));
    return r;
  });
  const hits = ROWS.filter((r) => r._h.includes(k));
  // Priced rows first: "paid last time" is the fact a seller checks before anything else.
  const show = hits.filter((r) => r.last_paid).concat(hits.filter((r) => !r.last_paid)).slice(0, 3).map(redact);
  res.setHeader("Cache-Control", "public, max-age=300");
  res.status(200).json({ q, n: hits.length, rows: show });
};
