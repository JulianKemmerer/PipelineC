import os
import re
import shutil
import sys

import COCOTB
import CXXRTL
import EDAPLAY
import MODELSIM
import pypeline_sim
import SYN
import AUTO_PIPELINE
import LOGIC
import AUTO_MULTI_CYCLE
import VERILATOR
import VHDL

# Default simulation tool is free online edaplayground
SIM_TOOL = EDAPLAY


def SET_SIM_TOOL(cmd_line_args, source_file=None):
    global SIM_TOOL
    if cmd_line_args.cocotb:
        SIM_TOOL = COCOTB
    elif cmd_line_args.edaplay:
        SIM_TOOL = EDAPLAY
    elif cmd_line_args.cxxrtl:
        SIM_TOOL = CXXRTL
    elif cmd_line_args.verilator:
        SIM_TOOL = VERILATOR
    elif cmd_line_args.modelsim:
        SIM_TOOL = MODELSIM
    elif source_file is not None and source_file.endswith(".py"):
        # No simulator explicitly requested for a Pypeline (.py) design --
        # default to the built-in native Python simulator instead of
        # edaplayground.com.
        SIM_TOOL = pypeline_sim


def NATIVE_SIM_SKIPS_BUILD(args) -> bool:
    """True when a comb-only native (.py) Pypeline simulation run can go straight
    against the design's Python source -- no VHDL elaboration or synthesis needed.
    If SET_SIM_TOOL selected the native simulator (explicit --native or no other
    simulator requested) and comb simulation was requested, the caller should run the
    sim now and skip straight to done. A non---comb native --sim run instead falls
    through to the full build (sweep + AUTO_PIPELINE pin-and-confirm), and the sim
    launches at the end with the discovered latencies emulated -- the same
    no---comb-means-pipelined rule the VHDL simulators follow."""
    return (
        SIM_TOOL is pypeline_sim
        and (args.sim or args.sim_comb)
        and (args.comb or args.no_synth)
    )


def SIM_AT_COMB_STAGE(args) -> bool:
    """True when --comb build's optional sim should run: explicit --sim_comb, or a
    native-sim --sim run that got degraded to comb (e.g. no synth tool installed)."""
    return args.sim_comb or (SIM_TOOL is pypeline_sim and args.sim)


def DO_COMB_STAGE_SIM(parser_state, args, comb_timing_params, source_file):
    """A --comb build's optional simulation, right after its final files: a
    good point to check basic single cycle/comb logic before pipelining with
    synth tools (SIM_AT_COMB_STAGE). A native non---comb --sim run degraded to
    comb by the no-synth-tool fallback also sims here, with zero latency (its
    warning already printed). The native simulator gets no timing params (zero
    MAIN latencies; a fixed latency= call site keeps its own .latency delay
    line); every other simulator gets comb_timing_params."""
    DO_OPTIONAL_SIM(
        SIM_AT_COMB_STAGE(args),
        parser_state,
        args,
        multimain_timing_params=(
            None if SIM_TOOL is pypeline_sim else comb_timing_params
        ),
        source_file=source_file,
    )


def DO_OPTIONAL_SIM(
    do_sim, parser_state, args, multimain_timing_params=None, source_file=None
):
    # The native sim runs a Pypeline design's @initial/@final(sim) hooks inside
    # its own run loop (pypeline_sim.run_sim); every other simulator is an
    # external tool run here, so its hooks wrap that run.
    pypeline = sys.modules.get("pypeline")
    if (
        do_sim
        and SIM_TOOL is not pypeline_sim
        and pypeline is not None
        and pypeline._hook_registry
    ):
        pending_exc = None
        try:
            pypeline.RUN_INITIAL_HOOKS("sim")
            _DO_OPTIONAL_SIM(
                do_sim, parser_state, args, multimain_timing_params, source_file
            )
        except BaseException as e:
            pending_exc = e
            raise
        finally:
            pypeline.RUN_FINAL_HOOKS("sim", pending_exc=pending_exc)
    else:
        _DO_OPTIONAL_SIM(
            do_sim, parser_state, args, multimain_timing_params, source_file
        )


def _DO_OPTIONAL_SIM(
    do_sim, parser_state, args, multimain_timing_params=None, source_file=None
):
    if SIM_TOOL is COCOTB:
        if do_sim:
            COCOTB.DO_SIM(multimain_timing_params, parser_state, args)
    elif SIM_TOOL is EDAPLAY:
        if do_sim:
            EDAPLAY.SETUP_EDAPLAY(0)
    elif SIM_TOOL is MODELSIM:
        MODELSIM.DO_OPTIONAL_DEBUG(do_sim, 0)
    elif SIM_TOOL is CXXRTL:
        if do_sim:
            CXXRTL.DO_SIM(0, parser_state)
    elif SIM_TOOL is VERILATOR:
        if do_sim:
            VERILATOR.DO_SIM(multimain_timing_params, parser_state, args)
    elif SIM_TOOL is pypeline_sim:
        if do_sim:
            hardware = {}
            if parser_state is not None:
                hardware = NATIVE_SIM_HARDWARE(parser_state, multimain_timing_params)
                # Fail loudly (rather than silently mis-model) if the design
                # uses a pipelined-native-sim construct the emulation can't
                # represent accurately -- see CHECK_PIPELINED_NATIVE_SIM_SUPPORTED.
                CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(
                    parser_state,
                    hardware["main_latencies"],
                    hardware["auto_pipeline_latencies"],
                )
            pypeline_sim.run_sim(
                source_file,
                args.run,
                part=getattr(args, "part", None),
                syn_tool=getattr(args, "syn_tool", None),
                wave=getattr(args, "wave", None),
                wave_signals=getattr(args, "wave_signals", ()),
                **hardware,
            )
    else:
        print("WARNING: Unknown simulation tool:", SIM_TOOL.__name__)


