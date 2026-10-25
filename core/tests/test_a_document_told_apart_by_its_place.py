"""Capital One and Schwab take each document as the one its record names.

Both keep a document under its account, type, title and date, and tell two
documents sharing all four apart by their place in the provider's list,
since their ids are opaque (Schwab's README says not stable). Each download
lists that day again and takes whatever stands in the record's place.

When the provider lists such documents in another order, or lists a new one
ahead of one already saved, the place no longer names the same document.
One document was saved twice under two records and the other never, and
since both records then say saved, no later run took it.

Each app here runs through its own main, as the panel runs it, with a
made-up config and output folder. Only what the provider answers is stood
in, the list it gives in the order it gives it and a PDF for an id, each
PDF carrying the id of the document it is.
"""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import storage as core_storage

REPO = Path(__file__).resolve().parents[2]
DATE = "2026-09-12"
PAGE = SimpleNamespace(url="about:blank")


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(app.name + "_docs")
    finally:
        sys.path.pop(0)


def pdf_of(document_id: str) -> bytes:
    """A PDF that opens, with a page, carrying which document it is."""
    import io

    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "document %s" % document_id})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def whose(body: bytes) -> str:
    """The id of the document whose PDF this is."""
    return body.split(b"(document ", 1)[1].split(b")", 1)[0].decode()


class Provider:
    """The list in the order the provider gives it, and a PDF for an id.
    A document in `refused` answers an error, and taking one in `stop_at`
    stops the run there, as Stop does. `days` gives a document a day of its
    own, DATE otherwise.

    With `lasting` False the provider hands each document a new id in each
    session (`new_session`), and an id from an earlier session is refused,
    the way Schwab's README says its ids are not stable. With `per_call`
    too, each list it gives hands out new ids and refuses the ones before."""

    def __init__(self):
        self.ids = []
        self.refused = set()
        self.stop_at = set()
        self.asked = []
        self.days = {}
        self.lasting = True
        self.per_call = False
        self.session = 1
        self.call = 0
        self.then = None

    def new_session(self):
        self.session += 1

    def id_of(self, document: str) -> str:
        if self.lasting:
            return document
        return "%sV%d" % (document, self.call if self.per_call else self.session)

    def day_of(self, document: str) -> str:
        return self.days.get(document, DATE)

    def listed(self):
        if self.per_call:
            self.call += 1
        listed = [(self.id_of(document), self.day_of(document)) for document in self.ids]
        if self.then is not None:
            # What every list after this one gives.
            self.ids, self.then = self.then, None
        return listed

    def pdf(self, document_id: str):
        self.asked.append(document_id)
        document = document_id if self.lasting else document_id.split("V")[0]
        if document_id != self.id_of(document):
            return 404, b""
        if document in self.stop_at:
            raise KeyboardInterrupt
        if document in self.refused:
            return 500, b""
        return 200, pdf_of(document)


class CapitalOne(Provider):
    """A bank account's statements of one day."""

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_documents", lambda page: True)
        monkeypatch.setattr(site, "_fetch_json", self._json)
        monkeypatch.setattr(site, "fetch_pdf",
                            lambda page, doc_type, ref, rec: self.pdf(rec["document_id"]))

    def _json(self, page, url, headers, body=None):
        listed = []
        if url == self.site.API["search"]:
            listed = [{"documentId": i, "documentType": self.site.TYPE_BANK_STATEMENT,
                       "documentCategory": "STATEMENT", "documentName": "Monthly Statement",
                       "documentDate": day, "description": "360 Checking...1111",
                       "account": {"accountReferenceId": "REF1111"}}
                      for i, day in self.listed()]
        return {"status": 200, "body": {"documents": listed}}


class Schwab(Provider):
    """A brokerage account's trade confirmations of one day, two buys of
    one fund."""

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "_gateway_call", self._call)
        monkeypatch.setattr(site, "fetch_pdf", lambda page, doc: self.pdf(doc["documentId"]))

    def _call(self, page, url, headers, post_body=None):
        if url == self.site.API["accounts"]:
            body = {"accountSelectorData": {"brokerageAccountList": {"brokerageAccounts": [
                {"id": "11111111", "nickName": "Brokerage"}]}}}
        else:
            body = {"documents": [
                {"documentId": i, "documentName": "Confirm - EXAMPLE - Bought",
                 "type": self.site.TYPE_CONFIRMS, "onDemandDocumentType": "TradeConfirms",
                 "date": "%s/%s/%s" % (day[5:7], day[8:], day[:4]),
                 "accountDisplayName": "1111-1111"} for i, day in self.listed()]}
        return {"status": 200, "body": body}


