"""Front-end-neutral Logic IR shared by the C (C_TO_LOGIC.py) and Python (PY_TO_LOGIC.py)
front ends: the Logic graph, ParserState, source-location metadata, internal naming
conventions, C type string helpers and the whole-design passes both front ends run.
See docs/LOGIC_DESIGN.md.
"""

import copy
import hashlib
import math
import os
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from utilities import FIND_REGEX_MATCHES

# LOGIC sits at the bottom of the compiler's import graph: AUTO and PY_TO_LOGIC read its
# constants at import time, so it must load completely before anything else. Its only
# other src import is the C front end, imported locally by the one fallback that needs it.


@dataclass(eq=False)
class ASTMeta:
    """Frontend-agnostic source location metadata stored on Logic objects.

    Both the C (pycparser) and Pypeline (python ast) frontends populate this.
    coord_str() and location_text() derive uniform strings from the raw fields
    so formatting is defined once regardless of which frontend produced the node.
    """

    src_file: str  # full source file path
    line: int  # 1-based line number
    col: int  # 0-based column offset
    end_col: Optional[int]  # end column if available (Python AST), else None
    hash_suffix: str = ""  # md5 fragment for C-frontend uniqueness; "" for Pypeline
    raw: Any = None  # original node — escape hatch for C-only deep navigation

    def coord_str(self) -> str:
        """Wire-name-safe location tag, e.g. 'myfile_py_l5_c12_a1b2c3d4'"""
        base = os.path.basename(self.src_file).replace(".", "_")
        end = f"_e{self.end_col}" if self.end_col is not None else ""
        return f"{base}_l{self.line}_c{self.col}{end}{self.hash_suffix}"

    def location_text(self) -> str:
        """Human-readable for error messages, e.g. 'myfile.py:5:12'"""
        return f"{self.src_file}:{self.line}:{self.col}"

    def __eq__(self, other):
        if not isinstance(other, ASTMeta):
            return NotImplemented
        return self.coord_str() == other.coord_str()

    def __hash__(self):
        return hash(self.coord_str())


# Debug
TRIM_COLLAPSE_LOGIC = (
    True  # Flag to reduce duplicate wires, unused modules, False for debug
)

# Internal names/keywords
RETURN_WIRE_NAME = "return_output"
SUBMODULE_MARKER = "____"  # Hacky, need to be something unlikely as wire name
CONST_PREFIX = "CONST_"
ENUM_CONST_MARKER = "$"  # Hackety hack hack
CLOCK_ENABLE_NAME = "CLOCK_ENABLE"
MUX_LOGIC_NAME = "MUX"
UNARY_OP_LOGIC_NAME_PREFIX = "UNARY_OP"
BIN_OP_LOGIC_NAME_PREFIX = "BIN_OP"
CONST_REF_RD_FUNC_NAME_PREFIX = "CONST_REF_RD"
VAR_REF_ASSIGN_FUNC_NAME_PREFIX = "VAR_REF_ASSIGN"
VAR_REF_RD_FUNC_NAME_PREFIX = "VAR_REF_RD"
CAST_FUNC_NAME_PREFIX = "CAST_TO"
ONE_HOT_EQ_LOGIC_NAME = "ONE_HOT_EQ"
BOOL_C_TYPE = "uint1_t"
VHDL_FUNC_NAME = "__vhdl__"
PRINTF_FUNC_NAME = "printf"
SIM_ASSERT_FUNC_NAME = "sim_assert"
SIM_FINISH_FUNC_NAME = "sim_finish"


def IS_SIM_CTRL_FUNC_NAME(func_name):
    """True for printf/sim_print, sim_assert, and sim_finish submodule instances: all are
    void, simulation-console-facing builtins that need CLOCK_ENABLE and a clk-gated process
    to fire once per enabled cycle, and whose outputs never drive anything."""
    return (
        func_name.startswith(PRINTF_FUNC_NAME)
        or func_name.startswith(SIM_ASSERT_FUNC_NAME)
        or func_name.startswith(SIM_FINISH_FUNC_NAME)
    )


ACCUM_FUNC_NAME = "accum"
COMPOUND_NULL = "COMPOUND_NULL"
# Unary Operators
UNARY_OP_NOT_NAME = "NOT"
UNARY_OP_NEGATE_NAME = "NEGATE"
# Binary operators
BIN_OP_GT_NAME = "GT"
BIN_OP_GTE_NAME = "GTE"
BIN_OP_LT_NAME = "LT"
BIN_OP_LTE_NAME = "LTE"
BIN_OP_PLUS_NAME = "PLUS"
BIN_OP_MINUS_NAME = "MINUS"
BIN_OP_NEQ_NAME = "NEQ"
BIN_OP_EQ_NAME = "EQ"
BIN_OP_AND_NAME = "AND"  # Ampersand? Nah, look like we got pointers round here?
BIN_OP_OR_NAME = "OR"
BIN_OP_XOR_NAME = "XOR"
BIN_OP_SL_NAME = "SL"
BIN_OP_SR_NAME = "SR"
BIN_OP_MOD_NAME = "MOD"
BIN_OP_MULT_NAME = "MULT"
BIN_OP_INFERRED_MULT_NAME = "INFERRED_MULT"
BIN_OP_DIV_NAME = "DIV"

# Hacky internal names hash large strings into short hex codes, dont need them to be too large
C_AST_NODE_HASH_LEN = 4


# Merge dicts whose values are ASTMeta; a shared key must map to the same location
def AST_META_VAL_UNIQUE_KEY_DICT_MERGE(self_d1, d2):
    # uh?
    if self_d1 == d2:
        return self_d1

    for key in d2:
        if key in self_d1:
            v1 = self_d1[key]
            v2 = d2[key]
            if not v1 == v2:
                print(
                    "AST_META_VAL_UNIQUE_KEY_DICT_MERGE Dicts aren't unique:",
                    self_d1,
                    d2,
                )
                print("key", key)
                print("v1", v1, v1.location_text())
                print("v2", v2, v2.location_text())
                print(0 / 0)
                sys.exit(-1)

    # Do merge with dict methods
    rv = self_d1
    rv.update(d2)

    return rv


def LIST_VAL_UNIQUE_KEY_DICT_MERGE(self_d1, d2):
    # Uhhh?
    if self_d1 == d2:
        return self_d1

    for key in d2:
        if key in self_d1:
            v1 = self_d1[key]
            v2 = d2[key]
            if str(v1) != str(v2):
                print("List val dicts aren't unique:", self_d1, d2)
                print("key", key)
                print("v1", v1)
                print("v2", v2)
                print(0 / 0)
                sys.exit(-1)

    # Do merge with dict methods
    rv = self_d1

    rv.update(d2)

    return rv


def UNIQUE_KEY_DICT_MERGE(self_d1, d2):
    # Uhh?
    if self_d1 == d2:
        return self_d1

    # Check that are unique
    for key in d2:
        if key in self_d1:
            v1 = self_d1[key]
            v2 = d2[key]
            if v1 != v2:
                print("Dicts aren't unique:", self_d1, d2)
                print("key", key)
                print("v1", v1)
                print("v2", v2)
                print(0 / 0)
                sys.exit(-1)
        # except:
        # pass

    # Do merge with dict methods
    rv = self_d1

    rv.update(d2)

    return rv


def DICT_SET_VALUE_MERGE(d1, d2):
    rv = d1
    for key in d2:
        if key in d1:
            # Result is union of two sets
            rv[key] = d1[key] | d2[key]
        else:
            rv[key] = d2[key]

    return rv


class AutoMultiCycleConstraint:
    """Cycle-count constraint of one AUTO_MULTI_CYCLE multi-cycle path, recorded in
    Logic.auto_multi_cycle_tuples[(start_reg, end_reg)] by the Pypeline elaborator.
      key            pypeline.AUTO_MULTI_CYCLE.canonical_key (cross-pass cache key)
      latency=N      fixed: the sweep never changes the count
      start_latency  the count the first sweep iteration uses (else 1)
      max_latency    the sweep never raises the count above this
    The elaborated count itself lives in the matching Logic.mcp_tuples entry.
    """

    __slots__ = ("key", "latency", "start_latency", "max_latency", "seed")

    def __init__(
        self, key, latency=None, start_latency=None, max_latency=None, seed=None
    ):
        self.key = key
        self.latency = latency
        self.start_latency = start_latency
        self.max_latency = max_latency
        # The starting count a latency hint or the latency memory gave the tag
        # (pypeline.SET_LATENCY_SEEDS), else None. Not identity: equality,
        # hashing and keys use the source constraint only.
        self.seed = seed

    @staticmethod
    def from_tag(tag):
        return AutoMultiCycleConstraint(
            tag.canonical_key,
            tag.fixed_latency,
            tag.start_latency,
            tag.max_latency,
            getattr(tag, "seed", None),
        )

    def _source_state(self):
        return (self.key, self.latency, self.start_latency, self.max_latency)

    def __getstate__(self):
        return self._source_state() + (self.seed,)

    def __setstate__(self, state):
        self.key, self.latency, self.start_latency, self.max_latency = state[:4]
        self.seed = state[4] if len(state) > 4 else None

    def __eq__(self, other):
        return (
            isinstance(other, AutoMultiCycleConstraint)
            and self._source_state() == other._source_state()
        )

    def __hash__(self):
        return hash(self._source_state())

    def is_fixed(self):
        return self.latency is not None

    def upper_bound(self):
        """Most cycles the path may be given (None = no cap)."""
        return self.latency if self.latency is not None else self.max_latency

    def describe(self):
        if self.latency is not None:
            return f"latency={self.latency}"
        parts = []
        if self.start_latency is not None:
            parts.append(f"start_latency={self.start_latency}")
        if self.max_latency is not None:
            parts.append(f"max_latency={self.max_latency}")
        return ", ".join(parts) if parts else "unconstrained"


class AutoPipelineLatency:
    """Latency constraint on one AUTO_PIPELINE call site, recorded per local
    submodule instance in Logic.sub_inst_to_auto_pipeline_latency.

    Built from pypeline.AUTO_PIPELINE(func, latency=/start_latency=/max_latency=)
    via from_tag, or from C `#pragma AUTOPIPELINE N` (fixed N). All three None
    means unconstrained: the sweep treats that region exactly as it always has.
      latency=N        fixed: exactly N inserted registers, in every build
      start_latency=S  the planned sweep's first iteration builds S registers
      max_latency=M    the sweep never builds more than M registers
    key_suffix() must stay identical to pypeline._auto_pipeline_latency_suffix
    (AUTO_PIPELINE canonical key / entity-name identity); a unit test checks it.
    """

    __slots__ = ("latency", "start_latency", "max_latency", "seed")

    def __init__(self, latency=None, start_latency=None, max_latency=None, seed=None):
        self.latency = latency
        self.start_latency = start_latency
        self.max_latency = max_latency
        # The starting count a latency hint or the latency memory gave the tag
        # (pypeline.SET_LATENCY_SEEDS), else None. Like start_latency=, it is
        # where the tag's planned sweep starts (start(), is_region()).
        # Equality, hashing, keys, key_suffix() and is_unconstrained() use the
        # source constraint only.
        self.seed = seed

    @staticmethod
    def from_tag(tag):
        return AutoPipelineLatency(
            getattr(tag, "fixed_latency", None),
            getattr(tag, "start_latency", None),
            getattr(tag, "max_latency", None),
            getattr(tag, "seed", None),
        )

    def _source_state(self):
        return (self.latency, self.start_latency, self.max_latency)

    def __getstate__(self):
        return self._source_state() + (self.seed,)

    def __setstate__(self, state):
        self.latency, self.start_latency, self.max_latency = state[:3]
        self.seed = state[3] if len(state) > 3 else None

    def start(self):
        """Where a region's planned sweep starts: the seed, else start_latency
        (None when neither is set)."""
        return self.seed if self.seed is not None else self.start_latency

    def is_region(self):
        """Planned as its own region: a source constraint, or a starting count
        from a hint or the latency memory (a start-only region, like
        start_latency=; see AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS for the
        callees a seed never makes a region)."""
        return not self.is_unconstrained() or self.seed is not None

    def is_unconstrained(self):
        return (
            self.latency is None
            and self.start_latency is None
            and self.max_latency is None
        )

    def is_fixed(self):
        return self.latency is not None

    def upper_bound(self):
        """Most registers the region may hold (None = no cap)."""
        return self.latency if self.latency is not None else self.max_latency

    def key_suffix(self):
        if self.latency is not None:
            return f"_latency_{self.latency}"
        suffix = ""
        if self.start_latency is not None:
            suffix += f"_start_latency_{self.start_latency}"
        if self.max_latency is not None:
            suffix += f"_max_latency_{self.max_latency}"
        return suffix

    def describe(self):
        if self.latency is not None:
            return f"latency={self.latency}"
        parts = []
        if self.start_latency is not None:
            parts.append(f"start_latency={self.start_latency}")
        if self.max_latency is not None:
            parts.append(f"max_latency={self.max_latency}")
        return ", ".join(parts) if parts else "unconstrained"

    def conflict_with_fixed(self, fixed):
        """The offending setting if this constraint can't hold on a function
        whose pipeline_latency is `fixed`, else None."""
        if self.latency is not None and self.latency != fixed:
            return f"latency={self.latency}"
        if self.start_latency is not None and self.start_latency != fixed:
            return f"start_latency={self.start_latency}"
        if self.max_latency is not None and self.max_latency < fixed:
            return f"max_latency={self.max_latency}"
        return None

    def __eq__(self, other):
        return isinstance(other, AutoPipelineLatency) and (
            self._source_state() == other._source_state()
        )

    def __hash__(self):
        return hash(self._source_state())

    def __repr__(self):
        return f"AutoPipelineLatency({self.describe()})"


