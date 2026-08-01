#!/usr/bin/env python3
"""Multi-MAIN global-wire simulation runner for pypeline designs.

Usage:
    pypeline_sim.py <design_file.py> --run <N>

Runs the pypeline design for N clock cycles, simulating all @MAIN functions
and global Wire[T]/Input[T]/Output[T] signals with delta-cycle convergence.

Each clock cycle:
  1. All MAINs are queued and run; wires that change cause dependent MAINs to
     be re-queued until a global fixed point is reached (like VHDL delta cycles).
  2. All registers commit simultaneously after convergence (mimicking clock edge).
  3. A final pass runs all MAINs with _sim_converging=False so that @sim_output
     functions fire exactly once per cycle with the correct converged values.

Global wires persist their values across cycles; registers commit at end of each.

Multi-file designs are supported: @MAIN functions and Wire[T]/Input[T]/Output[T]
declarations in imported sub-modules are discovered automatically, transitively --
including "pass-through" modules that declare no Wire[T] of their own but import
ones that do (e.g. a module whose only job is cross-module wiring between other
modules' globals).

Wire[T]/Input[T]/Output[T] sim keys are module-qualified ("<module>.<wire>"), matching
pypeline.py's _GlobalWireRewriter, so two unrelated modules declaring a same-named
Wire[T] (e.g. both calling it "key" for unrelated purposes) do not collide in
_sim_wire_state.
"""

import argparse
import copy
import importlib.util
import itertools
import sys
import os
import time
from collections import deque

# Ensure the src directory is on the path so pypeline can be imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pypeline

# Sentinel for --run all: run cycles indefinitely, relying on sim_finish() to stop
# the simulation, instead of a fixed pre-guessed cycle count.
RUN_ALL = "all"

# Safety cap for --run all so a design that never calls sim_finish() (a bug) fails
# loudly instead of hanging forever.
_RUN_ALL_SAFETY_CAP = 10_000_000


def parse_run_arg(s: str):
    """argparse type= callable for --run: accepts a positive int cycle count, or the
    literal string "all" (case-insensitive) meaning run until sim_finish() is called."""
    if s.strip().lower() == RUN_ALL:
        return RUN_ALL
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--run must be a positive integer or 'all', got {s!r}"
        )
    if n <= 0:
        raise argparse.ArgumentTypeError(f"--run must be positive, got {n}")
    return n


