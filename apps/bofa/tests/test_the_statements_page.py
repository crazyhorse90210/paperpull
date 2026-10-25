"""Bank of America's statements page, as the two recordings on #121 showed
it, read through a stand-in page (standin_bank). The list call and the PDF
links are learned from the page itself, every account and year is asked
for the way the page asks, and anything that does not fit stops the run
rather than being guessed at. Nothing is pressed. Every value is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_site as site
import standin_bank as sb


@pytest.fixture(autouse=True)
def fresh():
    site.forget()
    yield
    site.forget()


def no_presses(page):
    assert not [a for a in page.asked if a[0] in sb.PRESSES], page.asked
    assert not [a for a in page.asked if a[0] == "goto"], page.asked


# -- learning the page's own call ---------------------------------------------

def test_the_list_call_is_learned_from_one_reload_and_nothing_is_pressed():
    page = sb.Bank()
    call = site.learn(page)
    assert page.reloads == 1
    assert call.url == sb.LIST_URL
    assert call.account_key == sb.KEY
    assert call.statements_category == "CAT-STMT"
    assert call.years == ["2026", "2025"]
    assert [a[sb.KEY] for a in call.accounts] == ["K-ALPHA-0001", "K-BRAVO-0002"]
    # The page's own headers are sent again, never the ones the browser sets.
    assert call.headers == {"content-type": "application/json", "x-standin-csrf": "TOKEN-T"}
    assert call.template is not None and call.links == 2
    no_presses(page)
    assert not page.listeners, "the listener was left on the page"


def test_a_tab_off_the_statements_page_is_never_reloaded():
    page = sb.Bank(url="https://secure.bankofamerica.com/myaccounts/overview/?k=X")
    with pytest.raises(site.NotThere):
        site.learn(page)
    assert page.reloads == 0


def test_a_page_of_another_site_is_not_the_statements_page():
    assert not site.on_statements_page(sb.Bank(url="https://evil.test/sample-zz-stmts-docs/"))
    assert not site.on_statements_page(sb.Bank(url="https://www.bankofamerica.com/sample-zz-stmts-docs/"))
    assert not site.on_statements_page(sb.Bank(password=1))
    assert site.on_statements_page(sb.Bank())


def test_a_page_that_makes_no_list_call_is_not_guessed_at():
    page = sb.Bank()
    page.first_url = "https://secure.bankofamerica.com/sample/standin/zone/other/v1/listThings"
    with pytest.raises(site.NotLearned):
        site.learn(page)


@pytest.mark.parametrize("url", [
    "https://www.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "https://secure.bankofamerica.com.evil.test/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "http://secure.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "https://secure.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments?x=1",
])
def test_only_the_list_call_on_the_secure_host_is_heard(url):
    page = sb.Bank()
    page.first_url = url
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_sign_in_answer_is_a_session_that_ended():
    page = sb.Bank()
    page.first_status = 401
    page.listed = {"error": "signed out"}
    with pytest.raises(site.SessionExpired):
        site.learn(page)


@pytest.mark.parametrize("body", [
    {sb.KEY: "K-ALPHA-0001", "other": "x", "docCategoryId": "CAT-STMT", "year": "2026"},
    {"docCategoryId": "CAT-STMT", "year": "2026"},
    {sb.KEY: "K-BRAVO-0002", "docCategoryId": "CAT-STMT", "year": "2026"},
    {sb.KEY: "", "docCategoryId": "CAT-STMT", "year": "2026"},
])
def test_an_account_key_that_cannot_be_told_is_not_guessed(body):
    """Two names besides the known ones, none, or one whose value is not
    the selected account's, and nothing is asked."""
    page = sb.Bank()
    page.first_body = body
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_with_no_statements_category_is_not_guessed_at():
    page = sb.Bank()
    page.listed = dict(page.listed, documentCategoryList=[{"docCategoryName": "Tax Documents",
                                                           "docCategoryId": "CAT-TAX"}])
    with pytest.raises(site.NotLearned):
        site.learn(page)


# -- every account, every year -------------------------------------------------