class CapitalOneQuarterly(Provider):
    """A card account's quarterly statements of one day, which Capital One
    lists through its enterprise search for each card its first list names,
    and fetches by dataset."""

    CARD = "CARD0001"

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_documents", lambda page: True)
        monkeypatch.setattr(site, "_fetch_json", self._json)
        monkeypatch.setattr(site, "fetch_pdf", self._pdf)

    def _pdf(self, page, doc_type, ref, rec):
        if doc_type == self.site.TYPE_CARD_STATEMENT:
            return 200, pdf_of(self.CARD)
        assert doc_type == self.site.TYPE_CARD_QUARTERLY and rec["dataset_id"] == "DS1", rec
        return self.pdf(rec["document_id"])

    def _json(self, page, url, headers, body=None):
        listed = []
        if url == self.site.API["search"]:
            listed = [{"documentId": self.CARD, "documentType": self.site.TYPE_CARD_STATEMENT,
                       "documentCategory": "STATEMENT", "documentName": "Card Statement",
                       "documentDate": "2026-07-15", "description": "Savor...1234",
                       "account": {"accountReferenceId": "REF1234"}}]
        elif (url == self.site.API["ease_search"]
              and body["datasetAlias"] == ["QUARTER_ENDING_STATEMENT_v1"]):
            listed = [{"documentId": i, "datasetId": "DS1", "documentMetadata": [
                {"itemName": "documentDate", "itemValue": day},
                {"itemName": "documentType", "itemValue": "Card Quarterly Statement"}]}
                for i, day in self.listed()]
        return {"status": 200, "body": {"documents": listed}}


PROVIDERS = {"capitalone": CapitalOne, "capitalone-quarterly": CapitalOneQuarterly,
             "schwab": Schwab}
APPS = list(PROVIDERS)


class Home:
    """One app with a made-up config and output folder, run through its own
    main, and what the provider answers it."""

    def __init__(self, which: str, tmp_path: Path, monkeypatch, capsys):
        app = REPO / "apps" / which.split("-")[0]
        for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        config = json.loads((app / "config.example.json").read_text(encoding="utf-8"))
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
        })
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.out = Path(config["output_dir"])
        monkeypatch.setattr(self.mod.App, "page", lambda app: PAGE)
        monkeypatch.setattr(self.mod.App, "_on_its_site", lambda app: PAGE)
        monkeypatch.setattr(self.mod.App, "check_session", lambda app, *_a, **_kw: None)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        self.provider = PROVIDERS[which](self.mod.site, monkeypatch)

    def run(self, *flags) -> str:
        """The app's own main, as the panel starts it, and what it said."""
        self.capsys.readouterr()
        self.mod.main(["--config", str(self.cfg), *flags])
        return " ".join(self.capsys.readouterr().out.split())

    def run_all(self, *flags) -> str:
        return self.run("--all", "--yes", *flags)

    def on_disk(self) -> list:
        """Whose PDF each file under the output folder holds."""
        return sorted(document for document in (whose(p.read_bytes())
                                                for p in self.out.rglob("*.pdf"))
                      if document != CapitalOneQuarterly.CARD)

    def held(self) -> dict:
        """Whose PDF each saved record's file holds, by key."""
        progress = json.loads((self.out / "progress.json").read_text(encoding="utf-8"))
        held = {key: whose(Path(rec["pdf_path"]).read_bytes())
                for key, rec in sorted(progress.items())
                if isinstance(rec, dict) and rec.get("downloaded_ok")}
        return {key: document for key, document in held.items()
                if document != CapitalOneQuarterly.CARD}

    def left_for_a_person(self) -> dict:
        """The notes of every record marked for manual review, by key."""
        progress = json.loads((self.out / "progress.json").read_text(encoding="utf-8"))
        return {key: rec.get("notes", "") for key, rec in sorted(progress.items())
                if isinstance(rec, dict) and rec.get("state") == "Needs Manual Review"}


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


