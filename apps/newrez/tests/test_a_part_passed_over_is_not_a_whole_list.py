"""A document list read without a statements page, or a year its picker
offers, is never noted whole.

Discovery opens the monthly statements page and then the yearly one by
their addresses, and walks the monthly page's year picker. A page whose
address would not open was passed over, and so was a year the picker
offered whose choice would not take, and the list was noted as read whole,
so Resume carried on from it and called the run finished with a page or a
year never read.

Now Discover keeps what it read, writes a failure file, leaves the listing
as one that stopped, and Pilot, Run All and Discover stop at their end
rather than finish. A year whose list never showed is left as it was,
since a year with no statement never shows one, as the tester's own walk
of #38 ended. Driven in a real browser whose every address is answered
here. Every loan, year and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import newrez_docs as app_mod
import newrez_site as site
from paperpull_core import listing
from test_year_picker_in_a_browser import (
    LISTS, MONTHLY, YEARLY, _iso, _statements_page, _yearly_page)

THREE = {y: LISTS[y] for y in ("2026", "2025", "2024")}


@pytest.fixture()
def pages(monkeypatch):
    """A browser whose statements pages are answered here, and every other
    address with nothing, as in test_year_picker_in_a_browser. A year with
    no statement is given up on after four seconds."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "scroll_full_page", lambda page, *a, **k: None)
    monkeypatch.setattr(site, "YEAR_WAIT_S", 4, raising=False)
    ctx = browser.new_context()
    state = {"monthly": "<h1>empty</h1>", "yearly": "<h1>empty</h1>"}

    def serve(route):
        url = route.request.url
        if url.startswith(MONTHLY):
            route.fulfill(status=200, content_type="text/html", body=state["monthly"])
        elif url.startswith(YEARLY):
            route.fulfill(status=200, content_type="text/html", body=state["yearly"])
        else:
            route.fulfill(status=404, body="")

    ctx.route("**/*", serve)
    pg = ctx.new_page()
    yield pg, state
    browser.close()
    driver.stop()


def show(pages, monthly=None, yearly=("2025",)):
    page, state = pages
    state["monthly"] = _statements_page(THREE if monthly is None else monthly)
    state["yearly"] = _yearly_page(*yearly)
    page.goto(MONTHLY)
    return page


def year_will_not_take(monkeypatch, year):
    """The picker's choice of `year` waits out its time, however the picker
    is held."""
    from playwright.sync_api import ElementHandle, Locator, TimeoutError as PlaywrightTimeout

    for kind in (ElementHandle, Locator):
        def select_option(self, *a, _real=kind.select_option, **kw):
            if kw.get("label") == year:
                raise PlaywrightTimeout("Timeout exceeded, a choice that would not take.")
            return _real(self, *a, **kw)
        monkeypatch.setattr(kind, "select_option", select_option)


def yearly_will_not_open(page):
    """The yearly page's address answers nothing at all, so the goto
    raises."""
    page.context.route(YEARLY + "*", lambda route: route.abort())


def years_read(got):
    return sorted({d.date_text[:4] for d in got if d.kind == "statement"})


# -- the walk names what it passed over -------------------------------------------

def test_a_whole_walk_passes_over_nothing(pages):
    page = show(pages)
    got = site.collect_download_docs(page)
    assert years_read(got) == ["2024", "2025", "2026"]
    assert [d.date_text for d in got if d.kind == "tax"] == ["2025-12-31"]
    assert got.passed_over == ()


def test_a_year_the_picker_offered_that_would_not_take_is_passed_over(pages, monkeypatch):
    page = show(pages)
    year_will_not_take(monkeypatch, "2025")
    got = site.collect_download_docs(page)
    assert years_read(got) == ["2024", "2026"]
    assert got.passed_over == ("year picker",)


def test_a_year_whose_list_never_showed_is_left_as_it_was(pages):
    """A year with no statement never shows a list, which the tester's own
    page did for its oldest year."""
    page = show(pages, monthly=dict(THREE, **{"2023": []}))
    got = site.collect_download_docs(page)
    assert years_read(got) == ["2024", "2025", "2026"]
    assert got.passed_over == ()


def test_a_statements_page_that_would_not_open_is_passed_over(pages):
    page = show(pages)
    yearly_will_not_open(page)
    got = site.collect_download_docs(page)
    assert [d for d in got if d.kind == "tax"] == []
    assert got.passed_over == ("statements page",)


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch, pages):
    page, _state = pages
    pressed = []

    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement", "Tax Document"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_on_its_site", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, _name: pressed.append((doc.category, doc.date)))
        return app

    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    build.pressed = pressed
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(pages, make_app):
    show(pages)
    app = make_app("--all")
    app.cmd_run("all")
    assert {d[:4] for c, d in make_app.pressed if c == "Statement"} == {"2024", "2025", "2026"}
    assert ("Tax Document", "2025-12-31") in make_app.pressed
    assert listing.last(app) == listing.COMPLETE


@pytest.mark.parametrize("passed", ["year", "page"])
def test_a_list_passed_over_in_part_is_not_noted_whole(pages, make_app, monkeypatch, tmp_path,
                                                       capsys, passed):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    page = show(pages)
    if passed == "year":
        year_will_not_take(monkeypatch, "2025")
        missing = {("Statement", _iso(m)) for m in LISTS["2025"]}
    else:
        yearly_will_not_open(page)
        missing = {("Tax Document", "2025-12-31")}
    app = make_app("--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert make_app.pressed and not missing & set(make_app.pressed), make_app.pressed
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Newrez's document list was not read whole" in out
    assert "Not all of Newrez's document list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the document list",
                                                  "some of the list could not be read")

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(pages, make_app,
                                                                           monkeypatch):
    show(pages)
    year_will_not_take(monkeypatch, "2025")
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert make_app().discovery.data


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(pages, make_app, monkeypatch):
    show(pages)
    year_will_not_take(monkeypatch, "2025")
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert make_app.pressed
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        pages, make_app, monkeypatch, capsys):
    """Nothing in scope to pilot, the run's start being after every
    statement, and a year was never read."""
    show(pages)
    year_will_not_take(monkeypatch, "2025")
    app = make_app("--pilot", "--start-date", "2032-01-01")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Newrez's document list was read, so this run stops here" in out
    assert make_app.pressed == []
