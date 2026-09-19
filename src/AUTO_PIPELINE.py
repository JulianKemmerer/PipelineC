"""Automatic pipelining: how a design's pipelines are represented and built.

See docs/AUTO_PIPELINE_DESIGN.md. This module owns:

- the pipeline representation: `TimingParams` (per-instance slices and IO
  register flags, total latency) and `MultiMainTimingParams`;
- the pipeline map (`GET_PIPELINE_MAP`) and slicing down the hierarchy,
  including writing the resulting VHDL entities and the pipelined VHDL
  architecture text (stages, stage registers, IO registers);
- `AUTO_PIPELINE(...)` call sites: fixed `latency=` builds, constrained
  regions (`latency=` / `start_latency=` / `max_latency=`) enforced on sweep
  plans, and the `.latency` pin-and-confirm build loop;
- auto-pipelined RAMs: synchronous BRAM register placement and bank-tree
  candidates, measured through the same throughput sweep.

The search for good slices -- iterating synthesis toward a timing goal -- is
SWEEP.py; the synthesis runs and reports themselves are SYN.py.
"""
import copy
from dataclasses import asdict, dataclass, replace
import json
import hashlib
import math
import os
import sys
from pathlib import Path

import AUTO_MULTI_CYCLE
import C_TO_LOGIC
import OPEN_TOOLS
import PYRTL
import RAW_VHDL
import SYN
import VHDL


# Max total elaborate+synthesize passes of the AUTO_PIPELINE .latency
# pin-and-confirm loop in the pipelinec driver (Pypeline designs only):
# pass 1 discovers latencies with a full sweep; pass 2 re-elaborates with the
# real values and, with the previous pipelining pinned as seeds, needs only
# one confirmation synthesis. Passes beyond 2 happen only when a
# .latency-derived design change breaks timing under the pinned pipelining
# and the fallback sweep then lands on different latencies.
AUTO_PIPELINE_MAX_LATENCY_PASSES = 3


# These are the parameters that describe how multiple pipelines are timed
class MultiMainTimingParams:
    def __init__(self):
        # Pipeline params
        self.TimingParamsLookupTable = {}
        # AUTO_MULTI_CYCLE canonical key -> multi-cycle count the throughput sweep is
        # currently constraining that path with (see MCP_EFFECTIVE_NCYCLES);
        # keys absent use the elaborated count
        self.auto_multi_cycle_ncycles = {}
        # TODO some kind of params for clock crossing

    def GET_HASH_EXT(self, parser_state):
        # Hash of each main's own hash ext, which (via
        # RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES) covers the full
        # design content: descendant func names + io regs + slices. Content
        # awareness matters here: this hash names the multimain top synthesis
        # log, and an existing log is replayed instead of re-synthesizing --
        # a slices-only hash let the AUTO_PIPELINE pass-2 confirmation run
        # replay pass 1's log despite a resized (renamed) FIFO in the design.
        top_level_str = ""
        for main_func in sorted(parser_state.main_mhz.keys()):
            timing_params = self.TimingParamsLookupTable[main_func]
            hash_ext_i = timing_params.GET_HASH_EXT(
                self.TimingParamsLookupTable, parser_state
            )
            top_level_str += hash_ext_i
        # A sweep-chosen AUTO_MULTI_CYCLE count changes only the XDC, not any entity,
        # so it must enter the hash or a same-named log from another count
        # would be replayed. Counts equal to the elaborated ones add nothing:
        # every design without a sweep-raised AUTO_MULTI_CYCLE hashes as before.
        overrides = getattr(self, "auto_multi_cycle_ncycles", None)
        if overrides:
            elaborated = AUTO_MULTI_CYCLE.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state)
            changed = sorted(
                (key, n) for key, n in overrides.items() if elaborated.get(key) != n
            )
            if changed:
                top_level_str += "_auto_multi_cycle" + repr(changed)
        s = top_level_str
        hash_ext = "_" + ((hashlib.md5(s.encode("utf-8")).hexdigest())[0:8])
        # Side-record for name_index.log's PIPELINE VARIANTS section -- see
        # the matching comment in TimingParams.BUILD_HASH_EXT.
        hash_ext_info = getattr(parser_state, "pypeline_hash_ext_info", None)
        if hash_ext_info is None:
            hash_ext_info = {}
            parser_state.pypeline_hash_ext_info = hash_ext_info
        hash_ext_info.setdefault(
            hash_ext, ("<multimain top>", sorted(parser_state.main_mhz.keys()))
        )
        return hash_ext


# These are the parameters that describe how a pipeline should be formed
class TimingParams:
    def __init__(self, inst_name, logic):
        self.logic = logic
        self.inst_name = inst_name

        # Have the current params (slices) been fixed,
        # Default to fixed if known cant be sliced
        self.params_are_fixed = False
        # Params, private _ since cached
        self._slices = []  # Unless raw vhdl (no submodules), these are only ~approximate slices
        # Optional physical bit boundaries for a raw-HDL leaf.  Ordinary
        # fractional slicing keeps this unset and therefore retains the
        # historical equal-width allocation.  Typed exact placements set it
        # explicitly so code generation, entity hashing, and diagnostics all
        # describe the same (possibly uneven) chunks.
        self._exact_bit_boundaries = None
        # ??Maybe add flag for these fixed slices provide latency, dont rebuild? unecessary?
        self._has_input_regs = False
        self._has_output_regs = False

        # Sometimes slices are between submodules,
        # This can specify where a stage is artificially started by not allowing submodules to be instantiated even if driven in an early state
        # UNUSED FOR NOW
        # self.submodule_to_start_stage = {}
        # self.submodule_to_end_stage = {}

        # Cached stuff
        self.calcd_total_latency = None
        self.hash_ext = None
        # self.timing_report_stage_range = None

    def DEEPCOPY(self):
        rv = copy.copy(self)
        rv._slices = self._slices[:]  # COPY
        rv._exact_bit_boundaries = (
            None
            if self._exact_bit_boundaries is None
            else self._exact_bit_boundaries[:]
        )
        # Logic ok to be same obj
        # All others immut right now
        return rv

    def INVALIDATE_CACHE(self):
        self.calcd_total_latency = None
        self.hash_ext = None
        # self.timing_report_stage_range = None

    def IS_EMPTY(self):
        return (
            len(self._slices) == 0
            and not self._has_input_regs
            and not self._has_output_regs
        )

    # I was dumb and used get latency all over
    # mAKE CACHED VERSION
    def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
        if self.calcd_total_latency is None:
            self.calcd_total_latency = self.CALC_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
        return self.calcd_total_latency

    def GET_PIPELINE_LOGIC_ADDED_LATENCY(self, parser_state, TimingParamsLookupTable):
        total_latency = self.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
        # Remove latency added by user
        if self.logic.func_name in parser_state.func_fixed_latency:
            fixed_latency = parser_state.func_fixed_latency[self.logic.func_name]
            if total_latency < fixed_latency:
                raise Exception(
                    f"{total_latency} latency function {self.logic.func_name} has fixed latency less? {fixed_latency}?"
                )
            total_latency = total_latency - fixed_latency
        pipeline_added_latency = total_latency
        if self._has_input_regs:
            if pipeline_added_latency == 0:
                raise Exception(
                    f"Zero latency function {self.logic.func_name} has input regs?"
                )
            pipeline_added_latency -= 1
        if self._has_output_regs:
            if pipeline_added_latency == 0:
                raise Exception(
                    "Zero latency function {self.logic.func_name} has output regs?"
                )
            pipeline_added_latency -= 1
        return pipeline_added_latency

    # Haha why uppercase everywhere ...
    def CALC_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
        # Use hard coded pipelined latency
        if self.logic.func_name in parser_state.func_fixed_latency:
            fixed_latency = parser_state.func_fixed_latency[self.logic.func_name]
            pipeline_latency = fixed_latency
        # C built in has multiple shared latencies based on where used
        elif len(self.logic.submodule_instances) <= 0:
            # Just pipeline slices
            pipeline_latency = len(self._slices)
        else:
            # If cant be sliced then latency must be zero right?
            if not self.logic.CAN_HAVE_ADDED_LATENCY(parser_state):
                if self._has_input_regs or self._has_output_regs:
                    raise Exception(
                        f"{self.logic.func_name} cannot have IO regs but has been given them!?"
                    )
                    # print("Bad io regs on non sliceable!")
                    # sys.exit(-1)
                return 0

            if TimingParamsLookupTable is None:
                print(
                    "Need TimingParamsLookupTable for non raw hdl latency",
                    self.logic.func_name,
                )
                print(0 / 0)
                sys.exit(-1)

            pipeline_map = GET_PIPELINE_MAP(
                self.inst_name, self.logic, parser_state, TimingParamsLookupTable
            )
            pipeline_latency = pipeline_map.num_stages - 1

        # Adjut latency for io regs
        latency = pipeline_latency
        if self._has_input_regs:
            latency += 1
        if self._has_output_regs:
            latency += 1

        return latency

    def RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
        self, inst_name, Logic, TimingParamsLookupTable, parser_state
    ):
        # All modules include IO reg flags
        timing_params = TimingParamsLookupTable[inst_name]
        rv = (
            timing_params._has_input_regs,
            timing_params._has_output_regs,
        )
        # Only lowest level raw VHDL modules with no submodules include slices
        if len(Logic.submodule_instances) > 0:
            # Not raw hdl, slices dont guarentee describe pipeline structure
            for submodule in sorted(
                Logic.submodule_instances
            ):  # MUST BE SORTED FOR CONSISTENT ORDER!
                sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule
                if sub_inst not in parser_state.LogicInstLookupTable:
                    print("Missing inst_name:", sub_inst)
                    print("has instances:")
                    for inst_i, logic_i in parser_state.LogicInstLookupTable.items():
                        print(inst_i)
                    print(0 / 0, flush=True)
                    sys.exit(-1)
                sub_logic = parser_state.LogicInstLookupTable[sub_inst]
                # Each child contributes its FUNC NAME alongside its subtree
                # tuple. Load-bearing, not informational: this tuple feeds
                # BUILD_HASH_EXT, whose hash names both written VHDL entity
                # files (VHDL.GET_ENTITY_NAME) and synthesis log files
                # (per-func and multimain top), and existing files short-cut
                # rewriting/re-synthesis. A rendered entity's CONTENT embeds
                # its children's entity names, and canonical func names encode
                # elaboration-time values (e.g. an AUTO_PIPELINE
                # .latency-derived FIFO depth) -- so identical slices with a
                # renamed descendant must hash differently, or stale pass-1
                # artifacts get served (the AUTO_PIPELINE pass-2 confirmation
                # replay + the shared wireguard GHDL "unit not found"
                # mixed-name failure). The module's OWN name is deliberately
                # NOT included: it already appears in every filename the hash
                # is combined with, and leaving leaf tuples unchanged keeps
                # previously cached leaf synthesis logs valid.
                rv += (
                    (
                        sub_logic.func_name,
                        self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
                            sub_inst, sub_logic, TimingParamsLookupTable, parser_state
                        ),
                    ),
                )
        else:
            # Raw HDL
            raw_slice_state = tuple(timing_params._slices)
            if timing_params._exact_bit_boundaries is not None:
                raw_slice_state = (
                    raw_slice_state,
                    ("exact_bit_boundaries", tuple(timing_params._exact_bit_boundaries)),
                )
            rv += (raw_slice_state,)

        return rv

    # Hash ext only reflect raw hdl slices (better would be raw hdl bits per stage)
    def BUILD_HASH_EXT(self, inst_name, Logic, TimingParamsLookupTable, parser_state):
        # print("BUILD_HASH_EXT",Logic.func_name, flush=True)
        io_regs_and_slices_tup = self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
            inst_name, Logic, TimingParamsLookupTable, parser_state
        )
        s = str(io_regs_and_slices_tup)
        full_hash = hashlib.md5(s.encode("utf-8")).hexdigest()
        hash_ext = (
            "_" + (full_hash[0:8])
        )  # 4 chars enough, no you dummy, lets hope 8 is
        # print(f"inst {inst_name} {full_hash} {hash_ext}")
        # Side-record what this hash_ext decodes to (func name + stage count)
        # for name_index.log's PIPELINE VARIANTS section -- generic names like
        # "decrypt_dataflow_decrypt_dataflow_0CLK_6f395802" otherwise carry no
        # decodable meaning for the hash suffix anywhere in the build's own
        # output. First writer wins (same hash_ext recomputed later is the
        # same content by construction). Lazily created so this works
        # identically for a plain C-frontend parser_state.
        hash_ext_info = getattr(parser_state, "pypeline_hash_ext_info", None)
        if hash_ext_info is None:
            hash_ext_info = {}
            parser_state.pypeline_hash_ext_info = hash_ext_info
        hash_ext_info.setdefault(hash_ext, (Logic.func_name, len(self._slices)))
        return hash_ext

    def GET_HASH_EXT(self, TimingParamsLookupTable, parser_state):
        if self.hash_ext is None:
            self.hash_ext = self.BUILD_HASH_EXT(
                self.inst_name, self.logic, TimingParamsLookupTable, parser_state
            )

        return self.hash_ext

    def ADD_SLICE(self, slice_point):
        # ADD_SLICE is the legacy fractional interface.  Mixing it with a
        # previously installed exact group would make the physical meaning
        # ambiguous, so returning to it deliberately clears exact metadata.
        if self._exact_bit_boundaries is not None:
            self._exact_bit_boundaries = None
            self.INVALIDATE_CACHE()
        if self._slices is None:
            self._slices = []
        if slice_point > 1.0:
            print("Slice > 1.0?", slice_point)
            sys.exit(-1)
            slice_point = 1.0
        if slice_point < 0.0:
            print("Slice < 0.0?", slice_point)
            print(0 / 0)
            sys.exit(-1)
            slice_point = 0.0

        if slice_point not in self._slices:
            self._slices.append(slice_point)
            self._slices = sorted(self._slices)
            self.INVALIDATE_CACHE()
        else:
            raise Exception(
                f"Slice {slice_point} exists already cant add? slices pre add: {self._slices}"
            )

        if self.calcd_total_latency is not None:
            print("WTF adding a slice and has latency cache?", self.calcd_total_latency)
            print(0 / 0)
            sys.exit(-1)

    def SET_SLICES(self, value):
        if value != self._slices or self._exact_bit_boundaries is not None:
            self._slices = value[:]
            self._exact_bit_boundaries = None
            self.INVALIDATE_CACHE()

    def SET_EXACT_BIT_BOUNDARIES(self, boundaries, bit_width):
        """Install a strictly increasing physical split for a raw-HDL leaf."""
        boundaries = [int(boundary) for boundary in boundaries]
        bit_width = int(bit_width)
        if bit_width <= 0:
            raise ValueError(f"Exact bit-boundary width must be > 0: {bit_width}")
        if (
            boundaries != sorted(set(boundaries))
            or any(boundary <= 0 or boundary >= bit_width for boundary in boundaries)
        ):
            raise ValueError(
                f"Exact bit boundaries must be unique, strictly increasing, "
                f"and inside 0..{bit_width}: {boundaries}"
            )
        slices = [boundary / float(bit_width) for boundary in boundaries]
        if (
            slices != self._slices
            or boundaries != self._exact_bit_boundaries
        ):
            self._slices = slices
            self._exact_bit_boundaries = boundaries
            self.INVALIDATE_CACHE()

    def SET_HAS_IN_REGS(self, value):
        if value != self._has_input_regs:
            self._has_input_regs = value
            self.INVALIDATE_CACHE()

    def SET_HAS_OUT_REGS(self, value):
        if value != self._has_output_regs:
            self._has_output_regs = value
            self.INVALIDATE_CACHE()

    def GET_SUBMODULE_LATENCY(
        self, submodule_inst_name, parser_state, TimingParamsLookupTable
    ):
        # Auto-pipelined submodules report themselves as zero latency like regular comb logic funcs
        sub_inst = C_TO_LOGIC.LEAF_NAME(submodule_inst_name)
        if sub_inst in self.logic.sub_inst_to_auto_pipeline_latency or sub_inst in getattr(
            self.logic, "submodule_latencies_are_self_timed", ()
        ):
            return 0
        submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
        return submodule_timing_params.GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )


def DEL_PIPELINE_CACHES():
    global _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache
    global _FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache
    # global _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache

    _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache = {}
    _FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache = {}
    # Func-name keyed maps referencing Logic objects: a re-parse (AUTO_PIPELINE
    # pass 2) rebuilds same-named funcs as fresh objects, so entries would be
    # stale (see GET_ZERO_ADDED_CLKS_PIPELINE_MAP's identity check).
    _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache.clear()


_GET_ZERO_CLK_HASH_EXT_LOOKUP_cache = {}


_GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache = {}


def GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state):
    # Cached?
    # print("GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP")
    cache_key = str(sorted(set(parser_state.LogicInstLookupTable.keys())))
    if cache_key in _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache:
        cached_lookup = _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache[cache_key]
        rv = {}
        for inst_i, params_i in cached_lookup.items():
            rv[inst_i] = params_i.DEEPCOPY()
        return rv

    # Create empty lookup
    ZeroAddedClocksTimingParamsLookupTable = {}
    for logic_inst_name in parser_state.LogicInstLookupTable:
        logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
        timing_params_i = TimingParams(logic_inst_name, logic_i)
        ZeroAddedClocksTimingParamsLookupTable[logic_inst_name] = timing_params_i

    # Calc cached params so they are in cache
    bad_fixed_latency_when_cant_slice_func_names = set()
    for logic_inst_name in parser_state.LogicInstLookupTable:
        logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
        timing_params_i = ZeroAddedClocksTimingParamsLookupTable[logic_inst_name]
        # Sanity check functions that can't be sliced arent showing up with slices/latency in them
        pipeline_added_latency = timing_params_i.GET_PIPELINE_LOGIC_ADDED_LATENCY(
            parser_state, ZeroAddedClocksTimingParamsLookupTable
        )
        if logic_i.func_name not in bad_fixed_latency_when_cant_slice_func_names:
            if (pipeline_added_latency > 0) and not logic_i.CAN_HAVE_ADDED_LATENCY(
                parser_state
            ):
                print(
                    "Error: Zero latency static stateful function",
                    logic_i.func_name,
                    "actually describes a pipeline of non-zero latency/depth. (",
                    pipeline_added_latency + 1,
                    "stages total)",
                )
                bad_fixed_latency_when_cant_slice_func_names.add(logic_i.func_name)
        # Write cache
        if logic_i.func_name in _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache:
            timing_params_i.hash_ext = _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[
                logic_i.func_name
            ]
        else:
            _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[logic_i.func_name] = (
                timing_params_i.GET_HASH_EXT(
                    ZeroAddedClocksTimingParamsLookupTable, parser_state
                )
            )
    if len(bad_fixed_latency_when_cant_slice_func_names) > 0:
        print(
            """Modify one or more of the above functions:
Remove FUNC_LATENCY pragmas specifying fixed pipeline latencies.
OR
Remove stateful static local variables to allow pipelining."""
        )
        raise Exception("Resolve the above unexpected added pipeline latency errors.")

    _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache[cache_key] = (
        ZeroAddedClocksTimingParamsLookupTable
    )
    return ZeroAddedClocksTimingParamsLookupTable


_GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache = {}


def NORMALIZE_KNOWN_ZERO_DELAY_SUBMODULE_DELAYS(logic, parser_state):
    """Make intrinsically zero-delay child timing explicit.

    Generated helpers such as CONST_REF_RD intentionally skip path-delay
    synthesis, so their ``delay`` can still be None when pipeline-map code
    begins doing arithmetic. Normalize only children that the existing
    zero-delay classifier recognizes; return the first genuinely unresolved
    child so callers retain the existing hard-error behavior for missing timing.
    """
    for sub_inst in logic.submodule_instances:
        func_name = logic.submodule_instances[sub_inst]
        sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
        if sub_func_logic.delay is None:
            if SYN.LOGIC_IS_ZERO_DELAY(
                sub_func_logic, parser_state, allow_none_delay=True
            ):
                sub_func_logic.delay = 0
            else:
                return sub_func_logic
    return None


def GET_ZERO_ADDED_CLKS_PIPELINE_MAP(inst_name, Logic, parser_state, write_files=True):
    key = Logic.func_name

    # Try cache. A same-named entry built against a DIFFERENT Logic object is
    # simply stale (an AUTO_PIPELINE pass-2 re-parse rebuilds same-named funcs
    # as fresh objects): invalidate and rebuild below. (This used to print
    # "Zero clock cache no mactho" and call sys.exit(-1) -- which a
    # surrounding bare except accidentally swallowed, making it noisy
    # dead code.)
    rv = _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache.get(key)
    if rv is not None:
        if rv.logic is Logic:
            return rv
        del _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache[key]

    unresolved_submodule = NORMALIZE_KNOWN_ZERO_DELAY_SUBMODULE_DELAYS(
        Logic, parser_state
    )
    has_delay = unresolved_submodule is None
    if unresolved_submodule is not None:
        print(Logic.func_name, "/", unresolved_submodule.func_name)
        raise Exception("Can't get zero clock pipeline map without delay?")

    # Populate table as all 0 added clks
    ZeroAddedClocksLogicInst2TimingParams = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(
        parser_state
    )

    # Get params for this logic
    # print "Logic.func_name",Logic.func_name

    # Get pipeline map
    zero_added_clks_pipeline_map = GET_PIPELINE_MAP(
        inst_name, Logic, parser_state, ZeroAddedClocksLogicInst2TimingParams
    )

    # Only cache if has delay
    # zero_added_clks_pipeline_map.logic.delay is not None and  Dont need to check self, only submodules
    if zero_added_clks_pipeline_map.zero_clk_max_delay is not None:
        _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache[key] = zero_added_clks_pipeline_map
    else:
        # Sanity?
        if has_delay:
            # Seems to early catch designs optimizing away
            raise Exception(
                f"It looks like the function {zero_added_clks_pipeline_map.logic.func_name} reduces to constants/wires in an unexpected way? Missing '#pragma FUNC_WIRES {zero_added_clks_pipeline_map.logic.func_name}' ? "
            )

    return zero_added_clks_pipeline_map


class SubmoduleLevelInfo:
    def __init__(self, level_num):
        self.level_num = level_num

        # Starts with wires driving other wires
        self.driver_driven_wire_pairs = []
        # Ends with submodule logic connections
        self.submodule_insts = []

    def IS_EMPTY(self):
        return (
            len(self.driver_driven_wire_pairs) == 0 and len(self.submodule_insts) == 0
        )


class StageInfo:
    def __init__(self, stage_num):
        self.stage_num = stage_num

        # Submodule output wires first
        self.submodule_output_ports = []
        # Then sequence of per submodule level information
        self.submodule_level_infos = []


