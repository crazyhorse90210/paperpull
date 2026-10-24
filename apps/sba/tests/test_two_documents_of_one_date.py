"""Two documents of one date, and a control that could not be read.

SBA's statements page code was copied line for line from the Wells Fargo
app, and a read-only audit of that code found this on 2026-10-01 (fixed
there in 240a473e). Discovery kept one document per date, named Tax
Document or Loan Statement after the first control of that date it could
read, and the download pressed the first control carrying the date,
whatever it fetched. So when a 1098 and a statement share a date only the
first of them is ever found. And when the 1098 could not be read while the
page was surveyed, the date was recorded as the statement, the download
pressed the 1098, and it was filed as the statement. Nothing checks which
document a saved file is, so nothing would have said so.

The Wells Fargo repair took four versions. A review of the first found a
row offering View and Download refused as two documents, a tax row with no
date of its own borrowing the date of the statement row above it, and a
row's words deciding the kind of every control in it. A review of the
second found a menu's list item taken for an entry, and another control's
name counting toward a control's kind. A review of the third found that a
careful reading alone filed controls under kinds and dates the code before
it would not have. So each control is read both ways and filed only where
the two agree, and where they disagree it is counted and left for a person.
Each of those shapes is a test below, in SBA's own words, and a shape the
code before any repair got right is held to the same answer here.

Everything here is invented, and it drives a real browser, since what a
read of an element answers and where a press lands are what a fake page
gets wrong. Each page records where every click truly landed, in the
capture phase, by the data-guid around the click's target. A stalled read
is Playwright's own TimeoutError, raised by testkit.stall_reads.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import sba_docs as app_mod
import sba_site as site
from paperpull_core.testkit import receipt_app, stall_reads, text_pdf

DAY = "2026-01-31"
STATEMENT = "Loan Statement - January 31, 2026"
TAX = "Tax Document - January 31, 2026"

# Every read discovery and the download make of a control, so a stalled
# control answers none of them.
UNANSWERED = ("get_attribute", "inner_text", "evaluate")

UNREAD = "a document control on the page could not be read"
TWO_ROWS = "more than one row of this date holds this kind of document"

# Where each click landed, by the data-guid around its target.
LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " e.preventDefault(); }, true);</script>")

STATEMENT_ROW = ("<tr data-guid='r-statement'><td>01/31/2026</td><td>Loan statement</td>"
                 "<td><a href='#' data-guid='g-statement'>View statement</a></td></tr>")
TAX_ROW = ("<tr data-guid='r-tax'><td>01/31/2026</td><td>Form 1098</td>"
           "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>")
# A second loan's statement of the same day, printing the same words.
TWIN_ROW = ("<tr data-guid='r-twin'><td>01/31/2026</td><td>Loan statement</td>"
            "<td><a href='#' data-guid='g-twin'>View statement</a></td></tr>")
# One statement offered twice, the way many statement lists do.
VIEW_AND_DOWNLOAD_ROW = ("<tr data-guid='r-statement'><td>01/31/2026</td><td>Loan statement</td>"
                         "<td><a href='#' data-guid='g-view'>View</a> "
                         "<a href='#' data-guid='g-download'>Download</a></td></tr>")
OTHER_DAY_ROW = ("<tr data-guid='r-older'><td>12/31/2025</td><td>Loan statement</td>"
                 "<td><a href='#' data-guid='g-older'>View statement</a></td></tr>")


def _page(*rows):
    return "<table><tbody>%s</tbody></table>%s" % ("".join(rows), LISTENER)


def _blocks(*blocks):
    """A page laid out in plain blocks, with no table, list or grid rows."""
    return "<div>%s</div>%s" % ("".join(blocks), LISTENER)


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        driver.stop()
        pytest.skip("no browser to drive, %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def on_this_machine(monkeypatch):
    """The page is set here rather than opened at lending.sba.gov, and it
    has nothing to expand or scroll."""
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)
    monkeypatch.setattr(site, "scroll_full_page", lambda pg, *a, **k: None)


@pytest.fixture
def presses(monkeypatch):
    """Stands in for the catch. It presses the element the way the real
    catch does, remembers where the press landed, and saves a PDF that
    names the control it came from."""
    hits: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        before = len(pg.evaluate("window.hits"))
        try:
            el.click(timeout=3000)
        except Exception as e:
            hits.append("click failed " + type(e).__name__)
            return False
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        Path(out_path).write_bytes(b"%PDF-1.4\n% " + ",".join(landed).encode() + b"\n%%EOF\n")
        return bool(landed)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return hits


def _download(page, tmp_path, title, iso=DAY):
    trace: list = []
    saved = site.download_bill(page, tmp_path, iso, tmp_path / "saved.pdf", title=title, trace=trace)
    return saved, trace


def _refusals(trace):
    return [t.get("why") for t in trace if "why" in t]


def _found(docs):
    return sorted((d.date_text, d.kind, d.title) for d in docs)


# --- two kinds of document on one date ---------------------------------------

@pytest.mark.parametrize("rows", [(TAX_ROW, STATEMENT_ROW), (STATEMENT_ROW, TAX_ROW)],
                         ids=["tax form first", "statement first"])
def test_a_statement_and_a_tax_form_of_one_date_are_both_found(page, rows):
    """The statement was never found once the 1098 came first, and the 1098
    never once the statement did."""
    page.set_content(_page(*rows))
    assert _found(site.collect_download_docs(page)) == [
        (DAY, "statement", STATEMENT), (DAY, "tax", TAX)]


@pytest.mark.parametrize("rows", [(TAX_ROW, STATEMENT_ROW), (STATEMENT_ROW, TAX_ROW)],
                         ids=["tax form first", "statement first"])
@pytest.mark.parametrize("title, guid", [(STATEMENT, "g-statement"), (TAX, "g-tax")],
                         ids=["the statement", "the tax form"])
def test_each_document_of_the_date_is_pressed_for_its_own_kind(page, presses, tmp_path, rows, title, guid):
    """The download asked for a date alone and pressed the first control
    carrying it, so whichever came first was saved under both names."""
    page.set_content(_page(*rows))
    saved, trace = _download(page, tmp_path, title)
    assert saved and presses == [guid], (presses, trace)
    assert guid.encode() in (tmp_path / "saved.pdf").read_bytes()


# --- a control that could not be read ----------------------------------------

@pytest.mark.parametrize("rows, stalled, kept, guid", [
    ((TAX_ROW, STATEMENT_ROW), "g-tax", STATEMENT, "g-statement"),
    ((STATEMENT_ROW, TAX_ROW), "g-statement", TAX, "g-tax"),
], ids=["the 1098 unread", "the statement unread"])
def test_a_control_unread_during_discovery_is_not_saved_as_another(page, presses, tmp_path,
                                                                  rows, stalled, kept, guid):
    """The case the audit read. The first control of the date could not be
    read while the page was surveyed, so the date was recorded as the other
    document. Once it answered again, the download pressed it, the first
    control carrying the date, and filed it under the other's name."""
    page.set_content(_page(*rows))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {stalled}, locator=UNANSWERED)
        docs = site.collect_download_docs(page)
    assert [d.title for d in docs] == [kept]
    saved, trace = _download(page, tmp_path, kept)
    assert saved and presses == [guid], (presses, trace)
    assert guid.encode() in (tmp_path / "saved.pdf").read_bytes()


