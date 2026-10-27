"""A receipt is checked against each kind of purchase it could be taken for apart.

A warehouse receipt is known by its day and its total. One pool held the
other purchases of its day, which share the day, and the purchases either
side on other days, one of which may share the total. Asked together,
neither the day nor the total counted, and another receipt of the same day
was filed in its place with refuse_wrong_documents set. Now the render
checks it against the same day's and the saved file is checked again
against the rows either side (App._rivals), as Bank of America does. With
none of the same day the render checks it against those either side, so
no check is the plain one while another purchase is listed, which would
destroy a receipt that prints its day and total in forms it does not know.

Run through the app's own process_purchases(), with the render drawing a
receipt whose text names a day and a total, and the real delivery.place
checking it as render would.
"""
import contextlib
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_receipts as app_mod
import costco_site as site
from paperpull_core import delivery, testkit
from paperpull_core.journal import Journal
from paperpull_core.models import Item, Purchase

# Newest first, as process_purchases takes them. Two warehouse visits on
# the 15th, the 60.00 one beside a gas fill of 60.00 on the 9th, and the
# 143.21 one beside a visit of 143.21 on the 2nd.
LISTED = [("2026-08-21", "77.10"), ("2026-08-15", "60.00"), ("2026-08-15", "143.21"),
          ("2026-08-09", "60.00"), ("2026-08-02", "143.21"), ("2026-07-30", "12.34")]


class _Store:
    def update(self, *a, **kw):
        pass

    def append_rows(self, *a, **kw):
        pass

    def get(self, *a, **kw):
        return None


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


class _Page:
    url = "https://www.costco.com/OrderStatusCmd"


def receipt(day: str, total: str) -> bytes:
    return testkit.text_pdf(["COSTCO WHOLESALE", "Kirkland Signature Paper Towels",
                             "SUBTOTAL", "TOTAL %s" % total,
                             "%s/%s/%s 14:02" % (day[5:7], day[8:10], day[:4]),
                             "THANK YOU PLEASE COME AGAIN"])


def _run(tmp_path, monkeypatch, brings=None, strict=True):
    """process_purchases over LISTED, the render for (day, total) drawing
    the receipt `brings` names for it, its own when it names none."""
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": strict}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress = app.discovery = app.index_csv = app.order_csv = _Store()
    app.rules = None
    app._journal = Journal()
    app.page = lambda: _Page()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    app.write_failure = lambda *a, **kw: None
    monkeypatch.setattr(app_mod, "restoring", lambda page, **kw: contextlib.nullcontext())
    for name in ("goto_receipt", "goto_orders", "scroll_full_page"):
        monkeypatch.setattr(site, name, lambda *a: None)
    monkeypatch.setattr(site, "extract_details", lambda page, purchase: purchase)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "on_receipt_page", lambda page: True)
    monkeypatch.setattr(site, "receipt_is_present", lambda page: True)
    real_place = delivery.place

    def render(page, draw, out_path, *, expect=None, rivals=(), journal=None, strict=True):
        asked = (expect.date, expect.total)
        came = (brings or {}).get(asked, asked)
        return real_place(came if isinstance(came, bytes) else receipt(*came), out_path,
                          expect=expect, rivals=rivals, journal=journal, strict=strict)

    monkeypatch.setattr(delivery, "render", render)
    purchases = [Purchase(purchase_date=day, order_number="wh-%s-%s-%d" % (
        day.replace("-", ""), total.replace(".", ""), n), total=total,
        purchase_type="In-Warehouse", items=[Item(name="Kirkland Signature Paper Towels")])
        for n, (day, total) in enumerate(LISTED)]
    app.process_purchases(purchases)
    return app, len(list(tmp_path.glob("*.pdf")))


def test_every_receipt_naming_its_own_day_and_total_is_filed(tmp_path, monkeypatch):
    app, filed = _run(tmp_path, monkeypatch)
    assert filed == 6 and not app.stats["wrong_document"], dict(app.stats)


def test_the_other_receipt_of_the_day_is_refused_when_another_day_shares_its_total(
        tmp_path, monkeypatch):
    """The 60.00 visit's receipt comes back as the 143.21 visit's of the same
    day. The 2nd's visit shares that total and the 15th shares the day, so
    one pool counted neither and filed it unchecked."""
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-15", "60.00"): ("2026-08-15", "143.21")})
    assert filed == 5 and app.stats["wrong_document"] == 1, dict(app.stats)


def test_another_days_receipt_of_the_same_total_is_refused(tmp_path, monkeypatch):
    """The 60.00 visit's receipt comes back as the gas fill's of the 9th. The
    check against its own day passes it on the total, and the check against
    the rows either side refuses it by its day."""
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-15", "60.00"): ("2026-08-09", "60.00")})
    assert filed == 5 and app.stats["wrong_document"] == 1, dict(app.stats)


@pytest.mark.parametrize("came", [("2026-08-15", "143.21"), ("2026-08-09", "60.00")],
                         ids=["same day", "same total"])
def test_with_refuse_wrong_documents_off_nothing_is_destroyed(tmp_path, monkeypatch, came):
    app, filed = _run(tmp_path, monkeypatch, strict=False,
                      brings={("2026-08-15", "60.00"): came})
    assert filed == 6 and not app.stats["wrong_document"], dict(app.stats)


def test_a_receipt_printing_its_day_and_total_in_forms_not_known_is_kept(tmp_path, monkeypatch):
    """The 20th's is alone on its day. Nothing in it names another purchase,
    so nothing says it is not this one, and the render once made the plain
    check and destroyed it for its day and total not being found."""
    unknown = testkit.text_pdf(["COSTCO WHOLESALE", "Kirkland Signature Paper Towels",
                                "TOTAL SEVENTY SEVEN 10", "21 AUG 26 14:02",
                                "THANK YOU PLEASE COME AGAIN"])
    app, filed = _run(tmp_path, monkeypatch, brings={("2026-08-21", "77.10"): unknown})
    assert filed == 6 and not app.stats["wrong_document"], dict(app.stats)


def test_a_refused_receipt_that_cannot_be_removed_is_not_said_to_be_destroyed(
        tmp_path, monkeypatch):
    """A sync client holding the new file. It stays where it was saved, as it
    would with refusing off, rather than counted as destroyed while there."""
    real_unlink = Path.unlink

    def held(self, *a, **kw):
        if self.parent == tmp_path and self.suffix == ".pdf":
            raise PermissionError("held")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", held)
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-15", "60.00"): ("2026-08-09", "60.00")})
    assert filed == 6 and not app.stats["wrong_document"], dict(app.stats)