class Logic:
    def __init__(self):
        ####### MODIFY DEEP COPY + MERGES TOO
        #
        # ~
        #     ~~~~~
        # ~~~~~~~~~~~~~
        # ~~~~  Zero plus zero is the lord's work ^^^^^^
        # ``            `````````
        # of Montreal - St. Sebastian

        # FOR LOGIC IMPLEMENTED IN C THE STRINGS MUST BE C SAFE
        # (inst name adjust is after all the parsing so dont count SUBMODULE_MARKER)
        self.func_name = None  # Function name
        # My containing func names (could be used in multiple places
        self.containing_funcs = set()
        self.variable_names = set()  # Unordered set original variable names
        self.wires = set()  # Unordered set ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
        self.clock_enable_wires = []  # Over time, nesting ifs create more entries in list
        # Vars pragmad to be combinatorial feedback wires: name -> None, an
        # insertion-ordered set so emitted VHDL follows declaration order
        self.feedback_vars = {}
        self.inputs = []  # Ordered list of inputs ["a","b"]
        self.outputs = []  # Ordered list of outputs ["return"]
        self.state_regs = {}  # name -> variable info
        self.write_only_global_wires = {}  # name -> variable info (from list of global vars)
        self.read_only_global_wires = {}  # name -> variable info (from list of global vars)
        # global_wire_driven_paths: write_only_global_wires name -> set of driven
        # struct-field path tuples (e.g. {(), } for a whole-wire write, {("x",)} for
        # a `.x` field write). Populated by Pypeline's PY_TO_LOGIC.py elaborator only
        # (empty/absent for C-frontend Logic objects) -- lets multiple @MAIN functions
        # split non-overlapping fields of one compound global Wire[T]/Output[T]. See
        # VHDL.py's "Directly connected global wires" top-level wiring and
        # docs/PY_TO_LOGIC_DESIGN.md's Global Wires section.
        self.global_wire_driven_paths = {}
        # global_wire_dynamic_index_writes: set of write_only_global_wires names this
        # function writes via a variable (non-constant) array index -- such writes
        # aren't tracked leaf-by-leaf in global_wire_driven_paths, so combining one
        # with a second writer function of the same wire can't be safely validated;
        # see global_wire_driven_paths above.
        self.global_wire_dynamic_index_writes = set()
        # readback_global_wires: write_only_global_wires name -> name of the extra
        # internal input wire (<name>_PYPELINE_READBACK) created when this function
        # both writes AND reads the same global wire. The readback wire is registered in
        # read_only_global_wires (so the normal global_to_module record/port/read-
        # stage machinery feeds it) and drives the implicit whole-wire first alias:
        # the top level (VHDL.py "Directly connected global wires") feeds it with
        # zeros in the regions this function itself drives (read-before-own-write
        # = 0) and with the OTHER writers' live values everywhere else, giving
        # flattened-leaf semantics for a writer reading foreign leaves. Pypeline
        # frontend only; empty for C-frontend Logic objects.
        self.readback_global_wires = {}
        self.uses_nonvolatile_state_regs = False
        self.submodule_instances = {}  # instance name -> logic func_name
        self.next_user_inst_name = None  # User name for func
        self.debug_names = set()  # Names MARK_DEBUG
        self.mcp_tuples = set()  # Tuples of MCP params
        # Pypeline frontend only: (start_reg, end_reg) of an mcp_tuples entry
        # -> AutoMultiCycleConstraint when that multi-cycle path came from an AUTO_MULTI_CYCLE
        # tag (the sweep may raise its cycle count). Empty for C designs.
        self.auto_multi_cycle_tuples = {}
        self.next_func_call_auto_pipeline_latency = (
            None  # Pending #pragma AUTOPIPELINE constraint for next func call
        )
        # Which instances are tagged auto-pipeline: local inst name ->
        # AutoPipelineLatency (unconstrained unless latency/start/max given)
        self.sub_inst_to_auto_pipeline_latency = {}
        # Pypeline frontend only: local inst name -> AUTO_PIPELINE canonical
        # latency-cache key (pypeline.AUTO_PIPELINE.canonical_key). Empty for
        # .c-originated logic (#pragma AUTOPIPELINE has no Python object to
        # round-trip a discovered latency into).
        self.sub_inst_to_auto_pipeline_key = {}
        # Pypeline frontend only: local inst name -> AUTO_FSM canonical schedule-cache
        # key (pypeline.AUTO_FSM.canonical_key). Marks the call site whose submodule
        # is the generated resource-shared FSM entity (or, before a schedule exists,
        # the combinational passthrough placeholder). Empty for .c-originated logic.
        # Unlike sub_inst_to_auto_pipeline_key this never changes how SYN/SWEEP treat
        # the instance -- the generated FSM entity is stateful, hence already atomic
        # and zero-added-latency -- it exists so the driver can find AUTO_FSM call
        # sites to schedule. See docs/AUTO_FSM_DESIGN.md.
        self.sub_inst_to_auto_fsm_key = {}
        self.ast_meta = None
        self.pypeline_emission_names = None
        # Python clock-by-clock bodies consume these pipeline outputs in the
        # current cycle; only surrounding sliceable callers align transactions.
        self.submodule_latencies_are_self_timed = set()
        self.submodule_instance_to_source_origins = {}
        # Is this logic a c built in C function?
        self.is_c_built_in = False
        # Is this logic implemented as a VHDL function (non-pipelineable 0 clk logic, probably 0LLs)
        self.is_vhdl_func = False
        # Is this logic implemented as a VHDL expression (also 0 clk)
        self.is_vhdl_expr = False
        # Is this logic completely replaced with raw vhdl module text?
        # (non-pipelineable global func like) None if not, else the literal text.
        self.vhdl_module_text = None
        # Quoted printf format string for a printf-builtin instance's own standalone Logic()
        # (set by BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC from the containing func's
        # submodule_instance_to_printf_format_string below). Frontend-agnostic: both the C
        # and Pypeline frontends populate the per-instance dict; VHDL.GET_PRINTF_MODULE_TEXT
        # reads this instead of Logic.c_ast_node.
        self.printf_format_string = None
        # Quoted sim_assert message string for a sim_assert-builtin instance's own standalone
        # Logic(), mirroring printf_format_string above. None if no message was given.
        self.sim_assert_msg = None
        # Is this logic the input or output of a clock crossing?
        self.is_clock_crossing = False
        # TODO 'new style' is_? checks like below replacing C_TO_LOGIC generated C code stuff eventually
        self.is_new_style_bit_manip = False
        # self.is_new_style_mem_func = False
        # self.is_new_style_bit_math = False

        # Mostly for c built in C functions
        self.submodule_instance_to_ast_meta = {}
        # inst_name -> quoted printf format string, for printf-builtin submodule instances
        # (relay from call-site elaboration to BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC, which
        # copies the entry for a given instance onto that instance's own standalone
        # Logic.printf_format_string above)
        self.submodule_instance_to_printf_format_string = {}
        # inst_name -> quoted sim_assert message string (or None), for sim_assert-builtin
        # submodule instances, mirroring submodule_instance_to_printf_format_string above.
        self.submodule_instance_to_sim_assert_msg = {}
        self.submodule_instance_to_input_port_names = {}
        self.ref_submodule_instance_to_input_port_driven_ref_toks = {}
        self.ref_submodule_instance_to_ref_toks = {}

        # Python graph example was {} of strings so this
        # string based wire naming makes Pythonic sense.
        # I think pointers would work better - constant strings are the pointer?
        # Wire names with a dot means sub module connection
        # func0.a  is a port on the func0 instance
        # Connections are given as two lists "drives" and "driven by"
        self.wire_drives = {}  # wire_name -> set([driven,wire,names])
        self.wire_driven_by = {}  # wire_name -> driving wire

        # To keep track of C execution over time in logic graph,
        # each assignment assigns to a renamed variable, renamed
        # variables keep execution order
        # Need to keep dicts for variable names
        self.wire_aliases_over_time = {}  # orig var name -> [list,of,renamed,wire,names] # Further in list is further in time
        self.alias_to_orig_var_name = {}  # alias -> orig var name
        self.alias_to_driven_ref_toks = {}  # alias -> [ref,toks]

        # Need to look up types by wire name
        # wire_to_c_type[wire_name] -> c_type_str
        self.wire_to_c_type = {}

        # For timing, delay integer units (tenths of nanosec probably)
        # this is populated by vendor tool
        self.delay = None
        # True when delay was derived from the zero clock pipeline map
        # (submodule delays) instead of measured by a real synthesis run
        self.delay_is_estimated = False
        # Optional measured path decomposition supplied by timing backends
        # that can distinguish launch clock-to-Q, combinational, and setup
        # delay. ``planner_delay`` is the combinational component in the same
        # integer units as ``delay``. It is diagnostic by default; SYN's
        # internal experimental gate decides whether a planner consumes it.
        self.delay_components = None
        self.planner_delay = None
        # (value, unit) combinational cell area from a synthesis run of exactly
        # this function, when the backend measures area (DEVICE_MODELS); see
        # SYN.MEASURED_AREA
        self.measured_area = None

        # Save C code text for later
        self.c_code_text = None

        # Init constant clock enable stuff
        self.wires.add(CLOCK_ENABLE_NAME)
        self.clock_enable_wires.append(CLOCK_ENABLE_NAME)
        self.wire_to_c_type[CLOCK_ENABLE_NAME] = BOOL_C_TYPE

        # Just for functions using __clk()
        self.is_fsm_clk_func = False
        self.state_groups = []  # List of lists of state infos
        self.first_user_state = None  # First/user entry state
        self.func_call_name_to_state = {}  # Func call name to lookup of func call state
        self.func_call_node_to_entry_exit_states = {}  # Same funcs as above, node inst specific entry and exit
        # Current nested func scope since not single inst subroutines are inlined
        self.fsm_subroutine_scope = []

    @property
    def c_ast_node(self):
        """Backward-compat: returns the raw AST node stored in ast_meta.
        C-specific code that reads .c_ast_node continues to work unchanged."""
        return self.ast_meta.raw if self.ast_meta is not None else None

    # Help!
    def DEEPCOPY(self):
        rv = Logic()
        rv.func_name = self.func_name
        rv.variable_names = set(self.variable_names)
        rv.wires = set(
            self.wires
        )  # ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
        rv.inputs = self.inputs[:]  # ["a","b"]
        rv.outputs = self.outputs[:]  # ["return"]
        rv.state_regs = dict(
            self.state_regs
        )  # self.DEEPCOPY_DICT_COPY(self.state_regs)
        rv.read_only_global_wires = dict(self.read_only_global_wires)
        rv.write_only_global_wires = dict(self.write_only_global_wires)
        rv.global_wire_driven_paths = {
            k: set(v) for k, v in self.global_wire_driven_paths.items()
        }
        rv.global_wire_dynamic_index_writes = set(self.global_wire_dynamic_index_writes)
        rv.readback_global_wires = dict(self.readback_global_wires)
        rv.feedback_vars = dict.fromkeys(self.feedback_vars)
        rv.uses_nonvolatile_state_regs = self.uses_nonvolatile_state_regs
        rv.submodule_instances = dict(
            self.submodule_instances
        )  # instance name -> logic func_name all IMMUTABLE types?
        rv.next_user_inst_name = self.next_user_inst_name
        rv.debug_names = set(self.debug_names)
        rv.mcp_tuples = set(self.mcp_tuples)
        rv.auto_multi_cycle_tuples = dict(self.auto_multi_cycle_tuples)
        rv.next_func_call_auto_pipeline_latency = (
            self.next_func_call_auto_pipeline_latency
        )
        rv.sub_inst_to_auto_pipeline_latency = dict(
            self.sub_inst_to_auto_pipeline_latency
        )
        rv.sub_inst_to_auto_pipeline_key = dict(self.sub_inst_to_auto_pipeline_key)
        rv.sub_inst_to_auto_fsm_key = dict(self.sub_inst_to_auto_fsm_key)
        rv.ast_meta = self.ast_meta
        rv.pypeline_emission_names = self.pypeline_emission_names
        rv.submodule_latencies_are_self_timed = set(
            getattr(self, "submodule_latencies_are_self_timed", ())
        )
        rv.submodule_instance_to_source_origins = {
            k: set(v) for k, v in self.submodule_instance_to_source_origins.items()
        }
        rv.is_c_built_in = self.is_c_built_in
        rv.is_vhdl_func = self.is_vhdl_func
        rv.is_vhdl_expr = self.is_vhdl_expr
        rv.vhdl_module_text = self.vhdl_module_text
        rv.printf_format_string = self.printf_format_string
        rv.sim_assert_msg = self.sim_assert_msg
        rv.is_new_style_bit_manip = self.is_new_style_bit_manip
        rv.is_clock_crossing = self.is_clock_crossing
        rv.submodule_instance_to_ast_meta = self.DEEPCOPY_DICT_COPY(
            self.submodule_instance_to_ast_meta
        )  # dict(self.submodule_instance_to_ast_meta) # IMMUTABLE types / dont care
        rv.submodule_instance_to_printf_format_string = dict(
            self.submodule_instance_to_printf_format_string
        )  # IMMUTABLE (plain strings)
        rv.submodule_instance_to_sim_assert_msg = dict(
            self.submodule_instance_to_sim_assert_msg
        )  # IMMUTABLE (plain strings or None)
        rv.submodule_instance_to_input_port_names = self.DEEPCOPY_DICT_LIST(
            self.submodule_instance_to_input_port_names
        )
        rv.wire_drives = self.DEEPCOPY_DICT_SET(self.wire_drives)
        rv.wire_driven_by = dict(
            self.wire_driven_by
        )  # wire_name -> driving wire #IMMUTABLE
        rv.wire_aliases_over_time = self.DEEPCOPY_DICT_LIST(self.wire_aliases_over_time)
        rv.alias_to_orig_var_name = dict(self.alias_to_orig_var_name)  # IMMUTABLE
        rv.alias_to_driven_ref_toks = self.DEEPCOPY_DICT_LIST(
            self.alias_to_driven_ref_toks
        )  # alias -> [ref,toks]
        rv.wire_to_c_type = dict(self.wire_to_c_type)  # IMMUTABLE
        rv.delay = self.delay
        rv.delay_is_estimated = self.delay_is_estimated
        rv.delay_components = (
            dict(self.delay_components) if self.delay_components is not None else None
        )
        rv.planner_delay = self.planner_delay
        rv.measured_area = getattr(self, "measured_area", None)
        rv.c_code_text = self.c_code_text
        rv.containing_funcs = set(self.containing_funcs)
        rv.ref_submodule_instance_to_input_port_driven_ref_toks = (
            self.DEEPCOPY_DICT_LIST(
                self.ref_submodule_instance_to_input_port_driven_ref_toks
            )
        )
        rv.ref_submodule_instance_to_ref_toks = self.DEEPCOPY_DICT_LIST(
            self.ref_submodule_instance_to_ref_toks
        )
        rv.clock_enable_wires = self.clock_enable_wires[:]
        rv.is_fsm_clk_func = self.is_fsm_clk_func
        rv.state_groups = self.state_groups[:]
        rv.first_user_state = self.first_user_state
        rv.func_call_name_to_state = dict(self.func_call_name_to_state)
        rv.func_call_node_to_entry_exit_states = dict(
            self.func_call_node_to_entry_exit_states
        )

        return rv

    # Really, help! # Replace with deep copy?
    def DEEPCOPY_DICT_LIST(self, d):
        rv = {}
        for key in d:
            rv[key] = d[key][:]
        return rv

    def DEEPCOPY_DICT_SET(self, d):
        rv = {}
        for key in d:
            rv[key] = set(d[key])
        return rv

    def DEEPCOPY_DICT_COPY(self, d):
        rv = {}
        for key in d:
            rv[key] = copy.copy(d[key])
        return rv

    # Merges logic_b into self
    # Returns none intentionally
    def MERGE_COMB_LOGIC(self, logic_b):
        # Um...?
        if self == logic_b:
            return None

        # Func name must match if set
        if (self.func_name is not None) and (logic_b.func_name is not None):
            if self.func_name != logic_b.func_name:
                print("Cannot merge comb logic with mismatching func names!")
                print(self.func_name)
                print(logic_b.func_name)
            else:
                self.func_name = self.func_name
        # Otherwise use whichever is set
        elif self.func_name is not None:
            self.func_name = self.func_name
        else:
            self.func_name = logic_b.func_name

        # C built in status must match if set
        if (self.is_c_built_in is not None) and (logic_b.is_c_built_in is not None):
            if self.is_c_built_in != logic_b.is_c_built_in:
                print("Cannot merge comb logic with mismatching is_c_built_in !")
                print(self.func_name, self.is_c_built_in)
                print(logic_b.func_name, logic_b.is_c_built_in)
                sys.exit(-1)
            else:
                self.is_c_built_in = self.is_c_built_in
        # Otherwise use whichever is set
        elif self.is_c_built_in is not None:
            self.is_c_built_in = self.is_c_built_in
        else:
            self.is_c_built_in = logic_b.is_c_built_in

        # VHDL func status must match if set
        if (self.is_vhdl_func is not None) and (logic_b.is_vhdl_func is not None):
            if self.is_vhdl_func != logic_b.is_vhdl_func:
                print("Cannot merge comb logic with mismatching is_vhdl_func !")
                print(self.func_name, self.is_vhdl_func)
                print(logic_b.func_name, logic_b.is_vhdl_func)
                sys.exit(-1)
            else:
                self.is_vhdl_func = self.is_vhdl_func
        # Otherwise use whichever is set
        elif self.is_vhdl_func is not None:
            self.is_vhdl_func = self.is_vhdl_func
        else:
            self.is_vhdl_func = logic_b.is_vhdl_func

        # VHDL expression status must match if set
        if (self.is_vhdl_expr is not None) and (logic_b.is_vhdl_expr is not None):
            if self.is_vhdl_expr != logic_b.is_vhdl_expr:
                print("Cannot merge comb logic with mismatching is_vhdl_expr !")
                print(self.func_name, self.is_vhdl_expr)
                print(logic_b.func_name, logic_b.is_vhdl_expr)
                sys.exit(-1)
            else:
                self.is_vhdl_expr = self.is_vhdl_expr
        # Otherwise use whichever is set
        elif self.is_vhdl_expr is not None:
            self.is_vhdl_expr = self.is_vhdl_expr
        else:
            self.is_vhdl_expr = logic_b.is_vhdl_expr

        # VHDL module text keep whichever is set
        if (self.vhdl_module_text is not None) and (
            logic_b.vhdl_module_text is not None
        ):
            if self.vhdl_module_text != logic_b.vhdl_module_text:
                print("Cannot merge comb logic with mismatching vhdl_module_text !")
                print(self.func_name, self.vhdl_module_text)
                print(logic_b.func_name, logic_b.vhdl_module_text)
                sys.exit(-1)
            else:
                self.vhdl_module_text = self.vhdl_module_text
        # Otherwise use whichever is set
        elif self.vhdl_module_text is not None:
            self.vhdl_module_text = self.vhdl_module_text
        else:
            self.vhdl_module_text = logic_b.vhdl_module_text

        # Printf format string keep whichever is set (same pattern as vhdl_module_text)
        if (self.printf_format_string is not None) and (
            logic_b.printf_format_string is not None
        ):
            if self.printf_format_string != logic_b.printf_format_string:
                print("Cannot merge comb logic with mismatching printf_format_string !")
                print(self.func_name, self.printf_format_string)
                print(logic_b.func_name, logic_b.printf_format_string)
                sys.exit(-1)
            else:
                self.printf_format_string = self.printf_format_string
        elif self.printf_format_string is not None:
            self.printf_format_string = self.printf_format_string
        else:
            self.printf_format_string = logic_b.printf_format_string

        # sim_assert message string keep whichever is set (same pattern as printf_format_string)
        if (self.sim_assert_msg is not None) and (logic_b.sim_assert_msg is not None):
            if self.sim_assert_msg != logic_b.sim_assert_msg:
                print("Cannot merge comb logic with mismatching sim_assert_msg !")
                print(self.func_name, self.sim_assert_msg)
                print(logic_b.func_name, logic_b.sim_assert_msg)
                sys.exit(-1)
            else:
                self.sim_assert_msg = self.sim_assert_msg
        elif self.sim_assert_msg is not None:
            self.sim_assert_msg = self.sim_assert_msg
        else:
            self.sim_assert_msg = logic_b.sim_assert_msg

        # TODO refactor all the above copypasta

        # Dont do the same dumb above code - probably dont need it?
        # Absorb true values of using globals
        self.uses_nonvolatile_state_regs = (
            self.uses_nonvolatile_state_regs or logic_b.uses_nonvolatile_state_regs
        )
        self.is_clock_crossing = self.is_clock_crossing or logic_b.is_clock_crossing
        self.is_new_style_bit_manip = (
            self.is_new_style_bit_manip or logic_b.is_new_style_bit_manip
        )

        # Merge sets
        self.wires = self.wires | logic_b.wires
        self.state_regs = UNIQUE_KEY_DICT_MERGE(self.state_regs, logic_b.state_regs)
        self.variable_names = self.variable_names | logic_b.variable_names
        self.feedback_vars = dict.fromkeys(
            [*self.feedback_vars, *logic_b.feedback_vars]
        )
        self.debug_names = self.debug_names | logic_b.debug_names

        self.write_only_global_wires = UNIQUE_KEY_DICT_MERGE(
            self.write_only_global_wires, logic_b.write_only_global_wires
        )
        # Hacky hack gah, A.M. 180 - Song by Grandaddy
        # Auto remove read only regs promoted to local state regs
        self.read_only_global_wires = UNIQUE_KEY_DICT_MERGE(
            self.read_only_global_wires, logic_b.read_only_global_wires
        )
        read_only_reg_names = list(self.read_only_global_wires.keys())
        for read_only_reg_name in read_only_reg_names:
            if read_only_reg_name in self.state_regs:
                self.read_only_global_wires.pop(read_only_reg_name)

        # I/O order matters - check that
        # If one is empty then thats fine
        if len(self.inputs) > 0 and len(logic_b.inputs) > 0:
            # Check for equal
            if self.inputs != logic_b.inputs:
                print("Cannot merge comb logic with mismatching inputs !")
                print(self.func_name, self.inputs)
                print(logic_b.func_name, logic_b.inputs)
                print(0 / 0)
                sys.exit(-1)
            else:
                self.inputs = self.inputs[:]
        else:
            # Default a
            self.inputs = self.inputs[:]
            if len(self.inputs) <= 0:
                self.inputs = logic_b.inputs[:]

        if len(self.outputs) > 0 and len(logic_b.outputs) > 0:
            # Check for equal
            if self.outputs != logic_b.outputs:
                print("Cannot merge comb logic with mismatching outputs !")
                print(self.func_name, self.outputs)
                print(logic_b.func_name, logic_b.outputs)
                sys.exit(-1)
            else:
                self.outputs = self.outputs[:]
        else:
            # Default a
            self.outputs = self.outputs[:]
            if len(self.outputs) <= 0:
                self.outputs = logic_b.outputs[:]

        # Merge dicts
        self.wire_to_c_type = UNIQUE_KEY_DICT_MERGE(
            self.wire_to_c_type, logic_b.wire_to_c_type
        )
        self.submodule_instances = UNIQUE_KEY_DICT_MERGE(
            self.submodule_instances, logic_b.submodule_instances
        )
        self.wire_driven_by = UNIQUE_KEY_DICT_MERGE(
            self.wire_driven_by, logic_b.wire_driven_by
        )

        # Delay
        if self.delay is not None and logic_b.delay is not None:
            if self.delay != logic_b.delay:
                raise Exception("Mismatch delay!")
        elif self.delay is None:
            self.delay = logic_b.delay

        # Optional planner-only timing diagnostics follow the same merge
        # contract as measured delay. In ordinary frontend merges both sides
        # are None; this also makes post-measurement copies deterministic.
        if (
            self.delay_components is not None
            and logic_b.delay_components is not None
            and self.delay_components != logic_b.delay_components
        ):
            raise Exception("Mismatch delay components!")
        if self.delay_components is None:
            self.delay_components = (
                dict(logic_b.delay_components)
                if logic_b.delay_components is not None
                else None
            )
        if (
            self.planner_delay is not None
            and logic_b.planner_delay is not None
            and self.planner_delay != logic_b.planner_delay
        ):
            raise Exception("Mismatch planner delay!")
        if self.planner_delay is None:
            self.planner_delay = logic_b.planner_delay
        measured_area = getattr(self, "measured_area", None)
        measured_area_b = getattr(logic_b, "measured_area", None)
        if (
            measured_area is not None
            and measured_area_b is not None
            and measured_area != measured_area_b
        ):
            raise Exception("Mismatch measured area!")
        self.measured_area = (
            measured_area if measured_area is not None else measured_area_b
        )

        # NExt user inst name?
        if self.next_user_inst_name != logic_b.next_user_inst_name:
            if self.next_user_inst_name is None:
                self.next_user_inst_name = logic_b.next_user_inst_name
            else:
                raise Exception(
                    f"How to merge next inst names {self.next_user_inst_name} {logic_b.next_user_inst_name}?"
                )

        # WTF MERGE BUG?
        lens = len(self.wire_drives) + len(logic_b.wire_drives)
        self.wire_drives = DICT_SET_VALUE_MERGE(self.wire_drives, logic_b.wire_drives)
        if lens > 0 and len(self.wire_drives) == 0:
            print("self.wire_drives", self.wire_drives)
            print("logic_b.wire_drives", logic_b.wire_drives)
            print("Should have at least", lens, "entries...")
            print("MERGE COMB self.wire_drives", self.wire_drives)
            print("WTF")
            sys.exit(-1)

        # C ast node values wont be == , manual check with coord str
        self.submodule_instance_to_ast_meta = AST_META_VAL_UNIQUE_KEY_DICT_MERGE(
            self.submodule_instance_to_ast_meta,
            logic_b.submodule_instance_to_ast_meta,
        )
        self.submodule_instance_to_source_origins = DICT_SET_VALUE_MERGE(
            self.submodule_instance_to_source_origins,
            logic_b.submodule_instance_to_source_origins,
        )
        # Plain strings, unlike ast_meta -- ordinary equality-based merge is fine
        self.submodule_instance_to_printf_format_string = UNIQUE_KEY_DICT_MERGE(
            self.submodule_instance_to_printf_format_string,
            logic_b.submodule_instance_to_printf_format_string,
        )
        self.submodule_instance_to_sim_assert_msg = UNIQUE_KEY_DICT_MERGE(
            self.submodule_instance_to_sim_assert_msg,
            logic_b.submodule_instance_to_sim_assert_msg,
        )
        self.submodule_instance_to_input_port_names = LIST_VAL_UNIQUE_KEY_DICT_MERGE(
            self.submodule_instance_to_input_port_names,
            logic_b.submodule_instance_to_input_port_names,
        )
        self.ref_submodule_instance_to_input_port_driven_ref_toks = (
            LIST_VAL_UNIQUE_KEY_DICT_MERGE(
                self.ref_submodule_instance_to_input_port_driven_ref_toks,
                logic_b.ref_submodule_instance_to_input_port_driven_ref_toks,
            )
        )
        self.ref_submodule_instance_to_ref_toks = LIST_VAL_UNIQUE_KEY_DICT_MERGE(
            self.ref_submodule_instance_to_ref_toks,
            logic_b.ref_submodule_instance_to_ref_toks,
        )

        # Also for both wire drives and driven by, remove wire driving self:
        # wire_driven_by
        new_wire_driven_by = {}
        for driven_wire in self.wire_driven_by:
            # Filter out self driving
            driving_wire = self.wire_driven_by[driven_wire]
            if driving_wire != driven_wire:
                new_wire_driven_by[driven_wire] = driving_wire

        # print "new_wire_driven_by",new_wire_driven_by
        self.wire_driven_by = new_wire_driven_by

        # wire_drives
        new_wire_drives = {}
        for driving_wire in self.wire_drives:
            driven_wires = self.wire_drives[driving_wire]
            new_driven_wires = set()
            for driven_wire in driven_wires:
                if driven_wire != driving_wire:
                    new_driven_wires.add(driven_wire)
            new_wire_drives[driving_wire] = new_driven_wires
        self.wire_drives = new_wire_drives

        # If one node is null then use ot
        if (self.c_ast_node is not None) and (logic_b.c_ast_node is not None):
            if not self.c_ast_node == logic_b.c_ast_node:
                # EW WTF SLOW? if C_AST_NODE_COORD_STR(self.c_ast_node) != C_AST_NODE_COORD_STR(logic_b.c_ast_node):
                print("Cannot merge comb logic with mismatching c_ast_node!")
                print(self.func_name)
                print(logic_b.func_name)
                print(self.c_ast_node)
                print(logic_b.c_ast_node)
                print(0 / 0)
                sys.exit(-1)
            else:
                pass  # self.ast_meta already correct
        # Otherwise use whichever is set
        elif self.ast_meta is not None:
            pass  # self.ast_meta already correct
        else:
            self.ast_meta = logic_b.ast_meta

        # Only way this makes sense with MERGE_SEQUENTIAL_LOGIC
        # Need to be equal per variable
        # List val merge should do the trick
        self.wire_aliases_over_time = LIST_VAL_UNIQUE_KEY_DICT_MERGE(
            self.wire_aliases_over_time, logic_b.wire_aliases_over_time
        )

        # Only one orig wire name per alias
        self.alias_to_orig_var_name = UNIQUE_KEY_DICT_MERGE(
            self.alias_to_orig_var_name, logic_b.alias_to_orig_var_name
        )
        self.alias_to_driven_ref_toks = UNIQUE_KEY_DICT_MERGE(
            self.alias_to_driven_ref_toks, logic_b.alias_to_driven_ref_toks
        )

        # Code text keep whichever is set
        if (self.c_code_text is not None) and (logic_b.c_code_text is not None):
            if self.c_code_text != logic_b.c_code_text:
                print("Cannot merge comb logic with mismatching c_code_text!")
                print(self.c_code_text)
                print(logic_b.c_code_text)
            else:
                self.c_code_text = self.c_code_text
        # Otherwise use whichever is set
        elif self.c_code_text is not None:
            self.c_code_text = self.c_code_text
        else:
            self.c_code_text = logic_b.c_code_text

        # Clock enables need to be equal
        if self.clock_enable_wires != logic_b.clock_enable_wires:
            print("Mismatch clock enable wires merging parallel logic!")
            print(self.clock_enable_wires)
            print(logic_b.clock_enable_wires)
            sys.exit(-1)

        # Might never need this?
        self.is_fsm_clk_func |= logic_b.is_fsm_clk_func
        if self.state_groups != logic_b.state_groups:
            print("Cant merge state groups:")
            sys.exit(-1)
        if self.first_user_state != logic_b.first_user_state:
            print("Cant merge first user state")
            sys.exit(-1)
        if self.func_call_name_to_state != logic_b.func_call_name_to_state:
            print("Cant merge func_call_name_to_state")
            sys.exit(-1)
        if (
            self.func_call_node_to_entry_exit_states
            != logic_b.func_call_node_to_entry_exit_states
        ):
            print("Cant merge func_call_node_to_entry_exit_states")
            sys.exit(-1)

        return None

    # Function to merge logic with implied execution order
    # Merges with self
    # Intentionally returns None
    def MERGE_SEQ_LOGIC(self, second_logic):
        # only need to do specifically sequential part of merge here
        # We call COMB merge after adjusting for sequential
        # Um...?
        if self == second_logic:
            return None

        # print "===="
        # print "self.wire_drives", self.wire_drives
        # print "self.wire_driven_by", self.wire_driven_by
        # print "second_logic.wire_drives", second_logic.wire_drives
        # print "second_logic.wire_driven_by", second_logic.wire_driven_by

        # Driving wires need to reflect over time
        # Last alias from first logic replaces original wire name in second logic
        # self.wire_drives = {} # wire_name -> set(driven,wire,names])
        for orig_var in self.wire_aliases_over_time:
            # And the var drives second_logic
            if orig_var in second_logic.wire_drives:
                # First logic has aliases for orig var
                # Second logic has record of the orig var driving things
                # Both first and second logic should have same driven wies
                first_driven_wires = set()
                if orig_var in self.wire_drives:
                    first_driven_wires = self.wire_drives[orig_var]
                second_driven_wires = set()
                if orig_var in second_logic.wire_drives:
                    second_driven_wires = second_logic.wire_drives[orig_var]

                sorted_first_driven_wires = sorted(first_driven_wires)
                sorted_second_driven_wires = sorted(second_driven_wires)
                # Was the second logic actually refering to something different?
                if sorted_first_driven_wires != sorted_second_driven_wires:
                    # If second just has extra then OK
                    if len(sorted_first_driven_wires) < len(sorted_second_driven_wires):
                        # Check for match, but not like a dummy?
                        # for i in range(0, len(sorted_first_driven_wires)):
                        # if sorted_first_driven_wires[i] != sorted_second_driven_wires[i]:
                        for sorted_first_driven_wire in sorted_first_driven_wires:
                            if (
                                sorted_first_driven_wire
                                not in sorted_second_driven_wires
                            ):
                                print(
                                    "first driven wire:",
                                    sorted_first_driven_wire,
                                    "was not in second logic driven wires? was removed? wtf?",
                                )
                                print("first:", sorted_first_driven_wires)
                                print("second:", sorted_second_driven_wires)
                                # print 0/0
                                sys.exit(-1)
                        # Got match, first is subset of second, update first to match second
                        if len(second_driven_wires) > 0:
                            self.wire_drives[orig_var] = second_driven_wires
                        for second_driven_wire in second_driven_wires:
                            self.wire_driven_by[second_driven_wire] = (
                                second_logic.wire_driven_by[second_driven_wire]
                            )

                    else:
                        # First has same or more, cant match second at this point
                        print("orig_var", orig_var)
                        aliases = self.wire_aliases_over_time[orig_var]
                        print("first aliases", aliases)
                        last_alias = aliases[len(aliases) - 1]
                        print("first logic last_alias", last_alias)
                        print("self.wire_drives[orig_var]", first_driven_wires)
                        print("second_logic.wire_drives[orig_var]", second_driven_wires)
                        # Get the last alias for that var from first logic
                        print(
                            "second aliases",
                            second_logic.wire_aliases_over_time[orig_var],
                        )

                        # If this last alias is not in the first logic

                        # If aliases over time already agree then no need

                        # And replace that wire in the
                        # second logic wire_drives key (not value)
                        temp_value = set(second_logic.wire_drives[orig_var])
                        # Delete orig var key
                        second_logic.wire_drives.pop(orig_var, None)
                        # Replace with last alias
                        second_logic.wire_drives[last_alias] = temp_value
                        print(last_alias, " DRIVES ", temp_value)
                        sys.exit(-1)

        # wire_driven_by can't have multiple drivers over time and
        # should error out in normal merge below

        # wire_aliases_over_time
        # Do first+second first
        # If first logic has aliases over time
        for var_name in self.wire_aliases_over_time:
            if var_name in second_logic.wire_aliases_over_time:
                # And so does second
                # Merged value is first plus second
                first = self.wire_aliases_over_time[var_name]
                second = second_logic.wire_aliases_over_time[var_name]
                # Start with including first
                self.wire_aliases_over_time[var_name] = first[:]

                # Check that the aliases over time are equal
                # in the period of time they share (the first logic)
                for i in range(0, len(first)):
                    if first[i] != second[i]:
                        print(
                            "At time index",
                            i,
                            "for orig variable name =",
                            var_name,
                            "the first and second logic do not agree:",
                        )
                        print("First logic aliases over time:", first)
                        print("Second logic aliases over time:", second)
                        print(0 / 0)
                        sys.exit(-1)

                # Equal in shared time so only append not shared part of second
                for i in range(len(first), len(second)):
                    self.wire_aliases_over_time[var_name].append(second[i])
                # print "self.wire_aliases_over_time",self.wire_aliases_over_time

            else:
                # First only alias (second does not have alias)
                # Merged value is first only
                self.wire_aliases_over_time[var_name] = self.wire_aliases_over_time[
                    var_name
                ][:]
        # Then include wire_aliases_over_time ONLY from second logic
        for var_name in second_logic.wire_aliases_over_time:
            # And first logic does not
            if var_name not in self.wire_aliases_over_time:
                # Merged value is just from second logic
                second = second_logic.wire_aliases_over_time[var_name]
                self.wire_aliases_over_time[var_name] = second[:]

        # To not error in normal MERGE_LOGIC below, first and second logic must have same
        # resulting wire_aliases_over_time
        modified_second_logic = second_logic
        modified_second_logic.wire_aliases_over_time = self.wire_aliases_over_time
        # Then merge logic as normal
        self.MERGE_COMB_LOGIC(modified_second_logic)

        return None

    # Allow a wire not to be driven
    def WIRE_ALLOW_NO_DRIVEN_BY(self, wire, FuncLogicLookupTable):
        if WIRE_IS_CONSTANT(wire):
            return True
        if wire in self.variable_names:
            return True
        if wire in self.inputs:
            return True
        if wire == CLOCK_ENABLE_NAME:
            return True
        if wire in self.state_regs and self.state_regs[wire].is_volatile:
            return True
        # Only output ports are allowed to not to be driven by something
        if SUBMODULE_MARKER in wire:
            toks = wire.split(SUBMODULE_MARKER)
            submodule_inst = toks[0]
            # Uh if inst doesnt exist then problem....
            if submodule_inst not in self.submodule_instances:
                print("self.func_name", self.func_name)
                print("wire", wire)
                print("No submodule instance called", submodule_inst)
                print(self.submodule_instances)
                print(0 / 0)
                sys.exit(-1)
            # Otherwise proceed checking for outputs
            submodule_func_name = self.submodule_instances[submodule_inst]
            if submodule_func_name not in FuncLogicLookupTable:
                print("self.func_name", self.func_name)
                print("wire", wire)
                print("No func def for sub", submodule_func_name)
                print(FuncLogicLookupTable)
                sys.exit(-1)
            submodule_logic = FuncLogicLookupTable[submodule_func_name]
            port_name = toks[1]
            if port_name in submodule_logic.outputs:
                return True

        return False

    # Allow a wire not to drive anything
    def WIRE_ALLOW_NO_DRIVES(self, wire, FuncLogicLookupTable):
        if wire in self.variable_names:
            return True
        if wire in self.inputs:
            return True
        if wire == CLOCK_ENABLE_NAME:
            return True
        if wire in self.outputs:
            return True
        if wire in self.state_regs:
            return True
        if wire in self.write_only_global_wires:
            return True
        # Only clock enable and input ports are allowed to not drive anything
        if SUBMODULE_MARKER in wire:
            toks = wire.split(SUBMODULE_MARKER)
            submodule_inst = toks[0]
            # Uh if inst doesnt exist then problem....
            if submodule_inst not in self.submodule_instances:
                print("self.func_name", self.func_name)
                print("wire", wire)
                print("No submodule instance called", submodule_inst)
                print(self.submodule_instances)
                print(0 / 0)
                sys.exit(-1)
            # Otherwise proceed checking for inputs
            submodule_func_name = self.submodule_instances[submodule_inst]
            # Printf/sim_assert/sim_finish allow output(and outputs) not to not to drive anything
            if IS_SIM_CTRL_FUNC_NAME(submodule_func_name):
                return True
            if submodule_func_name not in FuncLogicLookupTable:
                print("self.func_name", self.func_name)
                print("wire", wire)
                print("No func def for sub", submodule_func_name)
                print(FuncLogicLookupTable)
                sys.exit(-1)
            submodule_logic = FuncLogicLookupTable[submodule_func_name]
            port_name = toks[1]
            if port_name == CLOCK_ENABLE_NAME:
                return True
            if port_name in submodule_logic.inputs:
                return True

        return False

    def WIRE_DO_NOT_COLLAPSE(self, wire, parser_state):

        if wire in self.variable_names:
            return True
        if wire in self.inputs:
            return True
        if wire == CLOCK_ENABLE_NAME:
            return True
        if wire in self.outputs:
            return True
        if wire in self.state_regs:
            return True
        if wire in self.write_only_global_wires:
            return True
        if wire in self.feedback_vars:
            return True

        # WANT TO TRIM SUBMODULES!
        # if SUBMODULE_MARKER in wire:
        #  return True
        # Most submodules are entirely in the same function/clock domain
        # So it is correct (for now until multi global readers?) to rip up submodule
        # if reached an output wire
        # CLOCK CROSSING functions are not this way and have 'used' outputs not see
        # since the outputs are in another domain
        if SUBMODULE_MARKER in wire:
            inst_name = wire.split(SUBMODULE_MARKER)[0]
            func_name = self.submodule_instances[inst_name]
            sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
            # If self or any submodules uses clock crossings
            if sub_func_logic.is_clock_crossing:
                return True
            # if LOGIC_NEEDS_GLOBAL_TO_MODULE(sub_func_logic, parser_state)
            #  return True
            # Only need to check if has outputs
            # inputs to something with no outputs still rips up
            if LOGIC_NEEDS_MODULE_TO_GLOBAL(sub_func_logic, parser_state):
                return True

        return False

    def REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(self, wire, parser_state):
        debug = False

        # Stop recursion if reached special wire
        if self.WIRE_DO_NOT_COLLAPSE(wire, parser_state):
            if debug:
                print("NOT REMOVE WIRE", self.func_name, "  ", wire, flush=True)
            return
        if debug:
            print("REMOVE WIRE", self.func_name, "  ", wire, flush=True)

        self.wires.discard(wire)
        self.wire_to_c_type.pop(wire, None)

        # Remove record of driving-wire driving wire
        #   This might also remove the driving-wire
        if wire in self.wire_driven_by:
            driving_wire = self.wire_driven_by[wire]
            all_driven_wires = []
            if driving_wire in self.wire_drives:
                all_driven_wires = self.wire_drives[driving_wire]
                all_driven_wires.discard(wire)
            if len(all_driven_wires) > 0:
                self.wire_drives[driving_wire] = all_driven_wires
            else:
                # Driving wire no longer drives anything, recurse to delete it too
                self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(driving_wire, parser_state)
                # self.wire_drives.pop(driving_wire)

            # Remove record of wire being driven by driving-wire
            self.wire_driven_by.pop(wire, None)

        # Remove record of wire driving driven-wires
        if wire in self.wire_drives:
            driven_wires = self.wire_drives[wire]
            self.wire_drives.pop(wire, None)
            # And remove all the driven wires too
            for driven_wire in driven_wires:
                self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(driven_wire, parser_state)

        # Is this wire a submodule port?
        if SUBMODULE_MARKER in wire:
            toks = wire.split(SUBMODULE_MARKER)
            if len(toks) > 2:
                print("What berries? Goji Berries - Rubik")
                sys.exit(-1)
            submodule_inst = toks[0]
            submodule_func_name = self.submodule_instances[submodule_inst]
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]

            # Skip ripping up vhdl text submodules modules
            if submodule_func_name == VHDL_FUNC_NAME:
                return
            # Also skip ripping up printfs/sim_asserts/sim_finishes
            if IS_SIM_CTRL_FUNC_NAME(submodule_func_name):
                return

            # Do the output ports drive anything now?
            # (know this output port wire doesnt)
            all_outputs_disconnected = True
            if len(submodule_logic.outputs) == 0:
                all_outputs_disconnected = False
            for output_port in submodule_logic.outputs:
                submodule_output_wire = submodule_inst + SUBMODULE_MARKER + output_port
                if submodule_output_wire in self.wire_drives:
                    # Still drives something
                    all_outputs_disconnected = False

            # Rip up the submodule
            if all_outputs_disconnected:
                # Rip up wires starting at its inputs
                for in_port in submodule_logic.inputs:
                    submodule_input_wire = submodule_inst + SUBMODULE_MARKER + in_port
                    if submodule_input_wire in self.wires:
                        self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(
                            submodule_input_wire, parser_state
                        )
                # Finally remove submodule itself
                self.REMOVE_SUBMODULE(
                    submodule_inst,
                    submodule_logic.inputs,
                    submodule_logic.outputs,
                    parser_state,
                )

    # Intentionally return None
    def REMOVE_SUBMODULE(
        self,
        submodule_inst,
        input_port_names,
        output_port_names,
        parser_state,
        remove_global=True,
    ):
        debug = False
        if debug:
            print("removing sub inst", self.func_name, submodule_inst, flush=True)

        # Remove from list of subs yo
        self.submodule_instances.pop(submodule_inst, None)
        self.submodule_instance_to_source_origins.pop(submodule_inst, None)

        # Make list of wires that look like
        #   submodule_inst + SUBMODULE_MARKER
        # SHOULD ONLY BE INPUT AND OUTPUT WIRES + submodule name
        # AND CLOCK EN TOO!
        io_wires = set()
        in_wires = set()
        out_wires = set()
        ce_wire = submodule_inst + SUBMODULE_MARKER + CLOCK_ENABLE_NAME
        io_wires.add(ce_wire)
        for input_port_name in input_port_names:
            in_wire = submodule_inst + SUBMODULE_MARKER + input_port_name
            io_wires.add(in_wire)
            in_wires.add(in_wire)
        for output_port_name in output_port_names:
            out_wire = submodule_inst + SUBMODULE_MARKER + output_port_name
            io_wires.add(out_wire)
            out_wires.add(out_wire)

        # Fast
        self.submodule_instance_to_ast_meta.pop(
            submodule_inst, None
        )  # NOT DONE UNTIL AFTER TRY GET LOGIC  needed?
        self.submodule_instance_to_input_port_names.pop(
            submodule_inst, None
        )  # NOT DONE UNTIL AFTER TRY GET LOGIC  needed?
        self.ref_submodule_instance_to_input_port_driven_ref_toks.pop(
            submodule_inst, None
        )
        self.ref_submodule_instance_to_ref_toks.pop(submodule_inst, None)

        # Discard a few, or intersect for many?
        if len(io_wires) < len(self.wires):
            for io_wire in io_wires:
                self.wires.discard(io_wire)
        else:
            self.wires = self.wires - io_wires

        for io_wire in io_wires:
            self.wire_to_c_type.pop(io_wire, None)

        # Super sloo?

        # WIRE_DRIVES
        # Only output port can drive something
        # NOT DONE UNTIL AFTER TRY GET LOGIC needed?
        for out_wire in out_wires:
            # Output wire drives stuff
            driven_wires = []
            if out_wire in self.wire_drives:
                driven_wires = self.wire_drives[out_wire]
            # Remove opposite direction here
            for driven_wire in driven_wires:
                self.wire_driven_by.pop(driven_wire)
            # Then remove original direction
            self.wire_drives.pop(out_wire, None)

        # WIRE DRIVEN BY
        # Only inputs (and CE wire)
        for in_wire in list(in_wires) + [ce_wire]:
            # IO wire is driven by thing
            if in_wire in self.wire_driven_by:
                driving_wire = self.wire_driven_by[in_wire]
                # Remove io wire from opposite direction
                all_driven_wires = self.wire_drives[driving_wire]
                all_driven_wires.discard(in_wire)
                if len(all_driven_wires) > 0:
                    self.wire_drives[driving_wire] = all_driven_wires
                else:
                    self.wire_drives.pop(driving_wire, None)
                # Then remove original direction
                self.wire_driven_by.pop(in_wire, None)

        # Shouldnt need to remove wire aliases since submodule connnections dont make assignment aliases?

        # Global instance removal:
        if remove_global:
            all_insts_of_this_logic = []
            if self.func_name in parser_state.FuncToInstances:
                all_insts_of_this_logic = parser_state.FuncToInstances[self.func_name]
                for global_inst in all_insts_of_this_logic:
                    global_sub_inst_name = (
                        global_inst + SUBMODULE_MARKER + submodule_inst
                    )
                    # Why ya gotta be so mad? Its only game?
                    # Dont do dumb loop collecting submodules with startswith
                    # Do recursive remove instead
                    parser_state = RECURSIVE_REMOVE_GLOBAL_INST(
                        global_sub_inst_name, parser_state
                    )

        return None

    def REMOVE_VAR_WIRE_DRIVE_HISTORY(self, var_name):
        self.wire_drives.pop(var_name, None)
        self.wire_driven_by.pop(var_name, None)
        # Then do all alias stuff
        if var_name in self.wire_aliases_over_time:
            all_aliases = self.wire_aliases_over_time[var_name]
            for alias in all_aliases:
                self.wires.discard(alias)
                self.wire_to_c_type.pop(alias, None)
                self.alias_to_orig_var_name.pop(alias, None)
                self.alias_to_driven_ref_toks.pop(alias, None)

                # Pop driven by, do corresponding wire drives
                driving_wire = self.wire_driven_by.pop(alias, None)
                if driving_wire is not None:
                    wires_driven_by_driving_wire = self.wire_drives[driving_wire]
                    wires_driven_by_driving_wire.remove(alias)
                    if len(wires_driven_by_driving_wire) == 0:
                        self.wire_drives.pop(driving_wire)

                # Pop wire_drives, do coresponding wire driven by
                driven_wires = self.wire_drives.pop(alias, None)
                if driven_wires is not None:
                    for driven_wire in driven_wires:
                        self.wire_driven_by.pop(driven_wire, None)

            self.wire_aliases_over_time[var_name] = []

    def COPY_SUBMODULE_INFO(self, new_inst, old_inst):
        if old_inst in self.submodule_instance_to_source_origins:
            self.submodule_instance_to_source_origins[new_inst] = set(
                self.submodule_instance_to_source_origins[old_inst]
            )
        if old_inst in self.submodule_instances:
            self.submodule_instances[new_inst] = self.submodule_instances[old_inst]
        if old_inst in self.submodule_instance_to_ast_meta:
            self.submodule_instance_to_ast_meta[new_inst] = (
                self.submodule_instance_to_ast_meta[old_inst]
            )
        if old_inst in self.submodule_instance_to_input_port_names:
            self.submodule_instance_to_input_port_names[new_inst] = (
                self.submodule_instance_to_input_port_names[old_inst]
            )
        if old_inst in self.ref_submodule_instance_to_input_port_driven_ref_toks:
            self.ref_submodule_instance_to_input_port_driven_ref_toks[new_inst] = (
                self.ref_submodule_instance_to_input_port_driven_ref_toks[old_inst]
            )
        if old_inst in self.ref_submodule_instance_to_ref_toks:
            self.ref_submodule_instance_to_ref_toks[new_inst] = (
                self.ref_submodule_instance_to_ref_toks[old_inst]
            )
        # A collapsed duplicate keeps its calls' AUTO_PIPELINE / AUTO_FSM tag
        # (duplicates are only ever collapsed within one tag group)
        for tags in (
            self.sub_inst_to_auto_pipeline_latency,
            self.sub_inst_to_auto_pipeline_key,
            self.sub_inst_to_auto_fsm_key,
        ):
            if old_inst in tags:
                tags[new_inst] = tags[old_inst]

    def CAN_HAVE_ADDED_LATENCY(self, parser_state):
        if self.func_name in parser_state.func_fixed_latency:
            return False
        if self.vhdl_module_text is not None:
            return False
        if self.is_vhdl_func:
            return False
        if self.is_vhdl_expr:
            return False
        if self.is_clock_crossing:
            return False
        if self.uses_nonvolatile_state_regs:
            return False
        # Is actually OK since global wires arent registered like func/pipelined IO regs
        # if self.uses_nonvolatile_state_regs and len(self.write_only_global_wires) > 0:
        #    return False
        # if self.uses_nonvolatile_state_regs and len(self.read_only_global_wires) > 0:
        #    return False
        if IS_MEM(self):
            # TODO support IO regs on built in RAM prim funcs
            return False
        # Yes actually want user prim funcs to pipeline, is their purpose
        #   if FUNC_IS_PRIMITIVE(self.func_name, parser_state):
        #       return False
        if self.func_name in parser_state.func_marked_blackbox:
            return False
        if self.uses_nonvolatile_state_regs:
            return False
        if len(self.feedback_vars) > 0:
            return False
        return True

    def SUB_HAS_AUTO_PIPELINE_IN_HIER(self, sub_inst, parser_state):
        if sub_inst in self.sub_inst_to_auto_pipeline_latency:
            return True
        sub_func_name = self.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
        if len(sub_logic.sub_inst_to_auto_pipeline_latency) > 0:
            return True
        for sub_sub_inst in sub_logic.submodule_instances:
            if sub_logic.SUB_HAS_AUTO_PIPELINE_IN_HIER(sub_sub_inst, parser_state):
                return True
        return False

    def HAS_AUTO_PIPELINE_IN_HIER(self, parser_state):
        for sub_inst in self.submodule_instances:
            if self.SUB_HAS_AUTO_PIPELINE_IN_HIER(sub_inst, parser_state):
                return True
        return False

    def CAN_USE_AUTOPIPELINING(self, parser_state):
        return self.CAN_HAVE_ADDED_LATENCY(
            parser_state
        ) or self.HAS_AUTO_PIPELINE_IN_HIER(parser_state)


