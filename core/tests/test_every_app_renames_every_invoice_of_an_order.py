"""Every invoice of an order split into several takes a new name together.

An order that came as several invoices is saved as several files, each with
its part, "2026-05-14 Target Unsure Item Invoice (1 of 2).pdf" and "...
(2 of 2).pdf", by Target and by Amazon. The index has one row for the
order, naming the invoice that names its items, and the order's notes name
the others, "Also saved ...". Target keeps each in the record's list of
invoices as well, Amazon names them in its notes alone.

Review Names and Rename renamed only the file the row names. A new summary
typed in Review Names, or a new naming pattern, left the order's other
invoices under the name the order had before, so someone looking for the
order by its new name found part of it.

These run each receipt app's own Review Names and Rename over an output
folder on disk, with the typing stood in for, and Target's and Amazon's own
saving of an order in several invoices. Every name, number and answer is
invented.
"""
import argparse
import importlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import renaming, storage, testkit
from paperpull_core.models import ONLINE, Item, Purchase, State

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d)
              and "def cmd_review_names" in entry_of(d).read_text(encoding="utf-8"))

# How an app that saves an order in several invoices writes the others down.
# Target names each in the record's list of invoices and in its notes, Amazon
# in its notes alone, after a colon.
STYLES = ("target", "amazon")

# A pattern that puts the order number in every name, and one that files
# every name in folders.
NUMBERED = "{date:yyyy-mm-dd} {provider} {summary} {number}[ ({part})]"
FOLDERS = "{provider}/{date:yyyy}/{date:yyyy-mm-dd} {summary}[ {kind}][ ({part})]"


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
    storage.set_filename_owner("")
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def app_in(mod, out: Path, documents: str = ""):
    """The app's own downloader over an output folder on disk, without its
    __init__, which would want a config file and a console, with the
    documents folder `documents` when one is given."""
    store = sys.modules["storage"]              # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    inst.args = argparse.Namespace(redownload=False, apply=False)
    inst.stats = {"new_files": [], "validation_failures": 0, "duplicate_filenames": 0,
                  "failed": 0, "manual_review": 0}
    inst.paths = store.Paths(out, documents_dir=documents)
    inst.paths.ensure()
    backups = inst.paths.backups
    inst.progress = store.JsonStore(inst.paths.progress_json, backups)
    inst.discovery = store.JsonStore(inst.paths.discovery_json, backups)
    inst.index_csv = store.CsvFile(inst.paths.receipt_index_csv,
                                   store.RECEIPT_INDEX_COLUMNS, backups)
    inst.order_csv = store.CsvFile(inst.paths.order_history_csv,
                                   store.ORDER_HISTORY_COLUMNS, backups)
    return inst


def invoice(folder: Path, name: str) -> Path:
    """An invoice of invented bytes, its own name among them, so where each
    file went can be told from its bytes."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% invented invoice " + name.encode() + b"\n%%EOF\n")
    return path


def split_order(number: str = "ORDER-0001", confidence: str = "Low") -> Purchase:
    return Purchase(purchase_type=ONLINE, purchase_date="2026-05-14", order_number=number,
                    summary="Unsure Item", confidence=confidence, document_type="Invoice",
                    items=[Item(name="Invented Garden Item")])


def name_of(purchase: Purchase, summary: str, part):
    """The name the app gives an invoice of `purchase` under the pattern set
    now, with its folders."""
    return storage.build_pdf_filename(purchase.purchase_date, summary, "Invoice", part=part,
                                      record=purchase)


def placed(name) -> str:
    """Where a name files its document, inside the folder it is filed in."""
    return (name.folder + "/" if getattr(name, "folder", "") else "") + str(name)


def saved_order(inst, purchase: Purchase, n: int = 3, style: str = "target",
                names=None) -> list:
    """The n invoices of `purchase` on disk, written down as the app's own
    run writes an order it saved in several, the first named by the index
    row and the record, and marked for review when the confidence is Low.
    `names` are the files' names when a test chooses them."""
    folder = inst.paths.folder_for(ONLINE)
    names = names or [name_of(purchase, purchase.summary, (i, n)) for i in range(1, n + 1)]
    files = [invoice(folder, name) for name in names]
    first, others = files[0], files[1:]
    extra = {"pdf_size": first.stat().st_size, "pdf_pages": 1, "downloaded_ok": True,
             "receipt_count": n}
    if style == "target":
        notes = ("Also saved %s; Invoice saved; no printable receipt exists"
                 % ", ".join(p.name for p in others))
        extra["invoices"] = [{"file": str(p), "part": "%d of %d" % (i, n), "number": "",
                              "kept": True, "names": i == 1, "size": p.stat().st_size,
                              "pages": 1} for i, p in enumerate(files, start=1)]
    else:
        notes = "Also saved: " + ", ".join(p.name for p in others)
    purchase.pdf_path, purchase.pdf_filename = str(first), first.name
    inst._record_state(purchase, State.PDF_VERIFIED, notes=notes, extra=extra)
    unsure = purchase.confidence == "Low"
    inst._write_csv_rows(purchase, receipt_status="Downloaded",
                         processing_status="Review Needed" if unsure else "Completed")
    if unsure:
        inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                           notes="Low classification confidence")
    else:
        inst._record_state(purchase, State.COMPLETED)
    return files