def test_a_control_still_unread_at_the_download_keeps_the_other_unpressed(page, presses, tmp_path, monkeypatch):
    """The 1098 still does not answer when the statement is fetched. It was
    passed over as if it were not on the page, which left the statement as
    the only control of its date and kind. A control that could not be read
    may be a second statement of the day, so nothing is pressed, and the
    reason is written in words of the app's own."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    stall_reads(monkeypatch, {"g-tax"}, locator=UNANSWERED)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [UNREAD], trace
    assert not (tmp_path / "saved.pdf").exists()
    said = json.dumps(trace)
    assert "1098" not in said and "statement" not in said.lower(), said


def test_an_unread_control_lends_no_other_control_its_date_or_kind(page, monkeypatch):
    """A control that would not answer is counted and left for the next run.
    The documents around it are named from their own controls only."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW, OTHER_DAY_ROW))
    stall_reads(monkeypatch, {"g-tax"}, locator=UNANSWERED)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Loan Statement - December 31, 2025"),
                            (DAY, "statement", STATEMENT)]
    assert docs.unread == 1


# --- two rows of one date and kind ---------------------------------------------

def test_two_statements_of_one_date_are_refused_rather_than_taken_as_one(page, presses, tmp_path):
    """Two loans' statements of the same day, in rows that print the same
    words. The first was saved as the day's statement and the second was
    never asked for. Nothing on the page tells them apart, so neither is
    guessed at."""
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_discovery_records_two_rows_of_one_date_once_and_says_so(page):
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW, TAX_ROW))
    docs = site.collect_download_docs(page)
    assert sorted((d.title, d.rows) for d in docs) == [(STATEMENT, 2), (TAX, 1)]


def test_view_and_download_in_one_row_are_one_document(page, presses, tmp_path):
    """Two controls in one row fetch one document, so the row is not
    refused as two. The first of them is pressed, as it always was."""
    page.set_content(_page(VIEW_AND_DOWNLOAD_ROW))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_document_alone_on_its_date_is_saved_as_before(page, presses, tmp_path):
    page.set_content(_page(STATEMENT_ROW, OTHER_DAY_ROW))
    saved, trace = _download(page, tmp_path, "Loan Statement - December 31, 2025", iso="2025-12-31")
    assert saved and presses == ["g-older"], (presses, trace)


# --- what the download is asked for, and when the page moves -------------------

def test_a_title_that_names_no_kind_presses_nothing(page, presses, tmp_path):
    """The kind is read back out of the title discovery wrote. A title it
    did not write says nothing about the kind, so nothing is guessed."""
    page.set_content(_page(STATEMENT_ROW))
    saved, trace = _download(page, tmp_path, "")
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the title does not say which kind of document it is"], trace


def test_a_page_whose_controls_cannot_be_counted_presses_nothing(page, presses, tmp_path, monkeypatch):
    """The page's controls would not even be counted, so what any of them
    fetches cannot be told, and nothing is pressed."""
    page.set_content(_page(STATEMENT_ROW))
    stall_reads(monkeypatch, {"g-statement"}, locator=("count",))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [UNREAD], trace


def test_a_page_redrawn_between_the_look_and_the_press_presses_nothing(page, presses, tmp_path, monkeypatch):
    """The statement is the first control when the page is read, and the
    page then draws the 1098 above it. The control at the statement's place
    is read again before it is pressed, and it is not the statement."""
    page.set_content(_page(STATEMENT_ROW, TAX_ROW))
    real = site._survey

    def then_redrawn(pg):
        found = real(pg)
        pg.evaluate("() => { const t = document.querySelector('[data-guid=r-tax]');"
                    " t.parentNode.insertBefore(t, t.parentNode.firstChild); }")
        return found
    monkeypatch.setattr(site, "_survey", then_redrawn)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the control was not the same when read again"], trace


def test_the_element_read_again_is_the_one_pressed(page, tmp_path, monkeypatch):
    """The page draws a 1098 row above the statement just as the press is
    made. The element read again is what is pressed, never whatever stands
    at its place among the controls by then."""
    page.set_content(_page(STATEMENT_ROW, OTHER_DAY_ROW))
    hits: list = []

    def drawn_above_then_pressed(pg, el, label, out_path, trace=None, dl_dir=None):
        pg.evaluate("row => document.querySelector('tbody').insertAdjacentHTML('afterbegin', row)", TAX_ROW)
        before = len(pg.evaluate("window.hits"))
        el.click(timeout=3000)
        hits.extend(pg.evaluate("window.hits")[before:])
        Path(out_path).write_bytes(b"%PDF-1.4\n%%EOF\n")
        return True
    monkeypatch.setattr(site, "_catch_pdf", drawn_above_then_pressed)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and hits == ["g-statement"], (hits, trace)


# --- a whole run ----------------------------------------------------------------
#
# The app's own discovery and download, the way a run calls them, so the
# title discovery writes is the one the download is handed. Each press saves
# a real PDF that names the control it came from, and what the run filed is
# read back out of the folders.

@pytest.fixture
def run(page, tmp_path, monkeypatch):
    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        before = len(pg.evaluate("window.hits"))
        el.click(timeout=3000)
        landed = pg.evaluate("window.hits")[before:]
        Path(out_path).write_bytes(text_pdf(["pressed " + ",".join(landed)]))
        return bool(landed)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    app = receipt_app(app_mod, tmp_path)
    app._context, app._work_page, app._dl_dir = page.context, page, tmp_path / "downloads"
    # The page is set into a blank tab, not on the SBA's own site, so the
    # check that the tab is on it (tabs.on_its_site) is stood in for too.
    app._on_its_site = lambda: page
    return app


