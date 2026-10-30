"""ALL portlandgeneral.com selectors, URLs, and page behavior live here.

When Portland General Electric changes its site, repair this file only.

STATUS: built and run 2026-10-29 on a real account, with nothing pressed
by the app. Discover listed 36 bills over every page of the history, and a
Pilot saved the newest, byte for byte the PDF the page's own Detailed Bill
link gives.

SEEN SIGNED IN, 2026-10-29 (shapes only, no values kept):

  * The bill list is Billing & Payment History,
    https://portlandgeneral.com/secure/payment/billing-payment-history, a
    Gatsby page whose account data all comes from api.portlandgeneral.com.
  * Its rows come from POST /pge-graphql, operationName getAccountDetails,
    variables {params: {accountNumberList: [{accountNumber,
    encryptedPersonId}]}, paymentHistoryParams: {pagingParams: {limit,
    offset}}}. The answer's data.getAccountDetails[0].paymentHistory holds
    paymentHistoryDetails, rows of {date (ISO), amountDue, amountPaid,
    encryptedBillId, billingPeriodStartDate, billingPeriodEndDate, kwh,
    type}, where type is "Bill" or "Payment", and totalDetailsRecords for
    paging. 15 rows on the first page seen.
  * Each bill row offers two links, "Simplified Bill (PDF)" and "Detailed
    Bill (PDF)", both href="#". Pressing one sends POST
    /pge-bill-api/pdf/bills with JSON {encryptedBillId, isSummary,
    isNonDetailed}, and the browser saves the PDF as a download. No new tab
    opens and the page does not navigate.
  * The API is authorized by an `authorization` header (and an
    aws_graphql_server header) the page adds, not by cookies. A run takes
    the list from the page's own getAccountDetails answer, asks further
    pages with the page's own query and those two headers, and asks
    /pge-bill-api/pdf/bills for each bill with {isSummary: false,
    isNonDetailed: false}, the Detailed Bill. The header values stay in
    memory and are never written.

Sign-in, with any verification code, is the account holder's own, in the
browser.

SAFETY (a utility account that can pay, enroll and start or stop service):
  This module is strictly READ-ONLY. It must NEVER activate any control that
  pays, sets up autopay, Equal Pay or a payment arrangement, adds a bank
  account, changes a pricing plan (Time of Day and the like), enrolls in
  paperless, Green Future, Peak Time Rebates, Smart Battery or any other
  program, starts, stops or moves service, changes notifications, or signs
  out. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO match one of
  the anchored document actions (SAFE_DOC_CONTROL_RES), and the shared core
  guards are consulted every time.
"""
from __future__ import annotations

import logging
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("portlandgeneral_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Portland General Electric", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://portlandgeneral.com"
PORTAL = f"{BASE}/portal"
DOCUMENTS_PATH = "/secure/payment/billing-payment-history"  # seen signed in, 2026-10-29
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
# The account API the signed-in pages ask. Its list and its PDFs are asked
# from inside the page, with the page's own authorization header.
API = "https://api.portlandgeneral.com"
GRAPHQL_URL = API + "/pge-graphql"
HISTORY_OPERATION = "getAccountDetails"
PDF_URL = API + "/pge-bill-api/pdf/bills"
# What discovery records as every bill's href. The bill itself is named by
# an encryptedBillId the API issues afresh with each answer, so it is never
# kept: the bill is found again by its date when it is fetched.
DOWNLOAD_PATH = "/pge-bill-api/pdf/bills"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    # NOT YET MAPPED: the site's home page, where the account holder signs
    # in, until a recording shows where the account pages live.
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/prelogin/", "/accounts/logout", "/account/login", "/login"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a utility portal. Every stem anchored so
# "Bill" is not "billing plan" and "Download" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bpay\s*now\b|\bautopay\b|\bauto\s*-?\s*pay\b|\btext\s+to\s+pay\b|"
    r"\bguest\s+pay\b|\bbank|\barrangements?\b|\blevel\s+pay\b|\bbudget\s+billing\b|\bpricing\s+plans?\b|"
    r"\brate\s+plans?\b|\bbilling\s+plans?\b|\bchange\s+plan\b|\bpaperless\b|\benroll|\bunenroll|\bsign\s*up\b|"
    r"\bregist(er|ration)\b|\bstart\s+service\b|\bstop\s+service\b|\bmove\s+service\b|\bmove\s*-?\s*(in|out)\b|"
    r"\btransfer|\bnotifications?\b|\bsign\s*(out|off)\b|\blog\s*(out|off)\b|\blogout\b|\bletters?\b|"
    r"\bexcel\b|\bexport\b|\bcsv\b|\bhistory\b|\bextension\b|\bwallet\b|\bschedul(e|es|ed|ing)\b|\bdonat|"
    r"\bprograms?\b|\bprofile\b|\bsettings?\b|\bpreferences?\b|\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|"
    r"\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bmanage\b|\bturn\s+(on|off)\b|\bopt\s*-?\s*(in|out)\b|\bclose\b|\bupload\b|"
    r"\bemail\b|\bshare\b|\bchat\b|\bcontact\b|\brequest(s|ed|ing)?\b|\boutages?\b|\bbuy\b|\bsell\b|\border\b|"
    r"\bdeposit|\bwithdraw|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bverify\b|\bpassword\b|\busername\b|"
    r"\bequal\s+pay\b|\btime\s+of\s+day\b|\bgreen\s+future\b|\bpeak\s+time\b|\bsmart\s+battery\b|"
    r"\bsmart\s+thermostat\b|\brebates?\b|\bclean\s+wind\b|"
    r"\brebalance\b|\bliquidate\b|\bdetails\b)", re.I)