# This started off as just code writing VHDL
# Then the logic of how the VHDL was written was highjacked for latency calculation
# Then latency calculations were highjacked for logic delay calculations
class PipelineMap:
    def __init__(self, logic):
        self.logic = logic
        # Any logic will have
        self.num_stages = 1  # Comb logic
        # New per stage info class
        self.stage_infos = []

        # Wires and submodules of const network like another pipeline stage outside pipeline
        self.const_network_stage_info = None  # StageInfo
        # Helper list of wires part of const network just used during prop processes
        self.const_network_wire_to_upstream_vars = {}

        # Read only global wires (might be volatile or not)
        self.read_only_global_network_stage_info = None
        self.read_only_global_network_wire_to_upstream_vars = {}

        # DELAY STUFF ONLY MAKES SENSE TO TALK ABOUT WHEN:
        # - 0 CLKS
        # - >0 delay submodules
        #  ITS NOT CLEAR HOW SLICES ACTUALLY DISTRIBUTE DELAY
        #  Ex. 1 ns split 2 equal clks?
        #    0.3 | 0.3 | 0.3  ?
        #    0   |  1  |  0   ?   Some raw VHDL is like this
        # Also once you are doing fractional stuff you might as well be doing delay ns
        # Doing slicing for multiple clocks shouldnt require multi clk pipeline maps anyway right?
        # HELP ME
        self.zero_clk_per_delay_submodules_map = {}  # dict[delay_offset] => [submodules,at,offset]
        self.zero_clk_submodule_start_offset = {}  # dict[submodule_inst] = start_offset  # In delay units
        self.zero_clk_submodule_end_offset = {}  # dict[submodule_inst] => end_offset # In delay units
        self.zero_clk_max_delay = None

    def __str__(self):
        rv = "Pipeline Map:\n"
        for delay in sorted(self.zero_clk_per_delay_submodules_map.keys()):
            submodules_insts = self.zero_clk_per_delay_submodules_map[delay]
            submodule_func_names = []
            for submodules_inst in submodules_insts:
                submodule_func_names.append(submodules_inst)

            rv += str(delay) + ": " + str(sorted(submodule_func_names)) + "\n"
        rv = rv.strip("\n")
        return rv

    def write_png(self, out_dir, parser_state):
        try:
            import graphviz
        except:
            return
        s = graphviz.Digraph(
            self.logic.func_name,
            filename="pipeline_map.gv",
            node_attr={"shape": "record"},
        )

        # Dont bother if more than 128 nodes...
        if len(self.logic.submodule_instances) > 128:
            return

        s.graph_attr["rankdir"] = "LR"  # Left to right ordering
        # s.graph_attr['splines']="ortho" # Right angle lines...doesnt look right?

        # SIZE IO + REGS NODES to be largest font
        # Get average bit width (height of node)
        smallest_font_pt = 14.0

        def get_avg_bit_width(sub_inst, logic, parser_state):
            sub_func_name = logic.submodule_instances[sub_inst]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # See registers estiamte .log
            input_ffs = 0
            for input_port in sub_logic.inputs:
                input_type = sub_logic.wire_to_c_type[input_port]
                input_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                    input_type, parser_state
                )
                input_ffs += input_bits
            output_ffs = 0
            for output_port in sub_logic.outputs:
                output_type = sub_logic.wire_to_c_type[output_port]
                output_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                    output_type, parser_state
                )
                output_ffs += output_bits
            return (input_ffs + output_ffs) / 2.0

        # Bit width(height) scaling
        MIN_AVG_BIT_WIDTH = 999999
        MAX_AVG_BIT_WIDTH = 0
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            if sub_logic.delay is not None and sub_logic.delay > 0:  # Skip zero delay
                avg_bit_width = get_avg_bit_width(sub_inst, self.logic, parser_state)
                if avg_bit_width < MIN_AVG_BIT_WIDTH:
                    MIN_AVG_BIT_WIDTH = avg_bit_width
                if avg_bit_width > MAX_AVG_BIT_WIDTH:
                    MAX_AVG_BIT_WIDTH = avg_bit_width

        # Delay (width) scaling
        MIN_NON_ZERO_DELAY = 999999
        MAX_DELAY = 0
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            if sub_logic.delay is not None and sub_logic.delay > 0:  # Skip zero delay
                if sub_logic.delay < MIN_NON_ZERO_DELAY:
                    MIN_NON_ZERO_DELAY = sub_logic.delay
                if sub_logic.delay > MAX_DELAY:
                    MAX_DELAY = sub_logic.delay

        by_eye_scale = 4.0  # By-eye const adjust...
        max_font_pt = smallest_font_pt + (
            (MAX_DELAY / MIN_NON_ZERO_DELAY) * by_eye_scale
        )
        for wire in self.logic.wires:
            # Constants(Node)
            if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
                # TODO resolve to const str and manually add location on next line
                val_str = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                    wire, self.logic, parser_state
                )
                s.node(wire, r"{ " + val_str + " | {<const> CONST}}")

            # Inputs(Node)
            if wire in self.logic.inputs:
                s.node(
                    wire,
                    r"{ " + wire + " | {<in> IN}}",
                    **{"fontsize": str(max_font_pt)},
                )

            # Clock enable(Node)
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(self.logic, parser_state):
                s.node(
                    C_TO_LOGIC.CLOCK_ENABLE_NAME,
                    r"{ " + C_TO_LOGIC.CLOCK_ENABLE_NAME + " | {<in> IN}}",
                    **{"fontsize": str(max_font_pt)},
                )

            # Outputs(Node)
            if wire in self.logic.outputs:
                s.node(
                    wire,
                    r"{ {<out> OUT} | " + wire + " }",
                    **{"fontsize": str(max_font_pt)},
                )

            # State regs
            if wire in self.logic.state_regs:
                # s.node(wire, r'{ <in> NEXT | '+wire+' | <out> NOW }')
                s.node(
                    wire + "_in",
                    r"{ {<in> NEXT} | " + wire + " }",
                    **{"fontsize": str(max_font_pt)},
                )
                s.node(
                    wire + "_out",
                    r"{ " + wire + " | {<out> NOW} }",
                    **{"fontsize": str(max_font_pt)},
                )

        # Submodules/Nodes with ports
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            # Need to lookup input ports, and output ports
            # Location
            # And total width of inputs/outputs for height
            # width is based on delay of func logic
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            inputs_text = ""
            for input_port in sub_logic.inputs:
                inputs_text += f"<{input_port}> {input_port}" + " |"
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                inputs_text += (
                    f"<{C_TO_LOGIC.CLOCK_ENABLE_NAME}> {C_TO_LOGIC.CLOCK_ENABLE_NAME}"
                    + " |"
                )
            inputs_text = inputs_text.strip("|")
            outputs_text = ""
            for output_port in sub_logic.outputs:
                outputs_text += f"<{output_port}> {output_port}" + " |"
            outputs_text = outputs_text.strip("|")
            func_name_text = sub_func_name
            if sub_inst in self.logic.submodule_instance_to_ast_meta:
                location_text = self.logic.submodule_instance_to_ast_meta[
                    sub_inst
                ].coord_str()
                # location_text = (  # str(os.path.basename(c_ast_node_coord.file)) + r'\n' +
                #    "line "
                #    + str(c_ast_node_coord.line)
                #    + " "
                #    + "col. "
                #    + str(c_ast_node_coord.column)
                # )
            else:
                location_text = "internal"
            avg_bit_width = get_avg_bit_width(sub_inst, self.logic, parser_state)
            width = 1
            height = 1
            font_pt = smallest_font_pt
            if sub_logic.delay is not None and sub_logic.delay > 0:
                width = float(sub_logic.delay) / MIN_NON_ZERO_DELAY
                font_pt += width * by_eye_scale
                width *= by_eye_scale
                height = float(avg_bit_width) / MIN_AVG_BIT_WIDTH
                height /= by_eye_scale
            ns = float(sub_logic.delay) / SYN.DELAY_UNIT_MULT
            shape_text = f"{ns:.1f}ns x ~{avg_bit_width}bits"
            s.node(
                sub_inst,
                r"{{"
                + inputs_text
                + r"} | "
                + func_name_text
                + r"\n"
                + location_text
                + r"\n"
                + shape_text
                + r"| {"
                + outputs_text
                + r"}}",
                **{
                    "width": str(width),
                    "height": str(height),
                    "fontsize": str(font_pt),
                },
            )

        # Connections/Edges
        for driving_wire, driven_wires in self.logic.wire_drives.items():

            def wire_to_gv_text(wire, dir):
                # Constants(Node)
                if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
                    return wire + ":" + "const"

                # Inputs(Node)
                if wire in self.logic.inputs:
                    return wire + ":" + "in"

                # Clock enable(Node)
                if wire == C_TO_LOGIC.CLOCK_ENABLE_NAME:
                    return wire

                # Outputs(Node)
                if wire in self.logic.outputs:
                    return wire + ":" + "out"

                # State regs
                if wire in self.logic.state_regs:
                    return wire + "_" + dir + ":" + dir

                # Submodule
                if C_TO_LOGIC.SUBMODULE_MARKER in wire:
                    return wire.replace(C_TO_LOGIC.SUBMODULE_MARKER, ":")

                return None
                # raise Exception(f"GV text for wire? {wire}")

            for driven_wire in driven_wires:
                drive_text = wire_to_gv_text(driving_wire, "out")
                if drive_text is None:
                    continue
                # Follow wire-wire connections to submodules
                # Quickly hacked together...
                next_driven_wires = []
                if driven_wire in self.logic.wire_drives:
                    next_driven_wires = self.logic.wire_drives[driven_wire]
                driven_text = wire_to_gv_text(driven_wire, "in")
                if driven_text is not None:
                    s.edges([(drive_text, driven_text)])
                while driven_text is None and len(next_driven_wires) > 0:
                    new_next_driven_wires = []
                    for next_driven_wire in next_driven_wires:
                        driven_text = wire_to_gv_text(next_driven_wire, "in")
                        if driven_text is None:
                            if next_driven_wire in self.logic.wire_drives:
                                new_next_driven_wires += self.logic.wire_drives[
                                    next_driven_wire
                                ]
                        else:
                            s.edges([(drive_text, driven_text)])
                    next_driven_wires = new_next_driven_wires[:]

        s.format = "png"
        try:
            s.render(directory=out_dir)
        except Exception as e:
            print(f"graphviz render exception: {e}")
        return


rf"""
___          ___     __   __   ___  __       . ___ 
 |  |  |\/| |__     |  \ /  \ |__  /__` |\ | '  |  
 |  |  |  | |___    |__/ \__/ |___ .__/ | \|    |  
                                                   
 ___        __  ___              ___       ___     
|__  \_/ | /__`  |     | |\ |     |  |__| |__      
|___ / \ | .__/  |     | | \|     |  |  | |___     
                                                   
 __        __   ___        ___      ___            
|__)  /\  /__` |__   |\/| |__  |\ |  |             
|__) /~~\ .__/ |___  |  | |___ | \|  |             
"""


