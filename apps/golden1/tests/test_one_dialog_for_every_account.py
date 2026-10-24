"""One history dialog for every account, its list drawn a moment after it opens (#35).

RECORDED, from the member's 0.39.1 Pilot of 2026-09-28. Discover listed 24
statements, all of them month ends, twelve for the checking account and the
same twelve dates again for the second account, the card, whose own list runs
on the 20th of each month. The Pilot then looked for 2026-07-31 in the card's
list and found nothing. Each account's history also read one page, where the
member counts seven years behind NEXT.

The dialog here works the way his page appears to. Statement History asks the
vendor for the account's list and the list arrives a moment later, drawn into
the same dialog the account before used. Until then the dialog holds the old
list, hidden or showing depending on the case. The card's heading names no
card, as his did, and carries a balance, which a key must not keep. Every
date, name and number is invented.

A test can hold an account's first list until the app has looked at the page
a given number of times, so the list lands between two of the app's own looks
and not where a clock puts it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_site as site


def _month_ends(n, first_year=2026, first_month=8):
    import calendar
    out, y, m = [], first_year, first_month
    for _ in range(n):
        out.append("%02d/%02d/%02d" % (m, calendar.monthrange(y, m)[1], y % 100))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _twentieths(n, first_year=2026, first_month=9):
    out, y, m = [], first_year, first_month
    for _ in range(n):
        out.append("%02d/20/%02d" % (m, y % 100))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


MEMBER = _month_ends(26)          # 08/31/26 back to 07/31/24, three pages
CARD = _twentieths(15)            # 09/20/26 back to 07/20/25, two pages

VENDOR = """<!doctype html><html><body>
<h1>eStatements</h1>
<form>
 <div id="panels">
  <div class="panel">
   <h2 aria-expanded="true" class="head">Member Share Draft XXXXXX1111 Balance $1,234.56</h2>
   <div class="body" id="p0"><ul><li><h3>Checking and Savings</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="0">Statement History</a></div></li></ul></li></ul></div>
  </div>
  <div class="panel">
   <h2 aria-expanded="false" class="head">PLATINUM REWARDS XXXXXXXXXXXX4321 Balance $98.76</h2>
   <div class="body" id="p1" style="display:none"><ul><li><h3>Platinum Rewards</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="1">Statement History</a></div></li></ul></li></ul></div>
  </div>
 </div>
 <div id="dlg" style="display:none">
  <div role="dialog" aria-labelledby="dt" tabindex="-1">
   <div role="document"><div><div><span id="dt">Statement History</span></div>
    <div><span id="list"></span>
     <div><button type="button" id="next"><span>NEXT</span></button>
          <button type="button" id="close"><span>Close</span></button></div></div>
   </div></div>
  </div>
 </div>
