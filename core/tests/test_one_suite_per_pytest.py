"""A pytest that reaches into more than one suite stops before it collects,
and says what to run instead.

On 2026-10-19 an outside review ran pytest from the repository folder and
met an ImportError from apps/amazon/storage.py while Apple's tests were
collected. Every app has its own storage.py, its tests put the app's folder
on sys.path and import storage, and one process keeps the first app's. The
cure it offered, emptying sys.modules between apps, failed 8 of Amazon's
tests beside Apple's, because the core binds one app per process. So
conftest.py at the root refuses such a run, and pytest.ini tells the story.

These run pytest on a small checkout laid out like the real one, with the
real pytest.ini and conftest.py at its root and two apps that each have a
storage.py, so a refused command and an allowed one can both be watched to
the end. They also hold the guard to every way the runner and CI start
pytest, since a guard that stopped one of those would stop every run.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

rat = pytest.importorskip("run_all_tests")


def _load_guard():
    """The root conftest.py, under a name of its own, so this file holds the
    one the checkout has whether or not pytest loaded it."""
    spec = importlib.util.spec_from_file_location("root_conftest_guard", REPO / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()

STORAGE = '''
NAME = "{name}"
'''

# Laid out as the real apps' tests are, the app's folder put first on
# sys.path and storage imported by its plain name.
APP_TEST = '''
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_its_own_storage():
    assert storage.NAME == "{name}"
'''

PLAIN_TEST = '''
def test_runs():
    pass
'''

APPS = ("one", "two")


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


def _checkout(root: Path, guarded: bool = True) -> Path:
    """Two apps with a storage.py each, and a core, gui and server with one
    test each, under the real pytest.ini and, when guarded, the real
    conftest.py."""
    shutil.copyfile(REPO / "pytest.ini", root / "pytest.ini")
    if guarded:
        shutil.copyfile(REPO / "conftest.py", root / "conftest.py")
    for name in APPS:
        _write(root, "apps/%s/storage.py" % name, STORAGE.format(name=name))
        _write(root, "apps/%s/tests/test_storage.py" % name, APP_TEST.format(name=name))
    for name in guard.OWN_FOLDERS:
        _write(root, "%s/tests/test_%s.py" % (name, name), PLAIN_TEST)
    return root


@pytest.fixture(scope="module")
def checkout(tmp_path_factory):
    return _checkout(tmp_path_factory.mktemp("checkout"))


def _pytest(cwd: Path, *args) -> tuple:
    """pytest run in cwd with args, as somebody would type it, and its
    exit code and whole output."""
    env = dict(os.environ)
    for name in ("PYTEST_ADDOPTS", rat.CORE_PART_ENV):
        env.pop(name, None)
    ran = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header",
                          "-p", "no:cacheprovider", *args],
                         cwd=cwd, capture_output=True, text=True, timeout=300, env=env)
    return ran.returncode, ran.stdout + ran.stderr


def _ran_anything(output: str) -> bool:
    return bool(re.search(r"\b\d+ (passed|failed|errors?|skipped)\b|no tests ran", output))


def test_the_checkout_here_meets_the_fault_without_the_guard(tmp_path):
    """Without conftest.py, two apps in one pytest run the second app's
    test against the first app's storage, as the real apps did."""
    root = _checkout(tmp_path, guarded=False)
    code, out = _pytest(root, "apps/one", "apps/two")
    assert code == 1, out
    assert "1 failed, 1 passed" in out, out
    assert "'one' == 'two'" in out, out


# Where pytest was started, what it was given, and the suites the refusal
# names, in the order it names them.
REFUSED = [
    ("", ["apps/one", "apps/two"], "2 suites, apps/one and apps/two"),
    ("", ["."], "5 suites, core, gui, server, apps/one and apps/two"),
    ("", [], "5 suites, core, gui, server, apps/one and apps/two"),
    ("", ["apps"], "2 suites, apps/one and apps/two"),
    ("apps", [], "2 suites, apps/one and apps/two"),
    ("apps/one", ["../two", "."], "2 suites, apps/two and apps/one"),
    ("", ["core/tests", "gui/tests"], "2 suites, core and gui"),
    ("", ["apps/one/tests/test_storage.py::test_its_own_storage", "server"],
     "2 suites, apps/one and server"),
]


@pytest.mark.parametrize("where, args, reached", REFUSED)
def test_a_command_reaching_two_suites_stops_before_it_collects(checkout, where, args, reached):
    code, out = _pytest(checkout / where, *args)
    assert code == 4, out
    assert "This command reaches into %s," % reached in out, out
    assert "each suite has to run in a pytest of its own" in out
    assert "python tools/run_all_tests.py" in out
    assert "CONTRIBUTING.md" in out
    assert not _ran_anything(out), out


