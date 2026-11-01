"""Activity and a bill's print page, read in a real browser by the scripts
the site layer runs inside the page, and drawn by the real inert render.

The unit tests answer those scripts themselves and mock the render, so
none of the inlining ran. Here CivicPay Online is a made-up site on this
machine. Activity draws the transaction table, and each bill's print page
links stylesheets and images of every kind the inlining has rules for: its
own, one on another host, one behind a redirect, one that closes its style
element and imports another, one that is too big, and one with a password
rule. The app attaches over CDP as it does at home, and every other host
name fails to resolve, so nothing reaches Tualatin Water. Every number,
date and amount is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import tualatin_docs as app_mod
import tualatin_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

HOST = "tualatin.merchanttransact.test"
OTHER = "other.merchanttransact.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (HOST, OTHER))
COOKIE = "CivicSession=fake-browser-session"

# Newest first, as (Activity's date, ISO, bill number).
BILLS = [("09/30/2026", "2026-09-30", "10000003"), ("08/31/2026", "2026-08-31", "10000002"),
         ("07/31/2026", "2026-07-31", "10000001")]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

ACTIVITY = """<!doctype html><html><head><title>Activity</title></head><body><main>
<h1>Account 987654-321</h1>%(filter)s
<table><thead><tr><th>Transaction Date</th><th>Transaction Type</th><th>Description</th>
<th>Amount</th><th>Balance</th></tr></thead><tbody>%(rows)s</tbody></table>%(pager)s
</main></body></html>"""

PRINT = """<!doctype html><html><head><title>My Bill</title>
<link rel="stylesheet" href="/css/bill.css">
<link rel="stylesheet" href="http://%(other)s/css/evil.css">
<link rel="stylesheet" href="http://%(host)s:%(port)d/css/bill.css">
<link rel="stylesheet" href="/css/moved.css">
<link rel="stylesheet" href="/css/breakout.css">
<link rel="stylesheet" href="/css/big.css">
<link rel="stylesheet" href="/css/big2.css">
</head><body><img src="/img/logo.png"><img src="http://%(other)s/img/track.png">
<h2>Bill Details</h2><p>Billing Date</p><p>%(billed)s</p><p>Due Date</p><p>10/20/2026</p>
<p>Total Amount Due</p><p>$100.00</p><script>document.title = 'ran';</script></body></html>"""


class FakePortal:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, host, path).
        self.seen = []
        self.extra_type = ""
        self.pager = ""
        self.filter = ""
        self.big = 4000
        # The bill number whose print page gives another Billing Date.
        self.other_date_for = ""
        self.print_redirect = False
        # The port of a second server on the portal's own host name.
        self.other_port = 0


SITE = FakePortal()


def _rows():
    out = ['<tr><td>10/05/2026</td><td>Payment</td><td>Online payment</td><td>($10.00)</td><td>$0.00</td></tr>']
    for shown, _, number in BILLS:
        out.append('<tr><td>%s</td><td>Billing</td><td><a href="/secure/MyBill/%s">Billing</a></td>'
                   '<td>$100.00</td><td>$100.00</td></tr>' % (shown, number))
    if SITE.extra_type:
        out.append('<tr><td>06/30/2026</td><td>%s</td><td></td><td>$1.00</td><td>$1.00</td></tr>' % SITE.extra_type)
    return "".join(out)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(("GET", self._host(), path))
        if self._host() != HOST:
            return self._send(200, b"body { color: red }", "text/css")
        if path == "/secure/Activity":
            html = ACTIVITY % {"rows": _rows(), "pager": SITE.pager, "filter": SITE.filter}
            return self._send(200, html.encode(), "text/html; charset=utf-8",
                              [("Set-Cookie", COOKIE + "; Path=/")])
        if COOKIE not in (self.headers.get("Cookie") or ""):
            return self._redirect("/LoginRedirect.aspx")
        for shown, iso, number in BILLS:
            if path == "/secure/MyBill/%s/Print" % number:
                if SITE.print_redirect:
                    return self._redirect("/LoginRedirect.aspx")
                billed = "1/15/2026" if number == SITE.other_date_for else shown.lstrip("0").replace("/0", "/")
                port = self.server.server_address[1]
                page = PRINT % {"other": "%s:%d" % (OTHER, port), "host": HOST,
                                "port": SITE.other_port, "billed": billed}
                return self._send(200, page.encode(),
                                  "text/html; charset=utf-8")
        if path == "/css/bill.css":
            return self._send(200, b'h2 { color: #036 } input[type="password"] { border: 1px solid }',
                              "text/css")
        if path == "/css/moved.css":
            return self._redirect("/css/bill.css")
        if path == "/css/breakout.css":
            return self._send(200, b'@import url("/css/imported.css"); p { margin: 0 }'
                                   b' </style><h1>BROKE OUT</h1><style>', "text/css")
        if path in ("/css/big.css", "/css/big2.css"):
            return self._send(200, b"/*" + b"x" * SITE.big + b"*/", "text/css")
        if path == "/img/logo.png":
            return self._send(200, PNG, "image/png")
        self.send_error(404)

    def log_message(self, *args):
        pass


class _OtherPort(_Handler):
    """The portal's host name on another port, which is not its origin."""

    def do_GET(self):
        SITE.seen.append(("GET", "another port", urlsplit(self.path).path))
        self._send(200, b"body { color: red }", "text/css")


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


_other_port = [0]


