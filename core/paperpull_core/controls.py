"""Deciding whether a control on the page may be touched at all.

Every app here is read-only, and the hard part of that promise is not the
downloading, it is the small number of places where the app has to interact
with the page to reach a document. A year picker has to be set. An accordion
has to be opened. Those are the moments where a mistake stops being a bug and
becomes something that touched the user's money.

This module exists because that judgment was written three times, in three
apps, and the third copy was the only one that got it right. The Ally and
Chase apps refused a control if it belonged to a money-movement widget, which
is the obvious danger. Neither considered that a control might belong to a
SIGN-IN form, so when a wrong URL guess landed one of them on a public page,
the account-picker lookup happily matched a login dropdown and set a value on
it. Nothing was submitted and no credential was touched, but selecting inside
a login form is not reading, and reading is all these tools do.

An app declares its own provider vocabulary and passes it in. Everything that
is true of every provider lives here, so the next app inherits the lesson
instead of rediscovering it.

TWO RULES WORTH KEEPING IN MIND WHEN EDITING THIS
-------------------------------------------------
1. It fails CLOSED. An identity that could not be read is unsafe, not safe.
   The reason is that an unreadable identity is exactly what a detached or
   mid-navigation element looks like.
2. It must not get so broad that it refuses the pickers an app genuinely
   needs. A guard that refuses the year picker does not announce itself. It
   makes discovery return nothing, and an empty run looks like an empty
   account. Both directions are tested.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Optional, Pattern

log = logging.getLogger("paperpull_core.controls")

# Anything belonging to a widget that moves money. The account-shaped names
# matter as much as the verbs: Ally's dashboard carries a transfer widget
# whose <select id="fromAccount"> is structurally identical to a statements
# picker, and only its identity tells them apart.
MONEY_CONTROL_RE = re.compile(
    r"(from|to|source|destination|target)\s*_?-?account|"
    r"transfer|payment|pay\b|bill|deposit|withdraw|zelle|wire|remit|"
    r"send\s*money|move\s*money|recipient|payee|amount|frequency|schedule",
    re.I)

# Anything belonging to a sign-in or registration form. Refused outright, and
# not because it moves money, because it does not.
AUTH_CONTROL_RE = re.compile(
    r"log[\s_-]?(in|on)|sign[\s_-]?(in|on|up)|signin|logon|"
    r"authenticat|credential|register|enroll(ment)?\b|"
    r"username|user[\s_-]?id|password|passcode|remember\s*me", re.I)

# Every name a control answers to. The enclosing form and the heading of the
# card it sits in are the parts that matter: an element's own id is often
# meaningless ("select-2"), while the form around it says "login-form".
IDENTITY_JS = r"""el => {
  const attrs = ['id','name','aria-label','placeholder','data-testid',
                 'data-track-name','data-cy','title'];
  const bits = attrs.map(a => el.getAttribute(a) || '');
  const form = el.closest('form');
  if (form) bits.push(form.id || '', form.getAttribute('name') || '',
                      form.getAttribute('aria-label') || '',
                      form.className || '');
  const sect = el.closest("section, [role='region'], [class*='card'], [class*='Card'], " +
                          "[class*='widget'], [class*='Widget'], [class*='module'], " +
                          "[class*='login'], [class*='signin']");
  if (sect) {
    bits.push(sect.getAttribute('aria-label') || '', sect.className || '');
    const h = sect.querySelector('h1,h2,h3,h4,legend');
    if (h) bits.push((h.innerText || '').slice(0, 60));
  }
  const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  if (lbl) bits.push((lbl.innerText || '').slice(0, 60));
  return bits.filter(Boolean).join(' | ');
}"""


def control_identity(loc) -> str:
    """Every name this control answers to, or an empty string if it could not
    be read. An empty string is treated as unsafe by the checks below."""
    return _identity_read(loc) or ""


def _identity_read(loc) -> Optional[str]:
    """control_identity's answer, or None when it could not be read."""
    try:
        return loc.evaluate(IDENTITY_JS) or ""
    except Exception:
        return None


