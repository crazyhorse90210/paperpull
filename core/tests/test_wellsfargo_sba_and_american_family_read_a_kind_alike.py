"""Wells Fargo, SBA and American Family read what a document is the same way.

The three apps carry one reading of a document's kind, the Wells Fargo
app's, ported to SBA from its old code and to American Family beside its
own (07298bc0). The rules that reading took from its review, a masked
number's last digits read as the account's and a lone link reading the part
of the page around it, were then shown to make wrong saves in the Wells
Fargo copy, and reached SBA and American Family only by a second port. The
review of that port found two more shapes the rules saved wrongly and fixed
them in SBA and American Family, and Wells Fargo kept saving them wrongly
until they were ported back. A masked number followed by letters that are
no form's name, "Checking ****1099View statement", was a form's number, and
a hidden field or a control shown only on hover stopped the climb. A fix
that reaches one copy and not the others leaves the others making the wrong
save. So this holds the three copies alike, the patterns they read words
with, the functions that read a kind and decide what is filed, held or
refused, and the part of the page script that climbs from a control and
reads the words around it. American Family's and Wells Fargo's are each
compared with SBA's. Wells Fargo's reader is SBA's own, so the rest of what
reads a control and chooses the one to press, and the whole page script,
are compared whole there too.

Each app keeps its own patterns for the kinds it lists (Wells Fargo's 1099,
1098 and 5498, SBA's 1098, 1099 and tax, American Family's 1099, 1098 and
5498 as numbers of their own, "tax forms" and its bills), so the same words
can read as different kinds in each, the dates and rows its old reading
takes, American Family's rules for a control named only by its row, and its
own way of finding a control again, American Family through the element it
read. Wells Fargo alone counts what discovery found across its accounts and
whether a page shows dated documents, held entries among them, in code of
its own. Those are not compared, and the code around each app's patterns is
compared with American Family's names for them read as SBA's.
"""
import ast
import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The two apps compared with SBA.
OTHERS = ("amfam", "wellsfargo")
# Each app's own names for the patterns its kinds are read with, written as
# SBA's, so the code around them can be compared. Wells Fargo's are SBA's.
OWN_NAMES = {"amfam": {"_A_TAX_FORM_RE": "_TAX_RE", "_A_STATEMENT_KIND_RE": "_STATEMENT_RE"}, "wellsfargo": {}}
# What a mask may end in before "ending" in each app's words, where SBA's
# says "loan".
MASK_WORDS = {"amfam": "policy", "wellsfargo": "card|loan"}
# The functions and classes that read a kind or hold its answers, the same
# code in all three apps once their own names are read as SBA's.
SAME_CODE = ("_names_a_tax_form", "_unsized", "_kind_of", "_rows_of", "_held_as", "kind_of_title",
             "_Found", "_Survey")
# Where each app reads a control's words and decides what is filed and what
# is held.
READER = {"sba": "_read_control", "amfam": "_reading", "wellsfargo": "_read_control"}
# The lines of that reading that read its words and decide. The old reading
# of a kind, kind_as_before, reads each app's own row and is not compared.
READING_LINES = ("words", "chain", "kind", "kind_near", "doubt", "held")
# What else reads a control and chooses the one to press, the same code in
# Wells Fargo and SBA. American Family reads its rows and finds a control
# again in its own ways, so only the parts above are compared there.
WHOLE_IN_WELLS_FARGO = ("_Seen", "_bill_controls", "parse_date", "_read_control", "_survey", "_control_for")
# American Family passes on new_only, writes a refusal with _nothing_pressed
# and reads each control through the element it found, read here as SBA
# writes it. Wells Fargo writes them as SBA does.
SURVEY_AS_SBA = {
    "amfam": {
        "def _survey(page, new_only: bool=False)": "def _survey(page)",
        "_read_control(ctrls.nth(i).element_handle(timeout=_READ_MS), i, new_only)": "_read_control(ctrls.nth(i), i)",
        ", rows_found: int=1, new_only: bool=False)": ", rows_found: int=1)",
        "_survey(page, new_only)": "_survey(page)",
        "_nothing_pressed(": "_refuse(",
    },
    "wellsfargo": {},
}


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


@pytest.fixture(scope="module")
def wellsfargo():
    yield from _load("wellsfargo")


@pytest.fixture(params=OTHERS)
def other(request):
    """The name of American Family or Wells Fargo, its reader and its code."""
    return (request.param,) + tuple(request.getfixturevalue(request.param))


def _as_sba(app, text):
    for own, sba_name in OWN_NAMES[app].items():
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


