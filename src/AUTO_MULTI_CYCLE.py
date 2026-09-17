"""Multi-cycle paths: MULTI_CYCLE registers and AUTO_MULTI_CYCLE cycle counts.

See docs/AUTO_MULTI_CYCLE_DESIGN.md. This module owns finding the
launch/capture register cells of each multi-cycle path, the timing
constraints written for them, the sweep's feedback that raises an
AUTO_MULTI_CYCLE count until its path meets timing, and harvesting the built
counts for the `.latency` pin-and-confirm loop.
"""
import math
import re
import sys

import C_TO_LOGIC
import SYN
import VHDL
import VIVADO


def ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state):
    """AUTO_MULTI_CYCLE canonical key -> cycle count the design was elaborated with
    (the matching Logic.mcp_tuples entry's count)."""
    rv = {}
    for logic in parser_state.FuncLogicLookupTable.values():
        auto_multi_cycle_tuples = getattr(logic, "auto_multi_cycle_tuples", None)
        if not auto_multi_cycle_tuples:
            continue
        for mcp_tup in logic.mcp_tuples:
            constraint = auto_multi_cycle_tuples.get((mcp_tup[1], mcp_tup[2]))
            if constraint is not None:
                rv[constraint.key] = int(mcp_tup[0])
    return rv


def MCP_EFFECTIVE_NCYCLES(mcp_tup, auto_multi_cycle_constraint, multimain_timing_params):
    """Cycle count to constrain an mcp_tuples entry with: the throughput
    sweep's current choice for an AUTO_MULTI_CYCLE path (MultiMainTimingParams.
    auto_multi_cycle_ncycles -- the sweep changes it without re-elaborating), else the
    elaborated count."""
    if auto_multi_cycle_constraint is not None:
        overrides = getattr(multimain_timing_params, "auto_multi_cycle_ncycles", None) or {}
        if auto_multi_cycle_constraint.key in overrides:
            return str(overrides[auto_multi_cycle_constraint.key])
    return mcp_tup[0]


def GET_MCP_CELL_PATHS(inst_name, top_inst, top_path, parser_state):
    """Vivado cell-path globs of every multi-cycle path in instance inst_name,
    relative to the synthesized top (top_inst, named top_path in the netlist).
    Returns [(mcp_tup, start_reg_cell_glob, end_reg_cell_glob,
    AutoMultiCycleConstraint or None)], sorted for deterministic output. Shared by
    the XDC writer and the sweep's timing-report-to-AUTO_MULTI_CYCLE matching."""
    rv = []
    # Determine partial hierarchy path being synthesized
    top_inst_tok = top_inst + C_TO_LOGIC.SUBMODULE_MARKER
    if inst_name == top_inst:
        partial_inst_name = ""
    elif inst_name.startswith(top_inst_tok):
        partial_inst_name = inst_name[len(top_inst_tok) :]
    partial_inst_name = partial_inst_name.strip(C_TO_LOGIC.SUBMODULE_MARKER)
    partial_inst_path = ""
    toks = partial_inst_name.split(C_TO_LOGIC.SUBMODULE_MARKER)
    for tok in toks:
        partial_inst_path += VHDL.WIRE_TO_VHDL_NAME(tok, parser_state) + "/"
    partial_inst_path = partial_inst_path.strip("/")
    if partial_inst_path != "":
        partial_inst_path = partial_inst_path + "/"
    # Loop over all MCP constraints in this func
    func_logic = parser_state.LogicInstLookupTable[inst_name]
    auto_multi_cycle_tuples = getattr(func_logic, "auto_multi_cycle_tuples", None) or {}
    top_prefix = top_path + "/" if top_path else ""
    for mcp_tup in sorted(func_logic.mcp_tuples):
        start_reg_cell_path = top_prefix + partial_inst_path + mcp_tup[1] + "_reg[*]"
        end_reg_cell_path = top_prefix + partial_inst_path + mcp_tup[2] + "_reg[*]"
        rv.append(
            (
                mcp_tup,
                start_reg_cell_path,
                end_reg_cell_path,
                auto_multi_cycle_tuples.get((mcp_tup[1], mcp_tup[2])),
            )
        )
    return rv