# So for ~now the answer is yes, forever
def GET_PIPELINE_MAP(inst_name, logic, parser_state, TimingParamsLookupTable):
    # FORGIVE ME (for this hacked custom graph breadth first thing w/ delays + multiple stages) - never
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    timing_params = TimingParamsLookupTable[inst_name]
    rv = PipelineMap(logic)

    # Non submodule modules like dont need this
    # Dont check just dont call this func in that case?
    if (
        VHDL.LOGIC_IS_RAW_HDL(logic, parser_state)
        or logic.is_vhdl_func
        or logic.is_vhdl_expr
        or logic.vhdl_module_text is not None
        or logic.func_name in parser_state.func_marked_blackbox
        or C_TO_LOGIC.FUNC_IS_PRIMITIVE(logic.func_name, parser_state)
    ):
        return rv

    print_debug = False
    bad_inf_loop = False
    if print_debug:
        print(
            "==============================Getting pipeline map======================================="
        )
        print("GET_PIPELINE_MAP:")
        print("inst_name", inst_name)
        print("logic.func_name", logic.func_name)
        # print "logic.submodule_instances:",logic.submodule_instances

    # Delay stuff was hacked into here and only works for combinatorial logic
    est_total_latency = None
    unresolved_submodule = NORMALIZE_KNOWN_ZERO_DELAY_SUBMODULE_DELAYS(
        logic, parser_state
    )
    has_delay = unresolved_submodule is None
    if print_debug and unresolved_submodule is not None:
        print("Submodule", unresolved_submodule.func_name, "has None delay")

    if print_debug:
        print("timing_params._slices", timing_params._slices)
        print("has_delay", has_delay)

    # Keep track of submodules whos inputs are fully driven
    fully_driven_submodule_inst_2_logic = {}
    # And keep track of which submodules remain
    # as to not keep looping over all submodules (sloo)
    not_fully_driven_submodules = set(logic.submodule_instances.keys())

    # Upon writing a submodule do not
    # add output wire (and driven by output wires) to wires_driven_so_far
    # Intead delay them for N clocks as counted by the clock loop
    #   "Let's pretend we don't exist. Lets pretend we're in Antarctica" - Of Montreal
    wire_to_remaining_clks_before_driven = {}
    # All wires start with invalid latency as to not write them too soon
    for wire in sorted(logic.wires):
        wire_to_remaining_clks_before_driven[wire] = -1

    # Bound on latency for sanity - this isnt used is it?
    if est_total_latency is not None:
        max_possible_latency = est_total_latency
        max_possible_latency_with_extra = max_possible_latency + 2

    # To keep track of 'execution order' do this stupid thing:
    # Keep a list of wires that are have been driven so far
    # Search this list to filter which submodules are in each level
    # Replaced wires_driven_so_far
    wires_driven_by_so_far = {}  # driven wire -> driving wire

    def RECORD_DRIVEN_BY(driving_wire, driven_wire_or_wires):
        if type(driven_wire_or_wires) is list:
            driven_wires = driven_wire_or_wires
        elif type(driven_wire_or_wires) is set:
            # Set iteration changes across Python processes.  This order is
            # carried into PipelineMap and eventually VHDL statement order,
            # so stabilize graph frontiers before traversing them.
            driven_wires = sorted(driven_wire_or_wires)
        else:
            driven_wires = [driven_wire_or_wires]
        for driven_wire in driven_wires:
            wires_driven_by_so_far[driven_wire] = driving_wire
            # Also set clks? Seems right?
            wire_to_remaining_clks_before_driven[driven_wire] = 0

    # Some wires are driven to start with
    RECORD_DRIVEN_BY(None, logic.inputs)
    RECORD_DRIVEN_BY(None, C_TO_LOGIC.CLOCK_ENABLE_NAME)
    RECORD_DRIVEN_BY(None, set(logic.state_regs.keys()))
    RECORD_DRIVEN_BY(None, logic.feedback_vars)

    # Keep track of delay offset when wire is driven
    # ONLY MAKES SENSE FOR 0 CLK RIGHT NOW
    delay_offset_when_driven = {}
    for wire_driven_so_far in list(wires_driven_by_so_far.keys()):
        delay_offset_when_driven[wire_driven_so_far] = (
            0  # Is per stage value but we know is start of stage 0
        )

    # Start with wires that have drivers
    last_wires_starting_level = None
    wires_starting_level = list(wires_driven_by_so_far.keys())[:]
    next_wires_to_follow = []

    # Special handling of wires not directly in pipeline:

    # Propagate network across wires until reaching submodule inputs
    # Append wire driver pairs to submodule_level_info
    # Return submodules reached by wire
    def propagate_wire(
        wire_to_follow,
        upstream_vars,
        submodule_level_info,
        network_wire_to_upstream_vars,
    ):
        if wire_to_follow not in network_wire_to_upstream_vars:
            network_wire_to_upstream_vars[wire_to_follow] = set()
        network_wire_to_upstream_vars[wire_to_follow] |= upstream_vars
        submodules_reached = set()
        # Submodule input port finishes level
        is_submodule_input = False
        if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(wire_to_follow, logic):
            sub_toks = wire_to_follow.split(C_TO_LOGIC.SUBMODULE_MARKER)
            submodule_inst = sub_toks[0]
            sub_func_name = logic.submodule_instances[submodule_inst]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            sub_port_name = sub_toks[1]
            if sub_port_name in sub_logic.inputs:
                is_submodule_input = True
            if sub_port_name in sub_logic.outputs:
                RECORD_DRIVEN_BY(None, wire_to_follow)
        if is_submodule_input:
            sub_toks = wire_to_follow.split(C_TO_LOGIC.SUBMODULE_MARKER)
            submodule_inst = sub_toks[0]
            submodules_reached.add(submodule_inst)
        else:
            # Otherwise keep following connected wires
            driven_wires = []
            if wire_to_follow in logic.wire_drives:
                driven_wires = sorted(logic.wire_drives[wire_to_follow])
            for driven_wire in driven_wires:
                RECORD_DRIVEN_BY(wire_to_follow, driven_wire)
                submodule_level_info.driver_driven_wire_pairs.append(
                    (wire_to_follow, driven_wire)
                )
                submodules_reached |= propagate_wire(
                    driven_wire,
                    upstream_vars,
                    submodule_level_info,
                    network_wire_to_upstream_vars,
                )
        return submodules_reached

    # Single submodule level of network propagation
    # Fucky since essentially can start with upstream root wires or following modules...
    # Return updated stage_info with new submodule level and return all_in_network_sub_insts_reached
    def propagate_submodule_level(
        things_to_follow,
        things_are_upstream_vars_not_submodules,
        submodule_level_num,
        stage_info,
        network_wire_to_upstream_vars,
    ):
        submodule_level_info = SubmoduleLevelInfo(submodule_level_num)
        # Upstreams vars for these wires depend on if starting off with wires or following submodules
        wire_to_upstream_vars = {}
        if things_are_upstream_vars_not_submodules:
            wires_to_follow = sorted(things_to_follow)
            for wire_to_follow in wires_to_follow:
                # Follow wires marking as mark of network to submodules
                upstream_vars = set([wire_to_follow])
                wire_to_upstream_vars[wire_to_follow] = upstream_vars
        else:
            submodules_to_follow_outputs = things_to_follow
            # Follow submodule outputs adding to wires_to_follow
            wires_to_follow = set()
            for sub_inst_reached in sorted(submodules_to_follow_outputs):
                sub_func_name = logic.submodule_instances[sub_inst_reached]
                sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
                # Known that this func has all inputs fully driven by network in prev sub level
                # And module can be instantiated in separate network
                prev_submodule_level_info = stage_info.submodule_level_infos[-1]
                prev_submodule_level_info.submodule_insts.append(sub_inst_reached)
                fully_driven_submodule_inst_2_logic[sub_inst_reached] = sub_logic
                not_fully_driven_submodules.remove(sub_inst_reached)
                # Set upstream vars for this output wire to be
                # everything that occurs across inputs
                input_upstream_vars = set()
                if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                    input_wire = (
                        sub_inst_reached
                        + C_TO_LOGIC.SUBMODULE_MARKER
                        + C_TO_LOGIC.CLOCK_ENABLE_NAME
                    )
                    if input_wire in network_wire_to_upstream_vars:
                        input_upstream_vars |= network_wire_to_upstream_vars[input_wire]
                for input_port in sub_logic.inputs:
                    input_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + input_port
                    )
                    input_upstream_vars |= network_wire_to_upstream_vars[input_wire]
                for output_port in sub_logic.outputs:
                    output_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + output_port
                    )
                    wires_to_follow.add(output_wire)
                    wire_to_upstream_vars[output_wire] = input_upstream_vars
        # Follow each wire with associated upstream vars to more submodules
        all_in_network_sub_insts_reached = set()
        for wire_to_follow in sorted(wires_to_follow):
            upstream_vars = wire_to_upstream_vars[wire_to_follow]
            sub_insts_reached = propagate_wire(
                wire_to_follow,
                upstream_vars,
                submodule_level_info,
                network_wire_to_upstream_vars,
            )
            # Are all submodule inputs part of network?
            for sub_inst_reached in sorted(sub_insts_reached):
                if sub_inst_reached in all_in_network_sub_insts_reached:
                    continue
                sub_func_name = logic.submodule_instances[sub_inst_reached]
                sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
                all_inputs_in_network = True
                for input_port in sub_logic.inputs:
                    input_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + input_port
                    )
                    if input_wire not in network_wire_to_upstream_vars.keys():
                        all_inputs_in_network = False
                        break
                if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                    input_wire = (
                        sub_inst_reached
                        + C_TO_LOGIC.SUBMODULE_MARKER
                        + C_TO_LOGIC.CLOCK_ENABLE_NAME
                    )
                    if input_wire not in network_wire_to_upstream_vars.keys():
                        all_inputs_in_network = False
                if all_inputs_in_network:
                    all_in_network_sub_insts_reached.add(sub_inst_reached)
        # Update and return where ended up
        stage_info.submodule_level_infos.append(submodule_level_info)
        return all_in_network_sub_insts_reached

    # Constant network propagation starts at user constant literals like '2'
    things_to_follow = set()
    for wire in sorted(logic.wires):
        if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
            RECORD_DRIVEN_BY(None, wire)
            things_to_follow.add(wire)
    if len(things_to_follow) > 0:
        rv.const_network_stage_info = StageInfo(0)
    submodule_level = 0
    while len(things_to_follow) > 0:
        things_are_upstream_vars_not_submodules = submodule_level == 0
        all_in_network_sub_insts_reached = propagate_submodule_level(
            things_to_follow,
            things_are_upstream_vars_not_submodules,
            submodule_level,
            rv.const_network_stage_info,
            rv.const_network_wire_to_upstream_vars,
        )
        submodule_level += 1
        # Conditionally set submodule outputs as next wires to follow
        things_to_follow = set()
        for sub_inst_reached in sorted(all_in_network_sub_insts_reached):
            sub_func_name = logic.submodule_instances[sub_inst_reached]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # Is this logic something constants propagate over?
            # Any pure function without state should work
            # Use clock/enable? check?
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                continue
            things_to_follow.add(sub_inst_reached)

    # Do read_only_global_wires (non volatile) network prop
    # Starts from read only wires
    things_to_follow = set(logic.read_only_global_wires.keys())
    RECORD_DRIVEN_BY(None, set(logic.read_only_global_wires.keys()))
    if len(things_to_follow) > 0:
        rv.read_only_global_network_stage_info = StageInfo(0)
        # And also includes constant network but does not include its upstream vars/wires - just that is in network
        for const_network_wire in rv.const_network_wire_to_upstream_vars:
            if (
                const_network_wire
                not in rv.read_only_global_network_wire_to_upstream_vars
            ):
                rv.read_only_global_network_wire_to_upstream_vars[
                    const_network_wire
                ] = set()
    submodule_level = 0
    while len(things_to_follow) > 0:
        things_are_upstream_vars_not_submodules = submodule_level == 0
        all_in_network_sub_insts_reached = propagate_submodule_level(
            things_to_follow,
            things_are_upstream_vars_not_submodules,
            submodule_level,
            rv.read_only_global_network_stage_info,
            rv.read_only_global_network_wire_to_upstream_vars,
        )
        submodule_level += 1
        # Conditionally set submodule outputs as next wires to follow
        things_to_follow = set()
        for sub_inst_reached in sorted(all_in_network_sub_insts_reached):
            sub_func_name = logic.submodule_instances[sub_inst_reached]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # Is this logic something non vol read only globals propagate over?
            if not SYN.LOGIC_IS_ZERO_DELAY(sub_logic, parser_state, True):
                continue
            things_to_follow.add(sub_inst_reached)

    # Pipeline is done when
    def PIPELINE_DONE():
        # ALl outputs driven
        for output in logic.outputs:
            if (output not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[output] is None
            ):
                if print_debug:
                    print("Pipeline not done, output seems never driven:", output)
                return False
            if print_debug:
                print("Output driven ", output, "<=", wires_driven_by_so_far[output])
        # Feedback wires
        for feedback_var in logic.feedback_vars:
            if (feedback_var not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[feedback_var] is None
            ):
                if print_debug:
                    print("Pipeline not done, feedback var seems never driven:", feedback_var)
                return False
            if print_debug:
                print(
                    "Feedback var driven ",
                    feedback_var,
                    "<=",
                    wires_driven_by_so_far[feedback_var],
                )
        # ALl globals driven
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile == False:
                if (state_reg not in wires_driven_by_so_far) or (
                    wires_driven_by_so_far[state_reg] is None
                ):
                    # A reg with no wire_driven_by entry was never written: it holds its
                    # value via REG_VAR (VHDL emits REG_COMB_x <= REG_VAR_x := x).
                    # This is valid hardware (read-only init-value register); skip it.
                    if state_reg not in logic.wire_driven_by:
                        if print_debug:
                            print("Register holds value (never written):", state_reg)
                        continue
                    if print_debug:
                        print("Pipeline not done, state_reg seems never driven:", state_reg)
                    return False
                if print_debug:
                    print(
                        "state_reg driven ",
                        state_reg,
                        "<=",
                        wires_driven_by_so_far[state_reg],
                    )
        # All write only global var wires
        for global_wire in logic.write_only_global_wires:
            if (global_wire not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[global_wire] is None
            ):
                if print_debug:
                    print("Pipeline not done, write only global seems never driven:", global_wire)
                return False
            if print_debug:
                print(
                    "Write only global driven ",
                    global_wire,
                    "<=",
                    wires_driven_by_so_far[global_wire],
                )
        # ALl voltatile globals driven
        # Some volatiles are read only - ex. valid indicator bit
        # And thus are never driven
        # Allow a volatile global wire not to be driven if logic says it is undriven
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile:
                volatile_global_wire = state_reg
                if volatile_global_wire in logic.wire_driven_by:
                    # Has a driving wire so must be driven for func to be done
                    if (volatile_global_wire not in wires_driven_by_so_far) or (
                        wires_driven_by_so_far[volatile_global_wire] is None
                    ):
                        if print_debug:
                            print(
                                "Pipeline not done, volatile global seems never driven:",
                                volatile_global_wire,
                            )
                        return False
                if print_debug:
                    print(
                        "Volatile driven ",
                        volatile_global_wire,
                        "<=",
                        wires_driven_by_so_far[volatile_global_wire],
                    )

        # All other wires driven?
        for wire in logic.wires:
            if wire not in wires_driven_by_so_far and not logic.WIRE_ALLOW_NO_DRIVEN_BY(
                wire, parser_state.FuncLogicLookupTable
            ):
                if print_debug:
                    print("Pipeline not done, wire seems never driven:", wire)
                return False
            if print_debug:
                driven_by = None
                if wire in wires_driven_by_so_far:
                    driven_by = wires_driven_by_so_far[wire]
                print("Wire driven ", wire, "<=", driven_by)
        if print_debug:
            print("Pipeline stages done...")
        return True

    # WHILE LOOP FOR MULTI STAGE/CLK
    stage_num = 0
    stage_info = StageInfo(stage_num)
    rv.stage_infos.append(stage_info)
    # Above constant and global wire prop
    # means might be done pipeline before even a single iteration
    # of below while loop that increments stage_num, and then stage_num-1 is used for stage count
    if PIPELINE_DONE():
        stage_num = 1
    while not PIPELINE_DONE():
        # Print stuff and set debug if obviously wrong
        if stage_num >= 5000:
            # Pipeline too long? Past hard coded limit probably...
            print("Pipelining is failing to construct inputs->stages->outputs...")
            print("for inst_name:", inst_name)
            bad_inf_loop = True
            print_debug = True
        if stage_num >= 5001:
            sys.exit(-1)
        if est_total_latency is not None:
            if stage_num >= max_possible_latency_with_extra:
                print("Something is wrong here, infinite loop probably...")
                print("for inst_name:", inst_name)
                # print 0/0
                sys.exit(-1)
            elif stage_num >= max_possible_latency + 1:
                bad_inf_loop = True
                print_debug = True
        if print_debug:
            print("STAGE NUM =", stage_num)

        submodule_level = 0
        # DO WHILE LOOP FOR PER COMB LOGIC SUBMODULE LEVELS
        while True:  # DO
            submodule_level_info = SubmoduleLevelInfo(submodule_level)
            # submodule_level_text = ""

            if print_debug:
                print("SUBMODULE LEVEL", submodule_level)

            #########################################################################################
            # THIS WHILE LOOP FOLLOWS WIRES TO SUBMODULES
            # (BEWARE!: NO SUBMODULES MAY BE FULLY DRIVEN DUE TO MULTI CLK LATENCY)
            # First follow wires to submodules
            # print "wires_driven_by_so_far",wires_driven_by_so_far
            # print "wires_starting_level",wires_starting_level
            wires_to_follow = wires_starting_level[:]
            while len(wires_to_follow) > 0:
                # Sort wires to follow for easy debug of duplicates
                wires_to_follow = sorted(wires_to_follow)
                for driving_wire in wires_to_follow:
                    if bad_inf_loop:
                        print("driving_wire", driving_wire)

                    # Record driving wire as being driven?
                    if driving_wire not in wires_driven_by_so_far:
                        # What drives the driving wire?
                        # Dont know driving wire?
                        driver_of_driver = None
                        if driving_wire in logic.wire_driven_by:
                            driver_of_driver = logic.wire_driven_by[driving_wire]
                        RECORD_DRIVEN_BY(driver_of_driver, driving_wire)

                    # If driving wire is submodule output
                    # Then connect module wire to write pipe
                    if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(
                        driving_wire, logic
                    ):  # is output checked next
                        sub_out_toks = driving_wire.split(C_TO_LOGIC.SUBMODULE_MARKER)
                        submodule_inst = sub_out_toks[0]
                        output_port = sub_out_toks[1]
                        submodule_inst_name = (
                            inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                        )
                        submodule_logic = parser_state.LogicInstLookupTable[
                            submodule_inst_name
                        ]
                        # Make sure is output
                        if output_port in submodule_logic.outputs:
                            # Zero latency special case already in write pipe
                            submodule_latency_from_container_logic = (
                                timing_params.GET_SUBMODULE_LATENCY(
                                    submodule_inst_name,
                                    parser_state,
                                    TimingParamsLookupTable,
                                )
                            )
                            if submodule_latency_from_container_logic > 0:
                                stage_info.submodule_output_ports.append(driving_wire)

                    # Loop over what this wire drives
                    if driving_wire in logic.wire_drives:
                        driven_wires = logic.wire_drives[driving_wire]
                        # Sort for easy debug
                        driven_wires = sorted(driven_wires)
                        if bad_inf_loop:
                            print("driven_wires", driven_wires)

                        # Handle each driven wire
                        for driven_wire in driven_wires:
                            if bad_inf_loop:
                                print("handling driven wire", driven_wire)

                            if driven_wire not in logic.wire_driven_by:
                                # In
                                print(
                                    "!!!!!!!!!!!! DANGLING LOGIC???????",
                                    driven_wire,
                                    "is not driven!?",
                                )
                                continue

                            # Add driven wire to wires driven so far
                            # Record driving this wire, at this logic level offset
                            if (driven_wire in wires_driven_by_so_far) and (
                                wires_driven_by_so_far[driven_wire] is not None
                            ):
                                # Already handled this wire
                                continue
                            RECORD_DRIVEN_BY(driving_wire, driven_wire)

                            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                            if has_delay:
                                delay_offset_when_driven[driven_wire] = (
                                    delay_offset_when_driven[driving_wire]
                                )
                            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

                            # Follow the driven wire unless its a submodule input port
                            # Submodules input ports is handled at hierarchy cross later - do nothing later
                            if not C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(
                                driven_wire, logic
                            ):
                                # Record reaching another wire
                                next_wires_to_follow.append(driven_wire)

                            # Driving of vol wires is delayed to last stage and done manually in other vhdl
                            # do not record the final driving of vol wires
                            if (
                                driven_wire in logic.state_regs
                                and logic.state_regs[driven_wire].is_volatile
                            ):
                                continue

                            # Record wire pair for rendering in vhdl
                            submodule_level_info.driver_driven_wire_pairs.append(
                                (driving_wire, driven_wire)
                            )

                wires_to_follow = next_wires_to_follow[:]
                next_wires_to_follow = []

            #########################################################################################

            # \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ GET FULLY DRIVEN SUBMODULES TO POPULATE SUBMODULE LEVEL \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/
            # Have followed this levels wires to submodules
            # We only want to consider the submodules whose inputs have all
            # been driven by now in clock cycle to keep execution order
            #   ALSO:
            #     Slicing between submodules is done via artificially delaying when submodules are instantiated/connected into later stages
            fully_driven_submodule_inst_this_level_2_logic = {}
            # Get submodule logics
            # Loop over each sumodule and check if all inputs are driven
            not_fully_driven_submodules_iter = sorted(
                not_fully_driven_submodules
            )
            for submodule_inst in not_fully_driven_submodules_iter:
                submodule_inst_name = (
                    inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                # Skip submodules weve done already
                already_fully_driven = (
                    submodule_inst in fully_driven_submodule_inst_2_logic
                )
                # Also skip if not the correct stage for this submodule
                incorrect_stage_for_submodule = False

                # if print_debug:
                # print ""
                # print "########"
                # print "SUBMODULE INST",submodule_inst, "FULLY DRIVEN?:",already_fully_driven

                if not already_fully_driven and not incorrect_stage_for_submodule:
                    submodule_logic = parser_state.LogicInstLookupTable[
                        submodule_inst_name
                    ]

                    # Check submodule signals that need to be driven before submodule can be used
                    # CLOCK ENABLE + INPUTS
                    submodule_has_all_inputs_driven = True
                    submodule_input_port_driving_wires = []
                    # Check clock enable
                    if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(
                        submodule_logic, parser_state
                    ):
                        # print "logic.func_name", logic.func_name
                        ce_wire = (
                            submodule_inst
                            + C_TO_LOGIC.SUBMODULE_MARKER
                            + C_TO_LOGIC.CLOCK_ENABLE_NAME
                        )
                        ce_driving_wire = logic.wire_driven_by[ce_wire]
                        submodule_input_port_driving_wires.append(ce_driving_wire)
                        if ce_driving_wire not in wires_driven_by_so_far:
                            submodule_has_all_inputs_driven = False
                    # Check each input
                    if submodule_has_all_inputs_driven:
                        for input_port_name in submodule_logic.inputs:
                            driving_wire = (
                                C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(
                                    logic, submodule_inst, input_port_name
                                )
                            )
                            submodule_input_port_driving_wires.append(driving_wire)
                            if driving_wire not in wires_driven_by_so_far:
                                submodule_has_all_inputs_driven = False
                                if bad_inf_loop:
                                    print(
                                        "!! "
                                        + submodule_inst
                                        + " input wire "
                                        + input_port_name
                                        + " not driven yet"
                                    )
                                    print(" ^ is driven by", driving_wire)
                                    # print "  <<<<<<<<<<<<< ", driving_wire , "is not (fully?) driven?"
                                    # print " <<<<<<<<<<<<< YOU ARE PROBABALY NOT DRIVING ALL LOCAL VARIABLES COMPLETELY(STRUCTS) >>>>>>>>>>>> "
                                    # C_TO_LOGIC.PRINT_DRIVER_WIRE_TRACE(driving_wire, logic, wires_driven_by_so_far)
                                break

                    # If all inputs are driven
                    if submodule_has_all_inputs_driven:
                        fully_driven_submodule_inst_2_logic[submodule_inst] = (
                            submodule_logic
                        )
                        fully_driven_submodule_inst_this_level_2_logic[
                            submodule_inst
                        ] = submodule_logic
                        not_fully_driven_submodules.remove(submodule_inst)
                        if bad_inf_loop:
                            print("submodule", submodule_inst, "HAS ALL INPUTS DRIVEN")

                        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                        if has_delay:
                            # Record delay offset as max of driving wires
                            # Do zero_clk_submodule_start_offset INPUT OFFSET as max of input wires
                            # Start with 0 since submodule can have no inputs and this no input port delay offset
                            input_port_delay_offsets = [0]
                            for (
                                submodule_input_port_driving_wire
                            ) in submodule_input_port_driving_wires:
                                # Some inputs might be constant, dont contribute to delay offset
                                # Some inputs might also be global read wires, similar no delay
                                if (
                                    submodule_input_port_driving_wire
                                    not in rv.const_network_wire_to_upstream_vars
                                    and submodule_input_port_driving_wire
                                    not in rv.read_only_global_network_wire_to_upstream_vars
                                ):
                                    delay_offset = delay_offset_when_driven[
                                        submodule_input_port_driving_wire
                                    ]
                                    input_port_delay_offsets.append(delay_offset)
                            max_input_port_delay_offset = max(input_port_delay_offsets)

                            # All submodules should be driven at some offset right?
                            # print "wires_driven_by_so_far",wires_driven_by_so_far
                            # print "delay_offset_when_driven",delay_offset_when_driven
                            rv.zero_clk_submodule_start_offset[submodule_inst] = (
                                max_input_port_delay_offset
                            )

                            # Do  delay starting at the input offset
                            # This delay_offset_when_driven value wont be used
                            # until the stage when the output wire is read
                            # So needs delay expected in last stage
                            submodule_timing_params = TimingParamsLookupTable[
                                submodule_inst_name
                            ]
                            submodule_delay = parser_state.LogicInstLookupTable[
                                submodule_inst_name
                            ].delay
                            # End offset is start offset plus delay
                            # Ex. 0 delay in offset 0
                            # Starts and ends in offset 0
                            # Ex. 1 delay unit in offset 0
                            # ALSO STARTS AND ENDS IN STAGE 0
                            if submodule_delay > 0:
                                abs_delay_end_offset = (
                                    submodule_delay
                                    + rv.zero_clk_submodule_start_offset[submodule_inst]
                                    - 1
                                )
                            else:
                                abs_delay_end_offset = (
                                    rv.zero_clk_submodule_start_offset[submodule_inst]
                                )
                            rv.zero_clk_submodule_end_offset[submodule_inst] = (
                                abs_delay_end_offset
                            )

                            # Do PARALLEL submodules map with start and end offsets from each stage
                            # Dont do for 0 delay submodules, ok fine
                            if submodule_delay > 0:
                                start_offset = rv.zero_clk_submodule_start_offset[
                                    submodule_inst
                                ]
                                end_offset = rv.zero_clk_submodule_end_offset[
                                    submodule_inst
                                ]
                                for abs_delay in range(start_offset, end_offset + 1):
                                    if abs_delay < 0:
                                        print("<0 delay offset?")
                                        print(start_offset, end_offset)
                                        print(delay_offset_when_driven)
                                        sys.exit(-1)
                                    # Submodule isnts
                                    if (
                                        abs_delay
                                        not in rv.zero_clk_per_delay_submodules_map
                                    ):
                                        rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ] = []
                                    if (
                                        submodule_inst
                                        not in rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ]
                                    ):
                                        rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ].append(submodule_inst)

                        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

                    else:
                        # Otherwise save for later
                        if bad_inf_loop:
                            print(
                                "submodule",
                                submodule_inst,
                                "does not have all inputs driven yet",
                            )

                else:
                    # if not already_fully_driven and not incorrect_stage_for_submodule:
                    if print_debug:
                        if not already_fully_driven:
                            print("submodule", submodule_inst)
                            print("already_fully_driven", already_fully_driven)
                            # if submodule_inst in timing_params.submodule_to_start_stage:
                            # print "incorrect_stage_for_submodule",incorrect_stage_for_submodule," = ",stage_num, "stage_num != ", timing_params.submodule_to_start_stage[submodule_inst]

            # print "got input driven submodules, wires_driven_by_so_far",wires_driven_by_so_far
            if bad_inf_loop:
                print(
                    "fully_driven_submodule_inst_this_level_2_logic",
                    fully_driven_submodule_inst_this_level_2_logic,
                )
            # /\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\

            # Im dumb
            submodule_level_iteration_has_submodules = (
                len(fully_driven_submodule_inst_this_level_2_logic) > 0
            )

            ################## INSTANTIATIONS + OUTPUT WIRES FROM SUBMODULE LEVEL ###################################
            # Get list of output wires for this all the submodules in this level
            # by writing submodule connections / entity connections
            for submodule_inst in fully_driven_submodule_inst_this_level_2_logic:
                submodule_inst_name = (
                    inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]

                # Use submodule logic to write vhdl
                submodule_level_info.submodule_insts.append(submodule_inst)

                # Get latency
                submodule_latency_from_container_logic = (
                    timing_params.GET_SUBMODULE_LATENCY(
                        submodule_inst_name, parser_state, TimingParamsLookupTable
                    )
                )
                # Add output wires of this submodule to wires driven so far after latency
                for output_port in submodule_logic.outputs:
                    # Construct the name of this wire in the original logic
                    submodule_output_wire = (
                        submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
                    )
                    if bad_inf_loop:
                        print("following output", submodule_output_wire)
                    # Add this output port wire on the submodule after the latency of the submodule
                    if bad_inf_loop:
                        print("submodule_output_wire", submodule_output_wire)
                    wire_to_remaining_clks_before_driven[submodule_output_wire] = (
                        submodule_latency_from_container_logic
                    )

                    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                    # Set delay_offset_when_driven for this output wire
                    if has_delay:
                        # Set delay offset for this wire
                        submodule_delay = parser_state.LogicInstLookupTable[
                            submodule_inst_name
                        ].delay
                        abs_delay_offset = rv.zero_clk_submodule_end_offset[
                            submodule_inst
                        ]
                        delay_offset_when_driven[submodule_output_wire] = (
                            abs_delay_offset
                        )
                        # ONly +1 if delay > 0
                        if submodule_delay > 0:
                            delay_offset_when_driven[submodule_output_wire] += (
                                1  # "+1" Was seeing stacked parallel submodules where they dont exist
                            )
                    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            ####################################################################################################################

            # END
            # SUBMODULE
            # LEVEL
            # ITERATION

            # This ends one submodule level iteration
            # Record text from this iteration
            submodule_level_prepend_text = (
                "  " + " " + "-- SUBMODULE LEVEL " + str(submodule_level) + "\n"
            )
            if not submodule_level_info.IS_EMPTY():
                stage_info.submodule_level_infos.append(submodule_level_info)

            # Sometimes submodule levels iterations dont have submodules as we iterate driving wires / for multiple clks
            # Only update counters if was real submodule level with submodules
            if submodule_level_iteration_has_submodules:
                # Update counters
                submodule_level = submodule_level + 1
            # else:
            # print "NOT submodule_level_iteration_has_submodules, and that is weird?"
            # sys.exit(-1)

            # Wires starting next level IS wires whose latency has elapsed just now
            wires_starting_level = []
            # Also are added to wires driven so far
            # (done per submodule level iteration since ALSO DOES 0 CLK SUBMODULE OUTPUTS)
            for wire in sorted(wire_to_remaining_clks_before_driven):
                if wire_to_remaining_clks_before_driven[wire] == 0:
                    if wire not in wires_driven_by_so_far:
                        if bad_inf_loop:
                            print("wire remaining clks done, is driven now", wire)

                        driving_wire = None
                        if wire in logic.wire_driven_by:
                            driving_wire = logic.wire_driven_by[wire]
                        RECORD_DRIVEN_BY(driving_wire, wire)
                        wires_starting_level.append(wire)

            # WHILE CHECK for when to stop try for submodule levels in this stage
            if not (len(wires_starting_level) > 0):
                # Break out of this loop trying to do submodule level iterations for this stage
                break
            else:
                # Record these last wires starting level and loop again
                # This is dumb and probably doesnt work?
                if last_wires_starting_level == wires_starting_level:
                    print("Same wires starting level?")
                    print(wires_starting_level)
                    # if print_debug:
                    sys.exit(-1)
                    # print_debug = True
                    # sys.exit(-1)
                else:
                    last_wires_starting_level = wires_starting_level[:]

        # PER CLOCK
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        if has_delay:
            # Get max delay
            if len(list(rv.zero_clk_per_delay_submodules_map.keys())) == 0:
                if print_debug:
                    print("No submodules with delay")
                rv.zero_clk_max_delay = 0
            else:
                rv.zero_clk_max_delay = (
                    max(rv.zero_clk_per_delay_submodules_map.keys()) + 1
                )  # +1 since 0 indexed
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

        # PER CLOCK decrement latencies
        if print_debug:
            print("Current stage info...", len(rv.stage_infos))
        stage_num = stage_num + 1
        stage_info = StageInfo(stage_num)
        rv.stage_infos.append(stage_info)
        for wire in wire_to_remaining_clks_before_driven:
            # if wire_to_remaining_clks_before_driven[wire] >= 0:
            wire_to_remaining_clks_before_driven[wire] = (
                wire_to_remaining_clks_before_driven[wire] - 1
            )

        # Output might be driven

        # For 0 clk global funcs, and no global funcs
        # the output is always driven in the last stage / stage zero
        # But for volatile globals the return value might be driven before
        # all of the other logic driving the volatiles is done
        num_volatiles = 0
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile:
                num_volatiles += 1
        if num_volatiles == 0:
            if est_total_latency is not None:
                # Sanity check that output is driven in last stage
                my_total_latency = stage_num - 1
                if PIPELINE_DONE() and (my_total_latency != est_total_latency):
                    print("Seems like pipeline is done before or after last stage?")
                    print(
                        "inst_name",
                        inst_name,
                        timing_params.GET_HASH_EXT(
                            TimingParamsLookupTable, parser_state
                        ),
                    )
                    print(
                        "est_total_latency",
                        est_total_latency,
                        "calculated total_latency",
                        my_total_latency,
                    )
                    print("timing_params._slices", timing_params._slices)
                    # print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
                    print(0 / 0)
                    sys.exit(-1)
                    print_debug = True

    # *************************** End of while loops *****************************************************#

    # Save number of stages using stage number counter
    rv.num_stages = stage_num
    my_total_latency = rv.num_stages - 1

    # Sanity check against estimate
    if est_total_latency is not None:
        if est_total_latency != my_total_latency:
            print("BUG IN PIPELINE MAP!")
            print(
                "inst_name",
                inst_name,
                timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state),
            )
            print(
                "est_total_latency",
                est_total_latency,
                "calculated total_latency",
                my_total_latency,
            )
            print("timing_params._slices5", timing_params._slices)
            # print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
            sys.exit(-1)

    if print_debug:
        print("Stage infos count:", len(rv.stage_infos))

    return rv


def CHECK_FIXED_LATENCY_BOUNDARY(inst_name, parser_state):
    """Reject added registers anywhere inside a user fixed-latency boundary."""
    fixed = getattr(parser_state, "func_fixed_latency", {})
    if not fixed:
        return
    current = inst_name
    while current:
        logic = parser_state.LogicInstLookupTable.get(current)
        if logic is not None and logic.func_name in fixed:
            raise ValueError(
                f"Cannot add pipeline registers to {inst_name}: "
                f"{current} has fixed latency {fixed[logic.func_name]}"
            )
        current, _, _ = current.rpartition(C_TO_LOGIC.SUBMODULE_MARKER)


# Returns updated TimingParamsLookupTable
# Index of bad slice if sliced through globals, scoo # Passing Afternoon - Iron & Wine
# THIS MUST BE CALLED IN LOOP OF INCREASING SLICES FROM LEFT=>RIGHT
def SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
    inst_name,
    logic,
    new_slice_pos,
    parser_state,
    TimingParamsLookupTable,
    skip_boundary_slice,
    write_files=True,
    rounding_so_fuck_it=False,
):
    print_debug = False

    CHECK_FIXED_LATENCY_BOUNDARY(inst_name, parser_state)
    # Get timing params for this logic
    timing_params = TimingParamsLookupTable[inst_name]
    if timing_params.params_are_fixed:
        print("Trying to add slice to fixed params?", inst_name)
        sys.exit(-1)

    if print_debug:
        print(
            "SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES",
            inst_name,
            new_slice_pos,
            "write_files",
            write_files,
        )

    # Add slice to current func
    timing_params.ADD_SLICE(new_slice_pos)
    slice_index = timing_params._slices.index(new_slice_pos)
    slice_ends_stage = slice_index

    # Raw HDL doesnt need further slicing, bottom of hierarchy
    if len(logic.submodule_instances) > 0:
        # print "logic.submodule_instances",logic.submodule_instances
        # Get the zero clock pipeline map for this logic
        zero_added_clks_pipeline_map = GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
            inst_name, logic, parser_state
        )
        total_delay = zero_added_clks_pipeline_map.zero_clk_max_delay

        # Get the offset as float
        delay_offset_float = new_slice_pos * total_delay
        delay_offset = math.floor(delay_offset_float)
        # Clamp to max?
        max_delay = max(
            zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map.keys()
        )
        if delay_offset > max_delay:
            delay_offset = max_delay
        delay_offset_decimal = delay_offset_float - delay_offset

        # Slice can be through modules or on the boundary between modules
        # The boundary between modules is important for moving slices right up against global logic?

        # Get submodules at this offset
        submodule_insts = (
            zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset]
        )

        # Slice each submodule at offset
        # Record if submodules need to be artifically delayed to start in a later stage
        for submodule_inst in submodule_insts:
            # Slice through submodule
            submodule_inst_name = (
                inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
            )
            submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
            # Only continue slicing down if not fixed slices already (trying to slice deeper and make fixed slices)
            if submodule_timing_params.params_are_fixed:
                continue
            # Slice through submodule
            # Only slice when >= 1 delay unit?
            submodule_func_name = logic.submodule_instances[submodule_inst]
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]

            start_offset = zero_added_clks_pipeline_map.zero_clk_submodule_start_offset[
                submodule_inst
            ]
            local_offset = delay_offset - start_offset
            local_offset_w_decimal = local_offset + delay_offset_decimal

            # print "start_offset",start_offset
            # print "local_offset",local_offset
            # print "local_offset_w_decimal",local_offset_w_decimal

            # Convert to percent to add slice
            submodule_total_delay = submodule_logic.delay
            slice_pos = float(local_offset_w_decimal) / float(submodule_total_delay)
            if print_debug:
                print(" Slicing:", submodule_inst)
                print("   @", slice_pos)

            # Slice into submodule only if the cut can actually land there:
            #  - the call site is AUTO_PIPELINE tagged (or contains a tag deeper),
            #    which overrides stateful boundaries on both sides, OR
            #  - both this func and the submodule are plain sliceable comb logic.
            # Checking the submodule side too keeps cuts from descending into
            # stateful (feedback/state reg) children where they would produce no
            # registers (latency stays 0) and silently vanish - such cuts instead
            # stop here and the child boundary becomes the stage boundary.
            # Checking the parent side keeps untagged comb children of stateful
            # funcs (e.g. FSMs) from gaining latency their container can't absorb.
            if not (
                logic.SUB_HAS_AUTO_PIPELINE_IN_HIER(submodule_inst, parser_state)
                or (
                    logic.CAN_HAVE_ADDED_LATENCY(parser_state)
                    and submodule_logic.CAN_HAVE_ADDED_LATENCY(parser_state)
                )
            ):
                continue

            # Defensive backstop, not the primary mechanism: a raw HDL leaf
            # whose own generator only meaningfully supports a bounded
            # number of slices (SPLIT_KIND_1LL - see RAW_VHDL.
            # LEAF_MAX_SPLIT_SLICES) must not silently accept one more - the
            # extra stage would be a bare register around logic that never
            # shrinks (RAW_VHDL module docstring). The real enforcement is
            # upstream in planning (SWEEP.PLAN_CUTS never requests a cut
            # here once the landscape marks the rest of the span illegal),
            # so this should essentially never fire; it exists to fail loud
            # (matching this function's own ADD_SLICE/CHECK_CUTS_VS_LATENCY
            # style) instead of silently producing a wasted stage if some
            # other slice-adding path (coarse/mini-sweep even-fraction
            # guesses, a future caller) ever disagrees with the landscape.
            if len(submodule_logic.submodule_instances) == 0:
                max_slices = RAW_VHDL.LEAF_MAX_SPLIT_SLICES(submodule_logic)
                if (
                    max_slices is not None
                    and len(submodule_timing_params._slices) >= max_slices
                ):
                    continue

            # Slice into that submodule
            skip_boundary_slice = False
            TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
                submodule_inst_name,
                submodule_logic,
                slice_pos,
                parser_state,
                TimingParamsLookupTable,
                skip_boundary_slice,
                write_files,
            )

            # Might be bad slice
            if type(TimingParamsLookupTable) is int:
                # Slice into submodule was bad
                if print_debug:
                    print("Adding slice", slice_pos)
                    print("To", submodule_inst)
                    print("Submodule Slice index", TimingParamsLookupTable)
                    print("Container slice index", slice_index)
                    print("Was bad")
                # Return the slice in the container that was bad
                return slice_index

    if write_files:
        # Final write package
        # Write VHDL file for submodule
        # Re write submodule package with updated timing params
        timing_params = TimingParamsLookupTable[inst_name]
        syn_out_dir = SYN.GET_OUTPUT_DIRECTORY(logic)
        if not os.path.exists(syn_out_dir):
            os.makedirs(syn_out_dir)
        VHDL.WRITE_LOGIC_ENTITY(
            inst_name, logic, syn_out_dir, parser_state, TimingParamsLookupTable
        )

    return TimingParamsLookupTable


