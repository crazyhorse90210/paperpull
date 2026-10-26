"""The self-test's network row with PAPERPULL_HOSTS_ONLY on.

The row asks the panel at the container's own network address, to show the
panel listens where Docker publishes it. With PAPERPULL_HOSTS_ONLY on, that
address is answered with the panel's own refusal unless it is listed, which
still shows the panel listens there, so the row passes and says why. A page
there with the address not listed means the panel never took the setting,
and nothing listed means no other device can open the panel, so both fail.
Off, only a page passes, as before. The self-test keeps its own copy of the
values that turn the setting on, and this holds the copy to the panel's.
"""
import ast
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

import selftest  # noqa: E402

ADDRESS = "172.18.0.2"
REFUSAL = ("This PaperPull Server was asked for as %s, and PAPERPULL_HOSTS_ONLY is on, so it "
           "answers only to the names and addresses in PAPERPULL_HOSTS." % ADDRESS)


def setting(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("%s is not set in %s" % (name, path))


def test_the_self_test_turns_the_setting_on_for_what_the_panel_does():
    assert setting(SERVER / "selftest.py", "HOSTS_ONLY_ON") == \
        setting(REPO / "gui" / "server_mode.py", "HOSTS_ONLY_ON")


@pytest.fixture
def row(monkeypatch):
    """network_checks against a panel that answers `status` and `body` at
    the container's address and a screen sharing server that does not
    answer there. Answers the row it printed."""
    def run(status, body="", hosts_only="", hosts=""):
        monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", hosts_only)
        monkeypatch.setenv("PAPERPULL_HOSTS", hosts)
        monkeypatch.setattr(selftest.socket, "gethostname", lambda: "box")
        monkeypatch.setattr(selftest.socket, "gethostbyname", lambda name: ADDRESS)

        def refuse(*args, **kwargs):
            raise OSError("refused")
        monkeypatch.setattr(selftest.socket, "create_connection", refuse)
        monkeypatch.setattr(selftest, "answer_of", lambda url: (status, body))
        monkeypatch.setattr(selftest, "results", [])
        selftest.network_checks()
        return selftest.results[-1]
    return run


def test_off_only_a_page_passes(row):
    assert row(200)[1]
    assert not row(400, REFUSAL)[1]


def test_on_the_panels_refusal_of_an_unlisted_address_passes_and_says_why(row):
    name, ok, said = row(400, REFUSAL, "1", "nas.local")
    assert name == "network" and ok
    assert "refusing an address PAPERPULL_HOSTS_ONLY leaves out" in said


def test_on_a_refusal_that_does_not_name_the_setting_fails(row):
    assert not row(400, "Bad Request", "1", "nas.local")[1]


def test_on_a_page_at_an_unlisted_address_fails_since_the_setting_never_reached_the_panel(row):
    name, ok, said = row(200, "", "1", "nas.local")
    assert not ok and "the address is not listed" in said


@pytest.mark.parametrize("hosts", [ADDRESS, "nas.local, %s" % ADDRESS, "http://%s:8765/" % ADDRESS])
def test_on_a_page_at_a_listed_address_passes(row, hosts):
    assert row(200, "", "1", hosts)[1]


def test_on_a_refusal_of_a_listed_address_fails(row):
    assert not row(400, REFUSAL, "1", ADDRESS)[1]


def test_on_with_nothing_listed_fails_and_says_no_other_device_can_open_it(row):
    name, ok, said = row(400, REFUSAL, "1", "")
    assert not ok and "lists nothing" in said and "no other device" in said


@pytest.mark.parametrize("status", [401, 403, 404, 500, 0])
def test_on_any_other_answer_fails(row, status):
    assert not row(status, REFUSAL, "1", "nas.local")[1]