def RECURSIVE_RENAME_GLOBAL_INST(inst_to_rename, renamed_inst_name, parser_state):
    # Do for all submodules first
    func_logic = parser_state.LogicInstLookupTable[inst_to_rename]
    for local_sub_inst in func_logic.submodule_instances:
        global_sub_inst = inst_to_rename + SUBMODULE_MARKER + local_sub_inst
        renamed_global_sub_inst = renamed_inst_name + SUBMODULE_MARKER + local_sub_inst
        parser_state = RECURSIVE_RENAME_GLOBAL_INST(
            global_sub_inst, renamed_global_sub_inst, parser_state
        )

    # Then rename current inst
    inst_func_name = func_logic.func_name
    ## Prevent renames from doing weird double copy paste
    # if inst_to_rename == global_dup_sub_inst_name:
    #  renamed_inst_name = global_new_sub_inst_name
    # else:
    #  renamed_inst_name = inst_to_rename.replace(global_dup_sub_inst_name+SUBMODULE_MARKER, global_new_sub_inst_name+SUBMODULE_MARKER)
    parser_state.FuncToInstances[inst_func_name].remove(inst_to_rename)
    parser_state.FuncToInstances[inst_func_name].add(renamed_inst_name)
    parser_state.LogicInstLookupTable[renamed_inst_name] = (
        parser_state.LogicInstLookupTable[inst_to_rename]
    )
    parser_state.LogicInstLookupTable.pop(inst_to_rename)

    return parser_state