# Returns index of bad slices or working TimingParamsLookupTable
def ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
    inst_name,
    logic,
    current_slices,
    parser_state,
    TimingParamsLookupTable,
    write_files=True,
    rounding_so_fuck_it=False,
):
    # Sanity check
    if not FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
        logic.func_name, parser_state
    ):
        raise Exception("Trying to slice into", inst_name, "for no reason...")

    # Do slice to main logic for each slice
    for current_slice_i in current_slices:
        # print "  current_slice_i:",current_slice_i
        skip_boundary_slice = False
        write_files_in_loop = False
        TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
            inst_name,
            logic,
            current_slice_i,
            parser_state,
            TimingParamsLookupTable,
            skip_boundary_slice,
            write_files_in_loop,
            rounding_so_fuck_it,
        )
        # Might be bad slice
        if type(TimingParamsLookupTable) is int:
            return TimingParamsLookupTable

    if write_files:
        # Do one final dumb loop over all timing params that arent zero clocks?
        # because write_files_in_loop = False above
        for inst_name_to_wr in TimingParamsLookupTable:
            wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
            wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
            if not wr_timing_params.IS_EMPTY():
                wr_syn_out_dir = SYN.GET_OUTPUT_DIRECTORY(wr_logic)
                if not os.path.exists(wr_syn_out_dir):
                    os.makedirs(wr_syn_out_dir)
                VHDL.WRITE_LOGIC_ENTITY(
                    inst_name_to_wr,
                    wr_logic,
                    wr_syn_out_dir,
                    parser_state,
                    TimingParamsLookupTable,
                )

    return TimingParamsLookupTable


def GET_BEST_GUESS_IDEAL_SLICES(latency):
    # Build ideal slices at this latency
    chunks = latency + 1
    slice_per_chunk = 1.0 / chunks
    slice_total = 0
    ideal_slices = []
    for i in range(0, latency):
        slice_total += slice_per_chunk
        ideal_slices.append(slice_total)

    return ideal_slices


# Todo just coarse for now until someone other than me care to squeeze performance?
# Course then fine - knowhaimsayin
def HARVEST_AUTO_PIPELINE_LATENCIES(parser_state, TimingParamsLookupTable):
    """Collect the discovered pipeline latency of every AUTO_PIPELINE-tagged
    submodule instance, grouped by the tag's canonical latency-cache key
    (pypeline.AUTO_PIPELINE.canonical_key, recorded per local submodule in
    Logic.sub_inst_to_auto_pipeline_key by the Pypeline elaborator).

    Returns (latencies, divergences):
      latencies:   canonical_key -> latency (int) for keys whose instances
                   all agree
      divergences: canonical_key -> {full inst path -> latency} for keys
                   whose instantiations were given different stage counts by
                   the sweep -- legal per-instance in the framework, but
                   unrepresentable as the single .latency int the design's
                   Python reads, so the driver errors on these.
    Pure in-memory walk over already-computed sweep results: no synthesis, no
    file I/O -- a no-AUTO_PIPELINE design pays only this walk (returns ({},{})).

    Every cached latency/hash in the table is invalidated first (same
    rationale as WRITE_FINAL_FILES): the sweep planner mutates submodule
    _slices after container totals were first memoized, so a memoized
    GET_TOTAL_LATENCY here can be stale -- e.g. a container whose memo was
    computed before its built-in div submodules received their own slices
    reports only its own cut count while the entity actually written (and
    confirmed by synthesis) is the deeper fresh total. The harvested value
    feeds .latency AND the native simulator's delay lines, both of which must
    match the VHDL actually built.
    """
    if TimingParamsLookupTable:
        for timing_params in TimingParamsLookupTable.values():
            timing_params.INVALIDATE_CACHE()
    key_to_inst_latencies = {}
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        if not logic.sub_inst_to_auto_pipeline_key:
            continue
        for local_sub, canonical_key in logic.sub_inst_to_auto_pipeline_key.items():
            if canonical_key is None:
                continue
            sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + local_sub
            sub_timing_params = TimingParamsLookupTable.get(sub_inst)
            if sub_timing_params is None:
                continue
            latency = sub_timing_params.GET_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
            key_to_inst_latencies.setdefault(canonical_key, {})[sub_inst] = latency
    latencies = {}
    divergences = {}
    for canonical_key, inst_latencies in key_to_inst_latencies.items():
        unique_latencies = set(inst_latencies.values())
        if len(unique_latencies) > 1:
            divergences[canonical_key] = dict(inst_latencies)
        else:
            latencies[canonical_key] = unique_latencies.pop()
    return latencies, divergences


def SEED_TIMING_PARAMS_FROM_PREVIOUS(
    prev_parser_state,
    prev_TimingParamsLookupTable,
    parser_state,
    TimingParamsLookupTable,
):
    """Carry the previous pass's sweep solution (slices + IO reg flags) into
    this pass's fresh zero-clock TimingParamsLookupTable so the stage-count
    discovery isn't redone: the pin-and-confirm loop then needs only one
    confirmation synthesis instead of a full sweep.

    Two-tier instance matching:
      a) exact full instance path (same func there too), else
      b) func name (entity name). Load-bearing, not a nicety: entity names
         encode closure values, so a .latency-derived parameter change (e.g.
         FIFO depth) renames its factory-closure entity and every instance
         path underneath it -- exactly where the AUTO_PIPELINE'd core lives.
         The core func's own name is stable (its closure captures only the
         user's func), so the func-name tier recovers its pipelining.
    Instances with no match in either tier keep zero slices -- correct for
    genuinely-new entities (the resized FIFO / widened counter: stateful,
    never sliced).

    Returns (TimingParamsLookupTable, unseeded_auto_pipeline_insts):
    unseeded_auto_pipeline_insts lists AUTO_PIPELINE-tagged instances whose
    func didn't exist at all in the previous pass -- i.e. the set of
    AUTO_PIPELINE call sites changed between passes (Python control flow
    branching on .latency's own value), which the driver makes a hard error.
    """
    # All func names that existed last pass (for the call-site-change check:
    # a tagged func whose discovered latency was 0 legitimately has empty
    # params and must NOT be flagged just for lacking a non-empty seed)
    prev_func_names = set()
    # func name -> representative non-empty previous TimingParams
    prev_func_to_params = {}
    for prev_inst, prev_params in prev_TimingParamsLookupTable.items():
        prev_logic = prev_parser_state.LogicInstLookupTable.get(prev_inst)
        if prev_logic is None:
            continue
        prev_func_names.add(prev_logic.func_name)
        if (
            prev_logic.func_name not in prev_func_to_params
            and not prev_params.IS_EMPTY()
        ):
            prev_func_to_params[prev_logic.func_name] = prev_params

    for inst_name, timing_params in TimingParamsLookupTable.items():
        logic = parser_state.LogicInstLookupTable[inst_name]
        prev_params = None
        exact = prev_TimingParamsLookupTable.get(inst_name)
        if exact is not None:
            prev_logic = prev_parser_state.LogicInstLookupTable.get(inst_name)
            if prev_logic is not None and prev_logic.func_name == logic.func_name:
                prev_params = exact
        if prev_params is None:
            prev_params = prev_func_to_params.get(logic.func_name)
        if prev_params is None or prev_params.IS_EMPTY():
            continue
        # Setters invalidate calcd_total_latency/hash_ext caches themselves
        timing_params.SET_SLICES(prev_params._slices)
        timing_params.SET_HAS_IN_REGS(prev_params._has_input_regs)
        timing_params.SET_HAS_OUT_REGS(prev_params._has_output_regs)

    # No cache computed against the previous pass's state may survive into
    # this table: the SET_* setters above no-op (keeping cached
    # hash_ext/calcd_total_latency strings) when the seeded value equals the
    # current one, and cached hash chains embed child func names that pass-2
    # re-elaboration may have renamed. Stale strings here leak pass-1 entity
    # references into the final top/file list (the shared wireguard GHDL
    # "unit not found" failure). Lazily recomputed against current state.
    for timing_params in TimingParamsLookupTable.values():
        timing_params.INVALIDATE_CACHE()

    unseeded = set()
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        if not logic.sub_inst_to_auto_pipeline_key:
            continue
        for local_sub, canonical_key in logic.sub_inst_to_auto_pipeline_key.items():
            if canonical_key is None:
                continue
            sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + local_sub
            sub_logic = parser_state.LogicInstLookupTable.get(sub_inst)
            if sub_logic is None:
                continue
            if sub_logic.func_name not in prev_func_names:
                unseeded.add(sub_inst)
    return TimingParamsLookupTable, sorted(unseeded)


def AUTO_PIPELINE_DIVERGENCE_EXIT(divergences):
    for key, inst_latencies in sorted(divergences.items()):
        print(f"AUTO_PIPELINE: {key}:")
        for sub_inst, lat in sorted(inst_latencies.items()):
            print(f"  {lat} clks : {sub_inst}")
    sys.exit(
        "AUTO_PIPELINE: ambiguous .latency: the above call site(s) are "
        "instantiated multiple times with different discovered stage "
        "counts, which a single .latency int cannot represent. Give "
        "each call site its own factory-produced closure, or pin an "
        "explicit latency=N."
    )


def CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(parser_state, TimingParamsLookupTable):
    """Safety net: every constrained AUTO_PIPELINE call site (latency=N /
    max_latency=M, or C #pragma AUTOPIPELINE N) must have been built within
    its constraint -- the sweep's region enforcement (SWEEP.
    ENFORCE_AUTO_PIPELINE_REGIONS) guarantees it, and this exits loudly if any
    path to final files ever did not. Walks Logic.sub_inst_to_auto_pipeline_
    latency, so it covers C designs (no latency-cache key) too."""
    if not TimingParamsLookupTable:
        return
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    checks = []
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        for local_sub, constraint in logic.sub_inst_to_auto_pipeline_latency.items():
            if constraint is None or constraint.upper_bound() is None:
                continue
            sub_inst = inst_name + marker + local_sub
            if sub_inst in TimingParamsLookupTable:
                checks.append((sub_inst, constraint))
    if not checks:
        return
    for timing_params in TimingParamsLookupTable.values():
        timing_params.INVALIDATE_CACHE()
    problems = []
    for sub_inst, constraint in checks:
        built = TimingParamsLookupTable[sub_inst].GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )
        cap = constraint.upper_bound()
        if built > cap or (constraint.is_fixed() and built != cap):
            problems.append(
                f"  {sub_inst}: {constraint.describe()} but {built} clks built"
            )
    if problems:
        print("\n".join(problems), flush=True)
        sys.exit(
            "AUTO_PIPELINE: built latency violates the call site latency "
            "constraint(s) above (internal error)."
        )


def AUTO_PIPELINE_SERVED_VALUES_MATCH(served, latencies):
    """True when every .latency value the design's Python consumed (served:
    canonical_key -> set of values returned) already equals the stage count
    harvested for that key -- the design as elaborated is consistent with the
    hardware built, so no re-elaboration pass is needed. A read key with no
    harvested instance would be served the same value again next pass."""
    for key, values in served.items():
        if len(values) != 1:
            return False
        if key in latencies and latencies[key] not in values:
            return False
    return True


def DO_AUTO_PIPELINE_LATENCY_PASSES(parser_state, multimain_timing_params, src_file):
    """AUTO_PIPELINE .latency pin-and-confirm passes (Pypeline designs only, see
    docs/AUTO_PIPELINE_DESIGN.md): if the design's Python read any AUTO_PIPELINE(...).latency,
    re-execute it with the discovered stage counts installed so those reads resolve to
    real values (e.g. for FIFO sizing), carrying the sweep's pipelining over as pinned
    seeds so only one confirmation synthesis is needed instead of a fresh sweep. A
    design with no AUTO_PIPELINE call sites, or one that never reads .latency, pays
    nothing beyond the in-memory harvest walk below."""
    import pypeline
    import SWEEP

    latencies, divergences = HARVEST_AUTO_PIPELINE_LATENCIES(
        parser_state, multimain_timing_params.TimingParamsLookupTable
    )
    if divergences:
        AUTO_PIPELINE_DIVERGENCE_EXIT(divergences)
    CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(
        parser_state, multimain_timing_params.TimingParamsLookupTable
    )
    # AUTO_MULTI_CYCLE counts ride the same passes: the sweep may have constrained a
    # multi-cycle path with a count the design's handshake wasn't built for
    auto_multi_cycle = AUTO_MULTI_CYCLE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(parser_state, multimain_timing_params)
    auto_multi_cycle_match = AUTO_MULTI_CYCLE.AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED(parser_state, auto_multi_cycle)
    if auto_multi_cycle and auto_multi_cycle_match:
        print(
            "AUTO_MULTI_CYCLE: every .latency read matched the built multi-cycle count",
            flush=True,
        )
        AUTO_MULTI_CYCLE.PRINT_AUTO_MULTI_CYCLE_NCYCLES(auto_multi_cycle)
    if auto_multi_cycle_match and not (latencies and pypeline.AUTO_PIPELINE_LATENCY_WAS_READ()):
        return parser_state, multimain_timing_params
    if (
        auto_multi_cycle_match
        and pypeline.AUTO_PIPELINE_BUILD_MODE() is not None
        and (
            AUTO_PIPELINE_SERVED_VALUES_MATCH(
                pypeline.AUTO_PIPELINE_SERVED_LATENCIES(), latencies
            )
        )
    ):
        # Fixed latency=N call sites, a correct start_latency=S guess, or a
        # discovered 0: what the Python read is what was built.
        print(
            "AUTO_PIPELINE: every .latency read matched the built stage count; "
            "skipping pin-and-confirm pass 2",
            flush=True,
        )
        for key, lat in sorted(latencies.items()):
            print(f"AUTO_PIPELINE {key}: {lat} clks", flush=True)
        return parser_state, multimain_timing_params

    import PY_TO_LOGIC
    auto_pipeline_pass = 1
    last_change_desc = None
    while True:
        auto_pipeline_pass += 1
        if auto_pipeline_pass > AUTO_PIPELINE_MAX_LATENCY_PASSES:
            sys.exit(
                f"AUTO_PIPELINE: .latency did not settle within "
                f"{AUTO_PIPELINE_MAX_LATENCY_PASSES} passes "
                f"(last change: {last_change_desc}). A "
                f".latency-derived design change is perturbing timing "
                f"enough to change the discovered stage count itself. "
                f"Pin an explicit latency=N at the unstable call site "
                f"to break the loop."
            )
        print(
            f"================== AUTO_PIPELINE Pass {auto_pipeline_pass}: "
            f"Re-elaborating with Discovered Latencies ================================",
            flush=True,
        )
        for key, lat in sorted(latencies.items()):
            print(f"AUTO_PIPELINE {key}: {lat} clks", flush=True)
        AUTO_MULTI_CYCLE.PRINT_AUTO_MULTI_CYCLE_NCYCLES(auto_multi_cycle)
        prev_parser_state = parser_state
        prev_tpl = multimain_timing_params.TimingParamsLookupTable
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(latencies)
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE(auto_multi_cycle)
        parser_state = PY_TO_LOGIC.PARSE_FILE(src_file)
        C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(parser_state)
        parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state)
        seeded_tpl, unseeded_ap_insts = SEED_TIMING_PARAMS_FROM_PREVIOUS(
            prev_parser_state,
            prev_tpl,
            parser_state,
            GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state),
        )
        if unseeded_ap_insts:
            sys.exit(
                "AUTO_PIPELINE: the set of AUTO_PIPELINE call sites "
                "changed between passes -- Python control flow (or an "
                "AUTO_PIPELINE'd function's closure-captured values, "
                "which are encoded in its identity) must not depend "
                "on .latency's own value; only sizing outside "
                "AUTO_PIPELINE'd functions may. New instance(s) with "
                "no previous-pass counterpart: " + ", ".join(unseeded_ap_insts)
            )
        seeded_tpl = REENFORCE_AUTO_PIPELINE_REGIONS(parser_state, seeded_tpl)
        multimain_timing_params = MultiMainTimingParams()
        multimain_timing_params.TimingParamsLookupTable = seeded_tpl
        multimain_timing_params, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(
            parser_state, multimain_timing_params
        )
        new_latencies, divergences = HARVEST_AUTO_PIPELINE_LATENCIES(
            parser_state, multimain_timing_params.TimingParamsLookupTable
        )
        if divergences:
            AUTO_PIPELINE_DIVERGENCE_EXIT(divergences)
        CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(
            parser_state, multimain_timing_params.TimingParamsLookupTable
        )
        new_auto_multi_cycle = AUTO_MULTI_CYCLE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(parser_state, multimain_timing_params)
        if new_latencies == latencies and new_auto_multi_cycle == auto_multi_cycle:
            # The .latency values this pass's Python consumed equal
            # the stage counts actually built -- converged. (Meeting
            # timing alone is NOT sufficient to stop: realizing the
            # seeded fractional slices hierarchically -- e.g. into
            # pipelined built-in div/mult entities with their own
            # stage granularity -- can change an instance's total
            # latency even on a passing confirmation run, and exiting
            # then would build VHDL whose actual depth contradicts
            # every .latency-derived constant baked into it, and
            # desync the native simulator's latency emulation.)
            break
        last_change_desc = ", ".join(
            f"{key}: {latencies.get(key)} -> {new_latencies.get(key)} clks"
            for key in sorted(set(latencies) | set(new_latencies))
            if latencies.get(key) != new_latencies.get(key)
        )
        auto_multi_cycle_change_desc = ", ".join(
            f"AUTO_MULTI_CYCLE {key}: {auto_multi_cycle.get(key)} -> {new_auto_multi_cycle.get(key)} cycles"
            for key in sorted(set(auto_multi_cycle) | set(new_auto_multi_cycle))
            if auto_multi_cycle.get(key) != new_auto_multi_cycle.get(key)
        )
        last_change_desc = ", ".join(
            d for d in (last_change_desc, auto_multi_cycle_change_desc) if d
        )
        print(
            "AUTO_PIPELINE: "
            + ("slice realization" if met else "fallback sweep")
            + f" changed discovered latencies ({last_change_desc}); "
            "re-elaborating...",
            flush=True,
        )
        latencies = new_latencies
        auto_multi_cycle = new_auto_multi_cycle

    return parser_state, multimain_timing_params


# Auto-pipelined RAMs: fixed-latency implementations measured by the
# ordinary throughput sweep, re-elaborating callers after each topology change.


@dataclass(frozen=True)
class RamPlan:
    input_regs: int = 0
    output_regs: int = 0
    split_depth: int = 0
    request_levels: int = 0
    response_levels: int = 0

    @property
    def latency(self):
        return (
            1
            + self.input_regs
            + self.output_regs
            + self.request_levels
            + self.response_levels
        )

    @property
    def write_stage(self):
        return self.input_regs + self.request_levels

    @property
    def read_after_write_gap(self):
        return 1 + self.write_stage

    @property
    def banks(self):
        return 1 << self.split_depth

    @property
    def fingerprint(self):
        return hashlib.sha256(repr(self).encode()).hexdigest()[:12]

    def record(self):
        return dict(
            asdict(self),
            latency=self.latency,
            banks=self.banks,
            read_after_write_gap=self.read_after_write_gap,
        )


def RAM_VALIDATE_CONSTRAINTS(latency, start_latency, max_latency):
    for name, value in (
        ("latency", latency),
        ("start_latency", start_latency),
        ("max_latency", max_latency),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"make_auto_pipeline_ram: {name} must be an integer >= 1")
    if latency is not None and (start_latency is not None or max_latency is not None):
        raise ValueError(
            "make_auto_pipeline_ram: latency cannot be combined with start_latency/max_latency"
        )
    if (
        start_latency is not None
        and max_latency is not None
        and start_latency > max_latency
    ):
        raise ValueError("make_auto_pipeline_ram: start_latency exceeds max_latency")


def RAM_VALIDATE_PORTS(ports):
    writers = sum(p != "r" for p in ports)
    if writers > 1 and (writers > 2 or len(ports) > 2):
        raise ValueError(
            "make_auto_pipeline_ram: unsupported BRAM port configuration; use one writer "
            "with any number of readers, or at most two physical rw/w/r ports"
        )


def RAM_MAX_SPLIT_DEPTH(size, width, ports, byte_write_enables):
    # ECP5: 16K data bits; 9/18/36-bit configurations include parity lanes.
    # The 36-bit SDP mode does not provide independently enabled byte lanes.
    max_width = (
        36 if sum(p != "r" for p in ports) <= 1 and not byte_write_enables else 18
    )
    physical_width = next(
        (w for w in (1, 2, 4, 9, 18, 36) if w >= width and w <= max_width), max_width
    )
    depth = {1: 16384, 2: 8192, 4: 4096, 9: 2048, 18: 1024, 36: 512}[physical_width]
    return max(0, (size - 1).bit_length() - int(math.log2(depth)))


def RAM_CANDIDATES(
    size,
    width,
    ports,
    byte_write_enables,
    latency=None,
    start_latency=None,
    max_latency=None,
):
    plans = [RamPlan(), RamPlan(output_regs=1), RamPlan(input_regs=1), RamPlan(1, 1)]
    for d in range(1, RAM_MAX_SPLIT_DEPTH(size, width, ports, byte_write_enables) + 1):
        plans.extend(
            (
                RamPlan(1, 1, d, d - 1, d),
                RamPlan(1, 1, d, d, d - 1),
                RamPlan(1, 1, d, d, d),
            )
        )
    if latency is not None:
        plans = [
            replace(p, output_regs=p.output_regs + latency - p.latency)
            for p in plans
            if p.latency <= latency
        ]
        # Prefer useful routing stages to delay padding for the native default.
        plans.sort(
            key=lambda p: (
                -p.split_depth,
                -p.request_levels - p.response_levels,
                -min(p.input_regs, 1),
                p.output_regs,
            )
        )
    else:
        plans = [p for p in plans if max_latency is None or p.latency <= max_latency]
        if start_latency is not None:
            lower = [p for p in plans if p.latency < start_latency]
            plans = [p for p in plans if p.latency >= start_latency]
            if not plans or plans[0].latency > start_latency:
                start = (
                    RamPlan(1, start_latency - 2)
                    if start_latency >= 3
                    else RamPlan(0, start_latency - 1)
                )
                plans.insert(0, start)
            plans += lower  # start is a bootstrap guess, not a lower bound
    return list(dict.fromkeys(plans))


def RAM_COLLECT(parser_state):
    entries = getattr(parser_state, "auto_pipeline_rams", {})
    instances = getattr(parser_state, "FuncToInstances", {})
    return {name: entry for name, entry in entries.items() if instances.get(name)}


def RAM_PLANS_FROM_STATE(parser_state):
    return {entry["key"]: entry["plan"] for entry in RAM_COLLECT(parser_state).values()}


def RAM_VALIDATE_BACKEND(parser_state):
    import SYN
    import OPEN_TOOLS

    if (
        RAM_COLLECT(parser_state)
        and SYN.SYN_TOOL is not None
        and (
            SYN.SYN_TOOL is not OPEN_TOOLS
            or not str(parser_state.part).upper().startswith("LFE5")
        )
    ):
        raise ValueError(
            "make_auto_pipeline_ram: synthesis currently requires ECP5 OPEN_TOOLS "
            "(--syn_tool open_tools); other backends have not been validated"
        )


