"""Which of the provider's own calls happened, and what came back.

Eleven of the forty eight apps drive a JSON API rather than a page. They
declare no selectors, so the selector census has nothing to say about
them and a failure file from one of them carries a page state and little
else. This is their half.

It listens rather than asking. Every response the page receives goes
past a Playwright listener, so it works whatever way an app makes its
call, an in-page fetch, a navigation, or a request the site's own
JavaScript made, and no app has to change how it calls anything.

WHAT COMES OUT

    the path       with anything id-shaped in it masked
    the method     GET, POST
    the status     404 is a different problem from 200 with nothing in it
    the kind       json, html, pdf
    the query      the names of the parameters, never their values
    the shape      the keys of a JSON answer, and the type of each value

THE SHAPE IS THE POINT, AND IT IS THE RISK

A maintainer repairing one of these apps needs the field names, because
an API that renamed `documents` to `items` looks from outside exactly
like an account with nothing in it. Those names are the provider's
schema, the same for every customer, so they carry nothing about whose
account it is.

Except when they do. An object keyed by account number is a thing that
exists, and there the keys *are* values. A key or a path segment used to
be masked when it looked like an identifier, a long run of digits, a hex
blob, two digits in a long token. An account's id made mostly of
letters looks like none of those. So every key and every segment is a
word on the fixed list in paperpull_core.words or leaves as its shape, a
for a letter and 9 for a digit, and no value is ever kept, only the name
of its type.

WHAT NEVER COMES OUT

No body, no header, no cookie, no query value, no host other than
whether it was the provider's. A response from anywhere but the
provider is counted and not described, because an advertiser's URL on a
bank's page is still a record of what somebody was doing.
"""
from __future__ import annotations

import re

from .characters import whole_json
from .failure import _count, _enum
from .words import Fixed, shape

# What a body is, as a word.
_KINDS = (("json", ("json",)), ("pdf", ("pdf",)), ("html", ("html",)),
          ("xml", ("xml",)), ("text", ("text/plain",)),
          ("image", ("image/",)), ("stream", ("octet-stream",)))

_METHODS = frozenset(("get", "post", "put", "patch", "delete", "head",
                      "options"))

MAX_SEEN = 24          # entries kept, newest wins
MAX_BODIES = 30        # bodies read in one run, because each is a round trip
MAX_BODY_BYTES = 2_000_000
MAX_KEYS = 30
MAX_DEPTH = 4


def mask_token(token: str) -> str:
    """One path segment or key, its words on the list kept and the rest
    written as their shape. A path like /accounts/12345678/documents is
    structure and an account number in one breath, and the structure is
    the only half worth having, so it leaves as /accounts/99999999/documents."""
    return shape(str(token or ""), collapse=False)[:40]


def path_shape(url: str) -> str:
    """The path, every part of it a word on the list or its shape."""
    from urllib.parse import unquote, urlsplit
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return ""
    parts = [mask_token(unquote(p)) for p in path.split("/") if p]
    return "/" + "/".join(parts[:12])


def query_keys(url: str) -> list:
    """The names of the parameters, never their values.

    A repair needs to know a call takes a year and a page. What year
    this person asked for is theirs."""
    from urllib.parse import parse_qsl, urlsplit
    try:
        pairs = parse_qsl(urlsplit(url or "").query, keep_blank_values=True)
    except ValueError:
        return []
    return sorted({mask_token(k)[:40] for k, _ in pairs})[:20]


def kind_of(content_type: str) -> str:
    ct = (content_type or "").lower()
    for word, needles in _KINDS:
        if any(n in ct for n in needles):
            return word
    return "other"


def shape_of(value, depth: int = 0):
    """The keys of a JSON answer and the type of each value.

    Never a value. A list becomes its length and the shape of its first
    entry, because a hundred documents have the same shape as one and
    the count is the part worth knowing."""
    if depth > MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:MAX_KEYS]:
            key = mask_token(k)
            # Keys of one shape stay apart, so forty account numbers read
            # as forty keys rather than one.
            while key in out:
                key += "+"
            out[key] = shape_of(v, depth + 1)
        if len(value) > MAX_KEYS:
            out["..."] = Fixed("%d more key(s)" % (len(value) - MAX_KEYS))
        return out
    if isinstance(value, list):
        # Fixed, since the count is ours to say and would otherwise leave
        # as the shape of its digits like any other.
        return [Fixed("%d item(s)" % len(value)),
                shape_of(value[0], depth + 1) if value else None]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        # Its length is a fact about the answer's shape. Its content is
        # a fact about the account.
        return "string"
    return type(value).__name__


