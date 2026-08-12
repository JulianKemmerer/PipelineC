# This file contains timing models, and other estimation tools that characterize devices
# The goal to is reduce time spent calling on or iterating with slow synthesis+pnr tools
# Primarily this begins with modelings timing delays, but could model resource usage too in future

# In line with issues like:
# https://github.com/JulianKemmerer/PipelineC/issues/46
# https://github.com/JulianKemmerer/PipelineC/issues/48
# https://github.com/JulianKemmerer/PipelineC/issues/64

# (C) 2022 Victor Surez Rovere <suarezvictor@gmail.com>
# NOTE: only for integer operations (not floats)

import os, re, math

ops = {}


def part_supported(part_str):
    # DEVICE_MODELS is deprecated for now: soft-operator-library entities
    # (include/pypeline/operators/) aren't named BIN_OP_*/UNARY_OP_*, so
    # func_name_to_op_and_widths can't recognize them -- estimation silently
    # falls back to real per-entity synthesis for those, producing
    # inconsistent (sometimes-modeled, sometimes-not) delay estimates within
    # the same design and destabilizing AUTOPIPELINE/throughput-sweep
    # planning. Always return False so every function goes through real
    # synthesis or the path_delay_cache uniformly until this is revisited.
    return False


def estimate_int_timing(integer_op, widths_vector):
    timing_model = {  # category, origin, slope
        "arith": (1.92, 0.04),
        "comp": (2.49, 0.0),
        "equal": (1.72, 0.04),
        "logical": (1.28, 0.0),
        "shift": (3.42, 0.0),
    }

    categ = ""
    if integer_op in ["PLUS", "MINUS", "NEGATE"]:
        categ = "arith"
    if integer_op in ["GT", "GTE", "LT", "LTE"]:
        categ = "comp"
    if integer_op in ["EQ", "NEQ"]:
        categ = "equal"
    if integer_op in ["AND", "OR", "XOR", "NOT"]:
        categ = "logical"
    if integer_op in ["SL", "SR"]:
        categ = "shift"
    if categ not in timing_model:
        return None  # unknown operation

    bits = max(widths_vector)
    origin, slope = timing_model[categ]
    return origin + bits * slope


def func_name_to_op_and_widths(func_name):
    p = func_name.find("_OP_")
    if p >= 0:
        optyp = func_name[:p]
        _ = func_name.find("_", p + 4)
        op = func_name[p + 4 : _]
        widths = re.findall(r"int[0-9]+", func_name[4:])
        if not len(widths):
            return None
        widths = [int(w[3:]) for w in widths]  # cut 'int'
        return op, widths
    return None


def process_delays(dir_path):
    print("real\top\testimation\twidths")
    mindelay = 1e6
    total = count = 0
    for path in os.listdir(dir_path):
        full = os.path.join(dir_path, path)
        if os.path.isfile(full):
            op_and_widths = func_name_to_op_and_widths(path)
            if op_and_widths is not None:
                op, widths = op_and_widths
                estim_ns = estimate_int_timing(op, widths)
                with open(full, "r") as file:
                    time_ns = float(file.read())

                if estim_ns is not None:
                    if time_ns < mindelay:
                        mindelay = time_ns
                    total += (time_ns - estim_ns) ** 2
                    count += 1
                    print(
                        str(time_ns)
                        + "\t"
                        + op
                        + "\t"
                        + str(estim_ns)
                        + "\t".join([str(w) for w in widths])
                    )

    rms = math.sqrt(total / count)
    print("Count:", count, ", minimum delay (ns):", mindelay, ", RMS error (ns):", rms)


# ═══════════════════════════════════════════════════════════════════════════
# Section (a): sky130 liberty NLDM data load + delay/setup table lookups.
#
# Real, load-dependent cell delay -- the missing physics behind PyRTL's flat
# per-gate-type/width-only cost model (see docs/DEVICE_MODELS_DESIGN.md and
# the plan this was built from). Reads a small condensed JSON data pack
# (src/liberty_data/, generated offline by a scratchpad script from a real
# sky130_fd_sc_hvl__tt_025C_3v30.lib -- see that script's docstring), not the
# raw multi-MB liberty file, so there is no runtime PDK dependency.
#
# Deliberately depends on nothing but the stdlib (os, json, math) -- no SYN,
# VHDL, or OPEN_TOOLS import anywhere in this section or section (b) below,
# so both can be imported and driven standalone (e.g. by a V6-style
# validation script run directly against latchup's own exported netlists)
# with zero PipelineC compiler integration. Only section (c) (the actual
# SYN_TOOL surface, further down) is allowed to depend on the rest of the
# compiler, and it does so via imports local to its own functions for
# exactly this reason.
# ═══════════════════════════════════════════════════════════════════════════