# The document actions this app would ever accept, anchored whole: the
# portal's own "View Your Detailed Bill PDF", "Download Your Solar Bill" and
# "View Bill", and the "View Utility Bill" its rules name. Nothing looser,
# so a label carrying anything more is refused.
# The two links each bill row offers. This app presses neither; they are
# named here for the survey's verdicts.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^(simplified|detailed)\s+bill\s+\(pdf\)$", re.I),
    re.compile(r"^view\s+bill\s+online$", re.I),
    re.compile(r"^(view|download)\s+(your\s+)?(detailed\s+)?(utility\s+)?bill(\s+\(?pdf\)?)?$", re.I),
)

BILL_CONTROL_RE = re.compile(r"^\s*(simplified|detailed)\s+bill\s+\(pdf\)\s*$", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "7-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# A bill's row on Billing History, and the table plugin's own cell for a
# table with no rows.
# For Diagnose's counts only: the bill links the page draws, two per bill.
BILL_ROW = "a[href$='#']"

FALLBACK = {
    "doc_row": BILL_ROW,
    "page_ready": "main",
}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "mdY":
                return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash2":
                return f"{_full_year(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


# A bill row's statement date, exactly as the table writes it: "Sep 12, 2026".
_STATEMENT_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+([0-9]{1,2}),\s+([0-9]{4})")
# The words that head the column that date is read from. A header holding
# both, as "Statement Date" or "Statement Date *" does, and "Due Date" does
# not, since the live header has only been named, never seen whole.
STATEMENT_HEAD_WORDS = frozenset({"statement", "date"})


def statement_date(text) -> Optional[str]:
    """A bill row's statement date as YYYY-MM-DD, or None. The whole cell
    must be the date and the day must exist; nothing is found inside other
    text."""
    m = _STATEMENT_DATE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """portlandgeneral.com answered as a signed-out session: its sign-in page,
    a redirect where a bill was asked for, a 401, or an HTML or JSON body
    where a PDF was expected. The run stops for the account holder."""


def looks_signed_out(page) -> bool:
    """The sign-in page by its address or a password field. A page whose
    address cannot be read raises, and is never called signed in."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page that shows a bill row is not a challenge,
    whatever its text says further down."""
    try:
        if page.get_by_role("link", name=BILL_CONTROL_RE).count() > 0:
            return None
    except Exception:
        pass
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:1500]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the anchored
    document actions."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return any(rx.match(name) for rx in SAFE_DOC_CONTROL_RES)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard, and a bill only from the one
# PDF address.
# ---------------------------------------------------------------------------
# The site and the account API its signed-in pages fetch from (seen
# 2026-10-29). Exact hosts only; analytics and cookie hosts are not allowed.
ALLOWED_HOSTS = {"portlandgeneral.com", "api.portlandgeneral.com"}
BILL_ID_RE = re.compile(r"bill-[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ISO_DAY_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?:T.*)?")
# The page asks for fifteen rows at a time. A history this many pages long
# is not a billing history, so the walk stops rather than run on.
MAX_PAGES = 60
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
# The only request headers taken from the page's own call. The values live
# in memory for one run and are never written, logged or printed.
_CARRIED_HEADERS = ("authorization", "aws_graphql_server")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly portlandgeneral.com or
    api.portlandgeneral.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_download_url(url: str) -> bool:
    """True only for the one address a bill is asked from."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.netloc == "api.portlandgeneral.com" and parts.path == DOWNLOAD_PATH
            and not parts.query and not parts.fragment)


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    document_id: str = ""
    # The API's id for this bill in the answer it came from. Valid only
    # with that answer's authorization, so it is never recorded.
    bill_ref: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


@dataclass
class _History:
    """The page's own history request, and what the API answered to it."""
    body: dict
    headers: dict
    answer: dict


