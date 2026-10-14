# Go to market: Legacy Requests

Written 2026-10-13, the day `/dates` shipped. The tool is free with no price on it, so the
goal of every play is **use** (visits to `/dates`, replies, forwards), not a sale.
Nothing here has been sent. Every draft waits for Aidan.

## What we know before choosing a channel

| channel, this product | sent | positive | source |
|---|---|---|---|
| Cold email to agency ops/purchasing, opening on **their own sole-source or minutes record**, asking a question, "not selling anything", no link | 26 (9/08) | **2** (Harford MD ops chief, Lakehaven WA purchasing; both answered the follow-up too) | `~/Desktop/panel-backtest/dataset.jsonl`; `outreach/README.md` |
| Gift pages to surplus dealers and APEX Accelerators | 25 (10/06) | 0 | `outreach/legacy_requests/` |
| Rural water circuit riders, concierge offer (opened on us, not their record) | 6 (10/04) | 0 | `outreach/concierge/super_users_2026-10-04.md` |
| Dealer executives, InMail | 10 | 0 | dataset.jsonl |

The only yeses for this product asked a question about the reader's own record and offered
nothing. That is rule 11 of the `distribution-channel` skill, measured here at 2 of 26.

What the customer told us (`~/Desktop/customer-lab/maps/obsolete-parts.json`):
*"If we know that the OEM has a legacy date, we buy items in advance."* (Chief of Operations,
2026-09-08). *"This work is typically performed by Operations or Engineering."* (Purchasing
Manager, 2026-09-11). *"All such purchases are subject to statute and policy with regard to
competitive bidding requirements."* (same, 2026-09-09).

## The plays, ranked

### 1. Agency ops and engineering, opened on their own filing plus the maker's date (their own record)

**Who vouches:** nobody. Their own record does. It is the only voucher that has worked for this
product (2 of 26), and `/dates` now hands us a second fact to put beside it: the maker's own
order-by date for the family their filing names.
**List:** the 15 agencies in `data/eol/installs.json` whose filings name a family with a notice
(Lexington, Ann Arbor, Visalia, Fort Lauderdale, Placer County Water Agency, Sugar Land, Green Bay,
Stockton...), one named ops or engineering lead each. Grow it by re-running `eol_installs.py`
after each ingest; every new agency whose filing names PowerFlex, SLC, S7, DeviceNet or a
discontinued analyzer is a row.
**Send:** Zoho, one to one, at most 10 a day (skill step 5b). No link in touch one; the link goes
in the reply to their answer, the way the Harford and Lakehaven follow-ups went.
**Draft:** below, **P(reply) 12%, above 98% of our 417 scored sends**. An earlier version with a
link and no "not selling anything" scored 4% (22nd percentile), so the question-only shape ships.

### 2. State rural water circuit riders (super user)

**Who vouches:** the association. A circuit rider is already the person a small plant calls when
something is down, visits hundreds of plants a year, and gets credit in the association's own
savings report when a plant avoids a cost. All four super-user facts hold
(`super_users_2026-10-04.md`, ranked list of 23).
**What they gain:** a buy-ahead list for the plants on their route, which is a line in their own
district savings column. The 10/04 touch offered a part hunt and opened on us; 0 of 6. This one
opens on their published savings report and asks what they see most.
**List:** 16 named wastewater technicians and circuit riders in WI, MI, MN, IA, CA, TX and FL
(`outreach/concierge/super_users_2026-10-04.md`), then the published technician pages of the
other state rural water associations. The 7 already touched get this as touch 2.
WRWA, MI RWA and MMUA publish phone numbers only: Aidan calls, then this email follows.
**Draft:** below, **P(reply) 30%, above 100% of our 417 scored sends** (the forecaster was told
it follows a phone call; for the seven reached cold by email, expect less).

### 3. Operator association newsletters (obligation inbox)