def RAM_REPORT_PLANS(parser_state):
    return {
        entry["key"]: dict(
            entry["options"],
            **entry["plan"].record(),
            constraints={
                k: entry["options"][k]
                for k in ("latency", "start_latency", "max_latency")
            },
        )
        for entry in RAM_COLLECT(parser_state).values()
    }


def RAM_SEARCH(parser_state, args, src_file, build):
    """Measure a bounded frontier, then trim each RAM against the whole design.

    Advancing all groups permits progress when several RAMs tie for the critical
    path. Per-group trim and same-latency probes recover unnecessary registers.
    Every probe uses the ordinary logic sweep, so RAM/operator timing is checked
    together. No fractional pipeline cut ever enters a memory.
    """
    import C_TO_LOGIC
    import PY_TO_LOGIC
    import SYN
    import SWEEP
    import pypeline

    RAM_VALIDATE_BACKEND(parser_state)
    entries = {e["key"]: e for e in RAM_COLLECT(parser_state).values()}
    choices = {key: RAM_CANDIDATES(**entry["options"]) for key, entry in entries.items()}
    initial = RAM_PLANS_FROM_STATE(parser_state)
    history, measured = [], {}
    original_part = parser_state.part

    def evaluate(plans, state=None):
        signature = tuple(sorted(plans.items()))
        pypeline.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(plans)
        if state is None:
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
            state = PY_TO_LOGIC.PARSE_FILE(src_file)
            state.part = original_part
            if set(RAM_PLANS_FROM_STATE(state)) != set(initial):
                raise ValueError(
                    "auto-pipelined RAM call sites changed during plan re-elaboration"
                )
            C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)
        print(
            "AUTO_PIPELINE_RAM candidate: "
            + ", ".join(f"{k[:12]} {p.record()}" for k, p in sorted(plans.items())),
            flush=True,
        )
        state, timing = build(state)
        report = SYN.SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(state, timing)
        clocks, _ = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(state)
        mhz = {
            clk: 1000.0 / path.path_delay_ns
            for clk, path in report.path_reports.items()
            if path.path_delay_ns
        }
        ratios = [
            frequency / clocks[clk] for clk, frequency in mhz.items() if clocks.get(clk)
        ]
        met = not getattr(timing, "sweep_timing_failures", []) and all(
            r >= 1.0 for r in ratios
        )
        resources = getattr(report, "ram_resources", {})
        record = dict(
            iteration=len(history),
            plans={k: p.record() for k, p in plans.items()},
            achieved_mhz=mhz,
            met=met,
            resources=resources,
        )
        history.append(record)
        # Prefer meeting the goal, fewer cycles, then lower area. On failure
        # retain the highest measured worst-clock/goal ratio.
        area = (
            resources.get("DP16KD", 0),
            resources.get("LUT4", 0),
            resources.get("DFF", 0),
        )
        score = (
            met,
            -sum(p.latency for p in plans.values())
            if met
            else min(ratios or [min(mhz.values(), default=0)]),
            tuple(-n for n in area),
            -sum(p.latency for p in plans.values()),
        )
        result = (score, dict(plans), state, timing, record)
        measured[signature] = result
        return result

    best = evaluate(initial, parser_state)
    has_goal = any(SYN.GET_TARGET_MHZ(main, best[2]) for main in best[2].main_mhz)
    if has_goal:
        for step in range(max(map(len, choices.values()))):
            plans = {
                key: options[min(step, len(options) - 1)]
                for key, options in choices.items()
            }
            signature = tuple(sorted(plans.items()))
            trial = measured.get(signature) or evaluate(plans)
            if trial[0] > best[0]:
                best = trial
            if best[0][0]:
                break
        if best[0][0]:
            for key in sorted(choices):
                for plan in sorted(choices[key], key=lambda p: p.latency):
                    if plan.latency > best[1][key].latency:
                        continue
                    plans = dict(best[1], **{key: plan})
                    signature = tuple(sorted(plans.items()))
                    trial = measured.get(signature) or evaluate(plans)
                    if trial[0] > best[0]:
                        best = trial

    # Reinstall the winning graph and regenerate final files/history after
    # losing probes. Cached synthesis results make this confirmation cheap.
    winner = evaluate(best[1]) if history[-1] is not best[4] else best
    state, timing = winner[2], winner[3]
    pypeline.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(best[1])
    if not winner[0][0]:
        reason = "auto-pipelined RAM latency limit or useful BRAM subdivision exhausted"
        print("AUTO_PIPELINE_RAM: " + reason, flush=True)
        timing.sweep_timing_failures = [
            (main, goal, achieved, reason + "; " + why)
            for main, goal, achieved, why in getattr(
                timing, "sweep_timing_failures", []
            )
        ]
    timing.auto_pipeline_ram_history = history
    output = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, SYN.TOP_LEVEL_MODULE)
    os.makedirs(output, exist_ok=True)
    with open(os.path.join(output, "auto_pipeline_ram_history.json"), "w") as f:
        json.dump(dict(selected=RAM_REPORT_PLANS(state), iterations=history), f, indent=2)
    for key, plan in best[1].items():
        print(
            f"AUTO_PIPELINE_RAM {key}: {plan.latency} clocks, {plan.banks} banks, read_after_write_gap={plan.read_after_write_gap}",
            flush=True,
        )
    SWEEP.WRITE_SWEEP_HISTORY(state, timing, build_complete=True)
    return state, timing


def DO_SWEEP_AND_AUTO_PIPELINE(parser_state, args, src_file, _ram_search=True):
    """Measure delays, run the throughput sweep, then converge AUTO_PIPELINE
    .latency feedback -- i.e. everything between "here is an elaborated design"
    and "here is a pipelined design whose Python agrees with what was built".

    Factored out of DO_PIPELINED_BUILD because AUTO_FSM.DO_SCHEDULE_PASSES wraps this
    whole thing in an outer loop of its own (schedule the FSMs -> re-elaborate ->
    build; if an FSM is blamed for missing timing, reschedule it into more states and
    go again). Returns the final (parser_state, multimain_timing_params): the
    AUTO_PIPELINE loop below re-parses the design internally, so the parser_state
    handed in is not necessarily the one that comes back out.
    """
    import SWEEP

    if RAM_COLLECT(parser_state):
        RAM_VALIDATE_BACKEND(parser_state)
        if _ram_search and not args.comb and not args.yosys_json and not args.no_sweep:
            return RAM_SEARCH(
                parser_state, args, src_file,
                lambda state: DO_SWEEP_AND_AUTO_PIPELINE(state, args, src_file, False),
            )

    if not args.comb and not args.yosys_json:
        if src_file.endswith(".py"):
            # Before any synthesis time is spent on a design that can't work
            AUTO_MULTI_CYCLE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ(parser_state)
        print(
            "================== Adding Timing Information from Synthesis Tool ================================",
            flush=True,
        )
        parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state)

    print(
        "================== Beginning Throughput Sweep ================================",
        flush=True,
    )
    multimain_timing_params = SWEEP.DO_THROUGHPUT_SWEEP(
        parser_state,
        coarse_only=args.coarse,
        starting_guess_latency=args.start,
        do_incremental_guesses=not (args.sweep),
        comb_only=args.comb,
        stop_at_latency=args.stop,
    )

    if src_file.endswith(".py") and not args.comb and not args.yosys_json:
        parser_state, multimain_timing_params = DO_AUTO_PIPELINE_LATENCY_PASSES(
            parser_state, multimain_timing_params, src_file
        )

    return parser_state, multimain_timing_params


def DO_PIPELINED_BUILD(parser_state, args, src_file):
    """Dispatch to the AUTO_FSM schedule-and-confirm loop when the design contains
    AUTO_FSM call sites, otherwise straight to the sweep + AUTO_PIPELINE convergence
    flow. Both paths return (parser_state, multimain_timing_params)."""
    auto_fsm_possible = (
        src_file.endswith(".py") and not args.comb and not args.yosys_json
    )
    if auto_fsm_possible:
        import AUTO_FSM

        auto_fsm_possible = AUTO_FSM.DESIGN_HAS_AUTO_FSM(parser_state)
    if auto_fsm_possible:
        import AUTO_FSM

        return AUTO_FSM.DO_SCHEDULE_PASSES(parser_state, args, src_file)
    return DO_SWEEP_AND_AUTO_PIPELINE(parser_state, args, src_file)


def WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(
    TimingParamsLookupTable, parser_state, extra_insts=None
):
    # extra_insts: additional instances to write even though their own timing
    # params are empty - ancestors of modified instances whose rendered
    # entity (names of instantiated children) changed (see
    # INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES)
    entities_written = set()
    for inst_name_to_wr in TimingParamsLookupTable:
        wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
        wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
        needs_write = not wr_timing_params.IS_EMPTY() or (
            extra_insts is not None and inst_name_to_wr in extra_insts
        )
        if needs_write:
            # Same skips as the syn file list (GET_VHDL_FILES_TCL_TEXT_AND_TOP)
            if (
                wr_logic.is_vhdl_func
                or wr_logic.is_vhdl_expr
                or wr_logic.func_name == C_TO_LOGIC.VHDL_FUNC_NAME
                or wr_logic.is_clock_crossing
            ):
                continue
            entity_name = VHDL.GET_ENTITY_NAME(
                inst_name_to_wr, wr_logic, TimingParamsLookupTable, parser_state
            )
            if entity_name not in entities_written:
                entities_written.add(entity_name)
                wr_syn_out_dir = SYN.GET_OUTPUT_DIRECTORY(wr_logic)
                if not os.path.exists(wr_syn_out_dir):
                    os.makedirs(wr_syn_out_dir)
                wr_filename = wr_syn_out_dir + "/" + entity_name + ".vhd"
                if not os.path.exists(wr_filename):
                    VHDL.WRITE_LOGIC_ENTITY(
                        inst_name_to_wr,
                        wr_logic,
                        wr_syn_out_dir,
                        parser_state,
                        TimingParamsLookupTable,
                    )


def INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(TimingParamsLookupTable, parser_state):
    # The zero clock timing params table is deep copied from a cached master
    # with latency/hash caches already computed. Adding slices invalidates the
    # caches of the sliced instances themselves, but instances ABOVE a
    # modified instance still carry stale zero clock hashes - their entity
    # names and rendered contents (names of instantiated children) must change
    # too. Invalidate all ancestors of any modified instance and return the
    # ancestor set so callers can (re)write their entity files.
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    ancestors = set()
    for inst_name, timing_params in TimingParamsLookupTable.items():
        if timing_params.IS_EMPTY():
            continue
        toks = inst_name.split(marker)
        for i in range(1, len(toks)):
            ancestors.add(marker.join(toks[0:i]))
    for ancestor_inst in ancestors:
        if ancestor_inst in TimingParamsLookupTable:
            TimingParamsLookupTable[ancestor_inst].INVALIDATE_CACHE()
    return ancestors


def SET_INITIAL_COARSE_LATENCY_GUESS(
    inst_name, target_mhz, inst_sweep_state, parser_state, starting_guess_latency
):
    logic = parser_state.LogicInstLookupTable[inst_name]
    # Reasonable starting guess and coarse throughput strategy is dividing each main up to meet target
    # Dont even bother running multimain top as combinatorial logic
    inst_sweep_state.coarse_latency = 0
    inst_sweep_state.initial_guess_latency = 0
    if starting_guess_latency is None:
        if logic.delay is None or logic.delay_is_estimated:
            # Leaf presynth mode no longer force-synthesizes mains - measure
            # on demand (stateful-subtree funcs are skipped by MEASURE_DELAYS
            # and use their estimated delay for the initial guess; the coarse
            # loop grows from below and self-corrects)
            SYN.MEASURE_DELAYS([logic.func_name], parser_state)
            logic = parser_state.FuncLogicLookupTable[logic.func_name]
            if logic.delay is None:
                # No estimate either - derive one now
                SYN.ESTIMATE_HIER_PATH_DELAYS([logic.func_name], parser_state)
                logic = parser_state.FuncLogicLookupTable[logic.func_name]
        target_path_delay_ns = 1000.0 / target_mhz
        path_delay_ns = float(logic.delay) / SYN.DELAY_UNIT_MULT
        if path_delay_ns > 0.0:
            # curr_mhz = 1000.0 / path_delay_ns
            # How many multiples are we away from the goal
            mult = path_delay_ns / target_path_delay_ns
            if mult > 1.0:
                # Divide up into that many clocks as a starting guess
                # If doesnt have global wires
                if FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
                    logic.func_name, parser_state
                ):
                    clks = int(math.ceil(mult)) - 1
                    inst_sweep_state.coarse_latency = clks
                    inst_sweep_state.initial_guess_latency = clks
    else:
        if FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
            logic.func_name, parser_state
        ):
            inst_sweep_state.coarse_latency = starting_guess_latency
            inst_sweep_state.initial_guess_latency = starting_guess_latency


def BUILD_AND_WRITE_COARSE_SLICED_TIMING_PARAMS(
    inst_name, logic, inst_sweep_state, parser_state
):
    # Reset to zero clock
    print("Building timing params starting without added pipelining...", flush=True)
    # TODO dont need full copy of all other inst being zero clock too
    TimingParamsLookupTable = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)

    # Do slicing
    # Set the slices in timing params and then rebuild
    # Make even slices
    best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(inst_sweep_state.coarse_latency)
    print(
        logic.func_name,
        ": sliced coarsely ~=",
        inst_sweep_state.coarse_latency,
        "clocks latency added...",
        flush=True,
    )
    # Do slicing and dont write vhdl this way since slow
    write_files = False

    # Sanity
    if len(TimingParamsLookupTable[inst_name]._slices) != 0:
        print(
            "Not starting with comb logic for main? sliced already?",
            TimingParamsLookupTable[inst_name]._slices,
        )
        sys.exit(-1)

    # Constrained AUTO_PIPELINE regions under this instance: fixed latency=N
    # regions get exactly N registers and are locked BEFORE the even
    # fractions below are sliced down (slicing skips locked children)
    coarse_regions = COLLECT_AUTO_PIPELINE_REGIONS(
        parser_state, scope_inst=inst_name
    )
    fixed_regions = [r for r in coarse_regions if r.constraint.is_fixed()]
    if fixed_regions:
        try:
            TimingParamsLookupTable = ENFORCE_AUTO_PIPELINE_REGIONS(
                fixed_regions, parser_state, TimingParamsLookupTable
            )
        except AutoPipelineLatencyInfeasible as err:
            sys.exit(str(err))

    # Apply slices to main funcs
    TimingParamsLookupTable = (
        ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
            inst_name,
            logic,
            best_guess_slices,
            parser_state,
            TimingParamsLookupTable,
            write_files,
        )
    )
    # TimingParamsLookupTable == None
    # means these slices go through global code
    if type(TimingParamsLookupTable) is not dict:
        print("Slicing through globals still an issue?")
        sys.exit(-1)
        # print("Can't syn when slicing through globals!")
        # return None, None, None, None

    region_ancestor_insts = None
    if coarse_regions:
        # ...and max_latency=M regions the even fractions over-sliced are
        # re-planned down to M; every constrained region ends up locked
        TimingParamsLookupTable = REENFORCE_AUTO_PIPELINE_REGIONS(
            parser_state, TimingParamsLookupTable, scope_inst=inst_name
        )
        region_ancestor_insts = INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(
            TimingParamsLookupTable, parser_state
        )

    # Fast one time loop writing only files that have non default,>0 latency
    print("Updating output files...", flush=True)
    WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(
        TimingParamsLookupTable, parser_state, region_ancestor_insts
    )
    # Write estimate of FF usage
    SYN.WRITE_REGISTERS_ESTIMATE_FILE(parser_state, TimingParamsLookupTable, inst_name)
    SYN.WRITE_AREA_ESTIMATE_FILE(parser_state, TimingParamsLookupTable, inst_name)

    return TimingParamsLookupTable


def FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(func_name, parser_state):
    # Immediate yes if is raw HDL with no submodules and is sliceable, has delay
    func_logic = parser_state.FuncLogicLookupTable[func_name]
    if len(func_logic.submodule_instances) == 0:
        return not SYN.LOGIC_IS_ZERO_DELAY(func_logic, parser_state, allow_none_delay=True)
    # Recurse into submodule if can use pipelining
    # Return true if any submodule is true
    if func_logic.CAN_USE_AUTOPIPELINING(parser_state):
        for sub_inst in func_logic.submodule_instances:
            sub_func_name = func_logic.submodule_instances[sub_inst]
            if FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
                sub_func_name, parser_state
            ):
                return True
    return False


_FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache = {}


def FUNC_SUBTREE_HAS_AUTO_PIPELINE(func_name, parser_state):
    # Does this func (or anything below it) contain an AUTO_PIPELINE-tagged
    # call site? Such funcs are on the pipelining "estimate chain": slicing
    # descends through them, so their geometry (and thus submodule delays
    # along the way) is needed.
    if func_name in _FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache:
        return _FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache[func_name]
    logic = parser_state.FuncLogicLookupTable[func_name]
    rv = len(logic.sub_inst_to_auto_pipeline_latency) > 0
    if not rv:
        for sub_func_name in logic.submodule_instances.values():
            if sub_func_name in parser_state.FuncLogicLookupTable:
                if FUNC_SUBTREE_HAS_AUTO_PIPELINE(sub_func_name, parser_state):
                    rv = True
                    break
    _FUNC_SUBTREE_HAS_AUTO_PIPELINE_cache[func_name] = rv
    return rv


def BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS(parser_state):
    """Timing params for builds that run no throughput sweep (--comb,
    --no_synth, --yosys_json): zero added pipelining everywhere EXCEPT fixed
    AUTO_PIPELINE(func, latency=N) call sites (and C `#pragma AUTOPIPELINE N`),
    which get exactly N registers -- a fixed latency is a functional contract
    (.latency reads N, native sim delays by N), not a timing hint, so every
    build honors it.

    Placing N registers well still needs delays, so only those call sites'
    subtrees are measured (ADD_PATH_DELAY_TO_LOOKUP rooted at their funcs) and
    planned with the sweep's own count-targeted region enforcement. Without a
    timing-capable tool (no tool installed for the PART, or --yosys_json) the
    PyRTL delay model is borrowed for that measurement: the latency is exact,
    the stage balance an estimate.

    Returns None -- today's zero-added-pipelining path, untouched -- when the
    design has no fixed latency > 0. Memoized on parser_state (a --comb build
    asks twice: final files, then the comb characterization synthesis)."""
    cached = getattr(parser_state, "_fixed_auto_pipeline_timing_params", None)
    if cached is not None:
        return cached
    regions = COLLECT_AUTO_PIPELINE_REGIONS(parser_state, fixed_only=True)
    if not any(region.constraint.latency > 0 for region in regions):
        return None
    previous_tool = SYN.SYN_TOOL
    SYN.PART_SET_TOOL(parser_state.part, allow_fail=True)
    borrowed_tool = SYN.SYN_TOOL is None or OPEN_TOOLS.YOSYS_JSON_ONLY
    if borrowed_tool:
        print(
            "WARNING: no timing-capable synthesis tool for this build; placing "
            "fixed AUTO_PIPELINE latency= registers using PyRTL delay estimates "
            "(the latency is exact, the stage balance is estimated).",
            flush=True,
        )
        SYN.SYN_TOOL = PYRTL
    try:
        print(
            "================== Measuring Delays for Fixed AUTO_PIPELINE "
            "Latencies ================================",
            flush=True,
        )
        SYN.ADD_PATH_DELAY_TO_LOOKUP(
            parser_state,
            root_func_names=sorted(
                {r.func_name for r in regions if r.constraint.latency > 0}
            ),
        )
        TimingParamsLookupTable = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
        try:
            TimingParamsLookupTable = ENFORCE_AUTO_PIPELINE_REGIONS(
                regions, parser_state, TimingParamsLookupTable
            )
        except AutoPipelineLatencyInfeasible as err:
            sys.exit(str(err))
        ancestor_insts = INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(
            TimingParamsLookupTable, parser_state
        )
        WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(
            TimingParamsLookupTable, parser_state, ancestor_insts
        )
    finally:
        if borrowed_tool:
            SYN.SYN_TOOL = previous_tool
    CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(parser_state, TimingParamsLookupTable)
    for region in regions:
        print(
            f"AUTO_PIPELINE {region.label()} ({region.constraint.describe()}): "
            f"{region.realized} clk(s) built at {region.inst}",
            flush=True,
        )
    multimain_timing_params = MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
    parser_state._fixed_auto_pipeline_timing_params = multimain_timing_params
    return multimain_timing_params


def UPDATE_PIPELINE_MIN_PERIOD_CACHE(
    timing_report, TimingParamsLookupTable, parser_state, inst_name=None
):
    return  # Disabled for now - wasnt using anyway...
    # Make dir if needed
    cache_dir = SYN.GET_PATH_DELAY_CACHE_DIR(parser_state, "pipeline_min_period")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # pipeline 'number' record in filename is size of largest slice 0..1.0
    # Find all pipelined cachable func instances
    cacheable_pipelined_instances = set()
    for func_inst, timing_params in TimingParamsLookupTable.items():
        func_logic = parser_state.LogicInstLookupTable[func_inst]
        # Cacheable non user code?
        if SYN.IS_USER_CODE(func_logic, parser_state):
            continue
        # Pipelined?
        if len(timing_params._slices) <= 0:
            continue
        # Func is inside the func inst being talked about?
        if inst_name:
            if func_inst.startswith(inst_name):
                cacheable_pipelined_instances.add(func_inst)
        else:
            cacheable_pipelined_instances.add(func_inst)

    # Organize timing report into main func -> period ns
    # Includes logic for inst name coarse or multi main top
    main_to_period = {}
    if len(parser_state.main_mhz) == 1:  # TODO --coarse like finding of main needed?
        the_main_inst = list(parser_state.main_mhz.keys())[0]
        if len(timing_report.path_reports) > 1:
            raise Exception("Should only be one path group in timing report!")
        main_to_period[the_main_inst] = list(timing_report.path_reports.values())[
            0
        ].path_delay_ns
    elif inst_name:
        the_main_inst = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
            inst_name, parser_state
        )
        if len(timing_report.path_reports) > 1:
            raise Exception("Should only be one path group in timing report!")
        main_to_period[the_main_inst] = list(timing_report.path_reports.values())[
            0
        ].path_delay_ns
    else:
        for reported_clock_group in timing_report.path_reports:
            path_report = timing_report.path_reports[reported_clock_group]
            some_main_insts = SYN.GET_MAIN_INSTS_FROM_PATH_REPORT(
                path_report, parser_state, TimingParamsLookupTable
            )
            for main_inst in some_main_insts:
                main_to_period[main_inst] = path_report.path_delay_ns

    # For each pipelined instance try to update cache with
    # period from its main func
    for func_inst in cacheable_pipelined_instances:
        timing_params = TimingParamsLookupTable[func_inst]
        func_logic = parser_state.LogicInstLookupTable[func_inst]
        main_inst = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
            func_inst, parser_state
        )
        # Sometimes, especally when finally meeting timing,
        # the timing report might not have a critical path through
        # a cacheable pipelined instance
        # Could assume met timing, but for now just skip...
        if main_inst not in main_to_period:
            continue
        period_ns = main_to_period[main_inst]
        # Try to update cache
        # What is slicing, specifically largest slice?
        slice_sizes = RAW_VHDL.SLICES_TO_SIZE_LIST(timing_params._slices)
        max_slice_size = max(slice_sizes)
        func_key = SYN.GET_CACHED_LOGIC_FILE_KEY(func_logic, parser_state)
        # Does the file exist?
        out_filepath = cache_dir + "/" + func_key + f"_{max_slice_size:.2f}.delay"
        if not os.path.exists(out_filepath):
            f = open(out_filepath, "w")
            f.write(str(period_ns))
            f.close()
        # Enforce monotonic smaller slicing always increases fmax in cache
        func_cache_files = Path(cache_dir).glob(f"{func_key}*")
        for func_cache_filepath in func_cache_files:
            func_cache_file = os.path.basename(str(func_cache_filepath))
            cached_slice_size = float(
                func_cache_file.replace(".delay", "").split("_")[-1]
            )
            # those with smaller slices than current
            if cached_slice_size < max_slice_size:
                # Should have better timing
                f = open(func_cache_filepath, "r")
                cached_period_ns = float(f.read())
                f.close()
                # Update if not...
                if period_ns < cached_period_ns:
                    f = open(func_cache_filepath, "w")
                    f.write(str(period_ns))
                    f.close()
            # Those with larger slices should not be fast
            elif cached_slice_size > max_slice_size:
                # Should not have better timing
                f = open(func_cache_filepath, "r")
                cached_period_ns = float(f.read())
                f.close()
                # Update as needed
                if cached_period_ns < period_ns:
                    f = open(out_filepath, "w")
                    f.write(str(cached_period_ns))
                    f.close()