import json as _json

_LIBERTY_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "liberty_data")
DEFAULT_LIBRARY = "sky130_fd_sc_hvl"
DEFAULT_CORNER = "tt_025C_3v30"

# No clock-tree or interconnect model (matches latchup's own timing.log,
# which reports zero net delay throughout -- see plan finding 7): every
# primary input and the idealized global clock source both settle with this
# transition. Real per-cell delay tables are dominated by output LOAD
# capacitance, not input transition (e.g. dfxtp_1's own Q-arc varies ~6x
# across its full load range at a *fixed* input transition, but only a few
# percent across its full transition range at fixed load) -- so this
# constant is a second-order simplification, not the dominant error term.
DEFAULT_TRANSITION_NS = 0.03

_liberty_cache = {}  # (library, corner) -> {cell_name: CellModel}


def _bilinear(table, x, y):
    """2D NLDM table lookup: x against index_1, y against index_2, with
    linear EXTRAPOLATION past either axis's bounds (not clamping) -- a real
    out-of-characterized-range load is real and must still get a
    worse-than-table-edge delay. Clamping was measured (V1, prior session)
    to silently underpredict exactly the cells whose real load exceeds their
    characterized range, which is the decisive cliff mechanism this whole
    model exists to capture.
    """
    idx1 = table["index_1"]
    idx2 = table["index_2"]
    rows = table["values"]

    def bracket(arr, v):
        if len(arr) == 1:
            return 0, 0, 0.0
        if v <= arr[0]:
            return 0, 1, (v - arr[0]) / (arr[1] - arr[0]) if arr[1] != arr[0] else 0.0
        if v >= arr[-1]:
            n = len(arr) - 1
            m = n - 1
            return m, n, (v - arr[m]) / (arr[n] - arr[m]) if arr[n] != arr[m] else 0.0
        for i in range(len(arr) - 1):
            if arr[i] <= v <= arr[i + 1]:
                frac = (v - arr[i]) / (arr[i + 1] - arr[i]) if arr[i + 1] != arr[i] else 0.0
                return i, i + 1, frac
        return len(arr) - 1, len(arr) - 1, 0.0

    i0, i1, fx = bracket(idx1, x)
    j0, j1, fy = bracket(idx2, y)
    v00, v01 = rows[i0][j0], rows[i0][j1]
    v10, v11 = rows[i1][j0], rows[i1][j1]
    v0 = v00 + (v01 - v00) * fy
    v1 = v10 + (v11 - v10) * fy
    return v0 + (v1 - v0) * fx


class CellModel:
    """One liberty cell's pins, arcs (combinational delay/transition tables,
    keyed by (out_pin, related_pin)), and setup/hold constraints (keyed by
    (in_pin, related_pin, timing_type)). Pure data + table lookups -- no
    graph/STA logic lives here, that's section (b) below.
    """

    def __init__(self, name, cell_json):
        self.name = name
        self.input_pins = cell_json["input_pins"]  # pin -> {"cap":.., "is_clock":..}
        self.output_pins = cell_json["output_pins"]  # pin -> {"max_capacitance":..}
        self.max_transition = cell_json.get("max_transition")
        self.is_sequential = cell_json.get("is_sequential", False)
        self._arcs = {}  # (out_pin, related_pin) -> arc dict
        for arc in cell_json.get("arcs", []):
            self._arcs[(arc["out_pin"], arc["related_pin"])] = arc
        self._constraints = {}  # (in_pin, related_pin, timing_type) -> entry dict
        for c in cell_json.get("constraints", []):
            self._constraints[(c["in_pin"], c["related_pin"], c["timing_type"])] = c
        self._clock_pins = {p for p, v in self.input_pins.items() if v.get("is_clock")}

    def is_clock_pin(self, pin):
        return pin in self._clock_pins

    def clock_pin(self):
        return next(iter(self._clock_pins), None)

    def input_pin_cap(self, pin):
        v = self.input_pins.get(pin)
        return v["cap"] if v else 0.0

    def timing_sense(self, out_pin, related_pin):
        arc = self._arcs.get((out_pin, related_pin))
        return arc.get("timing_sense") if arc else None

    def table_lookup(self, out_pin, related_pin, kind, in_trans, load_cap):
        """kind in ('cell_rise','cell_fall'). Returns (delay_ns, out_transition_ns,
        violates_max_capacitance) or None if this cell has no such arc."""
        arc = self._arcs.get((out_pin, related_pin))
        if arc is None:
            return None
        tbl = arc.get(kind)
        if tbl is None:
            return None
        delay = _bilinear(tbl, in_trans, load_cap)
        trans_kind = "rise_transition" if kind == "cell_rise" else "fall_transition"
        ttbl = arc.get(trans_kind)
        trans = _bilinear(ttbl, in_trans, load_cap) if ttbl is not None else in_trans
        if self.max_transition is not None:
            trans = min(trans, self.max_transition)
        mc = self.output_pins.get(out_pin, {}).get("max_capacitance")
        violates = mc is not None and load_cap > mc
        return delay, trans, violates

    def setup_requirement(self, in_pin, related_pin, data_trans, clk_trans):
        """Worst-case (rise/fall) setup_rising/setup_falling requirement in ns
        for this (in_pin, related_pin), or 0.0 if this cell declares none
        (e.g. not the data pin, or a cell type with no setup constraint)."""
        best = None
        for (ip, rp, ttype), entry in self._constraints.items():
            if ip != in_pin or rp != related_pin or "setup" not in ttype:
                continue
            for kind in ("rise_constraint", "fall_constraint"):
                tbl = entry.get(kind)
                if tbl is None:
                    continue
                v = _bilinear(tbl, data_trans, clk_trans)
                if best is None or v > best:
                    best = v
        return best if best is not None else 0.0