def test_each_reads_masks_form_names_and_sizes_with_the_same_patterns(sba, other):
    """A mask ends in "loan ending" in SBA's words, "policy ending" in
    American Family's and "card ending" or "loan ending" in Wells Fargo's,
    and is otherwise one pattern."""
    s, (app, o, _) = sba[0], other
    for name in ("_DOTS", "_DASHES", "_FORM_SUFFIXES"):
        assert getattr(s, name) == getattr(o, name), name
    for name in ("_FORM_NAME_RE", "_SIZE_RE"):
        assert (getattr(s, name).pattern, getattr(s, name).flags) == (getattr(o, name).pattern, getattr(o, name).flags), name
    assert s._MASKED_RE.pattern.count("loan") == 1
    assert (s._MASKED_RE.pattern.replace("loan", MASK_WORDS[app]), s._MASKED_RE.flags) == (o._MASKED_RE.pattern,
                                                                                          o._MASKED_RE.flags)


@pytest.mark.parametrize("name", SAME_CODE)
def test_each_reads_a_kind_with_the_same_code(sba, other, name):
    app, _, tree = other
    assert _as_sba(app, _top(tree, name)) == _top(sba[1], name)


def test_each_files_and_holds_a_control_by_the_same_three_readings(sba, other):
    """The careful reading, that reading without the two rules, and the
    old reading agree or the control is filed as nothing, and held when
    only the rules doubt it, in every app."""
    app, _, tree = other
    mine = _assigned(sba[1], READER["sba"], READING_LINES)
    theirs = _assigned(tree, READER[app], READING_LINES)
    assert {k: _as_sba(app, v) for k, v in theirs.items()} == mine


def test_the_old_reading_in_each_app_reads_no_size(sba, amfam, wellsfargo):
    """The old reading of a kind reads each app's own row with each app's
    own pattern, so it is not compared, but in every app it reads the words
    with every size left out."""
    for app, (_mod, tree) in (("sba", sba), ("amfam", amfam), ("wellsfargo", wellsfargo)):
        code = _assigned(tree, READER[app], ("kind_as_before",))["kind_as_before"]
        assert re.match(r"'tax' if _(A_TAX_FORM|TAX_AS_BEFORE)_RE\.search\(_unsized\(.*\)\) else 'statement'$", code), code


def test_each_counts_entries_and_refuses_twins_alike(sba, other):
    """What the survey keeps, holds and counts as unsure or unread, and the
    download's refusals before it presses, held entries counted as entries
    of their date and kind."""
    def survey(tree):
        return _top(tree, "_survey")

    def refusals(tree):
        code = _top(tree, "_control_for")
        return code[:code.index("chosen = mine[0]")]

    app, _, tree = other
    for read in (survey, refusals):
        theirs = read(tree)
        for was, now in SURVEY_AS_SBA[app].items():
            theirs = theirs.replace(was, now)
        assert theirs == read(sba[1]), read.__name__


def _climb(module):
    """The page script's part that climbs from a control and reads the
    words around it, from the entry it is bounded by to the elements it
    sits in, and the lists of what counts as a row or a control, each read
    whole however many lines it is written over. American Family names its
    check of a shown element, and SBA and Wells Fargo write the same check
    out where they read words."""
    script = module._WHERE_JS
    part = script[script.index("const bound ="):script.index("  return {")]
    head = [re.sub(r"\s+", " ", m.group(0)) for m in re.finditer(r"const (?:ROWS|CONTROLS|ANY_CONTROL) = [^;]*;", script)]
    return head, part.replace("!host || !host.getClientRects().length || getComputedStyle(host).visibility !== 'visible'",
                              "!shown(host)")


def test_each_climbs_from_a_control_and_reads_its_words_with_one_script(sba, other):
    head, part = _climb(sba[0])
    assert len(head) == 3 and "holdsAnother" in part and "drawn(c)" in part and "bounded" in part
    assert _climb(other[1]) == (head, part)


@pytest.mark.parametrize("name", WHOLE_IN_WELLS_FARGO)
def test_wells_fargo_reads_and_chooses_a_control_with_sba_s_code(sba, wellsfargo, name):
    """A control's date, its kind, what is built from them and the
    download's checks before and after it chooses, not only the lines
    compared in all three."""
    assert _top(wellsfargo[1], name) == _top(sba[1], name)


def test_wells_fargo_runs_sba_s_whole_page_script(sba, wellsfargo):
    """The dates, rows and words the script hands back, not only its climb."""
    assert wellsfargo[0]._WHERE_JS == sba[0]._WHERE_JS
