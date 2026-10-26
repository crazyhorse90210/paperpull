"""A statement list read without a year or a card its pickers offer is never
noted whole.

The list is read year by year through the "View:" picker, and card by card
through each card's accordion. A year the picker offered and would not
take was passed over, and so was a card whose accordion would not open, and
the page's text reading, read when that walk finds nothing, passed over an
account or a year its dropdowns offered and would not take. Each went on to
note the list as read whole, so Resume carried on from it and called the
run finished with a year or a card never read.

Now the walk names what it passed over, and Discover keeps what it read,
writes a failure file, leaves the listing as one that stopped, and Pilot,
Run All and Discover stop at their end rather than finish. A year the
opened picker does not list is not one it offered, since the years are
read from the page with the picker open, and is left as it was. So is an
option that is turned off or that the guard refuses, which is never
chosen. The pickers are stood in for, except where the choice itself is
under test, which is driven in a real browser against a made-up page.
Every card, year and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import chase_docs as app_mod
import chase_site as site
from paperpull_core import listing

CARDS = ("EXAMPLE CARD (...0001)", "OTHER CARD (...0002)")
YEARS = ("2031", "2030")


def rows_of(label, year):
    return [{"documentId": "", "date": "%s-0%d-15" % (year, m), "title": "Statement",
             "account": label, "kind": "statement", "occurrence": 0, "ambiguous": False}
            for m in (3, 4)]


@pytest.fixture
def pickers(monkeypatch):
    """The page's pickers, stood in for. `refuse` names the years the year
    picker will not take, `unlisted` the years the opened picker does not
    list, `closed` the cards whose accordion will not open, and `undrawn`
    the cards with no accordion on the page."""
    state = {"year": None, "refuse": set(), "unlisted": set(), "closed": set(),
             "undrawn": set()}

    def select_year(_page, year, why=None):
        if year in state["unlisted"]:
            if why is not None:
                why["why"] = "not offered"
            return False
        if year in state["refuse"]:
            return False
        state["year"] = year
        return True

    def expand_only_card(_page, label, why=None):
        if label in state["closed"] and why is not None:
            why["why"] = "would not open"
        return label not in state["closed"] | state["undrawn"]

    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "year_options", lambda page: list(YEARS))
    monkeypatch.setattr(site, "card_accordions", lambda page: [(None, c) for c in CARDS])
    monkeypatch.setattr(site, "select_year", select_year)
    monkeypatch.setattr(site, "collapse_all_cards", lambda page: None)
    monkeypatch.setattr(site, "expand_only_card", expand_only_card)
    real_read = site.read_card_rows

    def read_rows(page, label):
        # A card that would not open goes through the real read_card_rows,
        # whose accordion is the one stood in for above, and an open card
        # shows the rows of the year chosen.
        if label in state["closed"] | state["undrawn"]:
            return real_read(page, label)
        return rows_of(label, state["year"])
    monkeypatch.setattr(site, "read_card_rows", read_rows)
    return state


def read(got):
    return sorted((r["account"], r["date"]) for r in got)


ALL = sorted((c, r["date"]) for c in CARDS for y in YEARS for r in rows_of(c, y))


# -- the walk names what it passed over -------------------------------------------

def test_a_whole_walk_passes_over_nothing(pickers):
    got = site.chase_collect_via_api(page=None)
    assert read(got) == ALL
    assert got.passed_over == ()


def test_a_year_the_picker_would_not_take_is_passed_over(pickers):
    pickers["refuse"].add("2030")
    got = site.chase_collect_via_api(page=None)
    assert {d[:4] for _a, d in read(got)} == {"2031"}
    assert got.passed_over == ("year picker",)


def test_a_year_the_opened_picker_does_not_list_is_not_passed_over(pickers):
    """The years are read from everything on the page while the picker is
    open, so one the picker itself does not list may be a year printed
    beside it, which no run could ever choose. It is left as it was."""
    pickers["unlisted"].add("2030")
    got = site.chase_collect_via_api(page=None)
    assert {d[:4] for _a, d in read(got)} == {"2031"}
    assert got.passed_over == ()


def test_a_card_that_would_not_open_is_passed_over(pickers):
    pickers["closed"].add(CARDS[1])
    got = site.chase_collect_via_api(page=None)
    assert {a for a, _d in read(got)} == {CARDS[0]}
    assert got.passed_over == ("card",)


def test_a_card_a_view_does_not_draw_is_not_passed_over(pickers):
    """The cards are read once, on the view the page opens on, and looked
    for again on every year's. A year before a card existed may not draw
    it, which is no card that would not open (review)."""
    pickers["undrawn"].add(CARDS[1])
    got = site.chase_collect_via_api(page=None)
    assert {a for a, _d in read(got)} == {CARDS[0]}
    assert got.passed_over == ()


# -- a card's accordion, in a browser ---------------------------------------------

CARD_PAGE = """<!doctype html><html><body>
<button type="button" aria-expanded="false">EXAMPLE CARD (...0001)</button>
</body></html>"""


def test_a_card_whose_accordion_will_not_take_a_press_would_not_open(page):
    page.set_content(CARD_PAGE)
    page.evaluate("() => { document.querySelector('button').style.pointerEvents = 'none'; }")
    page.set_default_timeout(1500)
    why = {}
    assert site.expand_only_card(page, CARDS[0], why) is False
    assert why == {"why": "would not open"}
    assert site.read_card_rows(page, CARDS[0]).passed_over == ("card",)


def test_a_card_the_page_does_not_draw_is_not_one_that_would_not_open(page):
    page.set_content(CARD_PAGE)
    why = {}
    assert site.expand_only_card(page, CARDS[1], why) is False
    assert why == {}
    assert getattr(site.read_card_rows(page, CARDS[1]), "passed_over", ()) == ()


def test_a_card_on_the_page_opens(page):
    page.set_content(CARD_PAGE)
    why = {}
    assert site.expand_only_card(page, CARDS[0], why) is True and why == {}


# -- the choice of a year, in a browser -------------------------------------------

YEAR_PICKER = """<!doctype html><html><body>
<p><input id="filterstyledselect-year" aria-label="View:" value="2031" readonly></p>
<ul id="years" role="listbox" hidden>
  <li role="option" aria-label="2031, current selection">2031</li><li role="option">2030</li>