</form>
<script>
const LISTS = {0: MEMBER_JSON, 1: CARD_JSON};
const SHOW_AT_ONCE = SHOW_JSON;
const SAME_AGAIN = SAME_JSON;
const HELD = HELD_JSON;
const DRAW_MS = DRAW_JSON, NEXT_MS = 400;
let panel = 0, pageNo = 0, asked = 0;
window.__pressed = [];
for (const h of document.querySelectorAll('h2.head')) {
  h.addEventListener('click', () => {
    for (const other of document.querySelectorAll('h2.head')) {
      const open = other === h;
      other.setAttribute('aria-expanded', open ? 'true' : 'false');
      other.nextElementSibling.style.display = open ? '' : 'none';
    }
  });
}
function draw() {
  const dates = LISTS[panel].slice(pageNo * 12, pageNo * 12 + 12);
  const years = {};
  for (const d of dates) (years['20' + d.slice(-2)] = years['20' + d.slice(-2)] || []).push(d);
  let html = '<ul>';
  for (const y of Object.keys(years).sort().reverse()) {
    html += '<li><span class="yr">' + y + '</span><ul>' +
      years[y].map(d => '<li><a href="#" class="stmt">' + d + '</a></li>').join('') + '</ul></li>';
  }
  document.getElementById('list').innerHTML = html + '</ul>';
  document.getElementById('next').disabled = (pageNo + 1) * 12 >= LISTS[panel].length;
  for (const a of document.querySelectorAll('a.stmt')) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      window.__pressed.push(a.textContent);
      const pdf = '%PDF-1.4\\n% invented ' + (panel ? 'card' : 'member') + ' statement ' +
                  a.textContent + '\\n' + 'x'.repeat(300) + '\\n%%EOF\\n';
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
      link.download = 'dxweb.pdf';
      document.body.appendChild(link);
      link.click();
    });
  }
}
for (const a of document.querySelectorAll('a.hist')) {
  a.addEventListener('click', (e) => {
    e.preventDefault();
    const mine = ++asked;
    // The dialog the account before used, with its list still in it.
    if (SHOW_AT_ONCE) document.getElementById('dlg').style.display = '';
    const answer = () => {
      if (mine !== asked) return;
      panel = Number(a.dataset.panel); pageNo = 0;
      draw();
      document.getElementById('dlg').style.display = '';
    };
    // An account's first list a test holds is drawn when the test says so,
    // and a list asked for with no wait is drawn by the press itself.
    const held = HELD.indexOf(Number(a.dataset.panel));
    if (held >= 0) { HELD.splice(held, 1); window.__held = answer; }
    else if (DRAW_MS === 0) answer();
    else setTimeout(answer, DRAW_MS);
  });
}
document.getElementById('next').addEventListener('click', () => {
  setTimeout(() => { if (!SAME_AGAIN) pageNo += 1; draw(); }, NEXT_MS);
});
document.getElementById('close').addEventListener('click', () => {
  document.getElementById('dlg').style.display = 'none';
});
</script></body></html>"""


def _vendor_html(show_at_once=False, same_again=False, held=(), draw_ms=500):
    return (VENDOR.replace("MEMBER_JSON", json.dumps(MEMBER)).replace("CARD_JSON", json.dumps(CARD))
            .replace("SHOW_JSON", json.dumps(show_at_once)).replace("SAME_JSON", json.dumps(same_again))
            .replace("HELD_JSON", json.dumps(list(held))).replace("DRAW_JSON", json.dumps(draw_ms)))


def _drive(monkeypatch, html=None, **kw):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_content(html if html is not None else _vendor_html(**kw))
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "open_vendor", lambda page: pg)
    return driver, browser, pg


def _draw_after_look(monkeypatch, k):
    """The list the page holds is drawn right after the app's k-th look at
    the dated list since the press, before its next look. The app's own
    look opens the gate, so no clock says where the list lands. Returns
    what each of those looks looked for."""
    real = site._listed_labels
    looks: list = []

    def look(page, fresh_only=False):
        got = real(page, fresh_only=fresh_only)
        if page.evaluate("() => !!window.__held"):
            looks.append("drawn after the press" if fresh_only else "showing")
            if len(looks) == k:
                page.evaluate("() => { const answer = window.__held; window.__held = null; answer(); }")
        return got
    monkeypatch.setattr(site, "_listed_labels", look)
    return looks


# The first account's list drawn right after the app's first look found
# none, before its next look. Full runs under load did this twice on
# 2026-10-06, and the list the press drew was said to show without being
# drawn again.
BETWEEN_LOOKS = "first list drawn between two looks"


@pytest.fixture(params=["old list hidden", "old list showing"])
def vendor(request, monkeypatch):
    if request.param == BETWEEN_LOOKS:
        driver, browser, pg = _drive(monkeypatch, show_at_once=True, held=[0])
        _draw_after_look(monkeypatch, 1)
    else:
        driver, browser, pg = _drive(monkeypatch, show_at_once=request.param == "old list showing")
    yield pg
    browser.close()
    driver.stop()


def _dates(docs, account):
    return [d.date_text for d in docs if d.account == account]


@pytest.mark.parametrize("vendor", ["old list hidden", "old list showing", BETWEEN_LOOKS], indirect=True)
def test_each_account_is_read_from_its_own_list(vendor):
    """His Discover. The second account's history was read before its own
    list arrived, and got the first account's dates. It is read from the list
    drawn for it now, every page of it, and Discover says how, in words and
    counts that carry nothing from the headings."""
    trace: list = []
    docs = site.collect_download_docs(vendor, trace=trace)
    member = _dates(docs, "")
    card = [d.date_text for d in docs if d.account]
    assert len(card) == 15 and all(d.endswith("-20") for d in card), (card, trace)
    assert card[0] == "2026-09-20" and card[-1] == "2025-07-20", card
    assert len(member) == 26 and member[0] == "2026-08-31" and member[-1] == "2024-07-31", member
    assert {d.account for d in docs if d.account} == {"account ending 4321"}
    read = [t for t in trace if t.get("note") == "a panel's statement history was read"]
    assert [(t["pages"], t["dated"], t["list"], t["paging_stopped"]) for t in read] == [
        (3, 26, site.DRAWN, "NEXT is disabled"), (2, 15, site.DRAWN, "NEXT is disabled")], read

    lines = site.discovery_lines(trace)
    assert lines[0] == "The statements page shows 2 account(s), 0 taken for a card."
    assert lines[1] == ("Account 1 heading carries the words member, share, and a masked number. "
                        "The headings under it carry checking, savings.")
    assert lines[2] == ("Account 2 heading carries the words platinum, rewards, and a masked "
                        "number. The headings under it carry platinum, rewards.")
    assert lines[3] == ("Account 1 history, 26 statements on 3 page(s). Its list was drawn after "
                        "the press. Paging stopped because NEXT is disabled.")
    assert lines[4].startswith("Account 2 history, 15 statements on 2 page(s).")
    said = json.dumps(trace) + " ".join(lines)
    for private in ("4321", "1111", "1,234.56", "98.76", "PLATINUM", "Share Draft"):
        assert private not in said, private


def test_a_card_statement_is_saved_after_discovery_read_both(vendor, tmp_path):
    """His Pilot, after that Discover. The dialog last showed the card's
    oldest page, and the statement asked for is on the card's second page."""
    docs = site.collect_download_docs(vendor, trace=[])
    [doc] = [d for d in docs if d.date_text == "2025-08-20"]
    out = tmp_path / "card.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out, title=doc.title,
                              trace=trace, account=doc.account), trace
    assert b"invented card statement 08/20/25" in out.read_bytes()
    assert vendor.evaluate("window.__pressed") == ["08/20/25"]
    [searched] = [t for t in trace if t.get("note") == "the panel's statement history was searched"]
    assert searched["panel"] == 1 and searched["pages"] == 2 and searched["found"], searched