def run_sim(
    design_file: str,
    num_cycles,
    sim_mode: str = "strict",
    main_latencies=None,
    autopipeline_latencies=None,
    autofsm_schedules=None,
) -> None:
    """Run the native simulation.

    main_latencies / autopipeline_latencies / autofsm_schedules are passed only
    by the pipelinec driver after a non---comb build (SIM.DO_OPTIONAL_SIM):
    {main hw name -> total latency} from the final TimingParams, {AUTOPIPELINE
    canonical_key -> stage count} from the converged harvest, and {AUTOFSM
    canonical_key -> schedule} from the installed cache. They make the native
    sim emulate what was actually built -- AUTOPIPELINE call sites via
    per-call-site delay lines (AUTOPIPELINE._sim_delay_line), AUTOFSM call
    sites via a register-level model of the generated FSM (AUTOFSM._sim_fsm),
    and naturally-pipelined pure MAINs via write-side delay
    (pypeline._sim_pipelined_main_info). Plain native runs leave them all None:
    zero latency everywhere, as always.
    """
    # Apply sim mode before importing the design: @hw_func decorators read these
    # flags at decoration time, so they must be set before _import_design runs.
    if sim_mode == "strict":
        pypeline.SIM_STRICT_ARITH = True
        pypeline.SIM_RAW_INTS = False
    elif sim_mode == "loose":
        pypeline.SIM_STRICT_ARITH = False
        pypeline.SIM_RAW_INTS = False
    elif sim_mode == "raw":
        pypeline.SIM_STRICT_ARITH = False
        pypeline.SIM_RAW_INTS = True
    else:
        raise ValueError(
            f"Unknown sim_mode {sim_mode!r}; expected strict, loose, or raw"
        )
    # Install harvested AUTOPIPELINE latencies BEFORE importing the design:
    # AUTOPIPELINE objects capture ._latency at construction (import time),
    # and .latency-derived structure (e.g. make_stream_pipeline FIFO depths)
    # must elaborate identically to the VHDL build's pin-and-confirm pass.
    if autopipeline_latencies:
        pypeline.SET_AUTOPIPELINE_LATENCY_CACHE(autopipeline_latencies)
    # Same reasoning for AUTOFSM: the tag captures ._schedule/._latency at
    # construction, and .latency-derived Python sizing must match the build's.
    if autofsm_schedules:
        pypeline.SET_AUTOFSM_SCHEDULE_CACHE(autofsm_schedules)
    _evict_design_modules()
    module = _import_design(design_file)

    wire_info = _discover_wire_names(module)

    # Reset and initialise all wire and register state.
    pypeline.sim_reset()
    for name, inner_ctype in wire_info:
        pypeline._sim_wire_state[name] = pypeline.sim_zero(inner_ctype)
    pypeline._sim_wire_readers.clear()

    mains = list(pypeline._main_registry)
    if not mains:
        print("No @MAIN functions found in design — nothing to simulate.")
        return

    # Wire up write-side latency emulation for naturally-pipelined pure MAINs.
    pypeline._sim_pipelined_main_info.clear()
    if main_latencies:
        # Only reachable from the pipelinec driver flow, where PY_TO_LOGIC is
        # already imported -- pure native runs never pass main_latencies, so
        # they stay compiler-free.
        import PY_TO_LOGIC

        hw_name_to_fn = {}
        for fn in mains:
            mod = getattr(fn, "__module__", None)
            # The top design file is loaded as "pypeline_design" by both
            # PARSE_FILE and _import_design; sub-file MAINs get the module
            # prefix (dots -> underscores) exactly like elaboration does.
            prefix = None if mod in (None, "pypeline_design") else mod.replace(".", "_")
            hw_name_to_fn[PY_TO_LOGIC._hw_func_name(prefix, fn.__name__)] = fn
        for hw_name, latency in main_latencies.items():
            if latency <= 0:
                continue
            fn = hw_name_to_fn.get(hw_name)
            if fn is None:
                raise RuntimeError(
                    f"Pipelined MAIN {hw_name!r} (latency {latency}) has no "
                    f"matching @MAIN function in the native sim registry "
                    f"(known: {sorted(hw_name_to_fn)}) -- cannot emulate its "
                    f"latency."
                )
            if getattr(fn, "_pypeline_has_state", False):
                # A stateful (Reg/Feedback) MAIN is never sliced by the sweep;
                # its explicit registers already provide all of its timing in
                # native sim (any AUTOPIPELINE children inside it are delayed
                # at their own call sites). A nonzero reported latency here is
                # a build-side accounting artifact -- applying a write delay
                # on top would double-count.
                print(
                    f"Native sim: ignoring reported latency {latency} for "
                    f"stateful MAIN {hw_name!r} (stateful MAINs are "
                    f"self-timed; only pure MAINs get write-side delay "
                    f"emulation)."
                )
                continue
            pypeline._sim_pipelined_main_info[fn] = {
                "latency": latency,
                "queue": deque(),
                "collector": [],
            }

    # Activate simulation mode so @hw_func wrappers use sim bodies instead of
    # falling through to raw functions (which the elaborator relies on for its
    # exception-based hardware-function detection via _try_eval_const).
    pypeline._sim_active = True
    t0 = time.perf_counter()
    run_all = num_cycles == RUN_ALL
    cycle_iter = itertools.count() if run_all else range(num_cycles)
    finished = False
    cycles_run = 0
    for cycle in cycle_iter:
        if run_all and cycle >= _RUN_ALL_SAFETY_CAP:
            raise RuntimeError(
                f"--run all exceeded {_RUN_ALL_SAFETY_CAP} cycles without "
                f"sim_finish() ever being called -- likely a design bug (a design "
                f"that should terminate but never does), not a slow-but-working "
                f"simulation."
            )
        print("Clock: ", cycle, flush=True)
        cycles_run = cycle + 1
        try:
            _run_clock_cycle(mains, cycle)
        except pypeline.SimFinish:
            print("")
            print(f"sim_finish() called — stopping early at cycle {cycle}")
            finished = True
            break
        print("")
    if run_all and not finished:
        raise RuntimeError(
            "--run all: cycle loop ended without sim_finish() ever being called "
            "(unreachable in normal operation -- itertools.count() only stops via "
            "the safety cap above, which raises separately)."
        )
    elapsed = time.perf_counter() - t0
    print(
        f"{cycles_run} cycles in {elapsed:.3f}s"
        f"  ({elapsed / cycles_run * 1000:.2f} ms/cycle,"
        f" {cycles_run / elapsed:.1f} cycles/s)"
    )