def is_forbidden_context(identity: str,
                         forbidden_re: Optional[Pattern] = None,
                         extra_res: Iterable[Pattern] = (),
                         options: Iterable[str] = ()) -> bool:
    """True when a control must not be read OR written, for any reason.

    `forbidden_re` is the app's own provider vocabulary, and `extra_res` is for
    anything more it wants to add, such as a product picker whose OPTIONS name
    accounts rather than documents. `options` are the visible option labels,
    checked against the same patterns, because a picker sometimes only reveals
    what it is through what it offers.
    """
    if not identity:
        return True
    if MONEY_CONTROL_RE.search(identity) or AUTH_CONTROL_RE.search(identity):
        return True
    if forbidden_re is not None and forbidden_re.search(identity):
        return True
    for rx in extra_res:
        if rx.search(identity):
            return True
    for opt in options:
        for rx in (*extra_res,):
            if rx.search(opt or ""):
                return True
    return False


def safe_selects(page, forbidden_re: Optional[Pattern] = None,
                 signed_out=None, extra_res: Iterable[Pattern] = (),
                 limit: int = 12, unread: Optional[list] = None):
    """Yield (locator, identity) for the <select> elements safe to touch.

    `signed_out` is the app's own check. If it says this is not an application
    page, nothing here is touched at all, whatever the individual controls
    call themselves. A wrong URL guess is an ordinary thing to happen on a
    first probe. Treating whatever it lands on as though it were the app is
    what turns that into a safety problem.

    `unread`, when a caller hands in a list, gets each dropdown whose
    identity could not be read. It is refused like any control that cannot
    be named, and the list says it was there, which a caller looking for
    one dropdown among several needs to know. A dropdown that answered
    with no name at all is refused too, and is not in the list.
    """
    try:
        if signed_out is not None and signed_out(page):
            log.info("refusing every control: this is not a signed-in page")
            return
    except Exception:
        return
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return
    for i in range(n):
        s = loc.nth(i)
        identity = _identity_read(s)
        if identity is None:
            identity = ""
            if unread is not None:
                unread.append(s)
        if is_forbidden_context(identity, forbidden_re, extra_res):
            log.info("refusing dropdown: %s", identity[:120])
            continue
        yield s, identity


def describe_selects(page, forbidden_re: Optional[Pattern] = None,
                     extra_res: Iterable[Pattern] = (),
                     limit: int = 12) -> List[dict]:
    """Every <select> with its identity and the guard's verdict.

    Diagnostic only. It reads and never sets anything. If a real document
    picker is ever refused, this is where you will see why.
    """
    out: List[dict] = []
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return out
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        out.append({
            "identity": identity[:200],
            "refused": is_forbidden_context(identity, forbidden_re, extra_res),
        })
    return out


# Control labels that COMMIT something, as opposed to naming a document.
# Deliberately verb-led. A review found each app matching only bare verb stems,
# so "Save Changes", "Document Removal" and "Loss Mitigation Application"
# walked through every one of them.
#
# Equally deliberately this holds no money NOUNS. "Pay Statement", "Detailed
# Bill PDF" and "Trade Confirmation" are documents, and an earlier attempt that
# included those words refused real downloads in five apps.
#
# The word boundaries are load-bearing. Without the \b on "edit" this also
# matches "credit", and "Credit Card Statement" must stay downloadable.
SETTINGS_CONTROL_RE = re.compile(
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing|al)\b|\bdelet(e|es|ed|ing|ion)\b|"
    r"^\s*save\s*$|\bsave\s+(changes?|settings?|preferences?|profile)\b|"
    r"\bsettings?\b|\bpreferences?\b|\bmanage\b|"
    r"\bset\s+up\b|\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|"
    r"\bturn\s+(on|off)\b|\bopt\s*(in|out)\b|"
    r"\bconsent\b|\bauthoriz(e|es|ed|ing|ation)\b|"
    r"\bcertif(y|ies|ied|ication)\b|\bbeneficiar(y|ies)\b|"
    r"\bwithholding\b|\bautopay\b|\bauto-pay\b|"
    r"\bappl(y|ies|ied|ication)\b|\bplace\s+order\b|\brebalance\b|"
    r"\breallocate\b|\bliquidat(e|es|ed|ing|ion)\b|"
    r"\bbuy\b|\bsell\b|\bschedule\s+(a\s+)?(payment|transfer)\b|"
    # And what ends an account or the session. A dismiss press once took
    # "Close account" and "Dismiss and sign out" for a Close, and most
    # apps' own lists named neither (review of 0.45.0). "Close Account
    # menu" puts a menu away, and "Closed", "Closing" and "Close of" name
    # documents, so none of those is one.
    r"\bclose\s+(?!of\b)(?:[\w'-]+\s+){0,3}?accounts?\b(?!\s+menu\b)|"
    r"\b(?:sign|log)[\s_-]?(?:out|off)\b",
    re.I)