@pytest.mark.parametrize("k", [1, 2, 3])
def test_a_list_drawn_between_any_two_looks_is_said_to_be_drawn(monkeypatch, k):
    """The app looked for a list drawn after the press and then at what
    showed, so a list drawn between those two looks was taken as one that
    showed without being drawn again, and its first page was read with
    every dated control showing. The list comes right after the app's
    k-th look here, wherever that falls, and is said to be drawn."""
    driver, browser, pg = _drive(monkeypatch, show_at_once=True, held=[0])
    try:
        looks = _draw_after_look(monkeypatch, k)
        member = site.history_panels(pg)[0]
        facts: dict = {}
        assert site.open_panel_history(pg, member, [], facts=facts), facts
        assert len(looks) == k, looks
        assert facts["list"] == site.DRAWN, (facts, looks)
        assert site._last_read(pg) == {"panel": 0, "labels": MEMBER[:12]}
    finally:
        browser.close()
        driver.stop()


def test_a_look_that_could_not_be_read_says_nothing(monkeypatch):
    """A label read can run out of time on a loaded machine. When one did
    in the look for a list drawn after the press, that look came back
    empty, and the list the press drew was taken as one that showed
    without being drawn again. The press draws the list itself here, so it
    is there for every look, and the first two looks for a list drawn after
    the press each have a label read run out of time."""
    from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeout
    driver, browser, pg = _drive(monkeypatch, show_at_once=True, draw_ms=0)
    try:
        real_look, real_text = site._listed_labels, Locator.inner_text
        state = {"drawn_look": False, "ran_out": 0}

        def look(page, fresh_only=False):
            state["drawn_look"] = fresh_only
            try:
                return real_look(page, fresh_only=fresh_only)
            finally:
                state["drawn_look"] = False

        def inner_text(self, *args, **kwargs):
            if state["drawn_look"] and state["ran_out"] < 2:
                state["ran_out"] += 1
                state["drawn_look"] = False
                raise PlaywrightTimeout("Timeout 500ms exceeded, as a read on a loaded machine can")
            return real_text(self, *args, **kwargs)
        monkeypatch.setattr(site, "_listed_labels", look)
        monkeypatch.setattr(Locator, "inner_text", inner_text)
        member = site.history_panels(pg)[0]
        facts: dict = {}
        assert site.open_panel_history(pg, member, [], facts=facts), facts
        assert state["ran_out"] == 2
        assert facts["list"] == site.DRAWN, facts
        assert site._last_read(pg) == {"panel": 0, "labels": MEMBER[:12]}
    finally:
        browser.close()
        driver.stop()


