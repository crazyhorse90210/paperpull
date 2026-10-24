"""SBA and American Family read what a document is the same way.

Both apps carry the Wells Fargo app's reading of a document's kind, ported
to SBA from its old code and to American Family beside its own (07298bc0).
The rules that reading took from its review, a masked number's last digits
read as the loan's and a lone link reading the part of the page around it,
were then shown to make wrong saves in the Wells Fargo copy, and reached
SBA and American Family only by a second port. A fix that reaches one copy
and not the other leaves the other making the wrong save. So this holds
the two copies alike, the patterns they read words with, the functions
that read a kind and decide what is filed, held or refused, and the part
of the page script that climbs from a control and reads the words around
it.

Each app keeps its own patterns for the two kinds it lists (SBA's 1098,
1099 and tax, American Family's 1099, 1098 and 5498 as numbers of their
own, "tax forms" and its bills), so the same words can read as different
kinds in the two, the dates and rows its old reading takes, American
Family's rules for a control named only by its row, and its own way of
finding a control again, American Family through the element it read.
Those are not compared, and the code around each app's patterns is
compared with American Family's names for them read as SBA's.

The Wells Fargo copy is not compared yet. The review of the SBA and
American Family port found two more shapes the rules saved wrongly, and
fixed them in these two apps only. A masked number followed by letters
that are no form's name, "Checking ****1099View statement", is a form's
number there, and a hidden field or a control shown only on hover stops
its climb. Once Wells Fargo reads those shapes the same way, it belongs
here too.
"""
import ast
import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Each app's own names for the patterns its kinds are read with, written as
# SBA's, so the code around them can be compared.
OWN_NAMES = {"_A_TAX_FORM_RE": "_TAX_RE", "_A_STATEMENT_KIND_RE": "_STATEMENT_RE"}
# The functions and classes that read a kind or hold its answers, the same
# code in both apps once their own names are read as SBA's.
SAME_CODE = ("_names_a_tax_form", "_unsized", "_kind_of", "_rows_of", "_held_as", "kind_of_title",
             "_Found", "_Survey")
# The lines of a control's reading that read its words and decide what is
# filed and what is held, in SBA's _read_control and American Family's
# _reading. The old reading of a kind, kind_as_before, reads each app's own
# row and is not compared.
READING_LINES = ("words", "chain", "kind", "kind_near", "doubt", "held")