def _filed(app):
    """Each folder the run saved into, and the controls its PDFs came from."""
    out: dict = {}
    for pdf in sorted(app.paths.root.rglob("*.pdf")):
        pressed = re.search(rb"pressed ([\w,-]*)", pdf.read_bytes()).group(1).decode()
        out.setdefault(pdf.parent.name, []).append(pressed)
    return out


def test_a_run_files_the_statement_and_the_1098_of_one_day_each_as_itself(page, run):
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    run.cmd_discover(quiet=True)
    run.process(run._select())
    assert _filed(run) == {"Statements": ["g-statement"], "Tax Documents": ["g-tax"]}


def test_a_run_never_files_a_1098_unread_at_discovery_as_the_statement(page, run):
    """The audit's case through the whole run. The statement is filed as
    the statement, and the 1098 waits for a run that can read it."""
    page.set_content(_page(TAX_ROW, STATEMENT_ROW))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {"g-tax"}, locator=UNANSWERED)
        run.cmd_discover(quiet=True)
    run.process(run._select())
    assert _filed(run) == {"Statements": ["g-statement"]}


def test_a_twin_discovery_saw_is_refused_when_the_download_cannot_see_it(page, run):
    """Discovery scrolls the page and the download does not, so a row
    discovery saw may not be drawn when the download looks. How many rows
    discovery found travels with the document, through the whole run."""
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    run.cmd_discover(quiet=True)
    page.evaluate("() => document.querySelector('[data-guid=r-twin]').remove()")
    run.process(run._select())
    assert _filed(run) == {}
    attempt = json.loads((run.paths.diagnostics / "download-attempt.json").read_text(encoding="utf-8"))
    assert [t.get("why") for t in attempt["responses"]] == [
        "discovery found more than one row of this date holding this kind of document"], attempt


def test_a_twin_a_later_discovery_saw_is_refused_though_the_first_saw_none(page, run):
    """The first discovery saw one row of the day and a later one saw two.
    The record carries the later count, so the statement is refused even
    when the download sees one row again."""
    page.set_content(_page(STATEMENT_ROW))
    run.cmd_discover(quiet=True)
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW))
    run.cmd_discover(quiet=True)
    page.set_content(_page(STATEMENT_ROW))
    run.process(run._select())
    assert _filed(run) == {}


def test_diagnose_counts_what_the_download_would_refuse(page, run, monkeypatch):
    """A repair needs the rows of a date and kind, and the controls that
    would not answer or whose two readings disagree, so Diagnose says how
    many of each it saw. Its look at the page's links is another test's."""
    monkeypatch.setattr(site, "survey", lambda pg, **k: {})
    page.set_content(_page(STATEMENT_ROW, TWIN_ROW, "<tr><td>01/31/2026</td><td>Taxes</td>"
                           "<td><a href='#' data-guid='g-taxes'>View</a></td></tr>", TAX_ROW))
    with pytest.MonkeyPatch.context() as mp:
        stall_reads(mp, {"g-tax"}, locator=UNANSWERED)
        run.cmd_diagnose()
    info = json.loads((run.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert [(d["kind"], d["rows"]) for d in info["documents_recognized"]] == [("statement", 2)], info
    assert (info["document_controls_unread"], info["document_controls_unsure"]) == (1, 1), info


# --- the shapes the review of the first repair found ---------------------------

# View and Download, each naming the date for a screen reader.
DATED_NAMES_ROW = ("<tr data-guid='r-statement'><td>01/31/2026</td><td>Loan statement</td><td>"
                   "<a href='#' data-guid='g-view' aria-label='View statement January 31, 2026'>View</a> "
                   "<a href='#' data-guid='g-download' aria-label='Download statement January 31, 2026'>"
                   "Download</a></td></tr>")
# A link printing the date beside a plain one.
DATED_LINK_ROW = ("<tr data-guid='r-statement'><td>Loan statement</td>"
                  "<td><a href='#' data-guid='g-pdf'>Statement 01/31/2026 (PDF)</a></td>"
                  "<td><a href='#' data-guid='g-download'>Download PDF</a></td></tr>")
CARD = ("<div data-guid='c-statement'><span>01/31/2026</span> Loan statement "
        "<a href='#' data-guid='g-view'>View</a> <a href='#' data-guid='g-download'>Download</a></div>")
UNDATED_TAX_ROW = ("<tr data-guid='r-tax'><td>Tax year 2025</td><td>Form 1098</td>"
                   "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>")
SECOND_UNDATED_TAX_ROW = ("<tr data-guid='r-tax2'><td>Tax year 2025</td><td>Form 1099-C</td>"
                          "<td><a href='#' data-guid='g-tax2'>Download 1099-C</a></td></tr>")
BOTH_IN_ONE_ROW = ("<tr data-guid='r-both'><td>01/31/2026</td>"
                   "<td><a href='#' data-guid='g-statement'>View statement</a></td>"
                   "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>")
# Two loans' statements under one heading that prints their date.
UNDER_ONE_DATE = ("<div data-guid='d-day'><h3>January 31, 2026</h3>"
                  "<div>Disaster loan <a href='#' data-guid='g-first'>View</a></div>"
                  "<div>Express loan <a href='#' data-guid='g-second'>View</a></div></div>")
DATED_PDF_ON_A_TAX_ROW = ("<tr data-guid='r-tax'><td>Form 1098</td><td>"
                          "<a href='#' data-guid='g-tax' aria-label='Download PDF January 31, 2026'>PDF</a>"
                          "</td></tr>")
TAXES_ROW = ("<tr data-guid='r-taxes'><td>01/31/2026</td><td>Taxes</td>"
             "<td><a href='#' data-guid='g-taxes'>View</a></td></tr>")


@pytest.mark.parametrize("content, first", [
    (_page(DATED_NAMES_ROW), "g-view"),
    (_page(DATED_LINK_ROW), "g-pdf"),
    (_blocks(CARD), "g-view"),
], ids=["names that print the date", "a link that prints the date", "a card"])
def test_two_controls_of_one_statement_are_one_document(page, presses, tmp_path, content, first):
    """The first Wells Fargo repair made a control naming its own date a row
    of its own, so a statement offered by View and Download was refused as
    two. Two controls of one row, or of one card, fetch one document."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == [first], (presses, trace)


@pytest.mark.parametrize("rows", [(STATEMENT_ROW, UNDATED_TAX_ROW, SECOND_UNDATED_TAX_ROW),
                                  (UNDATED_TAX_ROW, SECOND_UNDATED_TAX_ROW, STATEMENT_ROW)],
                         ids=["statement first", "tax forms first"])
def test_a_tax_row_without_a_date_borrows_none_from_a_statement_row(page, presses, tmp_path, rows):
    """A tax row printing no date of its own climbed to the table around
    every row and took the statement row's date from it. It would be saved
    as a tax form of that day, the two tax rows would count as one, and the
    next month's statement would move the date it borrowed."""
    page.set_content(_page(*rows))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["no control of this date is this kind of document"], trace
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


def test_a_statement_beside_a_1098_in_one_row_is_never_pressed_for_it(page, presses, tmp_path):
    """The row's words decided the kind of every control in it, so both read
    as the tax form and the statement's View, the first, was pressed for the
    1098. Read the old way View is still the tax form, read with care it is
    the statement, so it is left for a person, and the 1098 is its own."""
    page.set_content(_page(BOTH_IN_ONE_ROW))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)
    presses.clear()
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["no control of this date is this kind of document"], trace


def test_two_loans_under_one_date_heading_are_refused_rather_than_taken_as_one(page, presses, tmp_path):
    """No table or list says where one statement ends. Each loan's part
    prints words of its own, so each is a row, and two rows of one date
    holding statements cannot be told apart."""
    page.set_content(_blocks(UNDER_ONE_DATE))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]


