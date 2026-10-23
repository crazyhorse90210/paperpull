"""This first build of Bank of America reads nothing and presses nothing.

Discover, Pilot, Run All and Resume say it is not built yet, to Record
instead, and stop as a run that stopped, never as a clean run that found
nothing. None of them asks anything of the browser. Login names a sign-in
form or a check and otherwise says it cannot tell, and never says a session
is signed in. Diagnose reads the page the person left open and follows,
presses and fetches nothing.

No browser is started. The page is a stand-in that writes down everything
asked of it, and every address and title in it is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_docs as app_mod
import bofa_site as site
from paperpull_core.run_reporting import PREFIX

# What a page can be asked that does something rather than read.
PRESSES = {"click", "dblclick", "tap", "check", "uncheck", "set_checked", "fill", "type",
           "press", "select_option", "dispatch_event", "set_input_files", "evaluate",
           "expose_binding", "route", "request"}


class Asked(list):
    def did(self, name):
        return [a for a in self if a[0] == name]


class Locator:
    def __init__(self, page, selector, n=0, text=""):
        self.page, self.selector, self.n, self.text = page, selector, n, text

    def __getattr__(self, name):
        if name in PRESSES:
            def press(*a, **k):
                self.page.asked.append((name, self.selector))
            return press
        raise AttributeError(name)

    def count(self):
        self.page.asked.append(("count", self.selector))
        return self.n

    def nth(self, i):
        return Locator(self.page, self.selector, 1, self.text)

    def inner_text(self, timeout=None):
        return self.text

    def all_inner_texts(self):
        return [self.text] if self.text else []

    def get_attribute(self, name):
        return ""


class Page:
    """A stand-in for a tab. `password` is how many password fields it has,
    `text` what its body says."""

    def __init__(self, url, password=0, text="Accounts overview", title="Accounts"):
        self.url, self.password, self.text, self._title = url, password, text, title
        self.asked = Asked()

    def __getattr__(self, name):
        if name in PRESSES:
            def press(*a, **k):
                self.asked.append((name, a))
            return press
        raise AttributeError(name)

    def is_closed(self):
        return False

    def title(self):
        return self._title

    def locator(self, selector):
        if "password" in selector:
            return Locator(self, selector, self.password)
        if selector == "body":
            return Locator(self, selector, 1, self.text)
        return Locator(self, selector, 1, "Statements")

    def get_by_role(self, role, **k):
        return Locator(self, role, 2, "View statement" if role == "link" else "Transfer | Zelle")

    def goto(self, url, **k):
        self.asked.append(("goto", url))
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def on(self, *a):
        self.asked.append(("on", a))


def _config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "document_types": ["Statement", "Tax Document"], "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5,
    }), encoding="utf-8")
    return cfg


@pytest.fixture
def no_browser(monkeypatch):
    def refuse(self):
        raise AssertionError("the browser was asked for")
    monkeypatch.setattr(app_mod.App, "browser", refuse)


@pytest.mark.parametrize("command", ["--discover", "--pilot", "--all", "--resume", "--dry-run"])
def test_a_run_says_it_is_not_built_and_stops(command, tmp_path, capsys, no_browser):
    cfg = _config(tmp_path)
    with pytest.raises(SystemExit) as stop:
        app_mod.main([command, "--config", str(cfg)])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    said = " ".join(out.split())
    assert "Bank of America is not built yet" in said
    assert "press Record" in said and "issue #121" in said
    result = [line for line in out.splitlines() if line.startswith(PREFIX)]
    assert result, out
    payload = result[-1][len(PREFIX):]
    # The panel's mark comes first when the panel started the run.
    got = json.loads(payload if payload.startswith("{") else payload.split(" ", 1)[1])
    assert got["stopped"] == 1 and got["new_files"] == 0, got
    out_dir = tmp_path / "out"
    assert not list(out_dir.rglob("*.pdf"))
    discovery = out_dir / "discovery.json"
    assert not discovery.exists() or json.loads(discovery.read_text(encoding="utf-8")) in ({}, [])


@pytest.mark.parametrize("command", ["--discover", "--pilot"])
def test_a_listing_is_never_noted_whole(command, tmp_path, capsys, no_browser):
    cfg = _config(tmp_path)
    with pytest.raises(SystemExit):
        app_mod.main([command, "--config", str(cfg)])
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note["complete"] is False


def test_the_site_refuses_a_list_and_a_document():
    page = Page("https://secure.bankofamerica.com/a")
    with pytest.raises(site.NotBuilt):
        site.collect_documents(page)
    with pytest.raises(site.NotBuilt):
        site.download_document(page, "Statement", "2026-03-31", Path("x.pdf"))
    assert not page.asked


def test_a_document_already_listed_stops_the_run_and_nothing_is_pressed(tmp_path, capsys, monkeypatch):
    cfg = _config(tmp_path)
    args = app_mod.build_parser().parse_args(["--pilot", "--config", str(cfg)])
    app = app_mod.App(args)
    page = Page("https://secure.bankofamerica.com/a")
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    doc = app_mod.Document(title="Statement", category="Statement", summary="Statement",
                           date="2026-03-31", account="Checking - 1111")
    with pytest.raises(SystemExit) as stop:
        app.process([doc])
    assert stop.value.code == 0
    assert "Bank of America is not built yet" in " ".join(capsys.readouterr().out.split())
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] == "goto"], page.asked
    assert not list((tmp_path / "out").rglob("*.pdf"))


def _login(tmp_path, monkeypatch, page, own):
    cfg = _config(tmp_path)
    args = app_mod.build_parser().parse_args(["--login", "--config", str(cfg)])
    app = app_mod.App(args)
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    monkeypatch.setattr(app_mod.tabs, "is_own", lambda tab: own)
    app.cmd_login()


@pytest.mark.parametrize("page", [
    Page("https://secure.bankofamerica.com/a"),
    Page("https://www.bankofamerica.com/", text="Welcome"),
])
def test_login_never_says_a_session_is_signed_in(page, tmp_path, capsys, monkeypatch):
    _login(tmp_path, monkeypatch, page, own=False)
    said = " ".join(capsys.readouterr().out.split()).lower()
    assert "cannot tell whether you are signed in" in said
    assert "success" not in said and "you are signed in" not in said.replace(
        "whether you are signed in", "")
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] == "goto"], page.asked


def test_login_names_a_sign_in_form(tmp_path, capsys, monkeypatch):
    page = Page("https://www.bankofamerica.com/", password=1)
    _login(tmp_path, monkeypatch, page, own=False)
    assert "shows a sign-in form" in " ".join(capsys.readouterr().out.split())
    assert not page.asked.did("goto")


def test_login_opens_the_home_page_only_in_a_tab_it_opened(tmp_path, capsys, monkeypatch):
    page = Page("about:blank", password=1)
    _login(tmp_path, monkeypatch, page, own=True)
    assert page.asked.did("goto") == [("goto", "https://www.bankofamerica.com/")]


def test_login_never_moves_a_tab_of_the_persons(tmp_path, capsys, monkeypatch):
    page = Page("https://www.elsewhere.test/")
    _login(tmp_path, monkeypatch, page, own=False)
    assert not page.asked.did("goto")
    assert "no tab is on bankofamerica.com" in " ".join(capsys.readouterr().out.split())


def test_login_names_a_check(tmp_path, capsys, monkeypatch):
    page = Page("https://secure.bankofamerica.com/a", text="Enter the code we sent you")
    _login(tmp_path, monkeypatch, page, own=False)
    assert "Security challenge detected" in capsys.readouterr().out


def test_a_password_field_or_an_unreadable_page_is_signed_out():
    assert site.looks_signed_out(Page("https://www.bankofamerica.com/", password=1))
    assert not site.looks_signed_out(Page("https://secure.bankofamerica.com/a"))

    class Broken(Page):
        def locator(self, selector):
            raise RuntimeError("gone")
    assert site.looks_signed_out(Broken("https://secure.bankofamerica.com/a"))
    assert site.looks_signed_out(Page(""))


def test_the_survey_reads_the_open_page_and_does_nothing_on_it():
    page = Page("https://secure.bankofamerica.com/a/b?acct=12345#top")
    report = site.survey(page, dwell_ms=0)
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] in ("goto", "on")], page.asked
    summary = report["pages"][0]
    assert summary["on_site"] is True
    assert "acct" not in summary["url"] and "12345" not in summary["url"]
    assert {c["safe"] for c in summary["controls"]} == {True, False}
    assert report["mapped"] is False


def test_the_survey_reads_nothing_off_a_page_of_another_site():
    page = Page("https://www.elsewhere.test/private", title="Someone's page")
    summary = site.survey(page, dwell_ms=0)["pages"][0]
    assert summary["on_site"] is False
    assert summary["title"] == "" and "controls" not in summary
    assert "elsewhere" not in summary["url"]