def LOAD_LIBERTY(library=DEFAULT_LIBRARY, corner=DEFAULT_CORNER):
    """Returns {cell_name: CellModel} for (library, corner), cached. Raises if
    no data pack has been generated for that pair -- see
    src/liberty_data/README (generator script lives in scratchpad, not
    shipped; this repo only ships the one pack currently validated)."""
    key = (library, corner)
    if key in _liberty_cache:
        return _liberty_cache[key]
    path = os.path.join(_LIBERTY_DATA_DIR, f"{library}__{corner}.json")
    if not os.path.exists(path):
        raise Exception(
            f"No liberty data pack for library={library} corner={corner} "
            f"(expected {path}). Only {DEFAULT_LIBRARY}/{DEFAULT_CORNER} ships today."
        )
    data = _json.load(open(path))
    models = {name: CellModel(name, c) for name, c in data["cells"].items()}
    _liberty_cache[key] = models
    return models


# ═══════════════════════════════════════════════════════════════════════════
# Section (b): netlist graph + rise/fall-aware static timing analysis.
#
# Operates on a yosys `write_json` netlist that has already been mapped to
# real liberty cells (dfflibmap + abc -liberty) -- this section does no
# synthesis itself, see section (c) for the yosys recipe that produces its
# input. Three fixes vs. the parked prior-session prototype
# (scratchpad/latchup_divider/local_liberty_sta.py), all measured causes of
# that prototype's pessimism on adder carry chains:
#
#  1. Rise and fall are propagated as SEPARATE arrival times per net, using
#     each arc's `timing_sense` to pick which input polarity feeds which
#     output polarity (positive_unate: rise<-rise, fall<-fall; negative_unate:
#     rise<-fall, fall<-rise). The old code took worst-of-rise/fall at every
#     hop, which double-counts on inverting chains -- real signal transitions
#     physically alternate fast/slow edges, and real STA never charges the
#     worst edge twice in a row. (non_unate arcs -- in practice only
#     sequential clk->Q here -- keep the conservative "either polarity might
#     produce either output edge" treatment, since that's what non-unate
#     actually means and no functional/value simulation is done to resolve
#     it.)
#  2. Register clk->Q is a real modeled arc (idealized clock: arrival 0,
#     DEFAULT_TRANSITION_NS slew), not an assumed-zero seed. dfxtp_1's own
#     clk->Q is 0.678 ns at light load and 2.627 ns at fanout 64 in this
#     library, and latchup's own timing.log always starts a path with
#     exactly that arc.
#  3. Register data-pin endpoints add a real setup_rising/setup_falling
#     requirement (looked up the same way as any other 2D table) instead of
#     stopping at the combinational arrival alone.
#
# Sequential-cell classification comes from the liberty pack's own
# `is_sequential` flag (any cell with an `ff` or `latch` group), not a
# hardcoded name-substring list -- this is what makes "all 57 cells, not just
# the ones this one divider happens to use" (user direction) actually pay off
# structurally: every DFF/latch/scan variant in the corner is handled
# uniformly, including ones no test design here exercises.
# ═══════════════════════════════════════════════════════════════════════════

from collections import deque as _deque


def _strip_bs(name):
    return name.lstrip("\\") if isinstance(name, str) else name


def _load_netlist_json(json_path, top=None):
    d = _json.load(open(json_path))
    if top is None:
        top = next(iter(d["modules"]))
    mod = d["modules"][top]
    cells = {_strip_bs(k): v for k, v in mod.get("cells", {}).items()}
    ports = {_strip_bs(k): v for k, v in mod.get("ports", {}).items()}
    return cells, ports