def RECURSIVE_REMOVE_GLOBAL_INST(inst_to_remove, parser_state):
    # WTF sometimes func isnt in here already? Modest Mouse - Medication
    if inst_to_remove not in parser_state.LogicInstLookupTable:
        return parser_state
    func_logic = parser_state.LogicInstLookupTable[inst_to_remove]

    # Do for all submodules first
    for local_sub_inst in func_logic.submodule_instances:
        global_sub_inst = inst_to_remove + SUBMODULE_MARKER + local_sub_inst
        parser_state = RECURSIVE_REMOVE_GLOBAL_INST(global_sub_inst, parser_state)

    # Then remove current inst
    inst_func_logic_name = func_logic.func_name
    parser_state.LogicInstLookupTable.pop(inst_to_remove)
    all_insts_of_sub = parser_state.FuncToInstances[inst_func_logic_name]
    if inst_to_remove in all_insts_of_sub:
        all_insts_of_sub.remove(inst_to_remove)  # Not all inst shows up?
    if len(all_insts_of_sub) > 0:
        parser_state.FuncToInstances[inst_func_logic_name] = all_insts_of_sub
    else:
        parser_state.FuncToInstances.pop(inst_func_logic_name)

    return parser_state


def WIRE_IS_CONSTANT(wire):
    new_wire = wire

    # Also split on last submodule marker
    toks = new_wire.split(SUBMODULE_MARKER)
    last_tok = toks[len(toks) - 1]

    # Hey - this is dumb
    rv = (
        last_tok.startswith(CONST_PREFIX)
        and not last_tok.startswith(CONST_REF_RD_FUNC_NAME_PREFIX + "_")
        and not last_tok.startswith(CONST_PREFIX + BIN_OP_SL_NAME + "_")
        and not last_tok.startswith(CONST_PREFIX + BIN_OP_SR_NAME + "_")
    )
    if (
        (CONST_PREFIX in wire)
        and not (rv)
        and CONST_REF_RD_FUNC_NAME_PREFIX + "_" not in wire
        and CONST_PREFIX + BIN_OP_SL_NAME + "_" not in wire
        and CONST_PREFIX + BIN_OP_SR_NAME + "_" not in wire
    ):
        print("WHJAT!?")
        print("wire", wire)
        print("new_wire", new_wire)
        print("WIRE_IS_CONSTANT   but is not?")
        raise Exception("This shouldn't happen")

    return rv


def WIRE_IS_SUBMODULE_PORT(wire, logic):
    # Remove last tok, should be port name
    toks = wire.split(SUBMODULE_MARKER)
    possible_submodule_inst_name = SUBMODULE_MARKER.join(toks[0 : len(toks) - 1])

    # Check port name too?
    # No for now?
    return possible_submodule_inst_name in logic.submodule_instances


def WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(wire, Logic, parser_state):
    if SUBMODULE_MARKER in wire:
        toks = wire.split(SUBMODULE_MARKER)
        submodule_inst_name = toks[0]
        port_name = toks[1]
        submodule_func_name = Logic.submodule_instances[submodule_inst_name]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        if submodule_logic.is_vhdl_expr and (port_name in submodule_logic.inputs):
            return True
    return False


def WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(wire, Logic, parser_state):
    if SUBMODULE_MARKER in wire:
        toks = wire.split(SUBMODULE_MARKER)
        submodule_inst_name = toks[0]
        port_name = toks[1]
        submodule_func_name = Logic.submodule_instances[submodule_inst_name]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        if submodule_logic.is_vhdl_func and (port_name in submodule_logic.inputs):
            return True
    return False