def _run_clock_cycle(mains: list, cycle: int) -> None:
    # Apply pipelined MAINs' N-cycles-old write-sets first: the wire values
    # everyone reads this cycle are what those MAINs computed N cycles ago
    # (their outputs crossing N pipeline register stages in hardware). Values
    # are cycle-constant, and every MAIN starts queued each cycle, so
    # applying before convergence is stable. During warm-up (queue shorter
    # than the latency) nothing is applied -- wires hold their typed-zero
    # reset values, like hardware's empty pipeline.
    for info in pypeline._sim_pipelined_main_info.values():
        if len(info["queue"]) >= info["latency"]:
            pypeline._sim_apply_delayed_writes(info["queue"].popleft())
    # Reset @sim_input's once-per-cycle result cache before anything else runs
    # this cycle, so the first call anywhere (convergence loop or final pass)
    # computes fresh and every later call this cycle reuses that same result.
    pypeline._sim_input_cache.clear()
    # Buffer register writes so they all commit together after convergence.
    pypeline._sim_reg_begin_buffer()
    pypeline._sim_converging = True
    try:
        _convergence_loop(mains, cycle)
    finally:
        pypeline._sim_converging = False

    # Final pass: _sim_converging is False so @sim_output functions execute.
    # _sim_current_main is set like in the convergence loop so pipelined
    # MAINs' write diversion (and reader tracking) sees the executing MAIN.
    for main_fn in mains:
        pypeline._sim_current_main = main_fn
        try:
            pypeline.sim_call(main_fn)
        finally:
            pypeline._sim_current_main = None

    # Commit all register writes simultaneously — the simulated clock edge.
    pypeline._sim_reg_flush_buffer()

    # Push this cycle's collected pipelined-MAIN write-sets into their delay
    # queues (deepcopy: entries must not alias objects the design mutates
    # in later cycles) and start fresh collectors for the next cycle.
    for info in pypeline._sim_pipelined_main_info.values():
        info["queue"].append(copy.deepcopy(info["collector"]))
        info["collector"].clear()


def _convergence_loop(mains: list, cycle: int) -> None:
    _MAX_EXECUTIONS = 10_000  # guard against combinatorial loops

    # Start with every MAIN in the queue (first cycle, or after clock edge).
    queue: deque = deque(mains)
    queued: set = set(mains)
    total_executions = 0

    while queue:
        if total_executions >= _MAX_EXECUTIONS:
            raise RuntimeError(
                f"Cycle {cycle}: convergence failed after {_MAX_EXECUTIONS} "
                f"MAIN executions — likely a combinatorial loop.\n"
                f"Wires with tracked readers: "
                f"{list(pypeline._sim_wire_readers.keys())}"
            )

        main_fn = queue.popleft()
        queued.discard(main_fn)

        # Snapshot wire values before this MAIN runs.
        wire_snap = dict(pypeline._sim_wire_state)

        # Run the MAIN.  _sim_wire_read records reads into _sim_wire_readers
        # so we know which MAINs to re-queue when a wire changes.
        pypeline._sim_current_main = main_fn
        try:
            pypeline.sim_call(main_fn)
        finally:
            pypeline._sim_current_main = None
        total_executions += 1

        # For every wire whose value changed, re-queue dependent MAINs.
        for name, new_val in pypeline._sim_wire_state.items():
            if new_val != wire_snap.get(name):
                for reader in pypeline._sim_wire_readers.get(name, ()):
                    if reader is not main_fn and reader not in queued:
                        queue.append(reader)
                        queued.add(reader)