def test_a_date_heading_over_entries_that_print_none_is_their_date(page, presses, tmp_path):
    """A list grouped by day prints the date once, over the day's entries,
    and the heading dates them. The old reading takes the kind from the
    whole day's words, which name a 1098, so the statement's entry reads
    as a tax form that way and is left for a person rather than filed."""
    page.set_content("<ul><li>January 31, 2026<ul>"
                     "<li>Loan statement <a href='#' data-guid='g-statement'>View</a></li>"
                     "<li>Form 1098 <a href='#' data-guid='g-tax'>Download</a></li>"
                     "</ul></li></ul>" + LISTENER)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


def test_two_rows_under_one_date_heading_row_are_two_documents(page, presses, tmp_path):
    """A heading row prints the day, and the statements under it are rows
    holding nothing but their controls. Each table row is an entry of its
    own, so the two are two documents, and neither is guessed at."""
    page.set_content(_page("<tr><td colspan='2'>January 31, 2026</td></tr>",
                           "<tr><td><a href='#' data-guid='g-first'>View statement</a></td></tr>",
                           "<tr><td><a href='#' data-guid='g-second'>View statement</a></td></tr>"))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_a_pdf_link_naming_only_the_date_on_a_1098_row_is_filed_as_neither(page):
    """A control naming its date was read as a statement from its name alone,
    while its row says 1098. The two readings disagree, so it is left for a
    person rather than filed as a statement."""
    page.set_content(_page(DATED_PDF_ON_A_TAX_ROW))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


def test_a_row_that_says_taxes_is_not_filed_as_a_tax_form(page):
    """Read the old way, "Taxes" holds the word tax and the statement was a
    tax form. Read with care, tax is a word of its own. They disagree, so
    the statement is left for a person rather than filed as a tax form."""
    page.set_content(_page(TAXES_ROW))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


def test_a_control_that_will_not_answer_its_second_read_is_not_pressed(page, presses, tmp_path, monkeypatch):
    """The page was read whole, then the control chosen does not answer when
    it is read again as the element that will be pressed."""
    page.set_content(_page(STATEMENT_ROW))
    stall_reads(monkeypatch, {"g-statement"}, locator=(), handle=UNANSWERED)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the control was not the same when read again"], trace


def test_a_row_drawn_again_between_the_look_and_the_press_is_not_trusted(page, presses, tmp_path, monkeypatch):
    """The list is drawn again, with the same words, after the page was
    read. The control at the statement's place reads the same, but its row
    is one the look never saw, so it is not taken for the control read."""
    page.set_content(_page(STATEMENT_ROW))
    real = site._survey

    def then_redrawn(pg):
        found = real(pg)
        pg.evaluate("() => { const b = document.querySelector('tbody'); b.innerHTML = b.innerHTML; }")
        return found
    monkeypatch.setattr(site, "_survey", then_redrawn)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the control was not the same when read again"], trace


# --- the shapes the second review found ---------------------------------------
#
# The second Wells Fargo version took any list item, table row or grid row
# for an entry, by its tag alone, and read a control's kind from every word
# of it, the names of other document controls included.

def test_a_menu_of_actions_is_not_an_entry(page, presses, tmp_path):
    """View and Download sit in a menu, each in a list item of its own,
    inside the entry that names a 1098. The list items print nothing of
    their own, so the entry around them says what both fetch."""
    page.set_content(_blocks("<div data-guid='e-tax'>01/31/2026 Form 1098 <ul>"
                             "<li><a href='#' data-guid='g-view'>View</a></li>"
                             "<li><a href='#' data-guid='g-download'>Download</a></li></ul></div>"))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(TAX, 1)]
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


def test_entries_gathered_in_one_list_item_keep_their_own_kinds(page, presses, tmp_path):
    """A year's documents gathered in one list item, each entry printing its
    own date. Both controls read as the tax form, and the statement's View
    was pressed for the 1098."""
    page.set_content("<ul><li>"
                     "<div>01/31/2026 Loan statement <a href='#' data-guid='g-statement'>View</a></div>"
                     "<div>01/31/2026 Form 1098 <a href='#' data-guid='g-tax'>View</a></div>"
                     "</li></ul>" + LISTENER)
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT), (DAY, "tax", TAX)]
    for title, guid in ((TAX, "g-tax"), (STATEMENT, "g-statement")):
        presses.clear()
        saved, trace = _download(page, tmp_path, title)
        assert saved and presses == [guid], (title, presses, trace)


