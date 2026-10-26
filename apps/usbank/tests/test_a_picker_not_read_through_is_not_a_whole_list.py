"""A statement list read without an account or a year its pickers offer is
never noted whole (#106 review).

The list is read account by account and year by year through the page's
own pickers. An account whose choice did not take was passed over, and so
was a year the picker would not take, a year the picker still showed the
one before for, and a picker that would not answer, would not list its
accounts or years, or listed none, of which only what was on show was read.
Each of those went on to note the list as read whole, so Resume carried on
from it and called the run finished with an account or a year never read.
Now the walk names each picker it could not read through, and Discover
keeps what it read, writes a failure file naming the picker, leaves the
listing as one that stopped, and Pilot and Run All stop at their end
rather than finish. A list that would not be counted, links whose words
would not come and rows the page's text reading could not read stop the
list, as rows that would not answer always did. Driven against a made-up
page in a real browser. Everything here is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_docs
import usbank_site as site
from paperpull_core import listing
from paperpull_core.testkit import stall_reads
from usbank_pages import BUSINESS, CARD, CHECKING, STATEMENTS, show

# Every statement the page lists, as a press is asked for it.
LISTED = sorted((acct, site.parse_date(d), "Statement") for acct, years in STATEMENTS.items()
                for dates in years.values() for d in dates)


@pytest.fixture(autouse=True)
def short_redraw(monkeypatch):
    """A list that has not come in a second and a half has not come."""
    monkeypatch.setattr(site, "REDRAW_MS", 1500)


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    pressed = []

    def press(_page, _ctx, account, date, *_a, title="", **_kw):
        pressed.append((account, date, title))
        return False

    def build(pg, *argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = usbank_docs.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = usbank_docs.App(args)
        app._work_page = pg
        monkeypatch.setattr(app, "page", lambda: pg)
        monkeypatch.setattr(app, "_on_its_site", lambda: pg)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        return app

    monkeypatch.setattr(site, "usbank_download", press)
    build.pressed = pressed
    return build


def _failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def _guids(page):
    """Name the pickers, so a read of one can be stalled (stall_reads)."""
    page.evaluate("""() => {
      document.getElementById('account-select').setAttribute('data-guid', 'account-select');
      document.getElementById('exp_button_year-filter-select').setAttribute('data-guid', 'year');
    }""")


def _card_not_chosen(monkeypatch):
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))


def _no_year_listed(page):
    page.evaluate("() => { document.getElementById('years').innerHTML = ''; }")


# -- the walk names what it could not read through -------------------------------

def test_a_whole_walk_passes_over_nothing(page):
    show(page)
    got = site.usbank_collect_structured(page)
    assert sorted((r["account"], r["date"], r["title"]) for r in got) == LISTED
    assert got.passed_over == ()


def test_an_account_that_could_not_be_chosen_is_passed_over(page, monkeypatch):
    show(page)
    _card_not_chosen(monkeypatch)
    got = site.usbank_collect_structured(page)
    assert CARD not in {r["account"] for r in got}
    assert got.passed_over == ("account picker",)


def test_a_year_the_picker_still_shows_another_for_is_passed_over(page):
    """The 2030 choice does not take, and the picker still shows 2031."""
    show(page, stuck=("2030",))
    got = site.usbank_collect_structured(page)
    assert got.passed_over == ("year picker",)
    assert {r["date"][:4] for r in got} == {"2031"}


def test_a_year_that_could_not_be_chosen_is_passed_over(page, monkeypatch):
    show(page, accounts=(CHECKING,), chosen=CHECKING)
    real = site.select_period
    monkeypatch.setattr(site, "select_period",
                        lambda pg, year: False if year == "2030" else real(pg, year))
    got = site.usbank_collect_structured(page)
    assert got.passed_over == ("year picker",)


def test_a_year_picker_that_lists_no_year_is_passed_over(page):
    """The picker opened and drew no year. That read as a page with only
    the year on show, and the list was noted whole."""
    show(page, accounts=(CHECKING,), chosen=CHECKING)
    _no_year_listed(page)
    offered = site.period_options(page)
    assert list(offered) == [] and offered.not_read == "the year picker listed no year"
    got = site.usbank_collect_structured(page)
    assert got.passed_over == ("year picker",)
    assert {r["date"][:4] for r in got} == {"2031"}


def test_years_drawn_after_the_first_look_are_read(page):
    """The picker draws its years only after the first look, and they are
    looked for once more before the picker is taken to list none. The
    account picker's own options show at the first look, and are no years."""
    show(page, accounts=(CHECKING,), chosen=CHECKING)
    _no_year_listed(page)
    shortened = page.wait_for_timeout

    def wait(ms):
        if ms == site.OPTIONS_WAIT_MS[1]:
            page.evaluate("""() => { document.getElementById('years').innerHTML =
              "<li role='option'>2031</li><li role='option'>2030</li>"; }""")
        return shortened(ms)
    page.wait_for_timeout = wait
    offered = site.period_options(page)
    assert list(offered) == ["2031", "2030"] and offered.not_read == ""


