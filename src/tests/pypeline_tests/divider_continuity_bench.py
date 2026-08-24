#!/usr/bin/env python3
"""Opt-in arithmetic Divider latency/fmax continuity benchmark.

This benchmark intentionally is not registered in ``run_all.py``.  A full
run maps and simulates every distinct automatic placement between 33 and 66
pipeline stages, then runs three ordinary timing-feedback sweeps.  It exists
to catch a QoR failure which a single-target benchmark cannot see: increasing
the requested fmax may select a shallower plan, or a deeper plan may map to
the same (or worse) fmax.

The input is the unchanged latchup arithmetic Divider.  Temporary variants
change only ``CLK_RATE_MHZ``.  DEVICE_MODELS.py and the production
``early_flatten_noabc`` recipe are evidence inputs, never tuning knobs.
"""

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import divider_qor_bench as _qor


REPO_ROOT = Path(__file__).resolve().parents[3]
PYPELINEC = REPO_ROOT / "src" / "pypelinec"
DIVIDER_QOR_BENCH = Path(__file__).resolve().parent / "divider_qor_bench.py"
DEFAULT_SOURCE = Path(
    "/home/julian/Desktop/earlyflatten_latchupdiv/33cycles_161mhz/solution.py"
)
EXPECTED_SOURCE_SHA256 = (
    "cfde3ad82985716544df580bb9415c6cbc4efa03ed4687b14a774e1bda56f70f"
)
EXPECTED_DEVICE_MODELS_SHA256 = (
    "165ee9474a42a8f7e7c124e89ecafc09ef46192f728fbed65c4c02ae044178ed"
)
RECIPE = "early_flatten_noabc"
DEFAULT_GOALS = (
    135.5,
    140.0,
    142.0,
    143.0,
    144.0,
    145.0,
    150.0,
    155.0,
    160.0,
    167.0,
    175.0,
    180.0,
    190.0,
    195.0,
    200.0,
    205.0,
    210.0,
    214.0,
    250.0,
    284.0,
)
DEFAULT_NORMAL_SWEEP_GOALS = (135.5, 180.0, 210.0)
MIN_USEFUL_STAGES = 33
MAX_USEFUL_STAGES = 66
MID_MIN_STAGES = 45
MID_MAX_STAGES = 53
BASELINE_LOW_FMAX_MHZ = 169.574
BASELINE_HIGH_FMAX_MHZ = 221.944
FMAX_NOISE_FRAC = 0.01
MID_GAIN_FRAC = 0.10

# C_TO_LOGIC.py's duplicate-instance-collapsing pass emits a coordinate
# fragment (e.g. ``_py_l34_l35_``) that is now sorted deterministically, so
# two builds of the same source always spell it the same way. The trailing
# per-build content hash (``_DUPLICATE_abcd``) is unrelated to physical
# placement identity, so it is still normalized out of the placement
# fingerprint here; actual VHDL hashes remain unmodified evidence.
_DUPLICATE_HASH_RE = re.compile(r"_DUPLICATE_[0-9a-fA-F]+")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _goal_text(goal):
    return format(float(goal), ".15g")


def _goal_tag(goal):
    return _goal_text(goal).replace("-", "m").replace(".", "p")


def _derive_source(original, goal):
    """Change exactly one CLK_RATE_MHZ assignment and nothing else."""
    pattern = re.compile(r"^CLK_RATE_MHZ\s*=\s*[^\r\n]+$", re.MULTILINE)
    matches = list(pattern.finditer(original))
    if len(matches) != 1:
        raise ValueError(
            f"expected one CLK_RATE_MHZ assignment, found {len(matches)}"
        )
    return pattern.sub(f"CLK_RATE_MHZ = {_goal_text(goal)}", original)


def _run_logged(argv, log_path, env=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(value) for value in argv],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        returncode = proc.wait()
    return returncode, time.monotonic() - started


def _normalized_placement(placement):
    """Fields which identify physical hardware, excluding goal/trace noise."""
    value = {
        key: placement.get(key)
        for key in (
            "kind",
            "instance_path",
            "function",
            "axis_unit",
            "bit_width",
            "bit_boundary",
            "bit_split_ordinal",
            "bit_split_count",
            "boundary_register",
            "fixed",
        )
        if placement.get(key) is not None
    }
    for key in ("instance_path", "function"):
        if isinstance(value.get(key), str):
            value[key] = _canonicalize_duplicate_name(value[key])
    return value


def _canonicalize_duplicate_name(value):
    return _DUPLICATE_HASH_RE.sub("_DUPLICATE", value)


