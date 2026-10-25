# pyright: reportInvalidTypeForm=none
"""Known issue: a callee shared by a scoped caller and an unscoped caller gets
one entity, built under whichever caller is elaborated first.

helper is a factory closure, so it is elaborated on demand, inside its first
caller's scope. scoped_caller (register_soft_add(scope=scoped_caller)) is
called first here, so the one helper entity gets the soft adder, and
plain_caller, which has no scope, uses it too. Calling plain_caller first
gives both the built-in adder instead. The entity name and specialization key
do not include the registrations the callee looked up.

Native simulation applies a scope to the scoped function's callees (option B
in the scoped-registration plan), so the expected hardware is two helper
entities: the soft adder under scoped_caller, the built-in one under
plain_caller. Checked by scoped_operator_registration_test.py
(known_issues_tests.py).
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
        "include", "pypeline",
    ),
)

from pypeline import MAIN, hw_func, uint9_t
from operators.soft import register_soft_add


def make_helper():
    @hw_func
    def helper(a: uint9_t, b: uint9_t) -> uint9_t:
        return a + b

    return helper


helper = make_helper()


def make_scoped_caller():
    @hw_func
    def scoped_caller(a: uint9_t, b: uint9_t) -> uint9_t:
        return helper(a, b)

    register_soft_add(scope=scoped_caller)
    return scoped_caller


scoped_caller = make_scoped_caller()


def make_plain_caller():
    @hw_func
    def plain_caller(a: uint9_t, b: uint9_t) -> uint9_t:
        return helper(a, b)

    return plain_caller


plain_caller = make_plain_caller()


@MAIN
def scoped_shared_callee_main(a: uint9_t, b: uint9_t) -> uint9_t:
    x = scoped_caller(a, b)
    y = plain_caller(x, b)
    return y