</ul>
<span>2029</span>
<script>(() => {
const picker = document.getElementById('filterstyledselect-year');
const years = document.getElementById('years');
picker.addEventListener('click', () => { years.hidden = false; });
for (const o of years.querySelectorAll('[role=option]')) {
  o.addEventListener('click', () => {
    picker.value = o.innerText.slice(0, 4); years.hidden = true; });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') years.hidden = true; });
})();</script></body></html>"""


@pytest.fixture()
def page(monkeypatch):
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
    yield pg
    browser.close()
    driver.stop()


def test_a_year_the_picker_lists_is_chosen(page):
    page.set_content(YEAR_PICKER)
    why = {}
    assert site.select_year(page, "2030", why) is True and why == {}
    assert page.input_value("#filterstyledselect-year") == "2030"


def test_a_year_printed_beside_the_picker_is_said_not_to_be_offered(page):
    """2029 is on the page, and the picker does not list it."""
    page.set_content(YEAR_PICKER)
    assert "2029" in site.year_options(page)
    why = {}
    assert site.select_year(page, "2029", why) is False
    assert why == {"why": "not offered"}


def test_a_year_the_picker_lists_and_will_not_take_is_not_said_to_be_not_offered(page):
    """2030 is listed, and a press on it never lands. A press that cannot
    land is given up on in a moment here, not thirty seconds."""
    page.set_content(YEAR_PICKER)
    page.evaluate("() => { document.querySelectorAll('[role=option]')[1]"
                  ".style.pointerEvents = 'none'; }")
    page.set_default_timeout(1500)
    why = {}
    assert site.select_year(page, "2030", why) is False
    assert why == {}
    assert page.input_value("#filterstyledselect-year") == "2031"


# -- the page's text reading ------------------------------------------------------

FALLBACK = """<!doctype html><html><body>
<label>Account <select id="acct" aria-label="Account">
  <option>Example Card ending 0001</option>
  <option>Other Card ending 0002</option>
  %s
</select></label>
<label>Year <select id="year" aria-label="Statement year">
  <option>2031</option><option>2030</option>%s
</select></label>
<ul id="rows"></ul>
<script>(() => {
const draw = () => {
  const a = document.getElementById('acct').value.slice(-4);
  const y = document.getElementById('year').value;
  document.getElementById('rows').innerHTML =
    '<li>Mar 15, ' + y + ' Statement ' + a + ' <a href="#">Download</a></li>';
};
document.getElementById('acct').onchange = draw;
document.getElementById('year').onchange = draw;
draw();
})();</script></body></html>"""


def choosing(monkeypatch, refuse=()):
    """_select_option, with the labels in `refuse` not taking, and every
    label asked for kept."""
    chosen = []
    real = site._select_option

    def choose(pg, sel, label):
        chosen.append(label)
        return False if label in refuse else real(pg, sel, label)
    monkeypatch.setattr(site, "_select_option", choose)
    return chosen


def test_the_page_text_reading_of_every_part_passes_over_nothing(page, monkeypatch):
    page.set_content(FALLBACK % ("", ""))
    chosen = choosing(monkeypatch)
    got = site.chase_collect(page)
    assert {"Example Card ending 0001", "Other Card ending 0002", "2031", "2030"} <= set(chosen)
    assert {r["date"][:4] for r in got} == {"2031", "2030"}
    assert got.passed_over == ()


def test_the_page_text_reading_passes_over_an_account_it_could_not_choose(page, monkeypatch):
    page.set_content(FALLBACK % ("", ""))
    choosing(monkeypatch, refuse=("Other Card ending 0002",))
    assert site.chase_collect(page).passed_over == ("account picker",)


def test_the_page_text_reading_passes_over_a_year_it_could_not_choose(page, monkeypatch):
    page.set_content(FALLBACK % ("", ""))
    choosing(monkeypatch, refuse=("2030",))
    assert site.chase_collect(page).passed_over == ("year picker",)


def test_the_page_text_reading_never_chooses_a_turned_off_or_refused_option(page, monkeypatch):
    """A turned off year waited out its time and was passed over, and an
    account the guard refuses is never chosen. Neither is a part of the
    list the walk could read."""
    page.set_content(FALLBACK % ("<option>Transfer funds ending 0003</option>",
                                 "<option disabled>2029</option>"))
    chosen = choosing(monkeypatch)
    got = site.chase_collect(page)
    assert "2029" not in chosen and not any("Transfer" in c for c in chosen), chosen
    assert {"Example Card ending 0001", "Other Card ending 0002", "2031", "2030"} <= set(chosen)
    assert got.passed_over == ()


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch):
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
        monkeypatch.setattr(app, "page", lambda: None)
        monkeypatch.setattr(app, "_on_its_site", lambda: None)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, _name: pressed.append((doc.account, doc.date)))
        return app

    build.pressed = pressed
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(pickers, make_app):
    app = make_app("--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == ALL
    assert listing.last(app) == listing.COMPLETE


@pytest.mark.parametrize("passed", ["year", "card"])
def test_a_list_passed_over_in_part_is_not_noted_whole(pickers, make_app, tmp_path, capsys,
                                                       passed):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    if passed == "year":
        pickers["refuse"].add("2030")
        taken = [r for r in ALL if r[1][:4] == "2031"]
    else:
        pickers["closed"].add(CARDS[1])
        taken = [r for r in ALL if r[0] == CARDS[0]]
    app = make_app("--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert sorted(make_app.pressed) == taken
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Chase's statement list was not read whole" in out
    assert "Not all of Chase's statement list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the statement list",
                                                  "some of the list could not be chosen")

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(pickers, make_app):
    pickers["refuse"].add("2030")
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert len(make_app().discovery.data) == len(CARDS) * 2


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(pickers, make_app):
    pickers["refuse"].add("2030")
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert make_app.pressed and {d[:4] for _a, d in make_app.pressed} == {"2031"}
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        pickers, make_app, capsys, monkeypatch):
    """No card would open, so the walk read nothing, and neither did the
    page's text reading after it. There is nothing to pilot, and the cards
    were never read."""
    pickers["closed"].update(CARDS)
    monkeypatch.setattr(site, "chase_collect", lambda page: [])
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Chase's statement list was read, so this run stops here" in out
    assert make_app.pressed == []
