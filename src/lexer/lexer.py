from enum import Enum


class Token(Enum):
    Identifier = 1,
    Semicolon = 2,
    LParen = 3,
    RParen = 4,
    LBracket = 5,
    RBracket = 6,
    Assignment = 7,
    Equals = 8,
    Integer = 9
    Float = 10,
    Plus = 11,
    Minus = 12,
    Times = 13,
    Divide = 14,
    PlusEquals = 15,
    MinusEquals = 16,
    TimesEquals = 17,
    DivideEquals = 18,


def split_lines(string):
    if len(string) == 0:
        return []
    else:
        return string.split("\n")
