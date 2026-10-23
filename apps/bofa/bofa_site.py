"""Bank of America's site, as far as this first shell knows it.

When the site changes, repair this file only.

STATUS, NOT BUILT (#121). This is the shell a tester signs in with and
Records in. It opens www.bankofamerica.com in a browser profile of its own,
the person signs in there themselves, and Record and Diagnose watch the tab
they leave open. Which page lists statements, how an account or a year is
picked and how a statement's PDF arrives are not known, and nothing here
guesses at them. Discover and every download raise NotBuilt, which says to
Record one trip to a statement, since a recording is what the real app is
written from (docs/testing-a-provider.md).

What this shell does know is how to tell a sign-in form, which is a
password field on the page. It knows no shape of a signed-in page, so it
never says a session is signed in. That waits for the recording.

SAFETY. A bank, with checking, savings, credit cards, Zelle, transfers and
bill pay.
  Strictly READ-ONLY, and in this shell nothing is pressed at all. No
  function here clicks, types, selects, submits a form or confirms a
  dialog. The one navigation is opening the home page, in a tab this run
  opened itself, when no tab of the person's is on Bank of America's site.
  The guard below is what Record marks each control a person pressed
  against, and what the real build will hold every press to. Every host but
  bankofamerica.com and its subdomains is refused.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("bofa_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("bankofamerica.com",)

BASE = "https://www.bankofamerica.com"
URLS = {
    "home": BASE + "/",
    # login.bat opens this. The person signs in from Bank of America's own
    # home page, the address the request names (#121).
    "login": BASE + "/",
}

# Diagnose writes this down, so a survey file says it came from a shell.
NOT_MAPPED = ("Bank of America is not built yet. This first build only opens "
              "the site for a sign-in, and Record and Diagnose.")

# What Discover, Pilot, Run All, Resume and every download say instead of
# guessing. Plain words, no address, nothing from a page.
NOT_BUILT = (
    "Bank of America is not built yet, so this run lists and downloads "
    "nothing. This first build opens the site for you to sign in, and "
    "nothing more. To help build it, sign in with Login, then press Record "
    "(under more) and click your way to one statement the way you always "
    "do, then Stop recording. The recording.json it writes in this "
    "provider's Diagnostics folder is what the real app is built from. "
    "Read it through, then attach it to issue #121 on GitHub. Every run "
    "but Login, Record and Diagnose stops until it is built.")


class NotBuilt(RuntimeError):
    """Asked for a list or a document this first build cannot read."""

    def __init__(self, what: str = ""):
        super().__init__(NOT_BUILT)
        self.what = what


class SessionExpired(RuntimeError):
    """Bank of America answered with a sign-in page instead of a document.
    Nothing in this shell raises it yet. The engine stops a run on it."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a bank. Never move money, never pay, never
# open, close, lock or replace anything, never order or request anything
# that may carry a fee, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|\bpays\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"\bdeposit|withdraw|send\s+money|request\s+money|move\s+money|\bsend\b|"
    r"cash\s+advance|balance\s+transfer|\bredeem|\brewards?\b|\bdeals?\b|"
    r"keep\s+the\s+change|\boffers?\b|"
    # Opening an account or a card, never its statements.
    r"\bapply\b|open\s+(a|an|another|new|my)\b[\w\s]{0,24}\b(accounts?|cards?|cds?|ira)\b"
    r"(?!\s+(statements?|documents?))|"
    r"open\s+\w{0,12}\s*(accounts?|cards?)\b(?!\s+(statements?|documents?))|"
    r"\bopen\s+(now|merrill)\b|"
    r"get\s+(a\s+|an\s+|the\s+|your\s+)?(new\s+)?(card|account|loan|quote)\b|"
    r"close\s+(my\s+|an?\s+|this\s+)?account|"
    # A paper copy of a statement can carry a fee at a bank, so ordering,
    # requesting or getting a copy is never pressed.
    r"\bstop\b|\border\b|\brequest|\bcop(y|ies)\b|\bpaper\b|"
    r"\bloan\b|\bborrow|refinanc|"
    # Word boundaries on both sides of every stem. A card is a document
    # here, so "Credit card statement" must pass, and "edit" sits inside
    # "Credit".
    r"\breplac(e|es|ed|ing|ement)\b|\bactivat|\block\b|\bunlock|\bpin\b|"
    r"travel\s+(notice|notification|plans?)|credit\s+limit|"
    r"overdraft|balance\s+connect|\balerts?\b|\bbudget|\bgoals?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bmodif(y|ies|ied|ying)\b|\bmanage\b|"
    r"\bset\s+up\b|\bdelet|\bremov(e|es|ed|ing|al)\b|\bcancel|dispute|"
    r"report\s+(a\s+)?(lost|stolen|fraud)|\bfraud\b|"
    r"password|passcode|username|online\s+id|\bprofile\b|settings|preferences|"
    r"contact\s+info|\baddress\b|\bemail\b|\bphone\b|"
    r"\bconfirm|\bsubmit|\bagree\b|\baccept\b|authoriz|\bchat\b|contact\s+us|\berica\b|"
    r"beneficiar|nickname|\btrade\b|\bbuy\b|\bsell\b|"
    r"log\s*out|logout|log\s*off|sign\s*out|sign\s*off)", re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statements?\b|documents?\b|"
    r"\bletters?\b|\bnotices?\b|1099|1098|5498|tax\s+(forms?|documents?|statements?)|"
    r"\bsummar(y|ies)\b|year.?end|"
    r"\bhistory\b|see\s+(more|all|older)|show\s+(more|all|older))", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


