from lexer import split_lines


def test_split_lines(string):
    assert len(split_lines("000\n0000")) == 2