def GET_MCP_PATH_CONSTRAINTS(
    inst_name, top_inst, top_path, multimain_timing_params, parser_state
):
    # Hard coded to Vivado for now...
    if SYN.SYN_TOOL is not VIVADO:
        raise Exception("Multi cycle paths have only been tested with Vivado!")
    rv = []
    for mcp_tup, start_reg_cell_path, end_reg_cell_path, auto_multi_cycle in GET_MCP_CELL_PATHS(
        inst_name, top_inst, top_path, parser_state
    ):
        ncycles = MCP_EFFECTIVE_NCYCLES(mcp_tup, auto_multi_cycle, multimain_timing_params)
        start_reg_path = start_reg_cell_path + "/C"
        end_reg_path = end_reg_cell_path + "/D"
        rv.append(
            f"set_multicycle_path {ncycles} -setup -from [get_pins {start_reg_path}] -to [get_pins {end_reg_path}]"
        )
        # Also need to stop tool from mangling the path of start and end regs
        rv.append(f"set_property KEEP TRUE [get_cells {start_reg_cell_path}]")
        rv.append(f"set_property KEEP TRUE [get_cells {end_reg_cell_path}]")
    return rv


def HARVEST_AUTO_MULTI_CYCLE_NCYCLES(parser_state, multimain_timing_params):
    """AUTO_MULTI_CYCLE canonical key -> multi-cycle count the build constrained it
    with: the throughput sweep's final choice where it made one, else the
    elaborated count. Every AUTO_MULTI_CYCLE elaborated into the design is present."""
    ncycles = ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state)
    overrides = getattr(multimain_timing_params, "auto_multi_cycle_ncycles", None) or {}
    for key in ncycles:
        if key in overrides:
            ncycles[key] = overrides[key]
    return ncycles


def CHECK_AUTO_MULTI_CYCLE_TAGS_READ(parser_state):
    """A start_latency=/max_latency= AUTO_MULTI_CYCLE whose .latency no design code
    read can't have its handshake follow the sweep's cycle count: fail the
    build before any synthesis is spent on it."""
    import pypeline

    elaborated = ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state)
    unread = [key for key in pypeline.AUTO_MULTI_CYCLE_UNREAD_KEYS() if key in elaborated]
    if unread:
        sys.exit(
            "AUTO_MULTI_CYCLE: .latency was never read by the design for "
            + ", ".join(unread)
            + ". The throughput sweep may change a multi-cycle path's cycle "
            "count, so the logic timing it (e.g. a launch/capture handshake "
            "counter) must be written in terms of MC.latency. Use "
            "MULTI_CYCLE[N] (or AUTO_MULTI_CYCLE(latency=N)) for a hand-timed path."
        )


def AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED(parser_state, auto_multi_cycle_ncycles):
    """True when every AUTO_MULTI_CYCLE count the build settled on equals the count the
    design was elaborated with and every .latency value design code read --
    no re-elaboration needed for AUTO_MULTI_CYCLE's sake."""
    import pypeline

    if ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state) != auto_multi_cycle_ncycles:
        return False
    for key, values in pypeline.AUTO_MULTI_CYCLE_SERVED_LATENCIES().items():
        if key in auto_multi_cycle_ncycles and values != {auto_multi_cycle_ncycles[key]}:
            return False
    return True


def PRINT_AUTO_MULTI_CYCLE_NCYCLES(auto_multi_cycle_ncycles):
    for key, ncycles in sorted(auto_multi_cycle_ncycles.items()):
        print(f"AUTO_MULTI_CYCLE {key}: {ncycles} cycles", flush=True)


# ─────────────────────────────────────────────
# AUTO_MULTI_CYCLE feedback inside the throughput sweep
# ─────────────────────────────────────────────

class AutoMultiCycleGroup:
    """All multi-cycle paths elaborated from one pypeline.AUTO_MULTI_CYCLE tag. They
    share a single cycle count (the design's Python reads one .latency int),
    kept in MultiMainTimingParams.auto_multi_cycle_ncycles[key] during the sweep."""

    def __init__(self, key, constraint):
        self.key = key
        self.constraint = constraint  # C_TO_LOGIC.AutoMultiCycleConstraint
        self.paths = []  # (inst, start_reg, end_reg)

    def label(self):
        return self.key


def COLLECT_AUTO_MULTI_CYCLE_GROUPS(parser_state):
    """AUTO_MULTI_CYCLE canonical key -> AutoMultiCycleGroup, over every instance whose
    Logic carries AUTO_MULTI_CYCLE multi-cycle paths."""
    groups = {}
    for inst in sorted(parser_state.LogicInstLookupTable):
        logic = parser_state.LogicInstLookupTable[inst]
        auto_multi_cycle_tuples = getattr(logic, "auto_multi_cycle_tuples", None)
        if not auto_multi_cycle_tuples:
            continue
        for (start_reg, end_reg), constraint in sorted(
            auto_multi_cycle_tuples.items(), key=lambda item: item[0]
        ):
            group = groups.setdefault(
                constraint.key, AutoMultiCycleGroup(constraint.key, constraint)
            )
            group.paths.append((inst, start_reg, end_reg))
    return groups