def _load(app):
    """The app's reader as a module of its own name, which its dataclasses
    need while it loads, and its code."""
    path = REPO / "apps" / app / ("%s_site.py" % app)
    spec = importlib.util.spec_from_file_location("in_step_%s_site" % app, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod, ast.parse(path.read_text(encoding="utf-8"))
    del sys.modules[spec.name]


@pytest.fixture(scope="module")
def sba():
    yield from _load("sba")


@pytest.fixture(scope="module")
def amfam():
    yield from _load("amfam")


def _as_sba(text):
    for own, sba_name in OWN_NAMES.items():
        text = re.sub(r"\b%s\b" % own, sba_name, text)
    return text


def _top(tree, name):
    """The function or class `name` at the top of a module, without its
    docstring, as code."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            node = copy.copy(node)
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:]
            return ast.unparse(node)
    raise AssertionError("no %s at the top of the module" % name)


def _assigned(tree, function, names):
    """Each assignment to one of `names` in `function`, as code, by name."""
    found = {}
    for node in ast.walk(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in names:
                assert node.targets[0].id not in found, "%s is set twice in %s" % (node.targets[0].id, function)
                found[node.targets[0].id] = ast.unparse(node.value)
    assert set(found) == set(names), (function, sorted(set(names) - set(found)))
    return found


def test_the_two_read_masks_form_names_and_sizes_with_the_same_patterns(sba, amfam):
    """A mask ends in "loan ending" in SBA's words and "policy ending" in
    American Family's, and is otherwise one pattern."""
    (s, _), (a, _) = sba, amfam
    for name in ("_DOTS", "_DASHES", "_FORM_SUFFIXES"):
        assert getattr(s, name) == getattr(a, name), name
    for name in ("_FORM_NAME_RE", "_SIZE_RE"):
        assert (getattr(s, name).pattern, getattr(s, name).flags) == (getattr(a, name).pattern, getattr(a, name).flags), name
    assert s._MASKED_RE.pattern.count("loan") == 1
    assert (s._MASKED_RE.pattern.replace("loan", "policy"), s._MASKED_RE.flags) == (a._MASKED_RE.pattern, a._MASKED_RE.flags)


@pytest.mark.parametrize("name", SAME_CODE)
def test_the_two_read_a_kind_with_the_same_code(sba, amfam, name):
    assert _as_sba(_top(amfam[1], name)) == _top(sba[1], name)


def test_the_two_file_and_hold_a_control_by_the_same_three_readings(sba, amfam):
    """The careful reading, that reading without the two rules, and the
    old reading agree or the control is filed as nothing, and held when
    only the rules doubt it, in both apps."""
    mine = _assigned(sba[1], "_read_control", READING_LINES)
    theirs = _assigned(amfam[1], "_reading", READING_LINES)
    assert {k: _as_sba(v) for k, v in theirs.items()} == mine


def test_the_old_reading_in_each_app_reads_no_size(sba, amfam):
    """The old reading of a kind reads each app's own row with each app's
    own pattern, so it is not compared, but in both it reads the words with
    every size left out."""
    for (_mod, tree), function in ((sba, "_read_control"), (amfam, "_reading")):
        code = _assigned(tree, function, ("kind_as_before",))["kind_as_before"]
        assert re.match(r"'tax' if _(A_TAX_FORM|TAX_AS_BEFORE)_RE\.search\(_unsized\(.*\)\) else 'statement'$", code), code


def test_the_two_count_entries_and_refuse_twins_alike(sba, amfam):
    """What the survey keeps, holds and counts as unsure or unread, and the
    download's refusals before it presses, held entries counted as entries
    of their date and kind. American Family passes on new_only, writes a
    refusal with _nothing_pressed and reads each control through the
    element it found, which is read here as SBA writes it."""
    def survey(tree):
        return _top(tree, "_survey")

    def refusals(tree):
        code = _top(tree, "_control_for")
        return code[:code.index("chosen = mine[0]")]

    amfam_as_sba = {
        "def _survey(page, new_only: bool=False)": "def _survey(page)",
        "_read_control(ctrls.nth(i).element_handle(timeout=_READ_MS), i, new_only)": "_read_control(ctrls.nth(i), i)",
        ", rows_found: int=1, new_only: bool=False)": ", rows_found: int=1)",
        "_survey(page, new_only)": "_survey(page)",
        "_nothing_pressed(": "_refuse(",
    }
    for read in (survey, refusals):
        theirs = read(amfam[1])
        for was, now in amfam_as_sba.items():
            theirs = theirs.replace(was, now)
        assert theirs == read(sba[1]), read.__name__


def _climb(module):
    """The page script's part that climbs from a control and reads the
    words around it, from the entry it is bounded by to the elements it
    sits in. American Family names its check of a shown element, and SBA
    writes the same check out where it reads words."""
    script = module._WHERE_JS
    part = script[script.index("const bound ="):script.index("  return {")]
    head = [line.strip() for line in script.splitlines() if re.match(r"\s*const (ROWS|CONTROLS|ANY_CONTROL) =", line)]
    return head, part.replace("!host || !host.getClientRects().length || getComputedStyle(host).visibility !== 'visible'",
                              "!shown(host)")


def test_the_two_climb_from_a_control_and_read_its_words_with_one_script(sba, amfam):
    head, part = _climb(sba[0])
    assert len(head) == 3 and "holdsAnother" in part and "bounded" in part
    assert _climb(amfam[0]) == (head, part)