# -- putting an overlay away ------------------------------------------------------
#
# A cookie banner, a survey or a promo sits over the page and takes the
# press meant for what is under it. What puts one away is a control whose
# WHOLE name says so. Eleven apps pressed any button whose name began with
# close, dismiss, no thanks or not now, and "Close account" begins with
# close. Their one check read the button's text alone, so a button named
# Close by its aria-label whose text or title said "Close my account" was
# pressed too (review of 0.45.0). American Family's own, from the review of
# 0.41.0, is the one this was taken from. Nothing may stand between Close
# and what it puts away, since "Close session window" and "Close policy
# panel" do more than dismiss (review of this change).

DISMISS_NAME_RE = re.compile(
    r"^\s*[×✕✖]?\s*(?:close|dismiss|no,?\s*thanks|not\s+now)"
    r"(?:\s+(?:this\s+)?(?:dialog|banner|window|message|pop-?up|survey|notice|alert|panel|menu|"
    r"modal|notification|overlay))?\s*[×✕✖xX]?\s*$",
    re.I)

# A close button that shows only its glyph, the way Bootstrap draws one.
_GLYPH_ONLY_RE = re.compile(r"^\s*[×✕✖✗xX]?\s*$")


def _refused_words(label: str, forbidden_re: Optional[Pattern] = None) -> bool:
    return bool(SETTINGS_CONTROL_RE.search(label) or AUTH_CONTROL_RE.search(label)
                or (forbidden_re is not None and forbidden_re.search(label)))


def is_dismiss_label(label: str, forbidden_re: Optional[Pattern] = None,
                     name_re: Pattern = DISMISS_NAME_RE) -> bool:
    """Whether this one label, whole, says put it away and nothing else."""
    label = re.sub(r"\s+", " ", (label or "").strip())
    return bool(label and name_re.search(label) and not _refused_words(label, forbidden_re))


def is_dismiss_control(labels, forbidden_re: Optional[Pattern] = None,
                       name_re: Pattern = DISMISS_NAME_RE) -> bool:
    """Whether a control whose labels, its text, aria-label and title as
    control_labels reads them, are these only puts something away. One of
    them says so whole, every other says so too or is a glyph alone, and
    none is a word the core's lists or the app's own `forbidden_re` refuse.
    No labels at all is not a dismiss control."""
    labels = [re.sub(r"\s+", " ", (w or "").strip()) for w in labels or ()]
    labels = [w for w in labels if w]
    if not labels or any(_refused_words(w, forbidden_re) for w in labels):
        return False
    said = [w for w in labels if is_dismiss_label(w, forbidden_re, name_re)]
    # Another label may be the core's own whole dismiss name, a bare Close
    # shown beside an aria-label in the app's own words, "Close Mobile menu".
    return bool(said) and all(w in said or _GLYPH_ONLY_RE.match(w) or is_dismiss_label(w, forbidden_re)
                              for w in labels)


_FOCUS_IN_A_FORM_JS = r"""() => {
  const a = document.activeElement;
  return !!(a && a.closest && a.closest('form, input, select, textarea, [contenteditable]'));
}"""


def _focus_in_a_form(page) -> bool:
    """Whether the focus is in a form's control, where a key would reach
    it. True when it could not be told."""
    try:
        return bool(page.evaluate(_FOCUS_IN_A_FORM_JS))
    except Exception:
        return True