# Benchmark-only escape hatch for src/tests/pypeline_tests/op_qor_bench.py:
# when set, routes integer GT/GTE/LT/LTE to the (otherwise dead,
# RAW_VHDL.py:3050-3665) sliced hand-pipelined comparator generators instead
# of a soft-operator-library implementation, so the QoR bench can measure
# "revived raw sliced" head to head against the soft flavors. Never set
# outside that harness -- it does not change canonical entity names (only
# what VHDL gets generated for the same name), so mixing settings within one
# process/output directory would produce inconsistent cached artifacts.
FORCE_RAW_INT_CMP_FOR_QOR_BENCH = os.environ.get("PYPELINE_FORCE_RAW_INT_CMP") == "1"


def C_BUILT_IN_FUNC_IS_RAW_HDL(
    logic_func_name, input_c_types, output_c_type, parser_state
):
    if (
        FORCE_RAW_INT_CMP_FOR_QOR_BENCH
        and C_TYPES_ARE_INTEGERS(input_c_types)
        and any(
            logic_func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + op)
            for op in (
                BIN_OP_GTE_NAME,
                BIN_OP_LTE_NAME,
                BIN_OP_LT_NAME,
                BIN_OP_GT_NAME,
            )
        )
    ):
        return True
    # IS RAW VHDL
    if (
        logic_func_name == VHDL_FUNC_NAME
        or IS_BIT_MANIP_NAME(logic_func_name)
        or IS_SIM_CTRL_FUNC_NAME(logic_func_name)
        or logic_func_name.startswith(ACCUM_FUNC_NAME)
        or logic_func_name.startswith(CONST_REF_RD_FUNC_NAME_PREFIX + "_")
        or (
            logic_func_name.startswith(
                CONST_PREFIX + BIN_OP_SL_NAME + "_"
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                CONST_PREFIX + BIN_OP_SR_NAME + "_"
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                UNARY_OP_LOGIC_NAME_PREFIX
                + "_"
                + UNARY_OP_NOT_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                UNARY_OP_LOGIC_NAME_PREFIX
                + "_"
                + UNARY_OP_NEGATE_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX
                + "_"
                + BIN_OP_INFERRED_MULT_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_PLUS_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MINUS_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_EQ_NAME
            )
        )
        or (  # and C_TYPES_ARE_INTEGERS(input_c_types)
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_NEQ_NAME
            )
        )
        or (  # and C_TYPES_ARE_INTEGERS(input_c_types)
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_AND_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_OR_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_XOR_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(CAST_FUNC_NAME_PREFIX)
            and C_TYPES_ARE_INTEGERS(input_c_types)
            and C_TYPES_ARE_INTEGERS([output_c_type])
        )
        or (logic_func_name.startswith(MUX_LOGIC_NAME))
    ):  # or
        return True

    # IS NOT RAW VHDL
    elif (
        logic_func_name.startswith(VAR_REF_RD_FUNC_NAME_PREFIX + "_")
        or logic_func_name.startswith(VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_")
        or (
            logic_func_name.startswith(
                UNARY_OP_LOGIC_NAME_PREFIX
                + "_"
                + UNARY_OP_NEGATE_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or logic_func_name.startswith(CAST_FUNC_NAME_PREFIX + "_")
        or logic_func_name.startswith(
            BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_DIV_NAME
        )
        or logic_func_name.startswith(
            BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MULT_NAME
        )
        or logic_func_name.startswith(
            BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MOD_NAME
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX
                + "_"
                + BIN_OP_INFERRED_MULT_NAME
            )
            and C_TYPE_IS_FLOAT_TYPE(output_c_type)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SL_NAME
            )
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SR_NAME
            )
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GT_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GTE_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LT_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LTE_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_PLUS_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MINUS_NAME
            )
            and C_TYPES_ARE_FLOAT_TYPES(input_c_types)
        )
        or (logic_func_name.startswith(ONE_HOT_EQ_LOGIC_NAME))
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GTE_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LTE_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LT_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
        or (
            logic_func_name.startswith(
                BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GT_NAME
            )
            and C_TYPES_ARE_INTEGERS(input_c_types)
        )
    ):
        return False

    else:
        raise Exception(
            "Is built in C function named",
            logic_func_name,
            "with input types",
            input_c_types,
            "raw VHDL or not?",
        )


def LOGIC_IS_RAW_HDL(Logic, parser_state):
    if Logic.is_c_built_in:
        input_types = []
        for in_port in Logic.inputs:
            input_types.append(Logic.wire_to_c_type[in_port])
        output_type = Logic.wire_to_c_type[RETURN_WIRE_NAME]
        return C_BUILT_IN_FUNC_IS_RAW_HDL(
            Logic.func_name, input_types, output_type, parser_state
        )
    else:
        if IS_BIT_MANIP(Logic):
            return True
        if IS_MEM(Logic):
            return True
    return False


# Set by PY_TO_LOGIC.PARSE_FILE around a Pypeline build so BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC
# below raises instead of silently falling back to the C front end's
# C_TO_LOGIC.BUILD_LOGIC_AS_C_CODE (C code generation, cpp, pycparser). Pypeline builds
# no longer emit anything that reaches it (integer NEGATE/compare/DIV/MOD/variable-shift
# now have Pypeline HDL lowerings available) -- this is the enforcement that it stays
# that way.
PYPELINE_NO_SW_LIB_GUARD = False


def BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(
    containing_func_logic, submodule_inst, parser_state
):
    # Construct a fake 'submodule_logic' with correct name, inputs, outputs
    import C_TO_LOGIC

    submodule_logic = Logic()
    submodule_logic.is_c_built_in = True
    # Look up logic name for the submodule instance
    # print "containing_func_logic.func_name",containing_func_logic.func_name
    submodule_logic_name = containing_func_logic.submodule_instances[submodule_inst]
    # print "submodule_inst",submodule_inst
    # print "submodule_logic_name",submodule_logic_name
    submodule_logic.func_name = submodule_logic_name
    # print("...", submodule_logic.func_name, flush=True)

    # Ports and types are specific to the submodule instance
    # Get data from c ast node
    if submodule_inst in containing_func_logic.submodule_instance_to_ast_meta:
        ast_meta = containing_func_logic.submodule_instance_to_ast_meta[submodule_inst]
        submodule_logic.ast_meta = ast_meta
    if (
        submodule_inst
        in containing_func_logic.submodule_instance_to_printf_format_string
    ):
        submodule_logic.printf_format_string = (
            containing_func_logic.submodule_instance_to_printf_format_string[
                submodule_inst
            ]
        )
    if submodule_inst in containing_func_logic.submodule_instance_to_sim_assert_msg:
        submodule_logic.sim_assert_msg = (
            containing_func_logic.submodule_instance_to_sim_assert_msg[submodule_inst]
        )

    # It looks like the c parser doesnt let you look up type from name...
    # Probably would be complicated
    # Lets manually do it.
    # 1) parse funtion param declartions in wire_to_c_type
    # 2) parse var decls to wire_to_c_type
    # 3) Look up driver of submodule to determine type

    # Assume children list is is order of args
    input_names = []
    if submodule_inst in containing_func_logic.submodule_instance_to_input_port_names:
        input_names = containing_func_logic.submodule_instance_to_input_port_names[
            submodule_inst
        ]
        submodule_logic.inputs += input_names
    else:
        raise Exception(f"Cannot find submodule input port names! {submodule_inst}")
        # input_names = c_ast_node.get_input_names(parser_state)
        # submodule_logic.inputs += input_names

    # Try to get input type from port name in container logic
    # Fall back on type of driving wires
    # For each input wire look up type of driving wire
    input_types = []
    for input_name in input_names:
        input_wire_name = submodule_inst + SUBMODULE_MARKER + input_name
        # First try input port type
        if input_wire_name in containing_func_logic.wire_to_c_type:
            c_type = containing_func_logic.wire_to_c_type[input_wire_name]
        else:
            # Fall back on driving wire
            # print logic.wire_driven_by
            driving_wire = containing_func_logic.wire_driven_by[input_wire_name]
            c_type = containing_func_logic.wire_to_c_type[driving_wire]

        """ Shouldnt need this here, is handled for general BIN OP?
    # If driving wire c type is enum and this is BIN OP == then replace with input port wire with uint
    if (C_TYPE_IS_ENUM(c_type, parser_state)) and (submodule_logic_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_EQ_NAME)):
      c_type = ...
    """

        # Record input info
        submodule_logic.wire_to_c_type[input_name] = c_type
        input_types.append(c_type)

    # Output wire is return wire
    # Try to get output port type from containing logic
    # Fall back on type of what is driven
    output_port_name = RETURN_WIRE_NAME
    output_wire_name = submodule_inst + SUBMODULE_MARKER + output_port_name
    c_type = None
    if output_wire_name in containing_func_logic.wire_to_c_type:
        c_type = containing_func_logic.wire_to_c_type[output_wire_name]
    else:
        # Fall back type of driven wire
        # By default assume type of driven wire if not yet driven
        if output_wire_name in containing_func_logic.wire_drives:
            driven_wires = containing_func_logic.wire_drives[output_wire_name]
            if len(driven_wires) == 0:
                print("Built in submodule not driving anthying?", submodule_inst)
                sys.exit(-1)
            c_type = containing_func_logic.wire_to_c_type[list(driven_wires)[0]]
        else:
            # Fine if vhdl func or other build in stuff like printf?
            if submodule_logic.func_name == VHDL_FUNC_NAME:
                pass
            elif IS_SIM_CTRL_FUNC_NAME(submodule_logic.func_name):
                pass
            else:
                print(
                    "containing_func_logic.func_name", containing_func_logic.func_name
                )
                print("output_wire_name", output_wire_name)
                # print "containing_func_logic.wire_drives",containing_func_logic.wire_drives
                for wire in containing_func_logic.wire_drives:
                    print(wire, "=>", containing_func_logic.wire_drives[wire])
                print(
                    "Input type to output type mapping assumption for built in submodule output "
                )
                print(submodule_logic.func_name)
                sys.exit(-1)

    # Record output type
    if c_type is not None:
        submodule_logic.outputs.append(output_port_name)
        submodule_logic.wire_to_c_type[output_port_name] = c_type

    # Record if vhdl func
    # CONST refs are vhdl funcs
    if submodule_logic_name.startswith(CONST_REF_RD_FUNC_NAME_PREFIX):
        submodule_logic.is_vhdl_func = True

    # Casts of ints are vhdl funcs too
    if submodule_logic_name.startswith(
        CAST_FUNC_NAME_PREFIX
    ) and C_TYPES_ARE_INTEGERS(input_types + [c_type]):
        submodule_logic.is_vhdl_func = True

    # Bit manip is VHDL func too
    if IS_BIT_MANIP(submodule_logic):
        submodule_logic.is_vhdl_func = True

    # Also do submodule instances for built in logic that is not raw VHDL
    if C_BUILT_IN_FUNC_IS_RAW_HDL(
        submodule_logic_name, input_types, c_type, parser_state
    ):
        # IS RAW VHDL
        pass
    # NOT RAW VHDL (assumed to be built from C code then)
    else:
        if PYPELINE_NO_SW_LIB_GUARD:
            raise Exception(
                f"Pypeline build reached the C-code-generation/cpp/pycparser path "
                f"for '{submodule_logic.func_name}' -- this should be "
                f"unreachable from Pypeline. Register a soft/Pypeline-HDL "
                f"implementation for whichever operator produced this entity."
            )
        submodule_logic = C_TO_LOGIC.BUILD_LOGIC_AS_C_CODE(
            submodule_inst, submodule_logic, parser_state, containing_func_logic
        )

    return submodule_logic


def C_TYPE_IS_STRUCT(c_type_str, parser_state):
    return (
        c_type_str in parser_state.struct_to_field_type_dict
    ) or C_TYPE_IS_ARRAY_STRUCT(c_type_str, parser_state)


def C_TYPE_IS_ENUM(c_type_str, parser_state):
    return c_type_str in parser_state.enum_info_dict


# Includes intN and uintN
def C_TYPES_ARE_ENUMS(c_types, parser_state):
    for c_type in c_types:
        if not C_TYPE_IS_ENUM(c_type, parser_state):
            return False
    return True


def C_TYPE_IS_ARRAY(c_type):
    if c_type is None:
        return False
    return "[" in c_type and c_type.endswith("]")


def C_TYPE_IS_FLOAT_E_M(c_type):
    if c_type is None:
        return False
    toks = c_type.split("_")
    if (
        c_type.startswith("float_")
        and c_type.endswith("_t")
        and len(toks) == 4
        and toks[1].isdigit()
        and toks[2].isdigit()
    ):
        return True
    return False


def C_TYPE_IS_FLOAT_TYPE(c_type):
    if c_type == "float":
        return True
    elif C_TYPE_IS_FLOAT_E_M(c_type):
        return True
    return False


def C_TYPES_ARE_FLOAT_TYPES(c_types):
    for c_type in c_types:
        if not C_TYPE_IS_FLOAT_TYPE(c_type):
            return False
    return True


def C_FLOAT_E_M_TYPE_TO_E_M(c_type):
    if c_type == "float":
        return (8, 23)
    # print("c_type",c_type)
    toks = c_type.split("_")
    e = int(toks[1])
    m = int(toks[2])
    return e, m


def C_FLOAT_TYPES_ARE_EQUAL(c_types):
    the_type = c_types[0]
    for c_type in c_types:
        if c_type == "float" and the_type == "float_8_23_t":
            continue
        elif c_type == "float_8_23_t" and the_type == "float":
            continue
        elif c_type != the_type:
            return False
    return True


def C_FLOAT_TYPES_TO_COMMON_TYPE(c_types):
    # Since alternative fp types are typically smaller
    # Find the minimum fp width involved, use probabaly wants that
    min_e = 9999
    min_m = 9999
    for c_type in c_types:
        e, m = C_FLOAT_E_M_TYPE_TO_E_M(c_type)
        min_e = min(min_e, e)
        min_m = min(min_m, m)
    if e == 8 and min_m == 23:
        return "float"
    return "float_" + str(min_e) + "_" + str(min_m) + "_t"


def C_TYPE_IS_USER_TYPE(c_type, parser_state):
    user_code = False
    if C_TYPE_IS_STRUCT(c_type, parser_state):
        if C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state):
            c_array_type = C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(c_type, parser_state)
            elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
            if C_TYPE_IS_STRUCT(elem_t, parser_state):
                user_code = True
        else:
            # Not the dumb array thing, is regular struct
            user_code = True
    elif C_TYPE_IS_ARRAY(c_type):
        elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
        if C_TYPE_IS_STRUCT(elem_type, parser_state):
            user_code = True
    elif C_TYPE_IS_ENUM(c_type, parser_state):
        user_code = True

    return user_code


def C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type):
    toks = input_array_type.split("[")
    # print toks
    elem_type = toks[0]
    dims = []
    for tok_i in range(1, len(toks)):
        tok = toks[tok_i]
        dim = int(tok.replace("]", ""))
        dims.append(dim)
    return elem_type, dims


def GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str):
    if not (C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str)):
        print("Cant GET_WIDTH_FROM_C_TYPE_STR since isnt int/uint N", c_type_str)
        print(0 / 0)
        sys.exit(-1)

    # Chars?
    if c_type_str == "char":
        return 8

    return int(c_type_str.replace("uint", "").replace("int", "").replace("_t", ""))


# 'Width' is apparently a integer like concept?
def GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str, allow_fail=False):
    if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str):
        return GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str)
    elif C_TYPE_IS_FLOAT_TYPE(c_type_str):
        e, m = C_FLOAT_E_M_TYPE_TO_E_M(c_type_str)
        return 1 + e + m
    elif C_TYPE_IS_ENUM(c_type_str, parser_state):
        # Enum type
        return GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(
            parser_state.enum_info_dict[c_type_str].int_c_type
        )
    else:
        if not allow_fail:
            print("Cant GET_WIDTH_FROM_C_TYPE_STR for ", c_type_str)
            print(0 / 0)
            sys.exit(-1)
        return None


def C_TYPE_IS_UINT_N(type_str):
    try:
        width = int(type_str.replace("uint", "").replace("_t", ""))
        return True
    except:
        # Chars?
        if type_str == "char":
            return True

        return False


def C_TYPE_IS_INT_N(type_str):
    try:
        width = int(type_str.replace("int", "").replace("_t", ""))
        return True
    except:
        return False


# Includes intN and uintN
def C_TYPES_ARE_INTEGERS(c_types):
    for c_type in c_types:
        # No dummy, arrays are not ints? You hacky hoe
        """
        if C_TYPE_IS_ARRAY(c_type):
          elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
          c_type = elem_type
          #print "c_type",c_type
        """
        if not (C_TYPE_IS_INT_N(c_type) or C_TYPE_IS_UINT_N(c_type)):
            return False
    return True


def WIRES_ARE_ENUM(wires, logic, parser_state):
    for wire in wires:
        # print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
        if not WIRE_IS_ENUM(wire, logic, parser_state):
            return False
    return True


def WIRES_ARE_UINT_N(wires, logic):
    for wire in wires:
        # print("wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire])
        if not C_TYPE_IS_UINT_N(logic.wire_to_c_type[wire]):
            return False
    return True


def WIRES_ARE_INT_N(wires, logic):
    for wire in wires:
        # print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
        if not C_TYPE_IS_INT_N(logic.wire_to_c_type[wire]):
            return False
    return True