def everything(folder: Path) -> dict:
    """Each file below `folder`, by where it is inside it, with its bytes."""
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()}


def notes_of(inst, key: str) -> list:
    """The purchase's notes in its record, its index rows and its order
    history rows, in that order."""
    number = key.partition(":")[2]
    record = inst.progress.get(key) or {}
    return ([record.get("notes") or ""]
            + [r.get("Notes") or "" for r in inst.index_csv.read_all()
               if r.get("Order or Receipt Number") == number]
            + [r.get("Notes") or "" for r in inst.order_csv.read_all()
               if r.get("Order or Receipt Number") == number])


def follows(before: list, after: list, moved: dict) -> None:
    """Each note naming an invoice that moved names it by its new name
    afterwards, and nothing else in it changed but what a rename adds at
    its end. Not passing for want of a note, the record's names them."""
    assert any(old in before[0] for old in moved), before[0]
    for was, now in zip(before, after):
        wanted = was
        for old, new in moved.items():
            wanted = wanted.replace(old, new)
        assert now.startswith(wanted), (was, now)
        assert not any(old in now for old in moved if old not in moved.values()), now


def review(mod, inst, monkeypatch, *answers):
    """The person types the new names in turn for the receipts offered.
    What was asked."""
    asked = []
    monkeypatch.setattr(mod, "ask",
                        lambda prompt: asked.append(prompt) or answers[len(asked) - 1])
    inst.cmd_review_names()
    return asked


def rename_again(inst):
    """How many files a Rename after it renamed, and what it said."""
    said = []
    result = renaming.run_for(inst, apply_changes=True, say=said.append)
    return result.renamed, said


# -- Review Names ------------------------------------------------------------------------