# The name of the dialog a control sits in, its aria-label, what its
# aria-labelledby names or else its first heading, "" outside one. A Close
# in a dialog asking "Close your account?" confirms, it does not dismiss.
_DIALOG_NAME_JS = r"""el => {
  const d = el.closest('[role=dialog], [role=alertdialog], dialog, [aria-modal=true]');
  if (!d) return '';
  const own = d.getAttribute('aria-label');
  if (own) return own;
  const ids = (d.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
  const named = ids.map(id => { const n = document.getElementById(id); return n ? n.innerText : ''; })
                   .join(' ').trim();
  if (named) return named;
  const h = d.querySelector('h1, h2, h3, h4, [role=heading]');
  return h ? (h.innerText || '') : '';
}"""


def _in_a_refused_dialog(el) -> bool:
    """Whether the dialog around `el` is named for something the core's
    lists refuse. True when it could not be read."""
    try:
        name = re.sub(r"\s+", " ", el.evaluate(_DIALOG_NAME_JS) or "").strip()
    except Exception:
        return True
    return bool(name) and _refused_words(name)


def dismiss_overlays(page, forbidden_re: Optional[Pattern] = None,
                     name_re: Pattern = DISMISS_NAME_RE, within=None, escape: bool = True,
                     limit: int = 6, settle_ms: int = 250, click_ms: int = 1000) -> int:
    """Put away what sits over the page. Escape first, never while the focus
    is in a form's control, which the key would reach. Then each visible
    button, in `within` when given, else anywhere on the page, whose name
    `name_re` takes and whose every label is_dismiss_control takes, against
    the core's lists and the app's own `forbidden_re`, and that is not in a
    dialog the core's lists refuse by its name. Never accept, and never what
    closes an account or signs out. The buttons are read once, before any
    press, so one that leaves the page moves none of the others along.
    Answers how many it pressed. Nothing here raises."""
    if escape:
        try:
            if not _focus_in_a_form(page):
                page.keyboard.press("Escape")
                page.wait_for_timeout(settle_ms)
        except Exception:
            pass
    pressed = 0
    try:
        found = (within if within is not None else page).get_by_role("button", name=name_re)
        for el in found.element_handles()[:limit]:
            try:
                if not el.is_visible():
                    continue
                if not is_dismiss_control(control_labels(el), forbidden_re, name_re):
                    continue
                if _in_a_refused_dialog(el):
                    continue
                el.click(timeout=click_ms)
                pressed += 1
                page.wait_for_timeout(settle_ms)
            except Exception:
                continue
    except Exception:
        pass
    return pressed


# -- reading the controls on a page -------------------------------------------
#
# Both of these were identical in the eleven apps cut from one scaffold, so
# every provider added since made another copy. The pattern that says which
# words finish a download stays with the app, because AT&T's menu says
# things nobody else's does, and so does the app's own is_safe_control.

class Survey(set):
    """The words control_texts read, and whether it read every control.

    A survey taken before a click is taken from one taken after it, and
    the difference is what the click revealed. That difference is whole
    only when both surveys were, so it carries the answer with it, and so
    does a survey joined with any other set of words."""

    def __init__(self, texts=(), complete: bool = True):
        super().__init__(texts)
        self.complete = complete

    def _with(self, texts, other) -> "Survey":
        return Survey(texts, self.complete and getattr(other, "complete", True))

    def __sub__(self, other):
        return self._with(set(self) - set(other), other)

    def __rsub__(self, other):
        return self._with(set(other) - set(self), other)

    def __or__(self, other):
        return self._with(set(self) | set(other), other)

    __ror__ = __or__


def control_texts(page, roles=("button", "link", "menuitem")) -> Survey:
    """The visible words of every control on the page, tidied and cut short.

    Used to tell what a click revealed: take this before and after, and the
    difference is what appeared. Anything that will not answer is skipped
    rather than raised, because a page mid-render is normal and a survey
    that stops is worth less than a partial one.

    Each role is read in one call, every control at once. Each control used
    to be read on its own with a 200 ms wait, and one that did not answer
    was left out. Left out before a click it looked revealed after it, so
    the page's own Download PDF could be pressed as the second step. Left
    out after a click, the plain Regular PDF was missing and Itemized PDF,
    a different document, could be pressed (the census after CI run
    36792330947).
    The first 120 of a role were read, so a click that moved controls
    across that line made the same false difference. A role that will not
    answer is still skipped, and the survey says it is not whole.
    """
    out = Survey()
    for role in roles:
        try:
            texts = page.get_by_role(role).all_inner_texts()
        except Exception:
            out.complete = False
            continue
        for t in texts:
            t = (t or "").strip()
            if t:
                out.add(re.sub(r"\s+", " ", t)[:60])
    return out