def NATIVE_SIM_HARDWARE(parser_state, multimain_timing_params):
    """pypeline_sim.run_sim's keyword arguments for the hardware a build made,
    so the native sim emulates the built latencies. With no final timing params
    (the comb path) only the RAM plans and installed AUTO_FSM schedules exist,
    and every MAIN latency is zero. Harvesting here (not reusing pypeline's
    cache) also covers designs whose AP .latency was never read -- the
    pin-and-confirm loop never ran for those, so the cache is still empty.
    Harvest divergences are already a fatal driver error for every non---comb
    .py build (AUTO_PIPELINE.AUTO_PIPELINE_DIVERGENCE_EXIT), so they are
    ignored here."""
    import pypeline

    pipeline_timing = None
    if multimain_timing_params is not None and any(
        parser_state.func_fixed_latency.get(logic.func_name, 0)
        for logic in parser_state.LogicInstLookupTable.values()
    ):
        # Plain placement data crosses the normal design reimport.
        # Only run_sim's reachability gate may import the evaluator.
        pipeline_timing = {
            name: (
                list(tp._slices),
                tp._has_input_regs,
                tp._has_output_regs,
                tp._exact_bit_boundaries,
                tp.logic.delay,
            )
            for name, tp in multimain_timing_params.TimingParamsLookupTable.items()
        }
    ap_latencies = None
    auto_multi_cycle_latencies = None
    if multimain_timing_params is not None:
        ap_latencies, _divergences = AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES(
            parser_state, multimain_timing_params.TimingParamsLookupTable
        )
        # The multi-cycle counts actually constrained, so AUTO_MULTI_CYCLE
        # handshakes count the same cycles as the built VHDL
        auto_multi_cycle_latencies = AUTO_MULTI_CYCLE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(
            parser_state, multimain_timing_params
        )
    return dict(
        main_latencies=GET_MAIN_FUNC_LATENCIES(parser_state, multimain_timing_params),
        auto_pipeline_latencies=ap_latencies,
        auto_pipeline_ram_plans=AUTO_PIPELINE.RAM_PLANS_FROM_STATE(parser_state),
        # The AUTO_FSM schedules the build actually used. Taken from pypeline's
        # installed cache rather than re-derived: the schedule in force is by
        # definition the one the final elaboration read, and re-scheduling
        # here could disagree with what was built.
        auto_fsm_schedules=pypeline.AUTO_FSM_SCHEDULE_CACHE() or None,
        pipeline_timing=pipeline_timing,
        auto_multi_cycle_latencies=auto_multi_cycle_latencies,
    )


# File in a build's --out_dir holding what native simulation of another top
# needs from that build (WRITE_BUILT_HARDWARE); present only once it met timing
BUILT_HARDWARE_FILE = "built_hardware.json"
# Format of BUILT_HARDWARE_FILE; a record of another version is not used
BUILT_HARDWARE_VERSION = 2
# Command-line settings that never change what a build produces (where it runs,
# how many jobs, where caches live, debug output, simulation-only options); every
# other setting, including any new one, is one of the BUILD_INPUTS
_SETTINGS_OUTSIDE_BUILD_INPUTS = frozenset(
    (
        "src_file",  # recorded as the absolute top path instead
        "out_dir",
        "jobs",
        "syn_cache",
        "syn_cache_prune",
        "rebuild",
        "list_params",
        "auto_fsm_sweep_debug",
        "sim",
        "sim_comb",
        "run",
        "cocotb",
        "makefile",
        "ghdl",
        "edaplay",
        "modelsim",
        "cxxrtl",
        "verilator",
        "main_cpp",
        "wave",
        "wave_signals",
    )
)
# Environment variables that are BUILD_INPUTS: the compiler's own knobs, by
# prefix, and the module search path a design's imports resolve through
_BUILD_ENVIRONMENT_PREFIXES = ("PIPELINEC_", "PYPELINEC_", "PYPELINE_")
_BUILD_ENVIRONMENT_NAMES = ("PYTHONPATH",)


def BUILD_INPUTS(args, src_file):
    """What a build's result depends on besides its design sources (which
    WRITE_BUILT_HARDWARE records by hash): the top, the compiler's own sources
    (SYN.COMPILER_SOURCE_HASH), every command-line setting outside
    _SETTINGS_OUTSIDE_BUILD_INPUTS, a file a setting names counting by its
    contents, and the compiler's environment knobs. Taken once, before the
    build reads anything, as the JSON form it is recorded in."""
    import hashlib
    import json
    import pypeline

    def file_identity(path):
        path = os.path.abspath(path)
        try:
            with open(path, "rb") as f:
                return [path, hashlib.sha256(f.read()).hexdigest()]
        except OSError:
            return [path, None]

    settings = {}
    for name, value in vars(args).items():
        if name in _SETTINGS_OUTSIDE_BUILD_INPUTS:
            continue
        if name == "define":
            # Order and repetition don't change the parameters
            value = pypeline.PARSE_DESIGN_PARAM_DEFINES(value)
        elif name == "latency_hints":
            value = [file_identity(path) for path in value]
        elif name == "pins" and value is not None:
            value = file_identity(value)
        settings[name] = value
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.startswith(_BUILD_ENVIRONMENT_PREFIXES)
        or name in _BUILD_ENVIRONMENT_NAMES
    }
    inputs = dict(
        compiler=SYN.COMPILER_SOURCE_HASH(),
        top=os.path.abspath(src_file),
        settings=settings,
        environment=environment,
    )
    return json.loads(json.dumps(inputs, sort_keys=True, default=str))


def _BUILD_INPUTS_DIFFERENCE(record, build_inputs):
    """What differs between a built hardware record and a run with
    build_inputs, as text for a message: the first differing input, or a
    recorded source whose contents changed. None when nothing does."""
    # A record without build inputs was written by an older compiler
    recorded = record.get("build_inputs") or {}
    if recorded.get("compiler") != build_inputs["compiler"]:
        return "the compiler's sources (src/, include/pypeline/)"
    if recorded.get("top") != build_inputs["top"]:
        return "the top"
    old, new = recorded.get("settings") or {}, build_inputs["settings"]
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            return "the -D values" if name == "define" else f"the --{name} setting"
    old, new = recorded.get("environment") or {}, build_inputs["environment"]
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            return f"the environment variable {name}"
    changed = _changed_sources(record["sources"])
    if changed:
        return changed[0]
    return None


def BUILT_HARDWARE_IS_CURRENT(build_inputs, args) -> bool:
    """Called before any build. True when this run is a plain build (no --sim,
    no --rebuild) of the top whose timing-met build --out_dir already holds,
    from equal BUILD_INPUTS and unchanged design sources: there is nothing to
    do, and the run says so. When that record differs, the run says what
    changed and the build follows (SIMULATE_BUILT_HARDWARE then removes it)."""
    if args.sim or args.rebuild or not build_inputs["top"].endswith(".py"):
        return False
    out_dir = SYN.SYN_OUTPUT_DIRECTORY
    record = _read_built_hardware(os.path.join(out_dir, BUILT_HARDWARE_FILE))
    if record is None or record["top"] != build_inputs["top"]:
        return False
    difference = _BUILD_INPUTS_DIFFERENCE(record, build_inputs)
    if difference is not None:
        print(
            f"Building again: {difference} changed since the build in {out_dir}",
            flush=True,
        )
        return False
    print(
        f"Up to date: {out_dir} holds the timing-met build of {record['top']} "
        "from these exact inputs (design sources, -D values, build settings, "
        "compiler). Nothing to do; --rebuild builds it again.",
        flush=True,
    )
    return True


