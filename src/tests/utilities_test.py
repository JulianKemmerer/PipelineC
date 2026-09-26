import shlex
import sys

from hypothesis import given
from hypothesis.strategies import integers, text

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


@given(integers(min_value=1, max_value=2**80))
def test_index_bit_width_holds_every_index(n):
    w = utilities.INDEX_BIT_WIDTH(n)
    assert w >= 1
    assert (1 << w) >= n  # 0..n-1 fits
    assert w == 1 or (1 << (w - 1)) < n  # and no wider than needed


def test_index_bit_width_known_values():
    # 1-element arrays get uint1_t, not uint0_t (issue #197)
    assert [utilities.INDEX_BIT_WIDTH(n) for n in (1, 2, 3, 4, 5, 128, 129)] == [
        1,
        1,
        2,
        2,
        3,
        7,
        8,
    ]
    # math.ceil(math.log(2**29, 2)) float rounding gives 30
    assert utilities.INDEX_BIT_WIDTH(2**29) == 29