**Who vouches:** the inbox exists to receive this. The Wastewatcher page: *"Do you have an article
to submit to The Wastewatcher? Contact Jerry Balbach, Editor."* One printed piece reaches every
member of a state operators' association. The payload is the article itself, ready to run, so the
obligation holds (skill rule 9).
**List:** MN (MWOA Wastewatcher), then every state WEF member association and AWWA section that
publishes a submissions address, plus ISA's Water/Wastewater division newsletter. Only inboxes that
publicly ask for articles qualify.
**Draft:** below, **P(reply) 12%, ranks above 98% of our 417 scored sends.**

### Ranked out, with the fact that put them out
- **Surplus dealers and APEX counselors:** 0 of 25 on 10/06 and 0 of 24 before. They gain from a
  sale we do not make.
- **Controls integrators and Rockwell distributors:** they sell the migration a legacy date
  triggers, so a list from us is a lead list for their own pitch, not a favour to the utility.
  Disqualified as sellers of the redesign (`project_parts_concierge_2026_10_04` memory).
- **Forums (r/PLC, PLCtalk, Practical Machinist):** every room bans links, two ban company names
  (`intercept_sources.md`).

## The floor

`~/.claude/BUSINESS.md` rule 4: **50 delivered recipients across at least 3 segments** before any
verdict. Play 1 has 15 agencies today, play 2 has 16 named riders, play 3 has about 20 inboxes to
find: about 51 across three segments, so the three plays together clear the floor and none alone
does. Below 50 delivered, the result is reported as a probe. Three touches each before silence
counts (skill rule 5).

## Rules for selling and marketing this product

1. **The first two sentences quote the reader's own filing, and the third gives the maker's date.**
   *Why:* every positive this product has had opened on the agency's own record (Harford: the Sod Run
   SCADA sole-source; Lakehaven: its own minutes). `distribution-channel` rule 11.
2. **Ask one question they already know the answer to. Offer nothing.** *Why:* both 9/08 replies
   answered a question about their own plant; the 25 gift pages of 10/06 offered something and got 0.
3. **Reach operations or engineering, never purchasing or a contracting officer.** *Why:* Lakehaven's
   purchasing manager: *"This work is typically performed by Operations or Engineering,"* and she
   forwarded us there (`obsolete-parts.json`, e_4137f65d6f).
