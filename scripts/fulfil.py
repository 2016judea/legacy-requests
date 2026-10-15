#!/usr/bin/env python3
"""The paywall's backup, run by hand. Nothing here emails anyone.

    python scripts/fulfil.py cs_live_...     # a buyer lost their password: reprint it
    python scripts/fulfil.py --recent        # every session of ours since launch, paid or not
    python scripts/fulfil.py --comp          # a $0 checkout link that unlocks like a paid one
                                             # (a friend, a press copy, or an end-to-end test)

The password lives in the session's metadata (minted by site/api/checkout.js) and in the
invoice footer Stripe emailed the buyer. The buyer's email went out from the webhook or
the confirmation page; `pw_emailed` in the metadata says which, and when.
Reads STRIPE_SECRET_KEY from ~/Desktop/bricks/.env and ACCESS_SECRET from ./.env.
"""
import base64, hashlib, hmac, os, secrets, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://legacy-requests.vercel.app"
ALPHA = "23456789BCDFGHJKMNPQRSTVWXYZ"  # same as site/api/_lib.js


def env(path, key):
    for line in Path(path).expanduser().read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"{key} missing from {path}")


KEY = env("~/Desktop/bricks/.env", "STRIPE_SECRET_KEY")
S = requests.Session()
S.auth = (KEY, "")


def stripe(path, **form):
    r = S.post(f"https://api.stripe.com/v1/{path}", data=form) if form else S.get(f"https://api.stripe.com/v1/{path}")
    j = r.json()
    if "error" in j:
        sys.exit(f"stripe: {j['error'].get('message')}")
    return j


def password(nonce):
    mac = hmac.new(env(ROOT / ".env", "ACCESS_SECRET").encode(), nonce.encode(), hashlib.sha256).digest()
    raw = nonce + "".join(ALPHA[b % len(ALPHA)] for b in mac[:7])
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def show(s):
    m = s.get("metadata") or {}
    email = (s.get("customer_details") or {}).get("email")
    print(f"{s['id']}\n  status   {s['status']} / {s['payment_status']}  ${(s.get('amount_total') or 0) / 100:.2f}"
          f"\n  email    {email}\n  password {m.get('password')}\n  link     {SITE}/asks/?pw={m.get('password')}"
          f"\n  emailed  {m.get('pw_emailed') or 'NOT YET'}")


if len(sys.argv) < 2:
    sys.exit(__doc__)
arg = sys.argv[1]
if arg == "--recent":
    for s in stripe("checkout/sessions?limit=100&created[gte]=1792022400")["data"]:
        if (s.get("metadata") or {}).get("product") == "legacy-requests-asks":
            show(s)
elif arg == "--comp":
    coupon = "LEGACY-ASKS-COMP"
    if "error" in S.get(f"https://api.stripe.com/v1/coupons/{coupon}").json():
        stripe("coupons", id=coupon, percent_off=100, duration="once", name="Legacy Requests open asks comp")
    nonce = "".join(secrets.choice(ALPHA) for _ in range(5))
    pw = password(nonce)
    s = stripe("checkout/sessions", **{
        "mode": "payment", "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": "usd", "line_items[0][price_data][unit_amount]": 8500,
        "line_items[0][price_data][product_data][name]": "Legacy Requests: every open ask",
        "discounts[0][coupon]": coupon, "customer_creation": "always",
        "metadata[product]": "legacy-requests-asks", "metadata[pw_nonce]": nonce, "metadata[password]": pw, "metadata[comp]": "1",
        "success_url": f"{SITE}/asks/?paid={{CHECKOUT_SESSION_ID}}",
    })
    print(f"comp checkout (no card, $0): {s['url']}\nsession {s['id']}  password {pw}")
else:
    show(stripe(f"checkout/sessions/{arg}"))
