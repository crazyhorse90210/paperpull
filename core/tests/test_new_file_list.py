"""Every provider must replace the previous run's import list, even when empty,
on a run that downloads, and leave it alone on a run that saves nothing."""
import ast
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from paperpull_core.run_reporting import NEW_LIST_NOTE, lists_what_it_saved
from paperpull_core.storage import atomic_write_text, now_iso

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (ROOT / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))


def summary_of(entry):
    """The app's own write_run_summary, exec'd without importing browser
    code or reading configs."""
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "write_run_summary")
    # The method is exec'd in isolation, so every name it reaches for must be
    # supplied here. report_run_result arrived with #19 after this test was
    # written, and every app failed until it was stubbed. It prints a
    # counts-only line for the panel, which this test does not care about.
    scope = {"atomic_write_text": atomic_write_text, "now_iso": now_iso,
             "report_run_result": lambda stats: None,
             "lists_what_it_saved": lists_what_it_saved, "NEW_LIST_NOTE": NEW_LIST_NOTE}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(entry), "exec"), scope)
    return scope["write_run_summary"]


def app_for(tmp_path, mode, dry_run=False, new_files=()):
    stats = defaultdict(int, started="2026-01-01T00:00:00", mode=mode,
                        dates=[], dates_processed=[], new_files=list(new_files))
    return SimpleNamespace(stats=stats, args=SimpleNamespace(dry_run=dry_run),
                           paths=SimpleNamespace(root=tmp_path,
                                                 run_summary=tmp_path / "run-summary.txt"))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_empty_run_replaces_previous_download_list(entry, tmp_path):
    write_run_summary = summary_of(entry)
    app = app_for(tmp_path, "all", new_files=["Statements/synthetic.pdf"])
    write_run_summary(app)
    listing = tmp_path / "new-this-run.txt"
    assert "Statements/synthetic.pdf" in listing.read_text()
    app.stats["new_files"] = []
    write_run_summary(app)
    lines = listing.read_text().splitlines()
    assert lines[0].startswith("# 0 file(s)")
    assert not [line for line in lines if line.strip() and not line.startswith("#")]
    # Repeated empty runs must not resurrect old entries.
    write_run_summary(app)
    assert "Statements/synthetic.pdf" not in listing.read_text()


LAST = "# 1 file(s) downloaded on this run (2026-01-01T00:00:00):\nStatements/last.pdf\n"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("mode,dry_run", [("verify", False), ("dry-run", True),
                                          ("pilot", True), ("all", True), ("resume", True),
                                          ("reparse-items", False)])
def test_a_run_that_saves_nothing_keeps_the_last_download_runs_list(entry, tmp_path, mode,
                                                                    dry_run):
    """Verify checks the files already saved and a dry run saves none, yet
    each wrote a summary that replaced new-this-run.txt with an empty list,
    as Rename did before 0.57.1 (#103, and the release review of 0.57.1).
    The run summary is still written, which tools/status.py reads as the
    last run."""
    listing = tmp_path / "new-this-run.txt"
    listing.write_text(LAST, encoding="utf-8")
    os.utime(listing, (1_000_000_000, 1_000_000_000))
    summary_of(entry)(app_for(tmp_path, mode, dry_run))
    assert listing.read_text(encoding="utf-8") == LAST
    assert listing.stat().st_mtime == 1_000_000_000, "the list was written again"
    assert "Mode:" in (tmp_path / "run-summary.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_the_list_says_each_file_is_named_as_the_run_saved_it(entry, tmp_path):
    """A Rename or the panel's move to a documents folder leaves the list as
    the download run wrote it, so its second line says a file may since have
    another name or folder, or two files may have traded names."""
    summary_of(entry)(app_for(tmp_path, "pilot", new_files=["Statements/a.pdf"]))
    lines = (tmp_path / "new-this-run.txt").read_text(encoding="utf-8").splitlines()
    assert lines[1] == NEW_LIST_NOTE.rstrip("\n") and lines[2:] == ["Statements/a.pdf"]


@pytest.mark.parametrize("mode", ["all", "pilot", "resume", "online", "instore", "documents",
                                  "letters", "id-cards", "", "anything new"])
def test_every_other_run_lists_what_it_saved(mode):
    """The rule fails open, a mode it does not know writes the list, since
    a download run with no list says Nothing new and moves nothing."""
    assert lists_what_it_saved({"mode": mode}, SimpleNamespace(dry_run=False))
    assert lists_what_it_saved({"mode": mode})
    assert not lists_what_it_saved({"mode": mode}, SimpleNamespace(dry_run=True))
