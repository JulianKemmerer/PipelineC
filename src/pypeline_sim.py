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
declarations in imported sub-modules are discovered automatically.

Limitation: Wire[T] sim keys are bare attribute names (no module prefix). Two
imported sub-modules that both declare a Wire[T] with the same name would silently
share the same sim state entry. Input[T]/Output[T] are safe since the elaborator
also requires those names to be globally unique. See the plan doc for a long-term fix.
"""

import argparse
import importlib.util
import sys
import os
from collections import deque

# Ensure the src directory is on the path so pypeline can be imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pypeline


def run_sim(design_file: str, num_cycles: int) -> None:
    module = _import_design(design_file)

    wire_info = _discover_wire_names(module)

    # Reset and initialise all wire and register state.
    pypeline.sim_reset()
    for name, inner_ctype in wire_info:
        pypeline._sim_wire_state[name] = _make_sim_zero(inner_ctype)
    pypeline._sim_wire_readers.clear()

    mains = list(pypeline._main_registry)
    if not mains:
        print("No @MAIN functions found in design — nothing to simulate.")
        return

    for cycle in range(num_cycles):
        _run_clock_cycle(mains, cycle)


def _run_clock_cycle(mains: list, cycle: int) -> None:
    # Buffer register writes so they all commit together after convergence.
    pypeline._sim_reg_begin_buffer()
    pypeline._sim_converging = True
    try:
        _convergence_loop(mains, cycle)
    finally:
        pypeline._sim_converging = False

    # Final pass: _sim_converging is False so @sim_output functions execute.
    for main_fn in mains:
        pypeline.sim_call(main_fn)

    # Commit all register writes simultaneously — the simulated clock edge.
    pypeline._sim_reg_flush_buffer()


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
    """Return (name, inner_ctype) for all Wire/Input/Output in module and imported sub-modules."""
    import types

    seen_ids: set = set()
    result: list = []
    result_names: set = set()

    def _scan(mod):
        if id(mod) in seen_ids:
            return
        seen_ids.add(id(mod))
        for name, ann in getattr(mod, "__annotations__", {}).items():
            if (
                isinstance(
                    ann, (pypeline._WireType, pypeline._InputType, pypeline._OutputType)
                )
                and name not in result_names
            ):
                result.append((name, ann.inner_ctype))
                result_names.add(name)
        for attr in vars(mod).values():
            if isinstance(attr, types.ModuleType) and any(
                isinstance(
                    a, (pypeline._WireType, pypeline._InputType, pypeline._OutputType)
                )
                for a in getattr(attr, "__annotations__", {}).values()
            ):
                _scan(attr)

    _scan(module)
    return result


def _make_sim_zero(ctype):
    """Return a simulation zero-value for the given pypeline ctype.

    For struct types (NamedTuple subclasses with _fields), returns a struct instance
    with all fields recursively zeroed. For scalar types, returns plain int 0 which
    the struct @typed_new constructor will wrap in a SimVal with the correct ctype.
    """
    if hasattr(ctype, "_fields"):
        return ctype(*(_make_sim_zero(ctype.__annotations__[f]) for f in ctype._fields))
    return 0


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
        type=int,
        required=True,
        help="Number of clock cycles to simulate.",
    )
    args = parser.parse_args()
    run_sim(args.design_file, args.run)


if __name__ == "__main__":
    main()