def test_a_member_statement_after_a_card_one_comes_from_the_members_list(monkeypatch, tmp_path):
    """The dialog last held the card's list, showing it again as it opens,
    and the member's own list is the one searched."""
    driver, browser, pg = _drive(monkeypatch, show_at_once=True)
    try:
        docs = site.collect_download_docs(pg, trace=[])
        card = [d for d in docs if d.date_text == "2026-09-20"][0]
        assert site.download_bill(pg, tmp_path / "dl", "2026-09-20", tmp_path / "a.pdf",
                                  title=card.title, trace=[], account=card.account)
        out = tmp_path / "b.pdf"
        trace: list = []
        assert site.download_bill(pg, tmp_path / "dl", "2024-08-31", out,
                                  title="Account Statement - August 31, 2024", trace=trace,
                                  account=""), trace
        assert b"invented member statement 08/31/24" in out.read_bytes()
        assert pg.evaluate("window.__pressed") == ["09/20/26", "08/31/24"]
    finally:
        browser.close()
        driver.stop()


def test_a_next_that_draws_the_same_page_again_ends_the_paging(monkeypatch, tmp_path):
    """A NEXT that brings the page it was pressed on is the last page, said
    in the trace, and not a loop to the page limit."""
    monkeypatch.setattr(site, "HISTORY_WAIT_MS", 2400)
    driver, browser, pg = _drive(monkeypatch, same_again=True)
    try:
        trace: list = []
        docs = site.collect_download_docs(pg, trace=trace)
        read = [t for t in trace if t.get("note") == "a panel's statement history was read"]
        assert [(t["pages"], t["paging_stopped"]) for t in read] == [
            (1, "NEXT drew the same page again"), (1, "NEXT drew the same page again")], read
        assert len(docs) == 24
    finally:
        browser.close()
        driver.stop()


def _panel(i, heading, card=False):
    return {"i": i, "heading": heading, "card": card}


def test_a_second_account_is_keyed_by_its_masked_number_and_not_its_balance():
    """0.39.1 keyed a second account by its whole heading. A balance in it
    would have listed every statement again as new each time it changed."""
    first = _panel(0, "Member Share Draft XXXXXX1111 Balance $1,234.56")
    for balance in ("$98.76", "$0.00", "$12,345.67 as of 09/27/2026"):
        second = _panel(1, "PLATINUM REWARDS XXXXXXXXXXXX4321 Balance " + balance)
        assert site._panel_account([first, second], first) == ""
        assert site._panel_account([first, second], second) == "account ending 4321"
    for masked in ("Visa ****4321", "Card ending in 4321", "Rewards ...4321", "Rewards x4321"):
        assert site._panel_account([first, _panel(1, masked)], _panel(1, masked)) == \
            "account ending 4321", masked
    # With no masked number, the heading's words, which a balance, a date or
    # a month name does not change.
    for tail in ("$4,321.00 on 09/20/2026", "$0.00 on Oct 20, 2026"):
        plain = _panel(2, "Savings Balance " + tail)
        assert site._panel_account([first, _panel(1, "Other"), plain], plain) == \
            "account savings balance on", tail
    # A card keeps the empty key of the first panel of its kind.
    card = _panel(1, "VISA SIGNATURE CARD ****4321", card=True)
    assert site._panel_account([first, card], card) == ""


def test_two_later_accounts_never_share_a_key():
    """A key two panels shared would give them one record for each date, and
    the second account's statements on those dates would never be saved. A
    credit union can mask one member number the same on every share, with a
    suffix after it."""
    first = _panel(0, "Member XXXXXX1111-00 Balance $1.00")
    shares = [_panel(1, "Share XXXXXX1111-20 Balance $5.00"), _panel(2, "Share XXXXXX1111-70 Balance $6.00")]
    panels = [first] + shares
    assert [site._panel_account(panels, p) for p in shares] == [
        "account ending 1111-20", "account ending 1111-70"]
    twins = [_panel(1, "Visa ****4321"), _panel(2, "Visa ****4321")]
    assert [site._panel_account([first] + twins, p) for p in twins] == ["account 2", "account 3"]