def WRITE_BUILT_HARDWARE(parser_state, multimain_timing_params, src_file, build_inputs):
    """After a synthesizing build of a Pypeline design met timing: record in
    BUILT_HARDWARE_FILE everything native simulation takes from a build
    (NATIVE_SIM_HARDWARE), with the top it built, the hashes of the sources it
    read, its design parameters and its BUILD_INPUTS, so another top (a
    testbench) can be simulated on this hardware without building
    (SIMULATE_BUILT_HARDWARE), and an identical later build of this top has
    nothing to do (BUILT_HARDWARE_IS_CURRENT)."""
    if not src_file.endswith(".py"):
        return
    import dataclasses
    import pypeline
    import PY_TO_LOGIC

    hardware = NATIVE_SIM_HARDWARE(parser_state, multimain_timing_params)
    record = dict(
        version=BUILT_HARDWARE_VERSION,
        top=os.path.abspath(src_file),
        sources=PY_TO_LOGIC.DESIGN_SOURCE_HASHES(),
        design_params={
            entry["name"]: entry["value"] for entry in pypeline.DESIGN_PARAM_REPORT()
        },
        # Native simulation cannot model these uses (PIPELINED_NATIVE_SIM_PROBLEMS)
        native_sim_problems=PIPELINED_NATIVE_SIM_PROBLEMS(
            parser_state,
            hardware["main_latencies"],
            hardware["auto_pipeline_latencies"],
        ),
        main_latencies=hardware["main_latencies"],
        auto_pipeline_latencies=hardware["auto_pipeline_latencies"] or {},
        auto_multi_cycle_latencies=hardware["auto_multi_cycle_latencies"] or {},
        auto_fsm_schedules={
            key: {f: schedule.get(f) for f in pypeline.AUTO_FSM_SIM_SCHEDULE_FIELDS}
            for key, schedule in sorted((hardware["auto_fsm_schedules"] or {}).items())
        },
        auto_pipeline_ram_plans={
            key: dataclasses.asdict(plan)
            for key, plan in sorted(hardware["auto_pipeline_ram_plans"].items())
        },
        pipeline_timing=hardware["pipeline_timing"],
        # Which rate a MAIN's goal is (AUTO.GOAL_OF_MAIN): a clock's mhz, or on
        # a synthesis-only tool its syn_mhz. Results of a key used at several
        # goals are recorded per goal (pypeline.GOAL_BINDING); a simulation
        # takes those of its own clock's goal.
        goal_mode="pnr" if SYN.TOOL_DOES_PNR() else "syn",
        unbuilt_latency_reads=_unbuilt_latency_reads(
            hardware["auto_pipeline_latencies"] or {},
            hardware["auto_multi_cycle_latencies"] or {},
        ),
        build_inputs=build_inputs,
    )
    path = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, BUILT_HARDWARE_FILE)
    SYN._write_json_atomic(path, record)
    print(f"Built hardware for native simulation of other tops: {path}", flush=True)


def _unbuilt_latency_reads(auto_pipeline_latencies, auto_multi_cycle_latencies):
    """{kind: {binding: value}}: the .latency value the final
    elaboration read for each AUTO_PIPELINE / AUTO_MULTI_CYCLE it never
    instantiated (a factory's unused alternative, say). A simulation of this
    build serves the same value (pypeline._require_built). A tag read with two
    different values is left out, so such a read stays an error there."""
    import pypeline

    reads = {}
    for kind, served, built in (
        ("AUTO_PIPELINE", pypeline.AUTO_PIPELINE_SERVED_LATENCIES(), auto_pipeline_latencies),
        (
            "AUTO_MULTI_CYCLE",
            pypeline.AUTO_MULTI_CYCLE_SERVED_LATENCIES(),
            auto_multi_cycle_latencies,
        ),
    ):
        for key, values in sorted(served.items()):
            if key not in built and len(values) == 1:
                reads.setdefault(kind, {})[key] = next(iter(values))
    return reads


def _read_built_hardware(path):
    """The BUILT_HARDWARE_FILE record at path, or None."""
    import json

    try:
        with open(path) as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("version") != BUILT_HARDWARE_VERSION:
        return None
    return record


def _changed_sources(sources):
    """Paths among {path: sha256} whose current contents differ, sorted."""
    import hashlib

    changed = []
    for path, sha in sorted(sources.items()):
        try:
            with open(path, "rb") as f:
                same = hashlib.sha256(f.read()).hexdigest() == sha
        except OSError:
            same = False
        if not same:
            changed.append(path)
    return changed


def SIMULATE_BUILT_HARDWARE(args, src_file, build_inputs) -> bool:
    """Called before any build. An --out_dir belongs to the top built in it:
    a native, non---comb --sim of another .py file there (a testbench of that
    hardware) simulates the recorded hardware (BUILT_HARDWARE_FILE) with no
    elaboration, search or synthesis, and returns True. Its sources and the
    compiler (build_inputs) must be unchanged since that build, and the
    simulation refuses hardware the build never decided (pypeline_sim.run_sim
    built_hardware_from=). A --sim of the built top itself builds: the record
    keeps only the AUTO_FSM schedule fields native simulation reads
    (AUTO_FSM_SIM_SCHEDULE_FIELDS), and a design may read others when it is
    imported. Otherwise a build follows and replaces the --out_dir's contents,
    so the record goes first: it is rewritten only if that build meets
    timing."""
    import pypeline

    out_dir = SYN.SYN_OUTPUT_DIRECTORY
    path = os.path.join(out_dir, BUILT_HARDWARE_FILE)
    record = _read_built_hardware(path)
    if (
        record is not None
        and record["top"] != build_inputs["top"]
        and SIM_TOOL is pypeline_sim
        and args.sim
    ):
        top = record["top"]
        changed = _changed_sources(record["sources"])
        if changed:
            sys.exit(
                f"ERROR: --out_dir {out_dir} holds the hardware built from {top}, "
                f"but these sources changed since that build:\n  "
                + "\n  ".join(changed)
                + f"\nRebuild {top} there first, or simulate in another --out_dir."
            )
        recorded_inputs = record.get("build_inputs") or {}
        if recorded_inputs.get("compiler") != build_inputs["compiler"]:
            sys.exit(
                f"ERROR: --out_dir {out_dir} holds the hardware built from {top} "
                "by another version of the compiler (its src/ or include/pypeline/ "
                f"sources differ from this one's).\nRebuild {top} there first, or "
                "simulate in another --out_dir."
            )
        if record["native_sim_problems"]:
            sys.exit(_PIPELINED_NATIVE_SIM_ERROR(record["native_sim_problems"]))
        print(
            f"Native sim: simulating the hardware built from {top} in {out_dir} "
            "(no elaboration or synthesis)",
            flush=True,
        )
        try:
            pypeline_sim.run_sim(
                src_file,
                args.run,
                main_latencies=record["main_latencies"],
                auto_pipeline_latencies=record["auto_pipeline_latencies"],
                auto_pipeline_ram_plans={
                    key: AUTO_PIPELINE.RamPlan(**plan)
                    for key, plan in record["auto_pipeline_ram_plans"].items()
                },
                auto_fsm_schedules=record["auto_fsm_schedules"],
                pipeline_timing=record["pipeline_timing"],
                auto_multi_cycle_latencies=record["auto_multi_cycle_latencies"],
                goal_mode=record["goal_mode"],
                built_hardware_from=out_dir,
                design_params=record["design_params"],
                unbuilt_latency_reads=record.get("unbuilt_latency_reads"),
                wave=args.wave,
                wave_signals=args.wave_signals,
            )
        except pypeline.BuiltHardwareError as e:
            sys.exit(f"ERROR: {e}")
        finally:
            pypeline.SET_BUILT_HARDWARE_SOURCE(None)
            pypeline.SET_AUTO_RUN_GOAL(None)
        return True
    if os.path.exists(path):
        os.remove(path)
    return False


