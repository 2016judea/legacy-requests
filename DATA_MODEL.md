# Data model — Legacy dates

Written 2026-10-13, from the need alone, before the data was checked (BUSINESS.md rule 5).

**The need.** A water utility's Chief of Operations, replying to us 2026-09-08:
*"If we know that the OEM has a legacy date, we buy items in advance."* Demand for an
obsolete part starts the day the OEM announces the date it stops selling, months or
years before any agency files a sole-source RFP. Legacy Requests showed only the RFP.
This adds the step before it.

## Ideal model

### Notice — one OEM statement that a product line is ending
| field | question it answers |
|---|---|
| `oem` | Whose gear is it? |
| `family` | Which product line, in the words on the cabinet door (PowerFlex 70, S7-300)? |
| `catalog_numbers` | Is *my* part number in it? |
| `status` | Can I still buy it new today? (last-time buy open / discontinued, repair only / successor named) |
| `legacy_date` | By what date must the order be in? |
| `days_left` | How long do I have? (derived) |
| `support_until` | Until when will they still repair it or sell spares? |
| `successor` | What do I replace it with? (job: *pick a replacement*) |
| `successor_kind` | Drop-in, or an engineering project? |
| `notice_url` | Where does the OEM say so? Every row cites it. |
| `quote` | The OEM's own sentence, verbatim, checked against the fetched page. |
| `fetched` | When did we last read it? |

### Install — evidence that a public agency runs that family
| field | question it answers |
|---|---|
| `agency`, `state` | Who else runs this, and will be buying ahead too? |
| `family` | Joins to Notice.family |
| `filing_url`, `date`, `quote` | Where did the agency say it runs it? Every row cites its filing. |

### Ask — the existing Legacy Requests row (an agency's sole-source filing)
Joins to Notice by make/model; it is the *after* to the Notice's *before*.

**Joins.** Notice.family ← Install.family (many agencies per notice). Notice.family ← Ask (manufacturer + model text).

## Reality check (2026-10-13)

| field | source | fillable? |
|---|---|---|
| Rockwell notices, catalog numbers, status, legacy_date, successor, successor_kind | Rockwell's public Product Lifecycle Status search (JSON behind rockwellautomation.com/…/product-lifecycle-status.html) | **Yes**, per catalog number. 22,408 catalogs read across 22 water-relevant bulletins. |
| Siemens / Schneider / ABB / Hach / Yaskawa notices | OEM support pages and PDFs | **Yes, by hand**, one notice at a time; quote verified against the fetched page. Several are bot-walled to curl (se.com, Siemens support) and were read rendered. |
| `support_until` | Siemens, Hach, Schneider state it; Rockwell's API does not | **Partial.** Shown where the OEM prints it. |
| Install | our own 261 agencies' filings (matter text + attachment text) | **Thin.** Sole-source filings name a family only when that family is the thing being bought. ~15–25 agency×family rows. |

**Call.** The Notice side fills; it is what the customer acts on, and they already
know what they run. The Install side is thin but real and every row is cited, so it
ships as "agencies on record running this", never as a count of the market. No field
was dropped to make the model fit.

---

# Data model — Open asks (the paid list)

Written 2026-10-15, from the need alone, before the data was checked (BUSINESS.md rule 5).

**The need.** A surplus dealer, an eBay industrial seller or a repair shop holds a part.
Somewhere a government buyer is asking for that exact part *right now*, with a date the
quote is due. The dealer wants every open ask in their line, early enough to quote, with
the person to call, and what the buyer paid last time so they know if their price clears.

## Ideal model

### Ask — one open government request for a part
| field | question it answers |
|---|---|
| `solicitation`, `source` | Which RFQ is it, on which board (DLA DIBBS, SAM.gov)? |
| `agency`, `office` | Who is buying? |
| `part`, `nsn` | What are they asking for, in their words and stock number? |
| `approved` [ `maker`, `cage`, `pn` ] | Whose part number will they accept? (joins to the dealer's listing) |
| `qty`, `unit` | How many? |
| `issued`, `due` | Is it still open, and by what date must the quote be in? |
| `buyer_name`, `buyer_email`, `buyer_phone` | Whom do I call? |
| `last_paid`, `last_paid_date`, `last_qty` | What did they pay last time, so does my price clear? |
| `surplus_ok` | Will they take surplus / not-new stock? |
| `rfq_url` | Where is the RFQ itself? Every row cites it. |
| `for_sale` [ `seller`, `url`, `price` ] | Is it already listed somewhere (our supply join)? |

### Seller — the dealer, shop or eBay seller we write to
| field | question it answers |
|---|---|
| `name`, `org`, `email`, `email_source` | Who, and where did their address come from? |
| `segment` | Dealer / eBay seller / repair shop |
| `lines` | Which makers do they stock or fix? (joins to Ask.approved.maker) |
| `their_record`, `record_url` | Their own listing or catalog page that matches an Ask |

**Joins.** Seller.their_record.pn ↔ Ask.approved.pn (exact, separators dropped, maker word
must agree: `scripts/join_supply.py`). Seller.lines ↔ Ask.approved.maker.

## Reality check (2026-10-15)

| field | source | fillable? |
|---|---|---|
| solicitation, nsn, part, qty, unit, issued, due | DIBBS bulk `in<YYMMDD>.txt` | **Yes.** 19,659 open lines today across 23 issue days. |
| approved cage + pn | DIBBS `bq<YYMMDD>.zip` → `as*.txt` | **Yes**, 14,208 of 19,659 lines carry one. |
| approved maker name, buyer name/email/phone, last_paid, surplus_ok | the RFQ PDF, one per solicitation | **Yes, slowly**: ~18.7k PDFs, ~4 h at a polite rate (`scripts/fetch_open_rfqs.py`). |
| SAM.gov open sole-source notices | `data/open_notices.jsonl` | **Thin**: 3 open today. Kept, not the bulk. |
| for_sale | our supply join | **Thin but real**: tens of exact matches, not hundreds. |
| Seller.lines, their_record | dealer sitemaps, eBay item pages, shop catalogs | **Yes, by hand per seller.** |

**Call.** The model fills. DIBBS is the bulk of open demand; council sole-source filings
(the 6,904 rows on `/`) are history, not open asks, and stay free on `/`.