def _build_graph(cells, models):
    """bit -> (inst,pin) driver; bit -> [(inst,pin),...] non-clock sinks;
    bit -> [(inst,pin),...] clock-pin sinks (excluded from graph edges and
    from load capacitance -- a global clock net's fanout is a clock-tree
    property with its own dedicated buffering in real synthesis, not a
    data-path load; see rung 2's identical fix for the same bug in a purely
    structural fanout count last session); bit -> summed real load pF.
    """
    driver_of = {}
    sinks_of = {}
    clk_sinks_of = {}
    load_cap = {}
    n_unmapped = 0
    for inst, c in cells.items():
        ctype = c.get("type", "")
        model = models.get(ctype)
        conns = c.get("connections", {})
        if model is None:
            n_unmapped += 1
            continue
        for pin, bits in conns.items():
            is_out = pin in model.output_pins
            is_clk = model.is_clock_pin(pin)
            for b in bits:
                if not isinstance(b, int):
                    continue
                if is_out:
                    driver_of[b] = (inst, pin)
                elif is_clk:
                    clk_sinks_of.setdefault(b, []).append((inst, pin))
                else:
                    sinks_of.setdefault(b, []).append((inst, pin))
                    load_cap[b] = load_cap.get(b, 0.0) + model.input_pin_cap(pin)
    return driver_of, sinks_of, clk_sinks_of, load_cap, n_unmapped


def _build_cell_graph(cells, models, driver_of):
    """Cell-instance dependency DAG for the COMBINATIONAL portion only:
    sequential cells' inputs are endpoints (never walked through) and their
    outputs are sources (seeded directly, never a predecessor to walk into).
    """
    preds = {inst: set() for inst in cells}
    succs = {inst: set() for inst in cells}
    for inst, c in cells.items():
        model = models.get(c.get("type", ""))
        if model is None or model.is_sequential:
            continue
        conns = c.get("connections", {})
        for pin, bits in conns.items():
            if pin in model.output_pins:
                continue
            for b in bits:
                if not isinstance(b, int):
                    continue
                d = driver_of.get(b)
                if d is None:
                    continue
                drv_inst, _ = d
                drv_model = models.get(cells[drv_inst].get("type", ""))
                if drv_model is not None and drv_model.is_sequential:
                    continue
                if drv_inst != inst:
                    preds[inst].add(drv_inst)
                    succs[drv_inst].add(inst)
    return preds, succs


def _source_polarities(sense, out_pol):
    """Which input polarity/polarities can produce this output polarity."""
    if sense == "positive_unate":
        return (out_pol,)
    if sense == "negative_unate":
        return ("fall" if out_pol == "rise" else "rise",)
    return ("rise", "fall")  # non_unate / unspecified -- conservative