class Requests:
    """Every call the provider answered, as shapes and counts.

        seen = Requests(page, site.is_safe_url)
        seen.start()
        ...
        report["requests"] = seen.report()

    Nothing here may raise. It runs through an ordinary working run."""

    def __init__(self, page, is_safe_url=None, limit: int = MAX_SEEN):
        self.page = page
        self.limit = max(4, int(limit))
        self.seen: list = []
        self.counts = {"provider": 0, "elsewhere": 0, "bodies_read": 0,
                       "too_large": 0, "unreadable": 0}
        self._is_safe = is_safe_url or (lambda u: True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            self.page.on("response", self._on_response)
            self._started = True
        except Exception:
            pass

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception:
            pass
        self._started = False

    def _on_response(self, response) -> None:
        """Guarded whole. An exception here surfaces inside Playwright's
        event loop and would take a working run down with it."""
        try:
            self._record(response)
        except Exception:
            self.counts["unreadable"] = self.counts.get("unreadable", 0) + 1

    def _record(self, response) -> None:
        url = response.url or ""
        try:
            safe = bool(self._is_safe(url))
        except Exception:
            safe = False
        if not safe:
            # Counted, never described. An advertiser's address on a
            # bank's page is still a record of what somebody was doing.
            self.counts["elsewhere"] += 1
            return
        self.counts["provider"] += 1

        headers = {}
        try:
            headers = response.headers or {}
        except Exception:
            pass
        kind = kind_of(headers.get("content-type", ""))
        entry = {
            "path": path_shape(url)[:200],
            "status": _count(response.status),
            "kind": kind,
        }
        try:
            entry["method"] = _enum(response.request.method, _METHODS, "other")
        except Exception:
            entry["method"] = "other"
        keys = query_keys(url)
        if keys:
            entry["query_keys"] = keys
        try:
            size = int(headers.get("content-length") or 0)
        except (TypeError, ValueError):
            size = 0
        if size:
            entry["bytes"] = _count(size)

        if kind == "json" and self.counts["bodies_read"] < MAX_BODIES:
            if size > MAX_BODY_BYTES:
                self.counts["too_large"] += 1
                entry["shape"] = Fixed("not read, %d bytes" % _count(size))
            else:
                # A round trip to the browser, which is why it is capped.
                try:
                    entry["shape"] = shape_of(whole_json(response.json()))
                    self.counts["bodies_read"] += 1
                except Exception:
                    self.counts["unreadable"] += 1
                    entry["shape"] = "unreadable"

        self.seen.append(entry)
        while len(self.seen) > self.limit:
            self.seen.pop(0)

    def report(self) -> dict:
        return {"seen": list(self.seen), "counts": dict(self.counts),
                "limit": self.limit}


def summarize(report: dict) -> list:
    """What a reader should notice, in sentences.

    It reads a failure file back, which a person may have edited or a
    disk cut short, so a field of the wrong type is read as missing and
    never raises. A raise here would take every other sentence of the
    file's summary with it."""
    said = []
    if not isinstance(report, dict):
        return said
    seen = report.get("seen")
    seen = [e for e in seen if isinstance(e, dict)] if isinstance(seen, list) else []
    counts = report.get("counts")
    if not isinstance(counts, dict):
        # Nobody watched, which is not the same as having watched and
        # seen nothing, and only one of those is worth a sentence.
        return said

    if not _count(counts.get("provider")):
        elsewhere = _count(counts.get("elsewhere"))
        if elsewhere:
            said.append("The page made %d request(s) and not one of them went "
                        "to the provider, so either the app never asked or it "
                        "asked somewhere this app does not recognize as the "
                        "provider's own." % elsewhere)
        else:
            said.append("The page made no requests at all while this ran.")
        return said

    bad = [e for e in seen if 400 <= _status(e) < 600]
    for e in bad[:4]:
        status = _status(e)
        said.append("%s %s answered %d." % (str(e.get("method") or "").upper(),
                                            e.get("path"), status))
        if status in (401, 403):
            said[-1] += " The session is probably over, or that call needs a header the app is not sending."
        elif status == 404:
            said[-1] += " The address has moved, or the thing asked for is not there."
        elif status == 429:
            said[-1] += " Too many requests, so slow the run down."

    # Which list is the rows is the app's to know, not this file's. A
    # messages list with nothing in it is no more an empty account than
    # an errors list is, so each sentence names the lists and says what
    # an empty one would mean, and claims no more.
    meaning = (" When an empty one is the list this app reads, that is an "
               "account with nothing in it or a filter that excluded "
               "everything, and those are different problems.")
    told = 0
    for e in seen:
        if told >= 3:
            break
        if e.get("kind") != "json" or _status(e) != 200:
            continue
        empty, holding, whole = _lists_of(e.get("shape"))
        if empty and not holding and whole:
            said.append("%s answered 200 with %s empty and no list in it "
                        "holding anything." % (e.get("path"), _names(empty))
                        + meaning)
            told += 1
        elif empty and holding:
            said.append("%s answered 200 with %s empty beside %s holding "
                        "items." % (e.get("path"), _names(empty),
                                    _names(holding)) + meaning)
            told += 1

    if not any(e.get("kind") == "json" for e in seen):
        said.append("Nothing the provider sent back was JSON, so this app's "
                    "API may have moved or the page is rendering on the "
                    "server now.")
    return said[:20]


_COUNT = re.compile(r"([0-9]{1,9}) item\(s\)")
# Deeper than any shape of ours, which stops at MAX_DEPTH, so only a file
# made by hand reaches it, and it reads as a part cut short.
_MAX_WALK = 64


def _status(entry: dict) -> int:
    """An entry's status, 0 when it is not a whole number. True is not 1."""
    status = entry.get("status")
    return status if type(status) is int else 0


def _looks_empty(shape) -> bool:
    """A shape that holds at least one list, none of them with anything in
    it, and nothing cut short."""
    empty, holding, whole = _lists_of(shape)
    return bool(empty) and not holding and whole


def _lists_of(shape) -> tuple:
    """(empty, holding, whole) for one answer. Where its lists held
    nothing, where they held something, and whether every part of it was
    read.

    One empty list says little on its own. A list answer carries an errors
    list with no errors in it beside the rows it found, so an errors or
    warnings list with nothing in it is left out, and an answer whose
    errors list holds something is about that error and says nothing here.
    A list inside a row is that row's own, a statement's list of inserts,
    so the rows are counted and their own lists are not. A part cut short,
    too deep or past MAX_KEYS, or a count that cannot be read, could hold
    the rows, so such an answer is never whole."""
    found = []
    _outer_lists(shape, "", 0, found)
    empty, holding, whole = [], [], True
    for where, size in found:
        if size is None:
            whole = False
        elif _names_errors(where):
            if size:
                return [], [], whole
        elif size:
            holding.append(where)
        else:
            empty.append(where)
    return empty, holding, whole


def _outer_lists(shape, where: str, depth: int, found: list) -> None:
    """Each list reached through objects alone, as (where, size), size None
    for a part cut short or a count that cannot be read."""
    if depth > _MAX_WALK or shape == "...":
        found.append((where, None))
    elif isinstance(shape, list):
        head = _COUNT.fullmatch(str(shape[0]) if shape else "")
        found.append((where or "the answer", int(head.group(1)) if head else None))
    elif isinstance(shape, dict):
        if "..." in shape:
            found.append((where, None))
        for k, v in shape.items():
            _outer_lists(v, "%s.%s" % (where, k) if where else str(k),
                         depth + 1, found)


def _names_errors(where: str) -> bool:
    """Whether the last name on a path is one for errors or warnings,
    errorInfo, validation_errors or WARNINGS."""
    last = where.rsplit(".", 1)[-1]
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", last)
    return any(w.lower() in ("error", "errors", "warning", "warnings")
               for w in words)


def _names(where: list) -> str:
    """A few of the places named, the way a sentence lists them."""
    shown = [w[:80] for w in where[:3]]
    if len(where) > 3:
        shown.append("%d more" % (len(where) - 3))
    if len(shown) == 1:
        return shown[0]
    return "%s and %s" % (", ".join(shown[:-1]), shown[-1])