def escape_for_locator(text: str) -> str:
    """Text made safe to put inside a pattern handed to a Playwright locator.

    re.escape does most of it, but since Python 3.7 it leaves "/" alone.
    Playwright writes a pattern into its selector between slashes, as
    name=/pattern/flags, so a slash in the text ends the pattern early and
    the locator raises InvalidSelectorError the first time it is used.
    Every caller catches that, so a control reading "View/print PDF" was
    simply never found. The extra backslash changes nothing for Python's
    own matching.
    """
    return re.escape(text).replace("/", "\\/")


def second_step(page, appeared: set, pattern: Pattern, is_safe_control, place,
                trace: Optional[list] = None):
    """A control the click revealed whose text says it finishes a download,
    as (element, text), or (None, "").

    Several providers answer a Download button with a small menu, so the
    document arrives only after a second click. The ones that read like the
    plain choice are tried first, because "Regular PDF" is the bill and
    "Itemized PDF" is a different document. Whatever is picked still has to
    pass the app's own guard.

    Nothing is picked from what appeared when a survey behind it could not
    read every control. A control already on the page could be in it, or
    the plain choice could be missing from it.

    And nothing is picked that is not where the press put it, by `place`,
    read with place_of just before the press. A list drawn anew after a
    press that went through, or a panel opened for another row, shows a
    Download of another document, and its PDF would be saved under this
    one's name. The first choice in that order that shows at all decides.
    When none of it sits where the press put it, nothing is picked, not
    even a lesser choice that does, since the page did something besides
    the press. When more than one does, or there are more of that name than
    are read, which document each is for cannot be told, and nothing is
    picked either. `trace`, when given, gets a note of where it sat, in
    fixed words only.
    """
    if not getattr(appeared, "complete", True):
        log.info("a survey of the controls was not whole, so no second step is taken")
        return None, ""
    ranked = sorted(appeared,
                    key=lambda t: (0 if re.search(r"regular|standard|full|^download", t, re.I) else 1, t))
    for text in ranked:
        if not (pattern.match(text) and is_safe_control(text)):
            continue
        shown, crowded = [], False
        for role in ("button", "link", "menuitem"):
            try:
                loc = page.get_by_role(role, name=re.compile(
                    "^" + escape_for_locator(text) + "$", re.I))
                count = loc.count()
                crowded = crowded or count > _READ_AT_MOST
                for i in range(min(count, _READ_AT_MOST)):
                    if loc.nth(i).is_visible():
                        shown.append(loc.nth(i))
            except Exception:
                continue
        if not shown:
            continue
        found, tied = [], []
        for candidate in ([] if crowded else shown):
            element = element_of(candidate)
            word = where_it_sits(place, element)
            found.append(word)
            if word in TIED:
                tied.append((element, word))
            else:
                _let_go(element, candidate)
        if len(tied) == 1:
            if trace is not None:
                trace.append({"note": "the revealed control sits where the press put it",
                              "where": tied[0][1]})
            return tied[0][0], text
        for element, _word in tied:
            _let_go(element, None)
        log.info("a revealed control is not where the press put it, so no second step is taken")
        if trace is not None:
            trace.append({"note": "a revealed control is not where the press put it, "
                                  "so it was not pressed",
                          "where": [CROWDED] if crowded else [SEVERAL] if tied
                          else sorted(set(found))})
        return None, ""
    return None, ""


