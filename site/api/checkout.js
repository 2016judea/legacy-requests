// POST /api/checkout -> { clientSecret } for Stripe embedded Checkout.
// One fixed price for every open ask (README "## Price"). The buyer's password is minted here so it
// can ride in the invoice footer (Stripe's own invoice email is a second copy of it).
// Copied from ~/Desktop/msp-house-index/site/api/checkout.js.
const { SITE, PRODUCT, stripe, newPassword } = require("./_lib");
const meta = require("../asks/meta.json");

const body = (req) => new Promise((ok) => { let s = ""; req.on("data", (d) => (s += d)); req.on("end", () => { try { ok(JSON.parse(s || "{}")); } catch { ok({}); } }); req.on("error", () => ok({})); });

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const b = req.body && typeof req.body === "object" ? req.body : await body(req);
  const from = String(b.from || "").replace(/[^a-z0-9-]/gi, "").slice(0, 24) || "asks";
  const name = "Legacy Requests: every open ask";
  try {
    const { nonce, password } = newPassword();
    const s = await stripe("checkout/sessions", {
      method: "POST",
      form: {
        ui_mode: "embedded_page",
        mode: "payment",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": String(meta.price_usd * 100),
        "line_items[0][price_data][product_data][name]": name,
        "line_items[0][price_data][product_data][description]": `All ${meta.n.toLocaleString("en-US")} open government requests for parts, with due dates and each buyer's email and phone.`,
        "payment_method_types[0]": "card",
        "payment_method_types[1]": "link",
        customer_creation: "always",
        "invoice_creation[enabled]": "true",
        "invoice_creation[invoice_data][description]": name,
        "invoice_creation[invoice_data][custom_fields][0][name]": "Password",
        "invoice_creation[invoice_data][custom_fields][0][value]": password,
        "invoice_creation[invoice_data][custom_fields][1][name]": "List",
        "invoice_creation[invoice_data][custom_fields][1][value]": SITE.replace("https://", "") + "/asks",
        "invoice_creation[invoice_data][footer]": `Your password: ${password}. Open the full list at ${SITE}/asks/?pw=${password}. Brick & Mortar · aidan@brickandmortar.dev`,
        "invoice_creation[invoice_data][metadata][product]": PRODUCT,
        "metadata[product]": PRODUCT,
        "metadata[pw_nonce]": nonce,
        "metadata[password]": password,
        "metadata[from]": from,
        "payment_intent_data[metadata][product]": PRODUCT,
        "payment_intent_data[metadata][pw_nonce]": nonce,
        "payment_intent_data[description]": name,
        return_url: `${SITE}/asks/?paid={CHECKOUT_SESSION_ID}`,
      },
    });
    res.status(200).json({ clientSecret: s.client_secret });
  } catch (e) {
    console.error("[checkout]", e.message);
    res.status(502).json({ error: "Checkout could not start. Please try again in a minute." });
  }
};