@pytest.mark.parametrize("method", ["inner_text", "evaluate"])
def test_a_year_picker_that_would_not_answer_is_never_none(page, monkeypatch, method):
    """The year picker's words or identity would not come. The guard reads
    a picker with no words or no identity as one it refuses, and the walk
    read only the year on show."""
    show(page, accounts=(CHECKING,), chosen=CHECKING)
    _guids(page)
    stall_reads(monkeypatch, {"year"}, locator=(method,),
                scripts=(site._IDENTITY_JS,) if method == "evaluate" else ())
    offered = site.period_options(page)
    assert list(offered) == [] and offered.not_read == "the year picker would not answer"
    assert "year picker" in site.usbank_collect_structured(page).passed_over


def test_an_account_picker_whose_options_would_not_answer_is_passed_over(page, monkeypatch):
    show(page)
    _guids(page)
    stall_reads(monkeypatch, {"account-select"}, locator=("evaluate",), scripts=(site._OPTIONS_JS,))
    offered = site.account_options(page)
    assert list(offered) == [] and offered.not_read
    assert "account picker" in site.usbank_collect_structured(page).passed_over


def test_a_picker_the_guard_refuses_is_not_passed_over(page):
    """A picker the guard refuses is never read whatever it says, so it is
    left as it was rather than stop every run."""
    show(page, accounts=(CHECKING,), chosen=CHECKING)
    page.evaluate("""() => document.getElementById('exp_button_year-filter-select')
                     .setAttribute('aria-label', 'Transfer from account')""")
    offered = site.period_options(page)
    assert list(offered) == [] and offered.not_read == ""


@pytest.mark.parametrize("shown, another", [
    ("2031", True), ("2030", False), ("", False), ("2031 2030", False),
], ids=["another year", "the one chosen", "no year", "two years"])
def test_only_a_picker_showing_one_other_year_went_back(page, monkeypatch, shown, another):
    monkeypatch.setattr(site, "_year_on_show", lambda pg: shown)
    assert site._shows_another_year(page, "2030") is another


def test_a_year_shown_late_is_looked_at_again(page, monkeypatch):
    looks = iter(["2031", "2031", "2030"])
    monkeypatch.setattr(site, "_year_on_show", lambda pg: next(looks))
    assert site._shows_another_year(page, "2030") is False


# -- Discover --------------------------------------------------------------------