# -- where a revealed control sits ---------------------------------------------
#
# What the press put on the page is told from what was already there by a
# look taken just before it. Only a handle into the page is kept, never a
# word the page wrote, so nothing of the page leaves it. The look holds the
# elements weakly and every element handle used to read it is let go, so a
# list drawn anew is not kept alive by a run going through hundreds of
# documents.
#
# Both reads go into every open shadow root, since a list built of web
# components (E*TRADE's documents table is one) keeps its rows' controls
# there. A closed shadow root cannot be read by anything, and its controls
# are not counted.
#
# Where a control sits cannot tell a dialog the press opened from one the
# page opened at the same moment for another reason, a late notice from an
# earlier document say, nor a row the page reused for another document
# around the very control pressed. Only what the saved PDF says can tell
# those apart (identity.py).

# What a press opens over the page or beside its control, a dialog, a modal
# region, a menu, a list of choices or a popover.
OPENED_CSS = ("dialog, [role=dialog], [role=alertdialog], [aria-modal=true], "
              "[role=menu], [role=listbox], [popover]")

# Everything that can be pressed, by its element or its role, the kinds
# control_texts reads and a few more, since counting one too many only
# refuses more.
PRESSABLE_CSS = ("a[href], button, input[type=button], input[type=submit], input[type=image], "
                 "summary, select, [role=button], [role=link], [role=menuitem], [role=tab], "
                 "[role=option], [role=checkbox], [role=radio]")

# A row of a list or a table, which holds one document.
ROW_CSS = "tr, [role=row], li, [role=listitem], article, [role=article]"

# Where a revealed control sits, in the words a trace may carry.
OPENED_BY_THE_PRESS = "in what the press opened"
BESIDE_THE_CONTROL = "beside the pressed control"
TIED = frozenset((OPENED_BY_THE_PRESS, BESIDE_THE_CONTROL))
ELSEWHERE = "elsewhere on the page"
LEFT_THE_PAGE = "the pressed control left the page"
LOADED_ANEW = "the page was loaded anew"
NOT_READ = "it could not be read"
SEVERAL = "more than one sits where the press put it"
CROWDED = "more of them than are read"
WHERE_WORDS = TIED | {ELSEWHERE, LEFT_THE_PAGE, LOADED_ANEW, NOT_READ}

# How many controls of one name and kind second_step reads. When there are
# more, which of them sit where the press put it cannot be told, and none
# is taken.
_READ_AT_MOST = 8

# What both reads share. An element's parent, from the top of a shadow root
# to the element that holds it. Whether `a` holds `c` that way. Every
# element a selector finds in the page and in every open shadow root in it.
_TREE_JS = r"""
  const shown = (e) => typeof e.checkVisibility === 'function'
      ? e.checkVisibility({visibilityProperty: true, checkVisibilityCSS: true})
      : e.getClientRects().length > 0;
  const up = (n) => {
    const p = n.parentNode;
    if (p && p.nodeType === 11 && p.host) return p.host;
    return p && p.nodeType === 1 ? p : null;
  };
  const holds = (a, c) => {
    for (let n = c; n; n = up(n)) if (n === a) return true;
    return false;
  };
  const every = (sel) => {
    const out = [];
    const walk = (root) => {
      out.push(...root.querySelectorAll(sel));
      for (const e of root.querySelectorAll('*')) if (e.shadowRoot) walk(e.shadowRoot);
    };
    walk(document);
    return out;
  };
"""

# Read just before the press. Every container present then and whether it
# showed, the control's own row, and for every element around the control
# how many other things that can be pressed it held. A control inside the
# pressed one, or around it, is the pressed one.
_PLACE_JS = r"""(el) => {%s
  const others = every(%s).filter(
      (c) => c !== el && !holds(el, c) && !holds(c, el) && shown(c));
  const around = [];
  let row = null;
  for (let a = up(el); a; a = up(a)) {
    around.push({node: new WeakRef(a), held: others.filter((c) => holds(a, c)).length});
    if (!row && a.matches(%s)) row = a;
  }
  const before = every(%s).map((e) => ({node: new WeakRef(e), shown: shown(e)}));
  return {el: new WeakRef(el), row: row ? new WeakRef(row) : null, around, before};
}""" % (_TREE_JS, repr(PRESSABLE_CSS), repr(ROW_CSS), repr(OPENED_CSS))

