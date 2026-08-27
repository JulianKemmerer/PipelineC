#!/usr/bin/env python3
"""Opt-in sky130 QoR and exact-final-VHDL verification for Divider.

This is deliberately outside ``run_all.py``: one full gate build can take
about an hour.  The compiler-facing controls are fixed, internal environment
variables; the harness does not expose arbitrary synthesis flags or a public
pipeline slice cap.
"""

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[3]
PYPELINEC = REPO_ROOT / "src" / "pypelinec"
FIXTURE_DIR = Path(__file__).resolve().parent / "qor" / "divider"
COCOTB_MODULE_DIR = FIXTURE_DIR
GOAL_MHZ = 143.0
SLICE_LIMITS = {"gate": 48, "arithmetic": 63}
RECIPES = (
    "current",
    "synth_flatten",
    "synth_flatten_noabc",
    "early_flatten_opt",
    "early_flatten_noabc",
)
DEFAULT_RECIPE = "early_flatten_noabc"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_file_record(path):
    """Hash one repository source file for launch/post-run comparison."""
    path = Path(path).resolve()
    try:
        display = str(path.relative_to(REPO_ROOT))
    except ValueError:
        display = str(path)
    return {
        "path": display,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _run_capture(argv, cwd=REPO_ROOT, env=None):
    return subprocess.run(
        [str(x) for x in argv],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _run_logged(argv, log_path, cwd=REPO_ROOT, env=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(x) for x in argv],
            cwd=cwd,
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


def _compiler_module(name):
    """Import compiler internals without depending on the caller's cwd/PYTHONPATH."""
    src_dir = str(REPO_ROOT / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    return __import__(name)


def _cad_tool_paths():
    # OPEN_TOOLS participates in the legacy compiler import cycle.  Enter it
    # through C_TO_LOGIC, matching DEVICE_MODELS.IS_INSTALLED, so attributes
    # used by VERILATOR/OPEN_TOOLS exist before those modules inspect them.
    _compiler_module("C_TO_LOGIC")
    open_tools = _compiler_module("OPEN_TOOLS")
    return {
        "yosys": Path(open_tools.YOSYS_BIN_PATH) / "yosys",
        "ghdl": Path(open_tools.GHDL_BIN_PATH) / "ghdl",
        "ghdl_prefix": Path(open_tools.GHDL_PREFIX),
    }


def _pinned_tool_env(env):
    """Use the same pinned CAD-suite binaries for the exact-VHDL simulation."""
    value = dict(env)
    paths = _cad_tool_paths()
    original_path = value.get("PATH", "")
    # The CAD suite also ships a cocotb development build whose VPI may need
    # a newer host glibc. Keep the cocotb-config selected by the caller's
    # original PATH ahead of the pinned CAD bin, while selecting GHDL with an
    # explicit GHDL_BIN_DIR below.
    host_cocotb = shutil.which("cocotb-config", path=original_path)
    path_parts = []
    if host_cocotb:
        path_parts.append(str(Path(host_cocotb).parent))
        value["COCOTB_CONFIG"] = host_cocotb
    path_parts.append(str(paths["ghdl"].parent))
    path_parts.append(original_path)
    value["PATH"] = os.pathsep.join(path_parts)
    value["GHDL_BIN_DIR"] = str(paths["ghdl"].parent)
    value["GHDL_PREFIX"] = str(paths["ghdl_prefix"])
    return value


def _simulation_toolchain(env, fallback=False):
    original_path = env.get("PATH", "")
    cocotb = shutil.which("cocotb-config", path=original_path)
    if fallback:
        ghdl = shutil.which("ghdl", path=original_path)
        reason = "host GHDL fallback after pinned GHDL rejected host-compatible cocotb VPI"
    else:
        ghdl = str(_cad_tool_paths()["ghdl"])
        reason = "pinned OSS CAD Suite GHDL with host-compatible cocotb VPI"
    return {
        "selection_reason": reason,
        "ghdl": _tool_record("ghdl", [ghdl, "--version"]) if ghdl else None,
        "cocotb": (
            _tool_record("cocotb", [cocotb, "--version"]) if cocotb else None
        ),
    }


def _looks_like_vpi_abi_failure(text):
    upper = text.upper()
    return (
        "GLIBC_" in upper
        and ("NOT FOUND" in upper or "VERSION" in upper)
        and ("VPI" in upper or "COCOTB" in upper)
    )


def _placement_request(extra_ids=(), hand_equivalent=False):
    assert len(extra_ids) <= 16
    if hand_equivalent:
        # The source's divide-by-zero select precedes the repeated division
        # steps. Register it, then the first 31 step outputs; the 32nd step is
        # the final comb region rather than an empty trailing stage.
        selectors = [
            {
                "kind": "instance_output",
                "func_name": "MUX_uint32_t",
                "ancestor_func": "radix2_div_gates",
                "fixed": True,
            },
            {
                "kind": "instance_output",
                "func_name": "step_gates",
                "limit": 31,
                "fixed": True,
            },
        ]
    else:
        selectors = [
            {
                "kind": "instance_output",
                "func_name": "step_gates",
                "all": True,
                "fixed": True,
            }
        ]
    return {
        "version": 1,
        "mode": "replace",
        "selectors": selectors,
        "placements": [
            {"candidate_id": candidate_id, "fixed": True}
            for candidate_id in extra_ids
        ],
    }


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _parse_depth(build_text):
    patterns = [
        r"\[sweep\]\s+solution:\s+(\d+)\s+slice\(s\) total",
        r"\[sweep\]\s+solution:\s+(\d+)\s+pipeline register stage\(s\) total",
        r"\[sweep\]\s+solution:.*?\b(\d+)\s+slice\(s\) built",
        r"\[sweep\]\s+solution:.*?\b(\d+)\s+pipeline register stage\(s\) built",
    ]
    matches = []
    for pattern in patterns:
        matches.extend(int(x) for x in re.findall(pattern, build_text))
        if matches:
            return matches[-1]
    return None


def _parse_pipeline_stages(build_text):
    matches = [
        int(value)
        for value in re.findall(r"\((\d+)\s+pipeline stages\)", build_text)
    ]
    return matches[-1] if matches else None


def _reported_pipeline_stages(build_text, slices):
    """Return reported stages, deriving N + 1 for log-less imports."""
    value = _parse_pipeline_stages(build_text)
    if value is None and slices is not None:
        value = slices + 1
    return value


def _load_sweep_record(run_dir, slices):
    paths = sorted(run_dir.glob("**/sweep_history.json"))
    if not paths:
        return None, None
    path = paths[-1]
    data = json.loads(path.read_text())
    records = [record for values in data.values() for record in values]
    if not records:
        return path, None
    if slices is not None:
        matching = [
            r
            for r in records
            if r.get("main_latency") == slices
            or r.get("pipeline_stages") == slices + 1
        ]
        if matching:
            return path, matching[-1]
    met = [r for r in records if r.get("action") == "met"]
    return path, (met[-1] if met else records[-1])


def _parse_timing_log(path):
    text = path.read_text(errors="replace")
    fields = {}
    patterns = {
        "worst_period_ns": r"Worst period \(ns\):\s*([0-9.eE+-]+)",
        "fmax_mhz": r"Fmax \(MHz\):\s*([0-9.eE+-]+)",
        "cells": r"N cells:\s*(\d+)",
        "max_capacitance_violations": r"N max_capacitance violations:\s*(\d+)",
        "launch_clock_to_q_ns": r"Launch clock-to-Q \(ns\):\s*([0-9.eE+-]+)",
        "combinational_delay_ns": r"Combinational delay \(ns\):\s*([0-9.eE+-]+)",
        "setup_ns": r"Setup \(ns\):\s*([0-9.eE+-]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            fields[key] = int(match.group(1)) if key in {
                "cells",
                "max_capacitance_violations",
            } else float(match.group(1))
    return fields


def _select_final_timing(run_dir, achieved_mhz):
    structured = sorted(run_dir.glob("top/*_timing.json"))
    candidates = []
    for path in structured:
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        fmax = value.get("fmax_mhz")
        if fmax is None and value.get("worst_period_ns"):
            fmax = 1000.0 / value["worst_period_ns"]
        candidates.append((path, value, fmax))
    for path in sorted(run_dir.glob("top/device_models*.log")):
        value = _parse_timing_log(path)
        candidates.append((path, value, value.get("fmax_mhz")))
    if not candidates:
        return None, {}
    if achieved_mhz is None:
        path, value, _ = candidates[-1]
        return path, value
    path, value, _ = min(
        candidates,
        key=lambda item: abs(item[2] - achieved_mhz)
        if item[2] is not None
        else float("inf"),
    )
    return path, value


def _parse_estimated_ffs(run_dir, timing_path):
    register_logs = sorted(run_dir.glob("top/*_registers.log"))
    if not register_logs:
        return None, None
    if timing_path is not None:
        timing_tokens = set(re.findall(r"[0-9a-f]{8}", timing_path.name))
        matching = [
            path
            for path in register_logs
            if timing_tokens & set(re.findall(r"[0-9a-f]{8}", path.name))
        ]
        if matching:
            register_logs = matching
    path = register_logs[-1]
    match = re.search(r"^(\d+) FFs Function: solution", path.read_text(errors="replace"), re.M)
    return path, int(match.group(1)) if match else None


def _select_mapped_json(run_dir, timing_path):
    candidates = sorted(run_dir.glob("top/*_liberty.json"))
    if not candidates:
        return None
    if timing_path is not None:
        timing_tokens = set(re.findall(r"[0-9a-f]{8}", timing_path.name))
        matching = [
            path
            for path in candidates
            if timing_tokens & set(re.findall(r"[0-9a-f]{8}", path.name))
        ]
        if matching:
            return matching[-1]
        if timing_tokens:
            # A restored best/met timing report must never be paired with the
            # sole JSON left by a later failed trim iteration.
            return None
    return candidates[-1]


def _mapped_netlist_metrics(path):
    if path is None:
        return {}
    data = json.loads(path.read_text())
    modules = data.get("modules", {})
    top_name = None
    for name, module in modules.items():
        top_attr = module.get("attributes", {}).get("top")
        if str(top_attr) in {"1", "00000000000000000000000000000001"}:
            top_name = name
            break
    if top_name is None and len(modules) == 1:
        top_name = next(iter(modules))
    if top_name is None:
        top_name = next((name for name in modules if name.lower().startswith("top")), None)
    if top_name is None:
        return {"mapped_json_error": "could not identify top module"}
    cells = modules[top_name].get("cells", {})
    histogram = {}
    for cell in cells.values():
        cell_type = cell.get("type", "<unknown>")
        histogram[cell_type] = histogram.get(cell_type, 0) + 1
    liberty_models = json.loads(
        (REPO_ROOT / "src" / "liberty_data" / "sky130_fd_sc_hvl__tt_025C_3v30.json").read_text()
    )["cells"]
    sequential = sum(
        count
        for cell_type, count in histogram.items()
        if liberty_models.get(cell_type, {}).get("is_sequential", False)
    )
    device_models = _compiler_module("DEVICE_MODELS")
    area = device_models.MEASURE_NETLIST_AREA(str(path), top=top_name)
    return {
        "mapped_top": top_name,
        "mapped_cells": len(cells),
        "mapped_dffs": sequential,
        "mapped_cell_histogram": dict(sorted(histogram.items())),
        "mapped_total_area": area["total_cell_area"],
        "mapped_combinational_area": area["combinational_cell_area"],
        "mapped_sequential_area": area["sequential_cell_area"],
        "mapped_area_unit": area["area_unit"],
    }


def _placement_trace_summary(run_dir):
    paths = sorted(run_dir.glob("top/placement_trace.json"))
    if not paths:
        return None, {}
    path = paths[-1]
    data = json.loads(path.read_text())
    mains = data.get("mains", {})
    if isinstance(mains, dict) and mains:
        candidate_entries = []
        selected_entries = []
        iteration_count = 0
        for main in mains.values():
            candidate_entries.extend(main.get("candidates", []))
            selected_entries.extend(main.get("final_selected", []))
            iteration_count += len(main.get("iterations", []))
    else:
        candidate_entries = data.get("placements", data.get("candidates", []))
        if not isinstance(candidate_entries, list):
            candidate_entries = []
        selected_entries = [
            e for e in candidate_entries if e.get("selected") or e.get("planned")
        ]
        iteration_count = len(data.get("iterations", []))
    kinds = {}
    for entry in candidate_entries:
        kind = entry.get("kind", "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
    realized = [e for e in selected_entries if e.get("realized")]
    return path, {
        "schema_version": data.get("schema_version"),
        "planner": data.get("planner"),
        "forced_mode": data.get("internal_forced_mode"),
        "mains": len(mains) if isinstance(mains, dict) else None,
        "iterations": iteration_count,
        "candidates": len(candidate_entries),
        "selected": len(selected_entries),
        "realized": len(realized),
        "fixed": sum(bool(e.get("fixed")) for e in selected_entries),
        "registered_bits": sum(int(e.get("registered_bits") or 0) for e in realized),
        "kinds": dict(sorted(kinds.items())),
    }


def _final_vhdl_records(run_dir):
    path = run_dir / "vhdl_files.txt"
    if not path.is_file():
        return None, []
    records = []
    for raw in shlex.split(path.read_text()):
        vhdl = Path(raw)
        if not vhdl.is_file():
            records.append({"path": raw, "missing": True})
            continue
        try:
            display = str(vhdl.resolve().relative_to(run_dir.resolve()))
        except ValueError:
            display = str(vhdl.resolve())
        records.append(
            {"path": display, "bytes": vhdl.stat().st_size, "sha256": _sha256(vhdl)}
        )
    return path, records


def _discover_frozen_vhdl(source):
    """Resolve a final run tree/file list or one exact generated ``*_syn.sh``."""
    source = source.resolve()
    if source.is_dir():
        list_path = source / "vhdl_files.txt"
        if not list_path.is_file():
            raise ValueError(f"frozen VHDL run has no vhdl_files.txt: {source}")
        source_root = source
        paths = [Path(x).resolve() for x in shlex.split(list_path.read_text())]
        top = "top"
    elif source.name == "vhdl_files.txt":
        list_path = source
        source_root = source.parent
        paths = [Path(x).resolve() for x in shlex.split(source.read_text())]
        top = "top"
    elif source.name.endswith("_syn.sh"):
        list_path = None
        source_root = source.parent.parent if source.parent.name == "top" else source.parent
        match = re.search(
            r"\bghdl\s+--std=08\s+(.*?)\s+-e\s+([A-Za-z][A-Za-z0-9_]*)\s*;",
            source.read_text(errors="replace"),
            re.S,
        )
        if not match:
            raise ValueError(f"could not discover GHDL file list/top from {source}")
        paths = [Path(x).resolve() for x in shlex.split(match.group(1))]
        top = match.group(2)
    else:
        raise ValueError(
            "--frozen-vhdl-source must name a run directory, vhdl_files.txt, "
            "or generated *_syn.sh"
        )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"frozen VHDL dependency is missing: {missing[0]}")
    if any(any(ch.isspace() for ch in str(path)) for path in paths):
        raise ValueError("frozen synthesis backend does not support whitespace in VHDL paths")
    return {
        "source": source,
        "source_root": source_root,
        "file_list": list_path,
        "vhdl_paths": paths,
        "top": top,
    }


def _vhdl_path_records(paths, base):
    records = []
    for path in paths:
        try:
            display = str(path.relative_to(base))
        except ValueError:
            display = str(path)
        records.append(
            {"path": display, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        )
    return records


def _vhdl_source_snapshot(paths, base):
    records = _vhdl_path_records(paths, base)
    return {
        "vhdl_files": records,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True).encode()
        ).hexdigest(),
    }


def _assert_vhdl_source_unchanged(snapshot, paths, base, phase):
    current = _vhdl_source_snapshot(paths, base)
    if current != snapshot:
        raise RuntimeError(
            f"frozen VHDL changed {phase}; refusing mixed-input QoR evidence"
        )


def _copy_vhdl_source_snapshot(paths, source_root, evidence_dir):
    """Copy ordered frozen inputs before either simulation or synthesis."""

    source_root = source_root.resolve()
    snapshot_root = evidence_dir / "frozen_vhdl_snapshot"
    snapshot_paths = []
    for index, source in enumerate(paths):
        source = source.resolve()
        try:
            relative = source.relative_to(source_root)
        except ValueError:
            relative = Path("_external") / f"{index:04d}_{source.name}"
        target = snapshot_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        snapshot_paths.append(target.resolve())

    original = _vhdl_source_snapshot(paths, source_root)
    copied = _vhdl_source_snapshot(snapshot_paths, snapshot_root)
    original_content = [
        (record["bytes"], record["sha256"])
        for record in original["vhdl_files"]
    ]
    copied_content = [
        (record["bytes"], record["sha256"])
        for record in copied["vhdl_files"]
    ]
    if copied_content != original_content:
        raise RuntimeError("frozen VHDL snapshot copy did not preserve bytes")
    return {
        "original": original,
        "snapshot": copied,
        "snapshot_root": snapshot_root.resolve(),
        "snapshot_paths": snapshot_paths,
    }


def _frozen_source_slices(frozen, fallback=None):
    manifest_path = frozen["source_root"] / "manifest.json"
    if manifest_path.is_file():
        value = json.loads(manifest_path.read_text()).get("metrics", {}).get("slices")
        if value is not None:
            return int(value)
    build_log = frozen["source_root"] / "build.log"
    if build_log.is_file():
        value = _parse_depth(build_log.read_text(errors="replace"))
        if value is not None:
            return value
    return fallback


def _frozen_generator_provenance(frozen):
    """Import the provenance recorded when the frozen VHDL was generated.

    Mapping a byte snapshot with today's harness does not mean today's
    compiler generated those bytes. Keep the two roles explicit and preserve
    the source manifest itself by hash.
    """

    manifest_path = frozen["source_root"] / "manifest.json"
    if not manifest_path.is_file():
        launch_path = frozen["source_root"] / "launch_context.json"
        build_log = frozen["source_root"] / "build.log"
        launch = (
            json.loads(launch_path.read_text()) if launch_path.is_file() else {}
        )
        build_text = (
            build_log.read_text(errors="replace") if build_log.is_file() else ""
        )
        trace_path, placements = _placement_trace_summary(frozen["source_root"])
        return {
            "available": bool(launch),
            "source_manifest": None,
            "launch_context": {
                "path": str(launch_path) if launch_path.is_file() else None,
                "sha256": _sha256(launch_path) if launch_path.is_file() else None,
            },
            "repository": launch.get("repository"),
            "compiler_sources": launch.get("compiler_sources"),
            "source": None,
            "model": launch.get("model"),
            "metrics": {
                "slices": _parse_depth(build_text),
                "stages": _parse_pipeline_stages(build_text),
            },
            "placements": placements,
            "placement_trace": str(trace_path) if trace_path else None,
            "evidence_note": launch.get("evidence_note"),
            "role": "authoritative launch-time provenance for VHDL generation",
            "note": "source run had not yet written its final manifest",
        }
    manifest = json.loads(manifest_path.read_text())
    discovered_vhdl = _vhdl_path_records(
        frozen["vhdl_paths"], frozen["source_root"]
    )
    manifest_vhdl = manifest.get("final_vhdl")
    if manifest_vhdl != discovered_vhdl:
        raise RuntimeError(
            "frozen source manifest final_vhdl does not match the discovered "
            "ordered VHDL bytes; generator provenance is not authoritative"
        )
    return {
        "available": True,
        "source_manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256(manifest_path),
        },
        "repository": manifest.get("repository"),
        "compiler_sources": manifest.get("compiler_sources"),
        "source": manifest.get("source"),
        "model": manifest.get("model"),
        "metrics": manifest.get("metrics"),
        "placements": manifest.get("placements"),
        "evidence_note": manifest.get("evidence_note"),
        "role": "authoritative provenance for VHDL generation",
        "final_vhdl_validation": {
            "matched": True,
            "ordered_file_count": len(discovered_vhdl),
            "aggregate_sha256": hashlib.sha256(
                json.dumps(discovered_vhdl, sort_keys=True).encode()
            ).hexdigest(),
        },
    }


def _discover_stream_types(run_dir):
    package = run_dir / "c_structs_pkg.pkg.vhd"
    text = package.read_text()
    record_bodies = {
        name: body
        for name, body in re.findall(
            r"type\s+(\w+)\s+is record(.*?)end record;", text, re.S | re.I
        )
    }
    input_stream = output_stream = None
    for name, body in record_bodies.items():
        if not name.startswith("stream_t_"):
            continue
        data_match = re.search(r"\bdata\s*:\s*(\w+)\s*;", body, re.I)
        if not data_match:
            continue
        payload = record_bodies.get(data_match.group(1), "")
        if re.search(r"\bdividend\s*:", payload) and re.search(r"\bdivisor\s*:", payload):
            input_stream = name
        if re.search(r"\bv1\s*:", payload) and re.search(r"\bv2\s*:", payload):
            output_stream = name
    if input_stream is None or output_stream is None:
        raise RuntimeError("could not discover Divider stream record types in c_structs_pkg.pkg.vhd")
    return input_stream, output_stream


def _write_sim_files(run_dir, artifact_dir=None, top_entity="top"):
    sim_dir = (artifact_dir or run_dir) / "exact_final_vhdl_sim"
    # GHDL work libraries and elaborated executables are not portable across
    # GHDL/cocotb builds. This directory is wholly benchmark-generated, so
    # recreate it for every verification rather than letting stale objects
    # make a new exact-VHDL run appear to fail.
    if sim_dir.exists():
        shutil.rmtree(sim_dir)
    sim_dir.mkdir(parents=True, exist_ok=True)
    input_stream, output_stream = _discover_stream_types(run_dir)
    wrapper = sim_dir / "divider_qor_tb.vhd"
    wrapper.write_text(
        f"""library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.c_structs_pkg.all;

entity divider_qor_tb is
port(
  clk              : in  std_logic;
  input_dividend   : in  unsigned(31 downto 0);
  input_divisor    : in  unsigned(31 downto 0);
  input_valid      : in  std_logic;
  input_ready      : out std_logic;
  output_quotient  : out unsigned(31 downto 0);
  output_remainder : out unsigned(31 downto 0);
  output_valid     : out std_logic
);
end divider_qor_tb;

architecture arch of divider_qor_tb is
  signal clk_u       : unsigned(0 downto 0);
  signal ready_u     : unsigned(0 downto 0);
  signal input_s     : {input_stream};
  signal output_s    : {output_stream};
begin
  clk_u(0) <= clk;
  input_s.data.dividend <= input_dividend;
  input_s.data.divisor <= input_divisor;
  input_s.valid(0) <= input_valid;
  input_ready <= ready_u(0);
  output_quotient <= output_s.data.v1;
  output_remainder <= output_s.data.v2;
  output_valid <= output_s.valid(0);

  dut : entity work.{top_entity} port map(
    clk => clk_u,
    input => input_s,
    input_ready => ready_u,
    output => output_s
  );
end arch;
"""
    )
    makefile = sim_dir / "Makefile"
    makefile.write_text(
        """SIM ?= ghdl
TOPLEVEL_LANG ?= vhdl
EXTRA_ARGS += --std=08 -Wno-hide
# Uninitialized pipeline records legitimately contain metavalue bits while the
# fixed-latency pipe fills.  Cocotb checks every externally valid result, so
# suppress numeric_std's per-bit warning flood for those invalid cycles.
SIM_ARGS += --ieee-asserts=disable
# GHDL "@file" response file, not $(shell cat ...): a large VHDL file list
# inlined into cocotb's single-line "analyse" recipe can exceed Linux's
# MAX_ARG_STRLEN (131072 bytes per argv/envp string).
VHDL_SOURCES += @$(DIVIDER_QOR_VHDL_FILES)
.PHONY: @$(DIVIDER_QOR_VHDL_FILES)
CUSTOM_COMPILE_DEPS += $(DIVIDER_QOR_VHDL_FILES)
VHDL_SOURCES += $(DIVIDER_QOR_WRAPPER)
TOPLEVEL = divider_qor_tb
MODULE = divider_qor_cocotb
COCOTB_CONFIG ?= cocotb-config
include $(shell $(COCOTB_CONFIG) --makefiles)/Makefile.sim
"""
    )
    return sim_dir, wrapper, makefile


def _merge_functional_result(process_value, reported):
    value = dict(process_value)
    value.update(
        {
            key: item
            for key, item in reported.items()
            if key
            not in {
                "passed",
                "returncode",
                "runtime_seconds",
                "toolchain",
                "fallback_used",
            }
        }
    )
    value["test_reported_passed"] = bool(reported.get("passed"))
    value["passed"] = (
        value.get("returncode") == 0 and value["test_reported_passed"]
    )
    return value


def _run_functional_sim(
    run_dir, slices, env, artifact_dir=None, vhdl_paths=None, top_entity="top"
):
    if slices is None:
        raise RuntimeError("cannot simulate without a reported final slice count")
    if vhdl_paths is None:
        vhdl_files = run_dir / "vhdl_files.txt"
        if not vhdl_files.is_file():
            raise RuntimeError(f"missing final VHDL list: {vhdl_files}")
    else:
        sim_parent = artifact_dir or run_dir
        vhdl_files = sim_parent / "frozen_vhdl_files.txt"
        vhdl_files.parent.mkdir(parents=True, exist_ok=True)
        vhdl_files.write_text(" ".join(str(path) for path in vhdl_paths) + "\n")
    sim_dir, wrapper, _makefile = _write_sim_files(
        run_dir, artifact_dir, top_entity=top_entity
    )
    functional_result = sim_dir / "functional_results.json"
    sim_env = _pinned_tool_env(env)
    toolchain = _simulation_toolchain(env)
    sim_env.update(
        {
            "DIVIDER_QOR_LATENCY": str(slices),
            "DIVIDER_QOR_VHDL_FILES": str(vhdl_files.resolve()),
            "DIVIDER_QOR_WRAPPER": str(wrapper.resolve()),
            "DIVIDER_QOR_FUNCTIONAL_RESULT": str(functional_result.resolve()),
            "PYTHONPATH": str(COCOTB_MODULE_DIR)
            + os.pathsep
            + sim_env.get("PYTHONPATH", ""),
            # The benchmark does not use third-party pytest plugins.  Avoid a
            # host plugin with an incompatible pytest/anyio version changing
            # cocotb's simulator process or adding unrelated warnings.
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    returncode, duration = _run_logged(
        ["make"], sim_dir / "sim.log", cwd=sim_dir, env=sim_env
    )
    fallback_used = False
    if returncode != 0 and _looks_like_vpi_abi_failure(
        (sim_dir / "sim.log").read_text(errors="replace")
    ):
        host_ghdl = shutil.which("ghdl", path=env.get("PATH", ""))
        host_cocotb = shutil.which("cocotb-config", path=env.get("PATH", ""))
        if host_ghdl and host_cocotb and Path(host_ghdl) != _cad_tool_paths()["ghdl"]:
            fallback_env = dict(env)
            fallback_env["COCOTB_CONFIG"] = host_cocotb
            fallback_env["GHDL_BIN_DIR"] = str(Path(host_ghdl).parent)
            fallback_env.pop("GHDL_PREFIX", None)
            fallback_rc, fallback_seconds = _run_logged(
                [
                    "make",
                    "SIM_BUILD=sim_build_fallback",
                    "COCOTB_RESULTS_FILE=results_fallback.xml",
                ],
                sim_dir / "sim_fallback.log",
                cwd=sim_dir,
                env=fallback_env,
            )
            duration += fallback_seconds
            returncode = fallback_rc
            fallback_used = True
            toolchain["fallback"] = _simulation_toolchain(env, fallback=True)
    value = {
        "passed": False,
        "returncode": returncode,
        "runtime_seconds": duration,
        "toolchain": toolchain,
        "fallback_used": fallback_used,
    }
    if functional_result.is_file():
        reported = json.loads(functional_result.read_text())
        # A test can write its result before the simulator/make process later
        # fails. Preserve that distinction; process failure can never be
        # overwritten into a functional PASS by the JSON payload.
        value = _merge_functional_result(value, reported)
    _write_json(functional_result, value)
    return value


def _tool_record(name, argv, **metadata):
    proc = _run_capture(argv)
    requested = str(argv[0])
    path = requested if Path(requested).is_file() else shutil.which(requested)
    record = {
        "name": name,
        "command": [str(x) for x in argv],
        "path": path,
        "sha256": _sha256(path) if path and Path(path).is_file() else None,
        "version": proc.stdout.strip(),
        "returncode": proc.returncode,
    }
    record.update(metadata)
    return record


def _tool_records():
    paths = _cad_tool_paths()
    return [
        _tool_record("yosys", [paths["yosys"], "--version"]),
        _tool_record(
            "ghdl",
            [paths["ghdl"], "--version"],
            ghdl_prefix=str(paths["ghdl_prefix"]),
        ),
        _tool_record("cocotb", ["cocotb-config", "--version"]),
    ]


def _artifact_records(run_dir, excluded_names=("manifest.json", "recipe_evidence.json")):
    records = []
    wanted = {".vhd", ".json", ".log", ".txt", ".xml"}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        if path.parent == run_dir and path.name in excluded_names:
            continue
        if path.suffix not in wanted and path.name != "Makefile":
            continue
        records.append(
            {
                "path": str(path.relative_to(run_dir)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def _is_generated_untracked_path(path):
    path = Path(path)
    return (
        "__pycache__" in path.parts
        or path.suffix in (".pyc", ".pyo")
        or (path.parts and path.parts[0] == "path_delay_cache")
    )


def _repo_state():
    commit = _run_capture(["git", "rev-parse", "HEAD"]).stdout.strip()
    raw_status = _run_capture(["git", "status", "--short"]).stdout.splitlines()
    status = [
        line
        for line in raw_status
        if not (
            line.startswith("?? ")
            and _is_generated_untracked_path(Path(line[3:].rstrip("/")))
        )
    ]
    diff = _run_capture(["git", "diff", "--binary", "--no-ext-diff", "HEAD"]).stdout
    untracked = []
    for line in status:
        if not line.startswith("?? "):
            continue
        path = REPO_ROOT / line[3:]
        paths = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for file_path in paths:
            rel_path = file_path.relative_to(REPO_ROOT)
            if _is_generated_untracked_path(rel_path):
                continue
            untracked.append(
                {
                    "path": str(rel_path),
                    "sha256": _sha256(file_path),
                }
            )
    state_material = diff + "\n" + json.dumps(untracked, sort_keys=True)
    return {
        "commit": commit,
        "dirty_paths": status,
        "dirty_diff_sha256": hashlib.sha256(state_material.encode()).hexdigest(),
        "untracked_files": untracked,
    }


def _compiler_source_records():
    paths = [
        "src/pypelinec",
        "src/C_TO_LOGIC.py",
        "src/SYN.py",
        "src/SWEEP.py",
        "src/RAW_VHDL.py",
        "src/VHDL.py",
        "src/DEVICE_MODELS.py",
    ]
    return [
        {"path": path, "sha256": _sha256(REPO_ROOT / path)}
        for path in paths
        if (REPO_ROOT / path).is_file()
    ]


def _model_record(recipe):
    device_models = _compiler_module("DEVICE_MODELS")
    env_override = os.environ.get("PIPELINEC_SKY130_LIB_PATH")
    if env_override:
        raise RuntimeError(
            "PIPELINEC_SKY130_LIB_PATH is not allowed for acceptance QoR; "
            "the benchmark requires the pinned vendored mapping liberty"
        )
    if device_models.LIBERTY_RAW_LIB_PATH is not None:
        raise RuntimeError(
            "DEVICE_MODELS.LIBERTY_RAW_LIB_PATH is not allowed for acceptance QoR"
        )
    library = device_models.SELECTED_LIBRARY
    corner = device_models.SELECTED_CORNER
    expected_liberty = (
        REPO_ROOT
        / "src"
        / "liberty_data"
        / f"{library}__{corner}.lib"
    ).resolve()
    resolved_liberty = Path(device_models._find_raw_liberty_lib()).resolve()
    if resolved_liberty != expected_liberty:
        raise RuntimeError(
            f"mapping liberty is not the pinned vendored file: {resolved_liberty}"
        )
    condensed_json = expected_liberty.with_suffix(".json")
    if not condensed_json.is_file():
        raise RuntimeError(f"missing condensed STA data: {condensed_json}")

    def file_record(path):
        return {
            "path": str(path.relative_to(REPO_ROOT)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    return {
        "backend": "DEVICE_MODELS",
        "model_version": device_models.MODEL_VERSION,
        "library": library,
        "corner": corner,
        "recipe": recipe,
        "cache_identity": device_models.GET_MODEL_CACHE_IDENTITY(recipe_name=recipe),
        "recipe_cache_suffix": device_models.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX(recipe),
        "mapping_liberty": file_record(expected_liberty),
        "sta_condensed_json": file_record(condensed_json),
        "override_policy": "external raw-liberty overrides rejected",
    }


def _manifest(
    run_dir,
    variant,
    recipe,
    placement,
    build_cmd,
    build_rc,
    build_seconds,
    functional,
    slices_override=None,
    exact_final_evidence=None,
):
    build_log = run_dir / "build.log"
    build_text = build_log.read_text(errors="replace") if build_log.is_file() else ""
    slices = _parse_depth(build_text)
    if slices is None:
        slices = slices_override
    # Existing-build imports may legitimately lack captured stdout. Once the
    # realized serial slice count is known, the combinational-region count is
    # defined by the compiler's public semantics: N slices delimit N + 1
    # stages. Do not leave a known result as ``stages: null`` merely because
    # the original PTY was not redirected into build.log.
    reported_stages = _reported_pipeline_stages(build_text, slices)
    history_path, final_record = _load_sweep_record(run_dir, slices)
    achieved = final_record.get("achieved_mhz") if final_record else None
    timing_path, timing = _select_final_timing(run_dir, achieved)
    exact_evidence_dir = run_dir / "exact_final_remap"
    if exact_final_evidence is not None:
        timing = exact_final_evidence.get("metrics", {})
        mapping = exact_final_evidence.get("mapping", {})
        timing_name = mapping.get("timing_report")
        timing_path = exact_evidence_dir / timing_name if timing_name else None
    if timing.get("fmax_mhz") is not None:
        achieved = timing["fmax_mhz"]
    register_path, estimated_ffs = _parse_estimated_ffs(run_dir, timing_path)
    if exact_final_evidence is not None:
        mapped_name = exact_final_evidence.get("mapping", {}).get("mapped_json")
        mapped_path = exact_evidence_dir / mapped_name if mapped_name else None
    else:
        mapped_path = _select_mapped_json(run_dir, timing_path)
    mapped_metrics = _mapped_netlist_metrics(mapped_path)
    trace_path, trace_summary = _placement_trace_summary(run_dir)
    vhdl_list_path, final_vhdl = _final_vhdl_records(run_dir)
    metrics = {
        "goal_mhz": GOAL_MHZ,
        "estimated_ffs": estimated_ffs,
        **mapped_metrics,
        **timing,
        "fmax_mhz": achieved,
        "slices": slices,
        "stages": reported_stages,
    }
    limit = SLICE_LIMITS[variant]
    checks = {
        "build_passed": build_rc == 0,
        "functional_passed": bool(functional.get("passed")),
        "fmax_strictly_above_143_mhz": achieved is not None and achieved > GOAL_MHZ,
        "slice_limit": slices is not None and slices <= limit,
        "stage_semantics": (
            slices is not None
            and metrics["stages"] == slices + 1
            and functional.get("latency_slices") == slices
            and trace_summary.get("realized") == slices
        ),
        "exact_final_frozen_remap": exact_final_evidence is not None,
        "mapped_json_preserved": (
            exact_final_evidence is not None
            and mapped_path is not None
            and mapped_path.is_file()
        ),
        "zero_unmapped_cells": (
            exact_final_evidence is not None
            and timing.get("n_unmapped_cells") == 0
        ),
        "complete_timing_topology": (
            exact_final_evidence is not None
            and timing.get("incomplete_topo") is False
        ),
        "mapping_identity_verified": (
            exact_final_evidence is not None
            and all(
                exact_final_evidence.get("acceptance", {})
                .get("checks", {})
                .get(name, False)
                for name in (
                    "mapped_json_hash_matches_timing",
                    "mapping_succeeded",
                    "timing_recipe_matches",
                    "timing_model_identity_matches",
                    "timing_vhdl_bytes_match_snapshot",
                )
            )
        ),
    }
    launch_context_path = run_dir / "launch_context.json"
    launch_context = (
        json.loads(launch_context_path.read_text())
        if launch_context_path.is_file()
        else {"repository": _repo_state(), "compiler_sources": _compiler_source_records()}
    )
    checks["fixture_source_unchanged"] = bool(
        launch_context.get("fixture_source_unchanged")
    )
    is_existing_build = bool(
        build_cmd and str(build_cmd[0]) == "<existing-build>"
    )
    checks["compiler_source_provenance"] = (
        launch_context.get("compiler_sources_unchanged") is True
        if not is_existing_build
        else bool(
            launch_context.get("repository", {}).get("snapshot_override")
        )
    )
    source_at_launch = launch_context.get("fixture_source_at_launch", {})
    liberty = REPO_ROOT / "src" / "liberty_data" / "sky130_fd_sc_hvl__tt_025C_3v30.lib"
    manifest = {
        "schema_version": 1,
        "mode": "autopipeline_build",
        "run_id": run_dir.name,
        "created_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "variant": variant,
        "recipe": recipe,
        "placement": placement,
        "acceptance": {
            "slice_limit": limit,
            "strict_fmax_mhz": GOAL_MHZ,
            "checks": checks,
            "passed": all(checks.values()),
        },
        "metrics": metrics,
        "placements": trace_summary,
        "functional": functional,
        "build": {
            "command": [str(x) for x in build_cmd],
            "returncode": build_rc,
            "runtime_seconds": build_seconds,
            "stdout": {
                "path": "build.log" if build_log.is_file() else None,
                "sha256": _sha256(build_log) if build_log.is_file() else None,
                "complete": bool(build_cmd and str(build_cmd[0]) != "<existing-build>"),
                "provenance": (
                    "captured_by_benchmark_harness"
                    if build_cmd and str(build_cmd[0]) != "<existing-build>"
                    else (
                        "preexisting_unverified_log; not asserted to be full stdout"
                        if build_log.is_file()
                        else "not_captured"
                    )
                ),
            },
        },
        "source": {
            "path": source_at_launch.get("path")
            or str((FIXTURE_DIR / f"{variant}.py").relative_to(REPO_ROOT)),
            "bytes": source_at_launch.get("bytes"),
            "sha256": launch_context.get("source_sha256_override")
            or source_at_launch.get("sha256"),
            "snapshot_override": "source_sha256_override" in launch_context,
            "verified_unchanged_through_final_verification": bool(
                launch_context.get("fixture_source_unchanged")
            ),
        },
        "repository": launch_context["repository"],
        "manifest_generator_repository": launch_context.get(
            "manifest_generator_repository"
        ),
        "compiler_sources": launch_context["compiler_sources"],
        "compiler_source_hashes_note": launch_context.get("compiler_source_hashes_note"),
        "evidence_note": launch_context.get("evidence_note"),
        "model": launch_context.get("model") or _model_record(recipe),
        "liberty": {
            "path": str(liberty.relative_to(REPO_ROOT)),
            "bytes": liberty.stat().st_size,
            "sha256": _sha256(liberty),
        },
        "tools": _tool_records(),
        "selected_artifacts": {
            "sweep_history": str(history_path.relative_to(run_dir)) if history_path else None,
            "timing": str(timing_path.relative_to(run_dir)) if timing_path else None,
            "register_estimate": str(register_path.relative_to(run_dir)) if register_path else None,
            "mapped_json": str(mapped_path.relative_to(run_dir)) if mapped_path else None,
            "placement_trace": str(trace_path.relative_to(run_dir)) if trace_path else None,
            "vhdl_file_list": str(vhdl_list_path.relative_to(run_dir)) if vhdl_list_path else None,
        },
        "exact_final_remap": (
            {
                "path": "exact_final_remap/recipe_evidence.json",
                "sha256": _sha256(exact_evidence_dir / "recipe_evidence.json"),
                "acceptance": exact_final_evidence.get("acceptance"),
            }
            if exact_final_evidence is not None
            else None
        ),
        "final_vhdl": final_vhdl,
    }
    _write_json(run_dir / "manifest.json", manifest)
    # Hash after writing the manifest so all evidence except the self-referential
    # manifest hash itself is represented.
    manifest["artifacts"] = _artifact_records(run_dir)
    _write_json(run_dir / "manifest.json", manifest)
    return manifest


def _run_frozen_recipe(args, variant, evidence_dir, frozen_source=None):
    """Map one byte-frozen generated VHDL design with one fixed recipe."""
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise ValueError(
            f"frozen-recipe evidence directory must be empty: {evidence_dir}"
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    mapper_sources_at_launch = _compiler_source_records()
    harness_source_at_launch = _source_file_record(Path(__file__))
    mapper_repository_at_launch = _repo_state()
    device_models = _compiler_module("DEVICE_MODELS")
    model_record = _model_record(args.recipe)
    frozen = _discover_frozen_vhdl(
        args.frozen_vhdl_source if frozen_source is None else frozen_source
    )
    slices = _frozen_source_slices(frozen, args.existing_latency)
    if slices is None:
        raise ValueError(
            "could not determine frozen design latency; provide --existing-latency"
        )

    original_source_snapshot = _vhdl_source_snapshot(
        frozen["vhdl_paths"], frozen["source_root"]
    )
    generator_provenance = _frozen_generator_provenance(frozen)
    trace_path, trace_summary = _placement_trace_summary(frozen["source_root"])
    copied_source = _copy_vhdl_source_snapshot(
        frozen["vhdl_paths"], frozen["source_root"], evidence_dir
    )
    snapshot_root = copied_source["snapshot_root"]
    snapshot_paths = copied_source["snapshot_paths"]

    env = os.environ.copy()
    functional = _run_functional_sim(
        snapshot_root,
        slices,
        env,
        artifact_dir=evidence_dir,
        vhdl_paths=snapshot_paths,
        top_entity=frozen["top"],
    )
    _assert_vhdl_source_unchanged(
        original_source_snapshot,
        frozen["vhdl_paths"],
        frozen["source_root"],
        "during functional simulation",
    )
    _assert_vhdl_source_unchanged(
        copied_source["snapshot"],
        snapshot_paths,
        snapshot_root,
        "during functional simulation",
    )

    suffix = device_models.GET_MODEL_ARTIFACT_SUFFIX(args.recipe)
    timing_log = evidence_dir / f"device_models_frozen{suffix}.log"
    started = time.monotonic()
    device_models._run_synth_and_sta(
        " ".join(str(path) for path in snapshot_paths),
        frozen["top"],
        evidence_dir,
        timing_log,
        args.recipe,
    )
    runtime = time.monotonic() - started
    _assert_vhdl_source_unchanged(
        original_source_snapshot,
        frozen["vhdl_paths"],
        frozen["source_root"],
        "during synthesis and STA",
    )
    _assert_vhdl_source_unchanged(
        copied_source["snapshot"],
        snapshot_paths,
        snapshot_root,
        "during synthesis and STA",
    )

    timing_path = timing_log.with_name(timing_log.stem + "_timing.json")
    timing = json.loads(timing_path.read_text()) if timing_path.is_file() else {}
    artifact_paths = device_models._get_synthesis_recipe_artifact_paths(
        frozen["top"], evidence_dir, args.recipe
    )
    mapped_path = Path(artifact_paths["mapped_json"])
    mapped = _mapped_netlist_metrics(mapped_path if mapped_path.is_file() else None)
    fmax = timing.get("fmax_mhz")
    if fmax is None and timing.get("worst_period_ns"):
        fmax = 1000.0 / timing["worst_period_ns"]
    timing_vhdl_hashes = [
        record.get("sha256")
        for record in timing.get("synthesis_inputs", {})
        .get("vhdl", {})
        .get("files", [])
    ]
    snapshot_vhdl_hashes = [
        record["sha256"] for record in copied_source["snapshot"]["vhdl_files"]
    ]
    mapper_sources_after = _compiler_source_records()
    harness_source_after = _source_file_record(Path(__file__))
    mapper_sources_unchanged = (
        mapper_sources_after == mapper_sources_at_launch
        and harness_source_after == harness_source_at_launch
    )
    checks = {
        "functional_passed": bool(functional.get("passed")),
        "fmax_strictly_above_143_mhz": fmax is not None and fmax > GOAL_MHZ,
        "slice_limit": slices <= SLICE_LIMITS[variant],
        "stage_semantics": (
            functional.get("latency_slices") == slices
            and trace_summary.get("realized") == slices
            and (generator_provenance.get("metrics") or {}).get("stages")
            == slices + 1
        ),
        "source_unchanged_through_simulation_and_mapping": True,
        "mapped_json_preserved": mapped_path.is_file(),
        "mapped_json_hash_matches_timing": (
            mapped_path.is_file()
            and timing.get("mapped_json_sha256") == _sha256(mapped_path)
        ),
        "mapping_succeeded": timing.get("mapping_succeeded") is True,
        "zero_unmapped_cells": timing.get("n_unmapped_cells") == 0,
        "complete_timing_topology": timing.get("incomplete_topo") is False,
        "timing_recipe_matches": timing.get("synthesis_recipe") == args.recipe,
        "timing_model_identity_matches": (
            timing.get("model_cache_identity") == model_record["cache_identity"]
        ),
        "timing_vhdl_bytes_match_snapshot": (
            timing_vhdl_hashes == snapshot_vhdl_hashes
            and len(timing_vhdl_hashes) > 0
        ),
        "mapper_sources_unchanged_through_mapping": mapper_sources_unchanged,
    }
    liberty = REPO_ROOT / "src" / "liberty_data" / "sky130_fd_sc_hvl__tt_025C_3v30.lib"
    evidence = {
        "schema_version": 1,
        "mode": "frozen_vhdl_recipe",
        "run_id": evidence_dir.name,
        "created_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "variant": variant,
        "recipe": args.recipe,
        "source": {
            "path": str(frozen["source"]),
            "top_entity": frozen["top"],
            "vhdl_file_list": (
                str(frozen["file_list"]) if frozen["file_list"] is not None else None
            ),
            "original_vhdl_files": original_source_snapshot["vhdl_files"],
            "original_aggregate_sha256": original_source_snapshot[
                "aggregate_sha256"
            ],
            "snapshot_root": str(snapshot_root.relative_to(evidence_dir)),
            **copied_source["snapshot"],
            "original_and_snapshot_bytes_equal": True,
            "verified_unchanged_before_copy_through_sta": True,
        },
        "vhdl_generator": generator_provenance,
        "manifest_mapper": {
            "repository_at_launch": mapper_repository_at_launch,
            "compiler_sources_at_launch": mapper_sources_at_launch,
            "compiler_sources_after_verification": mapper_sources_after,
            "harness_source_at_launch": harness_source_at_launch,
            "harness_source_after_verification": harness_source_after,
            "compiler_sources_unchanged": mapper_sources_unchanged,
            "role": (
                "mapping/STA/simulation harness provenance only; these "
                "sources are not asserted to have generated the frozen VHDL"
            ),
        },
        "model": model_record,
        "liberty": {
            "path": str(liberty.relative_to(REPO_ROOT)),
            "bytes": liberty.stat().st_size,
            "sha256": _sha256(liberty),
        },
        "tools": _tool_records(),
        "mapping": {
            "runtime_seconds": runtime,
            "synthesis_script": str(Path(artifact_paths["synthesis_script"]).name),
            "synthesis_log": str(Path(artifact_paths["synthesis_log"]).name),
            "mapped_json": str(mapped_path.name) if mapped_path.is_file() else None,
            "timing_report": str(timing_path.name) if timing_path.is_file() else None,
        },
        "placements": {
            **trace_summary,
            "trace_path": str(trace_path) if trace_path is not None else None,
        },
        "metrics": {
            "goal_mhz": GOAL_MHZ,
            "fmax_mhz": fmax,
            "slices": slices,
            "stages": slices + 1,
            **mapped,
            **timing,
        },
        "functional": functional,
        "acceptance": {
            "slice_limit": SLICE_LIMITS[variant],
            "strict_fmax_mhz": GOAL_MHZ,
            "checks": checks,
            "passed": all(checks.values()),
        },
        "evidence_note": args.evidence_note,
    }
    _write_json(evidence_dir / "recipe_evidence.json", evidence)
    evidence["artifacts"] = _artifact_records(evidence_dir)
    _write_json(evidence_dir / "recipe_evidence.json", evidence)
    status = "PASS" if evidence["acceptance"]["passed"] else "FAIL"
    print(
        f"[{status}] frozen {variant} recipe={args.recipe}: "
        f"fmax={fmax} MHz, slices={slices}, stages={slices + 1}, "
        f"functional={functional.get('passed')}"
    )
    print(f"Recipe evidence: {evidence_dir / 'recipe_evidence.json'}")
    return evidence


def _build_one(args, variant, run_dir):
    if (
        not args.existing_build
        and run_dir.exists()
        and any(run_dir.iterdir())
    ):
        raise ValueError(
            f"benchmark output directory must be empty for a new build: {run_dir}"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    model_record = _model_record(args.recipe)
    fixture_source = FIXTURE_DIR / f"{variant}.py"
    fixture_source_at_launch = {
        "path": str(fixture_source.relative_to(REPO_ROOT)),
        "bytes": fixture_source.stat().st_size,
        "sha256": _sha256(fixture_source),
    }
    env = os.environ.copy()
    env["PIPELINEC_INTERNAL_SKY130_RECIPE"] = args.recipe
    placement_label = args.placement
    if args.placement in ("step-boundaries", "step-boundaries-div0"):
        if variant != "gate":
            raise ValueError("step-boundaries placement is only valid for the gate fixture")
        request_path = run_dir / "placement_request.json"
        _write_json(
            request_path,
            _placement_request(
                args.extra_placement_id,
                hand_equivalent=args.placement == "step-boundaries-div0",
            ),
        )
        env["PIPELINEC_INTERNAL_PLACEMENT_FILE"] = str(request_path.resolve())
        if args.extra_placement_id:
            placement_label += f"+{len(args.extra_placement_id)}"

    build_cmd = [
        PYPELINEC,
        FIXTURE_DIR / f"{variant}.py",
        "--syn_tool",
        "sky130",
        "--out_dir",
        run_dir,
    ]
    if args.pipeline_min_effort is not None:
        build_cmd += ["--pipeline_min_effort", str(args.pipeline_min_effort)]
    if args.elaborate_only:
        build_cmd += ["--no_sweep"]

    launch_context = {
        "repository": _repo_state(),
        "compiler_sources": _compiler_source_records(),
        "harness_source_at_launch": _source_file_record(Path(__file__)),
        "evidence_note": args.evidence_note,
        "model": model_record,
        "fixture_source_at_launch": fixture_source_at_launch,
    }
    if args.compiler_commit:
        if args.existing_build:
            launch_context["manifest_generator_repository"] = launch_context[
                "repository"
            ]
            launch_context["repository"] = {
                "commit": args.compiler_commit,
                "snapshot_override": True,
                "dirty_state_captured": False,
                "state_note": (
                    "compiler snapshot predates this manifest; do not attribute "
                    "the manifest generator's current worktree to the build"
                ),
            }
            launch_context["compiler_sources"] = []
            launch_context["compiler_source_hashes_note"] = (
                "not recaptured from the already-running snapshot; commit and evidence_note are authoritative"
            )
    if args.source_sha256:
        launch_context["source_sha256_override"] = args.source_sha256
    _write_json(run_dir / "launch_context.json", launch_context)

    if args.existing_build:
        build_rc = args.existing_returncode
        build_seconds = args.existing_runtime_seconds or 0.0
        build_cmd = ["<existing-build>", run_dir]
    else:
        build_rc, build_seconds = _run_logged(build_cmd, run_dir / "build.log", env=env)

    build_text = (run_dir / "build.log").read_text(errors="replace") if (run_dir / "build.log").is_file() else ""
    slices = _parse_depth(build_text)
    if slices is None and args.existing_latency is not None:
        slices = args.existing_latency
    final_vhdl_exists = (run_dir / "vhdl_files.txt").is_file()
    functional = {"passed": False, "skipped": not final_vhdl_exists}
    exact_final_evidence = None
    # A timing miss makes pypelinec return nonzero after deliberately writing
    # its best VHDL.  That artifact still needs cycle verification, especially
    # for the forced 32-boundary physical-control experiment.
    if final_vhdl_exists and not args.elaborate_only:
        try:
            exact_final_evidence = _run_frozen_recipe(
                args,
                variant,
                run_dir / "exact_final_remap",
                frozen_source=run_dir,
            )
            functional = exact_final_evidence["functional"]
        except Exception as exc:
            functional = {"passed": False, "error": str(exc)}
            print(f"Exact final VHDL remap/verification failed: {exc}", file=sys.stderr)
    elif final_vhdl_exists:
        try:
            functional = _run_functional_sim(run_dir, slices, env)
        except Exception as exc:
            functional = {"passed": False, "error": str(exc)}
            print(f"Functional simulation setup failed: {exc}", file=sys.stderr)

    fixture_source_after = {
        "path": str(fixture_source.relative_to(REPO_ROOT)),
        "bytes": fixture_source.stat().st_size,
        "sha256": _sha256(fixture_source),
    }
    launch_context["fixture_source_after_verification"] = fixture_source_after
    launch_context["fixture_source_unchanged"] = (
        fixture_source_after == fixture_source_at_launch
    )
    if not args.existing_build:
        compiler_sources_after = _compiler_source_records()
        harness_source_after = _source_file_record(Path(__file__))
        launch_context["compiler_sources_after_verification"] = (
            compiler_sources_after
        )
        launch_context["harness_source_after_verification"] = (
            harness_source_after
        )
        launch_context["compiler_sources_unchanged"] = (
            compiler_sources_after == launch_context["compiler_sources"]
            and harness_source_after
            == launch_context["harness_source_at_launch"]
        )
    _write_json(run_dir / "launch_context.json", launch_context)
    manifest = _manifest(
        run_dir,
        variant,
        args.recipe,
        placement_label,
        build_cmd,
        build_rc,
        build_seconds,
        functional,
        slices_override=slices,
        exact_final_evidence=exact_final_evidence,
    )
    status = "PASS" if manifest["acceptance"]["passed"] else "FAIL"
    print(
        f"[{status}] {variant} recipe={args.recipe} placement={placement_label}: "
        f"fmax={manifest['metrics']['fmax_mhz']} MHz, "
        f"slices={manifest['metrics']['slices']}, stages={manifest['metrics']['stages']}, "
        f"functional={functional.get('passed')}"
    )
    print(f"Manifest: {run_dir / 'manifest.json'}")
    return manifest


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("gate", "arithmetic", "all"), default="all")
    parser.add_argument("--out_dir", type=Path, required=True)
    parser.add_argument("--recipe", choices=RECIPES, default=DEFAULT_RECIPE)
    parser.add_argument(
        "--placement",
        choices=("auto", "step-boundaries", "step-boundaries-div0"),
        default="auto",
    )
    parser.add_argument(
        "--extra-placement-id",
        action="append",
        default=[],
        help="Add a deterministic candidate_id from placement_trace.json to the "
        "fixed gate schedule (repeat at most 16 times).",
    )
    parser.add_argument("--pipeline_min_effort", type=int, default=None)
    parser.add_argument(
        "--elaborate-only",
        "--no-sweep",
        dest="elaborate_only",
        action="store_true",
        help="Generate the first planned VHDL/placement trace with PipelineC "
        "--no_sweep; diagnostic-only and performs no final sky130 timing sweep.",
    )
    parser.add_argument(
        "--frozen-vhdl-source",
        type=Path,
        help="Run only the selected fixed synthesis recipe on byte-frozen VHDL "
        "from a run directory, vhdl_files.txt, or generated *_syn.sh.",
    )
    parser.add_argument(
        "--existing-build",
        action="store_true",
        help="Do not rebuild; verify artifacts already in --out_dir (one variant only).",
    )
    parser.add_argument(
        "--existing-latency",
        type=int,
        default=None,
        help="Diagnostic fallback when an existing build has no build.log depth summary.",
    )
    parser.add_argument(
        "--existing-runtime-seconds",
        type=float,
        help="Measured wall time for an already-completed --existing-build whose "
        "stdout was not captured by this harness.",
    )
    parser.add_argument(
        "--existing-returncode",
        type=int,
        help="Observed process return code for --existing-build. Required for "
        "acceptance; diagnostic imports may leave it unknown.",
    )
    parser.add_argument(
        "--compiler-commit",
        help="Commit actually imported by an already-running/existing build; records a snapshot override.",
    )
    parser.add_argument(
        "--source-sha256",
        help="Source SHA-256 actually imported by an existing build when it differs from the checked-in fixture.",
    )
    parser.add_argument("--evidence-note", help="Free-form provenance note stored in the manifest.")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write the manifest but return success even when acceptance is not met.",
    )
    args = parser.parse_args(argv)
    if len(args.extra_placement_id) > 16:
        parser.error("at most 16 --extra-placement-id values are allowed")
    if args.extra_placement_id and not args.placement.startswith("step-boundaries"):
        parser.error("--extra-placement-id requires a step-boundaries placement")
    if args.existing_build and args.variant == "all":
        parser.error("--existing-build requires one explicit --variant")
    if args.existing_runtime_seconds is not None and not args.existing_build:
        parser.error("--existing-runtime-seconds requires --existing-build")
    if args.existing_runtime_seconds is not None and args.existing_runtime_seconds < 0:
        parser.error("--existing-runtime-seconds must be non-negative")
    if args.existing_returncode is not None and not args.existing_build:
        parser.error("--existing-returncode requires --existing-build")
    if args.existing_returncode is not None and args.existing_returncode < 0:
        parser.error("--existing-returncode must be non-negative")
    if (
        args.existing_build
        and args.existing_returncode is None
        and not args.diagnostic
    ):
        parser.error(
            "acceptance for --existing-build requires --existing-returncode; "
            "otherwise use --diagnostic"
        )
    if (args.compiler_commit or args.source_sha256) and not args.existing_build:
        parser.error("compiler/source snapshot overrides require --existing-build")
    if args.frozen_vhdl_source is not None and args.variant == "all":
        parser.error("--frozen-vhdl-source requires one explicit --variant")
    if args.frozen_vhdl_source is not None and args.existing_build:
        parser.error("--frozen-vhdl-source and --existing-build are mutually exclusive")
    if args.frozen_vhdl_source is not None and args.elaborate_only:
        parser.error("--frozen-vhdl-source and --elaborate-only are mutually exclusive")
    if args.frozen_vhdl_source is not None and args.placement != "auto":
        parser.error("frozen recipe runs inherit placement from their VHDL source")
    if args.elaborate_only and not args.diagnostic:
        parser.error("--elaborate-only is diagnostic-only; also pass --diagnostic")
    return args


def main(argv=None):
    args = _parse_args(argv)
    if args.frozen_vhdl_source is not None:
        evidence = _run_frozen_recipe(args, args.variant, args.out_dir.resolve())
        return 0 if evidence["acceptance"]["passed"] or args.diagnostic else 1
    variants = ("gate", "arithmetic") if args.variant == "all" else (args.variant,)
    manifests = []
    for variant in variants:
        run_dir = args.out_dir
        if len(variants) > 1:
            run_dir = run_dir / f"{variant}__{args.placement}__{args.recipe}"
        manifests.append(_build_one(args, variant, run_dir.resolve()))
    passed = all(m["acceptance"]["passed"] for m in manifests)
    return 0 if passed or args.diagnostic else 1


if __name__ == "__main__":
    sys.exit(main())