@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_renames_every_invoice_of_the_order(app, style, tmp_path, monkeypatch,
                                                       capsys):
    """The first of an order's three invoices is offered for review, and
    the new name is given to all three, each keeping its own part and its
    own bytes. Every note naming the other two names them as they are now,
    Target's list of invoices does, and the Rename after it finds nothing
    to change. The review says the first renamed, as the panel counts the
    receipts renamed, and the other two renamed with it."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    files = saved_order(inst, purchase, 3, style)
    bytes_of = [p.read_bytes() for p in files]
    before = notes_of(inst, purchase.key)
    capsys.readouterr()

    asked = review(mod, inst, monkeypatch, "Garden Hose")

    said = capsys.readouterr().out.splitlines()
    wanted = [name_of(purchase, "Garden Hose", (i, 3)) for i in (1, 2, 3)]
    assert wanted[2].endswith(" Garden Hose Invoice (3 of 3).pdf"), wanted
    assert len(asked) == 1
    # The panel's own count (rvRenamed in gui/static/app.js).
    assert len([t for t in said if re.match(r"^\s*Renamed (->|to) ", t)]) == 1, said
    also = [re.sub(r"^\s*Also renamed (->|to) ", "", t) for t in said
            if re.match(r"^\s*Also renamed (->|to) ", t)]
    assert also == wanted[1:], said
    assert sorted(p.name for p in folder.iterdir()) == sorted(wanted)
    assert [(folder / w).read_bytes() for w in wanted] == bytes_of
    record = inst.progress.get(purchase.key)
    assert record["pdf_path"] == str(folder / wanted[0])
    follows(before, notes_of(inst, purchase.key),
            {p.name: w for p, w in zip(files[1:], wanted[1:])})
    if style == "target":
        assert [e["file"] for e in record["invoices"]] == [str(folder / w) for w in wanted]
    renamed, said = rename_again(inst)
    assert renamed == 0, said


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_files_every_invoice_in_the_pattern_s_folders(app, tmp_path, monkeypatch):
    """Under a pattern that names folders, the other invoices go into the
    folders the first one goes to."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    files = saved_order(inst, purchase, 2, "amazon")
    storage.set_filename_patterns({"filename_pattern": FOLDERS})

    review(mod, inst, monkeypatch, "Garden Hose")

    wanted = [placed(name_of(purchase, "Garden Hose", (i, 2))) for i in (1, 2)]
    assert wanted[0].startswith(storage.spec().provider + "/2026/"), wanted
    assert sorted(everything(folder)) == sorted(wanted)
    assert not any(p.exists() for p in files)
    renamed, said = rename_again(inst)
    assert renamed == 0, said


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_leaves_an_invoice_another_purchase_names(app, tmp_path, monkeypatch):
    """A file deleted once it was imported elsewhere leaves its name free,
    and a later purchase of the same day and summary is saved under it.
    The order's notes still name it, and so do the later purchase's row and
    record, so whose invoice it is cannot be told. It keeps its name, the
    later purchase's row and record still name it, and the order's first
    invoice still takes the new name. Rename leaves it as well."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second = saved_order(inst, purchase, 2, "amazon")
    later = split_order("ORDER-0002", confidence="High")
    later.pdf_path, later.pdf_filename = str(second), second.name
    inst._record_state(later, State.PDF_VERIFIED, extra={
        "pdf_size": second.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
    inst._write_csv_rows(later, receipt_status="Downloaded", processing_status="Completed")
    inst._record_state(later, State.COMPLETED)
    held = second.read_bytes()

    review(mod, inst, monkeypatch, "Garden Hose")

    wanted = name_of(purchase, "Garden Hose", (1, 2))
    assert sorted(p.name for p in folder.iterdir()) == sorted([wanted, second.name])
    assert second.read_bytes() == held
    assert inst.progress.get(later.key)["pdf_path"] == str(second)
    assert second.name in inst.progress.get(purchase.key)["notes"]
    storage.set_filename_patterns({"filename_pattern": NUMBERED})
    renaming.run_for(inst, apply_changes=True, say=lambda *_: None)
    assert second.is_file() and second.read_bytes() == held


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_renames_the_invoices_still_on_disk(app, tmp_path, monkeypatch):
    """An invoice deleted once it was imported elsewhere is not there to
    rename. The others take the new name, and the notes still name the one
    deleted as it was saved."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second, third = saved_order(inst, purchase, 3, "target")
    second.unlink()

    review(mod, inst, monkeypatch, "Garden Hose")

    wanted = [name_of(purchase, "Garden Hose", (i, 3)) for i in (1, 3)]
    assert sorted(p.name for p in folder.iterdir()) == sorted(wanted)
    record = inst.progress.get(purchase.key)
    assert second.name in record["notes"] and wanted[1] in record["notes"]
    assert [e["file"] for e in record["invoices"]] == [
        str(folder / wanted[0]), str(second), str(folder / wanted[1])]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_leaves_a_file_whose_name_says_no_part(app, tmp_path, monkeypatch):
    """A file the notes name whose name does not say which invoice of the
    order it is, renamed by hand perhaps, cannot be given its part, so it
    keeps the name it has."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    names = [name_of(purchase, "Unsure Item", (1, 2)), "2026-05-14 Kept By Hand.pdf"]
    first, kept = saved_order(inst, purchase, 2, "amazon", names=names)

    review(mod, inst, monkeypatch, "Garden Hose")

    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [name_of(purchase, "Garden Hose", (1, 2)), kept.name])


def test_a_new_name_leaves_an_invoice_put_aside(tmp_path, monkeypatch):
    """An invoice of the order put aside in Manual Review, because it
    failed its check, is not filed with the rest. Target's list says so,
    and so do its notes. It keeps its name and its folder."""
    mod = load(REPO / "apps" / "target")
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second = saved_order(inst, purchase, 2, "target")
    aside = inst.paths.manual_review / second.name
    second.replace(aside)
    record = inst.progress.get(purchase.key)
    entries = [dict(record["invoices"][0]), dict(record["invoices"][1], file=str(aside),
                                                 kept=False)]
    inst.progress.update(purchase.key, {
        "invoices": entries,
        "notes": record["notes"].replace("Also saved " + second.name + ";",
                                         "Put aside in Manual Review " + aside.name + ";")})

    review(mod, inst, monkeypatch, "Garden Hose")

    assert [p.name for p in folder.iterdir()] == [name_of(purchase, "Garden Hose", (1, 2))]
    assert [p.name for p in inst.paths.manual_review.iterdir()] == [aside.name]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_for_an_older_copy_leaves_the_order_s_invoices(app, tmp_path,
                                                                 monkeypatch):
    """Download again saved a new copy of an order's first invoice beside
    the old one, and the record names the new copy. A new name typed for
    the old copy's row is that copy's alone, so the order's invoices the
    record names keep their names."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second = saved_order(inst, purchase, 2, "target")
    older = invoice(folder, Path(first.name).stem + " ORDER-0001.pdf")
    rows = inst.index_csv.read_all()
    copy = dict(rows[0], **{"PDF Filename": older.name, "PDF Full Path": str(older)})
    rows[0].update({"Classification Confidence": "High", "Processing Status": "Completed"})
    inst.index_csv.rewrite(rows + [copy])

    asked = review(mod, inst, monkeypatch, "Garden Hose")

    assert len(asked) == 1
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [first.name, second.name, name_of(purchase, "Garden Hose", (1, 2))])


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_name_in_the_notes_with_a_folder_in_it_is_left_alone(app, tmp_path, monkeypatch):
    """Notes can be edited by hand. A name in them that climbs out of the
    folder the order's invoices were saved in, into Manual Review here,
    names no invoice of the order, and that file keeps its name."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second = saved_order(inst, purchase, 2, "amazon")
    aside = inst.paths.manual_review / second.name
    second.replace(aside)
    inst.progress.update(purchase.key, {
        "notes": "Also saved: ../%s/%s" % (inst.paths.manual_review.name, aside.name)})

    review(mod, inst, monkeypatch, "Garden Hose")

    assert [p.name for p in folder.iterdir()] == [name_of(purchase, "Garden Hose", (1, 2))]
    assert [p.name for p in inst.paths.manual_review.iterdir()] == [aside.name]


def test_an_invoice_that_cannot_be_renamed_keeps_its_name(tmp_path, monkeypatch):
    """An invoice another program holds open cannot be renamed. The first
    takes the new name all the same, the one held keeps its name, the
    record and the notes still name it where it is, and the next Rename
    gives it the new name."""
    mod = load(REPO / "apps" / "target")
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    first, second = saved_order(inst, purchase, 2, "target")
    real = Path.rename

    def refused(self, target):
        if Path(self) == second:
            raise PermissionError(13, "held open", str(self))
        return real(self, target)

    monkeypatch.setattr(Path, "rename", refused)
    review(mod, inst, monkeypatch, "Garden Hose")
    monkeypatch.setattr(Path, "rename", real)

    wanted = [name_of(purchase, "Garden Hose", (i, 2)) for i in (1, 2)]
    assert sorted(p.name for p in folder.iterdir()) == sorted([wanted[0], second.name])
    record = inst.progress.get(purchase.key)
    assert second.name in record["notes"]
    assert [e["file"] for e in record["invoices"]] == [str(folder / wanted[0]), str(second)]

    renamed, said = rename_again(inst)

    assert renamed == 1, said
    assert sorted(p.name for p in folder.iterdir()) == sorted(wanted)
    assert wanted[1] in inst.progress.get(purchase.key)["notes"]


def test_ctrl_c_while_the_other_invoices_move_puts_every_invoice_back(tmp_path, monkeypatch,
                                                                    capsys):
    """Ctrl+C after the first invoice and the second took the new name and
    before the third did, with nothing written down yet. Every invoice
    goes back under the name it had, the CSVs and the record still name
    them so, and the review stops as Ctrl+C."""
    mod = load(REPO / "apps" / "amazon")
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    files = saved_order(inst, purchase, 3, "amazon")
    rows = inst.index_csv.read_all()
    record = dict(inst.progress.get(purchase.key))
    real = Path.rename

    def stopped(self, target):
        if Path(self) == files[2]:
            raise KeyboardInterrupt
        return real(self, target)

    monkeypatch.setattr(Path, "rename", stopped)
    with pytest.raises(KeyboardInterrupt):
        review(mod, inst, monkeypatch, "Garden Hose")
    monkeypatch.setattr(Path, "rename", real)

    assert sorted(p.name for p in folder.iterdir()) == sorted(p.name for p in files)
    assert inst.index_csv.read_all() == rows
    assert inst.progress.get(purchase.key) == record
    assert "put back under the name it had" in capsys.readouterr().out


def test_a_write_that_fails_puts_every_invoice_back(tmp_path, monkeypatch, capsys):
    """When progress.json cannot be written after the invoices moved,
    every invoice of the order goes back under the name it had, and the
    CSVs are written back."""
    mod = load(REPO / "apps" / "amazon")
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order()
    files = saved_order(inst, purchase, 3, "amazon")
    rows = inst.index_csv.read_all()
    orders = inst.order_csv.read_all()

    def refused(*_args, **_kwargs):
        raise PermissionError(13, "held open", str(inst.paths.progress_json))

    monkeypatch.setattr(inst.progress, "update", refused)
    with pytest.raises(SystemExit):
        review(mod, inst, monkeypatch, "Garden Hose")

    assert sorted(p.name for p in folder.iterdir()) == sorted(p.name for p in files)
    assert inst.index_csv.read_all() == rows
    assert inst.order_csv.read_all() == orders
    assert "put back under the name it had" in capsys.readouterr().out


# -- Rename ------------------------------------------------------------------------------

@pytest.mark.parametrize("pattern", [NUMBERED, FOLDERS], ids=["numbered", "folders"])
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_rename_gives_every_invoice_of_the_order_the_new_pattern(app, style, pattern,
                                                                 tmp_path):
    """A new naming pattern, and the app's own Rename. All three invoices
    of the order take it, each keeping its own part and its own bytes, the
    notes and Target's list of invoices follow them, and a Rename after it
    finds nothing to change."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order(confidence="High")
    files = saved_order(inst, purchase, 3, style)
    bytes_of = [p.read_bytes() for p in files]
    before = notes_of(inst, purchase.key)
    storage.set_filename_patterns({"filename_pattern": pattern})
    inst.args.apply = True

    inst.cmd_rename()

    names = [name_of(purchase, "Unsure Item", (i, 3)) for i in (1, 2, 3)]
    wanted = [placed(n) for n in names]
    assert "(3 of 3)" in wanted[2], wanted
    assert sorted(everything(folder)) == sorted(wanted)
    assert [(folder / w).read_bytes() for w in wanted] == bytes_of
    follows(before, notes_of(inst, purchase.key),
            {p.name: str(n) for p, n in zip(files[1:], names[1:])})
    if style == "target":
        assert [e["file"] for e in inst.progress.get(purchase.key)["invoices"]] == [
            str(folder / w) for w in wanted]
    renamed, said = rename_again(inst)
    assert renamed == 0, said


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_rename_brings_an_invoice_left_behind_into_line(app, tmp_path):
    """An order whose first invoice was given a new name by a Review Names
    from before, its others left under the name the order had. Rename names
    them as the first is named, from the record."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order(confidence="High")
    purchase.summary = "Garden Hose"
    names = [name_of(purchase, "Garden Hose", (1, 2)), name_of(purchase, "Unsure Item", (2, 2))]
    saved_order(inst, purchase, 2, "amazon", names=names)

    renamed, said = rename_again(inst)

    assert renamed == 1, said
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        name_of(purchase, "Garden Hose", (i, 2)) for i in (1, 2))


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("app", ["amazon", "target"])
def test_the_move_to_a_documents_folder_takes_every_invoice_of_the_order(
        app, style, tmp_path, monkeypatch):
    """The Move into an account's documents folder takes the order's other
    invoices with the first, each under the name it has, Amazon's named in
    its notes alone as well as Target's in its list, and the notes still
    name them."""
    mod = load(REPO / "apps" / app)
    docs = tmp_path / "Watched"
    inst = app_in(mod, tmp_path / "out", documents=str(docs))
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order(confidence="High")
    files = saved_order(inst, purchase, 3, style)
    bytes_of = [p.read_bytes() for p in files]
    before = notes_of(inst, purchase.key)
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")

    result = renaming.run_for(inst, apply_changes=True, say=lambda *_: None)

    there = docs / folder.name
    assert result.renamed == 3
    assert not any(p.exists() for p in files)
    assert [(there / p.name).read_bytes() for p in files] == bytes_of
    record = inst.progress.get(purchase.key)
    assert record["pdf_path"] == str(there / files[0].name)
    assert notes_of(inst, purchase.key)[0] == before[0]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_rename_leaves_every_invoice_of_an_order_with_no_index_row(app, tmp_path):
    """An order whose index row was never written, with the index open in
    Excel through its run, is not renamed, its first invoice for want of a
    row, and its others with it, so the order stays under one name. The
    order beside it with a row takes the new pattern."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order(confidence="High")
    files = saved_order(inst, purchase, 3, "amazon")
    whole = split_order("ORDER-0002", confidence="High")
    alone = saved_order(inst, whole, 1, "amazon")[0]
    inst.index_csv.rewrite([r for r in inst.index_csv.read_all()
                            if r["Order or Receipt Number"] == "ORDER-0002"])
    storage.set_filename_patterns({"filename_pattern": NUMBERED})

    renamed, said = rename_again(inst)

    assert renamed == 1, said
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [p.name for p in files] + [name_of(whole, "Unsure Item", None)])
    assert not alone.exists()


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_rename_leaves_an_invoice_whose_name_says_no_part(app, tmp_path):
    """A file the notes name with no part in its name keeps that name under
    a new pattern, since nothing says which invoice it is."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    folder = inst.paths.folder_for(ONLINE)
    purchase = split_order(confidence="High")
    names = [name_of(purchase, "Unsure Item", (1, 2)), "2026-05-14 Kept By Hand.pdf"]
    saved_order(inst, purchase, 2, "target", names=names)
    storage.set_filename_patterns({"filename_pattern": NUMBERED})

    renamed, said = rename_again(inst)

    assert renamed == 1, said
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [name_of(purchase, "Unsure Item", (1, 2)), names[1]])


# -- Each app's own saving ---------------------------------------------------------------

def test_target_gives_every_invoice_it_saved_the_new_name(tmp_path, monkeypatch):
    """Target's own run, from the invoices it placed to the rows it wrote,
    for an order in two invoices. A new name reaches both, the list of
    invoices and the notes follow, Target finds nothing to mend in its list
    afterwards, and its own Rename under a new pattern names both again."""
    mod = load(REPO / "apps" / "target")
    inst = app_in(mod, tmp_path / "out")
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
    placed_first = sorted(p.name for p in folder.iterdir())
    assert placed_first == ["2026-05-14 Target Unsure Item Invoice (1 of 2).pdf",
                            "2026-05-14 Target Unsure Item Invoice (2 of 2).pdf"], placed_first
    before = notes_of(inst, purchase.key)

    review(mod, inst, monkeypatch, "Garden Hose")

    reviewed = ["2026-05-14 Target Garden Hose Invoice (1 of 2).pdf",
                "2026-05-14 Target Garden Hose Invoice (2 of 2).pdf"]
    assert sorted(p.name for p in folder.iterdir()) == reviewed
    record = inst.progress.get(purchase.key)
    assert [e["file"] for e in record["invoices"]] == [str(folder / n) for n in reviewed]
    follows(before, notes_of(inst, purchase.key), {placed_first[1]: reviewed[1]})
    assert inst._mend_invoice_lists(save=False) == 0

    storage.set_filename_patterns({"filename_pattern": NUMBERED})
    inst.args.apply = True
    inst.cmd_rename()

    renamed = ["2026-05-14 Target Garden Hose 1000000000001 (1 of 2).pdf",
               "2026-05-14 Target Garden Hose 1000000000001 (2 of 2).pdf"]
    assert sorted(p.name for p in folder.iterdir()) == renamed
    record = inst.progress.get(purchase.key)
    assert [e["file"] for e in record["invoices"]] == [str(folder / n) for n in renamed]
    assert renamed[1] in record["notes"] and reviewed[1] not in record["notes"]
    again, said = rename_again(inst)
    assert again == 0, said


def test_amazon_gives_every_invoice_it_saved_the_new_name(tmp_path, monkeypatch):
    """Amazon's own saving of an order split across sellers, from the
    invoices it downloaded to the rows it wrote. A new name reaches all
    three, the notes follow, and its own Rename under a new pattern names
    all three again."""
    mod = load(REPO / "apps" / "amazon")
    site = sys.modules["amazon_site"]
    inst = app_in(mod, tmp_path / "out")
    purchase = split_order()

    def download(page, url, out_path):
        out_path.write_bytes(testkit.text_pdf(["Invoice", "Order ORDER-0001", url,
                                               "Invented Garden Item"]))
        return True

    monkeypatch.setattr(site, "download_invoice_pdf", download)
    invoices = [("Invoice %d" % i, "https://www.amazon.com/invented-invoice-%d" % i)
                for i in (1, 2, 3)]
    assert inst._save_invoices(None, purchase, invoices) is True
    inst._write_csv_rows(purchase, receipt_status="Downloaded",
                         processing_status="Review Needed")
    inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                       notes="Low classification confidence")
    folder = inst.paths.online
    saved = sorted(p.name for p in folder.iterdir())
    assert saved == ["2026-05-14 Amazon Unsure Item Invoice (%d of 3).pdf" % i
                     for i in (1, 2, 3)], saved
    bytes_of = [(folder / n).read_bytes() for n in saved]
    before = notes_of(inst, purchase.key)

    review(mod, inst, monkeypatch, "Garden Hose")

    reviewed = ["2026-05-14 Amazon Garden Hose Invoice (%d of 3).pdf" % i for i in (1, 2, 3)]
    assert sorted(p.name for p in folder.iterdir()) == reviewed
    assert [(folder / n).read_bytes() for n in reviewed] == bytes_of
    follows(before, notes_of(inst, purchase.key), dict(zip(saved[1:], reviewed[1:])))

    storage.set_filename_patterns({"filename_pattern": NUMBERED})
    inst.args.apply = True
    inst.cmd_rename()

    renamed = ["2026-05-14 Amazon Garden Hose ORDER-0001 (%d of 3).pdf" % i for i in (1, 2, 3)]
    assert sorted(p.name for p in folder.iterdir()) == renamed
    assert [(folder / n).read_bytes() for n in renamed] == bytes_of
    again, said = rename_again(inst)
    assert again == 0, said
