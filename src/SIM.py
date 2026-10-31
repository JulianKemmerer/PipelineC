import os
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
BUILT_HARDWARE_VERSION = 1
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
    """{kind: {canonical_key: value}}: the .latency value the final
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
                built_hardware_from=out_dir,
                design_params=record["design_params"],
                unbuilt_latency_reads=record.get("unbuilt_latency_reads"),
            )
        except pypeline.BuiltHardwareError as e:
            sys.exit(f"ERROR: {e}")
        finally:
            pypeline.SET_BUILT_HARDWARE_SOURCE(None)
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
