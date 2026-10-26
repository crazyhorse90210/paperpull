"""A tax document list read without a tax year its dropdown offers is never
noted whole.

The Documents page shows one tax year's forms at a time, through a
dropdown whose options read "Tax Year: 2031". A year the dropdown offered
and would not take was passed over and the list noted as read whole, so
Resume carried on from it and called the run finished with a year never
read.

Now Discover keeps what it read, writes a failure file, leaves the listing
as one that stopped, and Pilot, Run All and Discover stop at their end
rather than finish. A tax year read from the page's text, with no dropdown
to choose it in, is left as it was, since it may be any year the page
prints, and so is a year that is turned off, which is never chosen. Driven
in a real browser against a made-up page. Every account, year and form is
invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wealthfront_docs as app_mod
import wealthfront_site as site
from paperpull_core import listing

ACCOUNT = "Invented Cash Account"

PAGE = """<!doctype html><html><body>
<label>Tax year <select aria-label="tax year">
  <option>Tax Year: 2031</option><option>Tax Year: 2030</option>%s
</select></label>
<table><tbody id="rows"></tbody></table>
<script>(() => {
const sel = document.querySelector('select');
const draw = () => {
  document.getElementById('rows').innerHTML =
    '<tr class="doc"><td>%s</td><td>Form 1099 ' + sel.value.slice(-4) + '</td><td>Download</td></tr>';
};
sel.onchange = draw;
draw();
})();</script></body></html>"""

# The tax year written on the page, with no dropdown to choose it in.
TEXT_ONLY = """<!doctype html><html><body><h2>Tax Year: 2031</h2>
<p>Tax Year: 2030 forms are mailed.</p></body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    shortened = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: shortened(min(ms, 200))
    pg.set_content(PAGE % ("", ACCOUNT))
    yield pg
    browser.close()
    driver.stop()


# -- the years and where they came from -------------------------------------------

def test_the_dropdowns_own_years_are_said_to_be_its(page):
    years = site.get_tax_years(page)
    assert list(years) == ["2031", "2030"] and years.offered == {"2031", "2030"}


def test_a_turned_off_year_is_not_one_the_dropdown_offers(page):
    page.set_content(PAGE % ("<option disabled>Tax Year: 2029</option>", ACCOUNT))
    assert list(site.get_tax_years(page)) == ["2031", "2030"]


def test_years_read_from_the_pages_text_are_not_the_dropdowns(page):
    page.set_content(TEXT_ONLY)
    years = site.get_tax_years(page)
    assert list(years) == ["2031", "2030"] and years.offered == frozenset()


def test_a_year_worded_otherwise_than_it_is_chosen_by_is_not_offered(page):
    """select_tax_year chooses by the label "Tax Year: 2029" or "2029", so
    an option reading "TAX YEAR 2029" is read but never one it could
    choose, and a refusal of it says nothing about the page (review)."""
    page.set_content(PAGE % ("<option>TAX YEAR 2029</option>", ACCOUNT))
    years = site.get_tax_years(page)
    assert list(years) == ["2031", "2030", "2029"] and years.offered == {"2031", "2030"}


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch, page):
    pressed = []

    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Tax Document"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, _name: pressed.append(doc.date))
        return app

    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    build.pressed = pressed
    return build


def year_will_not_take(monkeypatch, year):
    real = site.select_tax_year
    monkeypatch.setattr(site, "select_tax_year",
                        lambda pg, y: False if y == year else real(pg, y))


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(make_app):
    app = make_app("--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == ["2030-12-31", "2031-12-31"]
    assert listing.last(app) == listing.COMPLETE


def test_a_tax_year_passed_over_is_not_noted_whole(make_app, monkeypatch, tmp_path, capsys):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    year_will_not_take(monkeypatch, "2030")
    app = make_app("--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert make_app.pressed == ["2031-12-31"]
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Wealthfront's document list was not read whole" in out
    assert "Not all of Wealthfront's document list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the document list",
                                                  "some of the list could not be chosen")

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_year_from_the_pages_text_that_would_not_take_is_left_as_it_was(
        make_app, monkeypatch, page):
    """No dropdown, so no year can be chosen, and the page's years may be
    any it prints."""
    page.set_content(TEXT_ONLY)
    app = make_app("--all")
    app.cmd_run("all")
    assert listing.last(app) == listing.COMPLETE


def test_a_year_worded_otherwise_that_would_not_take_is_left_as_it_was(make_app, monkeypatch,
                                                                       page):
    page.set_content(PAGE % ("<option>TAX YEAR 2029</option>", ACCOUNT))
    year_will_not_take(monkeypatch, "2029")
    app = make_app("--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == ["2030-12-31", "2031-12-31"]
    assert listing.last(app) == listing.COMPLETE


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(make_app, monkeypatch):
    year_will_not_take(monkeypatch, "2030")
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert len(make_app().discovery.data) == 1


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(make_app, monkeypatch):
    year_will_not_take(monkeypatch, "2030")
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert make_app.pressed == ["2031-12-31"]
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        make_app, monkeypatch, capsys):
    """Neither year would take, so nothing was read and there is nothing to
    pilot."""
    monkeypatch.setattr(site, "select_tax_year", lambda pg, y: False)
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Wealthfront's document list was read, so this run stops here" in out
    assert make_app.pressed == []