def _discover_wire_names(module) -> list:
    """Return (qualified_name, inner_ctype) for all Wire/Input/Output in module and
    imported sub-modules, recursively/transitively. Names are module-qualified
    ("<module>.<wire>", matching pypeline.py's _GlobalWireRewriter) so two unrelated
    modules declaring a same-named Wire[T] (e.g. both calling it "key") don't collide.
    """
    import types

    seen_ids: set = set()
    result: list = []
    result_keys: set = set()

    def _scan(mod):
        if id(mod) in seen_ids:
            return
        seen_ids.add(id(mod))
        for name, ann in getattr(mod, "__annotations__", {}).items():
            if isinstance(
                ann, (pypeline._WireType, pypeline._InputType, pypeline._OutputType)
            ):
                qualified = f"{mod.__name__}.{name}"
                if qualified not in result_keys:
                    result.append((qualified, pypeline._wire_ann_inner_ctype(ann)))
                    result_keys.add(qualified)
        for attr in vars(mod).values():
            if isinstance(attr, types.ModuleType):
                _scan(attr)

    _scan(module)
    return result


def _evict_design_modules():
    """Evict modules imported since PY_TO_LOGIC's first PARSE_FILE from
    sys.modules, so _import_design re-imports the design graph fresh in sim
    mode. Needed in the pipelinec non---comb --sim flow: elaboration imported
    the design's sub-modules with sim flags unset (decoration-time flags) and
    with an empty/older AUTOPIPELINE latency cache. Self-guarding no-op in
    every other context: pure native runs never import PY_TO_LOGIC, and the
    comb short-circuit runs before any parse (snapshot still None)."""
    ptl = sys.modules.get("PY_TO_LOGIC")
    if ptl is None or getattr(ptl, "_modules_before_first_parse", None) is None:
        return
    for mod_name in set(sys.modules) - ptl._modules_before_first_parse:
        del sys.modules[mod_name]


def _import_design(path: str):
    """Import a pypeline design file, triggering all decorator registrations."""
    # Clear any previously registered MAINs from a prior import in the same process.
    pypeline._main_registry.clear()

    abs_path = os.path.abspath(path)
    spec = importlib.util.spec_from_file_location("pypeline_design", abs_path)
    module = importlib.util.module_from_spec(spec)
    # Add the design file's directory to sys.path so its local imports work.
    design_dir = os.path.dirname(abs_path)
    if design_dir not in sys.path:
        sys.path.insert(0, design_dir)
    # Bootstrap the reusable include/pypeline library onto sys.path so designs
    # can `from stream import ...`, `from dsp.fir import ...`, etc. without
    # requiring PYTHONPATH to be set up manually.
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _include_pypeline = os.path.join(_repo_root, "include", "pypeline")
    if _include_pypeline not in sys.path:
        sys.path.insert(0, _include_pypeline)
    # Mirror PY_TO_LOGIC.PARSE_FILE's default soft-operator registration (int
    # NEGATE/compare/DIV/MOD, variable shift) so native sim executes the same
    # soft implementations hardware does for these -- structural fidelity,
    # not just golden-value correctness. Pure native runs never import
    # PY_TO_LOGIC, so this is the only place that registration happens for
    # them; the pipelinec --sim (non---comb) flow gets it from PARSE_FILE
    # too, and operators.soft de-dupes so registering it twice is harmless.
    import operators.soft as _pypeline_default_soft_ops

    _pypeline_default_soft_ops.register_sw_lib_replacements()
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate a pypeline design with global wires for N clock cycles."
    )
    parser.add_argument("design_file", help="Path to the pypeline design Python file.")
    parser.add_argument(
        "--run",
        metavar="N",
        type=parse_run_arg,
        required=True,
        help="Number of clock cycles to simulate, or 'all' to run until sim_finish() "
        "is called (subject to a safety cap).",
    )
    parser.add_argument(
        "--mode",
        choices=["strict", "loose", "raw"],
        default="strict",
        help=(
            "Simulation accuracy mode (default: strict). "
            "strict: full hardware accuracy, every arithmetic op masks to declared bit width. "
            "loose: SimVal typed objects preserved (bit-indexing works), but no bit-width masking. "
            "raw: maximum speed, plain Python ints throughout, no casting; "
            "bit-indexing on arithmetic results will not work."
        ),
    )
    args = parser.parse_args()
    run_sim(args.design_file, args.run, sim_mode=args.mode)


if __name__ == "__main__":
    main()