def GET_SIM_FILES(latency=0):
    # Get all vhd files in syn output
    vhd_files = []
    for root, dirs, filenames in os.walk(SYN.SYN_OUTPUT_DIRECTORY):
        for f in filenames:
            if f.endswith(".vhd"):
                # print "f",f
                fullpath = os.path.join(root, f)
                abs_path = os.path.abspath(fullpath)
                # print "fullpath",fullpath
                # f
                if (
                    (root == SYN.SYN_OUTPUT_DIRECTORY + "/main")
                    and f.startswith("main_")
                    and f.endswith("CLK.vhd")
                ):
                    clks = int(f.replace("main_", "").replace("CLK.vhd", ""))
                    if clks == latency:
                        print("Using top:", abs_path)
                        vhd_files.append(abs_path)
                else:
                    vhd_files.append(abs_path)

    return vhd_files


# Common info about what to generate for simulation
class SimGenInfo:
    def __init__(self):
        self.clock_name_to_mhz = None
        self.debug_input_to_vhdl_name = {}
        self.debug_output_to_vhdl_name = {}
        self.main_func_to_latency = {}
        # Top-level reset pins (Pypeline make_reset() Inputs), which a generated
        # testbench drives 1 before the first clock edge and 0 after it
        self.reset_inputs = []


def GET_SIM_GEN_INFO(parser_state, multimain_timing_params=None):
    sim_gen_info = SimGenInfo()
    # Clocks
    clock_name_to_mhz, out_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, None, True
    )
    # Which ones are not from the user internal
    for user_clk_name, clk_mhz in parser_state.clk_mhz.items():
        clk_name = "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(
            clk_mhz, parser_state.clk_group.get(user_clk_name)
        )
        # Remove assumed internally produced user clocks from dict
        clock_name_to_mhz.pop(clk_name, None)
        # If clock is external input save with new user name
        if user_clk_name in parser_state.input_wires:
            clock_name_to_mhz[user_clk_name] = clk_mhz
    sim_gen_info.clock_name_to_mhz = clock_name_to_mhz

    # Debug ports
    for output in parser_state.output_wires:
        if output.endswith("_DEBUG"):
            debug_name = output.split("_DEBUG")[0]
            sim_gen_info.debug_output_to_vhdl_name[debug_name] = output
    for input in parser_state.input_wires:
        if input.endswith("_DEBUG"):
            debug_name = input.split("_DEBUG")[0]
            sim_gen_info.debug_input_to_vhdl_name[debug_name] = input

    # Main func latencies
    sim_gen_info.main_func_to_latency = GET_MAIN_FUNC_LATENCIES(
        parser_state, multimain_timing_params
    )

    # Reset pins: the reset Inputs that are still top-level ports
    sim_gen_info.reset_inputs = sorted(
        key
        for key, decl in getattr(parser_state, "pypeline_resets", {}).items()
        if decl.kind == "Input" and key in parser_state.input_wires
    )

    return sim_gen_info


def GET_MAIN_FUNC_LATENCIES(parser_state, multimain_timing_params=None):
    """{main func hw name -> total latency in clocks} from the final timing
    params (all zeros when multimain_timing_params is None, e.g. comb)."""
    main_func_to_latency = {}
    for func in parser_state.main_mhz:
        if multimain_timing_params is not None:
            main_timing_params = multimain_timing_params.TimingParamsLookupTable[func]
            main_latency = main_timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
        else:
            main_latency = 0
        main_func_to_latency[func] = main_latency
    return main_func_to_latency


def CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(parser_state, main_latencies, ap_latencies=None):
    """Fail loudly (sys.exit) before native sim starts if a pipelined region
    uses global wires in a way the emulation cannot model, rather than
    silently producing cycle-wrong results (see pypeline_sim_DESIGN.md's
    "Pipelined native sim" Limitations, and PIPELINED_NATIVE_SIM_PROBLEMS)."""
    problems = PIPELINED_NATIVE_SIM_PROBLEMS(parser_state, main_latencies, ap_latencies)
    if problems:
        sys.exit(_PIPELINED_NATIVE_SIM_ERROR(problems))


