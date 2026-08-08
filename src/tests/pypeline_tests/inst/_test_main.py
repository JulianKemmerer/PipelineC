#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared __main__ harness for inst/*.py test files.

Instead of a hand-maintained list of test_* calls in each file's __main__
block (which silently drops a function if someone forgets to add it), a file
does:

    if __name__ == "__main__":
        from _test_main import run_module_tests
        run_module_tests()

and every test_* callable defined at module scope in that file runs
automatically, in definition order, with a PASS/FAIL line each and a final
summary. Any AssertionError (or other exception) is reported as a FAIL and
the process exits nonzero if anything failed -- run_all.py's Test entries
still just check the exit code.

This intentionally only fires under `python3 inst/X.py` (__name__ ==
"__main__"). It never fires when pypelinec elaborates the same file as a
design: PY_TO_LOGIC.PARSE_FILE imports it as module "pypeline_design", not
"__main__" (src/PY_TO_LOGIC.py), so elab/synth-category registrations of a
file that also has native_sim test_* functions never execute them -- as
before.
"""

import sys
import traceback


def run_module_tests() -> None:
    caller = sys.modules["__main__"]
    test_names = [
        name
        for name in vars(caller)
        if name.startswith("test_") and callable(getattr(caller, name))
    ]
    # Definition order, not alphabetical -- matches what hand-written
    # __main__ blocks did, and keeps setup-shaped tests (if any) predictable.
    test_names.sort(key=lambda n: getattr(caller, n).__code__.co_firstlineno)

    if not test_names:
        print("WARNING: no test_* functions found in this module", file=sys.stderr)

    failures = []
    for name in test_names:
        fn = getattr(caller, name)
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception:
            print(f"[FAIL] {name}")
            traceback.print_exc()
            failures.append(name)

    total = len(test_names)
    passed = total - len(failures)
    print(f"\n{passed}/{total} test functions passed.")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        sys.exit(1)