def WRITE_ALL_ZERO_CLK_VHDL(parser_state, ZeroClkTimingParamsLookupTable):
    # All instances are zero clock so just pick any instance
    for func_name in parser_state.FuncLogicLookupTable:
        if func_name in parser_state.FuncToInstances:
            inst_name = list(parser_state.FuncToInstances[func_name])[0]
            logic = parser_state.FuncLogicLookupTable[func_name]
            # ONly write non vhdl
            if (
                logic.is_vhdl_func
                or logic.is_vhdl_expr
                or (logic.func_name == C_TO_LOGIC.VHDL_FUNC_NAME)
            ):
                continue
            # Dont write clock cross funcs
            if logic.is_clock_crossing:
                continue
            # Dont write FSM funcs
            if logic.is_fsm_clk_func:
                continue
            # print("Writing function:", func_name, "...", flush=True)
            syn_out_dir = SYN.GET_OUTPUT_DIRECTORY(logic)
            if not os.path.exists(syn_out_dir):
                os.makedirs(syn_out_dir, exist_ok=True)
            VHDL.WRITE_LOGIC_ENTITY(
                inst_name,
                logic,
                syn_out_dir,
                parser_state,
                ZeroClkTimingParamsLookupTable,
            )

    # Include a zero clock multi main top too
    print("Writing multi main top level files...", flush=True)
    multimain_timing_params = MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = ZeroClkTimingParamsLookupTable
    is_final_top = False
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)
    # And clock cross entities
    VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)


# ─────────────────────────────────────────────
# Constrained AUTO_PIPELINE regions (latency= / start_latency= / max_latency=)
#
# Each constrained call site is a cut subtree of its own. The sweep's planner
# (SWEEP.py) plans its cuts like any other subtree; the functions here enforce
# the call site's count on that plan, feed timing failures back to the region,
# and snapshot/restore region state with the sweep's best/met results.
# ─────────────────────────────────────────────

AUTO_PIPELINE_REGION_RETRIES = 4


COUNT_TARGET_BISECT_STEPS = 32


class AutoPipelineLatencyInfeasible(Exception):
    """A constrained AUTO_PIPELINE call site's latency cannot be built."""


class AutoPipelineRegion:
    """One instance of a constrained AUTO_PIPELINE call site.

    The region is latency-decoupled from its container (GET_SUBMODULE_LATENCY
    reports tagged instances as 0), so it is planned on its own landscape,
    lowered, verified against its real GET_TOTAL_LATENCY and then locked
    (params_are_fixed) before any containing landscape is built -- the
    container sees an ordinary Segment.LOCKED, the same path mini-sweep locks
    use. Instances sharing a canonical key form one group and are planned to
    one register count, so the harvested .latency cannot diverge."""

    def __init__(self, inst, constraint, key, func_name):
        self.inst = inst
        self.constraint = constraint
        self.key = key  # canonical .latency key (None for C designs)
        self.func_name = func_name
        self.group = key if key is not None else ("inst", inst)
        # Budget divisor private to this region, multiplied on top of the
        # plan's global_scale; calibrated so start_latency / nudges persist
        self.scale = 1.0
        self.start_pending = constraint.start_latency is not None
        self.landscape = None
        self.cuts = []
        self.placements = []
        self.realized = 0
        self.count = None  # register count planned last iteration
        self.predicted_ns = 0.0
        self.rebalance_attempted = False

    def label(self):
        return self.key if self.key is not None else self.func_name

    def at_cap(self):
        cap = self.constraint.upper_bound()
        return cap is not None and self.realized >= cap

    def to_dict(self):
        return {
            "inst": self.inst,
            "key": self.key,
            "constraint": self.constraint.describe(),
            "realized_latency": self.realized,
            "cuts": len(self.cuts),
            "scale": round(self.scale, 4),
        }


def COLLECT_AUTO_PIPELINE_REGIONS(parser_state, scope_inst=None, fixed_only=False):
    """Every instance of a constrained AUTO_PIPELINE call site (optionally only
    those at/under scope_inst, or only fixed latency=N ones), sorted. Empty
    for designs without constraints, which keeps every region code path off."""
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    regions = []
    for inst_name in sorted(parser_state.LogicInstLookupTable):
        logic = parser_state.LogicInstLookupTable[inst_name]
        for local_sub in sorted(logic.sub_inst_to_auto_pipeline_latency):
            constraint = logic.sub_inst_to_auto_pipeline_latency[local_sub]
            if constraint is None or constraint.is_unconstrained():
                continue
            if fixed_only and not constraint.is_fixed():
                continue
            sub_inst = inst_name + marker + local_sub
            sub_logic = parser_state.LogicInstLookupTable.get(sub_inst)
            if sub_logic is None:
                continue
            if scope_inst is not None and not (
                sub_inst == scope_inst or sub_inst.startswith(scope_inst + marker)
            ):
                continue
            regions.append(
                AutoPipelineRegion(
                    sub_inst,
                    constraint,
                    logic.sub_inst_to_auto_pipeline_key.get(local_sub),
                    sub_logic.func_name,
                )
            )
    return regions


def _TRIM_PLACEMENT_PLAN_TO_COUNT(landscape, plan, count):
    """Reduce a planned (cuts, placements, budget) with too many cuts to
    exactly `count` by repeatedly dropping the cut whose removal merges the
    two lightest adjacent stages, then re-lowering the kept placements as
    required boundaries. None if the plan's placements aren't reusable as
    fixed placements (e.g. relocated bit-internal splits) or lowering moved
    the count."""
    import SWEEP

    cuts, placements, budget = plan
    by_unit = {}
    for placement in placements:
        by_unit.setdefault(placement.axis_unit, []).append(placement)
    for unit, unit_placements in by_unit.items():
        legal_ids = {
            c.candidate_id for c in landscape.candidates_by_unit.get(unit, ())
        }
        if any(p.candidate_id not in legal_ids for p in unit_placements):
            return None
    units = sorted(by_unit)
    weight = landscape.weight
    while len(units) > count:
        bounds = [-1] + units + [landscape.total_units - 1]
        stage_w = [
            sum(weight[bounds[i] + 1 : bounds[i + 1] + 1])
            for i in range(len(bounds) - 1)
        ]
        drop = min(
            range(len(units)), key=lambda j: (stage_w[j] + stage_w[j + 1], j)
        )
        del units[drop]
    fixed = [p for unit in units for p in by_unit[unit]]
    try:
        new_cuts, new_placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(
            landscape, float(sum(weight)) + 1.0, fixed_placements=fixed
        )
    except (ValueError, RuntimeError):
        return None
    if len(new_cuts) != count:
        return None
    return new_cuts, new_placements, budget


def COUNT_TARGETED_PLACEMENTS(landscape, count, strict=True, prefer_fewer=False):
    """Plan exactly `count` cuts on a landscape: bisect the stage budget
    PLAN_PIPELINE_PLACEMENTS is given (cut count is monotone non-increasing in
    the budget) until it yields `count`, so the positions are the planner's own
    tightest-stage placement for that many registers. When the count jumps
    over `count`, trim the nearest larger plan down to it; failing that return
    the nearest plan (fewer cuts when prefer_fewer, else more) -- the caller
    verifies the realized latency and retries.

    Returns (cuts, placements, budget_units). strict: more cuts than legal
    register positions raises AutoPipelineLatencyInfeasible instead of
    clamping."""
    import SWEEP

    total_w = float(sum(landscape.weight))
    if count <= 0:
        return [], [], total_w + 1.0
    n_legal = sum(1 for legal in landscape.legal if legal)
    if count > n_legal:
        if strict:
            raise AutoPipelineLatencyInfeasible(
                f"only {n_legal} legal register position(s) exist in "
                f"{landscape.subtree_root_inst}, {count} requested"
            )
        count = n_legal
        if count == 0:
            return [], [], total_w + 1.0
    lo, hi = 0.0, total_w + 1.0
    over = None
    under = None
    for _ in range(COUNT_TARGET_BISECT_STEPS):
        mid = 0.5 * (lo + hi)
        cuts, placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, mid)
        if len(cuts) == count:
            return cuts, placements, mid
        if len(cuts) > count:
            lo = mid
            over = (cuts, placements, mid)
        else:
            hi = mid
            under = (cuts, placements, mid)
        if hi - lo <= 1e-6 * max(1.0, hi):
            break
    if over is not None:
        trimmed = _TRIM_PLACEMENT_PLAN_TO_COUNT(landscape, over, count)
        if trimmed is not None:
            return trimmed
    if prefer_fewer and under is not None:
        return under
    if over is not None:
        return over
    if under is not None:
        return under
    return [], [], hi


def _INVALIDATE_REGION_CACHES(inst, TimingParamsLookupTable):
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    for name, timing_params in TimingParamsLookupTable.items():
        if (
            name == inst
            or name.startswith(inst + marker)
            or inst.startswith(name + marker)
        ):
            timing_params.INVALIDATE_CACHE()


def AUTO_PIPELINE_LATENCY_INFEASIBLE_MESSAGE(region, realized, tried, parser_state, why=""):
    return (
        f"AUTO_PIPELINE {region.label()} ({region.constraint.describe()}) at "
        f"{region.inst}{SYN.FUNC_SRC_LOC_STR(parser_state, region.func_name)}: "
        f"cannot build the requested latency"
        + (f" ({why})" if why else "")
        + f" -- realized {realized} clock(s) after planning "
        f"{', '.join(str(k) for k in tried)} register position(s). Relax or "
        "remove the constraint, or give the function more register positions."
    )


def _AUTO_PIPELINE_REGION_COUNT(region, period_ns, global_scale):
    """(register count to plan, calibrate region.scale to it?) before nudges."""
    import SWEEP

    constraint = region.constraint
    if constraint.is_fixed():
        return constraint.latency, False
    if region.landscape is None:
        return 0, False
    cap = constraint.max_latency
    if period_ns is None:
        count = constraint.start_latency or 0
        calibrate = False
    elif region.start_pending:
        region.start_pending = False
        count = constraint.start_latency
        calibrate = True
    else:
        budget = region.landscape.budget_units_for_period(period_ns) / (
            global_scale * region.scale
        )
        count = len(SWEEP.PLAN_PIPELINE_PLACEMENTS(region.landscape, budget)[0])
        calibrate = False
    if cap is not None and count > cap:
        count = cap
    count = min(count, sum(1 for legal in region.landscape.legal if legal))
    return count, calibrate


def _ENFORCE_ONE_AUTO_PIPELINE_REGION(
    region,
    count,
    parser_state,
    tpl,
    func_delay_scale,
    period_ns=None,
    global_scale=1.0,
    calibrate=False,
):
    import SWEEP

    marker = C_TO_LOGIC.SUBMODULE_MARKER
    constraint = region.constraint
    goal = constraint.latency if constraint.is_fixed() else None
    cap = constraint.max_latency
    k = count
    tried = []
    zero_tpl = None
    for attempt in range(AUTO_PIPELINE_REGION_RETRIES + 1):
        tried.append(k)
        if attempt > 0:
            # Undo the previous attempt's registers inside the region only
            if zero_tpl is None:
                zero_tpl = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
            for inst in list(tpl.keys()):
                if inst == region.inst or inst.startswith(region.inst + marker):
                    tpl[inst] = copy.deepcopy(zero_tpl[inst])
            region.landscape = SWEEP.BUILD_SLICE_LANDSCAPE(
                region.inst, parser_state, tpl, func_delay_scale
            )
        budget = None
        cuts, placements = [], []
        if k > 0:
            if region.landscape is None:
                if goal is not None:
                    raise AutoPipelineLatencyInfeasible(
                        AUTO_PIPELINE_LATENCY_INFEASIBLE_MESSAGE(
                            region, 0, tried, parser_state,
                            "no measurable pipelinable delay inside it",
                        )
                    )
            else:
                try:
                    cuts, placements, budget = COUNT_TARGETED_PLACEMENTS(
                        region.landscape,
                        k,
                        strict=goal is not None,
                        prefer_fewer=goal is None and cap is not None,
                    )
                except AutoPipelineLatencyInfeasible as err:
                    raise AutoPipelineLatencyInfeasible(
                        AUTO_PIPELINE_LATENCY_INFEASIBLE_MESSAGE(
                            region, 0, tried, parser_state, str(err)
                        )
                    )
        elif region.landscape is not None:
            budget = float(sum(region.landscape.weight)) + 1.0
        if placements:
            tpl = SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, parser_state, tpl)
            SWEEP.CHECK_PIPELINE_PLACEMENTS_REALIZED(placements, parser_state, tpl)
            _INVALIDATE_REGION_CACHES(region.inst, tpl)
            cuts, placements = SWEEP.DROP_NON_DEEPENING_PLACEMENTS(
                region.inst, cuts, placements, parser_state, tpl
            )
        _INVALIDATE_REGION_CACHES(region.inst, tpl)
        realized = tpl[region.inst].GET_TOTAL_LATENCY(parser_state, tpl)
        if goal is not None:
            target = goal
        elif cap is not None and realized > cap:
            target = cap
        else:
            target = None
        if target is None or realized == target:
            break
        next_k = max(0, k + (target - realized))
        if next_k in tried:
            next_k = k + (1 if target > realized else -1)
        if next_k < 0 or next_k in tried or attempt == AUTO_PIPELINE_REGION_RETRIES:
            raise AutoPipelineLatencyInfeasible(
                AUTO_PIPELINE_LATENCY_INFEASIBLE_MESSAGE(
                    region, realized, tried, parser_state
                )
            )
        k = next_k
    if calibrate and budget is not None and budget > 0.0 and period_ns is not None:
        # Make the unchanged knobs reproduce this count next iteration
        base = region.landscape.budget_units_for_period(period_ns) / global_scale
        region.scale = max(base / budget, 1e-9)
    region.cuts = list(cuts)
    region.placements = list(placements)
    region.realized = realized
    region.predicted_ns = (
        SWEEP.PREDICTED_STAGE_NS(cuts, region.landscape)
        if region.landscape is not None
        else 0.0
    )
    tpl[region.inst].params_are_fixed = True
    return tpl


def ENFORCE_AUTO_PIPELINE_REGIONS(
    regions,
    parser_state,
    tpl,
    func_delay_scale=None,
    period_ns=None,
    global_scale=1.0,
    unresolved=False,
    trim_pending=False,
):
    """Plan, lower, verify and lock every constrained AUTO_PIPELINE region.

    Register count per region group:
      - latency=N: N, always;
      - start_latency=S on its first iteration (or with no period to plan
        against): S, with region.scale calibrated so unchanged knobs keep
        reproducing S;
      - otherwise the count the planner picks for the plan's period, budget
        divided by global_scale * region.scale, capped at max_latency.
    With `unresolved` (timing still failing, the plan has no landscape of its
    own that could change) and no region count changed since last iteration,
    the group with the worst predicted stage grows by one register;
    `trim_pending` shrinks the group with the best predicted stage by one.

    Realized latency is verified after lowering (built-in operator stage
    granularity and non-deepening drops can make it differ from the cut
    count); fixed and capped regions retry with a corrected count and raise
    AutoPipelineLatencyInfeasible when the constraint cannot be met.
    Returns the updated table."""
    import SWEEP

    func_delay_scale = func_delay_scale or {}
    groups = {}
    order = []
    for region in regions:
        if region.group not in groups:
            groups[region.group] = []
            order.append(region.group)
        groups[region.group].append(region)
    decisions = []
    for group_key in order:
        members = groups[group_key]
        for region in members:
            region.landscape = SWEEP.BUILD_SLICE_LANDSCAPE(
                region.inst, parser_state, tpl, func_delay_scale
            )
        count, calibrate = _AUTO_PIPELINE_REGION_COUNT(
            members[0], period_ns, global_scale
        )
        decisions.append([members, count, calibrate])
    unchanged = all(d[0][0].count is not None and d[0][0].count == d[1] for d in decisions)
    if unchanged and (unresolved or trim_pending):
        if trim_pending:
            movable = [
                d
                for d in decisions
                if not d[0][0].constraint.is_fixed() and d[1] > 0
            ]
            if movable:
                d = min(movable, key=lambda d: d[0][0].predicted_ns)
                d[1] -= 1
                d[2] = True
        else:
            movable = [
                d
                for d in decisions
                if not d[0][0].constraint.is_fixed()
                and d[0][0].landscape is not None
                and (
                    d[0][0].constraint.max_latency is None
                    or d[1] < d[0][0].constraint.max_latency
                )
            ]
            if movable:
                d = max(movable, key=lambda d: d[0][0].predicted_ns)
                d[1] += 1
                d[2] = True
    for members, count, calibrate in decisions:
        for region in members:
            tpl = _ENFORCE_ONE_AUTO_PIPELINE_REGION(
                region,
                count,
                parser_state,
                tpl,
                func_delay_scale,
                period_ns=period_ns,
                global_scale=global_scale,
                calibrate=calibrate and period_ns is not None,
            )
            region.count = count
    return tpl


def REENFORCE_AUTO_PIPELINE_REGIONS(parser_state, tpl, scope_inst=None):
    """Pin-and-confirm seeding (SEED_TIMING_PARAMS_FROM_PREVIOUS) copies
    slices by instance path or function name, which can hand a constrained
    region another call site's pipelining. Keep every region that still
    satisfies its constraint, re-plan any that doesn't (fixed regions to N,
    over-cap regions to their cap), and lock them all. Also used by the
    coarse sweep after its even-fraction slicing (scope_inst = the swept
    instance)."""
    import SWEEP

    regions = COLLECT_AUTO_PIPELINE_REGIONS(parser_state, scope_inst=scope_inst)
    if not regions:
        return tpl
    for timing_params in tpl.values():
        timing_params.INVALIDATE_CACHE()
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    zero_tpl = None
    for region in regions:
        realized = tpl[region.inst].GET_TOTAL_LATENCY(parser_state, tpl)
        cap = region.constraint.upper_bound()
        violates = cap is not None and (
            realized > cap or (region.constraint.is_fixed() and realized != cap)
        )
        if not violates:
            tpl[region.inst].params_are_fixed = True
            continue
        if zero_tpl is None:
            zero_tpl = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
        for inst in list(tpl.keys()):
            if inst == region.inst or inst.startswith(region.inst + marker):
                tpl[inst] = copy.deepcopy(zero_tpl[inst])
        region.landscape = SWEEP.BUILD_SLICE_LANDSCAPE(region.inst, parser_state, tpl, {})
        try:
            tpl = _ENFORCE_ONE_AUTO_PIPELINE_REGION(
                region, cap, parser_state, tpl, {}
            )
        except AutoPipelineLatencyInfeasible as err:
            sys.exit(str(err))
    for timing_params in tpl.values():
        timing_params.INVALIDATE_CACHE()
    return tpl


def PLAN_REGION_CUTS(plan):
    return sum(len(region.cuts) for region in plan.regions)


def REGION_FOR_HOTSPOT(hotspot_func, plan, parser_state):
    """The constrained region group every in-plan instance of hotspot_func
    lies inside, else None."""
    if not plan.regions:
        return None
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    insts = sorted(
        inst
        for inst in parser_state.FuncToInstances.get(hotspot_func, ())
        if inst == plan.main_inst or inst.startswith(plan.main_inst + marker)
    )
    found = None
    for inst in insts:
        owner = next(
            (
                r
                for r in plan.regions
                if inst == r.inst or inst.startswith(r.inst + marker)
            ),
            None,
        )
        if owner is None or (found is not None and owner.group != found.group):
            return None
        if found is None:
            found = owner
    return found


def STOP_AT_AUTO_PIPELINE_LATENCY_LIMIT(plan, parser_state, capped_regions, hotspot_func=None):
    main_func_name = parser_state.LogicInstLookupTable[plan.main_inst].func_name
    seen = set()
    names = []
    for region in capped_regions:
        if region.group in seen:
            continue
        seen.add(region.group)
        names.append(
            f"{region.label()} ({region.constraint.describe()}, "
            f"{region.realized} clks built)"
        )
    names_str = ", ".join(names) if names else "?"
    where = (
        f" (critical path in {hotspot_func}"
        f"{SYN.FUNC_SRC_LOC_STR(parser_state, hotspot_func)})"
        if hotspot_func is not None
        else ""
    )
    print(
        f"[sweep] WARNING: {main_func_name} limited by AUTO_PIPELINE latency "
        f"constraint(s) {names_str}{where}: the constrained call site(s) cannot "
        "take more registers. Raise or remove latency= / max_latency=, or lower "
        "the clock goal. Keeping best result.",
        flush=True,
    )
    plan.stopped_reason = "auto_pipeline_latency_limit"
    plan.auto_pipeline_limit_blame = names_str


def AUTO_PIPELINE_REGION_FEEDBACK(plan, region, hotspot_func, target_mhz, curr_mhz, parser_state):
    """Failing-timing feedback for a critical path inside a constrained region.
    Returns (action string, made_change)."""
    import SWEEP

    step = min(
        max((target_mhz / curr_mhz) * 1.05, SWEEP.FUNC_SCALE_MIN_STEP),
        SWEEP.FUNC_SCALE_MAX_STEP,
    )
    group = [r for r in plan.regions if r.group == region.group]
    if not region.at_cap():
        for r in group:
            r.scale *= step
        plan.func_delay_scale[hotspot_func] = (
            plan.func_delay_scale.get(hotspot_func, 1.0) * step
        )
        return f"grow_auto_pipeline({region.label()} x{region.scale:.2f})", True
    if not region.rebalance_attempted:
        # Same register count, re-placed with the hotspot weighted heavier
        for r in group:
            r.rebalance_attempted = True
        plan.func_delay_scale[hotspot_func] = (
            plan.func_delay_scale.get(hotspot_func, 1.0) * step
        )
        return (
            f"rebalance_auto_pipeline({region.label()} at "
            f"{region.constraint.describe()})",
            True,
        )
    STOP_AT_AUTO_PIPELINE_LATENCY_LIMIT(plan, parser_state, [region], hotspot_func)
    return f"stop(auto-pipeline latency limit {region.label()})", False


def SNAPSHOT_AUTO_PIPELINE_REGIONS(plans):
    return {
        mi: [
            (list(r.cuts), list(r.placements), r.realized, r.scale, r.count)
            for r in p.regions
        ]
        for mi, p in plans.items()
        if p.regions
    }


def RESTORE_AUTO_PIPELINE_REGIONS(plans, snapshot):
    if not snapshot:
        return
    for mi, states in snapshot.items():
        for region, (cuts, placements, realized, scale, count) in zip(
            plans[mi].regions, states
        ):
            region.cuts = list(cuts)
            region.placements = list(placements)
            region.realized = realized
            region.scale = scale
            region.count = count


# ─────────────────────────────────────────────
# Pipelined VHDL architecture text: stage records and signals, the combinational
# stage process, stage-to-stage and IO registers, and submodule instances placed
# at their stage. VHDL.py emits everything else about an entity and calls these
# for its architecture once the TimingParams are final.
# ─────────────────────────────────────────────

