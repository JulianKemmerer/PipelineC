import shlex
import sys

from hypothesis import given
from hypothesis.strategies import text

from src import utilities


@given(text())
def test_get_tool_path(s):
    try:
        utilities.GET_TOOL_PATH(s)
    except Exception as e:
        # Exceptions should not be raised here
        assert False, f"string: {s} caused exception {e}"


def test_get_version_str():
    version = utilities.GET_VERSION_STR()
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_command_line_str_round_trips():
    assert shlex.split(utilities.GET_COMMAND_LINE_STR()) == sys.argv


def test_get_version_str_no_git(monkeypatch):
    monkeypatch.setattr(utilities, "_GIT", lambda argv: None)
    monkeypatch.setattr(utilities, "_VERSION_STR", None)
    version = utilities.GET_VERSION_STR()
    assert isinstance(version, str)
    assert len(version) > 0
