#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure compiler-helper unit tests -- no design build (PARSE_FILE may be
called incidentally, but that's not what's under test). See
elab_introspect_tests.py for tests whose whole point IS parsing a design and
inspecting the resulting parser_state/FuncLogicLookupTable/raised errors.

Run standalone: python3 unit_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main


def get_tests() -> list:
    tests = []
    # AUTOFSM scheduler/code-generator unit tests: exact schedule, register
    # allocation, byte-identical generated source across re-elaborations --
    # not visible in a build log, would otherwise only be checked indirectly
    # by full synthesis runs. Calls PY_TO_LOGIC.PARSE_FILE incidentally.
    tests.append(
        Test(
            name="autofsm_unit_test",
            category="unit",
            cmd=[INST_DIR / "autofsm_unit_test.py"],
        )
    )
    # Pure-unit tests for the AUTOPIPELINE .latency machinery
    # (SYN.HARVEST_AUTOPIPELINE_LATENCIES grouping + divergence detection,
    # SYN.SEED_TIMING_PARAMS_FROM_PREVIOUS two-tier matching + call-site-change
    # detection, CANONICAL_CALLABLE_KEY determinism, latency cache/read-flag
    # behavior) against hand-built fixtures -- no design build involved.
    tests.append(
        Test(
            name="autopipeline_harvest_test",
            category="unit",
            cmd=[INST_DIR / "autopipeline_harvest_test.py"],
        )
    )
    # Pure-unit tests for readable, hierarchical canonical names of
    # factory-closure functions (_canonical_func_name/_callable_canonical_name)
    # against hand-built fixtures, plus a PARSE_FILE regression test for the
    # factory-closure ast_meta src_file/line fix.
    tests.append(
        Test(
            name="factory_closure_naming_test",
            category="unit",
            cmd=[INST_DIR / "factory_closure_naming_test.py"],
        )
    )
    # Meta-test: every inst/*_test.py file must be registered in some
    # category module (see the file's own docstring) -- catches dead test
    # files and stale registrations after a rename/delete.
    tests.append(
        Test(
            name="registration_audit_test",
            category="unit",
            cmd=[INST_DIR / "registration_audit_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline pure compiler-helper unit tests."))