# Where the revealed control `step` sits, read once the press is over.
#   In what the press opened, a dialog, menu or popover that was not there
#   before the press, or was there hidden and shows now.
#   Beside the pressed control, inside the smallest element holding both,
#   which held nothing else to press before the press, is neither the
#   body nor the page, and is not wider than the pressed control's own row.
# Either way the pressed control is still on the page.
_WHERE_JS = r"""(step, place) => {%s
  const el = place.el.deref();
  if (!el || !el.isConnected) return %s;
  const before = place.before.map((x) => ({node: x.node.deref(), shown: x.shown}));
  for (let a = step; a; a = up(a)) {
    if (!a.matches(%s)) continue;
    const was = before.find((x) => x.node === a);
    if (!was || (!was.shown && shown(a))) return %s;
  }
  let both = up(el);
  while (both && !holds(both, step)) both = up(both);
  if (!both || both === document.body || both === document.documentElement) return %s;
  const row = place.row ? place.row.deref() : null;
  if (row && !holds(row, both)) return %s;
  const was = place.around.find((x) => x.node.deref() === both);
  return was && was.held === 0 ? %s : %s;
}""" % (_TREE_JS, repr(LEFT_THE_PAGE), repr(OPENED_CSS), repr(OPENED_BY_THE_PRESS),
        repr(ELSEWHERE), repr(ELSEWHERE), repr(BESIDE_THE_CONTROL), repr(ELSEWHERE))


class Place:
    """Where a press was made, read by place_of just before it. It holds a
    handle into the page and nothing the page wrote."""

    def __init__(self, handle):
        self.handle = handle

    def where(self, step) -> str:
        """Where the element `step` sits against this press, in WHERE_WORDS.
        A page loaded since the press cannot be asked about the place, which
        was in the page before it."""
        try:
            word = step.evaluate(_WHERE_JS, self.handle)
        except Exception as e:
            return LOADED_ANEW if "context" in str(e).lower() else NOT_READ
        return word if word in WHERE_WORDS else NOT_READ

    def still_there(self) -> bool:
        """Whether the control pressed is still on the page it was pressed
        on. False when that cannot be told."""
        try:
            return self.handle.evaluate(
                "(place) => { const el = place.el.deref(); return !!el && el.isConnected; }") is True
        except Exception:
            return False


def pressed_still_there(place: Optional[Place]) -> bool:
    """Whether the control pressed at `place` is still on the page it was
    pressed on, for a caller about to press something else for the same
    document. False when there is no place or it cannot be told."""
    return place is not None and place.still_there()


def _let_go(handle, found) -> None:
    """Let go of an element handle element_of made from `found`, so the
    element is not kept alive in the page for as long as the run lasts. A
    handle that was handed in is the caller's own and is kept."""
    if handle is None or handle is found:
        return
    try:
        handle.dispose()
    except Exception:
        pass


def element_of(found):
    """The one element a locator finds now, as an element handle, so what
    is judged is what gets pressed. A Locator finds it again each time it
    is used, and an element handle stays the element it is."""
    find = getattr(found, "element_handle", None)
    if not callable(find):
        return found
    try:
        return find(timeout=3000)
    except Exception:
        return None


def place_of(page, el) -> Optional[Place]:
    """Where `el` is about to be pressed, to be read just before the press
    and handed to second_step or where_it_sits once it is over. None when
    it could not be read, and then nothing the press reveals is taken."""
    handle = element_of(el)
    if handle is None:
        return None
    try:
        return Place(page.evaluate_handle(_PLACE_JS, handle))
    except Exception as e:
        log.info("where the press is made could not be read (%s)", type(e).__name__)
        return None
    finally:
        _let_go(handle, el)


def where_it_sits(place: Optional[Place], step) -> str:
    """Where the revealed control `step`, an element handle, sits against
    the press at `place`, in WHERE_WORDS. NOT_READ when either is missing."""
    if place is None or step is None:
        return NOT_READ
    return place.where(step)


