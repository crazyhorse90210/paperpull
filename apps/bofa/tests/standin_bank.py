"""A stand-in for Bank of America's statements page, for the tests.

The page answers as the two recordings on #121 showed it. Reloading the
statements page makes one list call, a POST whose answer holds a
documentList, an accountList, a documentCategoryList and a yearList, and
the page draws a "Download PDF for ..." link for each row it lists. Asking
the list from inside the page and asking for a PDF are answered by
`answer_list` and `answer_pdf`, which a test can replace.

Every value is invented. The account keys, the docIds, the account names
and every address are made up, and the list's address is not the bank's,
whose words the recordings kept only as shapes.
"""
import base64
import json

LIST_URL = "https://secure.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments"
PAGE_URL = "https://secure.bankofamerica.com/sample-zz-stmts-docs/?k=STANDINTOKEN&request_locale=en-us"
LINK_BASE = "https://secure.bankofamerica.com/sample/getpdf?doc="

# The name the body and the lists give an account by. The bank's own name
# for it is not in the recordings, so it is made up here.
KEY = "acctToken"

ACCOUNTS = [
    {KEY: "K-ALPHA-0001", "accountDisplayName": "Everyday Checking", "productCode": "PC1",
     "productSubCode": "S1", "groupCode": "DDA", "selected": True},
    {KEY: "K-BRAVO-0002", "accountDisplayName": "Travel Card", "productCode": "PC2",
     "productSubCode": "S2", "groupCode": "CCA", "selected": False},
]
CATEGORIES = [
    {"docCategoryName": "Statements", "docCategoryId": "CAT-STMT", "colorCode": "x", "isDownloadOnly": False},
    {"docCategoryName": "Tax Documents", "docCategoryId": "CAT-TAX", "colorCode": "y", "isDownloadOnly": False},
]
YEARS = ["2026", "2025"]


def row(doc_id, account, date, title="January Statement", category="CAT-STMT", date_string=None):
    return {"insertList": [], "docTypeId": "T1", "docId": doc_id, "docDisplayName": title,
            "productCode": account["productCode"], "source": "S", KEY: account[KEY],
            "accountDisplayName": account["accountDisplayName"], "docCategory": "Statements",
            "docCategoryId": category, "date": date,
            "dateString": date_string if date_string is not None else "",
            "isDownloadOnly": False}


# Each account's statements by year.
STATEMENTS = {
    ("K-ALPHA-0001", "2026"): [row("DOC000000000101", ACCOUNTS[0], "2026-01-15"),
                               row("DOC000000000102", ACCOUNTS[0], "2026-02-15", "February Statement")],
    ("K-ALPHA-0001", "2025"): [row("DOC000000000091", ACCOUNTS[0], "2025-12-15", "December Statement")],
    ("K-BRAVO-0002", "2026"): [row("DOC000000000201", ACCOUNTS[1], "2026-01-15")],
    ("K-BRAVO-0002", "2025"): [],
}


def answer(rows, accounts=None):
    return {"documentList": rows, "accountList": accounts if accounts is not None else ACCOUNTS,
            "documentCategoryList": CATEGORIES, "yearList": YEARS, "errorInfo": [],
            "status": "SUCCESS"}


class Request:
    def __init__(self, url, body, method="POST", headers=None):
        self.url = url
        self.method = method
        self.post_data_json = body
        self.headers = headers or {}

    def all_headers(self):
        return dict(self.headers)


class Response:
    def __init__(self, request, status, body):
        self.request = request
        self.status = status
        self._body = json.dumps(body).encode()
        self.headers = {"content-type": "application/json"}

    def body(self):
        return self._body


PRESSES = {"click", "dblclick", "tap", "check", "uncheck", "set_checked", "fill", "type",
           "press", "select_option", "dispatch_event", "set_input_files"}


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
        return self.n

    def nth(self, i):
        return Locator(self.page, self.selector, 1, self.text)

    def inner_text(self, timeout=None):
        return self.text

    def all_inner_texts(self):
        return [self.text] if self.text else []

    def get_attribute(self, name):
        return ""