# WTF enums
# Bullshit.
#
def WIRE_IS_ENUM(maybe_not_enum_wire, existing_logic, parser_state):
    # Will not be:
    # (this is dumb)
    #   known to enum
    #   Known not to be enum? wtf?
    # input
    # global
    #   volatile global
    # variable
    #   output
    #
    # Then must be ENUM

    # ORIG_WIRE_NAME_TO_ORIG_VAR_NAME
    if ENUM_CONST_MARKER in maybe_not_enum_wire:
        return True
    elif (maybe_not_enum_wire in existing_logic.wire_to_c_type) and C_TYPE_IS_ENUM(
        existing_logic.wire_to_c_type[maybe_not_enum_wire], parser_state
    ):
        return True
    elif (maybe_not_enum_wire in existing_logic.wire_to_c_type) and not C_TYPE_IS_ENUM(
        existing_logic.wire_to_c_type[maybe_not_enum_wire], parser_state
    ):
        return False
    # elif maybe_not_enum_wire in existing_logic.inputs:
    #  return False
    # elif (maybe_not_enum_wire in existing_logic.state_regs):
    #  return False
    # elif maybe_not_enum_wire in existing_logic.variable_names:
    #  return False
    # elif maybe_not_enum_wire in existing_logic.outputs:
    #  return False
    else:
        print("Unknown maybe ENUM?:", maybe_not_enum_wire)
        sys.exit(-1)


def GET_VAL_STR_FROM_CONST_WIRE(wire_name, Logic, parser_state):
    local_name = wire_name

    # Special null token
    if wire_name.startswith(CONST_PREFIX + COMPOUND_NULL):
        return COMPOUND_NULL

    # Get last submodule tok
    toks = local_name.split(SUBMODULE_MARKER)
    last_tok = toks[len(toks) - 1]
    local_name = last_tok

    # Strip off CONST_
    stripped_wire_name = local_name
    if local_name.startswith(CONST_PREFIX):
        stripped_wire_name = local_name[len(CONST_PREFIX) :]

    # CANT SPLIT ON UNDER dummy - ENUMS ARE CONSTs too
    if ENUM_CONST_MARKER in stripped_wire_name:
        ami_digit = stripped_wire_name.split(ENUM_CONST_MARKER)[0]
    else:
        # OK now can do dumb splitting
        toks = stripped_wire_name.split("_")
        ami_digit = toks[0]

    # print("const wire:",wire_name,"valuestr:",ami_digit)

    return ami_digit


def BUILD_CONST_WIRE(value_str, ast_meta, is_negated=False):
    rv = CONST_PREFIX
    if is_negated:
        rv += "-"
    rv += value_str + "_" + ast_meta.coord_str()
    return rv


def GET_CONTAINER_INST(inst_name):
    # Construct container from full inst name
    toks = inst_name.split(SUBMODULE_MARKER)
    container = SUBMODULE_MARKER.join(toks[0 : len(toks) - 1])
    if container == inst_name:
        return None
    if container == "":
        return None
    return container


def RECURSIVE_FIND_MAIN_FUNC_FROM_INST(inst_name, parser_state):
    container = GET_CONTAINER_INST(inst_name)
    if container is None:
        # Top level
        return inst_name
    else:
        return RECURSIVE_FIND_MAIN_FUNC_FROM_INST(container, parser_state)


# For things that look like
# Get the last token (leaf) token when splitting by "/" and sub marker
def LEAF_NAME(name, do_submodule_split=True):
    new_name = name

    # Pick last submodule item
    if (SUBMODULE_MARKER in name) and do_submodule_split:
        toks = new_name.split(SUBMODULE_MARKER)
        toks.reverse()
        new_name = toks[0]

    return new_name


def FUNC_SRC_LOC_STR(parser_state, func_name):
    """' [file.py:line]' for a function's true source location, or '' when
    none is known (built-ins, raw-HDL, etc.) -- for appending to stdout/
    [sweep] messages that name a function, so a reader isn't left grepping a
    second, much larger log file for a line number. Logic.ast_meta already
    carries this; nothing printed it before now."""
    logic = parser_state.FuncLogicLookupTable.get(func_name)
    ast_meta = getattr(logic, "ast_meta", None)
    if ast_meta is None:
        return ""
    return f" [{os.path.basename(ast_meta.src_file)}:{ast_meta.line}]"


# func_name -> whether that func's Logic needs a CLOCK_ENABLE input port
_LOGIC_NEEDS_CLOCK_ENABLE_cache = {}


def LOGIC_NEEDS_CLOCK_ENABLE(logic, parser_state):
    try:
        needs = _LOGIC_NEEDS_CLOCK_ENABLE_cache[logic.func_name]
        # print("Got cache!")
        return needs
    except:
        pass

    # Only async/flow control clock crossings (need clock enable to work with their write and read enable side fifos)
    # or WRITE side on wires that will default hold value
    # Almost covered by LOGIC_NEEDS_MODULE_TO_GLOBAL but thats for submodules
    if logic.is_clock_crossing:
        # i_need = LOGIC_NEEDS_MODULE_TO_GLOBAL(logic, parser_state)
        clk_cross_var = CLK_CROSS_FUNC_TO_VAR_NAME(logic.func_name)
        clk_cross_info = parser_state.clk_cross_var_info[clk_cross_var]
        i_need = ("_WRITE" in logic.func_name) or clk_cross_info.flow_control
    else:
        # TODO use needs clock too?
        i_need = (
            len(logic.state_regs) > 0
            or logic.uses_nonvolatile_state_regs
            or IS_SIM_CTRL_FUNC_NAME(logic.func_name)
        )

    # Check submodules too
    needs = i_need

    if not needs:
        sub_funcs = set(logic.submodule_instances.values())
        for submodule_logic_name in sub_funcs:
            # If not in FuncLogicLookupTable then not parsed from C code (i.e. built in assumed?), couldnt need clock enable
            if submodule_logic_name in parser_state.FuncLogicLookupTable:
                submodule_logic = parser_state.FuncLogicLookupTable[
                    submodule_logic_name
                ]
                needs = needs or LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state)
                if needs:
                    break
            elif IS_SIM_CTRL_FUNC_NAME(submodule_logic_name):
                needs = True
                break

    _LOGIC_NEEDS_CLOCK_ENABLE_cache[logic.func_name] = needs

    return needs


def GLOBAL_VAR_IS_SHARED(var_name, parser_state):
    if var_name in parser_state.output_wires:
        return True
    if var_name in parser_state.input_wires:
        return True
    # # Async wires assumed shared
    # if var_name in parser_state.async_wires:
    #   return True
    # Clock wires assumed shared
    if var_name in parser_state.clk_mhz:
        return True
    # Otherwise check where used
    if var_name not in parser_state.global_vars:
        return False
    var_info = parser_state.global_vars[var_name]
    # Instance array stuff wont appear used normally is special case
    part_of_inst_array = (var_name in parser_state.inst_array_dict.values()) or (
        var_name in parser_state.inst_array_dict.keys()
    )
    return len(var_info.used_in_funcs) > 1 or part_of_inst_array


def LOGIC_NEEDS_GLOBAL_TO_MODULE(Logic, parser_state):
    needs_global_to_module = False

    # Submodules determine if logic needs clk cross port
    for inst in Logic.submodule_instances:
        submodule_logic_name = Logic.submodule_instances[inst]
        if submodule_logic_name in parser_state.FuncLogicLookupTable:
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
            if submodule_logic.is_clock_crossing:
                var_name = CLK_CROSS_FUNC_TO_VAR_NAME(submodule_logic_name)
                clk_cross_info = parser_state.clk_cross_var_info[var_name]
                needs_global_to_module = (
                    needs_global_to_module
                    or ("_READ" in submodule_logic_name)
                    or clk_cross_info.flow_control
                )
            if needs_global_to_module:
                return True
            # Then check sub-sub modules
            needs_global_to_module = (
                needs_global_to_module
                or LOGIC_NEEDS_GLOBAL_TO_MODULE(submodule_logic, parser_state)
            )
            if needs_global_to_module:
                return True

    # Or if logic is reading a global reg
    if len(Logic.read_only_global_wires) > 0:
        return True

    return needs_global_to_module


def LOGIC_NEEDS_MODULE_TO_GLOBAL(Logic, parser_state):
    needs_module_to_global = False
    # Submodules determine if logic needs clock cross port
    for inst in Logic.submodule_instances:
        submodule_logic_name = Logic.submodule_instances[inst]
        if submodule_logic_name in parser_state.FuncLogicLookupTable:
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
            if submodule_logic.is_clock_crossing:
                var_name = CLK_CROSS_FUNC_TO_VAR_NAME(submodule_logic_name)
                clk_cross_info = parser_state.clk_cross_var_info[var_name]
                needs_module_to_global = (
                    needs_module_to_global
                    or ("_WRITE" in submodule_logic_name)
                    or clk_cross_info.flow_control
                )
            if needs_module_to_global:
                return True
            # Then check sub-sub modules
            needs_module_to_global = (
                needs_module_to_global
                or LOGIC_NEEDS_MODULE_TO_GLOBAL(submodule_logic, parser_state)
            )
            if needs_module_to_global:
                return True

    # Or if logic is writing a global reg with muliple reads
    for state_reg_var, var_info in Logic.state_regs.items():
        if var_info in parser_state.global_vars.values() and GLOBAL_VAR_IS_SHARED(
            state_reg_var, parser_state
        ):
            return True
    for state_reg_var, var_info in Logic.write_only_global_wires.items():
        if GLOBAL_VAR_IS_SHARED(state_reg_var, parser_state):
            return True

    return needs_module_to_global


def BUILD_FUNC_NAME(func_base_name, output_type, input_driver_types, base_name_is_name):
    # Build func name
    func_name = func_base_name
    if not base_name_is_name:
        types_str = ""
        ## Output type
        # types_str += "_" + output_type.replace("[","_").replace("]","")
        # Append input types to base name
        for input_driver_type in input_driver_types:
            if input_driver_type is None:
                print(
                    "Oh no, dont know types building func name instance", func_base_name
                )
                print(0 / 0)
                sys.exit(-1)
            # Input could be array type with brackets so remove for safe C func name
            types_str += "_" + input_driver_type.replace("[", "_").replace("]", "")

        func_name = func_base_name + types_str

    return func_name


class PrintfFormat:
    def __init__(self):
        self.index = None
        self.specifier = None
        self.c_type = None
        self.vhdl_to_string_toks = [None, None]
        self.base = None


def PRTINTF_STRING_TO_FORMATS(format_string):
    rv = []
    # Parse format string to get types of arguments
    # Thanks internet, https://stackoverflow.com/questions/30011379/how-can-i-parse-a-c-format-string-in-python

    cfmt = (
        f"""\
        (                                  # start of capture group 1
        %                                  # literal "%"
        (?:                                # first option
        (?:[-+0 #]"""
        + "{0,5})"
        + rf"""    # optional flags
        (?:\d+|\*)?                        # width
        (?:\.(?:\d+|\*))?                  # precision
        (?:h|l|ll|w|I|I32|I64)?            # size
        [cCdiouxXeEfgGaAnpsSZ]             # type
        ) |                                # OR
        %%)                                # literal "%%"
        """
    )
    format_specifier_tups = tuple(
        (m.start(1), m.group(1)) for m in re.finditer(cfmt, format_string, flags=re.X)
    )
    for format_specifier_tup in format_specifier_tups:
        index, format_specifier = format_specifier_tup
        f = PrintfFormat()
        f.index = index
        f.specifier = format_specifier
        if format_specifier == "%d":
            f.c_type = "int32_t"
            f.base = 10
            f.vhdl_to_string_toks = ["integer'image(to_integer(", "))"]
        elif format_specifier == "%u":
            f.c_type = "uint32_t"  # VHDL cant do full u32 range printed as int?32
            f.base = 10
            f.vhdl_to_string_toks = ["integer'image(to_integer(", "))"]
        elif (format_specifier == "%08X") or (
            format_specifier == "%X"
        ):  # hstring is UPPER CASE and 32b wide
            f.c_type = "uint32_t"
            f.base = 16
            f.vhdl_to_string_toks = ["to_hstring(", ")"]
        elif format_specifier == "%f":
            f.c_type = "float"
            f.base = None
            f.vhdl_to_string_toks = ["real'image(to_real(to_float(", ")))"]
        elif format_specifier == "%c":
            f.c_type = "char"
            f.base = None
            f.vhdl_to_string_toks = ["character'val(to_integer(", "))"]
        elif format_specifier == "%s":
            # Real type/size not known from the format string alone -- callers
            # (C_AST_PRINTF_FUNC_CALL_TO_LOGIC) inspect the driving wire's actual type
            # instead, mirroring C_AST_STRLEN_FUNC_CALL_TO_LOGIC. VHDL codegen already
            # supports any real length (to_string() operates on the unconstrained
            # byte_array_t), so no placeholder size is needed here.
            f.c_type = None
            f.base = None
            f.vhdl_to_string_toks = ["to_string(", ")"]
        else:
            print("TODO: Unsupported printf format:", format_specifier)
            sys.exit(-1)

        rv.append(f)

    return rv


def C_TYPE_SIZE(c_type, parser_state, allow_fail=False, c_ast_node=None):

    if C_TYPE_IS_ARRAY(c_type):
        elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
        elem_size = C_TYPE_SIZE(elem_t, parser_state)
        byte_size = elem_size
        for dim in dims:
            byte_size = byte_size * dim
    elif C_TYPE_IS_STRUCT(c_type, parser_state):
        field_to_type_dict = parser_state.struct_to_field_type_dict[c_type]
        byte_size = 0
        for field in field_to_type_dict:
            field_type = field_to_type_dict[field]
            field_size = C_TYPE_SIZE(field_type, parser_state)
            byte_size = byte_size + field_size
    elif C_TYPES_ARE_INTEGERS([c_type]):
        bit_width = GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
        byte_size = int(math.ceil(float(bit_width) / float(8)))
    elif C_TYPE_IS_FLOAT_TYPE(c_type):
        e, m = C_FLOAT_E_M_TYPE_TO_E_M(c_type)
        bit_width = 1 + e + m
        byte_size = int(math.ceil(float(bit_width) / float(8)))
    elif C_TYPE_IS_ENUM(c_type, parser_state):
        bit_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
        byte_size = int(math.ceil(float(bit_width) / float(8)))
    else:
        if not allow_fail:
            print("How to sizeof", c_type, "???")
            if c_ast_node:
                print(c_ast_node)
                print(c_ast_node.coord)
            else:
                print(0 / 0)
            # print("parser_state.struct_to_field_type_dict",parser_state.struct_to_field_type_dict)
            sys.exit(-1)
        byte_size = -1

    return byte_size


# Return None if wire is not driven by const (or anything)
def FIND_CONST_DRIVING_WIRE(wire, logic):
    if WIRE_IS_CONSTANT(wire):
        return wire
    elif wire in logic.wire_driven_by:
        driving_wire = logic.wire_driven_by[wire]
        # Wtf some wires like state vars driven themselves?
        if driving_wire != wire:
            return FIND_CONST_DRIVING_WIRE(driving_wire, logic)
    return None


def GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic, submodule_inst, input_port_name):
    # print "logic.func_name", logic.func_name
    name = submodule_inst + SUBMODULE_MARKER + input_port_name
    # print " logic.wire_driven_by"
    # print logic.wire_driven_by
    driving_wire = logic.wire_driven_by[name]
    return driving_wire


def FIND_DANGLING_LOGIC(logic):
    for driving_wire in logic.wire_drives:
        driven_wires = logic.wire_drives[driving_wire]
        # Handle each driven wire
        for driven_wire in driven_wires:
            if driven_wire not in logic.wire_driven_by:
                raise Exception(
                    f"{logic.func_name} has driving_wire {driving_wire} that is listed as driving driven_wire {driven_wire} but driven_wire is not in wire_driven_by dict?"
                )


# Record driving_wire -> driven_wire_names in logic's wire graph (no type checks or
# casts; the C front end's C_TO_LOGIC.APPLY_CONNECT_WIRES_LOGIC does those first)
def CONNECT_WIRES_LOGIC(logic, driving_wire, driven_wire_names):
    logic.wires.add(driving_wire)
    for driven_wire_name in driven_wire_names:
        logic.wires.add(driven_wire_name)
    # Record wire_drives
    all_driven_wire_names = set()
    # Start with existing driven wires
    if driving_wire in logic.wire_drives:
        all_driven_wire_names = logic.wire_drives[driving_wire]
    # Append the new wires
    for driven_wire_name in driven_wire_names:
        all_driven_wire_names.add(driven_wire_name)
    # Save
    if len(all_driven_wire_names) > 0:
        logic.wire_drives[driving_wire] = all_driven_wire_names
    # Record wire_driven_by
    for driven_wire_name in driven_wire_names:
        logic.wire_driven_by[driven_wire_name] = driving_wire

    return logic


# TRIM_COLLAPSE reconnects wires that were already type checked when first connected:
# a driven wire without a type takes its driver's type, then connect
def _TRIM_COLLAPSE_CONNECT_WIRES(func_logic, driving_wire, driven_wire_names):
    rhs_type = func_logic.wire_to_c_type[driving_wire]
    for driven_wire_name in driven_wire_names:
        if driven_wire_name not in func_logic.wire_to_c_type:
            func_logic.wire_to_c_type[driven_wire_name] = rhs_type
    return CONNECT_WIRES_LOGIC(func_logic, driving_wire, driven_wire_names)


# Names of funcs TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE already pruned this parse (DEL_ALL_CACHES clears)
_TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE_done_cache = set()


