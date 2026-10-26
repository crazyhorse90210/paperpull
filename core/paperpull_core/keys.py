"""The account part of a document's identity, and moving old ones over.

A document is remembered by a key built from its category, date, title and
account, and the account was cut to forty characters. Two cards of the same
product are named identically until the masked last four at the end, so
"MARRIOTT BONVOY BOUNDLESS CREDIT CARD (...1234)" and the same card ending
5678 produced the same key. The second card's entire history was read as
already downloaded and dropped, on every run, without a word anywhere.

It was found in Chase and fixed in Chase. Thirty-eight other apps had the
same forty characters, and the labels that overrun them are already sitting
in this repository's own fixtures: "U.S. Bank Cash+ Visa Signature Card
(...1234)" is forty-five characters and "Triple Cash Rewards World Elite
Mastercard ...7890" is fifty.

The key only changes for an account long enough to have been cut, so an
archive whose accounts are short is untouched and needs no migration at
all. For the rest, migrate_account_keys moves the record across the first
time the app runs, because a key that changes underneath an archive means
every document in it looks new and gets downloaded again beside the copy
already there.
"""
from __future__ import annotations

import re

# Any masked tail a provider writes: "(...1234)", "...1234", "****1234",
# "xxxx1234", or a plain trailing four digits.
_LAST_FOUR = re.compile(r"(\d{4})\s*\)?\s*$")
_ADDED_FOUR = re.compile(r"-\d{4}")

# What counts as finished, so a migration never lets a fresh discovery or a
# failed retry overwrite a completed record.
TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}


def account_component(account: str, limit: int = 40) -> str:
    """The account, short enough for a key and still telling two apart.

    Unchanged when it fits, which is most of them, so most archives never
    notice this exists. When it does not fit, the masked last four is kept,
    because that is the part that says which account this is.
    """
    raw = account or ""
    if len(raw) <= limit:
        return raw
    found = _LAST_FOUR.search(raw)
    return raw[:limit] + ("-" + found.group(1) if found else "")


def is_done(record: dict) -> bool:
    return bool(record.get("downloaded_ok") or record.get("state") in TERMINAL)


def _identity(record: dict) -> tuple:
    return tuple(record.get(field, "") for field in
                 ("category", "date", "title", "account", "document_id"))


def migrate_account_keys(records: dict, key_of) -> int:
    """Move records from the cut key to the one that keeps the last four.

    `key_of` takes a stored record and answers the key it should have now.

    A record is only moved when its current key is exactly the new key with
    the last four taken off, which is proof that this is the change being
    made and not some other difference. Anything else stays where it is,
    because guessing which record an unrecognized key belongs to is how one
    account's completed history ends up marking another's as done.
    """
    changed = 0
    for old_key, record in list(records.items()):
        if not isinstance(record, dict):
            continue
        try:
            new_key = key_of(record)
        except Exception:
            continue
        if not new_key or new_key == old_key:
            continue
        # Taking the added last four back out has to give exactly the key
        # this record is stored under. Anywhere in the key, because two apps
        # put the account first and the rest put it last.
        if not any(new_key[:m.start()] + new_key[m.end():] == old_key
                   for m in _ADDED_FOUR.finditer(new_key)):
            continue
        current = records.get(new_key)
        if current is not None and _identity(current) != _identity(record):
            continue
        # A fresh discovery or a failed retry must not erase finished history.
        winner = record if current is None or (
            is_done(record) and not is_done(current)) else current
        records[new_key] = dict(winner)
        del records[old_key]
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# Which one of several documents that share a title and a date
# ---------------------------------------------------------------------------

def stable_occurrences(rows, existing=None, fields=("title", "date")):
    """Number the rows that share a title and a date, the same way every run.

    Five apps have no account in the document's key and tell two documents
    of the same title and date apart by counting them: the first is 0, the
    next is 1. The counting followed the order the provider's API happened
    to answer in.

    Two accounts at Fidelity both have a Quarterly Statement for the same
    quarter. If that answer ever comes back the other way around, the one
    already downloaded takes the other's number, so it is skipped as done
    and the other is fetched again beside it, with the archive now wrong
    about which is which.

    A number already given to a document keeps it, which is looked up by
    what the document IS rather than where it appeared. Only a document
    nobody has seen takes a new number, the lowest one still free. An
    archive that already exists therefore keeps every key it has.
    """
    return _numbered(list(rows), existing, fields, {})


