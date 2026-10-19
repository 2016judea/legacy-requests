"""Open asks (scripts/build_asks.py): the paid list's rows, counted and rendered from the DIBBS daily files.

Proven 2026-10-18 against the cached archive: 4,793 of 52,616 RFQ lines appear in more than one daily
in<YYMMDD>.txt (a re-issue carries a new return-by date), and the builder summed every file, so a build
on 2026-10-05 would have sold 37,456 "open asks" where 35,065 were open.
"""
import json
from datetime import date, timedelta

import build_asks as B
import dibbs_match as D
import render_asks


def _line(sol, nsn, pr, rb, qty=1, issued="2026-09-28"):
    return {"solicitation": sol, "nsn": nsn, "item_pn": None, "pr": pr, "return_by": rb, "pdf": f"{sol}.pdf",
            "qty": qty, "ui": "EA", "nomenclature": "BAG,SPECIFIC PURPOSE", "issued": issued}


def _patch_days(monkeypatch, days: dict):
    monkeypatch.setattr(D, "issue_days", lambda n: sorted(days))
    monkeypatch.setattr(D, "load_day", lambda d: (days[d], {}))
    monkeypatch.setattr(B, "read_pdf", lambda sol: None)


def test_a_re_issued_rfq_line_counts_once_with_its_latest_due_date(monkeypatch):
    soon = (date.today() + timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=9)).isoformat()
    _patch_days(monkeypatch, {
        "260928": [_line("SPE1C126T1816", "8465016691874", "7018059672", soon, issued="2026-09-28")],
        "261009": [_line("SPE1C126T1816", "8465016691874", "7018059672", later, issued="2026-10-09")],
    })
    rows = B.dibbs_rows()
    assert len(rows) == 1
    assert rows[0]["due"] == later and rows[0]["issued"] == "2026-10-09"


def test_two_purchase_requests_for_one_nsn_on_one_rfq_are_two_asks(monkeypatch):
    soon = (date.today() + timedelta(days=3)).isoformat()
    _patch_days(monkeypatch, {"261008": [_line("SPE2DH27T0129", "6520016033451", "7018659442", soon, qty=1),
                                         _line("SPE2DH27T0129", "6520016033451", "7018659445", soon, qty=1)]})
    assert len(B.dibbs_rows()) == 2


def test_a_closed_line_is_not_revived_by_an_older_issue_day(monkeypatch):
    gone = (date.today() - timedelta(days=1)).isoformat()
    soon = (date.today() + timedelta(days=3)).isoformat()
    _patch_days(monkeypatch, {"260928": [_line("S1", "N1", "P1", soon)], "261009": [_line("S1", "N1", "P1", gone)]})
    assert B.dibbs_rows() == []


def test_a_zero_placeholder_phone_is_no_phone():
    # 30 of 19,673 shipped rows carried "000000000" (nine zeros, so the ten-digit null never fired)
    assert B.phone("000000000") in (None, "")
    assert B.phone("000-000-0000") in (None, "")
    assert B.phone("(215) 737-1234") == "215-737-1234"


def test_sam_quantity_text_becomes_a_number_or_nothing(tmp_path, monkeypatch):
    soon = (date.today() + timedelta(days=3)).isoformat()
    notice = {"notice_id": "abc", "title": "t", "agency": "VA", "office": None, "posted": "2026-10-01", "deadline_date": soon,
              "solicitation": "36C1", "sam_url": "https://sam.gov/opp/abc/view",
              "parts": [{"part": "filter", "manufacturer": "Evoqua", "part_numbers": ["W2T1"], "quantity": "1.00 EA"},
                        {"part": "pump", "manufacturer": "X", "part_numbers": [], "quantity": "36 National Stock Numbers (NSNs)"},
                        {"part": "seal", "manufacturer": "Y", "part_numbers": [], "quantity": None}]}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "open_notices.jsonl").write_text(json.dumps(notice) + "\n")
    monkeypatch.setattr(B, "ROOT", tmp_path)
    rows = B.sam_rows()
    assert [r["qty"] for r in rows] == [1, 36, None]
    # the recipient page formats qty with a thousands separator: a string here crashed the whole build
    meta = {"n": 1, "price_usd": 85, "built": "2026-10-15", "makers": []}
    html = render_asks.for_page(meta, {"token": "t", "org": "X", "lines": []}, [rows[0]], [], 0)
    assert "1 wanted" in html
