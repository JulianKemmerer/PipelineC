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
    # Meta-test: every markdown link/anchor in the repo resolves (in-page and
    # cross-file) -- catches stale doc links after a heading rename/move.
    tests.append(
        Test(
            name="doc_links_test",
            category="unit",
            cmd=[INST_DIR / "doc_links_test.py"],
        )
    )
    # Raw-HDL leaf split model: SPLIT_KIND classification (RAW_VHDL.
    # GET_LEAF_SPLIT_KIND/LEAF_MAX_SPLIT_SLICES) and the equal-width bit
    # allocator (RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_DICT) that replaced an
    # earlier, real-synthesis-disproven curve-inversion approach -- see the
    # test file's own docstring for what broke and why.
    tests.append(
        Test(
            name="leaf_split_unit_test",
            category="unit",
            cmd=[INST_DIR / "leaf_split_unit_test.py"],
        )
    )
    # SWEEP.PLAN_CUTS boundary-snap: prefer a real segment boundary over a
    # mid-segment cut within a bounded budget overrun, found necessary by
    # testing the real divider design against real sky130 synthesis (a low
    # cut count merged a SLICEABLE_1LL leaf into a neighboring stage instead
    # of getting its own boundary) -- see the test file's own docstring.
    tests.append(
        Test(
            name="plan_cuts_boundary_snap_test",
            category="unit",
            cmd=[INST_DIR / "plan_cuts_boundary_snap_test.py"],
        )
    )
    # Three bugs found during this session's audit, previously undetected:
    # SWEEP.AT_PREDICTED_FLOOR's missing upper bound (a floor-stop could
    # fire arbitrarily far above a stale/under-predicted floor),
    # SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS (restoring the best-seen result
    # never re-checked whether it actually met its goal before writing it
    # out), and RAW_VHDL.GET_LEAF_BIT_WIDTH + the SLICEABLE legal-unit cap
    # (a narrow leaf could accept far more cuts than its own width usefully
    # supports) -- see the test file's own docstring.
    tests.append(
        Test(
            name="floor_and_bits_cap_unit_test",
            category="unit",
            cmd=[INST_DIR / "floor_and_bits_cap_unit_test.py"],
        )
    )
    # Typed operation-boundary/bit-internal placement and direct lowering.
    tests.append(
        Test(
            name="typed_pipeline_placement_test",
            category="unit",
            cmd=[INST_DIR / "typed_pipeline_placement_test.py"],
        )
    )
    # SWEEP.RANK_PATH_FUNC_CANDIDATES / RESOLVE_PIPELINABLE_HOTSPOT: critical
    # path attribution ranked candidates by summed matched-substring length,
    # which has no depth signal (every ancestor's name is a substring of a
    # descendant register's name) and so always favored the single longest
    # candidate name. Found for real on wireguard-fpga's decrypt path: a
    # long auto-generated interface-func wrapper name outscored the actual
    # on-path `chacha20_chacha20_block_step`, so the sweep declared the path
    # unpipelinable (feedback_vars on the wrapper) and stopped 3x too early
    # -- see the test file's own docstring.
    tests.append(
        Test(
            name="path_attribution_test",
            category="unit",
            cmd=[INST_DIR / "path_attribution_test.py"],
        )
    )
    # DEVICE_MODELS sky130 STA diagnostics and fixed internal synthesis
    # recipes: component sums, endpoint semantics, structured arc traces,
    # and recipe-scoped cache/artifact identities. Uses tiny mapped-JSON
    # fixtures only; no external synthesis tool is invoked.
    tests.append(
        Test(
            name="device_models_sta_test",
            category="unit",
            cmd=[INST_DIR / "device_models_sta_test.py"],
        )
    )
    # Fast schema/parser coverage for the opt-in, hours-long Divider sky130
    # QoR harness.  The real benchmark itself is intentionally not in run_all.
    tests.append(
        Test(
            name="divider_qor_bench_unit_test",
            category="unit",
            cmd=[INST_DIR / "divider_qor_bench_unit_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline pure compiler-helper unit tests."))