def PIPELINED_NATIVE_SIM_PROBLEMS(parser_state, main_latencies, ap_latencies=None):
    """The global wire uses inside pipelined logic native sim cannot model,
    as messages (empty when it can model the build).

    A pipelined region is a naturally pipelined pure @MAIN (total latency > 0)
    or an AUTO_PIPELINE call site with latency > 0. Hardware aligns a global
    wire with the arguments/return of the function that uses it, at whatever
    pipeline stage that function sits. Native sim evaluates the region's whole
    body at entry and publishes its global writes with its delayed return, so
    it is exact for non-VOLATILE wires used in the region root's own body only.
    Refused here: VOLATILE wires used by the root, and any global wire used by
    a function called inside the region. pypeline._sim_region_for is the
    runtime twin of this check (it also covers plain native runs with no
    build).
    """
    import AUTO

    roots = set()
    for hw_name, latency in (main_latencies or {}).items():
        if latency > 0:
            roots.add(hw_name)
    if ap_latencies:
        for logic in parser_state.FuncLogicLookupTable.values():
            for inst, key in getattr(logic, "sub_inst_to_auto_pipeline_key", {}).items():
                if ap_latencies.get(key, 0) > 0:
                    roots.add(logic.submodule_instances[inst])
    problems = []
    for root in sorted(roots):
        logic = parser_state.FuncLogicLookupTable.get(root)
        if logic is None:
            continue
        own = {
            **logic.read_only_global_wires,
            **logic.write_only_global_wires,
        }
        volatile = sorted(
            wire
            for wire, info in own.items()
            if AUTO_PIPELINE.GLOBAL_WIRE_TIMING(info) == "volatile"
            and wire not in logic.readback_global_wires.values()
        )
        if volatile:
            problems.append(f"'{root}' uses VOLATILE global wire(s) {', '.join(volatile)}")
        for path, ent, kind, detail in AUTO.FIND_EFFECTS(
            parser_state, root, include_self=False
        ):
            if kind == "global":
                problems.append(
                    f"'{ent}' (instance {LOGIC.SUBMODULE_MARKER.join(path)} "
                    f"inside pipelined '{root}') uses global wire(s) {', '.join(detail)}"
                )
    return problems


