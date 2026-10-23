"""Bank of America's guard, host allowlist and document kinds.
Invented values only, never a real account's."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import bofa_docs as app_mod
import bofa_site as site
from paperpull_core import doc_types


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Bank of America"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Statements", "Tax Documents", "Other Documents"]
    assert storage.SPEC.routes[storage.STATEMENT] == "statements"
    assert storage.SPEC.routes[storage.TAX] == "tax_documents"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement", "Tax Document"]


@pytest.mark.parametrize("title,category,summary", [
    ("Monthly Statement", "Statement", "Monthly Statement"),
    ("1099-INT", "Tax Document", "1099-INT Tax Form"),
    ("1098 Mortgage Interest", "Tax Document", "1098 Tax Form"),
])
def test_bank_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


@pytest.mark.parametrize("name", [
    "Transfer | Zelle", "Send money with Zelle", "Pay bills", "Make a payment",
    "Schedule a payment", "Set up AutoPay", "Transfer between accounts",
    "Deposit a check", "Wire transfer", "Cash advance", "Balance transfer offers",
    "Redeem rewards", "BankAmeriDeals", "Keep the Change", "Lock card",
    "Unlock card", "Replace card", "Report a lost or stolen card",
    "Set travel notice", "Request a credit limit increase", "Order checks",
    "Request statement copies", "Stop payment", "Open a new account",
    "Close account", "Apply now", "Balance Connect for overdraft protection",
    "Manage alerts", "Go paperless", "Paperless settings", "Change Online ID",
    "Update contact info", "Edit nickname", "Ask Erica", "Chat with us",
    "Dispute a transaction", "Log Out", "Sign out", "Buy", "Sell",
    "Download | Make a payment",
])
def test_moving_money_and_changing_the_account_are_never_safe(name):
    assert not site.is_safe_control(name), name


@pytest.mark.parametrize("name", [
    "Download", "Download PDF", "View statement", "Statements & Documents",
    "Credit card statement", "Download statement", "1099-INT", "Tax documents",
    "View PDF", "See older statements",
])
def test_reading_a_document_is_safe(name):
    assert site.is_safe_control(name), name


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit card statement")   # "edit" inside Credit
    assert not site.is_safe_control("Edit statement nickname")


def test_only_bankofamerica_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.bankofamerica.com/")
    assert site.is_safe_url("https://secure.bankofamerica.com/a/b")
    assert not site.is_safe_url("http://www.bankofamerica.com/")          # not https
    assert not site.is_safe_url("https://www.bankofamerica.com.example/")
    assert not site.is_safe_url("https://notbankofamerica.com/")
    assert not site.is_safe_url("https://bankofamerica.com@evil.test/")
    assert not site.is_safe_url("https://www.bankofamerica.com:8443/")
    # Merrill and the bank's asset hosts are other hosts, never acted on.
    assert not site.is_safe_url("https://olui2.fs.ml.com/")
    assert not site.is_safe_url("https://www1.bac-assets.com/")


def test_the_sign_in_address_is_the_one_the_request_names():
    assert site.URLS["login"] == "https://www.bankofamerica.com/"
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["home"])


def test_the_document_key_tells_two_accounts_apart():
    one = app_mod.Document(category="Statement", date="2026-03-31", title="Statement",
                           account="Adv Plus Banking - 1111")
    two = app_mod.Document(category="Statement", date="2026-03-31", title="Statement",
                           account="Adv Plus Banking - 2222")
    assert one.key != two.key