def is_history_request(method: str, url: str, post_data: Optional[str]) -> bool:
    """Whether a request is the page's own billing-history query: a POST to
    exactly the GraphQL address, operation getAccountDetails, with paging
    variables for the payment history, and a query, never a mutation."""
    if (method or "").upper() != "POST" or url != GRAPHQL_URL:
        return False
    try:
        body = json.loads(post_data or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(body, dict) or body.get("operationName") != HISTORY_OPERATION:
        return False
    variables = body.get("variables")
    paging = (variables or {}).get("paymentHistoryParams") if isinstance(variables, dict) else None
    query = str(body.get("query") or "").lstrip()
    return (isinstance(paging, dict) and isinstance(paging.get("pagingParams"), dict)
            and query.startswith("query ") and "mutation" not in query.split("{", 1)[0].lower())


def _carried(headers: dict) -> dict:
    return {k: v for k, v in (headers or {}).items() if k.lower() in _CARRIED_HEADERS and v}


def _settled_here(page) -> bool:
    """Whether the tab is at Billing & Payment History's own address."""
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == DOCUMENTS_PATH
    except ValueError:
        return False


def _open(page, timeout_ms: int = 45000) -> _History:
    """Open Billing & Payment History by its address and take the history
    query the page itself sends, and the API's answer to it. Raises
    SessionExpired when the site shows its sign-in page or the API refuses
    the session, and ListStopped when the page never asks. Nothing is
    pressed."""
    got = []

    def seen(resp):
        try:
            if not got and is_history_request(resp.request.method, resp.url, resp.request.post_data):
                got.append(resp)
        except Exception:
            pass

    page.on("response", seen)
    try:
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening Billing & Payment History failed (%s)", type(e).__name__)
        waited = 0
        while not got and waited < timeout_ms:
            page.wait_for_timeout(250)
            waited += 250
    finally:
        try:
            page.remove_listener("response", seen)
        except Exception:
            pass
    if not got:
        if looks_signed_out(page):
            raise SessionExpired("portlandgeneral.com showed its sign-in page")
        raise ListStopped("Billing & Payment History did not ask for its list")
    resp = got[0]
    if looks_signed_out(page):
        raise SessionExpired("portlandgeneral.com showed its sign-in page")
    if not _settled_here(page):
        raise ListStopped("Billing & Payment History settled off its own address")
    if resp.status in (401, 403):
        raise SessionExpired("the account API refused the session")
    if resp.status != 200:
        raise ListStopped(f"the account API answered the list with {resp.status}")
    try:
        answer = intake.json_of(resp, MAX_LIST_BYTES)
        body = json.loads(resp.request.post_data or "")
        headers = _carried(resp.request.all_headers())
    except intake.TooLarge:
        raise ListStopped("the billing history answer is larger than any history")
    except Exception as e:
        raise ListStopped(f"the billing history answer could not be read ({type(e).__name__})")
    if not headers.get("authorization"):
        raise ListStopped("the page's own list request carried no authorization")
    _keep_private(answer)
    return _History(body=body, headers=headers, answer=answer)


_PRIVATE_FIELDS = ("accountNumber", "mainCustomerName", "coCustomerNames", "description",
                   "addressLine1", "addressLine2", "city", "postal")


def _keep_private(answer) -> None:
    """Register what names the account in the answer, its number, the
    customers' names and the service address, as private words, part by
    part, so nothing said or written by the run carries them. A part of
    four letters or more, or one with a digit: "OR" or "St" would turn
    "ORDER" and "Statement" into "[name]" in every diagnostic."""
    found = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in _PRIVATE_FIELDS:
            found.append(v)

    walk(((answer or {}).get("data") or {}).get(HISTORY_OPERATION))
    parts = {part for w in found for part in re.split(r"[\s,.#/-]+", w)
             if len(part) >= 4 or re.search(r"[0-9]", part)}
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))


def _errors_say_signed_out(answer) -> bool:
    for err in (answer or {}).get("errors") or []:
        text = json.dumps(err).lower() if not isinstance(err, str) else err.lower()
        if any(w in text for w in ("unauthori", "unauthenticat", "expired", "forbidden", "401")):
            return True
    return False


