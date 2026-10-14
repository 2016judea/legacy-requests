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