# Post processed version of pipeline map with info specific to how auto-pipelined HDL is rendered
class PiplineHDLParams:
    def __init__(
        self, inst_name, Logic, parser_state, TimingParamsLookupTable, pipeline_map
    ):
        self.pipeline_map = pipeline_map
        self.wires_to_decl = []
        self.wire_to_reg_stage_start_end = {}  # Same as comb range too
        # These used just internally? \/
        self.stage_to_driver_wires = {}
        self.stage_to_driven_wires = {}

        # Not needed for no submodule things like raw hdl
        if (
            VHDL.LOGIC_IS_RAW_HDL(Logic, parser_state)
            or Logic.is_vhdl_func
            or Logic.is_vhdl_expr
            or Logic.vhdl_module_text is not None
            or Logic.func_name in parser_state.func_marked_blackbox
        ):
            return
        timing_params = TimingParamsLookupTable[inst_name]

        # Not all netlist wires are vhdl wires
        for wire_name in Logic.wire_to_c_type:
            # Skip constants here
            if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name):
                continue
            # Skip globals too
            # Dont skip volatile globals, they are like regular wires
            if (
                wire_name in Logic.state_regs
                and not Logic.state_regs[wire_name].is_volatile
            ):
                continue
            # Skip VHDL input wires
            if C_TO_LOGIC.WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(
                wire_name, Logic, parser_state
            ):
                continue
            if C_TO_LOGIC.WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(
                wire_name, Logic, parser_state
            ):
                continue
            self.wires_to_decl.append(wire_name)
            self.wire_to_reg_stage_start_end[wire_name] = [None, None]

        # Arrange into list of driven(write) wires per stage, and list of driver(read) wires

        # Init non-stages stuff,
        #   inputs
        #   clockenable
        #   outputs
        #   volatiles being input in first state, output in final
        if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state):
            input_wires = [C_TO_LOGIC.CLOCK_ENABLE_NAME]
        else:
            input_wires = []
        for input_port in Logic.inputs:
            input_wires.append(input_port)
        # Inputs written in first stage
        for input_wire in input_wires:
            if 0 not in self.stage_to_driven_wires:
                self.stage_to_driven_wires[0] = []
            self.stage_to_driven_wires[0].append(input_wire)
        # Outputs read in final stage
        for output_port in Logic.outputs:
            if self.pipeline_map.num_stages - 1 not in self.stage_to_driver_wires:
                self.stage_to_driver_wires[self.pipeline_map.num_stages - 1] = []
            self.stage_to_driver_wires[self.pipeline_map.num_stages - 1].append(
                output_port
            )
        # Vol written at input read at output
        vol_state_regs = []
        for state_reg in Logic.state_regs:
            if Logic.state_regs[state_reg].is_volatile:
                vol_state_regs.append(state_reg)
        for state_reg in vol_state_regs:
            # Input write
            if 0 not in self.stage_to_driven_wires:
                self.stage_to_driven_wires[0] = []
            self.stage_to_driven_wires[0].append(state_reg)
            # Do final read of vol wire, includes driver wire of vol too
            driver_of_vol_wire = Logic.wire_driven_by[state_reg]
            if self.pipeline_map.num_stages - 1 not in self.stage_to_driver_wires:
                self.stage_to_driver_wires[self.pipeline_map.num_stages - 1] = []
            self.stage_to_driver_wires[self.pipeline_map.num_stages - 1].append(
                driver_of_vol_wire
            )
            self.stage_to_driver_wires[self.pipeline_map.num_stages - 1].append(
                state_reg
            )

        # Loop over all stages
        for stage in range(0, self.pipeline_map.num_stages):
            stage_info = pipeline_map.stage_infos[stage]
            if stage not in self.stage_to_driver_wires:
                self.stage_to_driver_wires[stage] = []
            if stage not in self.stage_to_driven_wires:
                self.stage_to_driven_wires[stage] = []
            # Sub output ports when module latency >0 pipeline wires are whats driven from submodule
            for submodule_output_port_wire in stage_info.submodule_output_ports:
                self.stage_to_driven_wires[stage].append(submodule_output_port_wire)
            # Driver driven pairs from each submodule level
            for submodule_level_info in stage_info.submodule_level_infos:
                # Driver driven pairs
                for (
                    driver_driven_wire_pair
                ) in submodule_level_info.driver_driven_wire_pairs:
                    driver_wire, driven_wire = driver_driven_wire_pair
                    if driven_wire in self.wires_to_decl:
                        self.stage_to_driven_wires[stage].append(driven_wire)
                    if driver_wire in self.wires_to_decl:
                        self.stage_to_driver_wires[stage].append(driver_wire)
                # Submodule instances
                for sub_inst in submodule_level_info.submodule_insts:
                    submodule_inst_name = (
                        inst_name + C_TO_LOGIC.SUBMODULE_MARKER + sub_inst
                    )
                    sub_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
                    # CE, inputs are read at instantiation
                    # In wires include ce
                    if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                        sub_in_wires = [
                            sub_inst
                            + C_TO_LOGIC.SUBMODULE_MARKER
                            + C_TO_LOGIC.CLOCK_ENABLE_NAME
                        ]
                    else:
                        sub_in_wires = []
                    for input_port in sub_logic.inputs:
                        in_wire = sub_inst + C_TO_LOGIC.SUBMODULE_MARKER + input_port
                        sub_in_wires.append(in_wire)
                    for in_wire in sub_in_wires:
                        if in_wire in self.wires_to_decl:
                            self.stage_to_driver_wires[stage].append(in_wire)
                    # HACK AF for VHDL expr and func since input wires dont get named
                    # So need to manually see reading of driver of input ports
                    # Mock Orange - Song in D
                    if sub_logic.is_vhdl_func or sub_logic.is_vhdl_expr:
                        for in_wire in sub_in_wires:
                            driver_of_in_wire = Logic.wire_driven_by[in_wire]
                            if driver_of_in_wire in self.wires_to_decl:
                                self.stage_to_driver_wires[stage].append(
                                    driver_of_in_wire
                                )
                    # Outputs are driven(written) if latency is 0
                    sub_latency = timing_params.GET_SUBMODULE_LATENCY(
                        submodule_inst_name, parser_state, TimingParamsLookupTable
                    )
                    if sub_latency == 0:
                        for out_port in sub_logic.outputs:
                            out_wire = sub_inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
                            if out_wire in self.wires_to_decl:
                                self.stage_to_driven_wires[stage].append(out_wire)

        # Do passes over drivers and driven wires per stage to find range of use

        # If a wire is written in a stage then its registers before then arent needed
        # Because wires are only written once - should be true
        # If a wire is read in a stage then need need registers up to prev stage to read from
        # Reverse order hides fact that VHDL func+expr module driver wires are weird?
        for stage in range(self.pipeline_map.num_stages - 1, -1, -1):
            driver_wires = self.stage_to_driver_wires[stage]
            driven_wires = self.stage_to_driven_wires[stage]
            for driver_wire in driver_wires:
                curr_start, curr_end = self.wire_to_reg_stage_start_end[driver_wire]
                if curr_end is None:
                    curr_end = stage - 1
                    self.wire_to_reg_stage_start_end[driver_wire] = [
                        curr_start,
                        curr_end,
                    ]
            for driven_wire in driven_wires:
                curr_start, curr_end = self.wire_to_reg_stage_start_end[driven_wire]
                if curr_start is None:
                    curr_start = stage
                    self.wire_to_reg_stage_start_end[driven_wire] = [
                        curr_start,
                        curr_end,
                    ]

        # Extra try to find start for wires that are never driven (read only driver)
        # Extra try to find end for wires that are never drivers (write only driven)
        # Only needed for write only globals?
        for stage in range(self.pipeline_map.num_stages - 1, -1, -1):
            driver_wires = self.stage_to_driver_wires[stage]
            driven_wires = self.stage_to_driven_wires[stage]
            for driver_wire in driver_wires:
                curr_start, curr_end = self.wire_to_reg_stage_start_end[driver_wire]
                if curr_start is None or (stage < curr_start):
                    curr_start = stage
                    self.wire_to_reg_stage_start_end[driver_wire] = [
                        curr_start,
                        curr_end,
                    ]
            for driven_wire in driven_wires:
                curr_start, curr_end = self.wire_to_reg_stage_start_end[driven_wire]
                if curr_end is None or (stage - 1 > curr_end):
                    curr_end = stage - 1
                    self.wire_to_reg_stage_start_end[driven_wire] = [
                        curr_start,
                        curr_end,
                    ]

        # Adjust range of use for non vol read only global wire network
        # Entire network downstream from var needs to be read at same time
        upstream_var_to_earliest_stage = {}
        for wire in self.pipeline_map.read_only_global_network_wire_to_upstream_vars:
            upstream_vars = (
                self.pipeline_map.read_only_global_network_wire_to_upstream_vars[wire]
            )
            if wire not in self.wire_to_reg_stage_start_end:
                continue
            start_stage, end_stage = self.wire_to_reg_stage_start_end[wire]
            if start_stage is None:
                continue
            for upstream_var in upstream_vars:
                if upstream_var not in upstream_var_to_earliest_stage:
                    upstream_var_to_earliest_stage[upstream_var] = start_stage
                if start_stage < upstream_var_to_earliest_stage[upstream_var]:
                    upstream_var_to_earliest_stage[upstream_var] = start_stage
        for wire in self.wire_to_reg_stage_start_end:
            start_stage, end_stage = self.wire_to_reg_stage_start_end[wire]
            if start_stage is None:
                continue
            if wire in self.pipeline_map.read_only_global_network_wire_to_upstream_vars:
                upstream_vars = (
                    self.pipeline_map.read_only_global_network_wire_to_upstream_vars[
                        wire
                    ]
                )
                for upstream_var in upstream_vars:
                    ro_var_info = Logic.read_only_global_wires[upstream_var]
                    if ro_var_info.is_volatile:
                        continue
                    # non vol read only global wire downstream from upstream_var
                    # Find earliest use of all wires
                    earliest_start_stage = upstream_var_to_earliest_stage[upstream_var]
                    if earliest_start_stage < start_stage:
                        self.wire_to_reg_stage_start_end[wire] = (
                            earliest_start_stage,
                            end_stage,
                        )

        # Pass to clear all record of unused None,None
        wires_to_rm = []
        for wire in self.wire_to_reg_stage_start_end:
            curr_start, curr_end = self.wire_to_reg_stage_start_end[wire]
            # print("wire, curr_start, curr_end", wire, curr_start, curr_end)
            if curr_start is None and curr_end is None:
                # Constants handled special outside pipeline, wont have start end
                if (
                    not Logic.WIRE_DO_NOT_COLLAPSE(wire, parser_state)
                    and wire
                    not in self.pipeline_map.const_network_wire_to_upstream_vars
                    and wire
                    not in self.pipeline_map.read_only_global_network_wire_to_upstream_vars
                ):
                    wires_to_rm.append(wire)
        for wire_to_rm in wires_to_rm:
            self.wires_to_decl.remove(wire_to_rm)
            self.wire_to_reg_stage_start_end.pop(wire_to_rm)


def GET_PIPELINE_ARCH_DECL_TEXT(
    inst_name, Logic, parser_state, TimingParamsLookupTable, pipeline_hdl_params
):
    timing_params = TimingParamsLookupTable[inst_name]
    total_latency = timing_params.GET_TOTAL_LATENCY(
        parser_state, TimingParamsLookupTable
    )
    pipeline_latency = timing_params.GET_PIPELINE_LOGIC_ADDED_LATENCY(
        parser_state, TimingParamsLookupTable
    )
    needs_clk = VHDL.LOGIC_NEEDS_CLOCK(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
    needs_regs = VHDL.LOGIC_NEEDS_REGS(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    is_raw_hdl = VHDL.LOGIC_IS_RAW_HDL(Logic, parser_state)
    needs_manual_regs = VHDL.LOGIC_NEEDS_MANUAL_REGS(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )

    rv = ""
    # Stuff originally in package
    rv += "-- Types and such\n"
    rv += "-- Declarations\n"
    rv += "attribute mark_debug : string;\n"

    # Declare latency for just the pipeline portion of logic, not io regs
    rv += (
        "constant ADDED_PIPELINE_LATENCY : integer := " + str(pipeline_latency) + ";\n"
    )

    # TODO built in raw vhdl still uses write pipe stuff

    # Raw HDL functions are done differently
    # Raw vhdl still uses write pipe
    wrote_variables_t = False
    wrote_variables_NULL = False
    if is_raw_hdl:
        # Type for wires/variables
        varables_t_pre = ""
        varables_t_pre += "\n"
        varables_t_pre += "-- One struct to represent this modules variables\n"
        varables_t_pre += "type raw_hdl_variables_t is record\n"
        varables_t_pre += " -- All of the wires in function\n"
        text = RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(
            inst_name, Logic, parser_state, timing_params
        )
        if text != "":
            rv += varables_t_pre
            rv += text
            rv += "end record;\n"
            wrote_variables_t = True
        rv += """
-- Type for this modules register pipeline
type raw_hdl_register_pipeline_t is array(0 to ADDED_PIPELINE_LATENCY) of raw_hdl_variables_t;
  """
    else:
        # For each stage make reg and comb signal as needed
        rv += "-- All of the wires/regs in function\n"
        for stage in range(0, pipeline_latency):
            rv += f"-- Stage {stage}\n"
            for prefix in ["REG", "COMB"]:
                for wire_name in pipeline_hdl_params.wires_to_decl:
                    (
                        start_stage,
                        end_stage,
                    ) = pipeline_hdl_params.wire_to_reg_stage_start_end[wire_name]
                    if start_stage is None or end_stage is None:
                        continue
                    if stage in range(start_stage, end_stage + 1):
                        # print("wire_name", wire_name)
                        vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(
                            wire_name, Logic, parser_state
                        )
                        # print "wire_name",wire_name
                        write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, Logic)
                        sig_name = (
                            prefix
                            + "_"
                            + "STAGE"
                            + str(stage)
                            + "_"
                            + write_pipe_wire_var_vhdl
                        )
                        rv += "signal " + sig_name + " : " + vhdl_type_str + ";\n"
                        # Mark debug?
                        local_mark_debug = False
                        if wire_name in Logic.debug_names:
                            local_mark_debug = True
                        if wire_name in Logic.alias_to_orig_var_name:
                            orig_var_name = Logic.alias_to_orig_var_name[wire_name]
                            if orig_var_name in Logic.debug_names:
                                local_mark_debug = True
                        global_mark_debug = (
                            Logic.func_name in parser_state.func_marked_debug
                        )
                        if (local_mark_debug or global_mark_debug) and prefix == "REG":
                            rv += (
                                """attribute mark_debug of """
                                + sig_name
                                + """ : signal is "true";\n"""
                            )
    # Input registers
    if timing_params._has_input_regs:
        in_regs_rec = ""
        for input_port in Logic.inputs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(input_port, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(input_port, Logic)
            in_regs_rec += " " + vhdl_name + " : " + vhdl_type_str + ";\n"
        if needs_clk_en:
            in_regs_rec += (
                " " + C_TO_LOGIC.CLOCK_ENABLE_NAME + " : unsigned(0 downto 0);\n"
            )
        if in_regs_rec != "":
            rv += """
-- Type holding all input registers
type input_registers_t is record\n"""
            rv += in_regs_rec
            rv += "end record;\n"

    # Output registers
    if timing_params._has_output_regs:
        out_regs_rec = ""
        for output_port in Logic.outputs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(output_port, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(output_port, Logic)
            out_regs_rec += " " + vhdl_name + " : " + vhdl_type_str + ";\n"
        if out_regs_rec != "":
            rv += """
-- Type holding all output registers
type output_registers_t is record\n"""
            rv += out_regs_rec
            rv += "end record;\n"

    # State registers
    if len(Logic.state_regs) > 0:
        rv += """
-- All user state registers\n"""
        for state_reg in Logic.state_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += (
                "signal "
                + vhdl_name
                + " : "
                + vhdl_type_str
                + " := "
                + VHDL.STATE_REG_TO_VHDL_INIT_STR(state_reg, Logic, parser_state)
                + ";\n"
            )
            # Mark debug?
            local_mark_debug = state_reg in Logic.debug_names
            global_mark_debug = Logic.func_name in parser_state.func_marked_debug
            if local_mark_debug or global_mark_debug:
                rv += (
                    """attribute mark_debug of """
                    + vhdl_name
                    + """ : signal is "true";\n"""
                )
        for state_reg in Logic.state_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += "signal " + "REG_COMB_" + vhdl_name + " : " + vhdl_type_str + ";\n"
        rv += "\n"

    # Feedback wires
    if len(Logic.feedback_vars) > 0:
        rv += """
-- Type holding all locally declared (feedback) wires of the func 
type feedback_vars_t is record"""
        rv += """
  -- Feedback vars\n"""
        for feedback_var in Logic.feedback_vars:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(feedback_var, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(feedback_var, Logic)
            rv += " " + vhdl_name + " : " + vhdl_type_str + ";\n"
        rv += "end record;\n"

    has_io_regs = timing_params._has_input_regs or timing_params._has_output_regs
    if has_io_regs:
        record_text = ""
        # Input regs
        if timing_params._has_input_regs and ((len(Logic.inputs) > 0) or needs_clk_en):
            record_text += """
    input_regs : input_registers_t;"""
        # Output regs
        if timing_params._has_output_regs and len(Logic.outputs) > 0:
            record_text += """
    output_regs : output_registers_t;"""
        if record_text != "":
            rv += """ 
  -- Type holding all IO regs (not part of body slicing)
  type io_registers_t is record"""
            rv += record_text
            # End
            rv += """ 
  end record;
  """

    # ALL MANUAL REGISTERS
    if needs_manual_regs:
        record_text = ""
        # Self regs
        if wrote_variables_t and is_raw_hdl:
            record_text += """
    raw_hdl_pipeline : raw_hdl_register_pipeline_t;"""
        if record_text != "":
            rv += """ 
  -- Type holding all manually (not auto generated in pipelining) registers for this function
  --  RAW HDL pipeline, user state regs
  type manual_registers_t is record"""
            rv += record_text
            # End
            rv += """ 
  end record;
  """

    # Func for nulling out IO regs
    if has_io_regs:
        func_text = ""
        # Input regs
        if timing_params._has_input_regs:
            for input_port in Logic.inputs:
                func_text += (
                    " rv.input_regs."
                    + VHDL.WIRE_TO_VHDL_NAME(input_port, Logic)
                    + " := "
                    + VHDL.WIRE_TO_VHDL_NULL_STR(input_port, Logic, parser_state)
                    + ";\n"
                )
            # Clock enable
            if needs_clk_en:
                func_text += (
                    " rv.input_regs."
                    + C_TO_LOGIC.CLOCK_ENABLE_NAME
                    + " := "
                    + VHDL.WIRE_TO_VHDL_NULL_STR(
                        C_TO_LOGIC.CLOCK_ENABLE_NAME, Logic, parser_state
                    )
                    + ";\n"
                )

        # Output regs
        if timing_params._has_output_regs:
            for output_port in Logic.outputs:
                func_text += (
                    " rv.output_regs."
                    + VHDL.WIRE_TO_VHDL_NAME(output_port, Logic)
                    + " := "
                    + VHDL.WIRE_TO_VHDL_NULL_STR(output_port, Logic, parser_state)
                    + ";\n"
                )
        # Function to null out IO regs
        rv += "\n-- Function to null out IO regs \n"
        rv += "function io_registers_NULL return io_registers_t is\n"
        rv += """ variable rv : io_registers_t;
  begin
"""
        rv += func_text
        rv += """
  return rv;
end function;\n
"""
    # Special resolved to be input reg or not internal clock enable
    if needs_clk_en:
        rv += "-- Resolved maybe from input reg clock enable\n"
        rv += "signal clk_en_internal : std_logic;\n"

    if has_io_regs:
        rv += """-- IO regs and signals for this function\n"""
        # Comb signal
        rv += "signal " + "io_registers : io_registers_t;\n"
        # Regs nulled out
        rv += "signal " + "io_registers_r : io_registers_t := io_registers_NULL;\n"
        # Mark debug?
        if Logic.func_name in parser_state.func_marked_debug:
            rv += """attribute mark_debug of io_registers_r : signal is "true";\n"""
        rv += "\n"

    # Func for nulling out manual regs
    if needs_manual_regs:
        func_text = ""
        # Raw hdl regs
        if wrote_variables_NULL and is_raw_hdl:
            func_text += "-- Not nulling raw hdl\n"
        # Function to null out manual regs
        rv += "\n-- Function to null out manual regs \n"
        rv += "function manual_registers_NULL return manual_registers_t is\n"
        rv += """ variable rv : manual_registers_t;
  begin
"""
        rv += func_text
        rv += """
  return rv;
end function;\n
"""

    if needs_manual_regs:
        rv += """-- Manual (not auto pipeline) registers and signals for this function\n"""
        # Comb signal of main regs
        rv += "signal " + "manual_registers : manual_registers_t;\n"
        # Main regs nulled out
        rv += (
            "signal "
            + "manual_registers_r : manual_registers_t := manual_registers_NULL;\n"
        )
        # Mark debug?
        if Logic.func_name in parser_state.func_marked_debug:
            rv += """attribute mark_debug of manual_registers_r : signal is "true";\n"""
        rv += "\n"

    if len(Logic.feedback_vars) > 0:
        rv += """-- Feedback vars in the func\n"""
        rv += "signal " + "feedback_vars : feedback_vars_t;\n"

    # Signals for submodule ports
    if len(Logic.submodule_instances) > 0:
        rv += """-- Each function instance gets signals\n"""
    for inst in Logic.submodule_instances:
        instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
        submodule_logic_name = Logic.submodule_instances[inst]
        submodule_logic = parser_state.LogicInstLookupTable[instance_name]
        submodule_logic_needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(
            submodule_logic, parser_state
        )

        # Skip VHDL
        if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
            continue
        # Skip clock cross
        if submodule_logic.is_clock_crossing:
            continue

        rv += "-- " + inst + "\n"
        # Clock enable
        if submodule_logic_needs_clk_en:
            ce_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(ce_wire, Logic, parser_state)
            rv += (
                "signal "
                + VHDL.WIRE_TO_VHDL_NAME(ce_wire, Logic)
                + " : "
                + vhdl_type_str
                + ";\n"
            )
        # Inputs
        for in_port in submodule_logic.inputs:
            in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(in_wire, Logic, parser_state)
            rv += (
                "signal "
                + VHDL.WIRE_TO_VHDL_NAME(in_wire, Logic)
                + " : "
                + vhdl_type_str
                + ";\n"
            )
        # Outputs
        for out_port in submodule_logic.outputs:
            out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(out_wire, Logic, parser_state)
            rv += (
                "signal "
                + VHDL.WIRE_TO_VHDL_NAME(out_wire, Logic)
                + " : "
                + vhdl_type_str
                + ";\n"
            )
        rv += "\n"

    # Certain submodules are always 0 delay "IS_VHDL_FUNC"
    rv += VHDL.GET_VHDL_FUNC_SUBMODULE_DECLS(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )

    rv += "\n"

    return rv


# TODO raw vhdl parts of this are a mess
# Hey Ya! - OutKast
def GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT(
    inst_name, Logic, parser_state, TimingParamsLookupTable, pipeline_hdl_params
):
    # Comb Logic pipeline
    timing_params = TimingParamsLookupTable[inst_name]
    total_latency = timing_params.GET_TOTAL_LATENCY(
        parser_state, TimingParamsLookupTable
    )
    pipeline_latency = timing_params.GET_PIPELINE_LOGIC_ADDED_LATENCY(
        parser_state, TimingParamsLookupTable
    )
    needs_clk = VHDL.LOGIC_NEEDS_CLOCK(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
    needs_regs = VHDL.LOGIC_NEEDS_REGS(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    is_raw_hdl = VHDL.LOGIC_IS_RAW_HDL(Logic, parser_state)
    needs_manual_regs = VHDL.LOGIC_NEEDS_MANUAL_REGS(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    needs_global_to_module = VHDL.LOGIC_NEEDS_GLOBAL_TO_MODULE(
        Logic, parser_state
    )  # , TimingParamsLookupTable)
    # needs_module_to_global = LOGIC_NEEDS_MODULE_TO_GLOBAL(Logic, parser_state)#, TimingParamsLookupTable)
    has_in_regs = timing_params._has_input_regs and (
        (len(Logic.inputs) > 0) or needs_clk_en
    )
    has_out_regs = timing_params._has_output_regs and (len(Logic.outputs) > 0)
    has_io_regs = has_in_regs or has_out_regs
    rv = ""
    rv += "\n"

    # Resolve what clock enable to use for user logic
    # the clock enable port, of input delayed reg version
    if needs_clk_en:
        rv += "-- Resolve what clock enable to use for user logic\n"
        if timing_params._has_input_regs:
            rv += (
                "clk_en_internal <= io_registers_r.input_regs."
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + "(0);\n"
            )
        else:
            rv += "clk_en_internal <= " + C_TO_LOGIC.CLOCK_ENABLE_NAME + "(0);\n"

    rv += "-- Combinatorial process for pipeline stages\n"
    rv += "process "
    process_sens_list = ""
    if needs_clk_en:
        process_sens_list += "CLOCK_ENABLE,\n"
        process_sens_list += "clk_en_internal,\n"
    if len(Logic.inputs) > 0:
        process_sens_list += " -- Inputs\n"
        for input_wire in Logic.inputs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(input_wire, Logic, parser_state)
            process_sens_list += " " + VHDL.WIRE_TO_VHDL_NAME(input_wire, Logic) + ",\n"
    if len(Logic.feedback_vars) > 0:
        process_sens_list += " -- Feedback vars\n"
        process_sens_list += " " + "feedback_vars,\n"
    if needs_regs:
        process_sens_list += " -- Registers\n"
        # User state registers
        for state_reg in Logic.state_regs:
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            process_sens_list += " " + vhdl_name + ",\n"
        # Auto gen pipeline regs?
        if not is_raw_hdl:
            for stage in range(0, pipeline_latency):
                process_sens_list += f" -- Stage {stage}\n"
                for wire_name in pipeline_hdl_params.wires_to_decl:
                    (
                        start_stage,
                        end_stage,
                    ) = pipeline_hdl_params.wire_to_reg_stage_start_end[wire_name]
                    if start_stage is None or end_stage is None:
                        continue
                    if stage in range(start_stage, end_stage + 1):
                        vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(
                            wire_name, Logic, parser_state
                        )
                        write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, Logic)
                        process_sens_list += (
                            " "
                            + "REG_STAGE"
                            + str(stage)
                            + "_"
                            + write_pipe_wire_var_vhdl
                            + ",\n"
                        )
        if has_io_regs:
            process_sens_list += " " + "io_registers_r,\n"
        if needs_manual_regs:
            process_sens_list += " " + "manual_registers_r,\n"
    if needs_global_to_module:
        process_sens_list += " -- Clock cross input\n"
        process_sens_list += " " + "global_to_module,\n"
    submodule_text = ""
    has_submodules_to_print = False
    if len(Logic.submodule_instances) > 0:
        submodule_text += " -- All submodule outputs\n"
        # All submodules
        for inst in Logic.submodule_instances:
            instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
            submodule_logic_name = Logic.submodule_instances[inst]
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]

            # Skip vhdl
            if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
                continue
            # Skip clock cross
            if submodule_logic.is_clock_crossing:
                continue

            new_inst_name = C_TO_LOGIC.LEAF_NAME(instance_name, do_submodule_split=True)
            if len(submodule_logic.outputs) > 0:
                has_submodules_to_print = True
                # submodule_text += " -- " + new_inst_name + "\n"
                # Outputs
                for out_port in submodule_logic.outputs:
                    out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
                    submodule_text += " " + VHDL.WIRE_TO_VHDL_NAME(out_wire, Logic) + ",\n"

    if has_submodules_to_print:
        process_sens_list += submodule_text

    if process_sens_list != "":
        rv += "(\n"
        # Remove last two chars
        process_sens_list = process_sens_list[0 : len(process_sens_list) - 2]
        rv += process_sens_list
        rv += ")\n"
    else:
        # Some tools assume wait is needed if empty sens list
        # Use all in sens list if nothing else
        # GHDL->Yosys needs?
        # if (SIM.SIM_TOOL == VERILATOR) or (SIM.SIM_TOOL == CXXRTL):
        rv += "(all)\n"

    rv += "is \n"

    # Variables for between pipeline stages
    # Raw vhdl still uses write pipe
    if is_raw_hdl:
        # READ PIPE
        rv += " -- Read and write variables to do register transfers per clock\n"
        rv += " -- from the previous to next stage\n"
        rv += " " + "variable read_pipe : raw_hdl_variables_t;\n"
        rv += " " + "variable write_pipe : raw_hdl_variables_t;\n"
        # Self regs
        rv += """
 -- This modules self pipeline registers read once per clock
 variable read_raw_hdl_pipeline_regs : raw_hdl_register_pipeline_t;
 variable write_raw_hdl_pipeline_regs : raw_hdl_register_pipeline_t;
  """
    else:
        if len(pipeline_hdl_params.wires_to_decl) > 0:
            rv += " " + "-- All of the wires in function\n"
            for wire_name in pipeline_hdl_params.wires_to_decl:
                vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(wire_name, Logic, parser_state)
                write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, Logic)
                rv += (
                    " "
                    + "variable VAR_"
                    + write_pipe_wire_var_vhdl
                    + " : "
                    + vhdl_type_str
                    + ";\n"
                )

    # State regs
    if len(Logic.state_regs) > 0:
        rv += " " + "-- State registers comb logic variables\n"
        for state_reg in Logic.state_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += "variable REG_VAR_" + vhdl_name + " : " + vhdl_type_str + ";\n"

    # BEGIN BEGIN BEGIN
    rv += "begin\n"

    # Input regs
    if timing_params._has_input_regs:
        rv += " -- Input regs\n"
        for input_port in Logic.inputs:
            rv += (
                """ io_registers.input_regs."""
                + VHDL.WIRE_TO_VHDL_NAME(input_port, Logic)
                + """ <= """
                + VHDL.WIRE_TO_VHDL_NAME(input_port, Logic)
                + """;\n"""
            )
        if needs_clk_en:
            rv += (
                """ io_registers.input_regs."""
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """ <= """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """;\n"""
            )

    if is_raw_hdl and needs_regs:
        # Raw hdl regs
        rv += """
 -- Raw hdl REGS
 -- Default read raw hdl regs once per clock
 read_raw_hdl_pipeline_regs := manual_registers_r.raw_hdl_pipeline;
 -- Default write contents of raw hdl regs
 write_raw_hdl_pipeline_regs := read_raw_hdl_pipeline_regs;
  """

    # Globals
    if len(Logic.state_regs) > 0:
        rv += """
  -- STATE REGS
  -- Default read regs into vars\n"""
        for state_reg in Logic.state_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += "  REG_VAR_" + vhdl_name + " := " + vhdl_name + ";\n"

    # Is there a pseudo stage of constant prop?
    if pipeline_hdl_params.pipeline_map.const_network_stage_info is not None:
        const_stage_info = pipeline_hdl_params.pipeline_map.const_network_stage_info
        rv += " " + "-- Constants and things derived from constants alone\n"
        # Write the text for each submodule level ~logic level in this stage
        for submodule_level_info in const_stage_info.submodule_level_infos:
            rv += GET_SUBMODULE_LEVEL_TEXT(
                inst_name,
                Logic,
                parser_state,
                TimingParamsLookupTable,
                submodule_level_info,
                pipeline_hdl_params,
            )

    # Is there a pseudo stage of non vol read only global prop?
    if pipeline_hdl_params.pipeline_map.read_only_global_network_stage_info is not None:
        nonvol_ro_stage_info = (
            pipeline_hdl_params.pipeline_map.read_only_global_network_stage_info
        )
        rv += " " + "-- Reads from global variables\n"
        # Read each global into VAR_ variable
        for ro_var in Logic.read_only_global_wires:
            rv += (
                "     "
                + "VAR_"
                + VHDL.WIRE_TO_VHDL_NAME(ro_var, Logic)
                + " := "
                + "global_to_module."
                + VHDL.WIRE_TO_VHDL_NAME(ro_var, Logic)
                + ";\n"
            )
        # Write the text for each submodule level ~logic level in this stage
        for submodule_level_info in nonvol_ro_stage_info.submodule_level_infos:
            rv += GET_SUBMODULE_LEVEL_TEXT(
                inst_name,
                Logic,
                parser_state,
                TimingParamsLookupTable,
                submodule_level_info,
                pipeline_hdl_params,
            )

    # The stages of pipeline
    rv += "\n"
    rv += " -- Loop to construct simultaneous register transfers for each of the pipeline stages\n"
    rv += " -- LATENCY=0 is combinational Logic\n"
    rv += " " + "for STAGE in 0 to ADDED_PIPELINE_LATENCY loop\n"

    # Raw hdl still write pipe
    if is_raw_hdl:
        rv += " " + " " + "-- Input to first stage are inputs to function\n"
        rv += " " + " " + "if STAGE=0 then\n"

        if needs_clk_en:
            rv += " " + " " + " " + "-- Raw hdl mux in clock enable\n"
            rv += (
                " "
                + " "
                + " "
                + "read_pipe."
                + VHDL.WIRE_TO_VHDL_NAME(C_TO_LOGIC.CLOCK_ENABLE_NAME, Logic)
                + "(0) := clk_en_internal;\n"
            )

        if len(Logic.inputs) > 0:
            rv += " " + " " + " " + "-- raw hdl mux in inputs\n"
            for input_wire in Logic.inputs:
                if timing_params._has_input_regs:
                    rv += (
                        " "
                        + " "
                        + " "
                        + "read_pipe."
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, Logic)
                        + " := io_registers_r.input_regs."
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, Logic)
                        + ";\n"
                    )
                else:
                    rv += (
                        " "
                        + " "
                        + " "
                        + "read_pipe."
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, Logic)
                        + " := "
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, Logic)
                        + ";\n"
                    )

        # Also mux volatile global regs into wire - act like regular wire
        # Does this make sense for raw vhdl? ever used?
        for state_reg in Logic.state_regs:
            if Logic.state_regs[state_reg].is_volatile:
                rv += (
                    " "
                    + " "
                    + " "
                    + "read_pipe."
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
                    + " := REG_VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
                    + ";\n"
                )

        rv += " " + " " + "else\n"
        rv += " " + " " + " " + "-- Default read from previous stage\n"
        rv += (
            " " + " " + " " + "read_pipe := " + "read_raw_hdl_pipeline_regs(STAGE-1);\n"
        )
        rv += " " + " " + "end if;\n"
        rv += " " + " " + "-- Default write contents of previous stage\n"
        rv += " " + " " + "write_pipe := read_pipe;\n"
        rv += "\n"

    # C built in Logic is static in the stages code here but coded as generic
    rv += VHDL.GET_ENTITY_PROCESS_STAGES_TEXT(
        inst_name, Logic, parser_state, TimingParamsLookupTable, pipeline_hdl_params
    )

    # Raw hdl still write pipe
    if is_raw_hdl:
        rv += " " + " " + "-- Write to stage reg\n"
        rv += " " + " " + "write_raw_hdl_pipeline_regs(STAGE) := write_pipe;\n"

    rv += " " + "end loop;\n"
    rv += "\n"

    # Raw hdl still write pipe
    if is_raw_hdl:
        # Self regs
        if needs_regs:
            rv += (
                " "
                + "manual_registers.raw_hdl_pipeline <= write_raw_hdl_pipeline_regs;\n"
            )
        # Outputs
        if len(Logic.outputs) > 0:
            rv += (
                " "
                + "-- raw hdl last stage of pipeline return wire to return port/reg\n"
            )
            for output_wire in Logic.outputs:
                if timing_params._has_output_regs:
                    rv += (
                        " "
                        + "io_registers.output_regs."
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                        + " <= "
                        + "write_raw_hdl_pipeline_regs(ADDED_PIPELINE_LATENCY)."
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                        + ";\n"
                    )
                else:
                    rv += (
                        " "
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                        + " <= "
                        + "write_raw_hdl_pipeline_regs(ADDED_PIPELINE_LATENCY)."
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                        + ";\n"
                    )

    # State regs
    if len(Logic.state_regs) > 0:
        rv += """-- Write regs vars to comb logic\n"""
        for state_reg in Logic.state_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += "REG_COMB_" + vhdl_name + " <= " + "REG_VAR_" + vhdl_name + ";\n"

    # Shared write only globals drive from 'when fully driven last' anywhere pipeline
    if len(Logic.write_only_global_wires) > 0:
        rv += "-- Global wires driven various places in pipeline\n"
        for var_name in Logic.write_only_global_wires:
            # # Do final read of global wire
            # driver_of_global_wire = logic.wire_driven_by[var_name]
            # text += "     " + "VAR_" + WIRE_TO_VHDL_NAME(var_name, logic) + " := " + GET_RHS(driver_of_global_wire, inst_name, logic, parser_state, TimingParamsLookupTable) + ";\n"
            # Do final write into wire var
            if VHDL.GLOBAL_VAR_IS_SHARED(var_name, parser_state):
                if needs_clk_en:
                    rv += (
                        "if clk_en_internal='1' then\n"
                        + "  module_to_global."
                        + VHDL.WIRE_TO_VHDL_NAME(var_name, Logic)
                        + " <= VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(var_name, Logic)
                        + ";\n"
                        + "else\n"
                        + "  module_to_global."
                        + VHDL.WIRE_TO_VHDL_NAME(var_name, Logic)
                        + " <= "
                        + VHDL.STATE_REG_TO_VHDL_INIT_STR(var_name, Logic, parser_state)
                        + ";\n"
                        + "end if;\n"
                    )
                else:
                    rv += (
                        "module_to_global."
                        + VHDL.WIRE_TO_VHDL_NAME(var_name, Logic)
                        + " <= VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(var_name, Logic)
                        + ";\n"
                    )

    # Add wait statement if nothing in sensitivity list for simulation?
    # GHDL->Yosys doesnt like?
    """if (
        process_sens_list == ""
        and (SIM.SIM_TOOL != VERILATOR)
        and (SIM.SIM_TOOL != CXXRTL)
    ):
        rv += " " + "-- For simulation? \n"
        rv += " " + "wait;\n"
    """
    rv += "end process;\n"

    # Register IO regs, only delaying signals clock enable - not responding to them
    if has_io_regs:
        rv += """-- Register IO reg signal
io_registers_r <= io_registers when rising_edge(clk);
"""

    # Register comb pipelining signals
    if needs_regs:
        rv += """
-- Register comb signals
process(clk) is
begin
 if rising_edge(clk) then\n"""
        if needs_clk_en:
            rv += " if clk_en_internal='1' then\n"

        if len(Logic.state_regs) > 0:
            for state_reg in Logic.state_regs:
                vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
                vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
                rv += "     " + vhdl_name + " <= REG_COMB_" + vhdl_name + ";\n"

        if needs_manual_regs:
            rv += """
     manual_registers_r <= manual_registers;
"""
        # Autogen pipeline regs
        if not is_raw_hdl:
            for stage in range(0, pipeline_latency):
                rv += f"     -- Stage {stage}\n"
                for wire_name in pipeline_hdl_params.wires_to_decl:
                    (
                        start_stage,
                        end_stage,
                    ) = pipeline_hdl_params.wire_to_reg_stage_start_end[wire_name]
                    if start_stage is None or end_stage is None:
                        continue
                    if stage in range(start_stage, end_stage + 1):
                        vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(
                            wire_name, Logic, parser_state
                        )
                        write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, Logic)
                        rv += (
                            "     "
                            + "REG_STAGE"
                            + str(stage)
                            + "_"
                            + write_pipe_wire_var_vhdl
                            + " <= COMB_STAGE"
                            + str(stage)
                            + "_"
                            + write_pipe_wire_var_vhdl
                            + ";\n"
                        )

        if needs_clk_en:
            rv += " end if;\n"
        rv += """ end if;
end process;
"""

    # Connect io_registers_r.output_regs. to output port
    if timing_params._has_output_regs:
        rv += " -- Output regs\n"
        for output_wire in Logic.outputs:
            rv += (
                " "
                + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                + " <= "
                + "io_registers_r.output_regs."
                + VHDL.WIRE_TO_VHDL_NAME(output_wire, Logic)
                + ";\n"
            )

    # Connect shared globals to global bus
    shared_global_regs = set()
    for state_reg, var_info in Logic.state_regs.items():
        if var_info in parser_state.global_vars.values() and VHDL.GLOBAL_VAR_IS_SHARED(
            state_reg, parser_state
        ):
            shared_global_regs.add(state_reg)
    if len(shared_global_regs) > 0:
        rv += "-- Shared global regs\n"
        for state_reg in shared_global_regs:
            vhdl_type_str = VHDL.WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
            vhdl_name = VHDL.WIRE_TO_VHDL_NAME(state_reg, Logic)
            rv += "module_to_global." + vhdl_name + " <= " + "REG_COMB_" + vhdl_name
            if needs_clk_en:
                rv += " when clk_en_internal='1' else " + vhdl_name
            rv += ";\n"

    return rv