def test_a_control_printing_a_1098_under_a_plain_label_is_the_tax_form(page):
    """Its label says only Download, and the words it shows name the form."""
    page.set_content(_blocks("<a href='#' data-guid='g-tax' aria-label='Download'>Form 1098 01/31/2026</a>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


def test_a_view_beside_a_1098_link_is_never_pressed_for_the_1098(page, presses, tmp_path):
    """A row's View beside the row's Download 1098. The row's words were
    read with the other control's name in them, so View read as the tax
    form and, coming first, was pressed for it. Read with care View is the
    statement, so the two readings disagree and View is left alone."""
    page.set_content(_page("<tr><td>01/31/2026</td><td>Loan statement</td>"
                           "<td><a href='#' data-guid='g-statement'>View</a></td>"
                           "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


@pytest.mark.parametrize("content", [
    _page("<tr><td>01/31/2026</td><td>Form 1098</td>"
          "<td><span>Online</span> <a href='#' data-guid='g-view'>View</a></td>"
          "<td><span>PDF</span> <a href='#' data-guid='g-download'>Download</a></td></tr>"),
    _blocks("<div>01/31/2026 Form 1098 "
            "<span>Online <a href='#' data-guid='g-view'>View</a></span> "
            "<span>PDF <a href='#' data-guid='g-download'>Download</a></span></div>"),
], ids=["in a table row", "on a card"])
def test_a_caption_beside_each_control_keeps_them_one_document(page, presses, tmp_path, content):
    """A caption beside each control is words of its own, and it neither
    splits the entry in two nor hides what the entry is."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(TAX, 1)]
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_link_every_row_calls_view_statement_is_filed_as_neither_in_a_1098_row(page):
    """Some lists word every document's link the same. The row says 1098 and
    the link says statement, so the two readings disagree and the link is
    left for a person rather than filed as either."""
    page.set_content(_page("<tr><td>01/31/2026</td><td>Form 1098</td>"
                           "<td><a href='#' data-guid='g-tax'>View statement</a></td></tr>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


def test_a_heading_that_says_tax_does_not_make_a_statement_a_tax_form(page, presses, tmp_path):
    """The day's heading names tax documents and one entry under it is the
    statement. Read with care the entry's own words are nearer and say
    statement, read the old way the heading says tax, so the statement is
    left for a person, never pressed for the 1098 or filed as one."""
    page.set_content("<ul><li>Tax documents and statements, January 31, 2026<ul>"
                     "<li>Loan statement <a href='#' data-guid='g-statement'>View</a></li>"
                     "<li>Form 1098 <a href='#' data-guid='g-tax'>Download</a></li>"
                     "</ul></li></ul>" + LISTENER)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


def test_a_control_in_a_part_of_an_entry_is_of_that_entry(page, presses, tmp_path):
    """The entry's words sit beside View, in a part of their own, and
    Download sits apart from them. A part of an entry is inside it, so the
    two controls fetch one document."""
    page.set_content(_blocks("<div>01/31/2026 "
                             "<div>Loan statement <a href='#' data-guid='g-view'>View</a></div>"
                             "<div><a href='#' data-guid='g-download'>Download</a></div></div>"))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_date_printed_in_one_link_dates_no_other_control(page, presses, tmp_path):
    """The statement's link prints its date and the 1098's prints none. The
    old reading dated the 1098 by the statement's link, and with care that
    date is the statement's, so the 1098 is left for a person rather than
    filed under a date that may not be its own."""
    page.set_content(_page("<tr><td><a href='#' data-guid='g-statement'>Statement 01/31/2026 (PDF)</a></td>"
                           "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)


def test_a_row_printing_its_own_date_dates_each_document_in_it(page, presses, tmp_path):
    """The row prints its date in a cell of its own, beside a statement link
    that prints the date too. The link is part of the row, not a row of its
    own, so the row is no list and its date is the 1098's as well."""
    page.set_content(_page("<tr><td>01/31/2026</td>"
                           "<td><a href='#' data-guid='g-statement'>Statement 01/31/2026 (PDF)</a></td>"
                           "<td><a href='#' data-guid='g-tax'>Download 1098</a></td></tr>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT), (DAY, "tax", TAX)]
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


def test_a_control_whose_readings_part_before_the_press_is_not_pressed(page, presses, tmp_path, monkeypatch):
    """The page was read and the statement's two readings agreed. Then its
    row came to name a 1098 as well. Its name, date and row are as before,
    but read again its readings disagree, so it is not pressed."""
    page.set_content(_page(STATEMENT_ROW))
    real = site._survey

    def then_changed(pg):
        found = real(pg)
        pg.evaluate("() => { document.querySelector('[data-guid=r-statement] td:nth-child(2)')"
                    ".textContent = 'Loan statement and Form 1098'; }")
        return found
    monkeypatch.setattr(site, "_survey", then_changed)
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["the control was not the same when read again"], trace


# --- the shapes the third review found ----------------------------------------
#
# The third Wells Fargo version filed a control by its careful reading
# alone. Each of these it filed under a kind or a date the code before it
# would not have.

def test_a_plain_download_beside_view_1098_is_not_filed_as_a_statement(page, presses, tmp_path):
    """The form's name is in View's own words, so with care the plain
    Download beside it named no kind and was a statement, pressed and filed
    as one. Read the old way it is the 1098, so it is left alone."""
    page.set_content(_page("<tr><td>01/31/2026</td>"
                           "<td><a href='#' data-guid='g-view'>View 1098</a></td>"
                           "<td><a href='#' data-guid='g-download'>Download</a></td></tr>"))
    docs = site.collect_download_docs(page)
    assert [(d.title, d.rows) for d in docs] == [(TAX, 1)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-view"], (presses, trace)


def test_a_dated_statement_link_in_a_row_that_names_a_tax_is_a_statement(page):
    """A loan whose row names the tax year its interest counts toward, its
    statements linked by date. Both readings call the link a statement by
    its own words."""
    page.set_content(_page("<tr><td>Interest for tax year 2025</td>"
                           "<td><a href='#' data-guid='g-statement'>Statement 01/31/2026 (PDF)</a></td></tr>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]


def test_a_1098_beside_dated_statement_links_takes_none_of_their_dates(page):
    """One row holds two dated statement links and a 1098 link with a year
    only. The 1098 was filed under the first statement's date."""
    page.set_content(_page("<tr><td><a href='#' data-guid='g-january'>Statement 01/31/2025 (PDF)</a> "
                           "<a href='#' data-guid='g-february'>Statement 02/28/2025 (PDF)</a></td>"
                           "<td><a href='#' data-guid='g-tax'>2025 Form 1098 (PDF)</a></td></tr>"))
    docs = site.collect_download_docs(page)
    assert sorted((d.date_text, d.kind) for d in docs) == [("2025-01-31", "statement"),
                                                            ("2025-02-28", "statement")]
    assert docs.unsure == 1


def test_a_form_number_written_without_its_hyphen_is_a_tax_form(page):
    """1099C is a 1099 to the old reading, which finds the number anywhere,
    and so it is to the careful one."""
    page.set_content(_page("<tr><td>01/31/2026</td><td>Form 1099C</td>"
                           "<td><a href='#' data-guid='g-tax'>View</a></td></tr>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


def test_a_long_entry_is_still_dated(page):
    """An entry with a long description printed its date beyond the length
    the second Wells Fargo version allowed a row, and was not found. The
    code before either version read it."""
    page.set_content(_blocks("<div>01/31/2026 Loan statement. " + "This statement covers activity. " * 12
                             + "<a href='#' data-guid='g-statement'>View</a></div>"))
    assert _found(site.collect_download_docs(page)) == [(DAY, "statement", STATEMENT)]


# --- the shapes the review of this port found -----------------------------------
#
# Finding a second document of a day, the port filed each of these under a
# kind it is not, where the code before it found only the first.

# A loan's statement, its masked number printed in a cell of its own.
MASKED_ROW = ("<tr data-guid='r-masked'><td>01/31/2026</td><td>Loan statement</td><td>%s</td>"
              "<td><a href='#' data-guid='g-masked'>View</a></td></tr>")
# The same, its masked number in the link's own words.
MASKED_LINK_ROW = ("<tr data-guid='r-masked'><td>01/31/2026</td><td><a href='#' data-guid='g-masked'>"
                   "View statement, loan ending 1099</a></td></tr>")


@pytest.mark.parametrize("row", [MASKED_ROW % loan for loan in (
    "Loan ****1099", "Loan ... 1098", "Loan … 1099", "Loan •••• 1099",
    "Loan XXXX-1098", "Loan #1099", "EIDL ending in 1099", "Disaster Loan ending 1098",
    "Last four digits 1099", "Loan ●●●● 1099", "Loan ···· 1099",
    "Loan XXXX–1099", "Loan **** - 1099", "Loan ending - 1098", "Disaster Loan *1099",
    "Loan ****1099-EIDL")]
    + [MASKED_LINK_ROW],
    ids=["asterisks", "dots", "an ellipsis", "bullets", "x's", "a number sign", "ending in", "a loan ending",
         "last four", "black circles", "middle dots", "x's and an en dash", "asterisks and a dash",
         "ending and a dash", "one asterisk", "a program's name after the digits", "in the link's own words"])
def test_a_statement_of_a_loan_ending_1099_is_never_filed_as_a_tax_form(page, presses, tmp_path, row):
    """The loan's masked number ends in 1099 or 1098, and both readings took
    those digits for the form, so its statement was filed as a Tax
    Document, alone or beside another loan's statement of the day. Read
    with care they are the loan's, the two readings disagree, and it is
    left for a person. Three dots, an ellipsis, black circles, middle dots,
    a dash other than a hyphen after a mask and "last four digits" masked
    nothing as first ported, the last since only sixteen characters before
    the digits were read (fresh reviews of the Wells Fargo port). And a
    loan's program named after a dash, ****1099-EIDL, was taken for a
    form's letters (fresh review of this port)."""
    page.set_content(_page(row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    page.set_content(_page(STATEMENT_ROW, row))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["no control of this date is this kind of document"], trace


# A 1099-C's link, naming only its date, for a screen reader.
DATED_BY_NAME_LINK = "<a href='#' data-guid='g-1099c' aria-label='Download PDF January 31, 2026'>PDF</a>"


@pytest.mark.parametrize("form", [
    "<div>Form 1099-C %s</div>" % DATED_BY_NAME_LINK,
    "<div role='listitem'>Form 1099-C %s</div>" % DATED_BY_NAME_LINK,
    "<article>Form 1099-C %s</article>" % DATED_BY_NAME_LINK,
    "<div>Form 1099-C <span>%s</span></div>" % DATED_BY_NAME_LINK,
], ids=["a block", "a list item by role", "an article", "a link in a part of its own"])
def test_a_form_dated_only_by_its_name_takes_its_kind_from_its_own_part_of_the_page(page, presses,
                                                                                   tmp_path, form):
    """A 1099-C's link names only its date, for a screen reader, and the
    form's name is printed beside it. No table row or list item holds it,
    so nothing around it was read and it was filed as a statement, alone or
    after the day's 1098. The part of the page holding it and no other
    control is read now, it names a tax form where the old reading of the
    link's name says statement, and it is left for a person."""
    page.set_content(_blocks(form))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    page.set_content(_blocks("<div>Form 1098 01/31/2026 <a href='#' data-guid='g-1098'>Download 1098</a></div>",
                             form))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "tax", TAX)] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == ["no control of this date is this kind of document"], trace


def test_a_link_dated_only_by_its_name_reads_no_words_it_shares_with_other_documents(page):
    """Statement links naming only their dates, each in a part of its own,
    under tabs that name statements and tax forms. The words around a link
    are read only as far as the part that holds it alone, so the tabs, which
    every document of the list shares, leave neither unsure, and both are
    filed as the code before filed them."""
    page.set_content(_blocks("<div><div role='tablist'><button>Statements</button> <button>Tax forms</button></div>"
                             "<div><a href='#' data-guid='g-january' aria-label='Download PDF January 31, 2026'>"
                             "PDF</a></div>"
                             "<div><a href='#' data-guid='g-december' aria-label='Download PDF December 31, 2025'>"
                             "PDF</a></div></div>"))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [("2025-12-31", "statement", "Loan Statement - December 31, 2025"),
                            (DAY, "statement", STATEMENT)] and docs.unsure == 0


@pytest.mark.parametrize("control", [
    "<a href='#' data-guid='%s' aria-label='Statement January 31, 2026'>PDF</a>",
    "<a href='#' data-guid='%s' aria-label='Download PDF January 31, 2026'>PDF</a>",
    "<input type='button' data-guid='%s' value='PDF' aria-label='View statement January 31, 2026'>",
], ids=["found by their words", "found by their names", "input buttons"])
def test_two_statements_dated_only_by_their_names_stay_two_entries(page, presses, tmp_path, control):
    """Two loans' statements of one day, each a control that says PDF and
    names only its date for a screen reader, each in a part of the page of
    its own, under a heading. Named "Statement" and a date, no control's
    name says it fetches a document, so the core finds them by their words
    (#38), and neither is another document control to the other here, nor
    is a button drawn as an input. What is read around each for its kind
    then reaches the heading, and taken for their entry it made the two one
    document, and the first was pressed for both. Each entry is still the
    control alone, as before the part around it was read, so the two are
    refused rather than guessed at (fresh review of the Wells Fargo
    port)."""
    page.set_content(_blocks("<div><h3>Statements</h3><div>%s</div><div>%s</div></div>"
                             % (control % "g-disaster", control % "g-express")))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 2)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


# --- the shapes the fresh reviews of the Wells Fargo port found -----------------
#
# The two rules the review of this port brought went into the Wells Fargo
# app as well, and two fresh reviews there found these shapes, each one this
# app read the same way. The last digits of a masked number were taken for
# the loan's after a lone bullet or "ending", a link with nothing around it
# read the tabs and menus of the page, and each rule alone could file a
# control the reading before it had left for a person, or leave its twin
# unrefused. Each shape here is held to the answer the code before these
# rules gave.

BULLET, ELLIPSIS, EN_DASH = chr(0x2022), chr(0x2026), chr(0x2013)


@pytest.mark.parametrize("words", ["Loan ...4321 %s 1098" % BULLET,
                                   "Disaster Lo%s 1099-C" % ELLIPSIS,
                                   "Disaster loan %s 1099-C" % BULLET],
                         ids=["after a bullet", "after a cut nickname", "after a loan's name and a bullet"])
def test_a_form_named_after_a_bullet_or_an_ellipsis_is_never_filed_as_a_statement(page, presses, tmp_path,
                                                                                   words):
    """A form's name printed after a bullet or a nickname cut short, beside
    a link naming only its date. The bullet was taken for a mask, so the
    form was no form, the link read as a statement both ways and the 1098
    was saved as the day's statement, and beside the day's real statement
    the two were refused as twins. A lone bullet masks nothing, and a number
    with letters after it is a form's name."""
    form = "<tr data-guid='r-form'><td>%s</td><td>%s</td></tr>" % (
        words, "<a href='#' data-guid='g-form' aria-label='Download PDF January 31, 2026'>PDF</a>")
    page.set_content(_page(form))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
    page.set_content(_page(STATEMENT_ROW, form))
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [(STATEMENT, 1)]
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)


@pytest.mark.parametrize("content", [
    _blocks("<a href='#' data-guid='g-tax'>Jan 31, 2026 %s 1099-C (PDF)</a>" % BULLET),
    _page("<tr><td>Year ending 01/31/2026</td><td>1099-C</td><td><a href='#' data-guid='g-tax'>View</a></td></tr>"),
    _page("<tr><td>Year ending 01/31/2026</td><td>1098</td><td><a href='#' data-guid='g-tax'>View</a></td></tr>"),
] + [_page("<tr><td>01/31/2026</td><td>%s</td><td><a href='#' data-guid='g-tax'>View</a></td></tr>" % words)
     for words in ("Mortgage interest %s 1098" % BULLET, "Disaster Lo%s 1099-C" % ELLIPSIS,
                   "Disaster Lo%s 1098" % ELLIPSIS, "Economic Injury Disaster Lo%s 1099" % ELLIPSIS,
                   "Disaster Lo%s 1099%sC" % (ELLIPSIS, EN_DASH), "Mortgage Interest Information... 1098",
                   "Loan ... 1099-C", "Loan ... 1099%sC" % EN_DASH)],
    ids=["a link naming a 1099-C after a bullet", "a 1099-C after a year ending", "a 1098 after a year ending",
         "a 1098 after a bullet", "a 1099-C after a cut nickname", "a 1098 after a cut name",
         "a 1099 after a cut name", "a 1099-C with an en dash after a cut name",
         "a 1098 after three dots ending a word", "a 1099-C after dots", "a 1099-C with an en dash after dots"])
def test_a_form_named_after_a_bullet_a_period_or_an_ellipsis_is_still_a_tax_form(page, content):
    """Each was filed as a tax form before, and taken for a masked number's
    digits it was left for a person every run. A period's "ending" is no
    loan's, and the dates the careful reading leaves out had put it just
    before the form. Dots right after a letter cut a name short, and a
    form's name stays a form's name after dots."""
    page.set_content(content)
    assert _found(site.collect_download_docs(page)) == [(DAY, "tax", TAX)]


@pytest.mark.parametrize("content, title, kept", [
    (_blocks("<section><p>Tax forms are listed under Tax Documents.</p>"
             "<div><a href='#' data-guid='g-statement' aria-label='Download PDF January 31, 2026'>PDF</a></div>"
             "</section><section><div><input type='checkbox' aria-label='Select'> Form 1098 "
             "<a href='#' data-guid='g-1098' aria-label='Download PDF January 31, 2026'>PDF</a></div></section>"),
     STATEMENT, (STATEMENT, 2)),
    (_page("<tr><td>01/31/2026</td><td>Loan statement</td><td>Loan %s 1099</td>"
           "<td><a href='#' data-guid='g-statement'>View</a></td></tr>" % (BULLET * 4),
           "<tr><td>01/31/2026</td><td>Form 1098</td><td><a href='#' data-guid='g-1098'>View</a></td></tr>"),
     TAX, (TAX, 2)),
], ids=["a statement unsure for the words near it", "a statement unsure for its masked number"])
def test_a_document_the_two_rules_leave_unsure_still_stops_its_twin(page, presses, tmp_path, content, title,
                                                                   kept):
    """The rules leave a statement for a person, and a control of the same
    day that reads as its kind both ways, a 1098 whose own part holds a box
    to tick, or the day's 1098 beside a statement taken for a tax form
    before, was then alone of its date and kind and was pressed for it. The
    code before refused both as two rows, and so does this one, since a
    control only the rules leave unsure is still an entry of what it was."""
    page.set_content(content)
    assert [(d.title, d.rows) for d in site.collect_download_docs(page)] == [kept]
    saved, trace = _download(page, tmp_path, title)
    assert not saved and presses == [], (presses, trace)
    assert _refusals(trace) == [TWO_ROWS], trace


def test_a_document_the_two_rules_leave_unsure_stops_no_other_kind_or_day(page, presses, tmp_path):
    """A loan's statement the masked-digits rule leaves unsure is held as
    the tax form both readings took it for before, so it stops only a tax
    form of its own day. The day's statement and a 1098 of another day are
    each pressed, as the code before pressed them."""
    page.set_content(_page(MASKED_ROW % "Loan ****1099", STATEMENT_ROW,
                           "<tr><td>12/31/2025</td><td>Form 1098</td>"
                           "<td><a href='#' data-guid='g-older-tax'>Download 1098</a></td></tr>"))
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-statement"], (presses, trace)
    presses.clear()
    saved, trace = _download(page, tmp_path, "Tax Document - December 31, 2025", iso="2025-12-31")
    assert saved and presses == ["g-older-tax"], (presses, trace)


def test_a_control_unsure_of_its_date_is_no_entry_of_any_date(page, presses, tmp_path):
    """The 1098 beside a dated statement link takes the link's date read the
    old way and no date read with care, so it is left for a person, as it
    was before the two rules. Only a control the two rules alone leave
    unsure is held as an entry, so the day's 1098 in a row of its own is
    pressed, as the code before pressed it."""
    page.set_content(_page("<tr><td><a href='#' data-guid='g-statement'>Statement 01/31/2026 (PDF)</a></td>"
                           "<td><a href='#' data-guid='g-undated'>Download 1098</a></td></tr>", TAX_ROW))
    saved, trace = _download(page, tmp_path, TAX)
    assert saved and presses == ["g-tax"], (presses, trace)


@pytest.mark.parametrize("content", [
    "<ul><li>Loan ****1099 <a href='#' data-guid='g-x' aria-label='Download PDF January 31, 2026'>PDF</a>"
    "</li></ul>" + LISTENER,
    _blocks("<div>Form 1098 <a href='#' data-guid='g-x' aria-label='Download PDF Taxable interest January 31, 2026'>"
            "PDF</a></div>"),
], ids=["a masked number beside a link naming its date", "a form beside a link the old reading calls tax"])
def test_the_two_rules_never_file_what_the_reading_before_them_left_for_a_person(page, content):
    """The old reading reads only a name that holds its date. Read with care
    as before, the masked digits named a form, and the link said no kind,
    so both were left for a person. With either rule alone the careful
    reading came to agree with the old one, and the first was filed as a
    statement, the second as a tax form. The careful reading without the
    rules must agree too."""
    page.set_content(content)
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1


@pytest.mark.parametrize("chrome", [
    "<div role='tablist'><button>Statements</button> <button>Tax forms</button></div>",
    "<div><div role='tab'>Statements</div> <div role='tab'>Tax forms</div></div>",
    "<nav><a href='#'>Tax Center</a></nav>",
], ids=["tab buttons", "tabs by role", "a menu link"])
def test_a_lone_link_dated_only_by_its_name_reads_no_tabs_menus_or_links_around_it(page, presses, tmp_path,
                                                                                   chrome):
    """A statement alone on its page, its link naming only its date, under
    tabs or a menu that name tax forms. Read as far as six levels up, the
    tabs made it a tax form read with care, and it was left for a person
    every run. The part read around a link holds no other control."""
    page.set_content(_blocks("<div>%s<div><a href='#' data-guid='g-x' aria-label='Download PDF January 31, 2026'>"
                             "PDF</a></div></div>" % chrome))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [(DAY, "statement", STATEMENT)] and docs.unsure == 0
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert saved and presses == ["g-x"], (presses, trace)


# --- the shapes the fresh review of this port found ------------------------------
#
# Ported as the Wells Fargo app has them, the two rules saved these where the
# reading they replace left them for a person. Letters running into a masked
# number from the next word were taken for a form's name, and a control
# nobody sees cut short the part read around a link. Each is held to the
# answer of the reading before.

@pytest.mark.parametrize("control", [
    "<button data-guid='g-masked'><span>Loan ****1099</span><span>View statement</span></button>",
    "<a href='#' data-guid='g-masked'><span>EIDL ****1099</span><span>PDF</span></a>",
    "<a href='#' data-guid='g-masked'><span>Loan %s1099</span><span>Statement PDF</span></a>" % (BULLET * 4),
], ids=["a button", "a link that says PDF", "bullets"])
def test_a_masked_number_running_into_the_control_s_words_is_still_the_loan_s(page, presses, tmp_path,
                                                                              control):
    """The control prints the loan's masked number and its own words in two
    spans with nothing between them, as a page drawn in parts often does, so
    its words read "Loan ****1099View statement". Any letter after the digits
    was taken for a form's name, so they were the form's, and the statement
    was saved as the day's Tax Document. Only a form's letters name a form,
    so the statement is left for a person, as the reading before left it."""
    page.set_content(_page("<tr><td>01/31/2026</td><td>%s</td></tr>" % control))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, TAX)
    assert not saved and presses == [], (presses, trace)


@pytest.mark.parametrize("part", [
    "<div><span>Form 1098</span> <form action='#'><input type='hidden' name='id' value='7'>%s</form></div>",
    "<div><a id='y2026'></a><span>Form 1098</span> <div>%s</div></div>",
    "<div><span>Form 1098</span> <button style='visibility:hidden'>Remove</button> <div>%s</div></div>",
], ids=["a hidden field of a form around it", "an empty anchor", "a control shown only on hover"])
def test_a_control_nobody_sees_does_not_cut_short_what_a_button_reads(page, presses, tmp_path, part):
    """A 1098's button names only its date, beside the form's name, inside a
    form whose hidden field carries the row's number, beside an empty
    anchor, or beside a control the page shows only on hover. Taken for
    another control, each cut short the part read around the button, so it
    read as a statement both ways and the 1098 was saved as the day's
    statement. None is drawn on the page, so the form's name is read and
    the 1098 is left for a person, as the reading before left it."""
    page.set_content(_blocks(part % ("<button data-guid='g-1098' aria-label='Download PDF January 31, 2026'>"
                                     "PDF</button>")))
    docs = site.collect_download_docs(page)
    assert _found(docs) == [] and docs.unsure == 1
    saved, trace = _download(page, tmp_path, STATEMENT)
    assert not saved and presses == [], (presses, trace)