def test_every_account_and_year_is_asked_the_way_the_page_asks():
    page = sb.Bank()
    rows = site.collect_documents(page)
    asked = [(b["body"][sb.KEY], b["body"]["year"]) for b in page.lists]
    assert asked == [("K-ALPHA-0001", "2026"), ("K-ALPHA-0001", "2025"),
                     ("K-BRAVO-0002", "2026"), ("K-BRAVO-0002", "2025")]
    for b in page.lists:
        assert b["url"] == sb.LIST_URL
        assert b["body"]["docCategoryId"] == "CAT-STMT" and b["body"]["lang"] == "en"
        assert "cookie" not in b["headers"]
    assert [(r["account"], r["date"], r["document_id"], r["year"]) for r in rows] == [
        ("Everyday Checking", "2025-12-15", "DOC000000000091", "2025"),
        ("Everyday Checking", "2026-01-15", "DOC000000000101", "2026"),
        ("Everyday Checking", "2026-02-15", "DOC000000000102", "2026"),
        ("Travel Card", "2026-01-15", "DOC000000000201", "2026"),
    ]
    assert all(r["category"] == "Statement" for r in rows)
    no_presses(page)


def test_a_scoped_run_asks_only_its_years():
    page = sb.Bank()
    site.collect_documents(page, keep=lambda year: year == "2026")
    assert {b["body"]["year"] for b in page.lists} == {"2026"}


def test_a_row_of_another_category_is_left_out():
    page = sb.Bank()
    other = sb.row("DOC000000000301", sb.ACCOUNTS[0], "2026-01-15", category="CAT-TAX")
    page.answer_list = lambda body: (list(sb.STATEMENTS.get((body[sb.KEY], body["year"]), []))
                                     + ([other] if body[sb.KEY] == "K-ALPHA-0001" else []))
    ids = [r["document_id"] for r in site.collect_documents(page)]
    assert "DOC000000000301" not in ids and len(ids) == 4


def test_a_statement_under_another_accounts_key_stops_the_list():
    """In this account's answer it is no statement of this account, and an
    account written another way would leave every statement out."""
    page = sb.Bank()
    stray = sb.row("DOC000000000302", sb.ACCOUNTS[1], "2026-01-20")
    page.answer_list = lambda body: (list(sb.STATEMENTS.get((body[sb.KEY], body["year"]), []))
                                     + ([stray] if body[sb.KEY] == "K-ALPHA-0001" else []))
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_year_named_only_by_an_accounts_own_answer_is_asked_too():
    page = sb.Bank()
    page.years_for = lambda body: ["2026", "2025", "2024"] if body[sb.KEY] == "K-BRAVO-0002" else sb.YEARS
    site.collect_documents(page)
    asked = [(b["body"][sb.KEY], b["body"]["year"]) for b in page.lists]
    assert ("K-BRAVO-0002", "2024") in asked and ("K-ALPHA-0001", "2024") not in asked
    assert len(asked) == len(set(asked)), "a year was asked twice"


def test_an_answer_that_says_another_status_or_an_error_stops_the_list():
    page = sb.Bank()
    page.status_for = lambda body: "ERROR" if body[sb.KEY] == "K-BRAVO-0002" else "SUCCESS"
    with pytest.raises(site.ListCut):
        site.collect_documents(page)
    page = sb.Bank()
    page.errors_for = lambda body: [{"code": "E1"}] if body["year"] == "2025" else []
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_an_account_without_a_key_is_not_left_out_quietly():
    page = sb.Bank()
    keyless = {k: v for k, v in sb.ACCOUNTS[1].items() if k != sb.KEY}
    page.listed = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")], accounts=[sb.ACCOUNTS[0], keyless])
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_call_the_page_could_not_make_stops_the_list():
    page = sb.Bank()
    page.list_raises = RuntimeError("TypeError: Failed to fetch")
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


@pytest.mark.parametrize("path", [
    "/samplepg/standinsamplezz/zone/statements/v1/deleteDocuments",
    "/samplepg/standinsamplezz/zone/statements/v1/updateDocuments",
    "/sample/standin/zone/statements/v1/lookupDocuments",
])
def test_a_call_naming_a_change_or_of_another_shape_is_never_heard(path):
    page = sb.Bank()
    page.first_url = "https://secure.bankofamerica.com" + path
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_call_whose_body_was_not_json_is_not_heard():
    page = sb.Bank()
    page.headers = dict(page.headers, **{"content-type": "application/x-www-form-urlencoded"})
    with pytest.raises(site.NotLearned):
        site.learn(page)