def placement_fingerprint(trace_path):
    trace = json.loads(Path(trace_path).read_text())
    placements = []
    for main_name, main in sorted(trace.get("mains", {}).items()):
        for placement in main.get("final_selected", []):
            if placement.get("realized"):
                placements.append(
                    {
                        "main": _canonicalize_duplicate_name(main_name),
                        **_normalized_placement(placement),
                    }
                )
    placements.sort(key=lambda value: json.dumps(value, sort_keys=True))
    encoded = json.dumps(placements, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), placements


def _source_record(path):
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _launch_context(source, original_source, goal):
    return {
        "created_utc": _datetime.datetime.now(
            _datetime.timezone.utc
        ).isoformat(),
        "repository": _qor._repo_state(),
        "compiler_sources": _qor._compiler_source_records(),
        "model": _qor._model_record(RECIPE),
        "continuity_source": _source_record(source),
        "original_source": _source_record(original_source),
        "goal_mhz": goal,
        "evidence_note": (
            "arithmetic Divider continuity plan; derived source changes only "
            "CLK_RATE_MHZ"
        ),
    }


def _read_plan_record(run_dir):
    path = run_dir / "continuity_plan.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _build_plan(
    source_path,
    original_source,
    goal,
    run_dir,
    cache_dir,
    placement_config=None,
    chunked_mux=False,
    exact_requested_bits=False,
):
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(
        run_dir / "launch_context.json",
        _launch_context(source_path, original_source, goal),
    )
    env = os.environ.copy()
    env["PYPELINEC_PATH_DELAY_CACHE_DIR"] = str(cache_dir.resolve())
    if placement_config is not None:
        env["PIPELINEC_INTERNAL_PLACEMENT_FILE"] = str(
            Path(placement_config).resolve()
        )
    if exact_requested_bits:
        env["PIPELINEC_INTERNAL_EXACT_REQUESTED_BITS"] = "1"
    cmd = [
        PYPELINEC,
        source_path,
        "--syn_tool",
        "sky130",
        "--out_dir",
        run_dir,
        "--no_sweep",
        "--no_hier_syn",
    ]
    returncode, runtime = _run_logged(cmd, run_dir / "build.log", env=env)
    build_text = (run_dir / "build.log").read_text(errors="replace")
    slices = _qor._parse_depth(build_text)
    stages = _qor._reported_pipeline_stages(build_text, slices)
    trace_path = run_dir / "top" / "placement_trace.json"
    fingerprint = placements = None
    if trace_path.is_file():
        fingerprint, placements = placement_fingerprint(trace_path)
    _, vhdl_records = _qor._final_vhdl_records(run_dir)
    record = {
        "schema_version": 1,
        "goal_mhz": goal,
        "source": _source_record(source_path),
        "build": {
            "command": [str(value) for value in cmd],
            "returncode": returncode,
            "runtime_seconds": runtime,
            "log_sha256": _sha256(run_dir / "build.log"),
        },
        "slices": slices,
        "stages": stages,
        "placement_fingerprint": fingerprint,
        "placements": placements,
        "final_vhdl": vhdl_records,
        "internal_placement_config": (
            None if placement_config is None else _source_record(placement_config)
        ),
        "internal_chunked_mux": bool(chunked_mux),
        "internal_exact_requested_bits": bool(exact_requested_bits),
    }
    _write_json(run_dir / "continuity_plan.json", record)
    return record


