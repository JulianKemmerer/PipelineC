from hypothesis import given
from hypothesis.strategies import text

from lexer import split_lines


@given(text())
def test_split_lines(s):
    assert len(split_lines(s)) == len(s.split("\n"))