SECURITY_CHALLENGE_MARKERS = [
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "authorization code", "authenticator",
    "confirm your identity", "verify your identity", "help us verify",
    "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "you have been logged off",
]

# Lowercased address fragments of a sign-in page. One only, the path the
# sign-in form has been on, not checked against an account yet. "/signin"
# is left out on purpose, since a signed-in overview may sit under a path
# like /myaccounts/signin/, and calling that signed out would refuse Record
# on the very page a person lands on. The password field below notices any
# sign-in form this misses.
LOGIN_URL_MARKERS = ["/login/sign-in/"]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic", "http error 429"]


def looks_signed_out(page) -> bool:
    """True where the page is the sign-in page by its address, shows a
    password field, or cannot say where it is."""
    try:
        url = (page.url or "").lower()
    except Exception:
        # A page that cannot say where it is is treated as signed out, the
        # safe answer.
        return True
    if not url or any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        return True
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the code, CAPTCHA or throttling prompt on screen, or None.
    Visible text only, and never a reason to think a session is signed in
    when it finds nothing."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def open_home(page) -> bool:
    """Bank of America's home page, where a person signs in, opened in a
    tab this run opened itself. Never in a tab of the person's, which is
    left where they put it. True when the tab ended on the site."""
    if not is_safe_url(URLS["home"]):
        return False
    try:
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log.info("home page failed: %s", e)
    try:
        return is_safe_url(page.url or "")
    except Exception:
        return False


# -- what this first build cannot do yet ---------------------------------------

def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every statement and tax form the accounts list. Not built, so this
    refuses rather than read a page it does not know."""
    raise NotBuilt("the list of statements")


def download_document(page, *args, **kwargs) -> bool:
    """Save one document. Not built, so this refuses rather than press or
    fetch anything."""
    raise NotBuilt("a statement's PDF")


# ---------------------------------------------------------------------------
# Diagnose survey. Read-only and on the page the person left open. Nothing
# is followed, pressed or downloaded, no screenshot is taken, and every word
# goes through the redactor and then the word list that writes the file.
# ---------------------------------------------------------------------------
def _page_summary(page) -> dict:
    out = {"url": "", "title": ""}
    try:
        url = page.url or ""
        out["on_site"] = is_safe_url(url)
        # The path only. A query string or a fragment can carry a session
        # or an account's id.
        out["url"] = (redact(re.split(r"[?#]", url, maxsplit=1)[0]) if out["on_site"]
                      else "(not on bankofamerica.com)")
    except Exception:
        out["on_site"] = False
    if not out["on_site"]:
        # Nothing is read off a page of another site.
        return out
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 80)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                controls.append({"role": role, "text": redact(text)[:60],
                                 "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    try:
        out["password_fields"] = page.locator("input[type='password']").count()
    except Exception:
        pass
    return out


def survey(page, dwell_ms: int = 2000) -> dict:
    """What the page the person left open looks like, without following,
    pressing or downloading anything."""
    report = {"pages": [], "responses": [], "mapped": False}
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:
        pass
    report["pages"].append(_page_summary(page))
    return report