def _exact_boundary_config(
    reference_run_dir,
    boundary,
    phase="automatic",
    divide_zero="automatic",
    chunked_mux_boundary=None,
    chunked_mux_terminal=False,
):
    """Replace a one-cut-per-leaf plan with the requested physical bit cut."""
    trace_path = reference_run_dir / "top" / "placement_trace.json"
    trace = json.loads(trace_path.read_text())
    selected = []
    for main in trace.get("mains", {}).values():
        selected.extend(main.get("final_selected", ()))
    output_selectors = []
    exact_groups = []
    bit_widths = set()
    for placement in selected:
        if not placement.get("realized"):
            continue
        if placement.get("kind") == "instance_output":
            output_selectors.append({"candidate_id": placement["candidate_id"]})
        elif placement.get("kind") == "bit_internal":
            if int(placement.get("bit_split_count", 0)) != 1:
                raise ValueError(
                    "exact-boundary scan requires one split per selected leaf"
                )
            bit_widths.add(int(placement["bit_width"]))
            exact_groups.append(
                {
                    "instance_path": placement["instance_path"],
                    "boundaries": [int(boundary)],
                }
            )
    if bit_widths != {34} or not exact_groups:
        raise ValueError(
            f"reference plan is not the expected split-34-bit schedule: "
            f"widths={bit_widths}, groups={len(exact_groups)}"
        )
    if not 1 <= int(boundary) < 34:
        raise ValueError(f"exact Divider subtract boundary must be in 1..33")
    if phase == "odd":
        candidates = []
        for main in trace.get("mains", {}).values():
            candidates.extend(main.get("candidates", ()))
        output_by_instance = {
            placement["instance_path"]: placement["candidate_id"]
            for placement in candidates
            if placement.get("kind") == "instance_output"
        }
        minus_by_iteration = {}
        mux_by_iteration = {}
        for inst_path, candidate_id in output_by_instance.items():
            match = re.search(r"FOR_i_(\d+)_(BIN_OP_MINUS|MUX_uint32_t_if_remainder)", inst_path)
            if match is None:
                continue
            table = minus_by_iteration if match.group(2) == "BIN_OP_MINUS" else mux_by_iteration
            table[int(match.group(1))] = (inst_path, candidate_id)
        if set(minus_by_iteration) != set(range(32)) or set(mux_by_iteration) != set(range(32)):
            raise ValueError("reference trace lacks the 32 Divider iteration operations")
        output_selectors = []
        exact_groups = []
        for iteration in range(32):
            minus_path, minus_candidate = minus_by_iteration[iteration]
            _mux_path, mux_candidate = mux_by_iteration[iteration]
            if iteration % 2:
                exact_groups.append(
                    {"instance_path": minus_path, "boundaries": [int(boundary)]}
                )
                output_selectors.append({"candidate_id": mux_candidate})
            else:
                output_selectors.append({"candidate_id": minus_candidate})
        # The odd phase naturally has one more loop boundary than the even
        # phase because iteration 31 includes its MUX output.  Omitting the
        # independent divide-by-zero output boundary keeps the comparison at
        # the same 48 slices.  ``on`` is retained as an explicit 49-slice A/B.
        if divide_zero == "on":
            divzero = [
                placement
                for placement in selected
                if placement.get("kind") == "instance_output"
                and "MUX_uint32_t_ifexpr" in placement.get("instance_path", "")
            ]
            if len(divzero) != 1:
                raise ValueError("reference trace lacks one divide-by-zero boundary")
            output_selectors.append({"candidate_id": divzero[0]["candidate_id"]})
    elif phase != "automatic":
        raise ValueError(f"unknown exact-boundary phase: {phase}")
    elif divide_zero == "off":
        output_selectors = [
            selector
            for selector in output_selectors
            if "MUX_uint32_t_ifexpr" not in selector["candidate_id"]
        ]
    elif divide_zero not in ("automatic", "on"):
        raise ValueError(f"unknown divide-zero boundary mode: {divide_zero}")
    if chunked_mux_boundary is not None:
        chunked_mux_boundary = int(chunked_mux_boundary)
        if not 1 <= chunked_mux_boundary < 32:
            raise ValueError("chunked uint32 MUX boundary must be in 1..31")
        mux_source = selected
        if chunked_mux_terminal:
            mux_source = list(selected)
            terminal_muxes = []
            for main in trace.get("mains", {}).values():
                terminal_muxes.extend(
                    placement
                    for placement in main.get("candidates", ())
                    if "FOR_i_0_MUX_uint32_t_if_remainder"
                    in placement.get("instance_path", "")
                )
            if len(terminal_muxes) != 1:
                raise ValueError(
                    f"expected one terminal iteration-0 MUX, found "
                    f"{len(terminal_muxes)}"
                )
            mux_source.extend(terminal_muxes)
        mux_outputs = [
            placement
            for placement in mux_source
            if placement.get("kind") == "instance_output"
            and "MUX_uint32_t_if_remainder" in placement.get("instance_path", "")
        ]
        mux_ids = {placement["candidate_id"] for placement in mux_outputs}
        output_selectors = [
            selector
            for selector in output_selectors
            if selector["candidate_id"] not in mux_ids
        ]
        exact_groups.extend(
            {
                "instance_path": placement["instance_path"],
                "boundaries": [chunked_mux_boundary],
            }
            for placement in mux_outputs
        )
    return {
        "version": 1,
        "mode": "replace",
        "selectors": output_selectors,
        "exact_bit_boundaries": exact_groups,
    }