def _tidy(value):
    # The stored record has been through the app's own cleanup and the raw
    # row has not, so both sides are tidied before being compared.
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _what_it_is(item, fields):
    return tuple(_tidy(item.get(f, "")) for f in fields) + (_tidy(item.get("account")),)


def _group_of(item, fields):
    return tuple(_tidy(item.get(f, "")) for f in fields)


def _numbered(rows, existing, fields, taken, every=False):
    """stable_occurrences, with the numbers `taken` already holds for each
    group given to no row here.

    With `every`, the rows that are what several records are take each of
    those records' numbers, lowest first, before any number none of them
    holds. Otherwise only the first record's number is kept for them."""
    known = {}
    for record in (existing or {}).values():
        if not isinstance(record, dict):
            continue
        numbers = known.setdefault(_what_it_is(record, fields), [])
        if every or not numbers:
            numbers.append(record.get("occurrence", 0) or 0)
    for numbers in known.values():
        numbers.sort()

    out = [None] * len(rows)
    for i, row in enumerate(rows):
        used = taken.setdefault(_group_of(row, fields), set())
        numbers = known.get(_what_it_is(row, fields))
        while numbers:
            occurrence = numbers.pop(0)
            if occurrence not in used:
                used.add(occurrence)
                out[i] = occurrence
                break

    for i, row in enumerate(rows):
        if out[i] is not None:
            continue
        used = taken.setdefault(_group_of(row, fields), set())
        occurrence = 0
        while occurrence in used:
            occurrence += 1
        used.add(occurrence)
        out[i] = occurrence
    return out


def places(rows, fields=("title", "date")):
    """Each row's place among the rows of this one list that are what it
    is, with how many those are, as (place, count)."""
    whats = [_what_it_is(row, fields) for row in rows]
    count = {}
    for what in whats:
        count[what] = count.get(what, 0) + 1
    seen = {}
    out = []
    for what in whats:
        out.append((seen.get(what, 0), count[what]))
        seen[what] = seen.get(what, 0) + 1
    return out


def twins(record, existing, fields=("title", "date")) -> int:
    """How many known records are what this one is, itself included, so one
    when nothing known is alike."""
    what = _what_it_is(record, fields)
    return sum(1 for known in (existing or {}).values()
               if isinstance(known, dict) and _what_it_is(known, fields) == what)


def _saved_alone(rows, records, saved, fields, key_of):
    """The saved records `records` does not hold, each as a record of the
    rows whose key it is, with the number its key holds.

    A history moved to another computer brings the app's progress and never
    its discovery, and --minimal none of the fields a key is made of, so a
    saved record is known by its key alone. A key no row listed now has is
    left out, and so is one that could be read as either of two rows'."""
    fields = tuple(fields) + ("account",)
    whats = {}
    for row in rows:
        whats.setdefault(key_of(row), set()).add(_what_it_is(row, fields[:-1]))
    found = {}
    for key, record in saved.items():
        if key in records or not isinstance(record, dict):
            continue
        readings = [(key, 0)] if key in whats else []
        base, _mark, number = key.rpartition("#")
        # Only a number as the app writes one, never #01.
        if (base in whats and number.isascii() and number.isdigit()
                and number == str(int(number))):
            readings.append((base, int(number)))
        if len(readings) != 1 or len(whats[readings[0][0]]) != 1:
            continue
        base, occurrence = readings[0]
        record = dict(record)
        record.update(zip(fields, next(iter(whats[base]))))
        record["occurrence"] = occurrence
        found[key] = record
    return found


