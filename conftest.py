"""A pytest that would run more than one suite stops before it collects.

The suites are core, gui, server and each folder of apps, and each runs in a
pytest of its own. tools/run_all_tests.py runs every one that way, and so
does CI. The apps cannot share a process. Every app has its own storage.py,
its tests put the app's folder on sys.path and import storage, and the first
app's storage stays in sys.modules for the rest of the run. pytest.ini tells
the longer story.

pytest loads this file for every run under this folder, the runner's and
CI's included, so it imports nothing but pytest and looks only at the paths
the run was given. It reads the apps folder only when one of those paths
holds every app.
"""
import os

import pytest

HERE = os.path.normcase(os.path.dirname(os.path.realpath(__file__)))
# The suites that are not apps, each the folder of that name.
OWN_FOLDERS = ("core", "gui", "server")
# The most suites named one by one in the refusal, and offered to the
# runner's --suites. A command that reaches more wants the whole run.
NAMED = 6


def every_app() -> list:
    """Each app folder that has tests, as the runner counts them."""
    apps = os.path.join(HERE, "apps")
    try:
        names = sorted(os.listdir(apps))
    except OSError:
        return []
    return ["apps/" + os.path.normcase(n) for n in names
            if not n.startswith(".") and os.path.isdir(os.path.join(apps, n, "tests"))]


def suites_of(path) -> list:
    """The suites a path given to pytest reaches into. The one it is in, or
    every suite below it for this folder and apps, or none for a path
    anywhere else, which pytest is left to collect as it would."""
    path = os.path.normcase(os.path.realpath(path))
    if path != HERE and not path.startswith(HERE.rstrip(os.sep) + os.sep):
        return []
    parts = [p for p in path[len(HERE):].split(os.sep) if p]
    if not parts:
        return list(OWN_FOLDERS) + every_app()
    if parts[0] in OWN_FOLDERS:
        return [parts[0]]
    if parts[0] == "apps":
        return ["apps/" + parts[1]] if len(parts) > 1 else every_app()
    return []


def runner_names(suites) -> list:
    """The names tools/run_all_tests.py --suites takes for these. The core
    runs there as two suites."""
    out = []
    for s in suites:
        out += ["core", "core-browsers"] if s == "core" else [s.split("/")[-1]]
    return out


def by_hand(suite) -> list:
    """The lines CONTRIBUTING.md gives for running one suite by hand, an
    app's from its own folder and the others' from this one."""
    if suite.startswith("apps/"):
        return ["cd " + suite, "python -m pytest tests"]
    return ["python -m pytest %s/tests" % suite]


def refusal(suites) -> str:
    if len(suites) <= NAMED:
        reached = "%d suites, %s and %s" % (len(suites), ", ".join(suites[:-1]), suites[-1])
    else:
        reached = "%d suites, %s and %d more" % (len(suites), ", ".join(suites[:3]), len(suites) - 3)
    one = next((s for s in suites if s.startswith("apps/")), suites[0])
    lines = [
        "This command reaches into %s," % reached,
        "and each suite has to run in a pytest of its own.",
        "",
        "Every app has its own storage.py, and its tests put the app's folder on sys.path",
        "and import storage. One process keeps the first app's storage for the whole run,",
        "so the next app's tests fail to import theirs or, worse, pass against the wrong",
        "app's code. The core binds one app per process too, so clearing sys.modules",
        "between suites does not cure it. pytest.ini tells the whole story.",
        "",
        "To run every suite, each in a pytest of its own, run this from the",
        "repository folder.",
        "",
        "    python tools/run_all_tests.py",
        "",
    ]
    if len(suites) <= NAMED:
        lines += [
            "To run only these, give the runner their names.",
            "",
            "    python tools/run_all_tests.py --suites " + ",".join(runner_names(suites)),
            "",
        ]
    lines += ["To run one suite by hand, do as CONTRIBUTING.md shows under Run the tests.", ""]
    lines += ["    " + line for line in by_hand(one)]
    return "\n".join(lines)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Here rather than at configure, so --help and --markers still answer
    from the repository folder."""
    config = session.config
    if config.getoption("pyargs", False):
        return
    start = str(config.invocation_params.dir)
    reached = []
    for arg in config.args:
        for suite in suites_of(os.path.join(start, arg.split("::")[0])):
            if suite not in reached:
                reached.append(suite)
    if len(reached) > 1:
        raise pytest.UsageError(refusal(reached))