each_app = pytest.mark.parametrize("home", APPS, indirect=True)


@each_app
def test_a_document_listed_first_beside_one_already_saved_is_downloaded(home):
    """A second document of one day, type, title and account, listed ahead
    of the one already saved, took the saved one's place, so the saved one
    was taken again as the new one and the new one never at all."""
    home.provider.ids = ["ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_a_document_that_failed_is_the_one_taken_again(home):
    """The second of two documents failed. Listed the other way around the
    next time, the run took the first one again in its place."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.refused = set()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_resume_takes_the_document_the_run_stopped_at(home):
    """Stopped before the second of two documents, Resume lists nothing of
    its own and took whatever stood in the second place on the day it ran."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.stop_at = set()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_download_again_takes_each_record_its_own_document(home):
    """Download again after a listing in the other order took each record's
    place afresh, so each record's new file held the other document. Both
    came back, since Download again saves beside a file and takes both, but
    a Pilot count that takes only the first leaves both records on the
    second document and the first one's earlier file held by no record."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    before = home.held()
    assert sorted(before.values()) == ["ST0001", "ST0002"]

    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all("--redownload", "--year", DATE[:4])
    assert home.held() == before


@each_app
def test_an_id_kept_for_a_document_is_never_another_documents(home):
    """When the list no longer has a record's place, the download falls back
    to the id the record keeps. A listing in the other order had written the
    first document's id over the second's, so the second's record took the
    first document."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    home.provider.ids = ["ST0002", "ST0001"]
    home.provider.refused = {"ST0001", "ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.refused = set()
    home.provider.ids = ["ST0001"]
    home.run("--resume")
    saved = home.on_disk()
    assert len(set(saved)) == len(saved), home.held()


@each_app
def test_a_new_document_beside_one_saved_is_downloaded_while_another_is_no_longer_listed(home):
    """Two alike saved. The list then gives the first again and a new one,
    and no longer the second. The first answering by its id says these ids
    last, so the new one is a document of its own and not the second."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    home.provider.ids = ["ST0001", "ST0003"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0003"], home.held()


@each_app
def test_a_new_document_beside_one_saved_is_downloaded_later_in_its_session(home):
    """Ids that change each session. The session's first run gave the
    statement saved last session this session's id, and a second statement
    alike is listed beside it later that session."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001"]
    home.run_all()

    home.provider.new_session()
    home.run_all()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()
    assert home.left_for_a_person() == {}


@each_app
def test_a_document_listed_in_place_of_one_saved_is_taken_for_it_as_before(home):
    """A corrected statement listed instead of the one saved, on its day and
    under its title, with nothing alike beside it. That the other days'
    documents answered by their ids says nothing of this one's, so it is
    taken for the one saved, as before, and nothing is downloaded twice."""
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0009", "ST0001"]
    home.run_all()
    home.provider.ids = ["ST0009", "ST0002"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0009"], home.held()
    assert home.left_for_a_person() == {}


@each_app
def test_an_archive_whose_ids_a_listing_swapped_takes_neither_document_twice(home):
    """Before this, a listing in the other order wrote each document's id
    over the other's record. Such an archive, the first saved and the second
    failed, is listed again in its first order."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    found = home.out / "discovery.json"
    discovery = json.loads(found.read_text(encoding="utf-8"))
    first, second = sorted(key for key, rec in discovery.items()
                           if rec["document_id"] != CapitalOneQuarterly.CARD)
    discovery[first]["document_id"], discovery[second]["document_id"] = "ST0002", "ST0001"
    found.write_text(json.dumps(discovery), encoding="utf-8")

    home.provider.refused = set()
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()
    assert home.left_for_a_person() == {}


# -- when the provider's ids do not last -------------------------------------
#
# Schwab's README says its ids are not stable. Here each session hands each
# document a new id and refuses one from an earlier session. A document alone
# on its day is still taken. Two alike, where which one was saved cannot be
# told, are left for a person rather than guessed at.

NOT_TOLD = "does not say which one this is"


@each_app
def test_two_documents_listed_together_are_each_taken_once_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"]

    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"]
    assert home.left_for_a_person() == {}


@each_app
def test_a_document_alone_on_its_day_is_taken_once_when_its_id_did_not_last(home):
    """Stopped before it, then Resume in a session that lists it under a new
    id, and then a run that lists it under another."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001"]
    home.provider.stop_at = {"ST0001"}
    home.run_all()
    assert home.on_disk() == []

    home.provider.stop_at = set()
    home.provider.new_session()
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    progress = json.loads((home.out / "progress.json").read_text(encoding="utf-8"))
    assert [rec["document_id"] for rec in progress.values()
            if rec["document_id"] != CapitalOneQuarterly.CARD] == [
        home.provider.id_of("ST0001")], "the record keeps an id it was not saved under"
    home.provider.new_session()
    home.run_all()
    assert home.on_disk() == ["ST0001"]


@each_app
def test_a_new_document_beside_one_saved_is_left_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001"]
    home.run_all()

    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    said = home.run_all()
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left
    assert NOT_TOLD in said

    for order in (["ST0001", "ST0002"], ["ST0002", "ST0001"]):
        home.provider.new_session()
        home.provider.ids = order
        home.run_all()
        home.run("--resume")
    assert home.on_disk() == ["ST0001"]


@each_app
def test_download_again_keeps_two_alike_saved_when_their_ids_did_not_last(home):
    """Two alike saved last session, and Download again this session, whose
    list says nothing of which is which. Neither is taken, both saved
    records stand as they were, and no later run fetches either again."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    before = home.held()

    home.provider.new_session()
    said = home.run_all("--redownload", "--year", DATE[:4])
    assert home.held() == before
    assert NOT_TOLD in said and "The copy saved before is kept" in said, said[-600:]
    home.provider.new_session()
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_a_failed_document_is_left_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()

    home.provider.refused = set()
    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


@each_app
def test_resume_leaves_a_document_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()

    home.provider.stop_at = set()
    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


@each_app
def test_a_second_run_in_one_session_takes_nothing_again_when_ids_do_not_last(home):
    """Run pressed twice in one session. The first run gave the statement
    saved last session this session's id, and the second must know it by
    that id, though it was saved under the old one."""
    home.provider.lasting = False
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0001"]
    home.run_all()

    home.provider.new_session()
    home.provider.ids = ["ST0001", "ST0009"]
    home.run_all()
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0009"], home.held()
    home.provider.new_session()
    home.run_all()
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0009"], home.held()


@each_app
def test_two_alike_saved_before_are_not_taken_again_by_a_second_run_in_one_session(home):
    """The first run of a session gave the lone statement of another day this
    session's id. That it then answered by that id in the second run says
    nothing of the ids the two alike were saved under last session."""
    home.provider.lasting = False
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0001", "ST0002", "ST0009"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0009"]

    for _ in range(2):
        home.provider.new_session()
        home.run_all()
        home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0009"], home.held()


@each_app
def test_one_of_two_alike_failed_is_never_taken_as_the_other_by_a_second_run(home):
    home.provider.lasting = False
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0001", "ST0002", "ST0009"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    home.provider.refused = set()

    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001", "ST0009"]
    home.run_all()
    home.run_all()
    saved = home.on_disk()
    assert len(set(saved)) == len(saved), home.held()


@each_app
def test_two_documents_are_each_taken_once_when_each_list_gives_new_ids(home):
    """Ids that change on every list the provider gives, and an id from an
    earlier list refused. Two alike, listed for the first time, were taken
    by their place within the run, and still are."""
    home.provider.lasting = False
    home.provider.per_call = True
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0001", "ST0002", "ST0009"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0009"], home.held()
    assert home.left_for_a_person() == {}
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0009"], home.held()


@each_app
def test_a_place_is_never_gone_by_once_the_list_changed_within_the_run(home):
    """Ids that change on every list. The run's own list gave two alike, and
    by the time of the downloads a third alike stands ahead of them, so
    neither place still names the document it named."""
    home.provider.lasting = False
    home.provider.per_call = True
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.then = ["ST0003", "ST0001", "ST0002"]
    home.run_all()
    assert home.on_disk() == [], home.held()
    left = home.left_for_a_person()
    assert len(left) == 2 and all(NOT_TOLD in why for why in left.values()), left


@each_app
def test_resume_never_takes_the_one_still_listed_for_the_other_when_ids_do_not_last(home):
    """Two alike, the first saved, Stop before the second. The day's list
    then gives only one of them, under a new id, which is the one saved."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()

    home.provider.stop_at = set()
    home.provider.new_session()
    home.provider.ids = ["ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


# -- the numbering itself ------------------------------------------------------

def test_with_no_id_kept_the_numbers_are_those_an_archive_already_has():
    """told_apart numbers as stable_occurrences does whenever no id decides
    and the archive was numbered by the same fields, so every key an archive
    has stays."""
    from paperpull_core.keys import stable_occurrences, told_apart
    fields = ("doc_type", "title", "date")

    def row(account, document_id="", doc_type="BANK", title="Monthly Statement",
            date=DATE):
        return {"doc_type": doc_type, "title": title, "date": date,
                "account": account, "document_id": document_id}

    def known(*pairs):
        return {"k%d" % i: dict(row(account), occurrence=occurrence)
                for i, (account, occurrence) in enumerate(pairs)}

    cases = [
        ([row("A"), row("B")], {}),
        ([row("B"), row("A")], known(("A", 0), ("B", 1))),
        ([row("A"), row("A"), row("A")], known(("A", 0), ("A", 1))),
        ([row("A", "x1"), row("A", "x2")], known(("A", 0), ("A", 1))),
        ([row("A"), row("B", doc_type="CARD"), row("A", date="2026-08-12")],
         known(("A", 0))),
    ]
    for rows, existing in cases:
        got = [occurrence for occurrence, _sure in told_apart(
            rows, existing, fields=fields)]
        assert got == stable_occurrences(rows, existing, fields=fields), (rows, existing)


def test_rows_alike_take_every_number_their_records_hold():
    """One account's two documents alike, numbered 1 and 2 across accounts,
    listed again with ids that answer nothing. They keep 1 and 2 in any
    order, and neither is given 0, which no record of that account holds.
    Each account is numbered on its own, as up to 0.33."""
    from paperpull_core.keys import told_apart
    fields = ("doc_type", "title", "date", "account")

    def row(account):
        return {"doc_type": "BANK", "title": "Monthly Statement", "date": DATE,
                "account": account, "document_id": "new"}

    def known(*pairs):
        return {"k%d" % i: dict(row(account), occurrence=occurrence, document_id="old%d" % i)
                for i, (account, occurrence) in enumerate(pairs)}

    across = known(("A", 0), ("B", 1), ("B", 2))
    for accounts, want in [("ABB", [0, 1, 2]), ("BBA", [1, 2, 0]), ("BAB", [1, 0, 2])]:
        got = [occurrence for occurrence, _sure in told_apart(
            [row(a) for a in accounts], across, fields=fields)]
        assert got == want, accounts
    each = known(("A", 0), ("B", 0))
    assert [occurrence for occurrence, _sure in told_apart(
        [row("B"), row("A")], each, fields=fields)] == [0, 0]
    # A third alike in the account takes a number neither record holds.
    assert [occurrence for occurrence, _sure in told_apart(
        [row("B"), row("B"), row("B")], across, fields=fields)] == [1, 2, 0]


# -- two accounts' documents of one day --------------------------------------
#
# Both apps keep a document under its account, and up to 0.33 their sites
# numbered each account's documents on their own. From 0.34 to 0.58 they
# were numbered across accounts, so a statement saved at 0 in a second
# account found 0 taken by the first, was numbered 1, and was downloaded
# again beside the one saved (#122). An archive numbered either way keeps
# every number it has and fetches nothing again. Each document here is named
# by its account's letter, A or B.

class CapitalOneAccounts(Provider):
    """Two bank accounts' statements of one day."""

    ACCOUNTS = {"A": ("360 Checking...1111", "REF1111"),
                "B": ("360 Savings...2222", "REF2222")}

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_documents", lambda page: True)
        monkeypatch.setattr(site, "_fetch_json", self._json)
        monkeypatch.setattr(site, "fetch_pdf",
                            lambda page, doc_type, ref, rec: self.pdf(rec["document_id"]))

    def _json(self, page, url, headers, body=None):
        listed = []
        if url == self.site.API["search"]:
            listed = [{"documentId": i, "documentType": self.site.TYPE_BANK_STATEMENT,
                       "documentCategory": "STATEMENT", "documentName": "Monthly Statement",
                       "documentDate": day, "description": self.ACCOUNTS[i[0]][0],
                       "account": {"accountReferenceId": self.ACCOUNTS[i[0]][1]}}
                      for i, day in self.listed()]
        return {"status": 200, "body": {"documents": listed}}


class SchwabAccounts(Provider):
    """Two brokerage accounts' trade confirmations of one day."""

    ACCOUNTS = {"A": ("11111111", "Brokerage"), "B": ("22222222", "Example Trust")}

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "_gateway_call", self._call)
        monkeypatch.setattr(site, "fetch_pdf", lambda page, doc: self.pdf(doc["documentId"]))

    def _call(self, page, url, headers, post_body=None):
        if url == self.site.API["accounts"]:
            body = {"accountSelectorData": {"brokerageAccountList": {"brokerageAccounts": [
                {"id": number, "nickName": nick} for number, nick in self.ACCOUNTS.values()]}}}
        else:
            body = {"documents": [
                {"documentId": i, "documentName": "Confirm - EXAMPLE - Bought",
                 "type": self.site.TYPE_CONFIRMS, "onDemandDocumentType": "TradeConfirms",
                 "date": "%s/%s/%s" % (day[5:7], day[8:], day[:4]),
                 "accountDisplayName": "%s-%s" % (self.ACCOUNTS[i[0]][0][:4],
                                                  self.ACCOUNTS[i[0]][0][4:])}
                for i, day in self.listed()]}
        return {"status": 200, "body": body}


TWO_ACCOUNTS = {"capitalone": CapitalOneAccounts, "schwab": SchwabAccounts}


@pytest.fixture
def two(request, tmp_path, monkeypatch, capsys):
    home = Home(request.param, tmp_path, monkeypatch, capsys)
    home.provider = TWO_ACCOUNTS[request.param](home.mod.site, monkeypatch)
    return home


def numbered_as(home, across: bool) -> None:
    """Every record numbered as an earlier version numbered it, in the order
    the list first gave them, and keyed again with that number. Up to 0.33
    each account on its own, from 0.34 to 0.58 across accounts."""
    stores = {name: json.loads((home.out / name).read_text(encoding="utf-8"))
              for name in ("discovery.json", "progress.json")}
    seen, number = {}, {}
    for key, record in stores["discovery.json"].items():
        group = (record["doc_type"], record["title"], record["date"])
        if not across:
            group += (record["account"],)
        number[key] = seen.get(group, 0)
        seen[group] = number[key] + 1
    for name, records in stores.items():
        rewritten = {}
        for key, record in records.items():
            record["occurrence"] = number[key]
            base = key.split("#")[0]
            rewritten[base + ("#%d" % number[key] if number[key] else "")] = record
        (home.out / name).write_text(json.dumps(rewritten), encoding="utf-8")


@pytest.mark.parametrize("two", list(TWO_ACCOUNTS), indirect=True)
@pytest.mark.parametrize("across", [False, True], ids=["each_account", "across_accounts"])
@pytest.mark.parametrize("lasting", [True, False], ids=["ids_last", "ids_do_not_last"])
@pytest.mark.parametrize("listed", [["A1", "B1"], ["A1", "B1", "B2"]],
                         ids=["one_each", "two_alike_in_one"])
def test_an_archive_keeps_each_accounts_numbers_and_fetches_nothing_again(
        two, across, lasting, listed):
    two.provider.lasting = lasting
    two.provider.ids = list(listed)
    two.run_all()
    assert two.on_disk() == sorted(listed)
    numbered_as(two, across)
    saved = sorted(json.loads((two.out / "progress.json").read_text(encoding="utf-8")))

    # Listed the other way around, so no account is first by luck, and with
    # a statement of each account on a day of its own, which is new.
    two.provider.new_session()
    two.provider.days = {"A9": "2026-08-12", "B9": "2026-08-12"}
    two.provider.ids = list(reversed(listed)) + ["A9", "B9"]
    two.provider.asked = []
    said = two.run_all()
    asked = [i if lasting else i.split("V")[0] for i in two.provider.asked]
    assert sorted(asked) == ["A9", "B9"], said[-600:]
    assert two.on_disk() == sorted(listed + ["A9", "B9"]), two.held()
    assert two.left_for_a_person() == {}
    known = json.loads((two.out / "discovery.json").read_text(encoding="utf-8"))
    assert set(saved) <= set(known) and len(known) == len(saved) + 2, sorted(known)


@pytest.mark.parametrize("two", list(TWO_ACCOUNTS), indirect=True)
@pytest.mark.parametrize("lasting", [True, False], ids=["ids_last", "ids_do_not_last"])
def test_an_archive_that_took_a_statement_again_on_0_34_takes_nothing_more(
        two, lasting, monkeypatch):
    """Saved up to 0.33, each account on its own, then run on 0.34 to 0.58,
    which numbered across accounts and took the second account's statement
    again under 1, beside the one saved at 0. Both records and both files
    stay as they are, and nothing more is fetched."""
    from paperpull_core.keys import told_apart
    two.provider.lasting = lasting
    two.provider.ids = ["A1", "B1"]
    two.run_all()
    numbered_as(two, across=False)

    with monkeypatch.context() as m:
        # That run's numbering, the account left out.
        m.setattr(two.mod, "_told_apart", lambda rows, existing=None, fields=(), **kw:
                  told_apart(rows, existing, tuple(f for f in fields if f != "account"), **kw))
        two.provider.new_session()
        two.run_all()
    assert two.on_disk() == ["A1", "B1", "B1"], two.held()
    saved = sorted(json.loads((two.out / "progress.json").read_text(encoding="utf-8")))
    assert len(saved) == 3

    for order in (["A1", "B1"], ["B1", "A1"]):
        two.provider.new_session()
        two.provider.ids = order
        two.provider.asked = []
        said = two.run_all()
        assert two.provider.asked == [], said[-600:]
    assert two.on_disk() == ["A1", "B1", "B1"], two.held()
    assert two.left_for_a_person() == {}
    known = json.loads((two.out / "discovery.json").read_text(encoding="utf-8"))
    assert sorted(known) == saved


def test_every_app_that_tells_documents_apart_numbers_by_its_whole_key():
    """An app numbering documents with told_apart names, in `fields`, every
    field its key is made of but the number. Numbered across a field its key
    holds, two documents saved at 0 in that field's two values were one
    group, so the second found 0 taken and was downloaded again (#122).

    stable_occurrences is not held to this. Its apps whose key holds a field
    their numbering leaves out (the category, or the account in IBKR and
    Vanguard) have numbered the same way since each shipped, so their
    archives were never numbered otherwise, and changing it now would."""
    import ast

    def strings(node):
        if isinstance(node, (ast.Tuple, ast.List)):
            return {e.value for e in node.elts if isinstance(e, ast.Constant)}
        return None

    found = {}
    for path in sorted(REPO.glob("apps/*/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {alias.asname or alias.name for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module == "paperpull_core.keys"
                 for alias in node.names if alias.name == "told_apart"}
        if not names:
            continue
        keys = [{n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                 and isinstance(n.value, ast.Name) and n.value.id == "self"} - {"occurrence"}
                for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
                for fn in cls.body if isinstance(fn, ast.FunctionDef) and fn.name == "key"]
        assert len(keys) == 1, path
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            bound = {t.id: strings(n.value) for n in ast.walk(func) if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)}
            for call in [n for n in ast.walk(func) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id in names]:
                given = [kw.value for kw in call.keywords if kw.arg == "fields"]
                assert given, "%s numbers by title and date alone" % path.name
                fields = (bound.get(given[0].id) if isinstance(given[0], ast.Name)
                          else strings(given[0]))
                assert fields is not None, "%s: fields not read" % path.name
                assert keys[0] <= fields, "%s numbers across %s, which its key holds" % (
                    path.name, ", ".join(sorted(keys[0] - fields)))
                found[path.parent.name] = sorted(fields)
    assert {"capitalone", "schwab"} <= set(found), found