# Wow this is post elab and includes adjustments to global table of instance names etc...
def TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(func_logic, parser_state):
    # Done already?
    if func_logic.func_name in _TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE_done_cache:
        return parser_state

    # First do recursively for each submodule
    for submodule_inst in func_logic.submodule_instances:
        submodule_func_name = func_logic.submodule_instances[submodule_inst]
        # Skip vhdl
        if submodule_func_name == VHDL_FUNC_NAME:
            continue
        # Skip clock crossings too
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        if submodule_logic.is_clock_crossing:
            continue
        parser_state = TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(submodule_logic, parser_state)

    debug = False
    # Then do for self
    parser_state.existing_logic = func_logic
    # Some code creates logic that will optimize away
    # But actually the amount of generated VHDL can be too much
    # So manually prune logic
    # Look for wires that do not drive anything
    #   Note: submodule input ports are
    #   the only wires that can stay and not drive anything to module
    #   Inputs for some faked funcs with no func body need to be saved too
    #   Original variable wires dont drive things because alias will drive instead; int x; x=1;
    for wire in set(func_logic.wires):  # Copy for iter
        if wire in func_logic.wires:  # Changes during iter
            drives_nothing = wire not in func_logic.wire_drives
            must_drive_something = not func_logic.WIRE_ALLOW_NO_DRIVES(
                wire, parser_state.FuncLogicLookupTable
            )
            if drives_nothing and must_drive_something:
                if debug:
                    print(
                        func_logic.func_name,
                        "drives_nothing and must_drive_something Removing",
                        wire,
                    )
                func_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(wire, parser_state)
            else:
                pass
                # if debug:
                #  print(func_logic.func_name,"drives_nothing", drives_nothing, wire)
                #  if not drives_nothing:
                #    print(func_logic.func_name,"Drives:",func_logic.wire_drives[wire])
                #  print(func_logic.func_name,"must_drive_something",must_drive_something, wire)
        else:
            if debug:
                pass
                # print(func_logic.func_name, "NOT Removing", wire)
                # print("drives_nothing",drives_nothing)
                # if not drives_nothing:
                #  print(func_logic.wire_drives[wire])
                #  print("must_drive_something",must_drive_something)

    # Songs: Ohia - Farewell Transmission
    # Not all wires are necessary
    # In fact, any wire that is not a sub/module port is probably extra?
    # Use 'WIRE_DO_NOT_COLLAPSE' to collapse connections down to submodule port connections
    making_changes = True
    while making_changes:
        making_changes = False
        for wire in set(func_logic.wires):  # Copy for iter
            if wire in func_logic.wires:  # Changes during iter
                # Look for not special wires that have driving info
                if (
                    not func_logic.WIRE_DO_NOT_COLLAPSE(wire, parser_state)
                    and (wire in func_logic.wire_driven_by)
                    and (wire in func_logic.wire_drives)
                ):
                    # Get driving info
                    driving_wire = func_logic.wire_driven_by[wire]
                    driven_wires = func_logic.wire_drives[wire]
                    # Replacing wire with driving_wire, must have same type dummy
                    types_match = True
                    driving_wire_c_type = func_logic.wire_to_c_type[driving_wire]
                    wire_c_type = func_logic.wire_to_c_type[wire]
                    if driving_wire_c_type != wire_c_type:
                        types_match = False
                    for driven_wire in driven_wires:
                        driven_wire_c_type = func_logic.wire_to_c_type[driven_wire]
                        if driving_wire_c_type != driven_wire_c_type:
                            types_match = False
                    if not types_match:
                        continue
                    # Do removal
                    making_changes = True
                    # Remove record of this wire driving anything so removal doesnt progate forward, only backwards
                    if debug:
                        print(func_logic.func_name, "unecessary Removing", wire)
                        print(driving_wire, "drives -> ", driven_wires)
                    func_logic.wire_drives.pop(wire)
                    # Make new connection before ripping up old wire
                    func_logic = _TRIM_COLLAPSE_CONNECT_WIRES(
                        func_logic, driving_wire, driven_wires
                    )
                    # Totally remove old wire
                    func_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(wire, parser_state)
                    # break # Needed?  Wanted?

    # Detect duplicate submodules
    # Clock enable makes thing complicated - todo make neater future me
    #   Bill Withers - Lean on Me
    # dict[ tuple(func name, in_port, driver, wires) ] = [list,of,matching,insts]
    # Do repeatedly unitl no more opts?
    making_changes = True
    while making_changes:
        making_changes = False

        # Find duplicates
        submodule_dups = {}
        for submodule_inst in func_logic.submodule_instances:
            submodule_func_name = func_logic.submodule_instances[submodule_inst]
            # Skip printf/sim_assert/sim_finish (each instance is distinct, not a dedup candidate)
            if IS_SIM_CTRL_FUNC_NAME(submodule_func_name):
                continue
            if submodule_func_name not in parser_state.FuncLogicLookupTable:
                continue
            submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
            # Make id tup
            # Name
            id_tup = (submodule_logic.func_name,)
            # Clock enable
            # Make ce connection
            if LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state):
                sub_ce_wire = submodule_inst + SUBMODULE_MARKER + CLOCK_ENABLE_NAME
                driver_of_ce = func_logic.wire_driven_by[sub_ce_wire]
                id_tup += (driver_of_ce,)
            # Inputs
            for sub_input_port in submodule_logic.inputs:
                sub_input_wire = submodule_inst + SUBMODULE_MARKER + sub_input_port
                driver_of_input = func_logic.wire_driven_by[sub_input_wire]
                id_tup += (driver_of_input,)
            # Which AUTO_PIPELINE / AUTO_FSM group the call belongs to, last
            # (the collapse below reads drivers by position): two calls of one
            # function in different latency groups, or one tagged and one not,
            # are different hardware even with equal inputs
            id_tup += (
                func_logic.sub_inst_to_auto_pipeline_key.get(submodule_inst),
                func_logic.sub_inst_to_auto_pipeline_latency.get(submodule_inst),
                func_logic.sub_inst_to_auto_fsm_key.get(submodule_inst),
            )
            # Record
            if id_tup not in submodule_dups:
                submodule_dups[id_tup] = []
            submodule_dups[id_tup].append(submodule_inst)

        # Filter out "single instances" in duplicates list
        for id_tup, dup_insts in list(submodule_dups.items()):
            if len(dup_insts) <= 1:
                submodule_dups.pop(id_tup)
        if len(submodule_dups) <= 0:
            continue

        # Since removal of duplicate can rewire potential 'downstream' (and upstream?) connections to other duplicates
        # Only remove one duplicate per round of collecting id_tups above
        # Collapse all duplicates (more than 1 inst per id tup)
        # for id_tup,dup_insts in :
        id_tup, dup_insts = list(submodule_dups.items())[0]
        sub_func_name = id_tup[0]
        tup_idx = 1
        sub_func_logic = parser_state.FuncLogicLookupTable[sub_func_name]
        # print(id_tup,"duplicates:",dup_insts)

        # Have instances to collapse
        # Create new inst
        # Mangle me some name
        # Special case loops easy to identify since have same coord?
        new_sub_inst_name = None
        c_ast_metas = set()
        for sub_inst in dup_insts:
            if sub_inst in func_logic.submodule_instance_to_ast_meta:
                c_ast_metas.add(func_logic.submodule_instance_to_ast_meta[sub_inst])
        # Same c ast node or not, need to keep prepend id text
        # Create hash based on all inst names
        dup_inst_name_hash = (
            hashlib.md5(",".join(dup_insts).encode("utf-8")).hexdigest()
        )[0:4]  # 4 chars enough?
        dup_postpend_text = "_DUPLICATE_" + dup_inst_name_hash
        if len(c_ast_metas) == 1:  # TODO what does this look like otherwise?
            the_ast_meta = list(c_ast_metas)[0]
            # Use coord_str() directly — raw node may be a Python AST node (Pypeline)
            new_sub_inst_name = (
                sub_func_logic.func_name
                + "["
                + the_ast_meta.coord_str()
                + "]"
                + dup_postpend_text
            )
        else:
            file_lines = []
            last_ast_meta = None
            # c_ast_metas is a set of ASTMeta, whose __hash__ is
            # hash(coord_str()) -- a str hash, randomized per-process by
            # PYTHONHASHSEED. Both the emitted "lNN" order below and
            # last_ast_meta (which alone picks src_file_str) would otherwise
            # leak that order into new_sub_inst_name, changing generated VHDL
            # bytes for an identical design and defeating DEVICE_MODELS'
            # byte-hash synthesis cache (confirmed: 5 fresh builds, 4x
            # l35_l34, 1x l34_l35). Sort on the location fields only --
            # NOT coord_str()/hash_suffix, which embed str(id(node)) for the
            # C frontend (TEMP_HACKY_C_AST_NODE_ID) and are themselves
            # process-unstable.
            for ast_meta in sorted(
                c_ast_metas,
                key=lambda m: (
                    m.src_file,
                    m.line,
                    m.col,
                    -1 if m.end_col is None else m.end_col,
                ),
            ):
                # file_coord_strs += "[" + C_AST_NODE_COORD_STR(c_ast_node) + "]"
                file_line = "l" + str(ast_meta.line)
                if file_line not in file_lines:
                    file_lines.append(file_line)
                last_ast_meta = ast_meta
            # new_sub_inst_name = sub_func_logic.func_name + file_coord_strs + dup_postpend_text
            file_coord_strs = "_".join(file_lines)
            if file_coord_strs != "":
                file_coord_strs = "_" + file_coord_strs
            src_file_str = "internal"
            if last_ast_meta and last_ast_meta.src_file:
                src_file_str = os.path.basename(last_ast_meta.src_file).replace(
                    ".", "_"
                )
            new_sub_inst_name = (
                sub_func_logic.func_name
                + "_"
                + src_file_str
                + file_coord_strs
                + dup_postpend_text
            )
        # print("replacing with",new_sub_inst_name)

        # Copy the submodule information from one of the identical insts to this
        func_logic.COPY_SUBMODULE_INFO(new_sub_inst_name, dup_insts[0])
        func_logic.submodule_instance_to_source_origins[new_sub_inst_name] = (
            set().union(*(func_logic.submodule_instance_to_source_origins.get(i, set()) for i in dup_insts))
        )

        # Wire new inst ce+inputs with known identical drivers
        # Make ce connection
        if LOGIC_NEEDS_CLOCK_ENABLE(sub_func_logic, parser_state):
            new_ce_wire = new_sub_inst_name + SUBMODULE_MARKER + CLOCK_ENABLE_NAME
            func_logic.wire_to_c_type[new_ce_wire] = sub_func_logic.wire_to_c_type[
                CLOCK_ENABLE_NAME
            ]
            driver_of_ce = id_tup[tup_idx]
            func_logic = _TRIM_COLLAPSE_CONNECT_WIRES(
                func_logic, driver_of_ce, [new_ce_wire]
            )
            tup_idx += 1
        for input_port in sub_func_logic.inputs:
            new_input_port_wire = new_sub_inst_name + SUBMODULE_MARKER + input_port
            func_logic.wire_to_c_type[new_input_port_wire] = (
                sub_func_logic.wire_to_c_type[input_port]
            )
            driver_of_input = id_tup[tup_idx]
            tup_idx += 1
            # Make input connection
            func_logic = _TRIM_COLLAPSE_CONNECT_WIRES(
                func_logic, driver_of_input, [new_input_port_wire]
            )

        # Wire new inst outputs to all outputs
        # Make dict[sub out port] = [list of driven wires, from, all dup, insts, outputs]
        sub_out_port_to_driven_wires = {}
        for output_port in sub_func_logic.outputs:
            for sub_inst in dup_insts:
                sub_inst_output = sub_inst + SUBMODULE_MARKER + output_port
                wires_driven_by_sub_output = func_logic.wire_drives[sub_inst_output]
                if output_port not in sub_out_port_to_driven_wires:
                    sub_out_port_to_driven_wires[output_port] = set()
                sub_out_port_to_driven_wires[output_port] |= set(
                    wires_driven_by_sub_output
                )

        # Remove all local duplicate insts - ripping up outputs we just recorded
        for sub_inst in dup_insts:
            # Local func def removal + dont do global insts since will be renamed below
            func_logic.REMOVE_SUBMODULE(
                sub_inst,
                sub_func_logic.inputs,
                sub_func_logic.outputs,
                parser_state,
                remove_global=False,
            )

        # Use info on now ripped up outputs to rewire outputs
        for sub_out_port, driven_wires in sub_out_port_to_driven_wires.items():
            new_inst_output = new_sub_inst_name + SUBMODULE_MARKER + sub_out_port
            func_logic.wire_to_c_type[new_inst_output] = sub_func_logic.wire_to_c_type[
                sub_out_port
            ]
            # print("new_inst_output",new_inst_output)
            # print("drives",driven_wires)
            func_logic = _TRIM_COLLAPSE_CONNECT_WIRES(
                func_logic, new_inst_output, list(driven_wires)
            )
            # for driven_wire in driven_wires:
            #  print("func_logic.wire_driven_by",func_logic.wire_driven_by[driven_wire])

        # Record global insts by doing process for each global inst of container
        all_insts_of_container_func = parser_state.FuncToInstances[func_logic.func_name]
        for global_inst in all_insts_of_container_func:
            # Record new glb inst
            global_new_sub_inst_name = (
                global_inst + SUBMODULE_MARKER + new_sub_inst_name
            )
            parser_state.LogicInstLookupTable[global_new_sub_inst_name] = sub_func_logic
            if sub_func_name not in parser_state.FuncToInstances:
                parser_state.FuncToInstances[sub_func_name] = set()
            parser_state.FuncToInstances[sub_func_name].add(global_new_sub_inst_name)

            # Rename duplicate global insts (to capture renaming of submoduels too)
            # SHit this is hack af
            for sub_inst in dup_insts:
                global_dup_sub_inst_name = global_inst + SUBMODULE_MARKER + sub_inst
                # Because the game is hard
                # Dont do dumb loop collecting submodules with startswith
                # Do recursive rename instead
                parser_state = RECURSIVE_RENAME_GLOBAL_INST(
                    global_dup_sub_inst_name, global_new_sub_inst_name, parser_state
                )
        # print("==")

        making_changes = True

    # Record doing this logic
    _TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE_done_cache.add(func_logic.func_name)

    return parser_state


def DEL_ALL_CACHES():
    # Clear the shared caches after parsing is done (C_TO_LOGIC.DEL_ALL_CACHES also calls this)
    # The trim/collapse memo is per-parse state: it records func NAMES already
    # pruned, but a later parse rebuilds fresh (untrimmed) Logic objects under
    # the same names and must not skip trimming them.
    _TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE_done_cache.clear()


# All the state obtained by parsing one design (a C file via C_TO_LOGIC.PARSE_FILE,
# or a Python file via PY_TO_LOGIC.PARSE_FILE)
class ParserState:
    def __init__(self):
        # Build map just of func names and where there are used
        self.func_name_to_calls = {}  # dict[func_name] = set(called_func_names)
        self.func_names_to_called_from = {}  # dict[func_name] = set(calling_func_names)
        self.struct_to_field_type_dict = {}
        self.enum_info_dict = {}
        self.global_vars = {}  # name->state reg info

        # Function definitons as logic
        self.FuncLogicLookupTable = {}  # dict[func_name]=Logic() <--
        # Elaborated to instances
        self.LogicInstLookupTable = {}  # dict[inst_name]=Logic()  (^ same logic object as above)
        self.FuncToInstances = {}  # dict[func_name]=set([instance, name, usages, of , func)
        self.path_delay_funcs = None  # Full-parse delay dependencies in bottom-up order.
        self.path_delay_measure_funcs = None  # Hierarchy eligible for geometry measurements.
        self.path_delay_frontier_funcs = None  # Measured frontiers: comb pipeline roots, scheduled AUTO_FSMs.

        # Pragma info
        self.main_mhz = {}  # dict[main_inst_name]=mhz # Any inst name can be used
        self.main_syn_mhz = {}
        self.main_clk_group = {}  # dict[main_inst_name]=clk_group_str
        self.func_marked_wires = set()
        self.func_fixed_latency = {}
        self.auto_pipeline_rams = {}
        self.func_marked_blackbox = set()
        self.func_marked_no_add_io_regs = set()
        self.func_marked_debug = set()
        self.marked_onehot = set()
        self.part = None
        # Set by pypeline's SYN_TOOL(...) / --syn_tool; no C pragma yet.
        self.syn_tool_name = None
        self.inst_array_dict = dict()
        self.async_wires = set()
        self.input_wires = set()
        self.output_wires = set()
        self.clk_mhz = {}
        self.clk_group = {}  # dict[user_clk_wire]=clk_group_str

        # Clock crossing info
        self.clk_cross_var_info = {}  # var name -> clk cross var info
        self.arb_handshake_infos = set()

        # Temp working copy of current func logic, probably should not be here?
        self.existing_logic = Logic()  # Empty start for 'global namespace parsing'?

        # ~~~ C front end only (filled and read by C_TO_LOGIC/C_TO_FSM) ~~~
        # The file of parsed C code
        self.c_file_ast = None  # Single C file tree
        self.global_consts = {}  # name->global const info
        # The func body stuff here is hacky af damn
        #   State regs only needed for GET_MEM_H_LOGIC_LOOKUP?
        self.func_to_local_state_regs = {}  # funcname-> [state,reg,infos]
        #   Local vars needed since doing MAYBE global all names in func body before parsing decls?
        self.func_to_local_variables = {}  # funcname-> set(vars)
        # Special primitive funcs
        self.PrimFuncLogicLookupTable = {}  # Why table vs .is_prim_func on logic?
        self.func_mult_style = {}
        self.io_pairs = set()
        # Generated header info
        # FSM funcs
        self.func_fsm_header_included = set()
        # SINGLE inst funcs
        self.func_single_inst_header_included = set()

    def DEEPCOPY(self):
        # Fuck me how many times will I get caught with objects getting copied incorrectly?
        rv = ParserState()

        rv.FuncLogicLookupTable = {}
        for fname in self.FuncLogicLookupTable:
            rv.FuncLogicLookupTable[fname] = self.FuncLogicLookupTable[fname].DEEPCOPY()

        rv.PrimFuncLogicLookupTable = {}
        for fname in self.PrimFuncLogicLookupTable:
            rv.PrimFuncLogicLookupTable[fname] = rv.FuncLogicLookupTable[fname]

        rv.LogicInstLookupTable = {}
        for inst_name in self.LogicInstLookupTable:
            func_name = self.LogicInstLookupTable[inst_name].func_name
            rv_func_logic = rv.FuncLogicLookupTable[func_name]
            rv.LogicInstLookupTable[inst_name] = rv_func_logic

        rv.FuncToInstances = copy.deepcopy(self.FuncToInstances)
        rv.path_delay_funcs = copy.deepcopy(self.path_delay_funcs)
        rv.path_delay_measure_funcs = copy.deepcopy(self.path_delay_measure_funcs)
        rv.path_delay_frontier_funcs = copy.deepcopy(self.path_delay_frontier_funcs)

        rv.existing_logic = None
        if self.existing_logic is not None:
            rv.existing_logic = self.existing_logic.DEEPCOPY()

        rv.struct_to_field_type_dict = dict(self.struct_to_field_type_dict)
        rv.enum_info_dict = dict(self.enum_info_dict)
        rv.global_vars = dict(self.global_vars)
        rv.global_consts = dict(self.global_consts)
        rv.func_to_local_state_regs = dict(self.func_to_local_state_regs)
        rv.func_to_local_variables = dict(self.func_to_local_variables)

        rv.func_name_to_calls = dict(self.func_name_to_calls)
        rv.func_names_to_called_from = dict(self.func_names_to_called_from)

        rv.main_mhz = dict(self.main_mhz)
        rv.main_syn_mhz = dict(self.main_syn_mhz)
        rv.main_clk_group = dict(self.main_clk_group)
        rv.func_mult_style = dict(self.func_mult_style)
        rv.func_marked_wires = set(self.func_marked_wires)
        rv.func_fixed_latency = dict(self.func_fixed_latency)
        rv.auto_pipeline_rams = dict(self.auto_pipeline_rams)
        rv.func_marked_blackbox = set(self.func_marked_blackbox)
        rv.func_marked_no_add_io_regs = set(self.func_marked_no_add_io_regs)
        rv.func_marked_debug = set(self.func_marked_debug)
        rv.marked_onehot = set(self.marked_onehot)
        rv.part = self.part
        rv.syn_tool_name = self.syn_tool_name
        rv.io_pairs = set(self.io_pairs)
        rv.inst_array_dict = dict(self.inst_array_dict)
        rv.async_wires = set(self.async_wires)
        rv.input_wires = set(self.input_wires)
        rv.output_wires = set(self.output_wires)
        rv.clk_mhz = dict(self.clk_mhz)
        rv.clk_group = dict(self.clk_group)

        rv.clk_cross_var_info = dict(self.clk_cross_var_info)
        rv.arb_handshake_infos = set(self.arb_handshake_infos)

        rv.func_fsm_header_included = set(self.func_fsm_header_included)
        rv.func_single_inst_header_included = set(self.func_single_inst_header_included)

        return rv


