"""A new name typed in Review Names keeps the "(1 of 2)" of an order split
into several invoices.

An order that came as several invoices is saved with its part at the end of
each name, "2026-05-14 Target Unsure Item Invoice (1 of 2).pdf", by Target
and by Amazon. Rename keeps it, reading the part from the file's own name
(renaming._part_of), since only the file knows it. Review Names built the new
name without it, so the first invoice of a split order was renamed as though
it were the whole order, "2026-05-14 Target Garden Hose Invoice.pdf", and no
later Rename could put it back, since the name it reads the part from had
lost it.

These run each receipt app's own review_names over an output folder on disk,
with the typing stood in for, and then the app's Rename over what the review
left. Every name, number and answer is invented.
"""
import argparse
import ast
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import renaming
from paperpull_core.models import ONLINE, Item, Purchase, State

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d)
              and "def cmd_review_names" in entry_of(d).read_text(encoding="utf-8"))


def names_parts(source: Path) -> bool:
    """Whether a file names a document with a part, a call to
    build_pdf_filename handing it part= anything but None."""
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "build_pdf_filename":
            continue
        for kw in node.keywords:
            if kw.arg == "part" and not (isinstance(kw.value, ast.Constant)
                                         and kw.value.value is None):
                return True
    return False


# Every app that saves a document with a part in its name, found by what its
# code does. Rename's own call in the core is not an app's.
PARTED = sorted(d.name for d in (REPO / "apps").iterdir()
                if d.is_dir() and any(names_parts(f) for f in d.glob("*.py")))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