def test_a_list_read_whole_is_noted_whole(page, make_app, tmp_path):
    show(page)
    app = make_app(page, "--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == LISTED
    assert listing.last(app) == listing.COMPLETE


@pytest.mark.parametrize("passed", ["account", "year"])
def test_a_list_passed_over_in_part_is_not_noted_whole(page, make_app, tmp_path, monkeypatch,
                                                       capsys, passed):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file naming the picker. The listing is left as
    one that stopped, so Resume carries on from it and stops too."""
    if passed == "account":
        show(page)
        _card_not_chosen(monkeypatch)
        read = [r for r in LISTED if r[0] != CARD]
    else:
        show(page, stuck=("2030",))
        read = [r for r in LISTED if r[1][:4] == "2031"]
    app = make_app(page, "--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert sorted(make_app.pressed) == read
    assert listing.last(app) == listing.STOPPED
    out = " ".join(capsys.readouterr().out.split())
    assert "U.S. Bank's statement list was not read whole, since its %s picker" % passed in out
    assert "Not all of U.S. Bank's statement list was read, so this run stops here" in out
    report = _failure(tmp_path)
    assert report["step"] == "read the statement list"
    assert report["reason"] == "a picker could not be read through"
    assert report["extra"]["listing"]["passed_over"] == ["%s picker" % passed]

    with pytest.raises(SystemExit):
        make_app(page, "--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(
        page, make_app, monkeypatch):
    show(page)
    _card_not_chosen(monkeypatch)
    app = make_app(page, "--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert {r["account"] for r in make_app(page).discovery.data.values()} == {CHECKING, BUSINESS}


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(page, make_app, monkeypatch):
    show(page)
    _card_not_chosen(monkeypatch)
    app = make_app(page, "--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert make_app.pressed and CARD not in {a for a, _d, _t in make_app.pressed}
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        page, make_app, monkeypatch, capsys):
    """Every statement the list read is before the run's start, so there is
    nothing to pilot, and the card was never read."""
    show(page)
    _card_not_chosen(monkeypatch)
    app = make_app(page, "--pilot", "--start-date", "2032-01-01")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = " ".join(capsys.readouterr().out.split())
    assert "No documents in scope to pilot" in out
    assert "Not all of U.S. Bank's statement list was read, so this run stops here" in out
    assert make_app.pressed == []
    assert listing.last(app) == listing.STOPPED


# -- a list that would not be read -----------------------------------------------

def test_a_list_that_would_not_be_counted_stops_the_list(page, monkeypatch):
    """It was read as a list with nothing in it, and the year as empty."""
    from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeout
    show(page)
    real = Locator.count
    wanted = "%s %s" % (site.SEL["list"], site.SEL["section"])

    def count(self):
        if wanted in str(self):
            raise PlaywrightTimeout("Timeout exceeded, a stalled read.")
        return real(self)
    monkeypatch.setattr(Locator, "count", count)
    with pytest.raises(site.RowUnread):
        site.read_rows(page, CHECKING)


NAMED_LINKS = ("<!doctype html><meta charset='utf-8'><main>"
               "<a href='#' data-guid='link-0' aria-label='Download March 15, 2031 statement'>"
               "Download</a>"
               "<a href='#' data-guid='link-1' aria-label='Download February 15, 2031 statement'>"
               "Download</a></main>")


def test_a_page_read_by_names_reads_every_link(page):
    page.set_content(NAMED_LINKS)
    assert sorted(r["date"] for r in site.read_rows(page, CARD)) == ["2031-02-15", "2031-03-15"]


@pytest.mark.parametrize("method", ["get_attribute", "count"])
def test_links_that_would_not_answer_stop_a_page_read_by_names(page, monkeypatch, method):
    """On a page read by its links' names, the first link would not give
    its words, or the links would not be counted. It was passed over, and
    the names read whole without it."""
    page.set_content(NAMED_LINKS)
    stall_reads(monkeypatch, {"link-0"}, locator=(method,))
    with pytest.raises(site.RowUnread):
        site.read_rows(page, CARD)


def test_a_page_that_did_not_open_again_is_no_list_read(page, monkeypatch):
    monkeypatch.setattr(site, "ensure_statements", lambda pg: False)
    with pytest.raises(site.RowUnread):
        site.usbank_collect_structured(page)


# -- the page's text reading -----------------------------------------------------

DROPDOWNS = ("<!doctype html><meta charset='utf-8'><main>"
             "<select id='acct'><option>Visa Platinum ...2222</option>"
             "<option>Business Card ...3333</option></select>"
             "<select id='yr'><option>2031</option><option>2030</option></select>"
             "<ul><li>October 9, 2031 <button aria-label='Download October 9, 2031 statement'>"
             "Download</button></li></ul></main>")


def test_the_text_reading_passes_over_nothing_on_a_page_it_reads(page):
    page.set_content(DROPDOWNS)
    got = site.usbank_collect(page)
    assert {d["account"] for d in got} == {CARD, BUSINESS}
    assert got.passed_over == ()


@pytest.mark.parametrize("label, part", [("Business Card ...3333", "account picker"),
                                         ("2030", "year picker")])
def test_the_text_reading_names_a_choice_that_did_not_take(page, monkeypatch, label, part):
    """Choosing the option failed. It was passed over, and the page's text
    read whole without it."""
    page.set_content(DROPDOWNS)
    real = site._select_option
    monkeypatch.setattr(site, "_select_option",
                        lambda pg, sel, lab: False if lab == label else real(pg, sel, lab))
    assert part in site.usbank_collect(page).passed_over


def test_the_text_reading_never_chooses_a_turned_off_or_refused_option(page, monkeypatch):
    """A turned off option and one the guard refuses are no accounts to
    choose, and neither is counted as one that did not take."""
    page.set_content(DROPDOWNS.replace(
        "<option>Visa Platinum ...2222</option>",
        "<option disabled>Closed card ...4444</option><option>Visa Platinum ...2222</option>"
        "<option>Transfer to account ...5555</option>"))
    chosen = []
    real = site._select_option
    monkeypatch.setattr(site, "_select_option",
                        lambda pg, sel, lab: chosen.append(lab) or real(pg, sel, lab))
    got = site.usbank_collect(page)
    assert {d["account"] for d in got} == {CARD, BUSINESS}
    assert got.passed_over == ()
    assert not any("4444" in c or "5555" in c for c in chosen)


def test_rows_the_text_reading_could_not_read_stop_the_list(page, monkeypatch):
    """The page's rows would not be read, which read as a page without
    rows, and the list was noted whole."""
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
    page.set_content(DROPDOWNS)
    real = Page.evaluate

    def evaluate(self, expression, *args, **kwargs):
        if expression == site._ROW_JS:
            raise PlaywrightTimeout("Timeout exceeded, a stalled read.")
        return real(self, expression, *args, **kwargs)
    monkeypatch.setattr(Page, "evaluate", evaluate)
    with pytest.raises(site.RowUnread):
        site.usbank_collect(page)
    # Elsewhere such a read is still a page with nothing on it, as it was.
    assert site.collect_documents(page) == []