def _map_exact_leaf(plan_dir, boundary, evidence_dir):
    """Map the generated split-subtractor entity without Divider context."""
    vhdl_paths = [
        Path(raw_path) for raw_path in (plan_dir / "vhdl_files.txt").read_text().split()
    ]
    candidates = []
    for path in vhdl_paths:
        if "BIN_OP_MINUS_uint34_t_uint34_t" not in str(path):
            continue
        body = path.read_text()
        if (
            f"bits_per_stage_dict[0] = {boundary}" in body
            and f"bits_per_stage_dict[1] = {34 - boundary}" in body
        ):
            candidates.append((path, body))
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one exact boundary-{boundary} subtract entity, "
            f"found {len(candidates)} in {plan_dir}"
        )
    source, body = candidates[0]
    entity_match = re.search(r"^entity\s+(\S+)\s+is\s*$", body, re.MULTILINE)
    if entity_match is None:
        raise RuntimeError(f"could not find entity name in {source}")
    entity = entity_match.group(1)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    device_models = _qor._compiler_module("DEVICE_MODELS")
    timing_log = evidence_dir / "isolated_exact_subtract.log"
    started = time.monotonic()
    device_models._run_synth_and_sta(
        " ".join(
            str(path)
            for path in vhdl_paths
            if path.name in ("c_structs_pkg.pkg.vhd", "global_wires_pkg.pkg.vhd")
        )
        + " "
        + str(source),
        entity,
        evidence_dir,
        timing_log,
        RECIPE,
    )
    runtime = time.monotonic() - started
    timing_path = timing_log.with_name(timing_log.stem + "_timing.json")
    timing = json.loads(timing_path.read_text())
    artifacts = device_models._get_synthesis_recipe_artifact_paths(
        entity, evidence_dir, RECIPE
    )
    mapped_path = Path(artifacts["mapped_json"])
    return {
        "boundary": boundary,
        "chunks": [boundary, 34 - boundary],
        "source": _source_record(source),
        "entity": entity,
        "runtime_seconds": runtime,
        "timing": timing,
        "mapped": _qor._mapped_netlist_metrics(mapped_path),
    }


def _map_frozen(run_dir, map_dir, cache_dir):
    cmd = [
        sys.executable,
        DIVIDER_QOR_BENCH,
        "--variant",
        "arithmetic",
        "--recipe",
        RECIPE,
        "--frozen-vhdl-source",
        run_dir,
        "--out_dir",
        map_dir,
        "--diagnostic",
        "--evidence-note",
        "arithmetic Divider continuity immutable mapping",
    ]
    plan = _read_plan_record(run_dir)
    if plan and plan.get("slices") is not None:
        cmd += ["--existing-latency", str(plan["slices"])]
    env = os.environ.copy()
    env["PYPELINEC_PATH_DELAY_CACHE_DIR"] = str(cache_dir.resolve())
    returncode, runtime = _run_logged(cmd, map_dir.parent / f"{map_dir.name}.log", env)
    evidence_path = map_dir / "recipe_evidence.json"
    if not evidence_path.is_file():
        raise RuntimeError(
            f"frozen map produced no recipe_evidence.json (rc={returncode}): {map_dir}"
        )
    evidence = json.loads(evidence_path.read_text())
    return {
        "returncode": returncode,
        "runtime_seconds": runtime,
        "evidence": str(evidence_path),
        "metrics": evidence.get("metrics", {}),
        "functional": evidence.get("functional", {}),
        "mapping_checks": evidence.get("acceptance", {}).get("checks", {}),
    }


def _build_normal_sweep(source_path, original_source, goal, run_dir, cache_dir):
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(
        run_dir / "launch_context.json",
        _launch_context(source_path, original_source, goal),
    )
    env = os.environ.copy()
    env["PYPELINEC_PATH_DELAY_CACHE_DIR"] = str(cache_dir.resolve())
    cmd = [
        PYPELINEC,
        source_path,
        "--syn_tool",
        "sky130",
        "--out_dir",
        run_dir,
        "--no_hier_syn",
    ]
    returncode, runtime = _run_logged(cmd, run_dir / "build.log", env=env)
    build_text = (run_dir / "build.log").read_text(errors="replace")
    slices = _qor._parse_depth(build_text)
    stages = _qor._reported_pipeline_stages(build_text, slices)
    trace_path = run_dir / "top" / "placement_trace.json"
    fingerprint = placements = None
    if trace_path.is_file():
        fingerprint, placements = placement_fingerprint(trace_path)
    record = {
        "goal_mhz": goal,
        "source": _source_record(source_path),
        "build": {
            "command": [str(value) for value in cmd],
            "returncode": returncode,
            "runtime_seconds": runtime,
        },
        "slices": slices,
        "stages": stages,
        "placement_fingerprint": fingerprint,
        "placements": placements,
    }
    if (run_dir / "vhdl_files.txt").is_file():
        record["exact_final"] = _map_frozen(
            run_dir, run_dir / "exact_final_remap", cache_dir
        )
    _write_json(run_dir / "continuity_sweep.json", record)
    return record