def run_sta(json_path, top=None, library=DEFAULT_LIBRARY, corner=DEFAULT_CORNER,
            default_trans=DEFAULT_TRANSITION_NS):
    """Real topological STA over a liberty-mapped yosys JSON netlist.
    Returns a dict: worst_period_ns, start_reg_name, end_reg_name (real
    hierarchical instance dotted-paths when the winning path starts/ends at a
    register -- None otherwise, e.g. a primary-input-sourced or
    primary-output-sunk path), n_cells, n_unmapped_cells,
    incomplete_topo (True means a combinational cycle or disconnected cell
    was found -- should never happen on real synthesized logic),
    n_max_capacitance_violations (informational: how many arcs were
    evaluated past their characterized load range this run).
    """
    models = LOAD_LIBERTY(library, corner)
    cells, ports = _load_netlist_json(json_path, top)
    driver_of, sinks_of, clk_sinks_of, load_cap, n_unmapped = _build_graph(cells, models)
    preds, succs = _build_cell_graph(cells, models, driver_of)

    indeg = {inst: len(preds[inst]) for inst in cells}
    order = []
    dq = _deque(inst for inst in cells if indeg[inst] == 0)
    while dq:
        inst = dq.popleft()
        order.append(inst)
        for s in succs[inst]:
            indeg[s] -= 1
            if indeg[s] == 0:
                dq.append(s)
    incomplete_topo = len(order) != len(cells)

    # arrival[bit] = {"rise": (t_ns, trans_ns, root_inst_or_None), "fall": (...)}
    # root_inst is the *originating register instance* (or None for a
    # primary-input-sourced signal) that this arrival ultimately traces back
    # to -- carried forward hop-by-hop so a winning endpoint can report real
    # start_reg_name/end_reg_name without a separate backtracking pass.
    arrival = {}
    all_bits = set(driver_of) | set(sinks_of) | set(clk_sinks_of)
    for b in all_bits:
        if b not in driver_of:
            arrival[b] = dict(rise=(0.0, default_trans, None), fall=(0.0, default_trans, None))

    n_violations = 0

    # Seed sequential-cell outputs via their own idealized clk-><out> arc.
    for inst, c in cells.items():
        model = models.get(c.get("type", ""))
        if model is None or not model.is_sequential:
            continue
        conns = c.get("connections", {})
        clk_pin = model.clock_pin()
        for out_pin in model.output_pins:
            bits = conns.get(out_pin, [])
            if not bits or not isinstance(bits[0], int):
                continue
            ob = bits[0]
            if clk_pin is None:
                arrival[ob] = dict(rise=(0.0, default_trans, inst), fall=(0.0, default_trans, inst))
                continue
            load = load_cap.get(ob, 0.0)
            res = {}
            for kind, pol in (("cell_rise", "rise"), ("cell_fall", "fall")):
                r = model.table_lookup(out_pin, clk_pin, kind, default_trans, load)
                if r is None:
                    res[pol] = (0.0, default_trans, inst)
                    continue
                delay, trans, violates = r
                if violates:
                    n_violations += 1
                res[pol] = (delay, trans, inst)
            arrival[ob] = res

    # Propagate through combinational cells in topological order.
    for inst in order:
        c = cells[inst]
        model = models.get(c.get("type", ""))
        if model is None or model.is_sequential:
            continue
        conns = c.get("connections", {})
        for out_pin in model.output_pins:
            out_bits = conns.get(out_pin, [])
            if not out_bits or not isinstance(out_bits[0], int):
                continue
            ob = out_bits[0]
            load = load_cap.get(ob, 0.0)
            best = dict(rise=None, fall=None)
            for in_pin in model.input_pins:
                in_bits = conns.get(in_pin, [])
                if not in_bits or not isinstance(in_bits[0], int):
                    continue
                ib = in_bits[0]
                in_state = arrival.get(ib)
                if in_state is None:
                    continue
                sense = model.timing_sense(out_pin, in_pin)
                for out_kind, out_pol in (("cell_rise", "rise"), ("cell_fall", "fall")):
                    for src_pol in _source_polarities(sense, out_pol):
                        src = in_state.get(src_pol)
                        if src is None:
                            continue
                        arr, trans, root = src
                        r = model.table_lookup(out_pin, in_pin, out_kind, trans, load)
                        if r is None:
                            continue
                        delay, out_trans, violates = r
                        cand = arr + delay
                        if best[out_pol] is None or cand > best[out_pol][0]:
                            best[out_pol] = (cand, out_trans, root)
                            if violates:
                                n_violations += 1
            if best["rise"] is None and best["fall"] is None:
                continue
            if best["rise"] is None:
                best["rise"] = best["fall"]
            if best["fall"] is None:
                best["fall"] = best["rise"]
            arrival[ob] = best

    # Endpoints: sequential-cell data-ish inputs (setup-constrained) and
    # true primary-output ports (no downstream register modeled here).
    worst_period = 0.0
    start_reg_name = None
    end_reg_name = None
    for inst, c in cells.items():
        model = models.get(c.get("type", ""))
        if model is None or not model.is_sequential:
            continue
        conns = c.get("connections", {})
        clk_pin = model.clock_pin()
        for in_pin in model.input_pins:
            if in_pin == clk_pin:
                continue
            bits = conns.get(in_pin, [])
            if not bits or not isinstance(bits[0], int):
                continue
            ib = bits[0]
            st = arrival.get(ib)
            if st is None:
                continue
            r_arr, r_trans, r_root = st["rise"]
            f_arr, f_trans, f_root = st["fall"]
            if r_arr >= f_arr:
                data_arr, data_trans, root = r_arr, r_trans, r_root
            else:
                data_arr, data_trans, root = f_arr, f_trans, f_root
            setup = model.setup_requirement(in_pin, clk_pin, data_trans, default_trans) if clk_pin else 0.0
            total = data_arr + setup
            if total > worst_period:
                worst_period = total
                start_reg_name = root
                end_reg_name = inst

    for pname, p in ports.items():
        if p.get("direction") != "output":
            continue
        for b in p.get("bits", []):
            if not isinstance(b, int):
                continue
            st = arrival.get(b)
            if st is None:
                continue
            cand = max(st["rise"][0], st["fall"][0])
            root = st["rise"][2] if st["rise"][0] >= st["fall"][0] else st["fall"][2]
            if cand > worst_period:
                worst_period = cand
                start_reg_name = root
                end_reg_name = None  # a top-level output port, not a register

    return dict(
        worst_period_ns=worst_period,
        start_reg_name=start_reg_name,
        end_reg_name=end_reg_name,
        n_cells=len(cells),
        n_unmapped_cells=n_unmapped,
        incomplete_topo=incomplete_topo,
        n_max_capacitance_violations=n_violations,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Section (c): the SYN_TOOL surface SYN.py actually calls.
#
# Modelled directly on src/PYRTL.py, the smallest working example of the
# contract SYN.py requires (see docs/DEVICE_MODELS_DESIGN.md for the full
# interface list). Selected via PART("sky130...") or --syn_tool sky130 (see
# SYN.PART_SET_TOOL / src/pipelinec) -- never the part-less default, so every
# existing PyRTL-estimated design is completely unaffected by this section
# existing at all.
#
# Deliberately imports SYN/VHDL/OPEN_TOOLS/C_TO_LOGIC *inside* these
# functions rather than at module top, unlike PYRTL.py -- so that sections
# (a) and (b) above stay importable with zero PipelineC dependency (stdlib
# only), which is what let V6 validate them directly against latchup's own
# exported netlists before any of this section existed.
#
# Unlike PyRTL's per-leaf-isolated `SYN_AND_REPORT_TIMING`, whole-design
# `SYN_AND_REPORT_TIMING_MULTIMAIN` here maps and STAs the ENTIRE design at
# once -- that's what lets cross-instance net sharing (the documented cliff
# mechanism) show up at all, since it can only exist in a netlist where more
# than one leaf's logic is visible simultaneously.
# ═══════════════════════════════════════════════════════════════════════════

# Which liberty library/corner every synth + STA call in this process uses.
# Settable like PYRTL.TECH_IN_NM/FF_OVERHEAD; joins the path_delay_cache key
# (SYN.GET_PATH_DELAY_CACHE_DIR) so a change here can never silently reuse a
# stale leaf delay measured under a different corner.
SELECTED_LIBRARY = DEFAULT_LIBRARY
SELECTED_CORNER = DEFAULT_CORNER

# Bump whenever run_sta()'s algorithm OR the synth recipe (ABC_EXTRA_ARGS
# below) changes in a way that could change a previously-cached leaf delay's
# value -- joins the path_delay_cache key (SYN.GET_PATH_DELAY_CACHE_DIR)
# alongside library/corner specifically so a change can never silently replay
# a stale pre-change delay.
MODEL_VERSION = 2

# Extra flags passed to yosys' `abc` pass (see _run_synth_and_sta). Measured
# (Phase 3.9 of the plan, not guessed): the plain `abc -liberty` invocation
# uses yosys' modern default script (ending in `&nf {D}`, a network-flow
# area-recovery mapper) which, on this design, chose sky130_fd_sc_hvl__mux2_1
# for ~1000 instances that latchup's real netlist has ZERO of -- confirmed
# via direct comparison of the real synth.v cell histogram, and confirmed
# NOT fixable by supplying `-D <ps>` delay targets to that script (swept
# 500-32000ps, zero effect on the output, bit-identical every time). `-fast`
# switches to the older, classic `map {D}` technology mapper, which matches
# latchup's real mapping far better with no other changes: at N=32,
# mux2_1 1056->0 (exact), predicted period error +33.6%->-1.6%; at N=1,
# error +68.8%->-6.5%. Adding a -D target back on top of -fast made it
# WORSE (-18.9%), so this is deliberately just the bare flag.
ABC_EXTRA_ARGS = "-fast"

# Real per-cell synthesis (dfflibmap/abc costing) needs the actual, full
# liberty file -- unlike sections (a)/(b), which only ever read the small
# committed JSON pack. This is a genuine external dependency, the same way
# VIVADO.py/QUARTUS.py depend on a real tool install; IS_INSTALLED() reports
# it missing rather than raising, same pattern as every other SYN_TOOL here.
# Override by setting this directly before synthesis, or via the
# PIPELINEC_SKY130_LIB_PATH environment variable, if it isn't found in a
# standard volare install location.
LIBERTY_RAW_LIB_PATH = None
_VOLARE_GLOB = os.path.expanduser(
    "~/.volare/volare/{library_family}/versions/*/{library_family}A/libs.ref/{library}/lib/{library}__{corner}.lib"
)


def _library_family(library):
    # "sky130_fd_sc_hvl" -> "sky130" -- the volare PDK family name, one
    # directory level above where per-library .lib files live.
    return library.split("_")[0]


def _find_raw_liberty_lib(library=None, corner=None):
    import glob

    library = library or SELECTED_LIBRARY
    corner = corner or SELECTED_CORNER
    if LIBERTY_RAW_LIB_PATH is not None and os.path.exists(LIBERTY_RAW_LIB_PATH):
        return LIBERTY_RAW_LIB_PATH
    env_path = os.environ.get("PIPELINEC_SKY130_LIB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    pattern = _VOLARE_GLOB.format(library_family=_library_family(library), library=library, corner=corner)
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def IS_INSTALLED():
    # C_TO_LOGIC must be imported before OPEN_TOOLS -- OPEN_TOOLS's own
    # import chain (OPEN_TOOLS -> C_TO_LOGIC -> SW_LIB -> SYN -> CC_TOOLS ->
    # VHDL -> CXXRTL -> SIM -> VERILATOR) circles back to read
    # OPEN_TOOLS.OSS_CAD_SUITE_PATH before OPEN_TOOLS itself has finished
    # defining it, if OPEN_TOOLS is the very first of these modules loaded
    # in the process (pre-existing repo-wide import-order fragility, not
    # specific to this file -- PYRTL.py avoids it the same way).
    import C_TO_LOGIC  # noqa: F401
    import OPEN_TOOLS

    if OPEN_TOOLS.YOSYS_BIN_PATH is None or OPEN_TOOLS.GHDL_PREFIX is None:
        return False
    try:
        LOAD_LIBERTY(SELECTED_LIBRARY, SELECTED_CORNER)
    except Exception:
        return False
    if _find_raw_liberty_lib() is None:
        return False
    return True


class PathReport:
    """Parsed from our own text log format (below) -- either freshly written
    this run, or read back from a cached log file, matching the pattern
    every other SYN_TOOL in this codebase uses for the
    `use_existing_log_file` fast path."""

    def __init__(self, path_report_text):
        self.path_delay_ns = None
        self.source_ns_per_clock = None
        self.path_group = "clk"
        self.netlist_resources = set()
        self.start_reg_name = None
        self.end_reg_name = None

        def _val(line, tok):
            return line.split(tok, 1)[1].strip()

        for line in path_report_text.split("\n"):
            if "Worst period (ns):" in line:
                self.path_delay_ns = float(_val(line, "Worst period (ns):"))
            elif "Start reg:" in line:
                v = _val(line, "Start reg:")
                self.start_reg_name = None if v == "None" else v
            elif "End reg:" in line:
                v = _val(line, "End reg:")
                self.end_reg_name = None if v == "None" else v


class ParsedTimingReport:
    def __init__(self, log_text):
        self.orig_text = log_text
        self.path_reports = {}
        if "Worst period (ns):" not in log_text:
            return  # a failed/incomplete run's raw log -- SYN.py checks len(path_reports)==0 and prints orig_text
        path_report = PathReport(log_text)
        self.path_reports[path_report.path_group] = path_report


def _write_sta_log(log_path, sta_result, library, corner):
    period_ns = sta_result["worst_period_ns"]
    fmax_mhz = (1000.0 / period_ns) if period_ns else 0.0
    lines = [
        "DEVICE_MODELS liberty STA report",
        f"Library: {library}",
        f"Corner: {corner}",
        f"Worst period (ns): {period_ns:.6f}",
        f"Fmax (MHz): {fmax_mhz:.6f}",
        f"Start reg: {sta_result['start_reg_name']}",
        f"End reg: {sta_result['end_reg_name']}",
        f"N cells: {sta_result['n_cells']}",
        f"N unmapped cells: {sta_result['n_unmapped_cells']}",
        f"N max_capacitance violations: {sta_result['n_max_capacitance_violations']}",
        f"Incomplete topo: {sta_result['incomplete_topo']}",
    ]
    with open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _run_synth_and_sta(vhdl_files_texts, top_entity_name, work_dir, log_path):
    """Real (no -flatten) synth + liberty dfflibmap/abc mapping, then a
    purely-structural post-abc `flatten` so the STA graph is one connected
    component without altering which gates abc chose (V2, prior session:
    this recipe reproduces latchup's own exact FF count and fanout profile).
    Returns the text to use as this run's cached log.
    """
    import C_TO_LOGIC
    import OPEN_TOOLS

    lib_path = _find_raw_liberty_lib()
    if lib_path is None:
        raise Exception(
            f"No sky130 liberty file found for library={SELECTED_LIBRARY} corner={SELECTED_CORNER}. "
            f"Install via volare, or set DEVICE_MODELS.LIBERTY_RAW_LIB_PATH / "
            f"the PIPELINEC_SKY130_LIB_PATH env var."
        )

    # Absolute so write_json's target and the bash script's `cwd=` agree
    # regardless of the caller's own working directory (matches the
    # already-validated prior-session prototype, local_liberty_sta.py).
    work_dir = os.path.abspath(work_dir)
    os.makedirs(work_dir, exist_ok=True)
    json_path = os.path.join(work_dir, top_entity_name + "_liberty.json")
    synth_log_path = os.path.join(work_dir, top_entity_name + "_synth.log")
    m_ghdl = "" if OPEN_TOOLS.GHDL_PLUGIN_BUILT_IN else "-m ghdl "
    script = (
        f"ghdl --std=08 {vhdl_files_texts} -e {top_entity_name}; "
        f"synth -top {top_entity_name}; "
        f"dfflibmap -liberty {lib_path}; "
        f"abc -liberty {lib_path} {ABC_EXTRA_ARGS}; "
        f"flatten; "
        f"write_json {json_path}"
    )
    sh_path = os.path.join(work_dir, top_entity_name + "_syn.sh")
    with open(sh_path, "w") as f:
        f.write(
            "#!/usr/bin/env bash\n"
            f'export GHDL_PREFIX="{OPEN_TOOLS.GHDL_PREFIX}"\n'
            f"{OPEN_TOOLS.YOSYS_BIN_PATH}/yosys {m_ghdl}-p '{script}' &>> {os.path.basename(synth_log_path)}\n"
        )
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT("bash " + os.path.basename(sh_path), cwd=work_dir)

    synth_log_text = open(synth_log_path).read() if os.path.exists(synth_log_path) else ""
    if not os.path.exists(json_path):
        _write_sta_log(log_path, dict(worst_period_ns=0.0, start_reg_name=None, end_reg_name=None,
                                       n_cells=0, n_unmapped_cells=0, n_max_capacitance_violations=0,
                                       incomplete_topo=False), SELECTED_LIBRARY, SELECTED_CORNER)
        return synth_log_text + "\n[DEVICE_MODELS] synth/mapping FAILED, no JSON netlist produced\n"

    sta_result = run_sta(json_path, top=top_entity_name, library=SELECTED_LIBRARY, corner=SELECTED_CORNER)
    _write_sta_log(log_path, sta_result, SELECTED_LIBRARY, SELECTED_CORNER)
    return synth_log_text + "\n" + open(log_path).read()


def SYN_AND_REPORT_TIMING(
    inst_name,
    Logic,
    parser_state,
    TimingParamsLookupTable,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
    is_final_top=False,
):
    import SYN

    multimain_timing_params = SYN.MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
    return SYN_AND_REPORT_TIMING_NEW(
        parser_state,
        multimain_timing_params,
        inst_name,
        total_latency,
        hash_ext,
        use_existing_log_file,
    )


def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
    return SYN_AND_REPORT_TIMING_NEW(parser_state, multimain_timing_params)


def SYN_AND_REPORT_TIMING_NEW(
    parser_state,
    multimain_timing_params,
    inst_name=None,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
):
    import SYN
    import VHDL

    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]
        timing_params = multimain_timing_params.TimingParamsLookupTable[inst_name]
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)
        if hash_ext is None:
            hash_ext = timing_params.GET_HASH_EXT(multimain_timing_params.TimingParamsLookupTable, parser_state)
        if total_latency is None:
            total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, multimain_timing_params.TimingParamsLookupTable)
        entity_file_ext = "_" + str(total_latency) + "CLK" + hash_ext
        log_file_name = "device_models" + entity_file_ext + ".log"
    else:
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        log_file_name = "device_models" + hash_ext + ".log"

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    log_path = output_directory + "/" + log_file_name

    if os.path.exists(log_path) and use_existing_log_file:
        print("Reading log", log_path)
        log_text = open(log_path).read()
    else:
        if inst_name:
            VHDL.WRITE_LOGIC_ENTITY(inst_name, Logic, output_directory, parser_state, multimain_timing_params.TimingParamsLookupTable)
            VHDL.WRITE_LOGIC_TOP(inst_name, Logic, output_directory, parser_state, multimain_timing_params.TimingParamsLookupTable)
        else:
            VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)

        # Written for parity with every other SYN_TOOL (constraints file on
        # disk for inspection); this tool's own delay computation never
        # consumes clk_to_mhz itself, same as PYRTL.py.
        SYN.WRITE_CLK_CONSTRAINTS_FILE(multimain_timing_params, parser_state, inst_name)
        SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(parser_state, inst_name)

        vhdl_files_texts, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
            multimain_timing_params, parser_state, inst_name
        )

        if not IS_INSTALLED():
            raise Exception("DEVICE_MODELS (sky130 liberty STA) not installed/available -- see IS_INSTALLED()")

        print("Running:", log_path, flush=True)
        log_text = _run_synth_and_sta(vhdl_files_texts, top_entity_name, output_directory, log_path)

    return ParsedTimingReport(log_text)