@pytest.mark.parametrize("bad", [
    {"date": "", "dateString": ""},
    {"date": "2026-02-30"},
    {"date": "2026-01-15", "dateString": "Jan 16, 2026"},
    {"docId": ""},
    {"docId": 12345},
    {"docCategoryId": ""},
])
def test_a_statement_row_it_cannot_read_stops_the_list(bad):
    """A statement it cannot read is never left out of a list taken as
    whole, so the run stops instead."""
    page = sb.Bank()
    broken = dict(sb.row("DOC000000000401", sb.ACCOUNTS[0], "2026-03-15"), **bad)
    page.answer_list = lambda body: [broken] if body["year"] == "2026" else []
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_list_call_that_fails_part_way_stops_the_list():
    page = sb.Bank()
    page.list_status = 500
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_sign_in_part_way_through_the_list_is_a_session_that_ended():
    page = sb.Bank()
    page.list_status = 403
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)


# -- the PDF link's form --------------------------------------------------------

ROW = sb.row("DOC000000000101", sb.ACCOUNTS[0], "2026-01-15")


@pytest.mark.parametrize("href", [
    "https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101",
    "https://secure.bankofamerica.com/sample/getpdf?a=K-ALPHA-0001&doc=DOC000000000101&t=T1",
    "https://secure.bankofamerica.com/sample/DOC000000000101/view.pdf",
])
def test_a_link_comes_out_of_its_form_and_another_row_takes_the_same_form(href):
    form = site.template_of(href, ROW)
    assert form is not None and site.fill(form, ROW) == href
    other = sb.row("DOC000000000201", sb.ACCOUNTS[1], "2026-01-15")
    filled = site.fill(form, other)
    assert "DOC000000000201" in filled and "DOC000000000101" not in filled
    if "K-ALPHA-0001" in href:
        assert "K-BRAVO-0002" in filled and "K-ALPHA-0001" not in filled


def test_a_docid_written_escaped_is_filled_escaped():
    escaped_row = dict(ROW, docId="DOC/0000+0101")
    href = "https://secure.bankofamerica.com/sample/getpdf?doc=DOC%2F0000%2B0101"
    form = site.template_of(href, escaped_row)
    assert site.fill(form, escaped_row) == href
    assert site.fill(form, dict(escaped_row, docId="DOC/9999+0001")).endswith("DOC%2F9999%2B0001")


def test_a_docid_found_only_inside_a_longer_run_makes_no_form():
    short = dict(ROW, docId="DOC0099")
    assert site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=DOC00992", short) is None


def test_a_value_that_would_change_the_address_is_never_written_as_it_is():
    form = site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101", ROW)
    assert site.fill(form, dict(ROW, docId="DOC00/../x?y=1")) is None
    assert site.fill(form, dict(ROW, docId="DOC000000000555")).endswith("doc=DOC000000000555")


def test_a_link_without_its_rows_docid_has_no_form():
    assert site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=SOMETHINGELSE", ROW) is None
    assert site.learn_template([ROW], ["javascript:void(0)"]) == (None, 0)


def test_links_from_two_forms_are_not_taken():
    rows = [ROW, sb.row("DOC000000000102", sb.ACCOUNTS[0], "2026-02-15")]
    links = ["https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101",
             "https://secure.bankofamerica.com/other/fetch/DOC000000000102"]
    assert site.learn_template(rows, links) == (None, 2)


def test_a_page_that_draws_no_link_it_can_read_learns_no_form():
    page = sb.Bank()
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "javascript:void(0)"}]
    call = site.learn(page)
    assert call.template is None
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs


def test_a_link_off_the_site_is_never_read():
    page = sb.Bank()
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "https://evil.test/getpdf?doc=DOC000000000101"}]
    assert site.download_links(page) == []


# -- one statement's PDF --------------------------------------------------------

