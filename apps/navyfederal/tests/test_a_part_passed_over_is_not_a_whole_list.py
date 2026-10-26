"""A statement list read without an account group or a year the page
offers is never noted whole.

The statements page lists each account as a group that opens to show its
rows, and the Previous Statements group shows one year at a time through a
year dropdown. A group that would not open on its own, with every other
one folded, was passed over, and so was a year whose choice raised, and the
list was noted as read whole. Resume then carried on from it and called
the run finished with a group or a year never read.

Now the walk names what it passed over, and Discover keeps what it read,
writes a failure file, leaves the listing as one that stopped, and Pilot,
Run All and Discover stop at their end rather than finish. A year that is
turned off is never chosen, and is no part of the list passed over. Driven
in a real browser against a made-up page in the shape the app expects.
Every account, year and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import navyfederal_docs as app_mod
import navyfederal_site as site
from paperpull_core import listing

CHECKING = "INVENTED CHECKING ACCOUNTS"
PREVIOUS = "PREVIOUS STATEMENTS"

PAGE = """<!doctype html><html><body>
<div class="product-kind-description-row" role="button" aria-expanded="false" data-k="a">%s</div>
<div id="rows-a"></div>
<div class="product-kind-description-row" role="button" aria-expanded="false" data-k="p">%s</div>
<div id="rows-p"></div>
<script>(() => {
const row = (date, k) => "<table><tbody><tr><td>" + date + "</td><td>Monthly Statement</td><td>" +
  "<button id='statement-link-" + k + "' aria-label='View Statement document'>View</button>" +
  "</td></tr></tbody></table>";
const groups = () => document.querySelectorAll('.product-kind-description-row');
function draw() {
  for (const h of groups()) {
    const k = h.dataset.k, open = h.getAttribute('aria-expanded') === 'true';
    const into = document.getElementById('rows-' + k);
    if (!open) { into.innerHTML = ''; continue; }
    if (k === 'a') { into.innerHTML = row('04/17/2031', 'a'); continue; }
    if (!into.querySelector('select')) {
      into.innerHTML = "<select id='yearSelection' aria-label='Year'><option>2031</option>" +
        "<option>2030</option>%s</select><div class='list'></div>";
      into.querySelector('select').onchange = draw;
    }
    into.querySelector('.list').innerHTML = row('03/17/' + into.querySelector('select').value, 'p');
  }
}
for (const h of groups()) {
  h.addEventListener('click', () => {
    h.setAttribute('aria-expanded', h.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
    draw();
  });
}
draw();
})();</script></body></html>"""


def draw(page, more=""):
    page.set_content(PAGE % (CHECKING, PREVIOUS, more))


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
    draw(pg)
    yield pg
    browser.close()
    driver.stop()


def group_will_not_open(monkeypatch, name, answer):
    """expand_only for the group `name` answers `answer`, False for a group
    no header names, None for one left open beside it."""
    real = site.expand_only
    monkeypatch.setattr(site, "expand_only",
                        lambda pg, needle: answer if needle == name else real(pg, needle))


def year_will_not_take(monkeypatch, year):
    from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeout
    real = Locator.select_option

    def select_option(self, *a, **kw):
        if kw.get("label") == year:
            raise PlaywrightTimeout("Timeout exceeded, a choice that would not take.")
        return real(self, *a, **kw)
    monkeypatch.setattr(Locator, "select_option", select_option)


def dated(got):
    return sorted((r["account"], r["date"]) for r in got)


ALL = [(CHECKING, "2031-04-17"), (PREVIOUS, "2030-03-17"), (PREVIOUS, "2031-03-17")]


# -- the walk names what it passed over -------------------------------------------

def test_a_whole_walk_passes_over_nothing(page):
    got = site.nfcu_collect(page)
    assert dated(got) == ALL
    assert got.passed_over == ()


@pytest.mark.parametrize("answer", [False, None], ids=["not named", "another left open"])
def test_a_group_that_would_not_open_is_passed_over(page, monkeypatch, answer):
    group_will_not_open(monkeypatch, CHECKING, answer)
    got = site.nfcu_collect(page)
    assert CHECKING not in {a for a, _d in dated(got)}
    assert got.passed_over == ("account group",)


def test_a_year_whose_choice_would_not_take_is_passed_over(page, monkeypatch):
    year_will_not_take(monkeypatch, "2030")
    got = site.nfcu_collect(page)
    assert dated(got) == [(CHECKING, "2031-04-17"), (PREVIOUS, "2031-03-17")]
    assert got.passed_over == ("year picker",)


def test_a_header_on_two_lines_is_its_group(page):
    """group_names gives a header's words on one line, and its group was
    looked for by them in the header as it reads, line break and all, so it
    was never opened, and now that would be passed over every run
    (review)."""
    page.set_content(PAGE % ("INVENTED CHECKING<br>ACCOUNTS", PREVIOUS, ""))
    got = site.nfcu_collect(page)
    assert dated(got) == ALL
    assert got.passed_over == ()


def test_a_turned_off_year_is_never_chosen_or_passed_over(page, monkeypatch):
    """Choosing it waited out its time and was taken for a year that would
    not take."""
    draw(page, "<option disabled>2029</option>")
    from playwright.sync_api import Locator
    chosen = []
    real = Locator.select_option

    def select_option(self, *a, **kw):
        chosen.append(kw.get("label"))
        return real(self, *a, **kw)
    monkeypatch.setattr(Locator, "select_option", select_option)
    got = site.nfcu_collect(page)
    assert chosen == ["2031", "2030"]
    assert got.passed_over == ()


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch, page):
    pressed = []

    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_on_its_site", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, *_a, **_kw: pressed.append((doc.account, doc.date)))
        return app

    monkeypatch.setattr(site, "ensure_statements", lambda pg: True)
    build.pressed = pressed
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(make_app):
    app = make_app("--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == ALL
    assert listing.last(app) == listing.COMPLETE


@pytest.mark.parametrize("passed", ["group", "year"])
def test_a_list_passed_over_in_part_is_not_noted_whole(make_app, monkeypatch, tmp_path, capsys,
                                                       passed):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    if passed == "group":
        group_will_not_open(monkeypatch, CHECKING, None)
        taken = [r for r in ALL if r[0] != CHECKING]
    else:
        year_will_not_take(monkeypatch, "2030")
        taken = [r for r in ALL if r[1][:4] == "2031"]
    app = make_app("--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert sorted(make_app.pressed) == taken
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Navy Federal's statement list was not read whole" in out
    assert "Not all of Navy Federal's statement list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the statement list",
                                                  "some of the list could not be chosen")

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(make_app, monkeypatch):
    year_will_not_take(monkeypatch, "2030")
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert len(make_app().discovery.data) == 2


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(make_app, monkeypatch):
    year_will_not_take(monkeypatch, "2030")
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert sorted(make_app.pressed) == [(CHECKING, "2031-04-17"), (PREVIOUS, "2031-03-17")]
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        make_app, monkeypatch, capsys):
    """No group would open, so nothing was read and there is nothing to
    pilot."""
    monkeypatch.setattr(site, "expand_only", lambda pg, needle: None)
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Navy Federal's statement list was read, so this run stops here" in out
    assert make_app.pressed == []
