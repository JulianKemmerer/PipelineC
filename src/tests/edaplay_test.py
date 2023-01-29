from hypothesis import given
from hypothesis.strategies import integers

from src import EDAPLAY


@given(integers(1))
def test_setup_edaplay(some_int):
    try:
        EDAPLAY.SETUP_EDAPLAY
    except Exception as e:
        # Exceptions should not be raised here
        assert False, f"Integer: {some_int} caused exception {e}"