class Bank:
    """The statements page in a tab. `listed` is what the page's own call
    answers on a reload, `links` the PDF links it then draws."""

    def __init__(self, url=PAGE_URL, password=0, text="Statements & Documents"):
        self.url = url
        self.password = password
        self.text = text
        self.asked = []          # every press and navigation, which a test reads
        self.lists = []          # every list asked for from inside the page
        self.pdfs = []           # every PDF asked for from inside the page
        self.listeners = []
        self.reloads = 0
        self.first_body = {KEY: "K-ALPHA-0001", "docCategoryId": "CAT-STMT", "lang": "en", "year": "2026"}
        self.first_status = 200
        self.first_url = LIST_URL
        self.headers = {"content-type": "application/json", "x-standin-csrf": "TOKEN-T",
                        "cookie": "SESSION=secret", "user-agent": "UA", "sec-fetch-mode": "cors"}
        self.listed = answer(STATEMENTS[("K-ALPHA-0001", "2026")])
        self.links = None        # None draws one link per listed row
        self.pdf_status = 200
        self.pdf_final_url = None
        self.pdf_disposition = 'attachment; filename="eStmt_%s.pdf"'
        self.pdf_bytes = b"%PDF-1.4 stand-in"
        # Given, the PDF each statement's address answers with, from its row.
        self.pdf_maker = None
        self.list_status = 200
        # Given, what an asked-for answer says of itself, from its body.
        self.years_for = None        # -> its yearList
        self.status_for = None       # -> its status
        self.errors_for = None       # -> its errorInfo
        # Given, an exception the page raises for an asked-for list or PDF.
        self.list_raises = None
        self.pdf_raises = None

    # -- what the page does ------------------------------------------------
    def __getattr__(self, name):
        if name in PRESSES:
            def press(*a, **k):
                self.asked.append((name, a))
            return press
        raise AttributeError(name)

    def is_closed(self):
        return False

    def title(self):
        return "Statements & Documents"

    def locator(self, selector):
        if "password" in selector:
            return Locator(self, selector, self.password)
        if selector == "body":
            return Locator(self, selector, 1, self.text)
        return Locator(self, selector, 1, "Statements")

    def get_by_role(self, role, **k):
        return Locator(self, role, 1, "Download PDF for January Statement for Everyday Checking")

    def on(self, event, fn):
        if event == "response":
            self.listeners.append(fn)

    def remove_listener(self, event, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, **k):
        self.asked.append(("goto", url))
        self.url = url

    def reload(self, **k):
        self.asked.append(("reload", self.url))
        self.reloads += 1
        req = Request(self.first_url, self.first_body, headers=self.headers)
        for fn in list(self.listeners):
            fn(Response(req, self.first_status, self.listed))

    def drawn_links(self):
        if self.links is not None:
            return self.links
        return [{"name": "Download PDF for %s for %s" % (r["docDisplayName"], r["accountDisplayName"]),
                 "href": LINK_BASE + r["docId"]} for r in self.listed.get("documentList") or []]

    def evaluate(self, js, arg=None):
        if "Download PDF for" in js:
            return self.drawn_links()
        if "method: 'POST'" in js:
            url, headers, body = arg
            self.lists.append({"url": url, "headers": headers, "body": body})
            if self.list_raises is not None:
                raise self.list_raises
            if self.list_status != 200:
                return {"status": self.list_status, "url": url, "json": None}
            got = answer(self.answer_list(body))
            if self.years_for:
                got["yearList"] = self.years_for(body)
            if self.status_for:
                got["status"] = self.status_for(body)
            if self.errors_for:
                got["errorInfo"] = self.errors_for(body)
            return {"status": 200, "url": url, "json": got}
        if "content-disposition" in js:
            self.pdfs.append(arg)
            if self.pdf_raises is not None:
                raise self.pdf_raises
            final = self.pdf_final_url or arg
            if self.pdf_status != 200:
                return {"status": self.pdf_status, "url": final, "ct": "text/html", "cd": "", "b64": ""}
            day = self.day_of(arg)
            data = self.pdf_maker(self.row_of(arg)) if self.pdf_maker else self.pdf_bytes
            return {"status": 200, "url": final, "ct": "application/pdf",
                    "cd": self.pdf_disposition % day if "%s" in self.pdf_disposition else self.pdf_disposition,
                    "b64": base64.b64encode(data).decode()}
        raise AssertionError("a snippet the stand-in does not know")

    # -- what the bank answers ---------------------------------------------
    def answer_list(self, body):
        return list(STATEMENTS.get((body.get(KEY), body.get("year")), []))

    def row_of(self, url):
        for rows in STATEMENTS.values():
            for r in rows:
                if url.endswith(r["docId"]):
                    return r
        return {}

    def day_of(self, url):
        return self.row_of(url).get("date") or "2000-01-01"