@pytest.fixture(autouse=True)
def default_names():
    """Files named the default way, whatever a test before this one chose."""
    from paperpull_core import storage
    storage.set_filename_owner("")
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def app_in(mod, out: Path):
    """The app's own downloader over an output folder on disk, without its
    __init__, which would want a config file and a console."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    inst.args = argparse.Namespace(redownload=False, apply=False)
    inst.paths = storage.Paths(out)
    inst.paths.ensure()
    backups = inst.paths.backups
    inst.progress = storage.JsonStore(inst.paths.progress_json, backups)
    inst.discovery = storage.JsonStore(inst.paths.discovery_json, backups)
    inst.index_csv = storage.CsvFile(inst.paths.receipt_index_csv,
                                     storage.RECEIPT_INDEX_COLUMNS, backups)
    inst.order_csv = storage.CsvFile(inst.paths.order_history_csv,
                                     storage.ORDER_HISTORY_COLUMNS, backups)
    return inst


def invoice(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.4\n% invented invoice " + name.encode() + b"\n%%EOF\n")
    return path


def split_order(number: str = "ORDER-0001") -> Purchase:
    return Purchase(purchase_type=ONLINE, purchase_date="2026-05-14", order_number=number,
                    summary="Unsure Item", confidence="Low", document_type="Invoice",
                    items=[Item(name="Invented Garden Item")])


def name_of(purchase: Purchase, summary: str, part) -> str:
    from paperpull_core.storage import build_pdf_filename
    return build_pdf_filename(purchase.purchase_date, summary, "Invoice", part=part,
                              record=purchase)


def review_then_rename(mod, inst, monkeypatch, answers=("Garden Hose",)):
    """The person types the new names in turn for the receipts offered,
    then runs Rename with --apply. What was asked, how many files Rename
    renamed, and what it said."""
    asked = []
    monkeypatch.setattr(mod, "ask",
                        lambda prompt: asked.append(prompt) or answers[len(asked) - 1])
    inst.cmd_review_names()
    said = []
    result = renaming.run_for(inst, apply_changes=True, say=said.append)
    return asked, result.renamed, said


def test_the_apps_that_name_a_part_have_review_names():
    """Not passing for want of an app to look at. Target and Amazon save
    each invoice of a split order with its part, and both are reviewed."""
    assert {"amazon", "target"} <= set(PARTED), PARTED
    assert set(PARTED) <= {a.name for a in APPS}, (PARTED, [a.name for a in APPS])


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_keeps_the_part_of_a_split_order(app, tmp_path, monkeypatch):
    """The first invoice of an order split in two, saved and marked for
    review for its name, as each app's own run writes one down. The second
    is beside it, named in the record's notes alone, as Amazon keeps it.
    A new name keeps "(1 of 2)", the record and both CSVs follow it, the
    second invoice takes the new name with its own part, and the Rename
    after it finds nothing to change. An order that came whole, reviewed in
    the same run, is given no part."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first = invoice(folder, name_of(purchase, "Unsure Item", (1, 2)))
    second = invoice(folder, name_of(purchase, "Unsure Item", (2, 2)))
    assert first.name.endswith(" Unsure Item Invoice (1 of 2).pdf"), first.name
    purchase.pdf_path, purchase.pdf_filename = str(first), first.name
    inst._record_state(purchase, State.PDF_VERIFIED, notes="Also saved " + second.name,
                       extra={"pdf_size": first.stat().st_size, "pdf_pages": 1,
                              "downloaded_ok": True})
    inst._write_csv_rows(purchase, receipt_status="Downloaded",
                         processing_status="Review Needed")
    inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                       notes="Low classification confidence")
    second_bytes = second.read_bytes()
    whole = split_order("ORDER-0002")
    alone = invoice(folder, name_of(whole, "Unsure Item", None))
    whole.pdf_path, whole.pdf_filename = str(alone), alone.name
    inst._record_state(whole, State.PDF_VERIFIED, extra={
        "pdf_size": alone.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
    inst._write_csv_rows(whole, receipt_status="Downloaded", processing_status="Review Needed")
    inst._record_state(whole, State.NEEDS_MANUAL_REVIEW, notes="Low classification confidence")

    asked, renamed, said = review_then_rename(mod, inst, monkeypatch, ("Garden Hose", "Lamp"))

    wanted = name_of(purchase, "Garden Hose", (1, 2))
    wanted_second = name_of(purchase, "Garden Hose", (2, 2))
    lamp = name_of(whole, "Lamp", None)
    assert wanted.endswith(" Garden Hose Invoice (1 of 2).pdf"), wanted
    assert lamp.endswith(" Lamp Invoice.pdf"), lamp
    assert len(asked) == 2
    assert sorted(p.name for p in folder.iterdir()) == sorted([wanted, wanted_second, lamp])
    assert (folder / wanted_second).read_bytes() == second_bytes
    record = inst.progress.get(purchase.key)
    assert (record["pdf_filename"], record["pdf_path"]) == (wanted, str(folder / wanted))
    assert inst.progress.get(whole.key)["pdf_filename"] == lamp
    assert [r["PDF Filename"] for r in inst.index_csv.read_all()] == [wanted, lamp]
    assert {r["PDF Filename"] for r in inst.order_csv.read_all()} == {wanted, lamp}
    assert renamed == 0, "Rename agrees with the names the review gave, %s" % said


def saved(inst, folder: Path, purchase: Purchase, part, name: str = "") -> Path:
    """An invoice of `purchase` on disk with its record and both CSVs, as
    the app's own run writes them down, marked for review when the
    purchase's confidence is Low. Named for its summary and part, or `name`
    when a download told it apart."""
    path = invoice(folder, name or name_of(purchase, purchase.summary, part))
    purchase.pdf_path, purchase.pdf_filename = str(path), path.name
    inst._record_state(purchase, State.PDF_VERIFIED, extra={
        "pdf_size": path.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
    unsure = purchase.confidence == "Low"
    inst._write_csv_rows(purchase, receipt_status="Downloaded",
                         processing_status="Review Needed" if unsure else "Completed")
    if unsure:
        inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                           notes="Low classification confidence")
    else:
        inst._record_state(purchase, State.COMPLETED)
    return path


def another_order(summary: str, number: str = "ORDER-0009") -> Purchase:
    """A purchase of the same day whose name nobody doubted."""
    other = split_order(number)
    other.summary, other.confidence = summary, "High"
    return other


@pytest.mark.parametrize("part", [(1, 2), None], ids=["part", "whole"])
@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_another_order_holds_is_told_apart_as_rename_tells_it(
        app, part, tmp_path, monkeypatch):
    """The name typed is already another order's file. The review tells the
    file apart by its order number, as a download and Rename do, and keeps
    its part. Told apart by " (2)", the first invoice of a split order was
    "... Garden Hose Invoice (1 of 2) (2).pdf", the next Rename read no part
    from it and moved it to "... Garden Hose Invoice.pdf", and an order that
    came whole went from "... Lamp Invoice (2).pdf" to "... Lamp Invoice
    ORDER-0001.pdf"."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    other = another_order("Garden Hose")
    held = saved(inst, folder, other, part)
    purchase = split_order()
    saved(inst, folder, purchase, part)

    asked, renamed, said = review_then_rename(mod, inst, monkeypatch)

    wanted = Path(name_of(purchase, "Garden Hose", part))
    wanted = wanted.stem + " ORDER-0001" + wanted.suffix
    assert len(asked) == 1
    assert sorted(p.name for p in folder.iterdir()) == sorted([held.name, wanted])
    assert inst.progress.get(purchase.key)["pdf_filename"] == wanted
    assert inst.progress.get(other.key)["pdf_filename"] == held.name
    assert renamed == 0, "Rename agrees with the name the review gave, %s" % said


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_part_a_download_told_apart_is_kept(app, tmp_path, monkeypatch):
    """The first invoice of a split order whose name another order's file
    had when it was saved, "... Unsure Item Invoice (1 of 2) ORDER-0001.pdf"
    as a download writes it. Rename leaves it as it is, and a new name
    typed for it keeps "(1 of 2)". Both read no part from a name with the
    order number after it, so Rename moved it to "... Unsure Item
    Invoice.pdf" and the review to "... Garden Hose Invoice.pdf"."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    other = another_order("Unsure Item")
    held = saved(inst, folder, other, (1, 2))
    purchase = split_order()
    told = Path(held.name)
    told = saved(inst, folder, purchase, (1, 2),
                 name=told.stem + " ORDER-0001" + told.suffix)

    said = []
    alone = renaming.run_for(inst, apply_changes=True, say=said.append)
    assert alone.renamed == 0, "Rename leaves a part a download told apart, %s" % said
    assert told.is_file()

    asked, renamed, said = review_then_rename(mod, inst, monkeypatch)

    wanted = name_of(purchase, "Garden Hose", (1, 2))
    assert len(asked) == 1
    assert sorted(p.name for p in folder.iterdir()) == sorted([held.name, wanted])
    assert renamed == 0, "Rename agrees with the name the review gave, %s" % said


@pytest.mark.parametrize("name, number, part", [
    ("X Invoice (1 of 2).pdf", "ORDER-0001", (1, 2)),
    ("X Invoice (1 of 2) ORDER-0001.pdf", "ORDER-0001", (1, 2)),
    ("X Invoice (1 of 2) order-0001 (3).pdf", "ORDER-0001", (1, 2)),
    ("X Invoice (1 of 2) (2).pdf", "ORDER-0001", (1, 2)),
    ("X Invoice (2 of 3) ORD0001.pdf", "ORD/0001.", (2, 3)),
    ("X Invoice (1 of 2) A (3).pdf", "A (3)", (1, 2)),
    ("X Invoice (1 of 2) A (3) (2).pdf", "A (3)", (1, 2)),
    ("Pack (1 of 2) Invoice (2 of 2) ORDER-0001.pdf", "ORDER-0001", (2, 2)),
    ("X Invoice (1 of 2) ORDER-0002.pdf", "ORDER-0001", None),
    ("X (1 of 2) Invoice.pdf", "ORDER-0001", None),
    ("X Invoice (1 of 2) ORDER-0001 Copy.pdf", "ORDER-0001", None),
    ("X Invoice (1 of 2).zip", "ORDER-0001", None),
    ("X Invoice.pdf", "ORDER-0001", None),
    ("X Notice (1 of 2).pdf", "", (1, 2)),
    ("X Notice (1 of 2) (2).pdf", "", None),
    ("X Notice (1 of 2) 4F2A9C.pdf", "", None),
])
def test_a_part_is_read_only_where_unique_path_could_have_put_it(name, number, part):
    """A part ends the name, or is followed only by what unique_path adds for
    the row, its own order number, a count, or both. A row with no order
    number, a document's, has its part read only at the very end, as before."""
    row = {"PDF Filename": name, "Order or Receipt Number": number}
    assert renaming._part_of(row) == part


def test_target_keeps_the_part_of_an_invoice_it_saved(tmp_path, monkeypatch):
    """Target's own run, from the invoice it placed to the rows it wrote,
    for an order whose two invoices both name its item. Each is placed by
    _place_invoice with the part Target printed on it, the order is filed by
    _file_invoices, and its rows are written as process_one writes them for
    a name it was unsure of. A new name for the order keeps "(1 of 2)" and
    reaches the second invoice as well, and the next Rename and the next
    review leave both."""
    mod = load(REPO / "apps" / "target")
    inst = app_in(mod, tmp_path / "out")
    inst.stats = {"new_files": [], "validation_failures": 0}
    purchase = split_order("1000000000001")
    walk = {"saved": [], "held": [], "missed": [], "count": 2, "tokens": []}
    for i in (1, 2):
        staged = invoice(tmp_path / "staged", "invoice-%d.pdf" % i)
        checked = SimpleNamespace(ok=True, reason="", size_bytes=staged.stat().st_size,
                                  page_count=1)
        inst._place_invoice(staged, purchase, (i, 2), (i, 2), "", checked,
                            "Invoice %d of 2 Invented Garden Item" % i, walk)
    assert inst._file_invoices(purchase, walk) is True
    inst._write_csv_rows(purchase, receipt_status="Downloaded",
                         processing_status="Review Needed")
    inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                       notes="Low classification confidence")
    folder = inst.paths.invoices
    placed = sorted(p.name for p in folder.iterdir())
    assert placed == ["2026-05-14 Target Unsure Item Invoice (1 of 2).pdf",
                      "2026-05-14 Target Unsure Item Invoice (2 of 2).pdf"], placed
    assert [r["PDF Filename"] for r in inst.index_csv.read_all()] == [placed[0]]

    asked, renamed, said = review_then_rename(mod, inst, monkeypatch)

    assert len(asked) == 1
    assert sorted(p.name for p in folder.iterdir()) == [
        "2026-05-14 Target Garden Hose Invoice (1 of 2).pdf",
        "2026-05-14 Target Garden Hose Invoice (2 of 2).pdf"]
    assert renamed == 0, "Rename agrees with the name the review gave, %s" % said
    again = []
    monkeypatch.setattr(mod, "ask", lambda prompt: again.append(prompt) or "Lamp")
    inst.cmd_review_names()
    assert again == [], "a receipt renamed is not offered again"