@pytest.fixture(scope="module")
def server():
    httpd, other = _serve(_Handler), _serve(_OtherPort)
    _other_port[0] = other.server_address[1]
    yield httpd.server_address[1]
    for h in (httpd, other):
        h.shutdown()
        h.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture
def drawn(monkeypatch):
    """The HTML each bill is drawn from, as the real inert render gets it."""
    from paperpull_core import receipt_pdf
    got, real = [], receipt_pdf.print_html_inert_to_pdf

    def draw(page, html, out_path, base=None):
        got.append(html)
        return real(page, html, out_path, base=base)
    monkeypatch.setattr(receipt_pdf, "print_html_inert_to_pdf", draw)
    return got


@pytest.fixture(autouse=True)
def fake_portal(server, monkeypatch):
    """CivicPay Online is the made-up site, on plain http."""
    SITE.reset()
    SITE.other_port = _other_port[0]
    base = "http://%s:%d" % (HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name in ("DOCUMENTS_URL", "STATEMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, base + site.DOCUMENTS_PATH)
    for name in ("home", "login", "documents", "statements"):
        monkeypatch.setitem(site.URLS, name, base + site.DOCUMENTS_PATH)
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == HOST)
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, capsys, *command):
    try:
        ended = ("returned", app_mod.main([*command, "--config", str(config_for(tmp_path, cdp_url))]))
    except SystemExit as e:
        ended = ("exit", e.code)
    return ended, capsys.readouterr().out


def folded(out):
    return " ".join(out.split())


def saved(tmp_path):
    folder = tmp_path / "out" / "Statements"
    return sorted(folder.rglob("*.pdf")) if folder.exists() else []


def text_of(pdf):
    from pypdf import PdfReader
    return " ".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)


def asked(path, host=HOST):
    return sum(1 for s in SITE.seen if s == ("GET", host, path))


def their_tab(attached, server):
    theirs = testkit.open_tab(attached, "http://%s:%d/secure/Activity" % (HOST, server), "Activity")
    testkit.keep_only(attached, {theirs})


def test_every_bill_is_drawn_from_its_own_page_with_only_its_own_look(attached, server, tmp_path,
                                                                      capsys, drawn):
    """Each print page is drawn as a PDF. Its own stylesheet and image are
    written in, and a password rule in that stylesheet does not make it a
    sign-in page. The stylesheet on another host, the one behind a redirect
    and the one it imports are never fetched or followed, the one that
    closes its style element does not draw into the bill, and the render
    itself asks the portal for nothing."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert len(drawn) == 3, folded(out)
    for html in drawn:
        assert "h2 { color: #036 }" in html and "data:image/png;base64," in html
        assert "@import" not in html and "</style><h1>" not in html
        assert "\\3c /style>" in html
    pdfs = saved(tmp_path)
    assert len(pdfs) == 3, folded(out)
    for pdf in pdfs:
        text = text_of(pdf)
        assert "Bill Details" in text and "Total Amount Due" in text, text
        assert "BROKE OUT" not in text, text
    assert asked("/css/bill.css") == 3, SITE.seen
    assert asked("/css/moved.css") == 3, SITE.seen
    assert asked("/img/logo.png") == 3, SITE.seen
    assert asked("/css/imported.css") == 0, SITE.seen
    assert not any(s[1] in (OTHER, "another port") for s in SITE.seen), SITE.seen


def test_a_stylesheet_over_the_budget_is_left_out_and_noted(attached, server, tmp_path, capsys,
                                                           monkeypatch, caplog, drawn):
    """Two stylesheets each well under the limit, which together are over
    it: the first is written in and the second left out, and the run's log
    says so, where the person reads it."""
    monkeypatch.setattr(site, "MAX_PAGE_BYTES", 60_000)
    SITE.big = 35_000
    their_tab(attached, server)

    with caplog.at_level("WARNING", logger="tualatin_docs.site"):
        ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert len(saved(tmp_path)) == 3, folded(out)
    noted = [r.getMessage() for r in caplog.records if "left out of its PDF" in r.getMessage()]
    assert len(noted) == 3, caplog.text[-2000:]
    assert asked("/css/big.css") == 3 and asked("/css/big2.css") == 3, SITE.seen
    for html in drawn:
        assert html.count("x" * SITE.big) == 1, len(html)
        assert "data:image/png;base64," in html


def test_a_print_page_of_another_billing_date_is_not_saved(attached, server, tmp_path, capsys):
    SITE.other_date_for = BILLS[1][2]
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert len(saved(tmp_path)) == 2, folded(out)
    assert out.count("marked for manual review") == 1, folded(out)


def test_a_redirect_on_a_print_page_stops_the_run_as_signed_out(attached, server, tmp_path, capsys):
    SITE.print_redirect = True
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "answered as signed out" in folded(out), folded(out)
    assert saved(tmp_path) == []
    assert asked("/LoginRedirect.aspx") == 0, SITE.seen


@pytest.mark.parametrize("change, said", [
    ({"extra_type": "Adjustment"}, "of a type 'Adjustment' this app does not know"),
    ({"pager": '<ul class="pagination"><li><a href="?page=2">2</a></li><li><a href="?page=2">Next</a></li></ul>'},
     "shows a pager"),
    ({"filter": '<label for="from">From</label><input type="date" id="from" name="StartDate">'},
     "shows a date filter"),
])
def test_anything_saying_activity_is_not_whole_stops_discover(attached, server, tmp_path, capsys,
                                                              change, said):
    for k, v in change.items():
        setattr(SITE, k, v)
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert said in folded(out), folded(out)