4. **Only an open date makes an opener.** Use a last-time buy still ahead (`/dates`, "Last-time buy
   open"). A date already past is history, not news. *Why:* the job is "buy items in advance"
   (e_892fd6f266); a passed date leaves nothing to buy ahead of.
5. **Claim the catalog numbers, never the family; say what their filing names, never that they
   run the exact part.** "504 DeviceNet cable and media catalog numbers" is true; "DeviceNet cable is
   end of life" is not (369 more are still active). *Why:* a distributor blog says every PowerFlex 4
   and 40 went end of life June 30, 2025; Rockwell's own data shows 33 of each discontinued that day
   and 38 PowerFlex 4 drives still active. This file's first drafts repeated the blog and were
   corrected before scoring. Likewise "Your spec calls
   for DeviceNet cable" is true; "your DeviceNet cable is end of life" may not be. *Why:* the join is by
   product family, and the page says so in its footer. A wrong claim about their own plant ends the
   thread.
6. **Never put a price on the tool or in a touch.** *Why:* the tool is free; price is negotiated off
   the tool if it ever exists (`feedback_price_is_negotiated_not_on_the_tool` memory); and any
   purchase has to clear their competitive-bidding rules (e_2411f8aba8), which a pitch makes harder
   to answer, not easier.
7. **No link in a cold first touch to an agency; the link goes in the reply.** *Why:* the 9/08
   shape had none and got 2 of 26. Scored today, the link-and-no-disclaimer version of the play 1
   draft fell from 7% to 4%. Super users and editors get the link in touch one, because the page is
   what they would pass on.
8. **Every number in a touch comes from `/dates` or the reader's filing, the day it is sent.** *Why:*
   the dates move (Rockwell revises discontinued dates), and a stale date in a message about dates is
   the one error the reader can check in a minute.
9. **Score every draft with the screen before it sends, and log it then.** `cd ~/Desktop/customer-lab
   && .venv/bin/python lab/screen.py --product legacy-requests ...` without `--dry` on send day.
   Rank drafts against each other, never against 50%. *Why:* the forecaster ranked 4 of 5 real
   positives in its top 60 of 419 (`panel-backtest/RESULTS.md`).
10. **Pipe by batch size.** Over 10 a day goes through Mailgun (100 requests a rolling 24h for the
    whole domain); one-to-one ops mail goes through Zoho at 10 an hour. *Why:* Zoho blocked all
    outgoing mail on 9/14 and 10/13 (skill step 5b).
11. **Read `/dates` traffic, not the inbox, to decide.** Vercel Web Analytics and PostHog are on the
    page. *Why:* BUSINESS.md rule 2, and 10/08: a recipient used a tool 31 times while never replying.

## Drafts (first touch, one per play)

Names and addresses live in `outreach/legacy_requests/gtm_2026-10-13/` (gitignored; this repo
is public). Scores are `lab/screen.py --dry`, 2026-10-13.

### Play 1: Lexington-Fayette, Division of Water Quality, ops lead (name to find before send)
Subject: question about DeviceNet in your 2025 spec
Score: P(reply) 12%, P(click) 4%, above 98% of 417 scored sends

```
[name],

I'm Aidan. Your Division of Water Quality's January 2025 low voltage spec says DeviceNet trunk, drop cables and accessories "shall be as recommended by the PLC manufacturer." Your 2024 agreement with GRW says the plants run CompactLogix.

Rockwell stops taking orders for most of its DeviceNet cable and media, 504 catalog numbers, on January 30, 2027, with no replacement planned.

When a maker puts a date like that on something you run, what does your shop do? Buy a stock of it ahead, or plan the move off it?

Not selling anything. I'm trying to understand what plants actually do before the date.

Aidan
aidanjude.substack.com
```

### Play 2: Wisconsin Rural Water, District 3 wastewater technician (after Aidan's call)
Subject: A line for District 3's savings
Score: P(reply) 30%, P(click) 40%, above 100% of 417 scored sends

```
[first name],

WRWA's 2025 report prints the system savings for each district. Here's a way to add to District 3's.

The last PowerFlex 70 drives come off Rockwell's order book in three steps: December 1, 2026, May 30, 2027 and July 1, 2027. Siemens moved the S7-300 to spares only on October 1, 2025, and stops taking orders for first-generation S7-1200 PLCs on October 31, 2027.

A plant that knows the date buys its spare before it. One that doesn't finds out when the drive fails.

Which drives and PLCs do you see most at the lift stations you visit?

Every date, each with the maker's own notice: https://legacy-requests.vercel.app/dates

Best,
Aidan Jude
aidanjude.substack.com
```

### Play 3: MWOA, The Wastewatcher, editor
Subject: An article for The Wastewatcher: the date on the cabinet door
Score: P(reply) 12%, P(click) 30%, above 98% of 417 scored sends

```
[first name],

The Wastewatcher page says to send you an article. Here's one, about 150 words. Free to run, edit or cut.

The date on the cabinet door

Every drive and PLC in a lift station has a date its maker stops selling it. The last PowerFlex 70 drives come off Rockwell's order book starting December 1, 2026. Siemens moved the S7-300 to spares only on October 1, 2025, and stops taking orders for first-generation S7-1200s on October 31, 2027. Rockwell stops taking orders for 504 DeviceNet cable and media catalog numbers on January 30, 2027, with no replacement planned.

A plant that knows the date buys its spare before it. The dates are public, but they sit on six makers' support sites. They're in one list now, each with the maker's own notice: legacy-requests.vercel.app/dates

Best,
Aidan Jude
aidanjude.substack.com
```