def _best_point(points, min_stages, max_stages):
    candidates = [
        point
        for point in points
        if min_stages <= point["stages"] <= max_stages
        and point.get("fmax_mhz") is not None
    ]
    return max(candidates, key=lambda point: point["fmax_mhz"]) if candidates else None


def _acceptance(plans, mapped, sweeps, model_unchanged):
    ordered_plans = sorted(plans, key=lambda value: value["goal_mhz"])
    selected_depths = [
        value["stages"] for value in ordered_plans if value.get("stages") is not None
    ]
    depth_monotonic = all(
        later >= earlier
        for earlier, later in zip(selected_depths, selected_depths[1:])
    )

    # The --no_sweep maps characterize every initial planner shape, including
    # shapes a real sweep measures and then rejects.  Keep them as diagnostic
    # evidence, but judge returned QoR on the exact final artifacts from the
    # ordinary sweeps: those are the schedules users actually receive.
    diagnostic_points = []
    for item in mapped:
        metrics = item["mapping"].get("metrics", {})
        diagnostic_points.append(
            {
                "source": "initial_plan_diagnostic",
                "goal_mhz": item["goal_mhz"],
                "slices": item["slices"],
                "stages": item["stages"],
                "placement_fingerprint": item["placement_fingerprint"],
                "fmax_mhz": metrics.get("fmax_mhz"),
                "functional_passed": bool(
                    item["mapping"].get("functional", {}).get("passed")
                ),
                "mapping_checks": item["mapping"].get("mapping_checks", {}),
            }
        )
    points = []
    for item in sweeps:
        mapping = item.get("exact_final", {})
        metrics = mapping.get("metrics", {})
        if item.get("stages") is None or metrics.get("fmax_mhz") is None:
            continue
        points.append(
            {
                "source": "normal_sweep_final",
                "goal_mhz": item["goal_mhz"],
                "slices": item["slices"],
                "stages": item["stages"],
                "placement_fingerprint": item.get("placement_fingerprint"),
                "fmax_mhz": metrics.get("fmax_mhz"),
                "functional_passed": bool(
                    mapping.get("functional", {}).get("passed")
                ),
                "mapping_checks": mapping.get("mapping_checks", {}),
            }
        )
    points.sort(key=lambda value: value["stages"])
    diagnostic_points.sort(key=lambda value: value["stages"])
    low = _best_point(points, 32, 34)
    mid = _best_point(points, MID_MIN_STAGES, MID_MAX_STAGES)
    high = _best_point(points, 63, 66)
    measured = [point for point in points if point.get("fmax_mhz") is not None]
    fmax_nondecreasing = all(
        later["fmax_mhz"] >= earlier["fmax_mhz"] * (1.0 - FMAX_NOISE_FRAC)
        for earlier, later in zip(measured, measured[1:])
    )
    meaningful_gain_for_deeper = all(
        later["stages"] == earlier["stages"]
        or later["fmax_mhz"] >= earlier["fmax_mhz"] * (1.0 + FMAX_NOISE_FRAC)
        for earlier, later in zip(measured, measured[1:])
    )

    def physical_checks(point):
        if (
            point is None
            or not point.get("placement_fingerprint")
            or not point["functional_passed"]
        ):
            return False
        checks = point["mapping_checks"]
        return all(
            checks.get(name, False)
            for name in (
                "stage_semantics",
                "mapping_succeeded",
                "zero_unmapped_cells",
                "complete_timing_topology",
                "timing_recipe_matches",
                "timing_model_identity_matches",
                "timing_vhdl_bytes_match_snapshot",
            )
        )

    sweep_by_goal = {float(value["goal_mhz"]): value for value in sweeps}
    ordered_sweeps = sorted(sweeps, key=lambda value: value["goal_mhz"])
    sweep_depths = [
        value["stages"]
        for value in ordered_sweeps
        if value.get("stages") is not None
    ]
    sweep_depth_monotonic = all(
        later >= earlier
        for earlier, later in zip(sweep_depths, sweep_depths[1:])
    )
    normal_sweeps_pass = all(
        goal in sweep_by_goal
        and sweep_by_goal[goal]["build"]["returncode"] == 0
        and sweep_by_goal[goal].get("exact_final", {})
        .get("functional", {})
        .get("passed")
        for goal in DEFAULT_NORMAL_SWEEP_GOALS
    )
    intermediate_sweep_depth = sweep_by_goal.get(180.0, {}).get("stages")
    checks = {
        "device_models_unchanged": model_unchanged,
        "target_to_depth_monotonic": depth_monotonic,
        "normal_sweep_target_to_depth_monotonic": sweep_depth_monotonic,
        "automatic_fmax_nondecreasing_with_depth": fmax_nondecreasing,
        "deeper_automatic_schedule_has_meaningful_gain": (
            meaningful_gain_for_deeper
        ),
        "low_endpoint_preserved": (
            low is not None
            and low["fmax_mhz"]
            >= BASELINE_LOW_FMAX_MHZ * (1.0 - FMAX_NOISE_FRAC)
        ),
        "automatic_midpoint_exists": mid is not None,
        "midpoint_at_least_10_percent_above_low": (
            low is not None
            and mid is not None
            and mid["fmax_mhz"] >= low["fmax_mhz"] * (1.0 + MID_GAIN_FRAC)
        ),
        "high_endpoint_preserved": (
            high is not None
            and high["fmax_mhz"]
            >= BASELINE_HIGH_FMAX_MHZ * (1.0 - FMAX_NOISE_FRAC)
        ),
        "accepted_points_physically_verified": all(
            physical_checks(point) for point in (low, mid, high)
        ),
        "normal_sweeps_pass": normal_sweeps_pass,
        "intermediate_sweep_at_most_53_stages": (
            intermediate_sweep_depth is not None
            and intermediate_sweep_depth <= MID_MAX_STAGES
        ),
    }
    return {
        "thresholds": {
            "fmax_noise_fraction": FMAX_NOISE_FRAC,
            "mid_gain_fraction": MID_GAIN_FRAC,
            "mid_stage_range": [MID_MIN_STAGES, MID_MAX_STAGES],
            "baseline_low_fmax_mhz": BASELINE_LOW_FMAX_MHZ,
            "baseline_high_fmax_mhz": BASELINE_HIGH_FMAX_MHZ,
        },
        "points": points,
        "initial_plan_diagnostic_points": diagnostic_points,
        "selected": {"low": low, "mid": mid, "high": high},
        "checks": checks,
        "passed": all(checks.values()),
    }


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out_dir", type=Path, required=True)
    parser.add_argument("--goals", type=float, nargs="*", default=DEFAULT_GOALS)
    parser.add_argument(
        "--normal-sweep-goals",
        type=float,
        nargs="*",
        default=DEFAULT_NORMAL_SWEEP_GOALS,
    )
    parser.add_argument(
        "--plans-only",
        action="store_true",
        help="Generate/fingerprint first plans without mapping or normal sweeps.",
    )
    parser.add_argument(
        "--exact-boundaries",
        type=int,
        nargs="*",
        default=(),
        help=(
            "Generate internal forced 49-stage variants whose selected "
            "34-bit subtractors use these exact boundaries (1..33)."
        ),
    )
    parser.add_argument(
        "--map-exact-boundaries",
        type=int,
        nargs="*",
        default=(),
        help="Immutable-remap/simulate only these generated exact variants.",
    )
    parser.add_argument(
        "--map-stages",
        type=int,
        nargs="*",
        default=(),
        help="Map only automatic representatives at these stage counts.",
    )
    parser.add_argument(
        "--exact-isolated-only",
        action="store_true",
        help=(
            "Run only isolated split-subtractor maps for --exact-boundaries; "
            "skip full baseline maps, full exact maps, normal sweeps, and gates."
        ),
    )
    parser.add_argument(
        "--exact-phase",
        choices=("automatic", "odd"),
        default="automatic",
        help="Loop-periodic placement phase for exact full-Divider variants.",
    )
    parser.add_argument(
        "--exact-divzero",
        choices=("automatic", "on", "off"),
        default="automatic",
        help="Whether the exact A/B includes the divide-by-zero output boundary.",
    )
    parser.add_argument(
        "--exact-chunked-mux-boundary",
        type=int,
        help=(
            "Internal prototype: replace selected uint32 MUX output boundaries "
            "with a genuine bit-chunk boundary at this bit."
        ),
    )
    parser.add_argument(
        "--exact-chunked-mux-terminal",
        action="store_true",
        help="Also split the terminal iteration-0 MUX (one additional slice).",
    )
    parser.add_argument(
        "--automatic-exact-requested-bits",
        action="store_true",
        help=(
            "Internal prototype: materialize automatic raster bit requests "
            "at their exact nearest integer bit boundaries."
        ),
    )
    parser.add_argument(
        "--continue",
        dest="continue_existing",
        action="store_true",
        help="Reuse completed plan/map/sweep records in an existing --out_dir.",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write the full result but return zero when the continuity gate fails.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if _sha256(source) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            f"arithmetic Divider source hash mismatch: {_sha256(source)}"
        )
    device_models_path = REPO_ROOT / "src" / "DEVICE_MODELS.py"
    model_sha_at_launch = _sha256(device_models_path)
    if model_sha_at_launch != EXPECTED_DEVICE_MODELS_SHA256:
        raise RuntimeError(
            "DEVICE_MODELS.py is not the fixed V4 input expected by this "
            f"benchmark: {model_sha_at_launch}"
        )

    out_dir = args.out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()) and not args.continue_existing:
        raise ValueError(
            f"output directory must be empty unless --continue is used: {out_dir}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "path_delay_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    original = source.read_text()

    plans = []
    for goal in sorted(set(float(value) for value in args.goals)):
        tag = _goal_tag(goal)
        source_path = out_dir / "sources" / tag / "solution.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        derived = _derive_source(original, goal)
        if source_path.is_file():
            if source_path.read_text() != derived:
                raise RuntimeError(f"continued source differs: {source_path}")
        else:
            source_path.write_text(derived)
        run_dir = out_dir / "plans" / tag
        record = _read_plan_record(run_dir)
        if record is None:
            if run_dir.exists():
                raise RuntimeError(f"incomplete plan directory: {run_dir}")
            record = _build_plan(
                source_path,
                source,
                goal,
                run_dir,
                cache_dir,
                exact_requested_bits=args.automatic_exact_requested_bits,
            )
        plans.append(record)

    mapped = []
    representatives = {}
    for plan in sorted(plans, key=lambda value: value["goal_mhz"]):
        if not (
            plan.get("placement_fingerprint")
            and plan.get("stages") is not None
            and MIN_USEFUL_STAGES <= plan["stages"] <= MAX_USEFUL_STAGES
        ):
            continue
        representatives.setdefault(plan["placement_fingerprint"], plan)

    exact_plans = []
    requested_exact = sorted(
        set(args.exact_boundaries) | set(args.map_exact_boundaries)
    )
    if requested_exact:
        reference = next(
            (plan for plan in plans if plan.get("stages") == 49), None
        )
        if reference is None:
            raise RuntimeError("exact-boundary scan found no 49-stage reference plan")
        reference_run_dir = out_dir / "plans" / _goal_tag(reference["goal_mhz"])
        reference_source = Path(reference["source"]["path"])
        for boundary in requested_exact:
            prefix = "" if args.exact_phase == "automatic" else f"{args.exact_phase}_"
            suffix = "" if args.exact_divzero == "automatic" else f"_dz_{args.exact_divzero}"
            if args.exact_chunked_mux_boundary is not None:
                suffix += f"_mux_b{args.exact_chunked_mux_boundary:02d}"
                if args.exact_chunked_mux_terminal:
                    suffix += "_terminal_v2"
            tag = f"{prefix}b{boundary:02d}{suffix}"
            experiment_root = out_dir / "exact_boundaries" / tag
            config_path = experiment_root / "placement.json"
            config = _exact_boundary_config(
                reference_run_dir,
                boundary,
                phase=args.exact_phase,
                divide_zero=args.exact_divzero,
                chunked_mux_boundary=args.exact_chunked_mux_boundary,
                chunked_mux_terminal=args.exact_chunked_mux_terminal,
            )
            if config_path.is_file():
                if json.loads(config_path.read_text()) != config:
                    raise RuntimeError(f"continued exact config differs: {config_path}")
            else:
                _write_json(config_path, config)
            run_dir = experiment_root / "plan"
            record = _read_plan_record(run_dir)
            if record is None:
                if run_dir.exists():
                    raise RuntimeError(f"incomplete exact plan directory: {run_dir}")
                record = _build_plan(
                    reference_source,
                    source,
                    reference["goal_mhz"],
                    run_dir,
                    cache_dir,
                    placement_config=config_path,
                    chunked_mux=args.exact_chunked_mux_boundary is not None,
                )
            exact_plans.append({"boundary": boundary, **record})

    if not args.plans_only and not args.exact_isolated_only:
        for fingerprint, plan in representatives.items():
            if args.map_stages and plan["stages"] not in set(args.map_stages):
                continue
            tag = f"s{plan['stages']}_{fingerprint[:12]}"
            map_dir = out_dir / "maps" / tag
            map_record_path = out_dir / "maps" / f"{tag}.json"
            if map_record_path.is_file():
                mapping = json.loads(map_record_path.read_text())
            else:
                if map_dir.exists():
                    raise RuntimeError(f"incomplete mapping directory: {map_dir}")
                plan_dir = out_dir / "plans" / _goal_tag(plan["goal_mhz"])
                mapping = _map_frozen(plan_dir, map_dir, cache_dir)
                _write_json(map_record_path, mapping)
            mapped.append({**plan, "mapping": mapping})

    exact_mapped = []
    exact_isolated = []
    if not args.plans_only:
        map_exact = set(args.map_exact_boundaries)
        for plan in exact_plans:
            experiment_root = (
                out_dir
                / "exact_boundaries"
                / (
                    ("" if args.exact_phase == "automatic" else f"{args.exact_phase}_")
                    + f"b{plan['boundary']:02d}"
                    + ("" if args.exact_divzero == "automatic" else f"_dz_{args.exact_divzero}")
                    + (
                        ""
                        if args.exact_chunked_mux_boundary is None
                        else f"_mux_b{args.exact_chunked_mux_boundary:02d}"
                    )
                    + ("_terminal_v2" if args.exact_chunked_mux_terminal else "")
                )
            )
            isolated_record_path = experiment_root / "isolated_v2.json"
            if isolated_record_path.is_file():
                isolated = json.loads(isolated_record_path.read_text())
            else:
                isolated = _map_exact_leaf(
                    experiment_root / "plan",
                    plan["boundary"],
                    experiment_root / "isolated_v2",
                )
                _write_json(isolated_record_path, isolated)
            exact_isolated.append(isolated)
            if args.exact_isolated_only or plan["boundary"] not in map_exact:
                continue
            map_dir = experiment_root / "map"
            map_record_path = experiment_root / "map.json"
            if map_record_path.is_file():
                mapping = json.loads(map_record_path.read_text())
            else:
                if map_dir.exists():
                    raise RuntimeError(f"incomplete exact mapping directory: {map_dir}")
                mapping = _map_frozen(
                    experiment_root / "plan", map_dir, cache_dir
                )
                _write_json(map_record_path, mapping)
            exact_mapped.append({**plan, "mapping": mapping})

    sweeps = []
    if not args.plans_only and not args.exact_isolated_only:
        for goal in sorted(set(float(value) for value in args.normal_sweep_goals)):
            tag = _goal_tag(goal)
            source_path = out_dir / "sources" / tag / "solution.py"
            if not source_path.is_file():
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(_derive_source(original, goal))
            run_dir = out_dir / "sweeps" / tag
            record_path = run_dir / "continuity_sweep.json"
            if record_path.is_file():
                record = json.loads(record_path.read_text())
            else:
                if run_dir.exists():
                    raise RuntimeError(f"incomplete sweep directory: {run_dir}")
                record = _build_normal_sweep(
                    source_path, source, goal, run_dir, cache_dir
                )
            sweeps.append(record)

    model_sha_after = _sha256(device_models_path)
    acceptance = None
    if not args.plans_only and not args.exact_isolated_only:
        acceptance = _acceptance(
            plans, mapped, sweeps, model_sha_after == model_sha_at_launch
        )
    result = {
        "schema_version": 1,
        "created_utc": _datetime.datetime.now(
            _datetime.timezone.utc
        ).isoformat(),
        "source": _source_record(source),
        "repository": _qor._repo_state(),
        "model": {
            **_qor._model_record(RECIPE),
            "device_models_sha256_at_launch": model_sha_at_launch,
            "device_models_sha256_after": model_sha_after,
            "unchanged": model_sha_after == model_sha_at_launch,
        },
        "plans": plans,
        "unique_placement_count": len(representatives),
        "mapped": mapped,
        "exact_boundary_plans": exact_plans,
        "exact_boundary_isolated": exact_isolated,
        "exact_boundary_mapped": exact_mapped,
        "normal_sweeps": sweeps,
        "acceptance": acceptance,
    }
    _write_json(out_dir / "continuity_results.json", result)
    print(f"Continuity evidence: {out_dir / 'continuity_results.json'}")
    if args.plans_only or args.exact_isolated_only:
        return 0
    status = "PASS" if acceptance["passed"] else "FAIL"
    print(f"[{status}] arithmetic Divider continuity")
    return 0 if acceptance["passed"] or args.diagnostic else 1


if __name__ == "__main__":
    sys.exit(main())
