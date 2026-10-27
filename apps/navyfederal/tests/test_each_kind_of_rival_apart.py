"""A statement is checked against each kind of statement it could be taken for apart.

Navy Federal bills every account on the same day. One pool held both the
other account's statement of the day, which shares the day, and the
account's own statements either side, which share the account, so neither
the day nor the account counted for any statement on a shared day, and a
wrong one was filed unchecked with refuse_wrong_documents set. Sixteen of
the owner's sixty four statements share a day. Now the capture checks it
against the same day's and the saved file is checked again against its own
account's either side (App._rivals), as Bank of America does. With none of
the same day the capture checks it against those either side, so no check
is the plain check of its day while another statement is listed, which
would destroy one that prints its day in a form the check does not know.

Run through the app's own process() and download_one(), with the press
bringing a statement whose text names a day and an account, and the real
delivery.place checking it as deliver would.
"""
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import navyfederal_docs as app_mod
import navyfederal_site as site
from paperpull_core import delivery, testkit
from paperpull_core.journal import Journal

CHECKING, CARD = "Everyday Checking", "Visa Signature Rewards"
# Both accounts billed on each of three days, newest first as _select hands them.
LISTED = [("2026-09-23", CHECKING), ("2026-09-23", CARD), ("2026-08-23", CHECKING),
          ("2026-08-23", CARD), ("2026-07-23", CHECKING), ("2026-07-23", CARD)]


class _Store:
    def get(self, *a, **kw):
        return None

    def update(self, *a, **kw):
        pass

    def append_rows(self, *a, **kw):
        pass


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


def statement(day: str, account: str) -> bytes:
    return testkit.text_pdf(["Navy Federal Credit Union", "Statement of Account",
                             "Statement closing date %s/%s/%s" % (day[5:7], day[8:10], day[:4]),
                             account, "Beginning balance and ending balance"])


def _run(tmp_path, monkeypatch, brings=None, strict=True, listed=LISTED):
    """process() over `listed`, the press for (day, account) bringing the
    statement `brings` names for it, its own when it names none, or the
    bytes it names. Answers the app and what was filed."""
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": strict}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress = app.discovery = app.index_csv = _Store()
    app._journal = Journal()
    app.page = lambda: object()
    app.check_session = lambda page: None
    app._on_its_site = lambda: app.page()
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: None
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    # The request as the site builds it, its identity the row's (identity_for).
    monkeypatch.setattr(site, "statement_request", lambda page, acct, day: delivery.DocumentRequest(
        trigger=lambda: None, expect=site.identity_for(SimpleNamespace(date=day, account=acct)),
        hints=(day, acct)))
    real_place = delivery.place

    def deliver(page, request, out_path, *, rivals=(), journal=None, strict=True, **kw):
        asked = tuple(request.hints)
        came = (brings or {}).get(asked, asked)
        data = came if isinstance(came, bytes) else statement(*came)
        return real_place(data, out_path, expect=request.expect, rivals=rivals,
                          journal=journal, strict=strict)

    monkeypatch.setattr(delivery, "deliver", deliver)
    docs = [app_mod.Document(title="Statement", category="Statement",
                             summary="%s Statement" % acct, date=day, account=acct,
                             document_id="doc-%d" % n)
            for n, (day, acct) in enumerate(listed)]
    app.process(docs)
    return app, sorted(p.name for p in tmp_path.glob("*.pdf"))


def test_every_statement_naming_its_own_day_and_account_is_filed(tmp_path, monkeypatch):
    app, filed = _run(tmp_path, monkeypatch)
    assert len(filed) == 6 and not app.stats["wrong_document"], filed
    assert app.stats["manual_review"] == 0


def test_another_month_of_the_same_account_is_refused_on_a_shared_day(tmp_path, monkeypatch):
    """August's checking statement comes back as July's. It names the right
    account, and the card's statement of August shares August's day, so one
    pool counted neither and filed it unchecked."""
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-23", CHECKING): ("2026-07-23", CHECKING)})
    assert not any(n.startswith("2026-08-23") and "Checking" in n for n in filed), filed
    assert len(filed) == 5
    assert app.stats["wrong_document"] == 1


def test_another_accounts_statement_of_the_same_day_is_refused(tmp_path, monkeypatch):
    """August's checking statement comes back as the card's of August. Its
    day is August's, and the card's statements of the other months shared
    its account, so one pool counted neither."""
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-23", CHECKING): ("2026-08-23", CARD)})
    assert len(filed) == 5 and app.stats["wrong_document"] == 1, filed


@pytest.mark.parametrize("came", [("2026-07-23", CHECKING), ("2026-08-23", CARD)],
                         ids=["another month", "another account"])
def test_with_refuse_wrong_documents_off_nothing_is_destroyed(tmp_path, monkeypatch, came):
    """Off, the app keeps what it was handed, as it keeps one the capture
    itself refuses."""
    app, filed = _run(tmp_path, monkeypatch, strict=False,
                      brings={("2026-08-23", CHECKING): came})
    assert len(filed) == 6 and not app.stats["wrong_document"], filed


# The closing day written 08-23-26, a form the check does not know, and the
# period before it as 07-24-26, so neither its day nor another's is found.
UNKNOWN_FORM = testkit.text_pdf(["Navy Federal Credit Union", "Statement of Account",
                                 "Statement period 07-24-26 to 08-23-26", CHECKING,
                                 "Beginning balance and ending balance"])


@pytest.mark.parametrize("shared", [True, False], ids=["a shared day", "its own day"])
def test_a_statement_printing_its_day_in_a_form_not_known_is_kept(tmp_path, monkeypatch, shared):
    """Nothing in it names another statement, so nothing says it is not this
    one. On a day no other account is billed the capture once made the
    plain check of its day and destroyed it for that day not being found."""
    listed = LISTED if shared else [r for r in LISTED if r != ("2026-08-23", CARD)]
    app, filed = _run(tmp_path, monkeypatch, listed=listed,
                      brings={("2026-08-23", CHECKING): UNKNOWN_FORM})
    assert len(filed) == len(listed) and not app.stats["wrong_document"], filed


def test_a_refused_statement_that_cannot_be_removed_is_not_said_to_be_destroyed(
        tmp_path, monkeypatch):
    """A sync client holding the new file. It stays where it was saved, as it
    would with refusing off, rather than counted as destroyed while there."""
    real_unlink = Path.unlink

    def held(self, *a, **kw):
        if self.parent == tmp_path and self.name.startswith("2026-08-23") and "Checking" in self.name:
            raise PermissionError("held")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", held)
    app, filed = _run(tmp_path, monkeypatch,
                      brings={("2026-08-23", CHECKING): ("2026-07-23", CHECKING)})
    assert len(filed) == 6 and not app.stats["wrong_document"], filed


def test_each_check_is_handed_one_kind(monkeypatch):
    docs = [app_mod.Document(date=day, account=acct, document_id=str(n))
            for n, (day, acct) in enumerate(LISTED)]
    same_day, near = app_mod.App._rivals(docs, docs[2])
    assert [(r.date, r.label) for r in same_day] == [("2026-08-23", CARD)]
    assert [(r.date, r.label) for r in near] == [("2026-09-23", CHECKING), ("2026-07-23", CHECKING)]