def test_a_key_stays_with_its_account_when_another_closes():
    """A place would pass to the next account when one before it closed, and
    that account's statements on the closed one's dates would read as
    already saved."""
    first = _panel(0, "Checking $1.00")
    savings, market = _panel(1, "Savings $5.00"), _panel(2, "Money Market $9.00")
    before = {p["heading"]: site._panel_account([first, savings, market], p) for p in (savings, market)}
    market_later = _panel(1, "Money Market $12.00")
    assert site._panel_account([first, market_later], market_later) == before["Money Market $9.00"] \
        == "account money market"
    assert before["Savings $5.00"] == "account savings"


def test_a_next_drawn_as_a_disabled_link_ends_the_paging_at_once(monkeypatch):
    """A WebForms link button that is off is drawn as a link with the class
    aspNetDisabled, which a browser calls enabled. Pressed, it brings no
    page, and the wait for one would cost each account the whole wait."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        pg = browser.new_page()
        pg.set_content("<div role='dialog'><ul><li><a href='#'>09/20/26</a></li></ul>"
                       "<a class='aspNetDisabled'>NEXT</a><button>Close</button></div>")
        facts: dict = {}
        assert not site.next_history_page(pg, facts)
        assert facts["stopped"] == "NEXT is disabled" and "waited_s" not in facts, facts
    finally:
        browser.close()
        driver.stop()


def test_the_heading_words_a_trace_carries_come_from_the_list():
    facts = site._panel_facts({"heading": "Jane Invented's PLATINUM Visa ****4321 $55.10",
                               "sub": ["Credit Card Statements"]})
    assert facts == {"words": ["platinum", "visa"], "words_under_it": ["card", "credit", "statements"],
                     "masked_number": True}
    assert site._panel_facts({"heading": "", "sub": []}) == {
        "words": [], "words_under_it": [], "masked_number": False}


# -- a control drawn as an input -------------------------------------------------
#
# A dated statement and a Statement History are found by their role, and
# Playwright gives an <input> of type button, submit, image or reset a
# button's role. The marks set before a press, and the panels, read links and
# buttons alone, so a control drawn as such an input carried no mark and was
# no panel's. The member's last page, left in the dialog when the second
# account's own list never came, was taken as that account's, drawn again the
# same, and a member statement was pressed and saved as the second
# account's. And with every Statement History drawn so, the open panel's
# history was read under the first account's key. Each page is read now as
# when its controls are links.

INPUT_KINDS = ("button", "submit", "image", "reset")
STATEMENT_LINK = "'<li><a href=\"#\" class=\"stmt\">' + d + '</a></li>'"
HISTORY_LINK = '<a href="#" class="hist" data-panel="%d">Statement History</a>'
MEMBER_OPEN = ('<h2 aria-expanded="true" class="head">Member Share Draft XXXXXX1111 Balance $1,234.56</h2>\n'
               '   <div class="body" id="p0">')
SECOND_SHUT = ('<h2 aria-expanded="false" class="head">PLATINUM REWARDS XXXXXXXXXXXX4321 Balance $98.76</h2>\n'
               '   <div class="body" id="p1" style="display:none">')


def _input(kind, more=""):
    """A control drawn as an <input> of `kind`, an image given a size so
    that it is drawn."""
    size = ' src="data:," width="24" height="24"' if kind == "image" else ""
    return '<input type="%s"%s%s>' % (kind, size, more)


def _swap(html, pairs):
    for old, new in pairs:
        assert old in html, old
        html = html.replace(old, new)
    return html


def _statements_as(html, kind):
    """The vendor's page with each dated statement drawn as an input of
    `kind`, named for a screen reader by its date, or as its link."""
    if kind == "link":
        return html
    size = ' src="data:," width="24" height="24"' if kind == "image" else ""
    return _swap(html, [
        (STATEMENT_LINK, "'<li><input type=\"%s\" class=\"stmt\"%s aria-label=\"' + d + '\"></li>'"
         % (kind, size)),
        ("document.querySelectorAll('a.stmt')", "document.querySelectorAll('.stmt')"),
        ("a.textContent", "a.getAttribute('aria-label')")])


def _histories_as(html, kind, open_panel=0):
    """The vendor's page with each panel's Statement History drawn as an
    input of `kind`, named for a screen reader, and the second panel the
    open one when `open_panel` is 1."""
    html = _swap(html, [(HISTORY_LINK % i, _input(kind, ' class="hist" data-panel="%d" '
                                                        'aria-label="Statement History"' % i))
                        for i in (0, 1)]
                 + [("document.querySelectorAll('a.hist')", "document.querySelectorAll('.hist')")])
    if open_panel:
        html = _swap(html, [
            (MEMBER_OPEN, MEMBER_OPEN.replace('"true"', '"false"').replace('id="p0">', 'id="p0" style="display:none">')),
            (SECOND_SHUT, SECOND_SHUT.replace('"false"', '"true"').replace(' style="display:none"', ''))])
    return html


@pytest.mark.parametrize("kind", ("link",) + INPUT_KINDS)
def test_a_list_left_from_the_account_before_is_never_the_next_accounts(monkeypatch, tmp_path, kind):
    """The second account's own list never comes, and the dialog goes on
    showing the member account's last page. Drawn as inputs, that page's
    statements carried no marks and were read as the second account's, and
    the member's statement of 08/31/24 was pressed and saved as the second
    account's. It is the list read before now, as with links, and nothing is
    listed for the second account or pressed for it."""
    monkeypatch.setattr(site, "HISTORY_WAIT_MS", 3000)
    driver, browser, pg = _drive(monkeypatch, _statements_as(
        _vendor_html(show_at_once=True, held=[1, 1, 1]), kind))
    try:
        trace: list = []
        docs = site.collect_download_docs(pg, trace=trace)
        assert [d.date_text for d in docs if d.account] == [], trace
        assert len(_dates(docs, "")) == 26
        shut = [t for t in trace if t.get("note") == "a panel's statement history did not show"]
        assert [(t["panel"], t["list"]) for t in shut] == [(1, site.BEFORE)], trace
        out = tmp_path / "second.pdf"
        later: list = []
        assert not site.download_bill(pg, tmp_path / "dl", "2024-08-31", out,
                                      title="Account Statement - August 31, 2024", trace=later,
                                      account="account ending 4321"), later
        assert not out.exists() and pg.evaluate("window.__pressed") == []
    finally:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_each_account_is_read_from_its_own_list_with_its_statements_drawn_as_inputs(monkeypatch, kind):
    """The dialog shows the member's last page as it opens for the second
    account, and the second account's list comes a moment later. Marked
    now, the member's page is not taken for it, and each account is read
    from its own list, every page."""
    driver, browser, pg = _drive(monkeypatch, _statements_as(_vendor_html(show_at_once=True), kind))
    try:
        docs = site.collect_download_docs(pg, trace=[])
        second = [d.date_text for d in docs if d.account]
        assert len(second) == 15 and all(d.endswith("-20") for d in second), second
        assert len(_dates(docs, "")) == 26
    finally:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("open_panel", [0, 1], ids=["the member's panel open", "the second panel open"])
@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_each_account_is_read_from_its_own_list_with_its_history_drawn_as_an_input(monkeypatch, kind,
                                                                                   open_panel):
    """Each panel's Statement History drawn as an input. No panel was found,
    so the page was read the way a page with no panels is, the open panel's
    first page alone, under the first account's key, and with the second
    panel open its statements were the member's. Each account is read from
    its own list now, under its own key, every page."""
    driver, browser, pg = _drive(monkeypatch, _histories_as(_vendor_html(), kind, open_panel))
    try:
        assert len(site.history_panels(pg)) == 2
        docs = site.collect_download_docs(pg, trace=[])
        member = _dates(docs, "")
        second = _dates(docs, "account ending 4321")
        assert len(member) == 26 and not any(d.endswith("-20") for d in member), member
        assert len(second) == 15 and all(d.endswith("-20") for d in second), second
    finally:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("field", ['<input type="text" aria-label="Statement History">',
                                   '<input type="checkbox" aria-label="Statement History">'],
                         ids=["a text field", "a box to tick"])
def test_a_field_named_statement_history_is_no_panels_link(monkeypatch, field):
    """Only an input Playwright gives a button's role is a control here, so a
    text field or a box to tick named like a Statement History is not taken
    for a panel's, and only the two panels' own are."""
    driver, browser, pg = _drive(monkeypatch, _swap(_vendor_html(), [
        ('<div id="panels">', '<div id="panels">' + field)]))
    try:
        panels = site.history_panels(pg)
        assert len(panels) == 2 and pg.locator("[data-paperpull-history]").count() == 2, panels
    finally:
        browser.close()
        driver.stop()
