from hypothesis import given
from hypothesis.strategies import text

import utilities


@given(text())
def test_get_tool_path(s):
    try:
        utilities.GET_TOOL_PATH(s)
    except Exception as e:
        # Exceptions should not be raised here
        assert False, f"string: {s} caused exception {e}"