def GET_C_ENTITY_PROCESS_STAGES_TEXT(
    inst_name, logic, parser_state, TimingParamsLookupTable, pipeline_hdl_params
):
    timing_params = TimingParamsLookupTable[inst_name]
    pipeline_latency = timing_params.GET_PIPELINE_LOGIC_ADDED_LATENCY(
        parser_state, TimingParamsLookupTable
    )
    text = "  " + " "
    for stage in range(0, pipeline_latency + 1):  # 0 latency is 1 comb stage
        is_first_stage = stage == 0
        is_last_stage = stage == pipeline_latency
        text += f"if STAGE = {stage} then\n"
        if len(pipeline_hdl_params.pipeline_map.stage_infos) <= stage:
            raise Exception(
                f"There is no stage {stage} in {logic.func_name} pipeline_latency={pipeline_latency}"
            )
        stage_info = pipeline_hdl_params.pipeline_map.stage_infos[stage]
        text += GET_STAGE_TEXT(
            inst_name,
            logic,
            parser_state,
            TimingParamsLookupTable,
            stage_info,
            pipeline_hdl_params,
            is_first_stage,
            is_last_stage,
        )
        if is_last_stage:
            text += "  " + " " + "end if;\n"
        else:
            text += "  " + " " + "els"

    return text


def GET_STAGE_TEXT(
    inst_name,
    logic,
    parser_state,
    TimingParamsLookupTable,
    stage_info,
    pipeline_hdl_params,
    is_first_stage,
    is_last_stage,
):
    timing_params = TimingParamsLookupTable[inst_name]
    needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(logic, parser_state)
    text = ""
    vol_state_regs = []
    for state_reg in logic.state_regs:
        if logic.state_regs[state_reg].is_volatile:
            vol_state_regs.append(state_reg)
    if is_first_stage:
        # First stage reads from inputs
        if needs_clk_en:
            text += "     " + "-- Mux in clock enable\n"
            text += (
                "     "
                + "VAR_"
                + VHDL.WIRE_TO_VHDL_NAME(C_TO_LOGIC.CLOCK_ENABLE_NAME, logic)
                + "(0) := clk_en_internal;\n"
            )

        if len(logic.inputs) > 0:
            text += "     " + "-- Mux in inputs\n"
            for input_wire in logic.inputs:
                if timing_params._has_input_regs:
                    text += (
                        "     "
                        + "VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, logic)
                        + " := io_registers_r.input_regs."
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, logic)
                        + ";\n"
                    )
                else:
                    text += (
                        "     "
                        + "VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, logic)
                        + " := "
                        + VHDL.WIRE_TO_VHDL_NAME(input_wire, logic)
                        + ";\n"
                    )

        # Also mux volatile global regs into wire - act like regular wire
        if len(vol_state_regs) > 0:
            text += (
                "     "
                + "-- Volatiles read from regs, written to pipe in first stage\n"
            )
            for state_reg in vol_state_regs:
                text += (
                    "     "
                    + "VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, logic)
                    + " := REG_VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, logic)
                    + ";\n"
                )
    else:
        # Not first stage typical reg from prev stage
        text += "     -- Read from prev stage\n"
        for wire_name in pipeline_hdl_params.wires_to_decl:
            start_stage, end_stage = pipeline_hdl_params.wire_to_reg_stage_start_end[
                wire_name
            ]
            if start_stage is None or end_stage is None:
                continue
            if stage_info.stage_num - 1 in range(start_stage, end_stage + 1):
                write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, logic)
                text += (
                    "     "
                    + "VAR_"
                    + write_pipe_wire_var_vhdl
                    + f" := REG_STAGE{stage_info.stage_num-1}_"
                    + write_pipe_wire_var_vhdl
                    + ";\n"
                )

    # Output port connections of completing previous submodule instantiations
    if len(stage_info.submodule_output_ports) > 0:
        text += "     " + "-- Submodule outputs\n"
    for submodule_output_port_wire in stage_info.submodule_output_ports:
        text += (
            "     "
            + VHDL.GET_WRITE_PIPE_WIRE_VHDL(submodule_output_port_wire, logic, parser_state)
            + " := "
            + VHDL.WIRE_TO_VHDL_NAME(submodule_output_port_wire, logic)
            + ";\n"
        )

    # Write the text for each submodule level ~logic level in this stage
    text += "\n"
    for submodule_level_info in stage_info.submodule_level_infos:
        text += GET_SUBMODULE_LEVEL_TEXT(
            inst_name,
            logic,
            parser_state,
            TimingParamsLookupTable,
            submodule_level_info,
            pipeline_hdl_params,
        )

    if is_last_stage:
        # -- Last stage of pipeline volatile global wires write to function volatile global regs
        if len(vol_state_regs) > 0:
            text += (
                "     " + "-- Volatiles read from pipe written to regs in last stage\n"
            )
            for state_reg in vol_state_regs:
                # Do final read of vol wire
                driver_of_vol_wire = logic.wire_driven_by[state_reg]
                text += (
                    "     "
                    + "VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, logic)
                    + " := "
                    + VHDL.GET_RHS(
                        driver_of_vol_wire,
                        inst_name,
                        logic,
                        parser_state,
                        TimingParamsLookupTable,
                    )
                    + ";\n"
                )
                # Do final write into reg
                text += (
                    "     "
                    + "REG_VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, logic)
                    + " := VAR_"
                    + VHDL.WIRE_TO_VHDL_NAME(state_reg, logic)
                    + ";\n"
                )

        # Outputs
        if len(logic.outputs) > 0:
            text += (
                "     " + "-- Last stage of pipeline return wire to return port/reg\n"
            )
            for output_wire in logic.outputs:
                if timing_params._has_output_regs:
                    text += (
                        "     "
                        + "io_registers.output_regs."
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, logic)
                        + " <= "
                        + "VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, logic)
                        + ";\n"
                    )
                else:
                    text += (
                        "     "
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, logic)
                        + " <= "
                        + "VAR_"
                        + VHDL.WIRE_TO_VHDL_NAME(output_wire, logic)
                        + ";\n"
                    )
    else:
        # Is not last stage typical write to comb signals
        text += "     -- Write to comb signals\n"
        for wire_name in pipeline_hdl_params.wires_to_decl:
            start_stage, end_stage = pipeline_hdl_params.wire_to_reg_stage_start_end[
                wire_name
            ]
            if start_stage is None or end_stage is None:
                continue
            if stage_info.stage_num in range(start_stage, end_stage + 1):
                write_pipe_wire_var_vhdl = VHDL.WIRE_TO_VHDL_NAME(wire_name, logic)
                text += (
                    "     "
                    + f"COMB_STAGE{stage_info.stage_num}_"
                    + write_pipe_wire_var_vhdl
                    + " <= VAR_"
                    + write_pipe_wire_var_vhdl
                    + ";\n"
                )

    return text


def RENDER_TEXT_FROM_DRIVER_DRIVEN_PAIR(
    driving_wire, driven_wire, inst_name, logic, parser_state, TimingParamsLookupTable
):
    # Dont write text connecting VHDL input ports
    # (connected directly in func call params)
    if C_TO_LOGIC.WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(
        driven_wire, logic, parser_state
    ):
        return None
    if C_TO_LOGIC.WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(
        driven_wire, logic, parser_state
    ):
        return None

    ### WRITE VHDL TEXT
    # If the driving wire is a submodule output AND LATENCY>0 then RHS uses register style
    # as way to ensure correct multi clock behavior
    RHS = VHDL.GET_RHS(driving_wire, inst_name, logic, parser_state, TimingParamsLookupTable)
    # Submodule or not LHS is write pipe wire
    LHS = VHDL.GET_LHS(driven_wire, logic, parser_state)
    # print "logic.func_name",logic.func_name
    # print "driving_wire, driven_wire",driving_wire, driven_wire
    # Need VHDL conversions for this type assignment?
    TYPE_RESOLVED_RHS = VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS(
        RHS, logic, driving_wire, driven_wire, parser_state
    )

    # Typical wires using := assignment, but feedback wires need <=
    ass_op = ":="
    if driven_wire in logic.feedback_vars:
        ass_op = "<="
    text = LHS + " " + ass_op + " " + TYPE_RESOLVED_RHS + ";" + "\n"
    return text


def GET_SUBMODULE_LEVEL_TEXT(
    inst_name,
    logic,
    parser_state,
    TimingParamsLookupTable,
    submodule_level_info,
    pipeline_hdl_params,
):
    timing_params = TimingParamsLookupTable[inst_name]
    # Starts with wires driving other wires
    text = f"     -- Submodule level {submodule_level_info.level_num}\n"
    for driver_driven_wire_pair in submodule_level_info.driver_driven_wire_pairs:
        driving_wire, driven_wire = driver_driven_wire_pair
        pair_text = RENDER_TEXT_FROM_DRIVER_DRIVEN_PAIR(
            driving_wire,
            driven_wire,
            inst_name,
            logic,
            parser_state,
            TimingParamsLookupTable,
        )
        if pair_text is not None:
            text += "     " + pair_text

    # Ends with submodule logic connections
    for submodule_inst in submodule_level_info.submodule_insts:
        submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
        submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
        submodule_latency_from_container_logic = timing_params.GET_SUBMODULE_LATENCY(
            submodule_inst_name, parser_state, TimingParamsLookupTable
        )
        text += (
            " "
            + " "
            + "   -- "
            + C_TO_LOGIC.LEAF_NAME(submodule_inst, True)
            + " LATENCY="
            + str(submodule_latency_from_container_logic)
            + "\n"
        )
        entity_connection_text = VHDL.GET_ENTITY_CONNECTION_TEXT(
            submodule_logic,
            submodule_inst,
            inst_name,
            logic,
            TimingParamsLookupTable,
            parser_state,
            submodule_latency_from_container_logic,
        )
        text += entity_connection_text + "\n"

    return text