def told_apart(rows, existing=None, fields=("title", "date"), id_field="document_id",
               saved=None, key_of=None):
    """Number the rows as stable_occurrences does, the provider's id first,
    and say of each row whether its number surely names that document.

    Capital One and Schwab keep a document under its account, type, title
    and date, and number two documents alike in all of those by place. A
    place says nothing once a list comes back in another order, or with a
    new one ahead of one already saved. The one saved was then numbered as
    the new one and taken twice, and the new one never.

    So a row the provider lists under the id a record keeps takes that
    record's number. A record answers first to the id it was saved under,
    from `saved` (the app's progress), and then to the one in `existing`
    (discovery), which a listing that surely named it wrote.

    When a row answered by its id, the ids of the documents alike to it
    came back, so a row alike that no record answers to is a new document.
    It takes the number of a record alike that was never saved, or else a
    number no record alike holds. Only a row alike says so. A document of
    another day answering by an id this session gave it says nothing of the
    ids documents alike were saved under in another session. So a document
    listed in place of one saved, with nothing alike beside it, is taken for
    the saved one, as stable_occurrences took it.

    The rest are numbered by place as stable_occurrences numbers them, which
    is sure when no record alike is left over, when none left over was
    saved, or when one row and one record are left over. Otherwise which
    row is the saved one cannot be told, so the row is not sure, and the
    app writes nothing of it over a record and downloads nothing for it.

    Rows alike take the numbers of every record left over that they are,
    lowest first, before a number none of those holds. stable_occurrences
    keeps only one of them, which comes to the same whenever the archive was
    numbered by these same `fields`. Capital One's and Schwab's were not.
    Both numbered each account on its own up to 0.33 and again since #122,
    and across accounts from 0.34 to 0.58, so one account's two documents
    alike can hold 1 and 2. Given 1 and then the lowest number free, the second
    was taken for a new document at 0.

    A history moved to another computer brings `saved` without `existing`,
    so a saved record discovery lacks counts as a record too, of the rows
    whose key it is. `key_of` takes a row and answers its key before a
    number is added. Without it a moved archive numbered across accounts
    was numbered by place, each account on its own, and a second account's
    statement saved under 1 was downloaded again at 0.

    Answers (occurrence, sure) for each row, in order.
    """
    rows = list(rows)
    records = {key: record for key, record in (existing or {}).items()
               if isinstance(record, dict)}
    saved = saved or {}
    if key_of is not None:
        records.update(_saved_alone(rows, records, saved, fields, key_of))

    def is_saved(key):
        record = saved.get(key)
        return isinstance(record, dict) and bool(record.get("downloaded_ok"))

    def saved_id(key):
        return _tidy(saved[key].get(id_field)) if is_saved(key) else ""

    def listed_id(key):
        return _tidy(records[key].get(id_field))

    alike = {}
    for key, record in records.items():
        alike.setdefault(_what_it_is(record, fields), []).append(key)

    out = [None] * len(rows)
    taken = {}
    matched = set()
    # The id a record was saved under first, then the one a listing that
    # surely named it gave it, which is the one this session knows it by
    # when the provider's ids change from one session to the next.
    for id_of in (saved_id, listed_id):
        for i, row in enumerate(rows):
            ident = _tidy(row.get(id_field))
            if out[i] is not None or not ident:
                continue
            group = _group_of(row, fields)
            for key in alike.get(_what_it_is(row, fields), ()):
                occurrence = records[key].get("occurrence", 0) or 0
                if (key in matched or id_of(key) != ident
                        or occurrence in taken.setdefault(group, set())):
                    continue
                taken[group].add(occurrence)
                matched.add(key)
                out[i] = occurrence
                break
    answered = {_what_it_is(rows[i], fields) for i in range(len(rows))
                if out[i] is not None}

    rest = [i for i in range(len(rows)) if out[i] is None]
    left = {what: [key for key in keys if key not in matched]
            for what, keys in alike.items()}
    new = [i for i in rest if left.get(_what_it_is(rows[i], fields))
           and _what_it_is(rows[i], fields) in answered]
    placed = [i for i in rest if i not in new]
    news = {_what_it_is(rows[i], fields) for i in new}
    unmatched = {key: records[key] for key in records if key not in matched
                 and _what_it_is(records[key], fields) not in news}
    for i, occurrence in zip(placed, _numbered([rows[i] for i in placed],
                                               unmatched, fields, taken, every=True)):
        out[i] = occurrence
    for i in new:
        # A record left over and never saved is filled first, since nothing
        # it holds can be taken twice, and one an earlier listing gave the
        # wrong id is so given the right one. Otherwise a number no record
        # of its kind holds.
        used = taken.setdefault(_group_of(rows[i], fields), set())
        over = left[_what_it_is(rows[i], fields)]
        held = {records[key].get("occurrence", 0) or 0 for key in over}
        spare = sorted(records[key].get("occurrence", 0) or 0
                       for key in over if not is_saved(key))
        free = [occurrence for occurrence in spare if occurrence not in used]
        occurrence = free[0] if free else 0
        while not free and (occurrence in used or occurrence in held):
            occurrence += 1
        used.add(occurrence)
        out[i] = occurrence

    sure = [True] * len(rows)
    for i in placed:
        what = _what_it_is(rows[i], fields)
        over = left.get(what, [])
        rows_over = [j for j in placed if _what_it_is(rows[j], fields) == what]
        if (over and any(is_saved(key) for key in over)
                and not (len(over) == 1 and len(rows_over) == 1)):
            sure[i] = False
    return list(zip(out, sure))