def _PIPELINED_NATIVE_SIM_ERROR(problems):
    return (
        "ERROR: native sim cannot model these global wire uses inside "
        "pipelined logic:\n  "
        + "\n  ".join(problems)
        + "\nHardware wires a global directly to the function that uses it "
        "and aligns it with that function's own arguments/return at the "
        "pipeline stage the function is placed (VOLATILE: per consumer "
        "stage). Native sim only models non-VOLATILE global wires used "
        "directly in the body of the pipelined @MAIN or AUTO_PIPELINE-tagged "
        "function itself. Simulate the generated hardware instead "
        "(--cocotb --ghdl), or move the wire access into the pipelined "
        "function and pass values as arguments/return values. See "
        "pypeline_guide.md 'Global wires in pipelined code'."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Waveforms: --wave FILE (docs/SIM_DESIGN.md#6-waveforms)
# ─────────────────────────────────────────────────────────────────────────────

# Waveform format of each file extension --wave accepts
_WAVE_FORMATS = {".vcd": "vcd", ".fst": "fst", ".ghw": "ghw"}
# The formats native simulation writes: VCD, and FST converted from it by vcd2fst
NATIVE_WAVE_FORMATS = ("vcd", "fst")


def WAVE_FORMAT(path):
    """The waveform format --wave FILE names by its extension: "vcd", "fst" or
    "ghw". Raises ValueError for any other extension."""
    fmt = _WAVE_FORMATS.get(os.path.splitext(path)[1].lower())
    if fmt is None:
        raise ValueError(
            f"--wave {path}: name the waveform file .vcd, .fst or .ghw (its "
            f"extension picks the format)"
        )
    return fmt


def NATIVE_WAVE_PROBLEM(path):
    """Why native simulation cannot write the waveform file path, or None.
    Checked before a run starts (CHECK_WAVE_ARGS, pypeline_sim's --wave) and
    again by START_NATIVE_WAVES."""
    try:
        fmt = WAVE_FORMAT(path)
    except ValueError as e:
        return str(e)
    if fmt not in NATIVE_WAVE_FORMATS:
        return (
            f"--wave {path}: native simulation writes .vcd or .fst; .ghw is "
            f"GHDL's own format (simulate the generated VHDL with --cocotb --ghdl)"
        )
    if fmt == "fst" and shutil.which("vcd2fst") is None:
        return (
            f"--wave {path}: native simulation writes FST by converting its VCD "
            f"with GTKWave's vcd2fst, which is not on PATH: install GTKWave, or "
            f"write a .vcd"
        )
    return _WAVE_DIRECTORY_PROBLEM(path)


def _WAVE_DIRECTORY_PROBLEM(path):
    """An error when the directory of the waveform file path does not exist."""
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        return f"--wave {path}: the directory {directory} does not exist"
    return None


def CHECK_WAVE_ARGS(args):
    """Called by the driver right after SET_SIM_TOOL: exit with an error,
    before anything is built or simulated, when --wave / --wave_signals cannot
    be honored. --wave needs --sim and a simulator that writes waveforms:
    native simulation (.vcd, .fst) or cocotb + GHDL (.vcd, .fst, .ghw, set in
    the generated Makefile, so not with --makefile). --wave_signals needs
    --wave and native simulation."""
    wave, patterns = args.wave, args.wave_signals
    if wave is None:
        if patterns:
            sys.exit(
                "ERROR: --wave_signals chooses what --wave FILE records; give --wave too"
            )
        return
    if not args.sim:
        sys.exit(f"ERROR: --wave {wave} records a simulation: add --sim")
    if SIM_TOOL is pypeline_sim:
        problem = NATIVE_WAVE_PROBLEM(wave)
    elif SIM_TOOL is COCOTB and args.ghdl:
        problem = _GHDL_WAVE_PROBLEM(args)
    else:
        problem = (
            f"--wave {wave}: waveforms come from native simulation (a .py design "
            f"with no simulator flag) or from --cocotb --ghdl"
        )
    if problem is not None:
        sys.exit(f"ERROR: {problem}")


def _GHDL_WAVE_PROBLEM(args):
    """Why --cocotb --ghdl cannot write args.wave, or None."""
    if args.makefile:
        return (
            f"--wave {args.wave}: --wave sets GHDL's options in the generated "
            f"Makefile; with --makefile, set them in your Makefile's SIM_ARGS"
        )
    if args.wave_signals:
        return (
            "--wave_signals chooses native simulation's global Wires; GHDL "
            "records every signal its waveform format can hold"
        )
    try:
        WAVE_FORMAT(args.wave)
    except ValueError as e:
        return str(e)
    return _WAVE_DIRECTORY_PROBLEM(args.wave)


# Kinds of the nodes of a signal's layout: the tree a value is flattened
# through to its leaves, which are its VCD variables
_WAVE_BITS = 0  # (kind, mask): an integer of a hardware type, two's complement
_WAVE_INT = 1  # (kind,): an integer of no type, as wide as its widest value
_WAVE_ENUM = 2  # (kind, enum class): a string variable holding the member's name
_WAVE_STR = 3  # (kind,): a string variable
_WAVE_STRUCT = 4  # (kind, ((field, node), ...)): a struct scope of its fields
_WAVE_ARRAY = 5  # (kind, (node, ...)): one signal per element, name[i]
# Whitespace, which a VCD string value cannot hold
_VCD_SPACE_RE = re.compile(r"\s")


def _wave_layout_of_ctype(t):
    """The layout of a value of the Pypeline type t."""
    import pypeline

    if getattr(t, "_pypeline_is_enum", False):
        return (_WAVE_ENUM, t)
    elem = pypeline._array_elem_ctype(t)
    if elem is not None:
        return (_WAVE_ARRAY, (_wave_layout_of_ctype(elem),) * pypeline._array_len(t))
    if hasattr(t, "_fields"):
        return (
            _WAVE_STRUCT,
            tuple((f, _wave_layout_of_ctype(t.__annotations__[f])) for f in t._fields),
        )
    return (_WAVE_BITS, (1 << pypeline._leaf_bit_width(t)) - 1)


def _wave_layout_of_value(value):
    """The layout of a value given to sim_wave: a Pypeline value (an integer,
    @struct, @enum member or array) takes its type's, a list or tuple is an
    array, a str a string, and a plain int or bool an integer of no type."""
    cls = type(value)
    if isinstance(value, str):
        return (_WAVE_STR,)
    if getattr(cls, "_pypeline_is_enum", False) or (
        hasattr(cls, "_fields") and hasattr(cls, "_pypeline_ctype_name")
    ):
        return _wave_layout_of_ctype(cls)
    if isinstance(value, (list, tuple)):
        return (_WAVE_ARRAY, tuple(_wave_layout_of_value(e) for e in value))
    if isinstance(value, int):
        ctype = getattr(value, "_ctype", None)
        return (_WAVE_INT,) if ctype is None else _wave_layout_of_ctype(ctype)
    raise TypeError(
        f"a {cls.__name__} is not a value a waveform can show: give a Pypeline "
        f"value, an int, a bool, a str, or a list of them"
    )


def _wave_shape_key(value):
    """A cheap key of what a value's layout depends on: values with one key
    have one layout, so WaveRecorder compares layouts once per new key."""
    name = getattr(type(value), "_pypeline_ctype_name", None)
    if name is not None:  # an @struct value or @enum member
        return name
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return ("list", len(value), _wave_shape_key(value[0]) if value else None)
    ctype = getattr(value, "_ctype", None)  # a SimVal's type
    if ctype is None:
        return "int"
    return getattr(ctype, "_pypeline_ctype_name", None) or ctype._ctype_name


def _wave_layouts_match(a, b):
    """Whether values of layout b flatten to the variables of layout a: the
    same tree, where an integer of no type fits an integer of a type."""
    if a[0] != b[0]:
        return {a[0], b[0]} == {_WAVE_BITS, _WAVE_INT}
    if a[0] in (_WAVE_BITS, _WAVE_ENUM):
        return a[1] == b[1]
    if a[0] == _WAVE_STRUCT:
        return len(a[1]) == len(b[1]) and all(
            fa == fb and _wave_layouts_match(na, nb)
            for (fa, na), (fb, nb) in zip(a[1], b[1])
        )
    if a[0] == _WAVE_ARRAY:
        return len(a[1]) == len(b[1]) and all(map(_wave_layouts_match, a[1], b[1]))
    return True


def _wave_layout_text(node):
    """How a message names a layout."""
    kind = node[0]
    if kind == _WAVE_BITS:
        return f"a {node[1].bit_length()}-bit integer"
    if kind == _WAVE_INT:
        return "an integer of no type"
    if kind == _WAVE_ENUM:
        return f"an @enum {node[1].__name__}"
    if kind == _WAVE_STR:
        return "a str"
    if kind == _WAVE_STRUCT:
        return f"a struct of {', '.join(f for f, _n in node[1])}"
    return f"a {len(node[1])}-element array"


class _WaveShapeError(Exception):
    """A value does not fit its signal's layout."""


def _wave_flatten(node, value, out):
    """Append the leaf values of value, flattened through its layout node, to
    out: ints, and strs for string variables."""
    kind = node[0]
    if kind == _WAVE_BITS:
        out.append(int(value) & node[1])
    elif kind == _WAVE_STRUCT:
        for field, child in node[1]:
            _wave_flatten(child, getattr(value, field), out)
    elif kind == _WAVE_ARRAY:
        if len(value) != len(node[1]):
            raise _WaveShapeError(f"{len(value)} elements where it had {len(node[1])}")
        for child, elem in zip(node[1], value):
            _wave_flatten(child, elem, out)
    elif kind == _WAVE_ENUM:
        member = node[1]._value2member_map_.get(int(value))
        out.append(str(int(value)) if member is None else member.name)
    elif kind == _WAVE_INT:
        value = int(value)
        if value < 0:
            raise _WaveShapeError(
                f"the negative integer {value}, which has no type to give its "
                f"width: pass a typed value such as int8_t(x)"
            )
        out.append(value)
    else:
        out.append(value if isinstance(value, str) else str(value))


def _vcd_code(n):
    """The VCD identifier code of the n-th variable: base 94 in '!'..'~'."""
    code = ""
    while True:
        n, digit = divmod(n, 94)
        code += chr(33 + digit)
        if n == 0:
            return code


class _WaveVar:
    """One VCD variable: a leaf of a recorded signal."""

    __slots__ = ("code", "kind", "width", "grows")

    def __init__(self, code, kind, width, grows):
        self.code = code  # its VCD identifier code
        self.kind = kind  # "wire" or "string"
        self.width = width  # its bits; a growing variable's widest value so far
        self.grows = grows  # an integer of no type, as wide as its widest value

    def line(self, value):
        """The VCD value change setting this variable to value."""
        if self.kind == "string":
            return f"s{_VCD_SPACE_RE.sub('_', value)} {self.code}\n"
        if self.grows:
            self.width = max(self.width, value.bit_length())
        elif self.width == 1:
            return f"{value}{self.code}\n"
        return f"b{value:b} {self.code}\n"


class _VcdWriter:
    """A VCD file whose variables are declared while values are written, and
    whose growing variables are only as wide as their widest value: value
    changes stream to <path>.body.tmp (those at time 0 stay in memory), and
    close() writes the header, with every scope and final width, the time-0
    values as $dumpvars, then the body. Timescale 1 ps."""

    def __init__(self, path):
        self.path = path  # the VCD file close() writes
        self._body_path = path + ".body.tmp"  # value changes after time 0
        self._body = None  # that file, opened by the first write after time 0
        # The scope tree: name -> _WaveVar, or (scope kind, {name: ...}) for a scope
        self._root = {}
        self._var_count = 0  # variables declared, numbering their codes
        self._time0 = []  # value changes at time 0, for $dumpvars
        self._time = 0  # time of the last value changes written

    def scope(self, path, kind):
        """Declare the scope at path (a tuple of names) of kind "module" or
        "struct"; missing parents are module scopes. An existing scope stays."""
        self._scope_children(path, kind)

    def var(self, path, kind, width, grows):
        """Declare and return a new _WaveVar at path."""
        children = self._scope_children(path[:-1], "module")
        if path[-1] in children:
            raise ValueError(f"two waveform signals are named '{'/'.join(path)}'")
        var = _WaveVar(_vcd_code(self._var_count), kind, width, grows)
        self._var_count += 1
        children[path[-1]] = var
        return var

    def _scope_children(self, path, kind):
        children = self._root
        for depth, name in enumerate(path):
            node = children.get(name)
            if node is None:
                node = children[name] = (
                    kind if depth == len(path) - 1 else "module",
                    {},
                )
            elif isinstance(node, _WaveVar):
                raise ValueError(
                    f"'{'/'.join(path[: depth + 1])}' cannot be both a waveform "
                    f"signal and a scope of signals"
                )
            children = node[1]
        return children

    def write(self, time, text):
        """Write value changes (VCD lines) at time, never before the last."""
        if time == 0:
            self._time0.append(text)
            return
        if self._body is None:
            self._body = open(self._body_path, "w")
        if time != self._time:
            self._body.write(f"#{time}\n")
            self._time = time
        self._body.write(text)

    def close(self, end_time):
        """Write the VCD file, its last values lasting until end_time."""
        if self._body is not None:
            self._body.close()
        with open(self.path, "w") as out:
            out.write("$version PypelineC native simulation $end\n")
            out.write("$timescale 1ps $end\n")
            self._write_scopes(out, self._root)
            out.write("$enddefinitions $end\n#0\n$dumpvars\n")
            out.writelines(self._time0)
            out.write("$end\n")
            if self._body is not None:
                with open(self._body_path) as body:
                    shutil.copyfileobj(body, out)
                os.remove(self._body_path)
            if end_time > self._time:
                out.write(f"#{end_time}\n")

    def _write_scopes(self, out, children):
        for name, node in children.items():
            if not isinstance(node, _WaveVar):
                out.write(f"$scope {node[0]} {name} $end\n")
                self._write_scopes(out, node[1])
                out.write("$upscope $end\n")
            elif node.kind == "string":
                out.write(f"$var string 1 {node.code} {name} $end\n")
            elif node.width == 1:
                out.write(f"$var wire 1 {node.code} {name} $end\n")
            else:
                out.write(
                    f"$var wire {node.width} {node.code} {name} [{node.width - 1}:0] $end\n"
                )


class _WaveSignal:
    """One recorded value: a port, a selected global Wire, a @MAIN's return
    or a sim_wave tap."""

    __slots__ = ("layout", "keys", "vars", "last")

    def __init__(self, layout, variables):
        self.layout = layout  # its layout tree, fixed when it is declared
        self.keys = set()  # _wave_shape_key of the values known to fit the layout
        self.vars = variables  # its leaves' _WaveVars, in flattening order
        self.last = None  # the leaf values last written


class WaveRecorder:
    """The waveform of one native simulation run: made and installed as
    pypeline's sim_wave recorder by START_NATIVE_WAVES, fed by pypeline_sim
    each cycle (main_return, end_cycle) and by sim_wave (tap), closed by
    STOP_NATIVE_WAVES.

    A signal's path is a tuple of names below the top scope (the top-level
    entity's name). Its layout comes from its type or its first value; a value
    is flattened to a tuple of leaf values when it is sampled, and end_cycle
    writes the leaves that changed at the cycle's time."""

    def __init__(self, path, top, clock_name, period):
        self.path = path  # the waveform file: .vcd, or .fst converted from a VCD
        self._fst = WAVE_FORMAT(path) == "fst"
        self._writer = _VcdWriter(path + ".vcd" if self._fst else path)
        self._top = top  # name of the top scope, the top-level entity
        self._period = period  # one clock period, in ps
        self._signals = {}  # signal path -> _WaveSignal
        self._pending = {}  # signal path -> its leaf values sampled this cycle
        self._tap_paths = {}  # (tap name, @MAIN wrapper or None) -> signal path
        self._wires = []  # (signal path, _sim_wire_state key), sampled every cycle
        self._returns = {}  # @MAIN wrapper -> the signal path of its return port
        self._noted = set()  # signal paths already noted as sampled twice in a cycle
        self._cycles = 0  # cycles written
        self._clock = self._writer.var((top, clock_name), "wire", 1, False)

    def add_wires(self, design_wires, patterns):
        """Declare the top-level ports (every Input and Output, by its port
        name) and the global Wires whose path below the top scope,
        <module>/<wire> (<wire> for a Wire of the top-level file), matches one
        of the fnmatch patterns."""
        import fnmatch

        wire_info, _insts = design_wires
        matched = set()
        for key, ctype in wire_info:
            module, name = key.rsplit(".", 1)
            if key in design_wires.ports or module == pypeline_sim.DESIGN_MODULE_NAME:
                names = (name,)
            else:
                names = (module.replace(".", "_"), name)
            if key not in design_wires.ports:
                hits = [p for p in patterns if fnmatch.fnmatchcase("/".join(names), p)]
                if not hits:
                    continue
                matched.update(hits)
            path = (self._top,) + names
            self._declare(path, _wave_layout_of_ctype(ctype))
            self._wires.append((path, key))
        for pattern in patterns:
            if pattern not in matched:
                print(f"WARNING: --wave_signals {pattern!r} matches no global Wire")

    def add_main_returns(self, mains):
        """Declare the return port <main>_return_output of each @MAIN that
        returns a value, except pipelined ones: native simulation computes
        their return at stage 0, cycles before the hardware's port shows it."""
        import inspect
        import pypeline

        pipelined = []
        for fn in mains:
            return_t = inspect.unwrap(fn).__annotations__.get("return")
            if return_t is None:
                continue
            name = fn._pypeline_main.name
            if fn in pypeline._sim_pipelined_main_info:
                pipelined.append(name)
                continue
            path = (self._top, f"{name}_return_output")
            self._declare(path, _wave_layout_of_ctype(return_t))
            self._returns[fn] = path
        if pipelined:
            print(
                f"NOTE: the waveform leaves out the return ports of pipelined "
                f"@MAIN {', '.join(sorted(pipelined))}: native simulation "
                f"computes them at stage 0, not at the cycle the hardware's port "
                f"shows them"
            )

    def _declare(self, path, layout):
        variables = []
        self._declare_node(path, layout, variables)
        signal = self._signals[path] = _WaveSignal(layout, variables)
        return signal

    def _declare_node(self, path, node, variables):
        kind = node[0]
        if kind == _WAVE_STRUCT:
            self._writer.scope(path, "struct")
            for field, child in node[1]:
                self._declare_node(path + (field,), child, variables)
        elif kind == _WAVE_ARRAY:
            for i, child in enumerate(node[1]):
                self._declare_node(path[:-1] + (f"{path[-1]}[{i}]",), child, variables)
        elif kind == _WAVE_BITS:
            width = node[1].bit_length()
            variables.append(self._writer.var(path, "wire", width, False))
        elif kind == _WAVE_INT:
            variables.append(self._writer.var(path, "wire", 1, True))
        else:
            variables.append(self._writer.var(path, "string", 1, False))

    def tap(self, name, value, main):
        """sim_wave(name, value) in the final pass of a cycle, under @MAIN main
        (None outside one): a name starting with "/" is a path below the top
        scope, any other is below the MAIN's scope; "/" and "." separate the
        scopes of a path."""
        key = (name, main)
        path = self._tap_paths.get(key)
        if path is None:
            path = self._tap_paths[key] = self._tap_path(name, main)
        self._sample(path, value)

    def _tap_path(self, name, main):
        if not isinstance(name, str):
            raise TypeError(
                f"sim_wave(name, value): the name must be a str, got {name!r}"
            )
        names = tuple(
            _VCD_SPACE_RE.sub("_", part) for part in re.split(r"[/.]", name) if part
        )
        if not names:
            raise ValueError(f"sim_wave({name!r}, ...): the name has no signal name")
        if name.startswith("/") or main is None:
            return (self._top,) + names
        return (self._top, main._pypeline_main.name) + names

    def main_return(self, main, value):
        """The value @MAIN main returned in the final pass of a cycle."""
        path = self._returns.get(main)
        if path is not None:
            self._sample(path, value)

    def _sample(self, path, value):
        signal = self._signals.get(path)
        key = _wave_shape_key(value)
        try:
            if signal is None:
                signal = self._declare(path, _wave_layout_of_value(value))
                signal.keys.add(key)
            elif key not in signal.keys:
                layout = _wave_layout_of_value(value)
                if not _wave_layouts_match(signal.layout, layout):
                    raise _WaveShapeError(
                        f"{_wave_layout_text(layout)} where it was "
                        f"{_wave_layout_text(signal.layout)}"
                    )
                signal.keys.add(key)
            leaves = []
            _wave_flatten(signal.layout, value, leaves)
        except (_WaveShapeError, TypeError, AttributeError) as e:
            raise ValueError(
                f"waveform signal '{'/'.join(path)}' got {e}: a signal keeps the "
                f"type it started with, so give a value of another type its own name"
            ) from None
        if path in self._pending and path not in self._noted:
            self._noted.add(path)
            print(
                f"NOTE: waveform signal '{'/'.join(path)}' was sampled more than "
                f"once in a cycle; the waveform shows the last value. Give each "
                f"sim_wave call its own name to see them all."
            )
        self._pending[path] = tuple(leaves)

    def end_cycle(self, cycle):
        """After the final pass of cycle: sample the ports and selected Wires,
        then write every signal that changed at time cycle * period, the clock
        rising there (from cycle 1) and falling half a period later."""
        import pypeline

        state = pypeline._sim_wire_state
        for path, key in self._wires:
            self._sample(path, state[key])
        lines = []
        for path, leaves in self._pending.items():
            signal = self._signals[path]
            if leaves == signal.last:
                continue
            last = signal.last or (None,) * len(leaves)
            for var, new, old in zip(signal.vars, leaves, last):
                if new != old:
                    lines.append(var.line(new))
            signal.last = leaves
        self._pending.clear()
        time = cycle * self._period
        clock = self._clock.code
        lines.append(f"{1 if cycle else 0}{clock}\n")
        self._writer.write(time, "".join(lines))
        if cycle:
            self._writer.write(time + self._period // 2, f"0{clock}\n")
        self._cycles = cycle + 1

    def close(self):
        """Write the waveform file, ending after the last cycle written; an
        .fst is converted from the VCD by vcd2fst, which keeps the VCD if that
        fails."""
        import subprocess

        self._writer.close(self._cycles * self._period)
        if self._fst:
            vcd = self._writer.path
            proc = subprocess.run(
                ["vcd2fst", "-v", vcd, "-f", self.path], capture_output=True, text=True
            )
            if proc.returncode != 0:
                print(
                    f"WARNING: vcd2fst could not convert the waveform (exit "
                    f"{proc.returncode}): {proc.stderr.strip()}. The VCD is {vcd}"
                )
                return
            os.remove(vcd)
        signals = len(self._signals) + 1  # and the clock
        print(
            f"Waveform: {self.path} ({signals} signal{'s' * (signals != 1)}, "
            f"{self._cycles} cycle{'s' * (self._cycles != 1)})"
        )


def START_NATIVE_WAVES(path, patterns, mains, design_wires):
    """Start recording a native simulation's waveform to path (.vcd or .fst):
    pypeline_sim.run_sim calls this once a run's @MAINs and global wires are
    known, before its first cycle. The top scope is SYN.TOP_LEVEL_MODULE (the
    top-level entity), the clock its port name with one period per cycle
    (clk, 1 ns, when no @MAIN names a rate); patterns are the --wave_signals
    globs. Installs a WaveRecorder as pypeline's sim_wave recorder."""
    import pypeline

    problem = NATIVE_WAVE_PROBLEM(path)
    if problem is not None:
        raise ValueError(problem)
    clock = next(
        (fn._pypeline_main.clock for fn in mains if fn._pypeline_main.clock), None
    )
    recorder = WaveRecorder(
        path,
        SYN.TOP_LEVEL_MODULE or "top",
        "clk" if clock is None else clock.port_name,
        1000 if clock is None else round(1e6 / clock.mhz),
    )
    recorder.add_wires(design_wires, patterns)
    recorder.add_main_returns(mains)
    pypeline.SET_SIM_WAVE_RECORDER(recorder)


def STOP_NATIVE_WAVES():
    """Close the waveform START_NATIVE_WAVES started, however the run ended:
    it ends after the last complete cycle (a sim_finish() cycle included), so
    a failing run still leaves a valid waveform."""
    import pypeline

    recorder = pypeline._sim_wave_recorder
    pypeline.SET_SIM_WAVE_RECORDER(None)
    if recorder is not None:
        recorder.close()