def controls_named(page, name_re: Pattern, roles=("button", "link")):
    """Every control on the page whose name matches, as one locator.

    A document is offered as a button on one provider and a link on the
    next, and the row it sits in supplies the date either way.

    A control is matched on its ACCESSIBLE NAME, which is what a screen
    reader would say and is usually what is written on it. Usually. A
    tester's survey counted eighteen controls on a page by what they say
    and this found none of them, so discovery reported no documents on a
    page holding nine. Whatever the cause on that page, a control whose
    own words match is a control, so when the accessible name finds
    nothing the words are asked instead (#38).
    """
    loc = page.get_by_role(roles[0], name=name_re)
    for role in roles[1:]:
        loc = loc.or_(page.get_by_role(role, name=name_re))
    try:
        if loc.count():
            return loc
    except Exception:
        return loc
    by_text = page.locator("a, button, [role=button], [role=link]").filter(has_text=name_re)
    try:
        if by_text.count():
            log.info("no control matched by its accessible name, %d matched by its words",
                     by_text.count())
            return by_text
    except Exception:
        pass
    return loc


# ---------------------------------------------------------------------------
# Paging forward
#
# Pagination needs its own judgment, and finding that out took a while.
# Every blocklist here refuses the word "next", correctly, because "Next" is
# what a wizard's commit button says. Eight apps then handed a pagination
# control to that same blocklist, so a control labeled "Next" was refused and
# they could not page forward at all. The run finished, reported success, and
# had seen the first page.
#
# Before that was noticed the hole went the other way: the label was empty for
# an icon-only chevron, an empty string matches no blocklist, and the control
# was clicked blind on a bank page.
#
# Both stop being possible if the label has to SAY it pages forward, matched
# whole rather than searched, so nothing else can ride along inside it.
# ---------------------------------------------------------------------------

NEXT_LABEL_RE = re.compile(
    r"^(?:next(?:\s+(?:page|month|period|\d{1,4}|>|»|›))?"
    r"|(?:go\s+to\s+)?next\s+page"
    r"|older(?:\s+(?:documents?|statements?|activity))?"
    r"|>|>>|\u203a|\u203a\u203a|\u00bb|\u2192)$", re.I)


def is_next_control(label: str) -> bool:
    """Whether this label means one page forward, and nothing else.

    An allowlist, matched against the whole label, because the blocklists
    cannot help here: they all refuse "next" for the commit button that
    also says it. "Next", "Next page" and a bare chevron pass. "Next
    Payment Due", "Pay now" and an empty label do not.
    """
    return bool(NEXT_LABEL_RE.match(re.sub(r"\s+", " ", (label or "").strip())))


def control_labels(el) -> list:
    """Each label a control carries, separately.

    Separately is the point, twice over. These were built by adding the
    text to the aria-label with nothing in between, so a control with both
    read "NextNext", a word no rule can be written against. Joining them
    with a space instead only moves the problem: a chevron whose text is
    "Next" and whose aria-label is "Next page" would read "Next Next page",
    which is not what either of them says.
    """
    def text_of():
        # A Locator takes a timeout, an ElementHandle does not, and both
        # turn up here. Asking the wrong one raises TypeError, which would
        # have come back as a control with no label at all.
        try:
            return el.inner_text(timeout=800)
        except TypeError:
            return el.inner_text()

    out = []
    for read in (text_of,
                 lambda: el.get_attribute("aria-label"),
                 lambda: el.get_attribute("title")):
        try:
            text = (read() or "").strip()
        except Exception:
            text = ""
        text = re.sub(r"\s+", " ", text)
        if text and text not in out:
            out.append(text)
    return out


def control_label(el) -> str:
    """The same labels as one string, for a log line or a message."""
    return " | ".join(control_labels(el))


def click_next_page(page, selector: str, settle_ms: int = 2500,
                    limit: int = 8) -> bool:
    """Page forward once, through the first control that says it does that.

    Every candidate is looked at rather than only the first, because the
    selectors here are broad enough to catch an unrelated element whose
    class merely contains "next", and stopping at that one meant never
    reaching the real control behind it.
    """
    try:
        loc = page.locator(selector)
        count = loc.count()
    except Exception:
        return False
    for i in range(min(count, limit)):
        try:
            el = loc.nth(i)
            if not (el.is_visible() and el.is_enabled()):
                continue
            if not any(is_next_control(part) for part in control_labels(el)):
                continue
            el.click()
            page.wait_for_timeout(settle_ms)
            return True
        except Exception:
            continue
    return False