def test_the_refusal_names_the_runner_suites_and_a_suite_by_hand(checkout):
    code, out = _pytest(checkout, "core/tests", "apps/two")
    assert code == 4, out
    assert "python tools/run_all_tests.py --suites core,core-browsers,two" in out
    assert "    cd apps/two\n    python -m pytest tests" in out


# Where pytest was started and what it was given, each reaching one suite.
ALLOWED = [
    ("apps/one", []),
    ("apps/one", ["tests"]),
    ("apps/one", ["../two"]),
    ("", ["apps/two"]),
    ("", ["apps/two/tests/test_storage.py::test_its_own_storage"]),
    ("", ["core/tests"]),
    ("", ["core/tests/test_core.py", "core"]),
    ("core", []),
    ("gui", []),
    ("server", []),
]


@pytest.mark.parametrize("where, args", ALLOWED)
def test_a_command_in_one_suite_runs_it(checkout, where, args):
    code, out = _pytest(checkout / where, *args)
    assert code == 0, out
    assert "1 passed" in out, out
    assert "This command reaches" not in out


@pytest.mark.parametrize("suite, part", [("apps/one", ""), ("core", "core"), ("gui", ""), ("server", "")])
def test_the_runner_runs_each_suite_as_it_did(checkout, suite, part):
    """With the runner's own command, its plugins and the core's part."""
    out, code, _records = rat.run_suite(checkout / suite, Path(sys.executable), timeout=300, part=part)
    assert code == 0, out
    assert "1 passed" in out, out


def test_every_suite_the_runner_runs_is_one_suite_here():
    """The runner starts each suite's pytest in that suite's folder with no
    path, so pytest is given the folder. Each one reaches exactly one suite,
    the core's two parts the same one and every other suite its own."""
    seen = {}
    for name, folder, _kind in rat.suites(False):
        reached = guard.suites_of(folder)
        assert len(reached) == 1, (name, reached)
        seen.setdefault(reached[0], set()).add(name)
    assert seen.pop("core") == {"core", "core-browsers"}
    assert all(len(names) == 1 for names in seen.values()), seen


def test_the_root_and_apps_reach_every_suite_and_nothing_else_reaches_one():
    every = {guard.suites_of(folder)[0] for _name, folder, _kind in rat.suites(False)}
    assert set(guard.suites_of(REPO)) == every
    assert set(guard.suites_of(REPO / "apps")) == {s for s in every if s.startswith("apps/")}
    for elsewhere in (REPO / "tools", REPO / "docs", REPO / "paperpull.py", REPO.parent):
        assert guard.suites_of(elsewhere) == [], elsewhere


def _ci_pytest_commands() -> list:
    """What each command in tests.yml that runs python -m pytest gives it,
    a folded block read as one command."""
    lines = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8").splitlines()
    commands = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, value = len(m.group(1)), m.group(2).strip()
        if value in (">-", ">", "|", "|-"):
            block = []
            for more in lines[i + 1:]:
                if more.strip() and len(more) - len(more.lstrip()) <= indent:
                    break
                block.append(more.strip())
            value = " ".join(block)
        words = value.split()
        for at in range(len(words) - 1):
            if words[at:at + 2] == ["-m", "pytest"]:
                commands.append(words[at + 2:])
    return commands


def test_every_pytest_line_of_ci_reaches_one_suite():
    commands = _ci_pytest_commands()
    assert len(commands) >= 2, commands
    for args in commands:
        paths = [w for w in args if not w.startswith("-")]
        assert paths, args
        reached = {s for p in paths for s in guard.suites_of(REPO / p.split("::")[0])}
        assert len(reached) == 1, (args, reached)


def test_two_real_apps_from_the_root_stop_with_the_way_to_run_them():
    code, out = _pytest(REPO, "apps/amazon", "apps/apple")
    assert code == 4, out
    assert "2 suites, apps/amazon and apps/apple," in out
    assert "python tools/run_all_tests.py --suites amazon,apple" in out
    assert "    cd apps/amazon\n    python -m pytest tests" in out
    assert not _ran_anything(out), out


def test_the_pytest_lines_of_ci_still_collect_from_the_real_checkout():
    for args in _ci_pytest_commands():
        code, out = _pytest(REPO, "--collect-only", *[w for w in args if w not in ("-q", "-v")])
        assert code == 0, out
        assert "This command reaches" not in out
