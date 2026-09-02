#!/usr/bin/env python3
"""Focused sky130 acceptance for packed user-type MUX splitting.

This opt-in benchmark runs one ordinary 180 MHz arithmetic Divider sweep.
Its loop-carried 32-bit values are single-field structs, so success exercises
the same physical MUX refinement already accepted for the plain uint Divider.
"""

import argparse
import json
from pathlib import Path
import sys

import divider_continuity_bench as continuity


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = (
    REPO_ROOT
    / "src"
    / "tests"
    / "pypeline_tests"
    / "qor"
    / "divider"
    / "arithmetic_struct_mux.py"
)
TARGET_MHZ = 180.0
REFERENCE_FMAX_MHZ = 194.2227297
REFERENCE_STAGES = 50
FMAX_TOLERANCE = 0.01
WRAPPER_MUX_PREFIX = "MUX_wrapped_uint32_t"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out_dir", type=Path, required=True)
    parser.add_argument("--continue", dest="continue_existing", action="store_true")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write acceptance evidence but return zero when a gate fails.",
    )
    return parser.parse_args(argv)


def _cache_files(cache_dir, name):
    return sorted(str(path) for path in cache_dir.rglob(name))


def _wrapper_mux_placements(trace):
    placements = []
    for main in trace.get("mains", {}).values():
        placements.extend(
            placement
            for placement in main.get("final_selected", ())
            if placement.get("function", "").startswith(WRAPPER_MUX_PREFIX)
        )
    return placements


def main(argv=None):
    args = _parse_args(argv)
    out_dir = args.out_dir.resolve()
    record_path = out_dir / "struct_mux_acceptance.json"
    if out_dir.exists() and any(out_dir.iterdir()) and not args.continue_existing:
        raise ValueError(
            f"output directory must be empty unless --continue is used: {out_dir}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "path_delay_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / "sweep_180mhz"
    sweep_record_path = run_dir / "continuity_sweep.json"
    if sweep_record_path.is_file():
        record = json.loads(sweep_record_path.read_text())
    else:
        if run_dir.exists():
            raise RuntimeError(f"incomplete sweep directory: {run_dir}")
        record = continuity._build_normal_sweep(
            SOURCE, SOURCE, TARGET_MHZ, run_dir, cache_dir
        )

    trace_path = run_dir / "top" / "placement_trace.json"
    trace = json.loads(trace_path.read_text()) if trace_path.is_file() else {}
    wrapper_placements = _wrapper_mux_placements(trace)
    chunked = [
        placement
        for placement in wrapper_placements
        if placement.get("kind") == "bit_internal"
        and placement.get("bit_width") == 32
        and placement.get("bit_boundary") == 16
        and placement.get("realized")
    ]
    # Terminal step is bit-index i == 0; the source counts i DOWN via
    # `for i in range(31, -1, -1)`, so instance names (which carry the
    # unroll ORDINAL, not the loop value) place i == 0 at the LAST
    # unrolled copy, ordinal 31.
    terminal_chunked = any(
        "FOR_i_ITER_31_MUX_" in placement.get("instance_path", "")
        and "if_remainder" in placement.get("instance_path", "")
        for placement in chunked
    )
    exact_final = record.get("exact_final", {})
    metrics = exact_final.get("metrics", {})
    functional = exact_final.get("functional", {})
    mapping_checks = exact_final.get("mapping_checks", {})
    fmax = metrics.get("fmax_mhz")
    uint_delay_files = _cache_files(cache_dir, "MUX_uint32_t.delay")
    uint_timing_files = _cache_files(cache_dir, "MUX_uint32_t.timing.json")
    wrapper_delay_files = [
        str(path)
        for path in cache_dir.rglob("*.delay")
        if WRAPPER_MUX_PREFIX in path.name
    ]
    checks = {
        "build_passed": record.get("build", {}).get("returncode") == 0,
        "expected_depth": (
            record.get("slices") == REFERENCE_STAGES - 1
            and record.get("stages") == REFERENCE_STAGES
        ),
        "timing_met": fmax is not None and fmax >= TARGET_MHZ,
        "fmax_matches_plain_uint_within_one_percent": (
            fmax is not None
            and abs(fmax - REFERENCE_FMAX_MHZ) / REFERENCE_FMAX_MHZ
            <= FMAX_TOLERANCE
        ),
        "trace_schema_5": trace.get("schema_version") == 5,
        "wrapper_muxes_chunked_at_midpoint": (
            bool(wrapper_placements)
            and len(chunked) == len(wrapper_placements)
        ),
        "terminal_wrapper_mux_chunked": terminal_chunked,
        "functional_141_vectors_passed": (
            functional.get("passed")
            and functional.get("valid_vectors") == 141
        ),
        "mapped_topology_passed": all(
            mapping_checks.get(name, False)
            for name in (
                "stage_semantics",
                "mapping_succeeded",
                "zero_unmapped_cells",
                "complete_timing_topology",
                "timing_recipe_matches",
                "timing_model_identity_matches",
                "timing_vhdl_bytes_match_snapshot",
            )
        ),
        "canonical_uint_mux_delay_cached": bool(uint_delay_files),
        "canonical_uint_mux_components_cached": bool(uint_timing_files),
        "no_wrapper_named_mux_delay_cache": not wrapper_delay_files,
    }
    acceptance = {
        "source": continuity._source_record(SOURCE),
        "target_mhz": TARGET_MHZ,
        "plain_uint_reference": {
            "stages": REFERENCE_STAGES,
            "fmax_mhz": REFERENCE_FMAX_MHZ,
            "tolerance_fraction": FMAX_TOLERANCE,
        },
        "result": {
            "slices": record.get("slices"),
            "stages": record.get("stages"),
            "fmax_mhz": fmax,
            "functional": functional,
            "wrapper_mux_placement_count": len(wrapper_placements),
            "chunked_wrapper_mux_count": len(chunked),
            "uint_delay_files": uint_delay_files,
            "uint_timing_files": uint_timing_files,
            "wrapper_delay_files": wrapper_delay_files,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    continuity._write_json(record_path, acceptance)
    print(json.dumps(acceptance, indent=2, sort_keys=True))
    if not acceptance["passed"] and not args.diagnostic:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