def test_a_statement_is_asked_for_at_its_own_rows_address():
    page = sb.Bank()
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000000201", year="2026")
    assert data.startswith(b"%PDF") and day == "2026-01-15"
    assert page.pdfs == [sb.LINK_BASE + "DOC000000000201"]
    no_presses(page)


def test_a_statement_no_longer_listed_is_not_asked_for():
    page = sb.Bank()
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000999999", year="2026")
    assert data is None and not page.pdfs
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-16",
                                    document_id="DOC000000000201", year="2026")
    assert data is None and not page.pdfs


def test_a_sign_in_instead_of_a_pdf_is_a_session_that_ended():
    page = sb.Bank()
    page.pdf_status = 401
    with pytest.raises(site.SessionExpired):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_pdf_that_ended_up_off_the_site_is_not_taken():
    page = sb.Bank()
    page.pdf_final_url = "https://evil.test/landing"
    with pytest.raises(site.SessionExpired):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_row_found_again_by_its_id_is_held_to_what_a_list_row_is():
    """A row under the same docId but of another category is not this
    statement, and nothing is asked for."""
    page = sb.Bank()
    taxed = sb.row("DOC000000000201", sb.ACCOUNTS[1], "2026-01-15", category="CAT-TAX")
    page.answer_list = lambda body: [taxed] if body[sb.KEY] == "K-BRAVO-0002" else []
    data, _day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                     document_id="DOC000000000201", year="2026")
    assert data is None and not page.pdfs


def test_a_statement_the_page_could_not_ask_for_stops_the_run():
    page = sb.Bank()
    page.pdf_raises = RuntimeError("TypeError: Failed to fetch")
    with pytest.raises(site.ListCut):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_form_on_another_host_than_the_pages_own_links_is_never_asked():
    page = sb.Bank()
    call = site.learn(page)
    call.template = "https://other.bankofamerica.com/getpdf?doc=\x00docId\x00"
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs


def test_a_form_that_would_leave_the_site_is_never_asked():
    page = sb.Bank()
    call = site.learn(page)
    call.template = "https://evil.test/getpdf?doc=\x00docId\x00"
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs


# -- dates ---------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("2026-01-15", "2026-01-15"), ("2026-01-15T00:00:00", "2026-01-15"),
    ("01/15/2026", "2026-01-15"), ("1/5/26", "2026-01-05"), ("Jan 15, 2026", "2026-01-15"),
    ("January 15, 2026", "2026-01-15"), ("2026-02-30", ""), ("13/01/2026", ""),
    ("yesterday", ""), ("", ""), (None, ""),
])
def test_dates_are_read_each_way_a_list_writes_them(text, want):
    assert site.parse_date(text) == want


def test_a_day_named_in_the_file_name_is_read():
    assert site.date_in_file_name('attachment; filename="eStmt_2026-01-15.pdf"') == "2026-01-15"
    assert site.date_in_file_name("attachment; filename=eStmt_2026-02-30.pdf") == ""
    assert site.date_in_file_name("inline") == ""


# -- what Diagnose may write -----------------------------------------------------

def test_what_was_learned_is_said_in_names_and_counts_never_a_value():
    page = sb.Bank()
    said = repr(site.learned_summary(site.learn(page)))
    for value in ("K-ALPHA-0001", "K-BRAVO-0002", "DOC000000000101", "TOKEN-T", "STANDINTOKEN",
                  "Everyday Checking", "Travel Card", "lookupDocuments", "getpdf", "2026-01-15"):
        assert value not in said, value
    assert "'pdf_form_learned': True" in said and "'accounts': 2" in said


def test_the_survey_reads_the_statements_page_and_presses_nothing():
    page = sb.Bank()
    report = site.survey(page, dwell_ms=0)
    assert report["list"]["accounts"] == 2 and report["pages"][0]["on_site"]
    assert "k=" not in report["pages"][0]["url"]
    no_presses(page)


def test_the_survey_of_another_page_reads_no_list():
    page = sb.Bank(url="https://secure.bankofamerica.com/myaccounts/overview/")
    report = site.survey(page, dwell_ms=0)
    assert report["list"]["stopped"] == "NotThere" and page.reloads == 0