def history_page(answer) -> Tuple[list, int]:
    """The payment-history rows of one answer and the total the API says
    there are. One account only: an answer for none or several stops the
    list, since a bill's file is named by its date alone."""
    if not isinstance(answer, dict):
        raise ListStopped("the billing history answer is not an object")
    if answer.get("errors"):
        if _errors_say_signed_out(answer):
            raise SessionExpired("the account API said the session has ended")
        raise ListStopped("the account API answered the list with errors")
    accounts = ((answer.get("data") or {}).get(HISTORY_OPERATION))
    if not isinstance(accounts, list):
        raise ListStopped("the billing history answer holds no account")
    if len(accounts) != 1:
        raise ListStopped(f"the billing history answer holds {len(accounts)} accounts, and this app reads one")
    history = (accounts[0] or {}).get("paymentHistory")
    if not isinstance(history, dict):
        raise ListStopped("the account holds no payment history")
    rows = history.get("paymentHistoryDetails")
    total = history.get("totalDetailsRecords")
    if not isinstance(rows, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ListStopped("the payment history's rows or total could not be read")
    return rows, total


def bill_day(text) -> Optional[str]:
    """A row's date, as the API writes it ("2026-09-30T00:00:00.000Z"),
    as YYYY-MM-DD, or None when it is not a calendar date."""
    m = _ISO_DAY_RE.fullmatch(str(text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def bills_of(rows: list) -> List[RawDoc]:
    """RawDocs from the history rows, one per row of type "Bill". Payments
    are not documents and are passed over. A bill row with no id, a date
    that is not a calendar date, or two bills of one date stops the list,
    carrying what was read before it, since a bill is found again by its
    date. Nothing from the row but its date goes into what is said."""
    docs: List[RawDoc] = []
    dates = set()
    for r in rows or []:
        if not isinstance(r, dict):
            raise ListStopped("a payment history row is not an object", docs)
        if r.get("type") != "Bill":
            continue
        ref = r.get("encryptedBillId")
        if not isinstance(ref, str) or not ref.strip():
            raise ListStopped("a bill row carries no bill id", docs)
        iso = bill_day(r.get("date"))
        if not iso:
            raise ListStopped("a bill's date is not a calendar date", docs)
        if iso in dates:
            raise ListStopped("two bills carry one date", docs)
        dates.add(iso)
        title = f"Portland General Electric Bill {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=DOWNLOAD_PATH, text=title,
                           row_index=len(docs), kind="statement",
                           document_id=f"bill-{iso}", bill_ref=ref.strip()))
    return docs


_ASK_JS = r"""async ([url, headers, body]) => {
  let r;
  try {
    r = await fetch(url, {method: 'POST', credentials: 'omit', redirect: 'manual',
                          headers: Object.assign({'content-type': 'application/json'}, headers),
                          body: JSON.stringify(body)});
  } catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  let data = null;
  try { data = await ppJson(r); } catch (e) { if (ppRefused(e)) throw e; data = null; }
  return {status: r.status, data: data};
}"""


def _ask_page(page, history: _History, offset: int) -> dict:
    """The history page at `offset`, asked from inside the signed-in page
    with the page's own query and headers, only the offset changed."""
    body = json.loads(json.dumps(history.body))
    body["variables"]["paymentHistoryParams"]["pagingParams"]["offset"] = offset
    if not is_history_request("POST", GRAPHQL_URL, json.dumps(body)):
        raise ListStopped("refusing a history request that is not the page's own")
    try:
        got = intake.evaluate(page, _ASK_JS, [GRAPHQL_URL, history.headers, body], limit=MAX_LIST_BYTES)
    except intake.TooLarge:
        raise ListStopped("a billing history page is larger than any history")
    got = got or {}
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the account API refused the session")
    if got.get("status") != 200 or not isinstance(got.get("data"), dict):
        raise ListStopped(f"a billing history page was answered with {got.get('status')}")
    return got["data"]


def _all_bills(page, history: _History) -> List[RawDoc]:
    rows, total = history_page(history.answer)
    paging = history.body["variables"]["paymentHistoryParams"]["pagingParams"]
    limit = paging.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ListStopped("the page's own request has no page size")
    every = list(rows)
    pages = 1
    while len(every) < total:
        if pages >= MAX_PAGES:
            raise ListStopped(f"the billing history ran past {MAX_PAGES} pages", bills_of(every))
        more, again = history_page(_ask_page(page, history, len(every)))
        if again != total:
            raise ListStopped("the billing history's total changed while it was read", bills_of(every))
        if not more:
            raise ListStopped(f"the billing history holds {total} rows and {len(every)} were given",
                              bills_of(every))
        every.extend(more)
        pages += 1
    if len(every) != total:
        raise ListStopped(f"the billing history holds {total} rows and {len(every)} were given",
                          bills_of(every))
    return bills_of(every)


def goto_documents(page) -> bool:
    """Open Billing & Payment History and take its list. False when it
    showed the sign-in page, settled elsewhere, or never asked."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Billing & Payment History did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether the billing history opened and could be read whole, which
    only a signed-in page allows."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the billing history could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the list is the API's answer, read whole."""
    return None


def table_header(page) -> dict:
    """For Diagnose. There is no bill table to read a header from."""
    return {"cells": [], "statement_date_column": None}


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill in the billing history, every page of it. Nothing is
    pressed. A list that cannot be read whole raises ListStopped holding
    what was read, and a signed-out session raises SessionExpired."""
    return _all_bills(page, _open(page))


_PDF_JS = r"""async ([url, headers, body, limit]) => {
  let r;
  try {
    r = await fetch(url, {method: 'POST', credentials: 'omit', redirect: 'manual',
                          headers: Object.assign({'content-type': 'application/json'}, headers),
                          body: JSON.stringify(body)});
  } catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  const type = r.headers.get('content-type') || '';
  if (r.status !== 200) return {status: r.status, type: type};
  const buf = await ppRead(r);
  if (buf.length > limit) return {status: r.status, type: type, too_big: true};
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, type: type, b64: btoa(s)};
}"""


def _fetch(page, history: _History, bill: RawDoc, out_path: Path, trace: Optional[list]) -> bool:
    """Ask the API for the bill's detailed PDF the way the page's own
    "Detailed Bill (PDF)" link does, from inside the page with its own
    headers, and keep it only when the body is a PDF. A refusal or a JSON or
    HTML body is the API saying the session has ended."""
    if not is_download_url(PDF_URL):
        return False
    body = {"encryptedBillId": bill.bill_ref, "isSummary": False, "isNonDetailed": False}
    try:
        got = intake.evaluate(page, _PDF_JS, [PDF_URL, history.headers, body, MAX_PDF_BYTES],
                              limit=MAX_PDF_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = str(got.get("type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": "api.portlandgeneral.com",
                      "status": got.get("status"), "type": ctype[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the account API refused the session")
    if got.get("status") != 200 or not got.get("b64"):
        return False
    try:
        data = intake.decode(got["b64"], validate=True, limit=MAX_PDF_BYTES)
    except Exception:
        return False
    if data[:5] != b"%PDF-":
        if data.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("the account API answered a bill with a sign-in body")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded for `iso_date`. The billing history
    is opened again, since the API's bill ids are issued afresh with each
    answer, and the bill is fetched only when exactly one bill there carries
    that date. `dl_dir` is unused: nothing goes through the browser's
    downloads. Nothing is pressed. SessionExpired propagates to the run."""
    out_path = Path(out_path)
    if href != DOWNLOAD_PATH or not BILL_ID_RE.fullmatch(document_id or "") \
            or document_id != f"bill-{iso_date}":
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    try:
        history = _open(page)
        found = [d for d in _all_bills(page, history) if d.date_text == iso_date]
    except ListStopped as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        return False
    if len(found) != 1:
        log.info("%d bills match the recorded date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single bill matches the record", "matches": len(found)})
        return False
    return _fetch(page, history, found[0], out_path, trace)


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in page.
# No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(billing\s+history|view\s+bill\s+history)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose, digits masked."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact(r.get("href", "") or "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    docs.sort(key=lambda d: 0 if d.date_text else 1)
    return docs


def _page_summary(page) -> dict:
    out = {"url": redact(page.url or ""), "title": ""}
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
            for i in range(min(loc.count(), 100)):
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
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                controls.append({"role": role, "text": redact(text)[:60],
                                 "href": redact(href)[:120],
                                 "safe": is_safe_control(text),
                                 "bill": bool(BILL_CONTROL_RE.search(text)),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    out["bill_controls"] = sum(1 for c in controls if c["bill"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in page looks like, without downloading anything.
    Records the page's headings and controls with the guard's verdict.
    Follows nothing and listens to nothing, since this app presses no
    control at all and a survey is not a reason to start. No screenshot."""
    report = {"pages": []}
    page.wait_for_timeout(dwell_ms)
    report["pages"].append(_page_summary(page))
    return report