def _MCP_CELL_GLOB_REGEX(cell_glob):
    """Regex for a report's register cell name (e.g. top/sub/launch_reg[12], or
    top/sub/launch_reg[field][12] for a struct register) matching a Vivado XDC
    cell glob (top/sub/launch_reg[*]; Vivado's * spans anything but a
    hierarchy separator)."""
    pattern = re.escape(cell_glob).replace(re.escape("[*]"), r"\[[^/]*\]")
    return re.compile(r"(^|/)" + pattern + r"$")


def AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT(
    path_report, groups, parser_state, multimain_timing_params
):
    """The AutoMultiCycleGroup whose multi-cycle path this timing report's critical
    path is -- start register = a tagged .start reg, end register = the same
    path's .end reg, and a requirement of (current count) clock periods -- or
    None. Cell names come from GET_MCP_CELL_PATHS, the same globs the
    set_multicycle_path constraints are written with."""
    if (
        not groups
        or path_report.start_reg_name is None
        or path_report.end_reg_name is None
    ):
        return None
    tpl = multimain_timing_params.TimingParamsLookupTable
    period_ns = path_report.source_ns_per_clock
    requirement_ns = getattr(path_report, "requirement_ns", None)
    for key in sorted(groups):
        group = groups[key]
        ncycles = multimain_timing_params.auto_multi_cycle_ncycles.get(key)
        if (
            ncycles is not None
            and requirement_ns is not None
            and period_ns
            and round(requirement_ns / period_ns) != ncycles
        ):
            continue
        for inst in sorted({path[0] for path in group.paths}):
            main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
                inst, parser_state
            )
            main_logic = parser_state.LogicInstLookupTable[main_func]
            top_path = VHDL.GET_ENTITY_NAME(main_func, main_logic, tpl, parser_state)
            for _tup, start_glob, end_glob, constraint in GET_MCP_CELL_PATHS(
                inst, main_func, top_path, parser_state
            ):
                if constraint is None or constraint.key != key:
                    continue
                if _MCP_CELL_GLOB_REGEX(start_glob).search(
                    path_report.start_reg_name
                ) and _MCP_CELL_GLOB_REGEX(end_glob).search(path_report.end_reg_name):
                    return group
    return None


def AUTO_MULTI_CYCLE_NEEDED_NCYCLES(path_delay_ns, ncycles, target_period_ns):
    """Cycle count a failing multi-cycle path needs. path_delay_ns is the
    per-cycle figure VIVADO.PathReport reports for a multi-cycle path
    ((requirement - slack) / ncycles), so the real launch->capture delay is
    ncycles * path_delay_ns. Always at least one more than the current count
    (the path failed at it)."""
    total_ns = path_delay_ns * ncycles
    needed = int(math.ceil(total_ns / target_period_ns - 1e-9))
    return max(ncycles + 1, needed)


def AUTO_MULTI_CYCLE_FEEDBACK(group, path_report, target_mhz, multimain_timing_params):
    """Failing-timing feedback for a critical path that IS an AUTO_MULTI_CYCLE
    multi-cycle path: raise the group's count to what the slack says it needs,
    unless that exceeds its latency= / max_latency= cap. Grow-only -- the count
    never drops below where it started. Returns (action, changed, limit blame
    or None)."""
    ncycles = multimain_timing_params.auto_multi_cycle_ncycles[group.key]
    needed = AUTO_MULTI_CYCLE_NEEDED_NCYCLES(
        path_report.path_delay_ns, ncycles, 1000.0 / target_mhz
    )
    cap = group.constraint.upper_bound()
    label = group.label()
    total_ns = path_report.path_delay_ns * ncycles
    if cap is not None and needed > cap:
        blame = (
            f"AUTO_MULTI_CYCLE {label} ({group.constraint.describe()}, {ncycles} cycles "
            f"built, ~{needed} needed)"
        )
        print(
            f"[sweep] WARNING: limited by {blame}: its multi-cycle path "
            f"(~{total_ns:.2f} ns) is the critical path and cannot take more "
            "cycles. Raise or remove latency= / max_latency=, or lower the clock "
            "goal. Keeping best result.",
            flush=True,
        )
        return f"stop(auto_multi_cycle latency limit {label})", False, blame
    multimain_timing_params.auto_multi_cycle_ncycles[group.key] = needed
    print(
        f"[sweep] AUTO_MULTI_CYCLE {label}: critical path is its multi-cycle path "
        f"(~{total_ns:.2f} ns at {ncycles} cycles); raising to {needed} cycles",
        flush=True,
    )
    return f"auto_multi_cycle({label} {ncycles}->{needed})", True, None