# Global list of these in parser_state + lists per function in logic for locally delclared
class VariableInfo:
    def __init__(self):
        self.name = None
        self.type_name = None
        self.init = None  # c ast node or string filename
        self.resolved_const_str = None
        self.is_volatile = False
        self.is_static_local = False
        self.path_id = None  # Use associated path id, for clk cross
        self.used_in_funcs = set()  # Global id occurs in funcs
        # Global wire timing inside a pipelined function (AUTO_PIPELINE.GLOBAL_WIRE_TIMING):
        # "legacy" (C: read at earliest use, written when ready),
        # "aligned" (Pypeline Wire: read with the args, written with the return),
        # "volatile" (Pypeline Wire[T, VOLATILE]: read per consumer stage, written when ready).
        self.pipeline_timing = "legacy"


def RECURSIVE_FIND_MAIN_FUNCS(
    func_name, func_name_to_calls, func_names_to_called_from, main_funcs
):
    # Is it main?
    if func_name in main_funcs:
        return set([func_name])
    rv = set()
    # Where called from?
    if func_name in func_names_to_called_from:
        called_from_funcs = func_names_to_called_from[func_name]
        for called_from_func in called_from_funcs:
            rv |= RECURSIVE_FIND_MAIN_FUNCS(
                called_from_func,
                func_name_to_calls,
                func_names_to_called_from,
                main_funcs,
            )
    return rv


class ClkCrossVarInfo:
    def __init__(self):
        self.write_read_main_funcs = ([], [])
        self.write_read_funcs = (None, None)
        self.write_read_sizes = (None, None)
        self.flow_control = False
        self.is_part_of_arb_handshake = False


def INFER_CLOCK_DOMAINS(
    var_to_rw_main_funcs, var_to_read_func, var_to_write_func, parser_state
):
    """Propagate known MHz/group values to MAINs sharing globals or clock-crossing vars.

    Pass empty dicts for all three var_to_* arguments when called from the Python path
    (no C-style clock-crossing variables exist there).
    Returns var_to_rw_mhz_groups dict (needed by GET_CLK_CROSSING_INFO for object construction).
    """

    inferring = True
    var_to_rw_mhz_groups = {}
    while inferring:
        inferring = False
        # Do pass over all shared globals (same domain) trying to match domains
        for global_var, global_var_state_reg_info in parser_state.global_vars.items():
            # Shared globals only here
            if not GLOBAL_VAR_IS_SHARED(global_var, parser_state):
                continue
            # Cannot do inferring for async wires
            if global_var in parser_state.async_wires:
                continue
            # Read+write mains for func
            rw_mains = set()
            for used_in_func in global_var_state_reg_info.used_in_funcs:
                used_in_mains = RECURSIVE_FIND_MAIN_FUNCS(
                    used_in_func,
                    parser_state.func_name_to_calls,
                    parser_state.func_names_to_called_from,
                    list(parser_state.main_mhz.keys()),
                )
                rw_mains |= used_in_mains
            # Look for a first valid main func domain and try to match it to others
            valid_main = None
            valid_mhz = None
            valid_group = None
            for rw_main in rw_mains:
                if (
                    rw_main in parser_state.main_mhz
                    and parser_state.main_mhz[rw_main] is not None
                ):
                    valid_main = rw_main
                    valid_mhz = parser_state.main_mhz[rw_main]
                    valid_group = parser_state.main_clk_group[rw_main]
                    break
            if valid_main:
                for rw_main in rw_mains - set([valid_main]):
                    if (
                        rw_main not in parser_state.main_mhz
                        or parser_state.main_mhz[rw_main] is None
                    ) and (
                        rw_main not in parser_state.main_clk_group
                        or parser_state.main_clk_group[rw_main] is None
                        or parser_state.main_clk_group[rw_main] == valid_group
                    ):
                        if rw_main not in parser_state.func_marked_wires:
                            print(
                                "Matching clock domain: main function",
                                rw_main,
                                "based on shared global variable",
                                global_var,
                                "used with clock domain for main function",
                                valid_main,
                                "@",
                                valid_mhz,
                                "MHz, Group:",
                                valid_group,
                            )
                        parser_state.main_mhz[rw_main] = valid_mhz
                        parser_state.main_clk_group[rw_main] = valid_group
                        if (
                            rw_main not in parser_state.main_syn_mhz
                            or parser_state.main_syn_mhz[rw_main] is None
                        ):
                            parser_state.main_syn_mhz[rw_main] = valid_mhz
                        inferring = True
        # Make sure global wires infer first
        if inferring:
            continue

        # Do pass over all clk crossing vars trying to match domains
        for var_name in var_to_rw_main_funcs:
            # Skip temp during code gen disconnected write side
            if var_name not in var_to_write_func:
                continue
            read_main_funcs, write_main_funcs = var_to_rw_main_funcs[var_name]
            read_func_name = var_to_read_func[var_name]
            write_func_name = var_to_write_func[var_name]
            # Can only be one write side mhz,group
            write_mhz_group_tuples = set()
            write_mhz = None
            write_group = None
            for write_main_func in write_main_funcs:
                if write_main_func in parser_state.main_mhz:
                    write_mhz = parser_state.main_mhz[write_main_func]
                    write_group = parser_state.main_clk_group[write_main_func]
                    if write_mhz is not None:
                        write_mhz_group_tuples.add((write_mhz, write_group))
            if len(write_mhz_group_tuples) > 1:
                print(
                    f"WARNING: Cannot use clock crossing {var_name} written from multiple clock domains (mhz,group) {write_mhz_group_tuples}!"
                )
                inferring = True
            if len(write_mhz_group_tuples) == 1:
                write_mhz, write_group = list(write_mhz_group_tuples)[0]
            else:
                write_mhz = None
                write_group = None
            # Can only be one read side mhz,group
            read_mhz_group_tuples = set()
            read_mhz = None
            read_group = None
            for read_main_func in read_main_funcs:
                if read_main_func in parser_state.main_mhz:
                    read_mhz = parser_state.main_mhz[read_main_func]
                    read_group = parser_state.main_clk_group[read_main_func]
                    if read_mhz is not None:
                        read_mhz_group_tuples.add((read_mhz, read_group))
            if len(read_mhz_group_tuples) > 1:
                print(
                    f"WARNING: Cannot use clock crossing {var_name} read from multiple clock domains (mhz,group) {read_mhz_group_tuples}!"
                )
                inferring = True
            if len(read_mhz_group_tuples) == 1:
                read_mhz, read_group = list(read_mhz_group_tuples)[0]
            else:
                read_mhz = None
                read_group = None
            # print("var_name",var_name, "read_mhz", read_mhz, "read_main_funcs",read_main_funcs,"write_mhz",write_mhz, "write_main_funcs",write_main_funcs)
            # Infer from each side if not marked async
            if var_name not in parser_state.async_wires:
                for read_main_func in read_main_funcs:
                    # Infer freqs to match if possible and same groups
                    if (
                        read_main_func is not None
                        and parser_state.main_mhz[read_main_func] is None
                        and write_mhz is not None
                        and (read_group is None or read_group == write_group)
                    ):
                        print(
                            "Matching clock domain: read side main function",
                            read_main_func,
                            "based on clock crossing variable",
                            var_name,
                            "from clock domain with write side main function",
                            write_main_func,
                            "@",
                            write_mhz,
                            "MHz, Group:",
                            write_group,
                        )
                        read_mhz = write_mhz
                        parser_state.main_mhz[read_main_func] = read_mhz
                        read_group = write_group
                        parser_state.main_clk_group[read_main_func] = read_group
                        if (
                            read_main_func not in parser_state.main_syn_mhz
                            or parser_state.main_syn_mhz[read_main_func] is None
                        ):
                            parser_state.main_syn_mhz[read_main_func] = read_mhz
                        inferring = True
                for write_main_func in write_main_funcs:
                    if (
                        write_main_func is not None
                        and read_mhz is not None
                        and parser_state.main_mhz[write_main_func] is None
                        and (write_group is None or write_group == read_group)
                    ):
                        print(
                            "Matching clock domain: write side main function",
                            write_main_func,
                            "based on clock crossing variable",
                            var_name,
                            "from clock domain with read side main function",
                            read_main_func,
                            "@",
                            read_mhz,
                            "MHz, Group:",
                            read_group,
                        )
                        write_mhz = read_mhz
                        parser_state.main_mhz[write_main_func] = write_mhz
                        write_group = read_group
                        parser_state.main_clk_group[write_main_func] = write_group
                        if (
                            write_main_func not in parser_state.main_syn_mhz
                            or parser_state.main_syn_mhz[write_main_func] is None
                        ):
                            parser_state.main_syn_mhz[write_main_func] = write_mhz
                        inferring = True
            # Finally record mhz,group
            var_to_rw_mhz_groups[var_name] = (
                (read_mhz, read_group),
                (write_mhz, write_group),
            )

    return var_to_rw_mhz_groups


def CLK_CROSS_FUNC_TO_VAR_NAME(func_name):
    if "_READ" in func_name:
        var_name = func_name.split("_READ")[0]
    elif "_WRITE" in func_name:
        var_name = func_name.split("_WRITE")[0]

    return var_name


class ArbHandshakeInfo:
    def __init__(self):
        self.input_var_name = None
        self.input_clk_cross_var_info = None
        self.output_var_name = None
        self.output_clk_cross_var_info = None


class EnumInfo:
    def __init__(self):
        self.name = None
        self.id_to_int_val = OrderedDict()
        self.int_c_type = None


# Only needed for logic to skip func parsing so what hurts if its hacky?
def FUNC_IS_OP_OVERLOAD(func_name):
    if func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_"):
        return True
    elif func_name.startswith(UNARY_OP_LOGIC_NAME_PREFIX + "_"):
        return True
    return False


# Logic classification by origin: bit manipulation, bit math and memory functions
# generated from C headers, and array-in-struct wrapper types.

# Generated header file names and RAM function name suffixes
BIT_MANIP_HEADER_FILE = "bit_manip.h"
BIT_MATH_HEADER_FILE = "bit_math.h"
MEM_HEADER_FILE = "mem.h"
RAM_SP_RF = "RAM_SP_RF"
RAM_DP_RF = "RAM_DP_RF"


def C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state):
    r = rf"\w+_array(_[0-9]+)+_t"
    array_struct_types = FIND_REGEX_MATCHES(r, c_type)
    is_array_type = len(array_struct_types) == 1
    # print "c_type array struct?",c_type, is_array_type
    # TODO inspect type is defined and elem type exists?
    return is_array_type


def C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(array_struct_c_type, parser_state):
    s = array_struct_c_type[: len(array_struct_c_type) - 2]  # Remove last two chars _t
    toks = s.split("_array_")
    elem_t = toks[0]
    dims = toks[1].split("_")
    array_c_type = elem_t
    for dim in dims:
        array_c_type += "[" + dim + "]"
    # print "c_type array struct type to array type",array_struct_c_type, array_c_type
    return array_c_type


# Auto generated functions are defined in bit manip or math
# Built in functions used in this generated code are not auto generated
def IS_AUTO_GENERATED(logic):
    # print "?? ",logic.func_name, "is built in:", logic.is_c_built_in

    rv = (
        (IS_BIT_MANIP(logic) or IS_MEM(logic) or IS_BIT_MATH(logic))
        and not logic.is_c_built_in
    )  # Built in functions used in bitmanip+math generated code are not auto generated

    # print "?? IS_AUTO_GENERATED",rv

    return rv
    # and not logic.is_c_built_in ) or logic.func_name.startswith(


# Bit manip occurs in bit manip fiel and is not the built in generated code
def IS_BIT_MANIP(logic):
    if logic.is_new_style_bit_manip:
        return True
    return IS_BIT_MANIP_NAME(logic.func_name)


def IS_BIT_MANIP_NAME(name):
    _BIT_MANIP_PATTERNS = [
        # Bit select: uint32_15_0, int8_3_3, float_3_2, float_8_23_t_15_0
        r"uint[0-9]+_[0-9]+_[0-9]+",
        r"int[0-9]+_[0-9]+_[0-9]+",
        r"float_[0-9]+_[0-9]+",
        r"float_[0-9]+_[0-9]+_t_[0-9]+_[0-9]+",
        # Bit concat: uint32_uint32, int16_uint8
        r"u?int[0-9]+_u?int[0-9]+",
        # Const bit assign: uint64_uint16_2 (must come before bit_dup to avoid ambiguity)
        r"u?int[0-9]+_uint[0-9]+_[0-9]+",
        # Bit dup: uint4_4
        r"u?int[0-9]+_[0-9]+",
        # Rotate: rotl64_7, rotr32_3
        r"rotl[0-9]+_[0-9]+",
        r"rotr[0-9]+_[0-9]+",
        # Byte swap: bswap_32
        r"bswap_[0-9]+",
        # Array to uint: uint8_array8_be, uint8_array8_le
        r"uint[0-9]+_array[0-9]+_(?:be|le)",
        # Uint to array: uint64_8_be, uint64_8_le
        r"uint[0-9]+_[0-9]+_(?:be|le)",
    ]
    for pattern in _BIT_MANIP_PATTERNS:
        if re.fullmatch(pattern, name):
            return True
    # old style: defined in the bit manip header file
    # if not logic.is_new_style_bit_manip and hasattr(logic, "c_ast_node") and logic.c_ast_node is not None:
    #    rv = (
    #        str(logic.c_ast_node.coord).split(":")[0].endswith(BIT_MANIP_HEADER_FILE)
    #        and not logic.is_c_built_in
    #    )
    #    return rv
    return False


def IS_MEM(logic):
    # If logic is new bit manip style it wont have c_ast_node
    # since doesnt have actual definition location in code
    if logic.is_new_style_bit_manip:
        return False
    rv = (
        logic.ast_meta is not None
        and logic.ast_meta.src_file.endswith(MEM_HEADER_FILE)
        and not logic.is_c_built_in
    )
    return rv


def IS_BIT_MATH(logic):
    rv = (
        logic.ast_meta is not None
        and logic.ast_meta.src_file.endswith(BIT_MATH_HEADER_FILE)
        and not logic.is_c_built_in
    )
    return rv


def FUNC_NAME_INCLUDES_TYPES(logic):
    # Currently this is only needed for bitmanip and bit math
    rv = (
        IS_AUTO_GENERATED(logic)
        or logic.func_name.startswith(  # Excludes mem below
            VAR_REF_RD_FUNC_NAME_PREFIX
        )
        or logic.func_name.startswith(VAR_REF_ASSIGN_FUNC_NAME_PREFIX)
        or logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX)
        or logic.func_name.startswith(UNARY_OP_LOGIC_NAME_PREFIX)
        or logic.func_name.startswith(MUX_LOGIC_NAME)
    )

    # Cant be MEM since MEM mem name doesnt include types
    rv = rv and not IS_MEM(logic)

    return rv


def GET_MEM_NAME(logic):
    if logic.func_name.endswith("_" + RAM_SP_RF + "_0"):
        return RAM_SP_RF + "_0"
    elif logic.func_name.endswith("_" + RAM_SP_RF + "_1"):
        return RAM_SP_RF + "_1"
    elif logic.func_name.endswith("_" + RAM_SP_RF + "_2"):
        return RAM_SP_RF + "_2"
    elif logic.func_name.endswith("_" + RAM_DP_RF + "_0"):
        return RAM_DP_RF + "_0"
    elif logic.func_name.endswith("_" + RAM_DP_RF + "_1"):
        return RAM_DP_RF + "_1"
    elif logic.func_name.endswith("_" + RAM_DP_RF + "_2"):
        return RAM_DP_RF + "_2"
    else:
        print("GET_MEM_NAME for func", logic.func_name, "?")
        sys.exit(-1)
