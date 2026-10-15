#!/usr/bin/env python
import copy
import hashlib
import math
import os
import pickle
import re
import shlex
import sys
from collections import OrderedDict
from subprocess import PIPE, Popen

import C_TO_FSM
import LOGIC
import SYN
import VHDL
from pycparser import c_ast, c_parser
from utilities import (
    FIND_REGEX_MATCHES,
    GET_SHELL_CMD_OUTPUT,
    GET_TOOL_PATH,
    INDEX_BIT_WIDTH,
    REPO_ABS_DIR,
)


# Global default constants for inferring different VHDL implementations of operators
MULT_STYLE_INFERRED = "infer"
MULT_STYLE_FABRIC = "fabric"
MULT_STYLE = None
STRLEN_FUNC_NAME = "strlen"
TEMP_HACKY_C_AST_NODE_ID = True
# Suffix of the generated FSM version of a __clk() function, its header and its static
# output regs. Defined here, not in C_TO_FSM, because FSM_CLK_HEADER below reads it while
# this module is being imported.
FSM_EXT = "_FSM"


def GET_CPP_INCLUDES_LIST():  # -> list[str]: needs typing library?
    path_list = []
    # Include output directory, and other generated output dir
    if os.path.isdir(SYN.SYN_OUTPUT_DIRECTORY):
        path_list += ["-I" + SYN.SYN_OUTPUT_DIRECTORY]
    for header_dir in GENERATED_HEADER_DIRS:
        # Include the header dir - maybe future wanted idk?
        path_str = SYN.SYN_OUTPUT_DIRECTORY + "/" + header_dir
        path_list += ["-I" + path_str]
        if os.path.exists(path_str):
            # But also anything else? idk hacky
            for thing in os.listdir(path_str):
                # os.isdir wasnt working?
                thing_path = path_str + "/" + thing
                isdir = True
                try:
                    os.listdir(thing_path)
                except OSError:
                    isdir = False
                if isdir:
                    path_list += ["-I" + thing_path]
    # Also include src files in git root dir
    dir_path = REPO_ABS_DIR()

    # TODO: Temporarily include both paths to avoid breakage while still refactoring
    path_list += ["-I" + dir_path + "/"]
    path_list += ["-I" + dir_path + "/pipelinec/include/"]
    path_list += ["-I" + dir_path + "/include/"]

    # For now global __PIPELINEC__ define lives here
    path_list += ["-D__PIPELINEC__"]

    return path_list


# Checked when cpp is first run, not at import: Pypeline (.py) builds import this module
# (VHDL.py, RAW_VHDL.py and pipelinec use its helpers) but never preprocess C.
def REQUIRE_CPP():
    if GET_TOOL_PATH("cpp") is None:
        # TODO fall back to clang tools?
        raise Exception("'cpp' C preprocessor is not installed!")


# TAKEN FROM https://github.com/eliben/pycparser/blob/c5463bd43adef3206c79520812745b368cd6ab21/pycparser/__init__.py
def preprocess_file(filename, cpp_path="cpp", cpp_args=""):
    """Preprocess a file using cpp.
    filename:
    Name of the file you want to preprocess.
    cpp_path:
    cpp_args:
    Refer to the documentation of parse_file for the meaning of these
    arguments.
    When successful, returns the preprocessed file's contents.
    Errors from cpp will be printed out.
    """
    REQUIRE_CPP()
    path_list = [cpp_path]
    if isinstance(cpp_args, list):
        path_list += cpp_args
    elif cpp_args != "":
        path_list += [cpp_args]

    # Include output directory, and other generated output dir
    includes_list = GET_CPP_INCLUDES_LIST()
    path_list += includes_list
    # print(path_list)

    # Finally the file
    path_list += [filename]

    try:
        # Note the use of universal_newlines to treat all newlines
        # as \n for Python's purpose
        #
        pipe = Popen(path_list, stdout=PIPE, universal_newlines=True)
        text = pipe.communicate()[0]
    except OSError as e:
        raise RuntimeError(
            "Unable to invoke 'cpp'.  "
            + "Make sure its path was passed correctly\n"
            + ("Original error: %s" % e)
        )
    except Exception as e:
        print("Something went wrong preprocessing:")
        print("File:", filename)
        raise e
    # print(text)
    return text


def preprocess_text(text, cpp_path="cpp"):
    """Preprocess a file using cpp.
    filename:
        Name of the file you want to preprocess.
    cpp_path:
    cpp_args:
        Refer to the documentation of parse_file for the meaning of these
        arguments.
    When successful, returns the preprocessed file's contents.
    Errors from cpp will be printed out.
    """
    REQUIRE_CPP()

    path_list = [cpp_path]

    # Include output directory, and other generated output dir
    includes_list = GET_CPP_INCLUDES_LIST()
    path_list += includes_list

    # Finally read from std in
    path_list += ["-"]  # TO read from std in

    try:
        # Note the use of universal_newlines to treat all newlines
        # as \n for Python's purpose
        #
        # print path_list
        pipe = Popen(path_list, stdout=PIPE, stdin=PIPE, universal_newlines=True)
        # Send in C text and get output
        # print "cpping..."
        # print "TEXT:",text
        text = pipe.communicate(input=text)[0]
    except OSError as e:
        raise RuntimeError(
            "Unable to invoke 'cpp'.  "
            + "Make sure its path was passed correctly\n"
            + ("Original error: %s" % e)
        )

    return text


# Use cpp -MM -MG to parse the #include tree and get all files
# that need to be code gen'd again
# DOES NOT INCLUDE to-be-generated missing files
def get_included_files(c_filename):
    REQUIRE_CPP()
    includes_list = GET_CPP_INCLUDES_LIST()
    includes_text = " ".join(includes_list)
    cmd = "cpp -MM -MG " + includes_text + " " + c_filename
    # print(cmd)
    include_str = GET_SHELL_CMD_OUTPUT(cmd)
    # print("include_str",include_str)
    include_str = include_str.replace("\\\n", " ")

    """
main.o: main.c examples/aws-fpga-dma/aws_fpga_dma.c \
 examples/aws-fpga-dma/../../axi.h examples/aws-fpga-dma/../../uintN_t.h \
 examples/aws-fpga-dma/dma_msg_hw.c examples/aws-fpga-dma/dma_msg.h \
 examples/aws-fpga-dma/work_hw.c examples/aws-fpga-dma/work.h \
 in_msg_clock_crossing.h out_msg_clock_crossing.h
  """
    # shlex.split('-o 1 --long "Some long string"')
    # ['-o', '1', '--long', 'Some long string']
    toks = shlex.split(include_str)
    # print toks[1:]
    files = toks[1:]
    return set(files)


def casthelp(arg):
    try:
        print(arg)
        return
    except:
        pass

    try:
        arg.show()
        return
    except:
        pass

    try:
        print(dir(arg))
        return
    except:
        pass


_other_partial_logic_cache = {}


def BUILD_LOGIC_AS_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    parser_state,
    containing_func_logic,
):
    # Cache the other partial logic
    cache_tok = partially_complete_logic.func_name
    # SHOULDNT NEED INPUT TYPES SINCE FUNC NAME IS UNIQUE

    if cache_tok in _other_partial_logic_cache:
        other_partial_logic = _other_partial_logic_cache[cache_tok]
    else:
        out_dir = SYN.GET_OUTPUT_DIRECTORY(partially_complete_logic)
        # Get C code depending on function
        # print "BUILD_LOGIC_AS_C_CODE"
        # print "partially_complete_logic.func_name",partially_complete_logic.func_name
        # print "containing_func_logic.func_name",containing_func_logic.func_name
        # print "=================================================================="
        if partially_complete_logic.func_name.startswith(
            LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_"
        ):
            c_code_text = GET_VAR_REF_ASSIGN_C_CODE(
                partially_complete_logic_local_inst_name,
                partially_complete_logic,
                containing_func_logic,
                out_dir,
                parser_state,
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX + "_"
        ):
            c_code_text = GET_VAR_REF_RD_C_CODE(
                partially_complete_logic_local_inst_name,
                partially_complete_logic,
                containing_func_logic,
                out_dir,
                parser_state,
            )
        elif partially_complete_logic.func_name.startswith(LOGIC.CAST_FUNC_NAME_PREFIX + "_"):
            c_code_text = GET_CAST_C_CODE(
                partially_complete_logic, containing_func_logic, out_dir, parser_state
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.UNARY_OP_NEGATE_NAME
        ):
            c_code_text = GET_UNARY_OP_NEGATE_C_CODE(
                partially_complete_logic, out_dir, containing_func_logic, parser_state
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MULT_NAME
        ) or partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_INFERRED_MULT_NAME
        ):
            c_code_text = GET_BIN_OP_MULT_C_CODE(
                partially_complete_logic, out_dir, parser_state
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_DIV_NAME
        ):
            c_code_text = GET_BIN_OP_DIV_C_CODE(
                partially_complete_logic, out_dir, parser_state
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MOD_NAME
        ):
            c_code_text = GET_BIN_OP_MOD_C_CODE(
                partially_complete_logic, out_dir, parser_state
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_GTE_NAME
        ):
            c_code_text = GET_BIN_OP_GT_GTE_C_CODE(
                partially_complete_logic, out_dir, op_str=">="
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_GT_NAME
        ):
            c_code_text = GET_BIN_OP_GT_GTE_C_CODE(
                partially_complete_logic, out_dir, op_str=">"
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_LTE_NAME
        ):
            c_code_text = GET_BIN_OP_LT_LTE_C_CODE(
                partially_complete_logic, out_dir, op_str="<="
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_LT_NAME
        ):
            c_code_text = GET_BIN_OP_LT_LTE_C_CODE(
                partially_complete_logic, out_dir, op_str="<"
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_PLUS_NAME
        ):
            c_code_text = GET_BIN_OP_PLUS_C_CODE(
                partially_complete_logic, out_dir
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MINUS_NAME
        ):
            c_code_text = GET_BIN_OP_MINUS_C_CODE(
                partially_complete_logic, out_dir
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME
        ):
            c_code_text = GET_BIN_OP_SL_C_CODE(
                partially_complete_logic_local_inst_name,
                partially_complete_logic,
                out_dir,
                containing_func_logic,
                parser_state,
            )
        elif partially_complete_logic.func_name.startswith(
            LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SR_NAME
        ):
            c_code_text = GET_BIN_OP_SR_C_CODE(
                partially_complete_logic_local_inst_name,
                partially_complete_logic,
                out_dir,
                containing_func_logic,
                parser_state,
            )
        elif partially_complete_logic.func_name.startswith(LOGIC.ONE_HOT_EQ_LOGIC_NAME):
            c_code_text = GET_ONE_HOT_EQ_C_CODE(
                partially_complete_logic_local_inst_name,
                partially_complete_logic,
                containing_func_logic,
                parser_state,
            )
        else:
            print(
                "How to BUILD_LOGIC_AS_C_CODE for",
                partially_complete_logic.func_name,
                "?",
            )
            sys.exit(-1)

        # Use the c code to get the logic
        partially_complete_logic.c_code_text = c_code_text

        # print("...",partially_complete_logic.func_name,flush=True)
        # print(c_code_text,flush=True)

        # And read logic
        # print "partially_complete_logic.
        fake_filename = partially_complete_logic.func_name + ".c"
        # print "fake_filename",fake_filename
        # Parse and return the only func def
        func_name = partially_complete_logic.func_name
        # print "... as C code...",partially_complete_logic.func_name

        preprocessed_c_code_text = preprocess_text(c_code_text)
        sw_func_name_2_logic = (
            GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(
                preprocessed_c_code_text, parser_state
            )
        )
        # Merge into existing
        for sw_func_name in sw_func_name_2_logic:
            # print "sw_func_name",sw_func_name
            if sw_func_name not in parser_state.FuncLogicLookupTable:
                parser_state.FuncLogicLookupTable[sw_func_name] = sw_func_name_2_logic[
                    sw_func_name
                ]

        FuncLogicLookupTable = GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(
            c_code_text, fake_filename, parser_state, parse_body=True
        )

        # Get the other partial logic if it exists
        if func_name not in FuncLogicLookupTable:
            print("I cant find func name", func_name, "in the C code so far")
            print("c_code_text")
            print(c_code_text)
            print("=========")
            print("sw_func_name_2_logic")
            print(sw_func_name_2_logic)
            print("CHECK CODE PARSING autogenerated stuff?")
            sys.exit(-1)
        other_partial_logic = FuncLogicLookupTable[func_name]
        # CACHE THIS
        _other_partial_logic_cache[cache_tok] = other_partial_logic

    # Also needs built in flag from partial logic
    other_partial_logic.is_c_built_in = partially_complete_logic.is_c_built_in
    # Fix cast ndoe too
    other_partial_logic.ast_meta = partially_complete_logic.ast_meta

    # Combine two partial logics
    # print "partially_complete_logic.c_ast_node.coord", partially_complete_logic.c_ast_node.coord
    # print "other_partial_logic.c_ast_node.coord", other_partial_logic.c_ast_node.coord
    partially_complete_logic.MERGE_COMB_LOGIC(other_partial_logic)
    # print "merged_logic.c_ast_node.coord", merged_logic.c_ast_node.coord
    # print "merged_logic.func_name", merged_logic.func_name

    return partially_complete_logic


def GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(
    text, fake_filename, parser_state, parse_body
):
    # Build function name to logic from func defs from files
    FuncLogicLookupTable = dict(
        parser_state.FuncLogicLookupTable
    )  #### Was deep copy Uh need this copy so bit manip/math funcs not directly in C text are accumulated over time wtf? TODO: Fix
    func_defs = GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename)

    for func_def in func_defs:
        if parse_body:
            print("... found:", func_def.decl.name, flush=True)
        # Each func def produces a single logic item
        parser_state.existing_logic = None
        logic = C_AST_FUNC_DEF_TO_LOGIC(func_def, parser_state, parse_body)
        FuncLogicLookupTable[logic.func_name] = logic

    return FuncLogicLookupTable


# WHY CAN I NEVER REMEMBER {} IS NOT IMMUTABLE (AKA needs copy operator)


# Node needs context for variable renaming over time, can give existing logic
# _node_record = {}
def C_AST_NODE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # Cover logic as far up in c ast tree as possible
    # Each node will have function to deal with node type:
    # which may or may not recursively call this function.

    # C_AST nodes can represent pure structure logic

    if type(c_ast_node) == c_ast.Compound:
        return C_AST_COMPOUND_TO_LOGIC(c_ast_node, prepend_text, parser_state)
    elif type(c_ast_node) == c_ast.Decl:
        return C_AST_DECL_TO_LOGIC(c_ast_node, prepend_text, parser_state)
    elif type(c_ast_node) == c_ast.DeclList:
        return C_AST_DECL_LIST_TO_LOGIC(c_ast_node, prepend_text, parser_state)
    elif type(c_ast_node) == c_ast.If:
        return C_AST_IF_TO_LOGIC(c_ast_node, prepend_text, parser_state)
    elif type(c_ast_node) == c_ast.Return:
        return C_AST_RETURN_TO_LOGIC(c_ast_node, prepend_text, parser_state)
    elif type(c_ast_node) == c_ast.FuncCall:
        return C_AST_FUNC_CALL_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.BinaryOp:
        return C_AST_BINARY_OP_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.UnaryOp:
        return C_AST_UNARY_OP_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.Constant:
        return C_AST_CONSTANT_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.ID:
        return C_AST_ID_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.StructRef or type(c_ast_node) == c_ast.ArrayRef:
        return C_AST_REF_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.Assignment:
        return C_AST_ASSIGNMENT_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.For:
        return C_AST_FOR_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.While:
        return C_AST_WHILE_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.Cast:
        return C_AST_CAST_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.Pragma:
        return C_AST_PRAGMA_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.EmptyStatement:
        print("Unecessary empty statement - extra ';' ?", c_ast_node.coord)
        sys.exit(-1)
    elif type(c_ast_node) == c_ast.TernaryOp:
        return C_AST_TERNARY_OP_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif C_AST_NODE_IS_COMPOUND_NULL(c_ast_node):
        return C_AST_COMPOUND_NULL_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    elif type(c_ast_node) == c_ast.InitList:
        return C_AST_INIT_LIST_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    else:
        # start here
        print("Animal Collective - The Purple Bottle")
        print("Cannot parse c ast node to logic:", c_ast_node.coord)
        print(c_ast_node)
        raise Exception("C ast node cannot be parsed to logic")


def C_AST_PRAGMA_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    toks = c_ast_node.string.split(" ")

    # FEEDBACK WIRES
    if toks[0] == "FEEDBACK":
        var_name = toks[1]
        parser_state.existing_logic.feedback_vars[var_name] = None
        # Clears all known aliases/drivers of this wire
        # (clears default null assignment, all aliases, so read comes from feedback wire)
        parser_state.existing_logic.REMOVE_VAR_WIRE_DRIVE_HISTORY(var_name)

    # User instance name for next function call
    if toks[0] == "INST_NAME":
        next_inst_name = toks[1]
        if len(toks) > 2:
            index_toks = toks[2:]
            for index_tok in index_toks:
                # Should be var name, eval as const, like array ref RESOLVE_CONST_ARRAY_REF_TO_LOGIC
                # print("index_tok",index_tok)
                res = re.split(r"\.|\[|\]", index_tok)
                index_ref_roks = tuple(res)
                # print("index_ref_roks",index_ref_roks)
                const_driving_wire = RESOLVE_REF_TOKS_TO_CONSTANT_WIRE(
                    index_ref_roks, c_ast_node, prepend_text, parser_state
                )
                if const_driving_wire is None:
                    raise Exception(
                        f"Cannot use non constant values in instance names! {index_tok}"
                    )
                # Get value from this constant
                maybe_digit = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                    const_driving_wire, parser_state.existing_logic, parser_state
                )
                next_inst_name += "[" + maybe_digit + "]"
        # print("next_inst_name",next_inst_name)
        parser_state.existing_logic.next_user_inst_name = next_inst_name

    # Use given file with raw VHDL init for variabel
    if toks[0] == "VAR_VHDL_INIT":
        var_name = toks[1]
        init_file = toks[2]
        var_info = parser_state.existing_logic.state_regs[var_name]
        var_info.init = init_file

    # Name to mark debug for
    if toks[0] == "MARK_DEBUG":
        var_name = toks[1]
        parser_state.existing_logic.debug_names.add(var_name)

    # Multi cycle paths
    if toks[0] == "MULTI_CYCLE":
        mcp_tup = (toks[1], toks[2], toks[3])
        parser_state.existing_logic.mcp_tuples.add(mcp_tup)

    # Auto-pipelined submodule instances
    if toks[0] == "AUTOPIPELINE":
        # Bare pragma: unconstrained (the sweep picks the latency).
        # `#pragma AUTOPIPELINE N`: fixed latency N (N inserted registers).
        # -1 is kept as the legacy spelling of unconstrained.
        constraint = LOGIC.AutoPipelineLatency()
        if len(toks) > 1 and not toks[1].startswith("/"):
            try:
                latency = int(toks[1])
            except ValueError:
                raise Exception(
                    f"#pragma AUTOPIPELINE {toks[1]}: expected an integer "
                    "latency (number of inserted registers)"
                )
            if latency >= 0:
                constraint = LOGIC.AutoPipelineLatency(latency=latency)
            elif latency != -1:
                raise Exception(
                    f"#pragma AUTOPIPELINE {latency}: latency must be >= 0"
                )
        parser_state.existing_logic.next_func_call_auto_pipeline_latency = constraint

    return parser_state.existing_logic


def C_AST_RETURN_TO_LOGIC(c_ast_return, prepend_text, parser_state):
    # Check for double return
    if LOGIC.RETURN_WIRE_NAME in parser_state.existing_logic.wire_driven_by:
        print(
            "What, more than one return? Come on eh don't make me sad...",
            str(c_ast_return.coord),
        )
        sys.exit(-1)

    # Return is just connection to wire
    # Since each logic blob is a C function
    # only one return per function allowed
    # connect variable wire name to "return"
    driven_wire_names = [LOGIC.RETURN_WIRE_NAME]
    prepend_text = ""
    return_logic = C_AST_NODE_TO_LOGIC(
        c_ast_return.expr, driven_wire_names, prepend_text, parser_state
    )

    parser_state.existing_logic = return_logic
    # Connect the return logic node to this one
    return return_logic


def CONNECT_FINAL_STATE_WIRES(prepend_text, parser_state, c_ast_node):
    # Final state wires are using made C AST location == func def
    # So need extra way to distinguish multiple things at same AST location
    # Use prepend text like IF true false branches

    # Tie all state regs to state wire
    # Collpase struct ref hierarchy to get top most orig wire name nodes
    for state_reg in parser_state.existing_logic.state_regs:
        # Read ref_toks takes care of it
        ref_toks = (state_reg,)
        new_prepend_text = state_reg + "_" + prepend_text
        connect_logic = C_AST_REF_TOKS_TO_LOGIC(
            ref_toks, c_ast_node, [state_reg], new_prepend_text, parser_state
        )
        parser_state.existing_logic.MERGE_COMB_LOGIC(connect_logic)

    # Tie feedback wires to var like state regs
    for feedback_var in parser_state.existing_logic.feedback_vars:
        ref_toks = (feedback_var,)
        new_prepend_text = feedback_var + "_" + prepend_text
        connect_logic = C_AST_REF_TOKS_TO_LOGIC(
            ref_toks, c_ast_node, [feedback_var], new_prepend_text, parser_state
        )
        parser_state.existing_logic.MERGE_COMB_LOGIC(connect_logic)

    return parser_state.existing_logic


def GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref):
    if type(c_ast_structref.name) is c_ast.StructRef:
        names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref.name)
        names_list = names_list + [c_ast_structref.field.name]
        return names_list
    elif type(c_ast_structref.name) is c_ast.ID:
        name_wire = str(c_ast_structref.name.name)
        names_list = [name_wire, c_ast_structref.field.name]
        return names_list
    elif type(c_ast_structref.name) is c_ast.ArrayRef:
        names_list = GET_NAMES_LIST_FROM_ARRAYREF(c_ast_structref.name)
        names_list = names_list + [c_ast_structref.field.name]
        return names_list
    else:
        print("Need entry in GET_NAMES_LIST_FROM_STRUCTREF", end=" ")
        casthelp(c_ast_structref.name)
        sys.exit(-1)

    return rv


def GET_BASE_VARIABLE_NAME_FROM_STRUCTREF(c_ast_structref):
    names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
    return names_list[0]


def C_AST_REF_TOK_IS_CONST(ref_tok):
    # Constant array ref
    if type(ref_tok) is int:
        return True
    # Sanity check
    elif (type(ref_tok) is str) and (ref_tok == "*"):
        print("Using string variable ref tok when not aware, fix.")
        sys.exit(-1)
    # ID or struct ref
    elif type(ref_tok) is str:
        return True
    # Must be variable array ref
    else:
        return False


def C_AST_REF_TOKS_ARE_CONST(ref_toks):
    for ref_tok in ref_toks:
        if not C_AST_REF_TOK_IS_CONST(ref_tok):
            return False
    return True


def C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(
    prepend_text, ref_toks, c_ast_node, parser_state
):
    existing_logic = parser_state.existing_logic
    orig_var_name = ref_toks[0]
    id_str = ""
    for i in range(0, len(ref_toks)):
        ref_tok = ref_toks[i]
        # Constant array ref
        if type(ref_tok) is int:
            id_str += "[" + str(ref_tok) + "]"
        # ID or struct ref
        elif type(ref_tok) is str:
            if i == 0:
                # Base ID
                id_str += ref_tok
            else:
                # Struct ref
                id_str += "." + ref_tok
        # Variable array ref
        elif not C_AST_REF_TOK_IS_CONST(ref_tok):
            id_str += "[*]"
        else:
            print("Whats this ref eh?", ref_tok, c_ast_node.coord)
            sys.exit(-1)

    # Alias will include location in src
    coord_str = C_AST_NODE_COORD_STR(c_ast_node)
    # Base name
    alias_base = prepend_text + id_str + "_" + coord_str

    # Return base without number appended?
    if orig_var_name not in existing_logic.wire_aliases_over_time:
        return alias_base

    # Aliases exist, maybe start i at last one
    aliases = existing_logic.wire_aliases_over_time[orig_var_name]
    if alias_base not in aliases:
        return alias_base

    # print("aliases",aliases,alias_base,alias_base not in aliases)
    # aliases = existing_logic.wire_aliases_over_time[orig_var_name]
    last_alias = aliases[len(aliases) - 1]
    # print(aliases,"last_alias",last_alias)
    maybe_last_digit = last_alias.replace(alias_base + "_", "")
    if maybe_last_digit.isdigit():
        last_num = int(maybe_last_digit)
        i = last_num + 1
    else:
        i = 0
    alias = alias_base + "_" + str(i)
    while alias in aliases:
        i = i + 1
        alias = alias_base + "_" + str(i)
    return alias


def GET_MOST_RECENT_ALIAS(logic, orig_var_name):
    if orig_var_name in logic.wire_aliases_over_time:
        aliases = logic.wire_aliases_over_time[orig_var_name]
        last_alias = aliases[len(aliases) - 1]
        return last_alias
    else:
        return orig_var_name


def GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(ref_toks, c_ast_node, parser_state):
    # print "=="
    # print "ref_toks",ref_toks
    var_dim_ref_tok_indices = []
    var_dims = []
    var_dim_iter_types = []
    curr_ref_toks = ref_toks[:]
    # need at last 2 ref toks, array cant be in pos 0
    while len(curr_ref_toks) >= 2:
        # print "=="
        # print "curr_ref_toks",curr_ref_toks
        last_index = len(curr_ref_toks) - 1
        last_tok = curr_ref_toks[last_index]
        if not C_AST_REF_TOK_IS_CONST(last_tok):
            # is variable array dim
            # Pop off this last entry
            curr_ref_toks = curr_ref_toks[:last_index]
            # Get the array type
            c_array_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(
                curr_ref_toks, c_ast_node, parser_state
            )
            # Sanity check
            if not LOGIC.C_TYPE_IS_ARRAY(c_array_type):
                print("Oh no not an array?", c_array_type)
                sys.exit(-1)
            # Get the dims from the array
            # print "c_array_type",c_array_type
            elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
            # print "elem_type",elem_type
            # print "dims",dims
            # Want last dim?
            """
      last_dim = dims[len(dims)-1]
      # Save
      var_dim_ref_tok_indices.append(last_index)
      var_dims.append(last_dim)   
      var_dim_iter_types.append("uint" + str(int(math.ceil(math.log(last_dim,2)))) + "_t")
      """
            # Or wait want first dim?
            first_dim = dims[0]
            # Save
            var_dim_ref_tok_indices.append(last_index)
            var_dims.append(first_dim)
            var_dim_iter_types.append("uint" + str(INDEX_BIT_WIDTH(first_dim)) + "_t")
        else:
            # Pop off this entry
            curr_ref_toks = curr_ref_toks[:last_index]
            # Thats it

    # Have been reversed
    var_dim_ref_tok_indices.reverse()
    var_dims.reverse()
    var_dim_iter_types.reverse()

    # print "var_dim_ref_tok_indices, var_dims, var_dim_iter_types",var_dim_ref_tok_indices, var_dims, var_dim_iter_types

    return var_dim_ref_tok_indices, var_dims, var_dim_iter_types


def MAYBE_GLOBAL_DECL_TO_LOGIC(maybe_global_name, parser_state, is_lhs_assign):
    # Immediately not if early data from ID occurance says its local
    if parser_state.existing_logic.func_name in parser_state.func_to_local_variables:
        if (
            maybe_global_name
            in parser_state.func_to_local_variables[
                parser_state.existing_logic.func_name
            ]
        ):
            return parser_state.existing_logic
    else:
        # raise Exception("Why looking for globals inside func?", parser_state.existing_logic.func_name)
        # Assume wont be global since not in user functions?
        # print("Missing local vars for func", parser_state.existing_logic.func_name)
        return parser_state.existing_logic

    # Catch read only global regs
    # If has same name as global and hasnt been declared as (local) variable already
    if (
        not is_lhs_assign
        and (maybe_global_name in parser_state.global_vars)
        and (maybe_global_name not in parser_state.existing_logic.variable_names)
    ):
        # Copy info into existing_logic read_only_global_regs
        parser_state.existing_logic.read_only_global_wires[maybe_global_name] = (
            parser_state.global_vars[maybe_global_name]
        )
        parser_state.existing_logic.wire_to_c_type[maybe_global_name] = (
            parser_state.global_vars[maybe_global_name].type_name
        )
        parser_state.existing_logic.variable_names.add(maybe_global_name)

    # Regular globals (state regs written in func)
    # If has same name as global and hasnt been declared as (local) variable already
    if maybe_global_name in parser_state.global_vars:
        # Promote read only to local static
        read_only_promote_to_write = (
            is_lhs_assign
            and maybe_global_name in parser_state.existing_logic.read_only_global_wires
        )
        if read_only_promote_to_write:
            # Remove read only entry
            parser_state.existing_logic.read_only_global_wires.pop(maybe_global_name)
        # Copy global state reg to local if promoting or seeing for first time
        if (
            read_only_promote_to_write
            or maybe_global_name not in parser_state.existing_logic.variable_names
        ):
            # Copy info into existing_logic
            parser_state.existing_logic.state_regs[maybe_global_name] = (
                parser_state.global_vars[maybe_global_name]
            )
            parser_state.existing_logic.wire_to_c_type[maybe_global_name] = (
                parser_state.global_vars[maybe_global_name].type_name
            )
            parser_state.existing_logic.variable_names.add(maybe_global_name)
            # Record using globals
            if not parser_state.existing_logic.state_regs[
                maybe_global_name
            ].is_volatile:
                parser_state.existing_logic.uses_nonvolatile_state_regs = True
                # print "rv.func_name",rv.func_name, rv.uses_nonvolatile_state_regs

    # Constant global values
    if (maybe_global_name in parser_state.global_consts) and (
        maybe_global_name not in parser_state.existing_logic.variable_names
    ):
        # Get info
        info = parser_state.global_consts[maybe_global_name]
        parser_state.existing_logic.wire_to_c_type[maybe_global_name] = info.type_name
        parser_state.existing_logic.variable_names.add(maybe_global_name)
        # Do constant logic from init
        lhs_ref_toks = (maybe_global_name,)
        parser_state.existing_logic = C_AST_DECL_TO_LOGIC(info.lhs, "", parser_state)

    # Sanity check not using clock cross globals?
    # TODO: for other things like brams declared but not directly used?
    if maybe_global_name in parser_state.clk_cross_var_info:
        print(
            "Looks like you are using a clock crossing variable '",
            maybe_global_name,
            "' directly instead of with READ and WRITE functions?",
        )
        sys.exit(-1)

    return parser_state.existing_logic


# If this works great, if not ill be so sad
# Sadness forever


def C_AST_ASSIGNMENT_TO_LOGIC(
    c_ast_assignment, driven_wire_names, prepend_text, parser_state
):
    # Assume lhs can be evaluated as ref?
    lhs_ref_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(
        c_ast_assignment.lvalue, prepend_text, parser_state
    )
    lhs_orig_var_name = lhs_ref_toks[0]

    FuncLogicLookupTable = parser_state.FuncLogicLookupTable
    existing_logic = parser_state.existing_logic

    parser_state.existing_logic = LOGIC.Logic()
    if existing_logic is not None:
        parser_state.existing_logic = existing_logic
    # BOTH LHS and RHS CAN BE EXPRESSIONS!!!!!!
    # BUT LEFT SIDE MUST RESULT IN VARIABLE ADDRESS / wire?
    # ^^^^^^^^^^^^^^^^^

    # Special handling of writing to globals
    # Why is this needed - special is_lhs_assign that doesnt happen elsewhere? sigh...
    parser_state.existing_logic = MAYBE_GLOBAL_DECL_TO_LOGIC(
        lhs_orig_var_name, parser_state, is_lhs_assign=True
    )

    # Sanity check
    if lhs_orig_var_name not in parser_state.existing_logic.wire_to_c_type:
        print(
            "It looks like variable",
            lhs_orig_var_name,
            "isn't declared?",
            c_ast_assignment.coord,
        )
        sys.exit(-1)
    lhs_base_type = parser_state.existing_logic.wire_to_c_type[lhs_orig_var_name]
    const_lhs = C_AST_REF_TOKS_ARE_CONST(lhs_ref_toks)

    if not const_lhs:
        # TODO
        if c_ast_assignment.op != "=":
            print(
                f"TODO: Unsupported assignment {c_ast_assignment.op} on non constant destination/left hand side!",
                c_ast_assignment.coord,
            )
            sys.exit(-1)

        # Variable references write to larger "sized" references then constant references
        # dims=A,B,C
        # x[i] = 0   writes the entire 'x' array  (aka reads from anywhere in 'x' depend on this)
        # x[0][i] writes all of x[0] which is of type array[B]
        # x[i][0] writes all of x[ ][0]?? which is of type array[A]  ???
        # x[0][1][i] writes all of x[0][1] which is of type array[C]
        # x[i][0][j] writes all of x[ ][0][ ] which is of type x_type[A][C] ?
        # y[k].x[i][0][j]  = rhs
        #
        # The RHS value is 'written' by muxing it into that portion of the array
        # First ready the entire struct portion that could be written
        # The full range of references is a sum of reading a bunch of constants
        # Build list of ref toks
        # [y,0,x,0,0,0]
        # [y,0,x,0,0,1]
        # [y,0,x,1,0,0]
        # ...
        # Get list of variable dims
        (
            var_dim_ref_tok_indices,
            var_dims,
            var_dim_iter_types,
        ) = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(
            lhs_ref_toks, c_ast_assignment.lvalue, parser_state
        )

        # print "lhs_ref_toks",lhs_ref_toks
        # print "var_dims",var_dims
        # print "var_dim_ref_tok_indices",var_dim_ref_tok_indices

        # Do the nest loops to create all possible ref toks
        ref_toks_set = set()

        for orig_ref_tok_i in range(0, len(lhs_ref_toks)):
            orig_ref_tok = lhs_ref_toks[orig_ref_tok_i]
            # Start a new return set()
            new_ref_toks_set = set()
            # Is this orig ref tok variable?
            if not C_AST_REF_TOK_IS_CONST(orig_ref_tok):
                # Variable
                # What dimension is this variable
                # Sanity check
                if orig_ref_tok_i not in var_dim_ref_tok_indices:
                    print("Wait this ref tok isnt variable?", orig_ref_tok)
                    sys.exit(-1)
                # Get index of this var dim is list of var dims
                var_dim_i = var_dim_ref_tok_indices.index(orig_ref_tok_i)
                var_dim = var_dims[var_dim_i]
                # For each existing ref tok append that with all possible dim values
                for ref_toks in ref_toks_set:
                    for dim_val in range(0, var_dim):
                        new_ref_toks = ref_toks + (dim_val,)
                        new_ref_toks_set.add(new_ref_toks)
            else:
                # Constant just append this constant value to all ref toks in list
                for ref_toks in ref_toks_set:
                    new_ref_toks = ref_toks + (orig_ref_tok,)
                    new_ref_toks_set.add(new_ref_toks)
                # Or add as base element
                if len(ref_toks_set) == 0:
                    new_ref_toks_set.add((orig_ref_tok,))

            # Next iteration save new ref toks
            ref_toks_set = set(new_ref_toks_set)

        # Reduce that list of refs
        reduced_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(
            ref_toks_set, c_ast_assignment.lvalue, parser_state
        )
        sorted_reduced_ref_toks_set = sorted(
            reduced_ref_toks_set
        )  # To establish an order for name strings

        ##########################################
        # These refs are input to write funciton
        #   Do regular logic writing to 'base' variable (in C this time?)
        # Writing to this base variable is mux between different copies of base var?
        # ^^^^^^^^^^^^^^^^^^^^ NOOOOOOOO dont want to be muxing giant base var when only writing a portion
        #
        # IF
        # x[ ][0][ ] which is of type x_type[A][C]
        # What is the type driven by y[k].name[i][0][j]
        #     is it    y_name_type[A][B][D] ????
        # Assign all the ref toks into a type like y_name_type[A][B][D]
        # Make copyies of that val and make constant assingments into it
        # Then nmux the copies type based on values of k,i,j
        # Output of write function is like y_name_type[A][B][D]
        lhs_elem_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(
            lhs_ref_toks, c_ast_assignment.lvalue, parser_state
        )

        # Build C array type using variable dimensions
        lhs_array_type = None
        # Elem might be array so try to break apart
        if LOGIC.C_TYPE_IS_ARRAY(lhs_elem_c_type):
            # Innner element is constant sized array, has those dims, then variable ones
            (
                lhs_array_elem_c_type,
                lhs_array_elem_dims,
            ) = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(lhs_elem_c_type)
            lhs_array_type = lhs_array_elem_c_type
            for var_dim in var_dims:
                lhs_array_type += "[" + str(var_dim) + "]"
            for lhs_array_elem_dim in lhs_array_elem_dims:
                lhs_array_type += "[" + str(lhs_array_elem_dim) + "]"
        else:
            # Innner element is not an array, just variable dims
            lhs_array_type = lhs_elem_c_type
            for var_dim in var_dims:
                lhs_array_type += "[" + str(var_dim) + "]"

        # print "lhs_ref_toks",lhs_ref_toks
        # print "var_dim_ref_tok_indices, var_dims, var_dim_iter_types",var_dim_ref_tok_indices, var_dims, var_dim_iter_types
        # print "lhs_array_type",lhs_array_type

        # Use recognized auto generated array types
        lhs_struct_array_type = (
            lhs_elem_c_type.replace("[", "_")
            .replace("]", "_")
            .replace("__", "_")
            .strip("_")
            + "_array"
        )
        for var_dim in var_dims:
            lhs_struct_array_type += "_" + str(var_dim)
        lhs_struct_array_type += "_t"

        # This is going to be implemented in as C so func name needs to be unique
        func_name = LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX

        # Fuck it just make names that wont be wrong/overlap
        # Are there built in structs?
        # output/elem type
        func_name += "_" + lhs_elem_c_type.replace("[", "_").replace("]", "_").replace(
            "__", "_"
        ).strip("_")
        # Base type
        lhs_base_var_type_c_name = (
            lhs_base_type.replace("[", "_")
            .replace("]", "_")
            .replace("__", "_")
            .strip("_")
        )
        func_name += "_" + lhs_base_var_type_c_name
        # output ref toks --dont include base var name
        for ref_tok in lhs_ref_toks[1:]:
            if type(ref_tok) is int:
                func_name += "_" + str(ref_tok)
            elif type(ref_tok) is str:
                func_name += "_" + ref_tok
            elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                func_name += "_" + "VAR"
            else:
                print("What is lhs ref tok?", ref_tok)
                sys.exit(-1)
        """ SHOULDNT NEED INPUT REF TOKS SINCE HASHED? 
        # input ref toks  --dont include base var name
        for ref_toks in sorted_reduced_ref_toks_set:
            for ref_tok in ref_toks[1:]:
                if type(ref_tok) == int:
                    func_name += "_" + str(ref_tok)
                elif type(ref_tok) == str:
                    func_name += "_" + ref_tok
                elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                    func_name += "_" + "VAR"
                else:
                    print("What is lhs ref tok?", ref_tok)
                    sys.exit(-1)
        """
        # NEED HASH to account for reduced ref toks as name
        input_ref_toks_str = ""
        for ref_toks in sorted(ref_toks_set):
            for ref_tok in ref_toks[1:]:  # Skip base var name
                if type(ref_tok) is int:
                    input_ref_toks_str += "_INT_" + str(ref_tok)
                elif type(ref_tok) is str:
                    input_ref_toks_str += "_STR_" + ref_tok
                elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                    input_ref_toks_str += "_" + "VAR"
                else:
                    print("What is ref tok bleh????", ref_tok)
                    sys.exit(-1)
        # Hash the string
        hash_ext = (
            "_" + ((hashlib.md5(input_ref_toks_str.encode("utf-8")).hexdigest())[0:4])
        )  # 4 chars enough?
        func_name += hash_ext

        # Preparing for N arg func inst
        func_c_ast_node = c_ast_assignment.lvalue
        func_base_name = func_name  # Func name is unique
        base_name_is_name = True
        input_drivers = []  # Wires or C ast nodes
        input_driver_types = []  # Might be none if not known
        input_port_names = []  # Port names on submodule

        # get inst name
        func_inst_name = BUILD_INST_NAME(
            prepend_text, func_base_name, c_ast_assignment.lvalue
        )
        output_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
        # LHS type is output type too
        parser_state.existing_logic.wire_to_c_type[output_wire_name] = (
            lhs_struct_array_type
        )
        # Save ref toks for this ref submodule
        parser_state.existing_logic.ref_submodule_instance_to_ref_toks[
            func_inst_name
        ] = lhs_ref_toks

        # DO INPUT WIRES
        # (elem_val, ref_tok0, ref_tok1, ..., var_dim0, var_dim1, ...)

        # Elem val is from rhs
        input_port_name = "elem_val"
        input_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
        # Set type of input wire if not set already
        if input_wire not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[input_wire] = lhs_elem_c_type
        # Make the c_ast node drive the input wire
        input_connect_logic = C_AST_NODE_TO_LOGIC(
            c_ast_assignment.rvalue, [input_wire], prepend_text, parser_state
        )
        # Merge this connect logic
        parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
        parser_state.existing_logic = parser_state.existing_logic
        # What drives the input port?
        driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]
        # Save this
        input_drivers.append(driving_wire)
        input_driver_types.append(lhs_elem_c_type)
        input_port_names.append(input_port_name)

        # Do C_AST_REF_TOKS_TO_LOGIC
        # For all the ref toks
        # DONT INCLUDE VAR NAMES IN ports
        # Dont want to encode ref toks?
        # Var assign is implemented in C, then must be C safe
        ref_toks_i = 0
        parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
            func_inst_name
        ] = []
        for ref_toks in sorted_reduced_ref_toks_set:
            input_port_name = "ref_toks_" + str(ref_toks_i)
            ref_toks_i += 1

            ## if base variable then call it base
            # if len(ref_toks) == 1:
            # input_port_name = "base_var"
            input_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name

            # Make the ref toks drive the input wire
            # This can create submoduel so have useful prepend text saying auto gen by this assignment
            input_connnect_prepend_text = (
                LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_INPUT_" + prepend_text
            )
            input_connect_logic = C_AST_REF_TOKS_TO_LOGIC(
                ref_toks,
                c_ast_assignment.lvalue,
                [input_wire],
                input_connnect_prepend_text,
                parser_state,
            )
            # Merge this connect logic
            parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
            parser_state.existing_logic = parser_state.existing_logic
            # What the type?
            input_wire_c_type = parser_state.existing_logic.wire_to_c_type[input_wire]

            # What drives the input port?
            driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]

            # Save this
            input_drivers.append(driving_wire)
            input_driver_types.append(input_wire_c_type)
            input_port_names.append(input_port_name)

            # SET ref_submodule_instance_to_input_port_driven_ref_toks
            parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
                func_inst_name
            ].append(ref_toks)

        # Do C_AST_NODE_TO_LOGIC for var_dim c_ast_nodes
        for var_dim_i in range(0, len(var_dims)):
            ref_tok_index = var_dim_ref_tok_indices[var_dim_i]
            ref_tok_c_ast_node = lhs_ref_toks[ref_tok_index]
            # Sanity check
            if C_AST_REF_TOK_IS_CONST(ref_tok_c_ast_node):
                print("Not a variable ref tok?", ref_tok_c_ast_node)
                sys.exit(-1)

            # Cant use hacky str encode sinc eis just "*"
            # Say which variable index this is
            input_port_name = "var_dim_" + str(var_dim_i)
            input_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name

            # Set type of input wire
            parser_state.existing_logic.wire_to_c_type[input_wire] = var_dim_iter_types[
                var_dim_i
            ]

            # Make the c_ast node drive the input wire
            input_connect_logic = C_AST_NODE_TO_LOGIC(
                ref_tok_c_ast_node, [input_wire], prepend_text, parser_state
            )
            # Merge this connect logic
            parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
            parser_state.existing_logic = parser_state.existing_logic
            # What the type?
            input_wire_c_type = parser_state.existing_logic.wire_to_c_type[input_wire]

            # What drives the input port?
            driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]

            # Save this
            input_drivers.append(driving_wire)
            input_driver_types.append(input_wire_c_type)
            input_port_names.append(input_port_name)

        # OK, got all the input wires connected

        # VERY SIMILAR TO CONST
        ###########################################
        # RECORD NEW ALIAS FOR THIS ASSIGNMENT!!!

        # Assignments are ordered over time with existing logic
        # Assigning to a variable creates an alias
        # future reads on this variable are done from the alias
        lhs_next_wire_assignment_alias = C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(
            prepend_text, lhs_ref_toks, c_ast_assignment.lvalue, parser_state
        )
        # print "lhs_next_wire_assignment_alias",lhs_next_wire_assignment_alias

        # /\
        # SET LHS TYPE
        # Type of alias wire is "larger" sized array type
        # parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = lhs_array_type
        parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = (
            lhs_struct_array_type
        )

        # Save orig var name
        parser_state.existing_logic = parser_state.existing_logic
        parser_state.existing_logic.variable_names.add(lhs_orig_var_name)

        # print "lhs_next_wire_assignment_alias",lhs_next_wire_assignment_alias

        # print "c_ast_assignment.rvalue"
        # casthelp(c_ast_assignment.rvalue)
        driven_wire_names = [lhs_next_wire_assignment_alias]
        parser_state.existing_logic = parser_state.existing_logic

        # Get func logic
        rhs_to_lhs_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            func_c_ast_node,
            func_base_name,
            base_name_is_name,
            input_drivers,  # Wires or C ast nodes
            input_driver_types,  # Might be none if not known
            input_port_names,  # Port names on submodule
            driven_wire_names,
            parser_state,
        )

        # Set type of RHS wire as LHS type if not known
        rhs_driver = rhs_to_lhs_logic.wire_driven_by[lhs_next_wire_assignment_alias]
        if rhs_driver not in rhs_to_lhs_logic.wire_to_c_type:
            # rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_array_type
            rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_struct_array_type

        # Merge existing and rhs logic
        parser_state.existing_logic.MERGE_SEQ_LOGIC(rhs_to_lhs_logic)

        # Add alias to list in existing logic
        existing_aliases = []
        if lhs_orig_var_name in parser_state.existing_logic.wire_aliases_over_time:
            existing_aliases = parser_state.existing_logic.wire_aliases_over_time[
                lhs_orig_var_name
            ]
        new_aliases = existing_aliases

        # Dont double add aliases
        if lhs_next_wire_assignment_alias not in new_aliases:
            new_aliases = new_aliases + [lhs_next_wire_assignment_alias]
        parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name] = (
            new_aliases
        )
        parser_state.existing_logic.alias_to_driven_ref_toks[
            lhs_next_wire_assignment_alias
        ] = lhs_ref_toks
        parser_state.existing_logic.alias_to_orig_var_name[
            lhs_next_wire_assignment_alias
        ] = lhs_orig_var_name

        return parser_state.existing_logic

    else:
        # CONSTANT ~~~~~~~~~~~~~~
        ###########################################
        return C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(
            lhs_ref_toks,
            c_ast_assignment.lvalue,
            c_ast_assignment.rvalue,
            parser_state,
            prepend_text,
            c_ast_assignment,
        )


def C_AST_AUG_ASSIGNMENT_TO_RHS_LOGIC(
    c_ast_assignment, driven_wire_names, prepend_text, parser_state
):
    # Ah fuckery can we just convert this into a binary op now?
    # I think I am seeing the promise land
    # of compiler optimizations and the beauty of pycparser again
    op = None
    if c_ast_assignment.op == "+=":
        op = "+"
    elif c_ast_assignment.op == "-=":
        op = "-"
    elif c_ast_assignment.op == "*=":
        op = "*"
    elif c_ast_assignment.op == "/=":
        op = "/"
    elif c_ast_assignment.op == "%=":
        op = "%"
    elif c_ast_assignment.op == "<<=":
        op = "<<"
    elif c_ast_assignment.op == ">>=":
        op = ">>"
    elif c_ast_assignment.op == "&=":
        op = "&"
    elif c_ast_assignment.op == "^=":
        op = "^"
    elif c_ast_assignment.op == "|=":
        op = "|"

    if op is not None:
        fake_bin_op_rhs = c_ast.BinaryOp(
            op, left=c_ast_assignment.lvalue, right=c_ast_assignment.rvalue
        )
        fake_bin_op_rhs.coord = c_ast_assignment.coord
        # print(fake_bin_op_rhs.coord)
        # casthelp(fake_bin_op_rhs)
        # sys.exit(0)
        return C_AST_BINARY_OP_TO_LOGIC(
            fake_bin_op_rhs, driven_wire_names, prepend_text, parser_state
        )
    else:
        print("Unsupported assignment op", c_ast_assignment.op, c_ast_assignment.coord)
        sys.exit(-1)


def C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(
    lhs_ref_toks,
    lhs_c_ast_node,
    rhs_c_ast_node,
    parser_state,
    prepend_text,
    c_ast_assignment,
):
    # RECORD NEW ALIAS FOR THIS ASSIGNMENT!!!
    lhs_orig_var_name = lhs_ref_toks[0]
    # print("lhs_orig_var_name",lhs_orig_var_name)

    # Assignments are ordered over time with existing logic
    # Assigning to a variable creates an alias
    # future reads on this variable are done from the alias
    lhs_next_wire_assignment_alias = C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(
        prepend_text, lhs_ref_toks, lhs_c_ast_node, parser_state
    )
    # Record
    parser_state.existing_logic.alias_to_driven_ref_toks[
        lhs_next_wire_assignment_alias
    ] = lhs_ref_toks
    parser_state.existing_logic.alias_to_orig_var_name[
        lhs_next_wire_assignment_alias
    ] = lhs_orig_var_name

    # /\
    # SET LHS TYPE
    lhs_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(
        lhs_ref_toks, lhs_c_ast_node, parser_state
    )
    parser_state.existing_logic.variable_names.add(lhs_orig_var_name)
    # Type of alias wire is same as original wire
    parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = (
        lhs_c_type
    )

    # Get the RHS logic driving the alias
    driven_wire_names = [lhs_next_wire_assignment_alias]
    # Ahhhh jeez this is shitty special casing for augmented operators
    if c_ast_assignment is not None and c_ast_assignment.op != "=":
        rhs_to_lhs_logic = C_AST_AUG_ASSIGNMENT_TO_RHS_LOGIC(
            c_ast_assignment, driven_wire_names, prepend_text, parser_state
        )
    else:
        # Normal "=" 'operator'
        rhs_to_lhs_logic = C_AST_NODE_TO_LOGIC(
            rhs_c_ast_node, driven_wire_names, prepend_text, parser_state
        )

    # Set type of RHS wire as LHS type if not known
    # print("rhs_to_lhs_logic.wire_driven_by",rhs_to_lhs_logic.wire_driven_by)
    rhs_driver = rhs_to_lhs_logic.wire_driven_by[lhs_next_wire_assignment_alias]
    # print("lhs",lhs_ref_toks,lhs_next_wire_assignment_alias, "=",  rhs_driver)
    # if lhs_orig_var_name in parser_state.existing_logic.wire_aliases_over_time:
    #  print("aliases:",parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name])
    if rhs_driver not in rhs_to_lhs_logic.wire_to_c_type:
        # print "rhs_driver",rhs_driver
        # print "lhs_c_type",lhs_c_type
        rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_c_type

    # Merge existing and rhs logic
    parser_state.existing_logic.MERGE_SEQ_LOGIC(rhs_to_lhs_logic)

    # Add alias to list in existing logic
    existing_aliases = []
    if lhs_orig_var_name in parser_state.existing_logic.wire_aliases_over_time:
        existing_aliases = parser_state.existing_logic.wire_aliases_over_time[
            lhs_orig_var_name
        ]
    new_aliases = existing_aliases

    # Dont double add aliases
    if lhs_next_wire_assignment_alias not in new_aliases:
        new_aliases = new_aliases + [lhs_next_wire_assignment_alias]
    parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name] = new_aliases

    return parser_state.existing_logic


def EXPAND_REF_TOKS_OR_STRS(ref_toks_or_strs, c_ast_ref, parser_state):
    # print "EXPAND:",ref_toks_or_strs

    # Get list of variable dims TODO: Modify  GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES to accept strs?
    var_dim_ref_tok_indices = []
    var_dims = []
    curr_ref_toks = ref_toks_or_strs[:]
    # need at last 2 ref toks, array cant be in pos 0
    while len(curr_ref_toks) >= 2:
        last_index = len(curr_ref_toks) - 1
        last_tok = curr_ref_toks[last_index]
        if last_tok == "*" or not C_AST_REF_TOK_IS_CONST(last_tok):
            # is variable array dim
            # Pop off this last entry
            curr_ref_toks = curr_ref_toks[:last_index]

            # need to fake c_ast node for is this is strs
            curr_ref_toks_faked = ()
            for curr_ref_tok in curr_ref_toks:
                if curr_ref_tok == "*":
                    curr_ref_toks_faked += (c_ast.Node(),)
                else:
                    curr_ref_toks_faked += (curr_ref_tok,)

            # Get the array type
            c_array_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(
                curr_ref_toks_faked, c_ast_ref, parser_state
            )
            # Sanity check
            if not LOGIC.C_TYPE_IS_ARRAY(c_array_type):
                print("Oh no not an array?2", c_array_type)
                sys.exit(-1)
            # Get the dims from the array
            elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
            # Want last dim
            # last_dim = dims[len(dims)-1]
            # First dim?
            first_dim = dims[0]
            # Save
            var_dim_ref_tok_indices.append(last_index)
            var_dims.append(first_dim)
        else:
            # Pop off this last entry
            curr_ref_toks = curr_ref_toks[:last_index]
            # Thats it

    # Do the nest loops to create all possible ref toks
    ref_toks_set = set()

    for orig_ref_tok_i in range(0, len(ref_toks_or_strs)):
        orig_ref_tok = ref_toks_or_strs[orig_ref_tok_i]
        # Start a new return list
        new_ref_toks_set = set()
        # Is this orig ref tok variable?
        if orig_ref_tok == "*" or not C_AST_REF_TOK_IS_CONST(orig_ref_tok):
            # Variable
            # What dimension is this variable
            # Sanity check
            if orig_ref_tok_i not in var_dim_ref_tok_indices:
                print("Wait this ref tok isnt variable?2", orig_ref_tok)
                sys.exit(-1)
            # Get index of this var dim is list of var dims
            var_dim_i = var_dim_ref_tok_indices.index(orig_ref_tok_i)
            var_dim = var_dims[var_dim_i]
            # For each existing ref tok append that with all possible dim values
            for ref_toks in ref_toks_set:
                for dim_val in range(0, var_dim):
                    new_ref_toks = ref_toks + (dim_val,)
                    new_ref_toks_set.add(new_ref_toks)
        else:
            ## Fix string digits to be ints
            # if type(orig_ref_tok) == str and orig_ref_tok.isdigit():
            # orig_ref_tok = int(orig_ref_tok)
            # ???^^^ what?

            # Constant just append this constant value to all ref toks in list
            for ref_toks in ref_toks_set:
                new_ref_toks = ref_toks + (orig_ref_tok,)
                new_ref_toks_set.add(new_ref_toks)
            # Or add as base element
            if len(ref_toks_set) == 0:
                new_ref_toks_set.add((orig_ref_tok,))

        # Next iteration save new ref toks
        ref_toks_set = set(new_ref_toks_set)

    return ref_toks_set


# Do one level of expansion to next branches
# Expands variable ref toks, structs to fields, arrays to elements
# Does not return self ref_toks in set, self is not a branch of self
_REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache = {}


def REF_TOKS_TO_OWN_BRANCH_REF_TOKS(ref_toks, c_ast_ref, parser_state):
    # Try for cache
    if parser_state.existing_logic.func_name is None:
        print("Wtf none??????")
        sys.exit(-1)
    cache_key = (parser_state.existing_logic.func_name, ref_toks)
    try:
        return set(
            _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache[cache_key]
        )  # Copy since set is mutable + WILL be mutated
    except:
        pass

    debug = False
    # Only return one level of extra branchs
    # Current c type
    # Get the CONST C type as evaulated (a,*,b) is like a[0].b
    # (a,b,*) is want the compound a.b, so trim
    trimmed_ref_toks = TRIM_VAR_REF_TOKS(ref_toks)
    c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(trimmed_ref_toks, c_ast_ref, parser_state)
    if debug:
        print("c_type", c_type)
    # Use this type to do struct and array expansion
    rv = set()
    # Struct?
    if LOGIC.C_TYPE_IS_STRUCT(c_type, parser_state):
        # Child branches are struct field names
        field_type_dict = parser_state.struct_to_field_type_dict[c_type]
        if debug:
            print("Struct:", field_type_dict)
        for field in field_type_dict:
            new_toks = trimmed_ref_toks[:]
            new_toks += (field,)
            rv.add(new_toks)

    # Array?
    elif LOGIC.C_TYPE_IS_ARRAY(c_type):
        # One dimension at a time works?
        base_elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
        current_dim = dims[0]
        if debug:
            print("Array current_dim:", current_dim)
        inner_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(c_type)
        for i in range(0, current_dim):
            new_toks = trimmed_ref_toks[:]
            new_toks += (i,)
            rv.add(new_toks)
    else:
        # Not composite type
        if debug:
            print("Not composite type, no branches")
        # Only branch is self, not included
        rv = set()

    # Then expand all variable references
    # rv is based on ref_toks so wont have variable ref toks if ref_toks wasnt
    if not C_AST_REF_TOKS_ARE_CONST(trimmed_ref_toks):
        # Expand know all variable ref toks inrv
        expanded_ref_toks_set = set()
        for ref_toks_i in rv:
            expanded_ref_toks_set |= EXPAND_REF_TOKS_OR_STRS(
                ref_toks_i, c_ast_ref, parser_state
            )
        rv = expanded_ref_toks_set

    # Update cache
    _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache[cache_key] = frozenset(rv)
    # print cache_key
    return rv


_REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache = {}


# Traverse compound types down to individual ref toks to collect all branches
#  expanding variable refs along the way
def REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(ref_toks, c_ast_ref, parser_state):
    debug = False

    # Try for cache
    if parser_state.existing_logic.func_name is None:
        print("Wtf none??????")
        sys.exit(-1)
    cache_key = (parser_state.existing_logic.func_name, ref_toks)
    try:
        return set(
            _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache[cache_key]
        )  # Copy since set is mutable + WILL be mutated
    except:
        pass

    # Will I forget to trim elsewhere?
    #   Arcade Fire - Everything Now
    rv = set([TRIM_VAR_REF_TOKS(ref_toks)])
    # Get next level branches
    next_branch_ref_toks_set = REF_TOKS_TO_OWN_BRANCH_REF_TOKS(
        ref_toks, c_ast_ref, parser_state
    )
    rv |= next_branch_ref_toks_set
    # print "ref_toks",ref_toks,"next_branch_ref_toks_set",next_branch_ref_toks_set
    # Recurse from there
    for next_branch_ref_toks in next_branch_ref_toks_set:
        rv |= REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(
            next_branch_ref_toks, c_ast_ref, parser_state
        )

    if debug:
        print("All branches:", rv)
        # sys.exit(-1)

    # Update cache
    _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache[cache_key] = frozenset(rv)

    return rv


_REDUCE_REF_TOKS_OR_STRS_cache = {}


def REDUCE_REF_TOKS_OR_STRS(ref_toks_set, c_ast_node, parser_state):
    # Try for cache
    if parser_state.existing_logic.func_name is None:
        print("Wtf none??????")
        sys.exit(-1)
    cache_key = (parser_state.existing_logic.func_name, frozenset(ref_toks_set))
    try:
        return set(
            _REDUCE_REF_TOKS_OR_STRS_cache[cache_key]
        )  # Copy since set is mutable + WILL be mutated
    except:
        pass

    # Collpase ex. [ [struct,pointa,x] , [struct,pointa,y], [struct,pointb,x] ]
    # collpases down to [ [struct,pointa], [struct,pointb,x] ] since sub elements of point are all driven
    # What about if ref_toks ends in variable/array ref tok? Collapse down to array base name right?
    #   [struct,array,*/castnode, anotherarray, */castnode]
    # First expand to get rid of variable ref toks
    expanded_ref_toks_set = set()
    for ref_toks in ref_toks_set:
        expanded_ref_toks_set_i = EXPAND_REF_TOKS_OR_STRS(
            ref_toks, c_ast_node, parser_state
        )
        expanded_ref_toks_set |= expanded_ref_toks_set_i

    # Then reduce that expanded list
    rv_ref_toks_set = set(expanded_ref_toks_set)
    still_removing_elements = True
    while still_removing_elements:
        # Assume stoping now
        still_removing_elements = False

        # Loop over all ref toks
        loop_copy_rv_ref_toks_set = set(rv_ref_toks_set)
        for ref_toks in loop_copy_rv_ref_toks_set:
            # IF removing elements then back to outermost loop
            if still_removing_elements:
                break

            # Remove children of this ref_tok
            # Do the faster of two options
            # 1) Look through all ref toks for possible children of the current ref tok
            # 2) Look through all children of the current ref tok for if they occur in all ref toks
            all_branch_ref_toks = REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(
                ref_toks, c_ast_node, parser_state
            ) - set([ref_toks])
            # print("Looking from",ref_toks,"for",all_branch_ref_toks)
            # print("Could search",len(all_branch_ref_toks),"own_branch_ref_toks")
            # print("Could search",len(loop_copy_rv_ref_toks_set),"loop_copy_rv_ref_toks_set")
            if len(all_branch_ref_toks) < len(loop_copy_rv_ref_toks_set):
                # Faster to search struct/array def branches than entire set of ref toks from code
                for branch_ref_tok in all_branch_ref_toks:
                    if branch_ref_tok in rv_ref_toks_set:
                        rv_ref_toks_set.remove(branch_ref_tok)
                        still_removing_elements = True
            else:
                # Faster to search entire set of ref toks from code than all possible branches from ref tok
                for maybe_child_ref_tok in loop_copy_rv_ref_toks_set - set([ref_toks]):
                    if REF_TOKS_COVERED_BY(maybe_child_ref_tok, ref_toks, parser_state):
                        rv_ref_toks_set.remove(maybe_child_ref_tok)
                        still_removing_elements = True
            # Record if change was made and jump to next iteration
            if still_removing_elements:
                break

            # Check if these ref_toks are a leaf with all sibling leafs driven
            if len(ref_toks) < 2:
                continue

            # Get root struct for this struct ref
            root_ref_toks = ref_toks[0 : len(ref_toks) - 1]
            # Check if all fields of this root struct ref are in this list
            root_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(
                root_ref_toks, c_ast_node, parser_state
            )
            all_fields_present = True
            if LOGIC.C_TYPE_IS_STRUCT(root_c_type, parser_state):
                field_types_dict = parser_state.struct_to_field_type_dict[root_c_type]
                for field_name in field_types_dict:
                    possible_ref_toks = root_ref_toks + (field_name,)
                    if possible_ref_toks not in rv_ref_toks_set:
                        all_fields_present = False

                # If all there then remove them all
                if all_fields_present:
                    still_removing_elements = True
                    for field_name in field_types_dict:
                        possible_ref_toks = root_ref_toks + (field_name,)
                        rv_ref_toks_set.remove(possible_ref_toks)
                    # And replace with root
                    rv_ref_toks_set.add(root_ref_toks)
                    # Next iteration
                    break

            elif LOGIC.C_TYPE_IS_ARRAY(root_c_type):
                # print "!~~~"
                # print "root_ref_toks",root_ref_toks
                # print "root_c_type",root_c_type
                elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(root_c_type)
                # last_dim = dims[len(dims)-1]
                # No want first dim?
                first_dim = dims[0]

                for i in range(0, first_dim):
                    possible_ref_toks = root_ref_toks + (i,)
                    # print "  possible_ref_toks",possible_ref_toks
                    # print "in"

                    if possible_ref_toks not in rv_ref_toks_set:
                        # print "NO"
                        all_fields_present = False

                # If all there then remove them all
                if all_fields_present:
                    # print "all_fields_present", root_ref_toks
                    still_removing_elements = True
                    for i in range(0, first_dim):
                        possible_ref_toks = root_ref_toks + (i,)
                        # print "  REMOVING possible_ref_toks",possible_ref_toks
                        rv_ref_toks_set.remove(possible_ref_toks)
                    # And replace with root
                    rv_ref_toks_set.add(root_ref_toks)
                    # Next iteration
                    break
            else:
                # Is not a composite type?
                pass

    # Update cache
    _REDUCE_REF_TOKS_OR_STRS_cache[cache_key] = frozenset(rv_ref_toks_set)

    # sys.exit(-1)
    return rv_ref_toks_set


# Please just be mostly used for silly len(ref_toks) compare stuff, not fundamentally required
# 141 sec w/ cache
# 186 w/o cache
_TRIM_VAR_REF_TOKS_cache = {}


def TRIM_VAR_REF_TOKS(ref_toks):
    # Try for cache
    try:
        return _TRIM_VAR_REF_TOKS_cache[ref_toks]
    except:
        pass

    # Remove last variable tok since
    # Ex. (a,1,c) covers same as (a,1,c,*)
    last_ref_tok = ref_toks[len(ref_toks) - 1]
    while not C_AST_REF_TOK_IS_CONST(last_ref_tok):
        ref_toks = ref_toks[0 : len(ref_toks) - 1]
        last_ref_tok = ref_toks[len(ref_toks) - 1]

    # Update cache
    _TRIM_VAR_REF_TOKS_cache[ref_toks] = ref_toks
    return ref_toks


# _REF_TOKS_COVERED_BY_cache = {}
# With cache: 63.812 seconds, 206.699 seconds
# Without cache: 47.065 seconds, 128.514 seconds
# More testing: without cache: 141, with cache: 240
def REF_TOKS_COVERED_BY(ref_toks, covering_ref_toks, parser_state):
    """
    # Try for cache
    if parser_state.existing_logic.func_name is None:
      print "Wtf none??????"
      sys.exit(-1)
    cache_key = (parser_state.existing_logic.func_name, ref_toks, covering_ref_toks)
    try:
      return _REF_TOKS_COVERED_BY_cache[cache_key]
    except:
      pass
    """

    # Remove last variable tok since
    # Ex. (a,1,c) covers same as (a,1,c,*), and makes len check easier below
    # For both input ref toks
    covering_ref_toks = TRIM_VAR_REF_TOKS(covering_ref_toks)
    ref_toks = TRIM_VAR_REF_TOKS(ref_toks)

    rv = True
    # Immediate len check
    # Large len means more specific/narrow/smaller covering
    if len(covering_ref_toks) > len(ref_toks):
        rv = False
    else:
        """
        # Simple compare of range -  NOT faster
        if ref_toks[0:len(covering_ref_toks)] == covering_ref_toks:
          rv = True
        else:
        """
        # Individual tok checking
        # Likely mismatches are towards end? - Hell yeah for big arrays?
        # Build Me Up Buttercup - The Foundatons
        # for ref_tok_i in range(0, len(covering_ref_toks)):
        for ref_tok_i in range(len(covering_ref_toks) - 1, -1, -1):
            ref_tok = ref_toks[ref_tok_i]
            covering_ref_tok = covering_ref_toks[ref_tok_i]
            # Look for mismatch
            if ref_tok == covering_ref_tok:
                pass
            # Didnt match check type first, isinstance is slow?
            else:
                if (
                    type(covering_ref_tok) is int and type(ref_tok) is int
                ):  # ALREADY KNOW != and (covering_ref_tok != ref_tok):
                    rv = False
                    break
                elif (
                    type(covering_ref_tok) is str and type(ref_tok) is str
                ):  # ALREADY KNOW != and (covering_ref_tok != ref_tok):
                    rv = False
                    break
                # Variable c ast nodes only match one way
                # * covers digit but digit doesnt cover *
                elif (
                    not C_AST_REF_TOK_IS_CONST(covering_ref_tok)
                    and type(ref_tok) is int
                ):
                    pass
                elif not C_AST_REF_TOK_IS_CONST(covering_ref_tok) and ref_tok.isdigit():
                    pass
                # * covers others *
                elif not C_AST_REF_TOK_IS_CONST(
                    covering_ref_tok
                ) and not C_AST_REF_TOK_IS_CONST(ref_tok):
                    pass
                else:
                    rv = False
                    break

    """
  # Update cache
  _REF_TOKS_COVERED_BY_cache[cache_key] = rv
  """

    return rv


def WIRE_TO_DRIVEN_REF_TOKS(wire, parser_state):
    # Get ref toks for this alias
    if wire in parser_state.existing_logic.alias_to_driven_ref_toks:
        driven_ref_toks = parser_state.existing_logic.alias_to_driven_ref_toks[wire]
    else:
        # Must be orig variable name
        if wire in parser_state.existing_logic.variable_names:
            driven_ref_toks = (wire,)
        # Or input
        elif wire in parser_state.existing_logic.inputs:
            driven_ref_toks = (wire,)
        # Or state regs
        elif wire in parser_state.global_vars:
            driven_ref_toks = (wire,)
        else:
            print("wire:", wire)
            print("var name?:", parser_state.existing_logic.variable_names)
            print(
                "does not have associatated ref toks",
                parser_state.existing_logic.alias_to_driven_ref_toks,
            )
            print(0 / 0)
            sys.exit(-1)

    return driven_ref_toks


# THIS IS DIFFERENT FROM REDUCE DONE ABOVE
# (does modifies remaining_ref_toks, but use return value since can be cached)


# Fat cache...
# With cache, run time 230 sec w heapy, Total size = 1261187248 bytes
# Without cache, run time 180 sec w heapy, Total size = 1098484016 bytes
# _REMOVE_COVERED_REF_TOK_BRANCHES_cache = {}
# Try without heapy...
# With cache runtime: 74.670 seconds, 304.788 seconds
# Without cache runtime: 61.963 seconds, 210.264 seconds,
def REMOVE_COVERED_REF_TOK_BRANCHES(
    remaining_ref_toks_set, driven_ref_toks, c_ast_node, parser_state
):
    # print "remaining_ref_toks_set",remaining_ref_toks_set
    # print "driven_ref_toks",driven_ref_toks
    # print "=="
    debug = False
    # debug = (parser_state.existing_logic.func_name == "VAR_REF_RD_uint8_t_64_uint8_t_64_64_VAR_4538") and driven_ref_toks==('base', 0, 63)

    if debug:
        orig_remaining_ref_toks_set = set(remaining_ref_toks_set)  # debug

    if parser_state.existing_logic.func_name is None:
        print("Wtf none??????")
        sys.exit(-1)

    """
  # Try for cache
  cache_key = (parser_state.existing_logic.func_name, driven_ref_toks, frozenset(remaining_ref_toks_set))
  remaining_ref_toks_set_cache = None
  try:
    remaining_ref_toks_set_cache = set(_REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]) # Copy since set is mutable + WILL be mutated
  except:
    pass
  if remaining_ref_toks_set_cache:
    if debug:
      print "orig_remaining_ref_toks_set",orig_remaining_ref_toks_set
      print "orig driven_ref_toks",driven_ref_toks
      print "remaining_ref_toks_set",remaining_ref_toks_set_cache
      print "2" 
    if driven_ref_toks in remaining_ref_toks_set_cache:
      print parser_state.existing_logic.func_name
      print "orig driven_ref_toks",driven_ref_toks
      print "remaining_ref_toks_set",remaining_ref_toks_set_cache
      print "pre remaining_ref_toks_set==remaining_ref_toks_set_cache",remaining_ref_toks_set==remaining_ref_toks_set_cache
      print "WTF? driven_ref_toks in remaining_ref_toks_set_cache"
      sys.exit(-1)
      
    remaining_ref_toks_set = remaining_ref_toks_set_cache
    return remaining_ref_toks_set
  """

    # Removed covered branches
    removed_something = False
    # Given alias wire (a,1,c) it covers any remaining wire (a,1,c) , (a,1,c,0) ,  (a,1,c,1)
    to_be_removed = set()
    for ref_toks in (
        remaining_ref_toks_set
    ):  # set(remaining_ref_toks_set): # NO -slo? Copy for iteration
        if REF_TOKS_COVERED_BY(ref_toks, driven_ref_toks, parser_state):
            # Remove this ref toks
            if debug:
                print(ref_toks, "covered by", driven_ref_toks)
            # remaining_ref_toks_set.remove(ref_toks)
            to_be_removed.add(ref_toks)
            removed_something = True
        else:
            if debug:
                print(ref_toks, "not covered by", driven_ref_toks)
    remaining_ref_toks_set -= to_be_removed

    if debug:
        print("orig_remaining_ref_toks_set", orig_remaining_ref_toks_set)
        print("orig driven_ref_toks", driven_ref_toks)
        print("remaining_ref_toks_set after removing coverage", remaining_ref_toks_set)

    if removed_something:
        # The current driven_ref_toks would be removed from list
        # Removing the branches at/under driven_ref_toks might also
        # Might also be removing all the branches of the parent to driven_ref_toks
        # Ex. (a,1,c) removed from a list of that could have had (a,1,a) , (a,1,b)
        #   BUT DIDNT
        #   So (a,1,c) might be the last child of (a,1) remaining, check
        # Do this repeatedly up the tree collapsing as far as possible
        # Need at least 2 toks to get root tok
        ref_toks_removed = TRIM_VAR_REF_TOKS(driven_ref_toks)
        while len(ref_toks_removed) >= 2:
            root_toks = ref_toks_removed[0 : len(ref_toks_removed) - 1]
            keep_root = True  # default keep root branch
            # Is root even a compound type?
            own_branch_ref_toks = REF_TOKS_TO_OWN_BRANCH_REF_TOKS(
                root_toks, c_ast_node, parser_state
            )

            # Set stuff faster?
            keep_root = (
                len(own_branch_ref_toks.intersection(remaining_ref_toks_set)) > 0
            )
            """
      if len(own_branch_ref_toks) > 0:
        # Has branches, are they all removed now?
        keep_root = False # Assume all branches are gone
        for branch_ref_toks in own_branch_ref_toks:
          if branch_ref_toks in remaining_ref_toks_set:
              # Found a remaining branch, root stays
              keep_root = True
              break
      """

            if not keep_root:
                # Remove root, and loop again
                """
                if root_toks not in remaining_ref_toks_set:
                  print "orig_remaining_ref_toks_set",orig_remaining_ref_toks_set
                  print "orig driven_ref_toks",driven_ref_toks
                  print "Missing ref tok?",root_toks
                  print "remaining_ref_toks_set",remaining_ref_toks_set
                  print "ref_toks_removed",ref_toks_removed
                  sys.exit(-1)
                """
                remaining_ref_toks_set.discard(root_toks)
                ref_toks_removed = root_toks
            else:
                # Keeping root, stop here
                break

        if debug:
            print(
                "remaining_ref_toks_set after collpasing refs too",
                remaining_ref_toks_set,
            )
            print("")

    """
  # Update cache  
  _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key] = frozenset(remaining_ref_toks_set) # Copy since set is mutable + WILL be mutated
  if debug:
    print "Updating cache", cache_key
    print _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]
  """

    # WTF?
    if (
        driven_ref_toks in remaining_ref_toks_set
    ):  # or (driven_ref_toks in _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]):
        print("WTF? driven_ref_toks in remaining_ref_toks_set2")
        sys.exit(-1)

    return remaining_ref_toks_set


# ID could be a struct ID which needs struct read logic
# ID could also be an array ID which needs array read logic


# x[i][1][k]
# First need to select the i'th [n][n] array from 'x'
# Then select the 1st [n] array from output of above
# Then select k'th element from output of above
# So out of all x only these elements are needed
#
# x 0 0 0
# x 0 0 1
# x 0 1 0     X
# x 0 1 1     X
# x 1 0 0
# x 1 0 1
# x 1 1 0     X
# x 1 1 1     X

# Need to expand struct, array to all branches?
# Then evaluate  s.x[i][1] to be  s[x,i,1]
# s.x[0][0]
# s.x[0][1]   X
# s.x[1][0]
# s.x[1][1]   X
# s.y[0][0]
# s.y[0][1]
# s.y[1][0]
# s.y[1][1]


# Struct read is different from array read since:
# At the time of struct read it is possible to narrow down the
# renamed intermediate wires that of what the struct ref is referreing
# for an array reference the "struct locations in memory / memory addrs" cannot be known ahead of time
# Always need to input entire array unless constant, when constant do like struct ref?

"""
DID you do struct ref wrong?
CANT PROCESS AS single x.y.z expression
Need to recursively get X, with .y  ... then get output of that DOT z
fuck

ONly diff between constant array and dynamic is where the "branches" start in the structref/array search
# Since arrays are written to like structs, COPY ON READ
Structref and constant array look very similar
"""


def RESOLVE_C_AST_NODE_TO_CONSTANT_STR(c_ast_node, prepend_text, parser_state):
    # Very similar to RESOLVE_REF_TOKS_TO_CONSTANT_WIRE
    if c_ast_node is None:
        return None

    # Ugh hacky pass through for ram init, etc
    if type(c_ast_node) == c_ast.InitList:
        return None

    dummy_wire = "DUMMY_RESOLVE_WIRE"
    driven_wire_names = [dummy_wire]
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
        c_ast_node, driven_wire_names, prepend_text, parser_state
    )
    # Is dummy wire driven by constant?
    const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        dummy_wire, parser_state.existing_logic
    )

    # Remove the dummy wire
    # Fast
    parser_state.existing_logic.wires.remove(dummy_wire)
    parser_state.existing_logic.wire_to_c_type.pop(dummy_wire, None)
    # IO wire is driven by thing
    driving_wire = parser_state.existing_logic.wire_driven_by[dummy_wire]
    # Remove io wire from opposite direction
    all_driven_wires = parser_state.existing_logic.wire_drives[driving_wire]
    all_driven_wires.remove(dummy_wire)
    if len(all_driven_wires) > 0:
        parser_state.existing_logic.wire_drives[driving_wire] = all_driven_wires
    else:
        parser_state.existing_logic.wire_drives.pop(driving_wire)
    # Then remove original direction
    parser_state.existing_logic.wire_driven_by.pop(dummy_wire)

    # Return the constant or None
    if const_driving_wire is not None:
        # Get value from this constant
        val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_driving_wire, parser_state.existing_logic, parser_state
        )
        return val_str  # , parser_state.existing_logic
    else:
        return None  # , parser_state.existing_logic


def RESOLVE_REF_TOKS_TO_CONSTANT_WIRE(ref_toks, c_ast_node, prepend_text, parser_state):
    # Very similar to RESOLVE_CONST_ARRAY_REF_TO_LOGIC

    # Do a fake C_AST_NODE to logic for subscript

    # if can trace to constant wire then
    dummy_wire = "DUMMY_RESOLVE_WIRE"
    driven_wire_names = [dummy_wire]
    # This will be removed always?
    # OK to pre evaluate the subscript because will be evaluated always the same
    # Will just be driving var ref opr var assign submodules instead of dummy?
    # parser_state.existing_logic.wire_to_c_type[dummy_wire] = "uint32_t"
    parser_state.existing_logic = C_AST_REF_TOKS_TO_LOGIC(
        ref_toks, c_ast_node, driven_wire_names, prepend_text, parser_state
    )
    # Is dummy wire driven by constant?
    const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        dummy_wire, parser_state.existing_logic
    )

    # Remove the dummy wire
    # Fast
    parser_state.existing_logic.wires.remove(dummy_wire)
    parser_state.existing_logic.wire_to_c_type.pop(dummy_wire, None)
    # IO wire is driven by thing
    driving_wire = parser_state.existing_logic.wire_driven_by[dummy_wire]
    # Remove io wire from opposite direction
    all_driven_wires = parser_state.existing_logic.wire_drives[driving_wire]
    all_driven_wires.remove(dummy_wire)
    if len(all_driven_wires) > 0:
        parser_state.existing_logic.wire_drives[driving_wire] = all_driven_wires
    else:
        parser_state.existing_logic.wire_drives.pop(driving_wire)
    # Then remove original direction
    parser_state.existing_logic.wire_driven_by.pop(dummy_wire)

    # Const wire might be non if ref toks do not resolve to const
    return const_driving_wire


# Returns None if not resolved
# THIS RELYS ON optimizing away constant funcs to const wires in N ARG FUNC logic
# returns  (const, logic)
def RESOLVE_CONST_ARRAY_REF_TO_LOGIC(c_ast_array_ref, prepend_text, parser_state):
    # So this is like needed because constant resolving variable ref
    # into a smaller var ref, or totally constant ref is hard to do
    # ~hElP!~

    # Do a fake C_AST_NODE to logic for subscript
    # if can trace to constant wire then
    dummy_wire = "DUMMY_RESOLVE_WIRE"
    driven_wire_names = [dummy_wire]
    # This will be removed always?
    # OK to pre evaluate the subscript because will be evaluated always the same
    # Will just be driving var ref opr var assign submodules instead of dummy?
    # parser_state.existing_logic.wire_to_c_type[dummy_wire] = "uint32_t"
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
        c_ast_array_ref.subscript, driven_wire_names, prepend_text, parser_state
    )
    # Is dummy wire driven by constant?
    const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        dummy_wire, parser_state.existing_logic
    )

    # Remove the dummy wire
    # Fast
    parser_state.existing_logic.wires.remove(dummy_wire)
    parser_state.existing_logic.wire_to_c_type.pop(dummy_wire, None)
    # IO wire is driven by thing
    driving_wire = parser_state.existing_logic.wire_driven_by[dummy_wire]
    # Remove io wire from opposite direction
    all_driven_wires = parser_state.existing_logic.wire_drives[driving_wire]
    all_driven_wires.remove(dummy_wire)
    if len(all_driven_wires) > 0:
        parser_state.existing_logic.wire_drives[driving_wire] = all_driven_wires
    else:
        parser_state.existing_logic.wire_drives.pop(driving_wire)
    # Then remove original direction
    parser_state.existing_logic.wire_driven_by.pop(dummy_wire)

    # Return the constant or None
    if const_driving_wire is not None:
        # Get value from this constant
        maybe_digit = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_driving_wire, parser_state.existing_logic, parser_state
        )
        if not maybe_digit.isdigit():
            print(
                "Constant array ref with non integer index?",
                const_driving_wire,
                c_ast_array_ref,
            )
            sys.exit(-1)
        # print "CONST",maybe_digit
        return int(maybe_digit), parser_state.existing_logic
    else:
        return None, parser_state.existing_logic


# ONLY USE THIS WITH REF C AST NODES
# Returns toks, logic
def C_AST_REF_TO_TOKENS_TO_LOGIC(
    c_ast_ref, prepend_text, parser_state, first_call=True
):
    toks = tuple()
    if type(c_ast_ref) == c_ast.ID:
        toks += (str(c_ast_ref.name),)
    elif type(c_ast_ref) == c_ast.ArrayRef:
        new_tok = None
        # Only constant array ref right now
        const, parser_state.existing_logic = RESOLVE_CONST_ARRAY_REF_TO_LOGIC(
            c_ast_ref, prepend_text, parser_state
        )
        if const is None:
            new_tok = c_ast_ref.subscript
        else:
            new_tok = const
        # Name is a ref node
        new_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(
            c_ast_ref.name, prepend_text, parser_state, first_call=False
        )
        toks += new_toks
        toks += (new_tok,)
    elif type(c_ast_ref) == c_ast.StructRef:
        # Name is a ref node
        new_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(
            c_ast_ref.name, prepend_text, parser_state, first_call=False
        )
        toks += new_toks
        toks += (str(c_ast_ref.field.name),)
    else:
        print("Uh what node in C_AST_REF_TO_TOKENS?", c_ast_ref)
        print(0 / 0)
        sys.exit(-1)

    # Reverse reverse
    # toks = toks[::-1]

    # If the first call/ top level getitng ref
    # Then do special case replacement of any variable dimensions of length=1 with index=0
    if first_call:
        # Try to eval var dims
        (
            var_dim_ref_tok_indices,
            var_dims,
            var_dim_iter_types,
        ) = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(toks, c_ast_ref, parser_state)
        for var_dim_i in range(0, len(var_dims)):
            var_dim = var_dims[var_dim_i]
            if var_dim == 1:
                ref_tok_index = var_dim_ref_tok_indices[var_dim_i]
                # Overwrite with constant [0]
                toks_list = list(toks)
                toks_list[ref_tok_index] = 0
                toks = tuple(toks_list)

    return toks, parser_state.existing_logic


_C_AST_REF_TOKS_TO_C_TYPE_cache = {}


# "Const" here means variable refs are evaluated x[*] = type of x[0]
def C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_ref, parser_state):
    debug = False
    if debug:
        print("ref_toks", ref_toks)
    # Try to get cache
    # Build key
    ref_toks_str = parser_state.existing_logic.func_name[:]
    for ref_tok in ref_toks:
        if type(ref_tok) is int:
            ref_toks_str += "_INT_" + str(ref_tok)
        elif type(ref_tok) is str:
            ref_toks_str += "_STR_" + ref_tok
        elif not C_AST_REF_TOK_IS_CONST(ref_tok):
            ref_toks_str += "_" + "VAR"
        else:
            print("What is ref tok bleh?sdsd???", ref_tok)
            sys.exit(-1)
    cache_key = ref_toks_str
    # cache_key = (parser_state.existing_logic.func_name, ref_toks)

    # Try for cache
    try:
        return _C_AST_REF_TOKS_TO_C_TYPE_cache[cache_key]
    except:
        pass

    # Get base variable name
    var_name = ref_toks[0]

    # Get the type of this base name
    if var_name in parser_state.existing_logic.wire_to_c_type:
        base_type = parser_state.existing_logic.wire_to_c_type[var_name]
    else:
        if debug:
            # print("parser_state.existing_logic",parser_state.existing_logic)
            print(
                "parser_state.existing_logic.func_name",
                parser_state.existing_logic.func_name,
            )
            print("known variables:", parser_state.existing_logic.variable_names)
            for wire in sorted(parser_state.existing_logic.variable_names):
                print(wire, ":", parser_state.existing_logic.wire_to_c_type[wire])
            # print( "parser_state.existing_logic.wire_to_c_type",parser_state.existing_logic.wire_to_c_type)
        raise Exception(
            f"It looks like variable {var_name} is not defined? {c_ast_ref.coord}"
        )
        # sys.exit(-1)

    # Is this base type an ID, array or struct ref?
    if len(ref_toks) == 1:
        # Just an ID
        current_c_type = base_type
    else:
        # Is a struct ref and/or array ref
        remaining_toks = ref_toks[1:]

        # While we have a reminaing tok
        current_c_type = base_type
        while len(remaining_toks) > 0:
            # if var_name == "bs":
            # print "current_c_type",current_c_type
            # print "remaining_toks",remaining_toks

            next_tok = remaining_toks[0]
            if type(next_tok) is int:
                # Constant array ref
                # Sanity check
                if not LOGIC.C_TYPE_IS_ARRAY(current_c_type):
                    # TODO Explore allowing uint/float to be C TYPE CAN BE BIT ARRAY?
                    print(
                        "Looks like an array reference but not an array type?",
                        current_c_type,
                        remaining_toks,
                        c_ast_ref.coord,
                    )
                    sys.exit(-1)
                # Go to next tok
                remaining_toks = remaining_toks[1:]
                # Remove inner subscript to form output type
                current_c_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(current_c_type)
            elif type(next_tok) is str:
                # Struct
                # Sanity check
                if not LOGIC.C_TYPE_IS_STRUCT(current_c_type, parser_state):
                    print(
                        "Struct ref tok but not struct type?",
                        remaining_toks,
                        current_c_type,
                        c_ast_ref.coord,
                    )
                    # print(parser_state.struct_to_field_type_dict)
                    sys.exit(-1)
                field_type_dict = parser_state.struct_to_field_type_dict[current_c_type]
                if next_tok not in field_type_dict:
                    print(
                        next_tok,
                        "is not a member field of",
                        current_c_type,
                        c_ast_ref.coord,
                    )
                    # print 0/0
                    sys.exit(-1)
                # Go to next tok
                remaining_toks = remaining_toks[1:]
                current_c_type = field_type_dict[next_tok]
            elif not C_AST_REF_TOK_IS_CONST(next_tok):
                # Variable array ref
                # Sanity check
                if not LOGIC.C_TYPE_IS_ARRAY(current_c_type):
                    print(
                        "Arrayref tok but not array type?2",
                        current_c_type,
                        remaining_toks,
                        c_ast_ref.coord,
                    )
                    sys.exit(-1)
                # Go to next tok
                remaining_toks = remaining_toks[1:]
                # Remove inner subscript to form output type
                current_c_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(current_c_type)
            else:
                casthelp(next_tok)
                print("What kind of reference is this?", c_ast_ref.coord)
                sys.exit(-1)

    # Sanity check on const ref must be array type
    """
  if not C_AST_REF_TOKS_ARE_CONST(ref_toks):
    if not C_TYPE_IS_ARRAY(current_c_type):
      print "Ref toks are array type?"
      print ref_toks
      print current_c_type
      sys.exit(-1)
  """

    # Write cache
    _C_AST_REF_TOKS_TO_C_TYPE_cache[cache_key] = current_c_type

    if debug:
        print("current_c_type", current_c_type)

    return current_c_type


def C_AST_ID_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # Is the ID an ENUM constant?
    is_enum_const = ID_IS_ENUM_CONST(
        c_ast_node, parser_state.existing_logic, prepend_text, parser_state
    )

    # print c_ast_node
    # print "is_enum_const",is_enum_const
    if is_enum_const:
        return C_AST_ENUM_CONST_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
    else:
        return C_AST_REF_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )


def C_AST_REF_TO_LOGIC(c_ast_ref, driven_wire_names, prepend_text, parser_state):
    if type(c_ast_ref) == c_ast.ArrayRef:
        pass
    elif type(c_ast_ref) == c_ast.StructRef:
        pass
    elif type(c_ast_ref) == c_ast.ID:
        pass
    else:
        print("What type of ref is this?", c_ast_ref)
        sys.exit(-1)

    # Get tokens to identify the reference
    # x.y[5].z.q[i]   is [x,y,5,z,q,<c_ast_node>]
    ref_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(
        c_ast_ref, prepend_text, parser_state
    )

    return C_AST_REF_TOKS_TO_LOGIC(
        ref_toks, c_ast_ref, driven_wire_names, prepend_text, parser_state
    )


# Does c_ast_ref need to be a ref or just for coord?
def C_AST_REF_TOKS_TO_LOGIC(
    ref_toks, c_ast_ref, driven_wire_names, prepend_text, parser_state
):
    # FUCK - its not so bad, dont worry
    debug = False

    # The original variable name is the first tok
    base_var_name = ref_toks[0]

    # What type is this reference?
    c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_ref, parser_state)

    # Use base var (NOT ORIG WIRE SINCE structs) to look up alias list
    driving_aliases_over_time = []
    # Some wires are special and are already considered driven
    #  ex. input, global, volatile global, or in wire driven by
    if (
        (base_var_name in parser_state.existing_logic.inputs)
        or (base_var_name in parser_state.existing_logic.state_regs)
        or (base_var_name in parser_state.existing_logic.read_only_global_wires)
        or (base_var_name in parser_state.existing_logic.wire_driven_by)
        or (base_var_name in parser_state.existing_logic.feedback_vars)
    ):
        driving_aliases_over_time += [base_var_name]
    aliases_over_time = []
    if base_var_name in parser_state.existing_logic.wire_aliases_over_time:
        aliases_over_time = parser_state.existing_logic.wire_aliases_over_time[
            base_var_name
        ]
    driving_aliases_over_time += aliases_over_time

    # Does most recent alias cover entire wire?
    # Break orig wire name to all branches
    # print "ref_toks",ref_toks
    entire_tree_ref_toks_set = REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(
        ref_toks, c_ast_ref, parser_state
    )
    if debug:
        print("ref_toks to logic", ref_toks)
        print("entire_tree_ref_toks_set", entire_tree_ref_toks_set)
    # print ""

    # sys.exit(-1)
    if len(driving_aliases_over_time) == 0:
        # if debug:
        # print "=="
        # print "func name",parser_state.existing_logic.func_name
        # print "ref_toks",ref_toks
        # print "driving_aliases_over_time",driving_aliases_over_time
        # print "entire_tree_ref_toks_set",entire_tree_ref_toks_set
        # print "No driving aliases?", prepend_text, c_ast_ref.coord
        # print 0/0
        print(ref_toks, "not fully driven when read at?", c_ast_ref.coord)
        sys.exit(-1)

    # Find the first alias (IN REVERSE ORDER) that elminates some branches
    remaining_ref_toks_set = set(entire_tree_ref_toks_set)
    i = len(driving_aliases_over_time) - 1
    first_driving_alias = None
    while len(remaining_ref_toks_set) == len(entire_tree_ref_toks_set):
        if i < 0:
            print("Ran out of aliases?")
            print("func name", parser_state.existing_logic.func_name)
            print("ref_toks", ref_toks)
            print("entire_tree_ref_toks_set", entire_tree_ref_toks_set)
            print("driving_aliases_over_time", driving_aliases_over_time)
            print("remaining_ref_toks_set", remaining_ref_toks_set)
            print(
                "This is either my problem or your code doesnt drive all your local variables..."
            )
            print("Why you so angry at me?")
            print("   The Lemon Twigs - Baby, Baby")
            sys.exit(-1)

        alias = driving_aliases_over_time[i]
        alias_c_type = parser_state.existing_logic.wire_to_c_type[alias]
        alias_driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(alias, parser_state)

        if debug:
            print("maybe first alias#", i, alias)
            print("alias_driven_ref_toks", alias_driven_ref_toks)
            print("orig ref_toks", ref_toks)
            print("pre remaining_ref_toks_set", remaining_ref_toks_set)

        remaining_ref_toks_set = REMOVE_COVERED_REF_TOK_BRANCHES(
            remaining_ref_toks_set, alias_driven_ref_toks, c_ast_ref, parser_state
        )
        # Next alias working backwards
        i = i - 1

        if debug:
            print("post remaining_ref_toks_set", remaining_ref_toks_set)
            print("")

    # At this point alias is first driver
    first_driving_alias = alias
    first_driving_alias_c_type = alias_c_type
    # If all wires elminated because was exact type match then do simple wire assignment
    first_driving_alias_type_match = first_driving_alias_c_type == c_type

    if len(remaining_ref_toks_set) == 0 and first_driving_alias_type_match:
        return APPLY_CONNECT_WIRES_LOGIC(
            parser_state,
            first_driving_alias,
            driven_wire_names,
            prepend_text,
            c_ast_ref,
        )
    else:
        if debug:
            print("ref_toks", ref_toks)
            print("c_type", c_type)
            print("first_driving_alias_c_type", first_driving_alias_c_type)
            print("entire_tree_ref_toks_set", entire_tree_ref_toks_set)
            print("first_driving_alias", first_driving_alias)
            print("remaining_ref_toks_set", remaining_ref_toks_set)

        # Create list of driving aliases
        driving_aliases = []
        # if len(remaining_wires) < len_pre_drive:
        driving_aliases += [first_driving_alias]

        # print "remaining_wires after first alias",remaining_wires

        # Work backwards in alias list starting with next wire
        i = len(driving_aliases_over_time) - 2
        while len(remaining_ref_toks_set) > 0:
            if i < 0:
                """
                print("Ran out of aliases?@@@@@@@")
                print("func name",parser_state.existing_logic.func_name)
                print("starting ref_toks",ref_toks)
                print("c_type",c_type)
                print("expanded entire_tree_ref_toks_set",entire_tree_ref_toks_set)
                print("driving_aliases_over_time",driving_aliases_over_time)
                print("remaining_ref_toks_set",remaining_ref_toks_set)
                #print "="
                #print "first_driving_alias",first_driving_alias
                #print "first_driving_alias_c_type",first_driving_alias_c_type
                print("=")
                print("This is either my problem or your code doesnt drive all your local variables...")
                """
                print(
                    "It looks like struct/array variable like",
                    ref_toks,
                    "from func",
                    parser_state.existing_logic.func_name,
                    "does not have all struct fields / array indices assigned when read at?",
                    c_ast_ref.coord,
                )
                sys.exit(-1)

            alias = driving_aliases_over_time[i]
            alias_driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(alias, parser_state)
            # Then remove all branch wires covered by this driver
            len_pre_drive = len(remaining_ref_toks_set)

            if debug:
                print("alias#", i, alias)
                print("alias_driven_ref_toks", alias_driven_ref_toks)
                print("orig ref_toks", ref_toks)
                print("pre remaining_ref_toks_set", remaining_ref_toks_set)

            remaining_ref_toks_set = REMOVE_COVERED_REF_TOK_BRANCHES(
                remaining_ref_toks_set, alias_driven_ref_toks, c_ast_ref, parser_state
            )

            if debug:
                print("post remaining_ref_toks_set", remaining_ref_toks_set)
                print("")

            # Record this alias as driver if it drove wires
            if len(remaining_ref_toks_set) < len_pre_drive:
                driving_aliases += [alias]

            # Next alias working backwards
            i = i - 1

        # Reverse order of drivers
        driving_aliases = driving_aliases[::-1]

        # print "func_inst_name",func_inst_name
        # print "driving_aliases_over_time",driving_aliases_over_time
        # print "first_driving_alias",first_driving_alias
        # print "ref driving aliases",driving_aliases

        # Needs ref read function
        # Name needs ot include the ref being done

        # Constant ref ?
        # Variable ref needs different func name but mostly same args
        prefix = LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX
        if not C_AST_REF_TOKS_ARE_CONST(ref_toks):
            prefix = LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX

        # NEEDS TO BE LEGIT C FUNC NAME
        # Func name == base name since is custom unique name
        func_name = prefix
        # Cant cache all refs?
        # Fuck it just make names that wont be wrong/overlap
        # Are there built in structs?
        # output type
        # Base type
        # output ref toks --dont include base var name
        # input ref toks  --dont include base var name
        # # ?? not needed, included in output ref toks?  variable dims (If not const)

        # Output type of the ref
        func_name += "_" + c_type.replace("[", "_").replace("]", "")

        # Base type of the ref
        # Dont always have to use base var type?
        # x.y.int[const 2]   driven by array int[4]
        # Same func as
        # somearray[const 2] driven by array int[4]
        base_var_type = parser_state.existing_logic.wire_to_c_type[base_var_name]
        base_var_type_c_name = base_var_type.replace("[", "_").replace("]", "")
        func_name += "_" + base_var_type_c_name

        # Output ref toks
        for ref_tok in ref_toks[1:]:  # Skip base var name
            if type(ref_tok) is int:
                func_name += "_" + str(ref_tok)
            elif type(ref_tok) is str:
                func_name += "_" + ref_tok
            elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                func_name += "_" + "VAR"
            else:
                print("What is ref tok?", ref_tok)
                sys.exit(-1)

        # Need to condense c_ast_ref in function name since too big for file name?
        # Bleh? TODO later and solve for bigger reasons?
        # Damnit cant postpone
        # Build list of driven ref toks and reduce
        driven_ref_toks_list = []
        for driving_alias in driving_aliases:
            driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(driving_alias, parser_state)
            driven_ref_toks_list.append(driven_ref_toks)
        # Reduce
        reduced_driven_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(
            driven_ref_toks_list, c_ast_ref, parser_state
        )
        sorted_reduced_driven_ref_toks_set = sorted(reduced_driven_ref_toks_set)

        # Sanity
        if len(sorted_reduced_driven_ref_toks_set) <= 0:
            print("Wtf no sorted input ref toks for ref read @", c_ast_ref.coord)
            sys.exit(-1)
        if len(driven_ref_toks_list) <= 0:
            print("Wtf no input ref toks for ref read @", c_ast_ref.coord)
            sys.exit(-1)

        """ SHOULDNT NEED SINCE HASHED
        # Func name built with reduced list
        for driven_ref_toks in sorted_reduced_driven_ref_toks_set:
            for ref_tok in driven_ref_toks[1:]:  # Skip base var name
                if type(ref_tok) == int:
                    func_name += "_" + str(ref_tok)
                elif type(ref_tok) == str:
                    func_name += "_" + ref_tok
                elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                    func_name += "_" + "VAR"
                else:
                    print("What is ref tok bleh?", ref_tok)
                    sys.exit(-1)
        """

        # APPEND HASH to account for differences when not reduced name
        # BLAGH
        # Ref toks driven by aliases
        input_ref_toks_str = ""
        for driven_ref_toks in driven_ref_toks_list:
            for ref_tok in driven_ref_toks[1:]:  # Skip base var name
                if type(ref_tok) is int:
                    input_ref_toks_str += "_INT_" + str(ref_tok)
                elif type(ref_tok) is str:
                    input_ref_toks_str += "_STR_" + ref_tok
                elif not C_AST_REF_TOK_IS_CONST(ref_tok):
                    input_ref_toks_str += "_" + "VAR"
                else:
                    print("What is ref tok bleh????", ref_tok)
                    sys.exit(-1)
        # Hash the string
        hash_ext = (
            "_" + ((hashlib.md5(input_ref_toks_str.encode("utf-8")).hexdigest())[0:4])
        )  # 4 chars enough?
        func_name += hash_ext

        # Get inst name
        func_base_name = func_name  # Is unique
        func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_ref)
        if debug:
            print("REF FUNC NAME:", func_name)
            print("REF INST NAME:", func_inst_name)
        # Save ref toks for this ref submodule
        parser_state.existing_logic.ref_submodule_instance_to_ref_toks[
            func_inst_name
        ] = ref_toks[:]

        # Input wire is most recent copy of input ID node

        # N input port names named by their arg name
        # Decompose inputs to N ARG FUNCTION
        input_drivers = []  # Wires or C ast nodes
        input_driver_types = []  # Might be none if not known
        input_port_names = []  # Port names on submodule

        # Each of those aliases drives an input port
        # Var ref is implemented in C, then must be C safe (just do same for const ref too , why not)
        ref_toks_i = 0
        parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
            func_inst_name
        ] = []
        for driving_alias in driving_aliases:
            # print "driving_alias",driving_alias
            # Build an input port name based off the tokens this alias drives?
            driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(driving_alias, parser_state)
            driving_alias_type = parser_state.existing_logic.wire_to_c_type[
                driving_alias
            ]

            # This is strange... ref tok to c type resolves to constant type
            # Type for this maybe variable refence wire might be weird non constant array thing
            # use type of driving alias instead of ref to c type?
            # ref_tok_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(driven_ref_toks, c_ast_ref, parser_state)

            # if base variable then call it base
            # if len(driven_ref_toks) == 1:
            # input_port_name = "base_var"
            input_port_name = "ref_toks_" + str(ref_toks_i)
            ref_toks_i += 1
            input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            # Remember using driving wire not c ast node  (since doing use_input_nodes_fuck_it = False)
            # print "driving_alias",driving_alias
            # print "drives:"
            # print "input_port_wire",input_port_wire
            input_drivers.append(driving_alias)
            input_driver_types.append(driving_alias_type)
            input_port_names.append(input_port_name)

            # SET ref_submodule_instance_to_input_port_driven_ref_toks
            parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
                func_inst_name
            ].append(driven_ref_toks)

        # print "ref_toks",ref_toks
        # Variable dimensions come after
        (
            var_dim_ref_tok_indices,
            var_dims,
            var_dim_iter_types,
        ) = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(
            ref_toks, c_ast_ref, parser_state
        )
        if debug:
            print("var_dim_ref_tok_indices", var_dim_ref_tok_indices)
            print("var_dims", var_dims)
            print("var_dim_iter_types", var_dim_iter_types)
        for var_dim_i in range(0, len(var_dims)):
            ref_tok_index = var_dim_ref_tok_indices[var_dim_i]
            var_dim_iter_type = var_dim_iter_types[var_dim_i]
            ref_tok_c_ast_node = ref_toks[ref_tok_index]
            # Sanity check
            if C_AST_REF_TOK_IS_CONST(ref_tok_c_ast_node):
                print("Not a variable ref tok?2", ref_tok_c_ast_node)
                sys.exit(-1)

            # Say which variable index this is
            input_port_name = "var_dim_" + str(var_dim_i)
            input_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name

            # Set type of input wire
            parser_state.existing_logic.wire_to_c_type[input_wire] = var_dim_iter_types[
                var_dim_i
            ]

            # Make the c_ast node drive the input wire
            input_connect_logic = C_AST_NODE_TO_LOGIC(
                ref_tok_c_ast_node, [input_wire], prepend_text, parser_state
            )
            # Merge this connect logic
            parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)

            # What drives the input port?
            driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]

            # Save this
            input_drivers.append(driving_wire)
            input_driver_types.append(var_dim_iter_type)
            input_port_names.append(input_port_name)

        # Can't.shouldnt rely on uint resizing to occur in the raw vhdl (for const ref)
        # So force output to be same type as ref would imply

        # Output wire is the type of the struct ref
        output_port_name = LOGIC.RETURN_WIRE_NAME

        # Output wire is the type of the ref rd
        output_c_type = c_type
        # Variable ref reads are implemented in C
        # and so cant have an output type of an array type
        # Use auto gen struct array types
        if not C_AST_REF_TOKS_ARE_CONST(ref_toks) and LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            output_struct_array_type = (
                elem_t.replace("[", "_").replace("]", "_").replace("__", "_").strip("_")
                + "_array"
            )
            for dim in dims:
                output_struct_array_type += "_" + str(dim)
            output_struct_array_type += "_t"
            output_c_type = output_struct_array_type

        output_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + output_port_name
        parser_state.existing_logic.wire_to_c_type[output_wire] = output_c_type
        # Don't set type of output wire - shouldnt need to?

        # DO THE N ARG FUNCTION
        func_c_ast_node = c_ast_ref
        base_name_is_name = True
        func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            func_c_ast_node,
            func_base_name,
            base_name_is_name,
            input_drivers,  # Wires or C ast nodes
            input_driver_types,  # Might be none if not known
            input_port_names,  # Port names on submodule
            driven_wire_names,
            parser_state,
        )

        parser_state.existing_logic = func_logic

        # After a constant reference read insert new alias?

        return func_logic


def GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(input_array_type):
    elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type)
    output_dims = dims[1:]
    output_type = elem_type
    for output_dim in output_dims:
        output_type = output_type + "[" + str(output_dim) + "]"

    return output_type
        # return True


def ID_IS_ENUM_CONST(c_ast_id, existing_logic, prepend_text, parser_state):
    # Get ref tokens
    base_name = str(c_ast_id.name)
    ref_toks = (base_name,)

    # Will not be:
    # (this is dumb)
    #   known to enum const
    # input
    # global
    #   volatile global
    # variable
    #   output
    #
    # Then must be ENUM
    if (
        (base_name in existing_logic.wire_to_c_type)
        and LOGIC.C_TYPE_IS_ENUM(existing_logic.wire_to_c_type[base_name], parser_state)
        and LOGIC.WIRE_IS_CONSTANT(base_name)
    ):
        return True
    elif base_name in existing_logic.inputs:
        return False
    elif (
        (base_name in existing_logic.state_regs)
        or (base_name in existing_logic.read_only_global_wires)
        or (base_name in existing_logic.write_only_global_wires)
    ):
        return False
    elif base_name in existing_logic.variable_names:
        return False
    elif base_name in existing_logic.outputs:
        return False
    else:
        # Check that is one of the enum consts available at least :(
        for enum_type in parser_state.enum_info_dict:
            ids = parser_state.enum_info_dict[enum_type].id_to_int_val.keys()
            for id_str in ids:
                if id_str == base_name:
                    return True
        return False


# ENUM is like constant
def C_AST_ENUM_CONST_TO_LOGIC(
    c_ast_node, driven_wire_names, prepend_text, parser_state
):
    # Create wire for this constant
    # wire_name =  CONST_PREFIX + str(c_ast_node.type)+ "_"+ str(c_ast_node.value)
    value = str(c_ast_node.name)

    # casthelp(c_ast_node)
    # print "value",value
    # print "==="
    # Hacky use $ for enum only oh sad
    # Um how did this work before?
    wire_name = (
        LOGIC.CONST_PREFIX + str(value) + LOGIC.ENUM_CONST_MARKER + C_AST_NODE_COORD_STR(c_ast_node)
    )

    # Try to set type based on enum name, might not be possible if multiple matches
    # Then have to rely on user comparing against known enum type wire
    enum_type = None
    enum_name_matches = 0
    for enum, enum_info in parser_state.enum_info_dict.items():
        if value in enum_info.id_to_int_val.keys():
            enum_type = enum
            enum_name_matches += 1
    if enum_name_matches == 1:
        parser_state.existing_logic.wire_to_c_type[wire_name] = enum_type
        for driven_wire_name in driven_wire_names:
            if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
                parser_state.existing_logic.wire_to_c_type[driven_wire_name] = enum_type

    # flag to not check types /cast in APPLY_CONNNECT since dontknow exact enum type?
    # is resolved immediately after? boo enums??
    check_types_do_cast = False
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
        parser_state,
        wire_name,
        driven_wire_names,
        prepend_text,
        c_ast_node,
        check_types_do_cast,
    )

    ### FUCK CAN'T DO ENUM TYPE CHECKING SINCE OPERATORS IMPLEMENTED AS unsigned compare (not num type compare, for pipelining...)
    # Hey yeah this sucks

    return parser_state.existing_logic


def C_AST_COMPOUND_NULL_TO_LOGIC(
    c_ast_node, driven_wire_names, prepend_text, parser_state
):
    # Driven wire needs to have type
    driven_type = None
    for driven_wire_name in driven_wire_names:
        if driven_wire_name in parser_state.existing_logic.wire_to_c_type:
            driven_type = parser_state.existing_logic.wire_to_c_type[driven_wire_name]
    if driven_type is None:
        print("No type information for compound null expression at", c_ast_node.coord)
        sys.exit(-1)
    # Make up a wire name?
    wire_name = LOGIC.BUILD_CONST_WIRE(LOGIC.COMPOUND_NULL, C_AST_NODE_TO_META(c_ast_node))
    parser_state.existing_logic.wire_to_c_type[wire_name] = driven_type
    # Connect the constant to the wire it drives
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
        parser_state, wire_name, driven_wire_names, prepend_text, c_ast_node, False
    )
    return parser_state.existing_logic


# Const jsut makes wire with CONST name
# C ast constants are not enum id constants
def C_AST_CONSTANT_TO_LOGIC(
    c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated=False
):
    value_str = c_ast_node.value
    return NON_ENUM_CONST_VALUE_STR_TO_LOGIC(
        value_str, c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated
    )


def SUFFIX_C_TYPE_FROM_INT_LITERAL(int_lit):
    if int_lit.upper().endswith("UZZ"):
        return "size_t"
    elif int_lit.upper().endswith("Z"):
        return "size_t"
    elif int_lit.upper().endswith("ULL"):
        return "uint64_t"
    elif int_lit.upper().endswith("LL"):
        return "int64_t"
    elif int_lit.upper().endswith("UL"):
        return "uint32_t"
    elif int_lit.upper().endswith("L"):
        return "int32_t"
    else:
        return None


def STRIP_INT_LIT_SUFF(int_lit):
    return int_lit.strip("LL").strip("U").strip("u").strip("L")


def C_CONST_STR_TO_STR_VALUE(c_const_str):
    s = c_const_str[:]
    s = s.replace("\\n", "\n")
    s = s.replace("\\t", "\t")
    return s


def NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
    value_str, c_ast_node, is_negated=False, expected_c_type=None
):
    value_str_no_suff = STRIP_INT_LIT_SUFF(value_str)
    if value_str.lower().startswith("0x"):
        hex_str = value_str_no_suff.lower().replace("0x", "")
        suff_c_type = SUFFIX_C_TYPE_FROM_INT_LITERAL(value_str)
        c_type_str = None
        if suff_c_type:
            c_type_str = suff_c_type
        hex_str = STRIP_INT_LIT_SUFF(hex_str)
        value = int(hex_str, 16)
        if not c_type_str:
            bits = value.bit_length()
            if bits == 0:
                bits = 1
            # If user provides extra bits then use them
            if bits < len(hex_str) * 4:
                bits = len(hex_str) * 4
            if is_negated:
                c_type_str = "int" + str(bits + 1) + "_t"
            else:
                c_type_str = "uint" + str(bits) + "_t"
    elif value_str.lower().startswith("0b"):
        bin_str = value_str.lower().replace("0b", "")
        suff_c_type = SUFFIX_C_TYPE_FROM_INT_LITERAL(bin_str)
        c_type_str = None
        if suff_c_type:
            c_type_str = suff_c_type
        bin_str = STRIP_INT_LIT_SUFF(bin_str)
        value = int(bin_str, 2)
        if not c_type_str:
            bits = value.bit_length()
            if bits == 0:
                bits = 1
            # If user provides extra bits then use them
            if bits < len(bin_str):
                bits = len(bin_str)
            if is_negated:
                c_type_str = "int" + str(bits + 1) + "_t"
            else:
                c_type_str = "uint" + str(bits) + "_t"
    elif value_str_no_suff.isdigit():
        suff_c_type = SUFFIX_C_TYPE_FROM_INT_LITERAL(value_str)
        value_str = value_str_no_suff
        value = int(value_str)
        if suff_c_type:
            c_type_str = suff_c_type
        else:
            bits = value.bit_length()
            if bits == 0:
                bits = 1
            if is_negated:
                c_type_str = "int" + str(bits + 1) + "_t"
            else:
                c_type_str = "uint" + str(bits) + "_t"
    elif value_str.startswith(
        "'"
    ):  # type(c_ast_node) == c_ast.Constant and c_ast_node.type=='char':
        # value is expected to be integer like for negating (doesnt make sense for str), for char it does
        value = value_str.strip("'")
        # c_type_str = "char"
        # print "Char val", value
        c_type_str = "uint8_t"
        value = ord(value)
    elif value_str.startswith(
        '"'
    ):  # type(c_ast_node) == c_ast.Constant and c_ast_node.type=='string':
        value = value_str.strip('"')
        actual_str = C_CONST_STR_TO_STR_VALUE(value)
        c_type_str = "char[" + str(len(actual_str)) + "]"
    elif (
        (type(c_ast_node) == c_ast.Constant and c_ast_node.type == "float")
        or ("." in value_str)
        or (value_str.lower().endswith("f"))
        or (value_str.lower().endswith("l"))
        or (expected_c_type is not None and LOGIC.C_TYPE_IS_FLOAT_TYPE(expected_c_type))
    ):
        value = float(value_str.strip("f").strip("l").strip("F").strip("L"))
        c_type_str = "float"
    elif "e" in value_str:
        # Scientific notation
        float_val = float(value_str)
        if float_val.is_integer():
            raise Exception(
                f"TODO unhandled exponent integer constant.. {value_str} {type(c_ast_node)} {c_ast_node}"
            )
        else:
            value = float_val
            c_type_str = "float"
    else:
        print("What type of constant is?", value_str, type(c_ast_node), c_ast_node)
        print(0 / 0)
        sys.exit(-1)

    if is_negated:
        value = value * -1

    # print("value,c_type_str",value_str,value,c_type_str)

    return value, c_type_str


def NON_ENUM_CONST_VALUE_STR_TO_LOGIC(
    value_str,
    c_ast_node,
    driven_wire_names,
    prepend_text,
    parser_state,
    is_negated=False,
    known_c_type=None,
):
    # Try to absorb type from known driven wires
    if known_c_type is None:
        for driven_wire in driven_wire_names:
            if driven_wire in parser_state.existing_logic.wire_to_c_type:
                known_c_type = parser_state.existing_logic.wire_to_c_type[driven_wire]

    # Determine type if needed
    wire_name = LOGIC.BUILD_CONST_WIRE(value_str, C_AST_NODE_TO_META(c_ast_node), is_negated)
    if known_c_type is None:
        value, c_type_str = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
            value_str, c_ast_node, is_negated
        )
        if (
            c_type_str is not None
        ):  # and (wire_name not in parser_state.existing_logic.wire_to_c_type):
            parser_state.existing_logic.wire_to_c_type[wire_name] = c_type_str
    else:
        parser_state.existing_logic.wire_to_c_type[wire_name] = known_c_type

    # Set type of driven wires if not yet set
    for driven_wire_name in driven_wire_names:
        if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driven_wire_name] = (
                parser_state.existing_logic.wire_to_c_type[wire_name]
            )

    # Connect the constant to the wire it drives
    # print("connecting",wire_name, driven_wire_names,parser_state.existing_logic.wire_to_c_type[wire_name])
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
        parser_state, wire_name, driven_wire_names, prepend_text, c_ast_node
    )
    # print("connected",wire_name,"type",parser_state.existing_logic.wire_to_c_type[wire_name])

    return parser_state.existing_logic


def C_AST_STATIC_NON_CONST_DECL_TO_LOGIC(
    c_ast_static_decl, prepend_text, parser_state, state_reg_var, c_type
):
    # Like a global variable

    # Dont make new state reg info, use existing from earlier pass
    # var_info = VariableInfo()
    var_info = parser_state.func_to_local_state_regs[
        parser_state.existing_logic.func_name
    ][state_reg_var]
    var_info.name = state_reg_var
    var_info.type_name = c_type
    var_info.init = c_ast_static_decl.init  # Static init must be const?
    var_info.resolved_const_str = RESOLVE_C_AST_NODE_TO_CONSTANT_STR(
        c_ast_static_decl.init, prepend_text, parser_state
    )
    var_info.is_volatile = "volatile" in c_ast_static_decl.quals
    var_info.is_static_local = True

    # Copy info into existing_logic
    parser_state.existing_logic.state_regs[state_reg_var] = var_info
    # Record using non vol state
    if not var_info.is_volatile:
        parser_state.existing_logic.uses_nonvolatile_state_regs = True

    return parser_state.existing_logic


def C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(c_ast_decl, parser_state):
    if not hasattr(c_ast_decl, "type"):
        raise Exception(f"No type on variable?: {c_ast_decl.coord}")
    if type(c_ast_decl.type) is c_ast.ArrayDecl:
        c_ast_array_decl = c_ast_decl.type
        name, elem_type, dim = C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(
            c_ast_array_decl, parser_state
        )
        wire_name = name
        c_type = elem_type + "[" + str(dim) + "]"
    elif type(c_ast_decl.type) is c_ast.TypeDecl:
        c_ast_typedecl = c_ast_decl.type
        wire_name = c_ast_decl.name
        c_type = c_ast_typedecl.type.names[0]
    elif type(c_ast_decl.type) is c_ast.PtrDecl:
        c_ast_typedecl = c_ast_decl.type.type  # one type node lower down
        wire_name = c_ast_decl.name
        print(f"Ignoring pointer declaration: {wire_name} {c_ast_decl.type.coord}")
        # c_type = c_ast_typedecl.type.names[0]
        c_type = None
    else:
        raise Exception(
            f"C_AST_DECL_TO_C_TYPE_AND_VAR_NAME {c_ast_decl} {c_ast_decl.type.coord}"
        )
    return c_type, wire_name


def C_AST_NODE_IS_COMPOUND_NULL(c_ast_node):
    return (
        type(c_ast_node) is c_ast.InitList
        and len(c_ast_node.exprs) == 1
        and type(c_ast_node.exprs[0]) is c_ast.Constant
        and c_ast_node.exprs[0].value == "0"
    )


def C_AST_INIT_LIST_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # print(c_ast_node)
    # print("drives",driven_wire_names)
    for driven_wire_name in driven_wire_names:
        # Init/drive driven wire
        lhs_ref_toks = parser_state.existing_logic.alias_to_driven_ref_toks[
            driven_wire_name
        ]
        c_type = parser_state.existing_logic.wire_to_c_type[driven_wire_name]
        parser_state.existing_logic = C_AST_INIT_TO_LOGIC(
            c_ast_node, lhs_ref_toks, c_ast_node, c_type, prepend_text, parser_state
        )
    return parser_state.existing_logic


def C_AST_INIT_TO_LOGIC(
    c_ast_init, lhs_ref_toks, lhs_c_ast_node, c_type, prepend_text, parser_state
):
    # All inits start with null
    const_zero = c_ast.Constant(type="int", value="0")
    fake_compound_null_init_node = c_ast.InitList(exprs=[const_zero])
    fake_compound_null_init_node.coord = c_ast_init.coord
    parser_state.existing_logic = C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(
        lhs_ref_toks,
        lhs_c_ast_node,
        fake_compound_null_init_node,
        parser_state,
        prepend_text,
        None,
    )
    # parser_state.existing_logic = C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(lhs_ref_toks, lhs_c_ast_node, c_ast_init, parser_state, prepend_text, None)
    # If just null then return now
    # = {0}; // Is special null token
    if C_AST_NODE_IS_COMPOUND_NULL(c_ast_init):
        return parser_state.existing_logic

    # Each thing in init list is either position based, [index], .member
    pos = 0
    # Shared logic for 1 or more init exprs
    if type(c_ast_init) == c_ast.InitList:
        init_exprs = c_ast_init.exprs
    else:
        init_exprs = [c_ast_init]
    for init_expr in init_exprs:
        # What is expected for this expression given type?
        ref_toks = None
        expr_node = None
        if type(c_ast_init) == c_ast.InitList and LOGIC.C_TYPE_IS_ARRAY(c_type):
            # Array
            elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            expr_node = init_expr
            expr_type = elem_t
            # Assign this pos in array, or specified pos
            if type(init_expr) == c_ast.NamedInitializer:
                # pos name
                pos = int(init_expr.name[0].value)
                expr_node = init_expr.expr
            ref_toks = lhs_ref_toks + (pos,)
            parser_state.existing_logic = C_AST_INIT_TO_LOGIC(
                expr_node,
                ref_toks,
                lhs_c_ast_node,
                expr_type,
                prepend_text,
                parser_state,
            )
        elif type(c_ast_init) == c_ast.InitList and LOGIC.C_TYPE_IS_STRUCT(
            c_type, parser_state
        ):
            # Struct
            field_type_dict = parser_state.struct_to_field_type_dict[c_type]
            field_names_list = list(field_type_dict.keys())
            field_types_list = list(field_type_dict.values())
            expr_node = init_expr
            # Assign to specified member or by pos in member list
            if type(init_expr) == c_ast.NamedInitializer:
                # Field name based
                member_name = init_expr.name[0].name
                pos = field_names_list.index(member_name)
                expr_type = field_type_dict[member_name]
                expr_node = init_expr.expr
            else:
                # Position based
                expr_type = field_types_list[pos]
                member_name = field_names_list[pos]
            ref_toks = lhs_ref_toks + (member_name,)
            parser_state.existing_logic = C_AST_INIT_TO_LOGIC(
                expr_node,
                ref_toks,
                lhs_c_ast_node,
                expr_type,
                prepend_text,
                parser_state,
            )
        elif type(c_ast_init) == c_ast.InitList:
            print(
                "Type",
                c_type,
                "does not appear to use initialization lists?",
                c_ast_init.coord,
            )
            sys.exit(-1)
        else:
            # Simple var
            expr_type = c_type
            expr_node = init_expr
            ref_toks = tuple(lhs_ref_toks)
            # Do assignment
            parser_state.existing_logic = C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(
                ref_toks, lhs_c_ast_node, expr_node, parser_state, prepend_text, None
            )

        # Update for next expr
        pos += 1

    return parser_state.existing_logic


def C_AST_DECL_LIST_TO_LOGIC(c_ast_node, prepend_text, parser_state):
    # Apparently just a list of decls...
    for decl in c_ast_node.decls:
        parser_state.existing_logic = C_AST_DECL_TO_LOGIC(
            decl, prepend_text, parser_state
        )
    return parser_state.existing_logic


def C_AST_DECL_TO_LOGIC(c_ast_decl, prepend_text, parser_state):
    c_type, wire_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(c_ast_decl, parser_state)
    # This is a variable declaration
    parser_state.existing_logic.wire_to_c_type[wire_name] = c_type
    parser_state.existing_logic.wires.add(wire_name)
    parser_state.existing_logic.variable_names.add(wire_name)

    # Non const statics are registers - handled differently from comb logic
    if "static" in c_ast_decl.storage and "const" not in c_ast_decl.quals:
        return C_AST_STATIC_NON_CONST_DECL_TO_LOGIC(
            c_ast_decl, prepend_text, parser_state, wire_name, c_type
        )

    # Variable should have no assignments to it at time of declaration
    # A repeated declaration is the same as clearing assignments
    if wire_name in parser_state.existing_logic.wire_aliases_over_time:
        parser_state.existing_logic.wire_aliases_over_time[wire_name] = []

    # If has init value then is also assignment
    if c_ast_decl.init is not None:
        lhs_ref_toks = (wire_name,)
        parser_state.existing_logic = C_AST_INIT_TO_LOGIC(
            c_ast_decl.init,
            lhs_ref_toks,
            c_ast_decl.type,
            c_type,
            prepend_text,
            parser_state,
        )
    else:
        # No init but all vars init to zeros by default (like statics do)
        const_zero = c_ast.Constant(type="int", value="0")
        fake_compound_null_init_node = c_ast.InitList(exprs=[const_zero])
        fake_compound_null_init_node.coord = c_ast_decl.coord
        lhs_ref_toks = (wire_name,)
        parser_state.existing_logic = C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(
            lhs_ref_toks,
            c_ast_decl.type,
            fake_compound_null_init_node,
            parser_state,
            prepend_text,
            None,
        )

    return parser_state.existing_logic


def C_AST_COMPOUND_TO_LOGIC(c_ast_compound, prepend_text, parser_state):
    existing_logic = parser_state.existing_logic

    # How to handle assignment over time?
    # Use function that merges logic over time
    # MERGE_SEQUENTIAL_LOGIC
    # TODO: Do this every place merge logic is used? probabhly not
    # Assumption: Compound logic block items imply execution order
    rv = existing_logic
    if existing_logic is None:
        rv = LOGIC.Logic()

    if c_ast_compound.block_items is not None:
        for block_item in c_ast_compound.block_items:
            # print "block_item in c_ast_compound.block_items"
            # casthelp(block_item)
            # print '"leading_zeros" in rv.wire_to_c_type', ("leading_zeros" in rv.wire_to_c_type)
            # print "block_item",block_item
            parser_state.existing_logic = rv
            driven_wire_names = []
            item_logic = C_AST_NODE_TO_LOGIC(
                block_item, driven_wire_names, prepend_text, parser_state
            )
            prev_logic = rv
            next_logic = item_logic

            # print "MERGING block item sequentially"
            # print "PRE SEQ MERGE rv.wire_drives", rv.wire_drives
            # print "PRE SEQ MERGE rv.wire_driven_by", rv.wire_driven_by

            prev_logic.MERGE_SEQ_LOGIC(next_logic)
            rv = prev_logic

            # Update parser state since merged in exsiting logic
            parser_state.existing_logic = rv

            # print str(block_item)
            # print "rv.wire_drives", rv.wire_drives
            # print "rv.wire_driven_by", rv.wire_driven_by

    return rv


# C AST nodes from different parsing runs, i.e. different object, same looking C code will produce different coordinate strings
# This is wtf hacky since comparing C AST nodes has problems too
_C_AST_NODE_COORD_STR_cache = {}


def C_AST_NODE_COORD_STR(c_ast_node):
    # Try cache
    try:
        rv = _C_AST_NODE_COORD_STR_cache[c_ast_node]
        # print "_C_AST_NODE_COORD_STR_cache"
        return rv
    except:
        pass

    c_ast_node_cord = c_ast_node.coord

    # pycparser doesnt actually do column numbers right
    # But string representation of node is correct and can be hashed
    str_to_hash = str(
        c_ast_node
    )  # Doesnt actually identify nodes, nor does coord, see LOGIC.AST_META_VAL_UNIQUE_KEY_DICT_MERGE
    if TEMP_HACKY_C_AST_NODE_ID:
        str_to_hash = str(id(c_ast_node))
    hash_ext = (
        "_"
        + (hashlib.md5(str_to_hash.encode("utf-8")).hexdigest())[0:LOGIC.C_AST_NODE_HASH_LEN]
    )  # 4 chars enough?

    file_coord_str = (
        str(c_ast_node_cord.file)
        + "_l"
        + str(c_ast_node_cord.line)
        + "_c"
        + str(c_ast_node_cord.column)
        + hash_ext
    )
    # Get leaf name (just stem file name of file hierarcy)
    toks = file_coord_str.split("/")
    toks.reverse()
    file_coord_str = toks[0]
    # file_coord_str = LEAF_NAME(file_coord_str)
    # file_coord_str = file_coord_str.replace(".","_").replace(":","_")
    # file_coord_str = file_coord_str.replace(":","_")
    # Lose readability for sake of having DOTs mean struct ref in wire names
    file_coord_str = file_coord_str.replace(".", "_")

    # if file_coord_str in _C_AST_NODE_COORD_STR_cache.values():
    # casthelp(c_ast_node) NO PARENT NDOES
    # print(id(c_ast_node), file_coord_str)

    # Save cache
    _C_AST_NODE_COORD_STR_cache[c_ast_node] = file_coord_str

    return file_coord_str


def C_AST_NODE_TO_META(c_ast_node):
    """Wrap a raw pycparser node in ASTMeta using the same hash as C_AST_NODE_COORD_STR."""
    cord = c_ast_node.coord
    str_to_hash = str(id(c_ast_node)) if TEMP_HACKY_C_AST_NODE_ID else str(c_ast_node)
    hash_suffix = (
        "_" + hashlib.md5(str_to_hash.encode("utf-8")).hexdigest()[:LOGIC.C_AST_NODE_HASH_LEN]
    )
    return LOGIC.ASTMeta(
        src_file=str(cord.file) if cord else "",
        line=cord.line if cord else 0,
        col=cord.column if cord else 0,
        end_col=None,
        hash_suffix=hash_suffix,
        raw=c_ast_node,
    )


def C_AST_FOR_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # Do init first
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
        c_ast_node.init, [], prepend_text, parser_state
    )

    # Repeatedly:
    #   // Evaluate condition
    #   if cond:
    #     body statement
    #     next statement
    i = 0
    while True:
        # Separate the duplicated logic with identifying prepend text
        iter_prepend_text = (
            prepend_text
            + "FOR_"
            + C_AST_NODE_COORD_STR(c_ast_node)
            + "_ITER_"
            + str(i)
            + "_"
        )
        # Evaluate condition driving a dummy wire so we can recover the value?
        cond_val = None
        COND_DUMMY = iter_prepend_text + "COND_DUMMY"
        parser_state.existing_logic.wire_to_c_type[COND_DUMMY] = LOGIC.BOOL_C_TYPE
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.cond, [COND_DUMMY], iter_prepend_text, parser_state
        )
        const_cond_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
            COND_DUMMY, parser_state.existing_logic
        )
        if const_cond_wire is None:
            print(
                "Unsupported for loop condition (missing FSM __clk()?) at",
                c_ast_node.cond.coord,
                "iteration",
                i,
            )
            sys.exit(-1)
        cond_val = int(
            LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_cond_wire, parser_state.existing_logic, parser_state
            )
        )

        # Now that constant condition evaluated
        # Remove dummy COND wire and anything driving it / driven by it?
        parser_state.existing_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(
            COND_DUMMY, parser_state
        )

        # If the condition is true, do an iteration of the body statement
        # Otherwise stop loop
        if not cond_val:
            break

        # Do body statement
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.stmt, [], iter_prepend_text, parser_state
        )

        # Do next statement
        i = i + 1
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.next, [], iter_prepend_text, parser_state
        )

    return parser_state.existing_logic


def C_AST_WHILE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # Repeatedly:
    #   if cond:
    #     body statement
    #
    i = 0
    while True:
        # Separate the duplicated logic with identifying prepend text
        iter_prepend_text = (
            prepend_text
            + "WHILE_"
            + C_AST_NODE_COORD_STR(c_ast_node)
            + "_ITER_"
            + str(i)
            + "_"
        )
        # Evaluate condition driving a dummy wire so we can recover the value?
        cond_val = None
        COND_DUMMY = iter_prepend_text + "COND_DUMMY"
        parser_state.existing_logic.wire_to_c_type[COND_DUMMY] = LOGIC.BOOL_C_TYPE
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.cond, [COND_DUMMY], iter_prepend_text, parser_state
        )
        const_cond_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
            COND_DUMMY, parser_state.existing_logic
        )
        if const_cond_wire is None:
            print(
                "Unsupported while loop condition (missing FSM __clk()?) at",
                c_ast_node.cond.coord,
                "iteration",
                i,
            )
            sys.exit(-1)
        cond_val = int(
            LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_cond_wire, parser_state.existing_logic, parser_state
            )
        )

        # Now that constant condition evaluated
        # Remove dummy COND wire and anything driving it / driven by it?
        parser_state.existing_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(
            COND_DUMMY, parser_state
        )

        # If the condition is true, do an iteration of the body statement
        # Otherwise stop loop
        if not cond_val:
            break

        # Do body statement
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.stmt, [], iter_prepend_text, parser_state
        )

        # Next iteration
        i = i + 1

    return parser_state.existing_logic


# Helper for if(cond) meaning if(cond!=0)
def C_AST_BOOL_COND_NODE_TO_LOGIC(
    c_ast_node_cond, driven_wire_names, prepend_text, parser_state
):
    # Like cond!=0 op
    # Do as AST manip like C_AST_AUG_ASSIGNMENT_TO_RHS_LOGIC
    op = "!="
    const_zero = c_ast.Constant(type="int", value="0")
    const_zero.coord = c_ast_node_cond.coord
    fake_bin_op = c_ast.BinaryOp(op, left=c_ast_node_cond, right=const_zero)
    fake_bin_op.coord = c_ast_node_cond.coord
    return C_AST_BINARY_OP_TO_LOGIC(
        fake_bin_op, driven_wire_names, prepend_text, parser_state
    )


def C_AST_TERNARY_OP_TO_LOGIC(
    c_ast_node, driven_wire_names, prepend_text, parser_state
):
    # Logic is MUX with SEL, TRUE, and FALSE logic connected

    # MUX output type is the same as inputs (aside from select)
    # Try to determine types by evaluating input nodes like done for binary ops
    func_base_name = LOGIC.MUX_LOGIC_NAME
    ter_op_cond_input_port_name = c_ast_node.children()[0][0]
    ter_op_true_input_port_name = c_ast_node.children()[1][0]
    ter_op_false_input_port_name = c_ast_node.children()[2][0]
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_node)
    ter_op_cond_input = func_inst_name + LOGIC.SUBMODULE_MARKER + ter_op_cond_input_port_name
    ter_op_true_input = func_inst_name + LOGIC.SUBMODULE_MARKER + ter_op_true_input_port_name
    ter_op_false_input = (
        func_inst_name + LOGIC.SUBMODULE_MARKER + ter_op_false_input_port_name
    )

    # Get logic for condition wire
    parser_state.existing_logic.wire_to_c_type[ter_op_cond_input] = LOGIC.BOOL_C_TYPE
    parser_state.existing_logic = C_AST_BOOL_COND_NODE_TO_LOGIC(
        c_ast_node.cond,
        [ter_op_cond_input],
        prepend_text,
        parser_state,
    )

    # Then evaluate true/false branch input wires
    c_ast_node_to_driven_input_wire_names = OrderedDict()
    c_ast_node_to_driven_input_wire_names[c_ast_node.iftrue] = [ter_op_true_input]
    c_ast_node_to_driven_input_wire_names[c_ast_node.iffalse] = [ter_op_false_input]
    # Set types if known since this is a MUX
    output_type = None
    for driven_wire_name in driven_wire_names:
        if driven_wire_name in parser_state.existing_logic.wire_to_c_type:
            output_type = parser_state.existing_logic.wire_to_c_type[driven_wire_name]
            break
    if output_type:
        parser_state.existing_logic.wire_to_c_type[ter_op_true_input] = output_type
        parser_state.existing_logic.wire_to_c_type[ter_op_false_input] = output_type
    true_input_type = output_type
    false_input_type = output_type
    # Evaluate input nodes
    parser_state.existing_logic = SEQ_C_AST_NODES_TO_LOGIC(
        c_ast_node_to_driven_input_wire_names, prepend_text, parser_state
    )
    input_type = output_type
    # Try to get types from input nodes if needed
    # TYPES MUST MATCH
    if input_type is None:
        true_input_type = None
        if ter_op_true_input in parser_state.existing_logic.wire_to_c_type:
            true_input_type = parser_state.existing_logic.wire_to_c_type[
                ter_op_true_input
            ]
        false_input_type = None
        if ter_op_false_input in parser_state.existing_logic.wire_to_c_type:
            false_input_type = parser_state.existing_logic.wire_to_c_type[
                ter_op_false_input
            ]
        if ter_op_true_input == false_input_type and false_input_type is not None:
            input_type = false_input_type

    # And get wires driving input ports (since evaluated c ast node already)
    ter_op_cond_input_driver = parser_state.existing_logic.wire_driven_by[
        ter_op_cond_input
    ]
    ter_op_true_input_driver = parser_state.existing_logic.wire_driven_by[
        ter_op_true_input
    ]
    ter_op_false_input_driver = parser_state.existing_logic.wire_driven_by[
        ter_op_false_input
    ]

    # Specify mux instance
    base_name_is_name = False  # Append types
    input_port_names = []
    input_port_names.append(ter_op_cond_input_port_name)  # cond
    input_port_names.append(ter_op_true_input_port_name)  # true
    input_port_names.append(ter_op_false_input_port_name)  # false
    input_driver_types = []
    input_driver_types.append(LOGIC.BOOL_C_TYPE)
    input_driver_types.append(true_input_type)
    input_driver_types.append(false_input_type)
    input_drivers = []  # Wires or C ast nodes
    input_drivers.append(ter_op_cond_input_driver)
    input_drivers.append(ter_op_true_input_driver)
    input_drivers.append(ter_op_false_input_driver)

    # Hook up the MUX instance to the logic graph
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        driven_wire_names,
        parser_state,
        output_type,
    )

    for driven_wire_name in driven_wire_names:
        if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driven_wire_name] = output_type

    return parser_state.existing_logic


def C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_ref):
    rv = ""
    # For now only deal with constant
    for i in range(0, len(ref_toks)):
        ref_tok = ref_toks[i]
        if type(ref_tok) is int:
            # Array ref
            rv += "_" + str(ref_tok)
        elif type(ref_tok) is str:
            if i == 0:
                # Base var
                rv += ref_tok
            else:
                # Struct ref
                rv += "_" + ref_tok
        elif not C_AST_REF_TOK_IS_CONST(ref_tok):
            rv += "_" + "VAR"
        else:
            print("What kind of ref is this?", ref_toks, c_ast_ref.coord)
            sys.exit(-1)
    return rv


def C_AST_IF_TO_LOGIC(c_ast_node, prepend_text, parser_state):
    # Each if is just an IF ELSE (no explicit logic for "else if")
    # If logic is MUX with SEL, TRUE, and FALSE logic connected
    # And a bunch of other jazz to resolve assignments over time after the if

    # One submodule MUX instance per variable contains in the if at this location
    # Name comes from location in file
    file_coord_str = C_AST_NODE_COORD_STR(c_ast_node)

    # print("IF",file_coord_str, flush=True)

    # Port names from c_ast

    # Mux select is driven by intermediate shared wire without variable name
    mux_cond_port_name = c_ast_node.children()[0][0]
    mux_intermediate_cond_wire_wo_var_name = (
        prepend_text
        + LOGIC.MUX_LOGIC_NAME
        + "_"
        + file_coord_str
        + "_interm_"
        + mux_cond_port_name
    )
    parser_state.existing_logic.wires.add(mux_intermediate_cond_wire_wo_var_name)
    parser_state.existing_logic.wire_to_c_type[
        mux_intermediate_cond_wire_wo_var_name
    ] = LOGIC.BOOL_C_TYPE
    # Get logic for this if condition with it driving the shared condition wire
    cond_logic = C_AST_BOOL_COND_NODE_TO_LOGIC(
        c_ast_node.cond,
        [mux_intermediate_cond_wire_wo_var_name],
        prepend_text,
        parser_state,
    )
    parser_state.existing_logic.MERGE_SEQ_LOGIC(cond_logic)

    # See if condition is constant - no mux at all
    # Just only parse one branch of the logic as is just a compound statement in line
    const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        mux_intermediate_cond_wire_wo_var_name, parser_state.existing_logic
    )
    if const_driving_wire is not None:
        # print("const_driving_wire",const_driving_wire)
        # ONLY USE ONE BRANCH AND RETURN
        const_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_driving_wire, parser_state.existing_logic, parser_state
        )
        try:
            const_cond_val = int(const_val_str)
        except:
            print("Something weird with constant use in if at:", c_ast_node.coord)
            sys.exit(-1)
        driven_wire_names = []  # The compand branch doesnt drive anything
        # Remove cond wire
        parser_state.existing_logic.wires.remove(mux_intermediate_cond_wire_wo_var_name)
        parser_state.existing_logic.wire_to_c_type.pop(
            mux_intermediate_cond_wire_wo_var_name
        )

        # Remove record of cond being driven
        # DRIVEN BY
        cond_driver = parser_state.existing_logic.wire_driven_by[
            mux_intermediate_cond_wire_wo_var_name
        ]
        parser_state.existing_logic.wire_driven_by.pop(
            mux_intermediate_cond_wire_wo_var_name
        )
        # WIRE DRIVES
        all_wires_driven_by_cond_driver = parser_state.existing_logic.wire_drives[
            cond_driver
        ]
        all_wires_driven_by_cond_driver.remove(mux_intermediate_cond_wire_wo_var_name)
        if len(all_wires_driven_by_cond_driver) > 0:
            parser_state.existing_logic.wire_drives[cond_driver] = (
                all_wires_driven_by_cond_driver
            )
        else:
            parser_state.existing_logic.wire_drives.pop(cond_driver)

        if const_cond_val == 1:
            # TRUE BRANCH ONLY
            # Sanity check?
            if c_ast_node.iftrue is None:
                print("If reduces to true branch but true is none?", c_ast_node.coord)
                sys.exit(-1)
            parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
                c_ast_node.iftrue, driven_wire_names, prepend_text, parser_state
            )
            return parser_state.existing_logic
        else:
            # FALSE BRANCH ONLY
            # Sanity check?
            if c_ast_node.iffalse is not None:
                # print("If reduces to false branch but false is none?", c_ast_node.coord)
                # sys.exit(-1)
                parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
                    c_ast_node.iffalse, driven_wire_names, prepend_text, parser_state
                )
            return parser_state.existing_logic

    # ~~~~~~ NOT A CONSTANT MUX ~~~~~~~~~~ \/
    # Why are port names not constant and instead derived from child names?
    mux_true_port_name = c_ast_node.children()[1][0]
    mux_false_port_name = "iffalse"  # Will this work?
    if len(c_ast_node.children()) >= 3:
        mux_false_port_name = c_ast_node.children()[2][0]

    # Create TRUE and FALSE branch clock enable muxes
    func_base_name = LOGIC.MUX_LOGIC_NAME
    base_name_is_name = False  # Append types
    most_recent_clk_en_wire = parser_state.existing_logic.clock_enable_wires[-1]
    zero_wire = LOGIC.BUILD_CONST_WIRE(str(0), C_AST_NODE_TO_META(c_ast_node))
    parser_state.existing_logic.wire_to_c_type[zero_wire] = LOGIC.BOOL_C_TYPE
    input_port_names = []
    input_port_names.append(mux_cond_port_name)
    input_port_names.append(mux_true_port_name)
    input_port_names.append(mux_false_port_name)
    input_driver_types = []
    input_driver_types.append(LOGIC.BOOL_C_TYPE)
    input_driver_types.append(LOGIC.BOOL_C_TYPE)
    input_driver_types.append(LOGIC.BOOL_C_TYPE)
    # TRUE
    #  mux cond true means clock enable should be on the true mux input
    input_drivers = []
    input_drivers.append(mux_intermediate_cond_wire_wo_var_name)  # Cond Wire
    input_drivers.append(most_recent_clk_en_wire)  # true value is clock enable
    input_drivers.append(zero_wire)  # false value is zero
    # New clock enable wire to be used in TRUE branch
    true_clock_enable_prepend_text = prepend_text + "TRUE_" + LOGIC.CLOCK_ENABLE_NAME + "_"
    true_clock_enable_wire_name = true_clock_enable_prepend_text + "_" + file_coord_str
    output_driven_wire_names = []
    output_driven_wire_names.append(true_clock_enable_wire_name)
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        true_clock_enable_prepend_text,
        c_ast_node.iftrue,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        output_driven_wire_names,
        parser_state,
    )
    # FALSE
    false_clock_enable_prepend_text = prepend_text + "FALSE_" + LOGIC.CLOCK_ENABLE_NAME + "_"
    false_clock_enable_wire_name = (
        false_clock_enable_prepend_text + "_" + file_coord_str
    )
    if len(c_ast_node.children()) >= 3:
        #  mux cond false means clock enable should be on the false mux input
        input_drivers = []
        input_drivers.append(mux_intermediate_cond_wire_wo_var_name)  # Cond Wire
        input_drivers.append(zero_wire)  # true value is zero
        input_drivers.append(most_recent_clk_en_wire)  # false value is clock enable
        # New clock enable wire to be used in TRUE branch
        output_driven_wire_names = []
        output_driven_wire_names.append(false_clock_enable_wire_name)
        parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            false_clock_enable_prepend_text,
            c_ast_node.iffalse,
            func_base_name,
            base_name_is_name,
            input_drivers,  # Wires or C ast nodes
            input_driver_types,  # Might be none if not known
            input_port_names,  # Port names on submodule
            output_driven_wire_names,
            parser_state,
        )

    # Get true/false logic
    # Add prepend text to seperate the two branches into paralel combinational logic
    # Rename each driven wire with inst name and _true or _false
    prepend_text_true = prepend_text
    prepend_text_false = prepend_text
    driven_wire_names = []
    #
    # Should be able to get away with only deep copying existing_logic
    parser_state_for_true = copy.copy(parser_state)
    parser_state_for_true.existing_logic = parser_state.existing_logic.DEEPCOPY()
    # Should be able to get away with only deep copying existing_logic
    parser_state_for_false = copy.copy(parser_state)
    parser_state_for_false.existing_logic = parser_state.existing_logic.DEEPCOPY()

    # TRUE BRANCH
    parser_state_for_true.existing_logic.clock_enable_wires.append(
        true_clock_enable_wire_name
    )
    true_logic = C_AST_NODE_TO_LOGIC(
        c_ast_node.iftrue, driven_wire_names, prepend_text_true, parser_state_for_true
    )
    #
    if len(c_ast_node.children()) >= 3:
        # FALSE BRANCH
        parser_state_for_false.existing_logic.clock_enable_wires.append(
            false_clock_enable_wire_name
        )
        false_logic = C_AST_NODE_TO_LOGIC(
            c_ast_node.iffalse,
            driven_wire_names,
            prepend_text_false,
            parser_state_for_false,
        )
    else:
        # No false branch false logic if identical to existing logic
        false_logic = parser_state.existing_logic.DEEPCOPY()

    # Var names cant be mixed type per C spec
    merge_var_names = true_logic.variable_names | false_logic.variable_names

    # Find out which ref toks parser_state.existing_logic, p.x, p.y etc are driven inside this IF
    # Driving is recorded with aliases over time
    # True and false can share some existing drivings we dont want to consider
    # Loop over each variable
    var_name_2_all_ref_toks_set = {}
    ref_toks_id_str_to_output_wire = {}
    # print "==== IF",file_coord_str,"======="
    for var_name in merge_var_names:
        # Get aliases over time
        # original
        original_aliases = []
        if var_name in parser_state.existing_logic.wire_aliases_over_time:
            original_aliases = parser_state.existing_logic.wire_aliases_over_time[
                var_name
            ]
        # true
        true_aliases = []
        if var_name in true_logic.wire_aliases_over_time:
            true_aliases = true_logic.wire_aliases_over_time[var_name]
        # false
        false_aliases = []
        if var_name in false_logic.wire_aliases_over_time:
            false_aliases = false_logic.wire_aliases_over_time[var_name]
        # Max len
        max_aliases_len = max(len(true_aliases), len(false_aliases))

        # print(var_name, "IF at", c_ast_node.coord)
        # print(var_name, "original_aliases:", original_aliases)
        # print(var_name, "true_aliases",true_aliases)
        # print(var_name, "false_aliases",false_aliases)
        # Ah need to know if var is declared inside if
        # so that we don try to read from it when its not actually in scope?
        # Scope? Whats scope oh no! Radiohead - Everything in its right place
        declared_in_this_if = None
        if var_name in parser_state.existing_logic.state_regs:
            declared_in_this_if = False
        elif var_name in parser_state.existing_logic.write_only_global_wires:
            declared_in_this_if = False
        elif var_name in parser_state.existing_logic.read_only_global_wires:
            declared_in_this_if = False
        elif var_name in parser_state.existing_logic.inputs:
            declared_in_this_if = False
        elif var_name in parser_state.existing_logic.outputs:
            declared_in_this_if = False
        elif var_name not in parser_state.existing_logic.variable_names:
            declared_in_this_if = True
        else:
            # Some existing variable - but from where? Ugh? Judge by aliases on true and false branches?
            declared_in_this_if = (len(original_aliases) == 0) and (
                (len(true_aliases) > 0) or (len(false_aliases) > 0)
            )
        if declared_in_this_if:
            # print(var_name, "declared_in_this_if", c_ast_node.coord)
            continue
        # print(var_name, "declared outside if", c_ast_node.coord)

        # Find where the differences start in the wire aliases over time
        diff_start_i = None
        for i in range(0, max_aliases_len):
            # If no element here then difference starts here
            if (i > len(true_aliases) - 1) or (i > len(false_aliases) - 1):
                diff_start_i = i
                break

            # Both have elements, same?
            if true_aliases[i] != false_aliases[i]:
                diff_start_i = i
                break

        # If no difference then this var was not driven inside this IF
        if diff_start_i is None:
            # print(var_name, "NO DIFFERENT ALIASES = NOT DRIVEN INSIDE:", c_ast_node.coord)
            continue
        # print(var_name, "DRIVEN INSIDE:", c_ast_node.coord)

        # Collect all the ref toks from aliases - whatever order
        all_ref_toks_set = set()
        for i in range(diff_start_i, max_aliases_len):
            if i < len(true_aliases):
                true_ref_toks = true_logic.alias_to_driven_ref_toks[true_aliases[i]]
                if true_ref_toks not in all_ref_toks_set:
                    all_ref_toks_set.add(true_ref_toks)
            if i < len(false_aliases):
                false_ref_toks = false_logic.alias_to_driven_ref_toks[false_aliases[i]]
                if false_ref_toks not in all_ref_toks_set:
                    all_ref_toks_set.add(false_ref_toks)

        # Collpase hierarchy to get top most orig wire name nodes

        all_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(
            all_ref_toks_set, c_ast_node, parser_state
        )

        # sys.exit(-1)
        # Ok now have collpased list of ref toks that needed MUXes for this IF
        # Save this for later too
        var_name_2_all_ref_toks_set[var_name] = set(all_ref_toks_set)

        # Now do MUX inst logic
        for ref_toks in all_ref_toks_set:
            # Might be first place to see globals... is this getting out of hand?
            var_name = ref_toks[0]

            # Get c type of ref
            c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_node, parser_state)

            # Preparing to do N arg func instance
            # Prepend text needed ot identify specific ref tok for instance
            ref_tok_id_str = C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_node)
            mux_prepend_text = prepend_text + ref_tok_id_str + "_"
            func_c_ast_node = c_ast_node
            func_base_name = LOGIC.MUX_LOGIC_NAME
            base_name_is_name = False  # Append types
            input_port_names = []
            input_port_names.append(mux_cond_port_name)
            input_port_names.append(mux_true_port_name)
            input_port_names.append(mux_false_port_name)
            input_driver_types = []
            input_driver_types.append(LOGIC.BOOL_C_TYPE)
            input_driver_types.append(c_type)
            input_driver_types.append(c_type)
            input_drivers = []
            input_drivers.append(mux_intermediate_cond_wire_wo_var_name)  # Wire

            # Need to do logic of reading ref toks
            # So need to construct wire names
            # Build instance name
            func_inst_name = BUILD_INST_NAME(
                mux_prepend_text, func_base_name, func_c_ast_node
            )

            # Using each branches logic use id_or_structref logic to form read wire driving T/F ports
            # TRUE
            mux_true_connection_wire_name = (
                func_inst_name + LOGIC.SUBMODULE_MARKER + mux_true_port_name
            )
            parser_state.existing_logic.wire_to_c_type[
                mux_true_connection_wire_name
            ] = c_type
            true_logic.wire_to_c_type[mux_true_connection_wire_name] = c_type
            parser_state_for_true.existing_logic = true_logic
            true_read_logic = C_AST_REF_TOKS_TO_LOGIC(
                ref_toks,
                c_ast_node,
                [mux_true_connection_wire_name],
                mux_prepend_text + "TRUE_INPUT_" + LOGIC.MUX_LOGIC_NAME + "_",
                parser_state_for_true,
            )
            # Merge in read
            true_logic.MERGE_COMB_LOGIC(true_read_logic)
            # Record input driving wire and type
            true_input_driving_wire = true_logic.wire_driven_by[
                mux_true_connection_wire_name
            ]
            true_input_driving_wire_type = true_logic.wire_to_c_type[
                true_input_driving_wire
            ]
            parser_state.existing_logic.wire_to_c_type[true_input_driving_wire] = (
                true_input_driving_wire_type
            )
            input_drivers.append(true_input_driving_wire)

            # FALSE
            mux_false_connection_wire_name = (
                func_inst_name + LOGIC.SUBMODULE_MARKER + mux_false_port_name
            )
            parser_state.existing_logic.wire_to_c_type[
                mux_false_connection_wire_name
            ] = c_type
            false_logic.wire_to_c_type[mux_false_connection_wire_name] = c_type
            parser_state_for_false.existing_logic = false_logic
            false_read_logic = C_AST_REF_TOKS_TO_LOGIC(
                ref_toks,
                c_ast_node,
                [mux_false_connection_wire_name],
                mux_prepend_text + "FALSE_INPUT_" + LOGIC.MUX_LOGIC_NAME + "_",
                parser_state_for_false,
            )
            # Merge in read
            false_logic.MERGE_COMB_LOGIC(false_read_logic)
            # Record input driving wire and type
            false_input_driving_wire = false_logic.wire_driven_by[
                mux_false_connection_wire_name
            ]
            false_input_driving_wire_type = false_logic.wire_to_c_type[
                false_input_driving_wire
            ]
            parser_state.existing_logic.wire_to_c_type[false_input_driving_wire] = (
                false_input_driving_wire_type
            )
            input_drivers.append(false_input_driving_wire)

            # Mux doesnt have connecitons from output right now
            # Instead mux changes most recent alias for a variable
            output_driven_wire_names = []
            # Record type of output wire
            mux_output_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
            parser_state.existing_logic.wire_to_c_type[mux_output_wire_name] = c_type
            ref_toks_id_str_to_output_wire[ref_tok_id_str] = mux_output_wire_name

            # Hook up the MUX instance now, adjust aliases after
            parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
                mux_prepend_text,
                func_c_ast_node,
                func_base_name,
                base_name_is_name,
                input_drivers,  # Wires or C ast nodes
                input_driver_types,  # Might be none if not known
                input_port_names,  # Port names on submodule
                output_driven_wire_names,
                parser_state,
            )

            # Merge MUX instance this into true and false now so dont have to after TF merge at end
            # Mux instance occurs AFTER inputs so use SEQ MERGE
            # true_logic.MERGE_SEQ_LOGIC(parser_state.existing_logic)
            # false_logic.MERGE_SEQ_LOGIC(parser_state.existing_logic)

    # Merge T/F branches into existing logic
    # Wire aliases over time from the true and false branches CANT be merged
    # since selection of final alias from either true or false branch is what THIS MUX DOES
    # Loop over and remove branch-only aliases over time
    # RV contains logic before T/F logic so orig aliases
    new_true_false_logic_wire_aliases_over_time = {}
    for orig_var in merge_var_names:
        # Filtered aliases contains orig from RV logic
        filtered_aliases = []
        original_aliases = []
        if orig_var in parser_state.existing_logic.wire_aliases_over_time:
            original_aliases = parser_state.existing_logic.wire_aliases_over_time[
                orig_var
            ]
        filtered_aliases += original_aliases

        # Remove aliases not in original
        if orig_var in true_logic.wire_aliases_over_time:
            for alias in true_logic.wire_aliases_over_time[orig_var]:
                if alias in original_aliases:
                    # Is in orig, keep if not in list already
                    if alias not in filtered_aliases:
                        filtered_aliases.append(alias)

        if orig_var in false_logic.wire_aliases_over_time:
            for alias in false_logic.wire_aliases_over_time[orig_var]:
                if alias in original_aliases:
                    # Is in orig, keep if not in list already
                    if alias not in filtered_aliases:
                        filtered_aliases.append(alias)

        if len(filtered_aliases) > 0:
            new_true_false_logic_wire_aliases_over_time[orig_var] = filtered_aliases

    # Shared comb mergeable wire aliases over time
    true_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
    false_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
    # Pop off last elements of each branches not mergeable clock enables
    del true_logic.clock_enable_wires[-1]
    if len(c_ast_node.children()) >= 3:
        del false_logic.clock_enable_wires[-1]
    # Merge the true and false logic as parallel COMB logic since aliases over time fixed above
    true_logic.MERGE_COMB_LOGIC(false_logic)
    true_false_merged = true_logic

    # After TF merge we can have correct alias list include the mux output
    # Alias list for struct variable may be appended to multiple times
    # But since by def those drivings dont overlap then order doesnt really matter in aliases list
    for variable in merge_var_names:
        # vars declared inside and IF cannot be used outside that if so cannot/should not have MUX inputs+outputs
        declared_in_this_if = (
            variable not in parser_state.existing_logic.variable_names
            and (variable not in parser_state.existing_logic.state_regs)
            and (variable not in parser_state.existing_logic.read_only_global_wires)
            and (variable not in parser_state.existing_logic.write_only_global_wires)
        )
        if declared_in_this_if:
            continue

        # If not driven then skip
        if variable not in var_name_2_all_ref_toks_set:
            continue
        # Otherwise get drive orig wire names (already collapsed)
        all_ref_toks_set = var_name_2_all_ref_toks_set[variable]

        # Add mux output as alias for this var
        aliases = []
        if variable in true_false_merged.wire_aliases_over_time:
            aliases = true_false_merged.wire_aliases_over_time[variable]
            # Remove and re add after
            true_false_merged.wire_aliases_over_time.pop(variable)

        # Ok to add to same alias list multiple times for each orig_wire
        for ref_toks in all_ref_toks_set:
            ref_tok_id_str = C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_node)
            mux_connection_wire_name = ref_toks_id_str_to_output_wire[ref_tok_id_str]
            true_false_merged.alias_to_orig_var_name[mux_connection_wire_name] = (
                variable
            )
            true_false_merged.alias_to_driven_ref_toks[mux_connection_wire_name] = (
                ref_toks
            )
            # set the C type for output connection based on orig var name
            c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_node, parser_state)
            true_false_merged.wire_to_c_type[mux_connection_wire_name] = c_type
            # Mux output just adds an alias over time to the original variable
            # So that the next read of the variable uses the mux output
            if mux_connection_wire_name not in aliases:
                aliases.append(mux_connection_wire_name)

        # Re add if not empty list
        if len(aliases) > 0:
            true_false_merged.wire_aliases_over_time[variable] = aliases

    # Update parser state since aliases have been updated
    # HELP ME
    parser_state.existing_logic.MERGE_SEQ_LOGIC(true_false_merged)
    # TF merged has existing state, was merged when doing inputs
    # parser_state.existing_logic = true_false_merged

    return parser_state.existing_logic


# Function instance is module connection
# Connect certain input nodes to certain lists of wire names
# dict[c_ast_node] => [list of driven wire names]
def SEQ_C_AST_NODES_TO_LOGIC(
    c_ast_node_2_driven_wire_names, prepend_text, parser_state
):
    rv = parser_state.existing_logic
    # Get logic for each connection and merge
    for c_ast_node in c_ast_node_2_driven_wire_names:
        driven_wire_names = c_ast_node_2_driven_wire_names[c_ast_node]
        parser_state.existing_logic = rv
        l = C_AST_NODE_TO_LOGIC(
            c_ast_node, driven_wire_names, prepend_text, parser_state
        )
        first = rv
        second = l
        first.MERGE_SEQ_LOGIC(second)
        rv = first
        parser_state.existing_logic = rv

    return rv


def TRY_CONST_REDUCE_C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    func_inst_name,
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers,  # List of Wires, c ast nodes, or ref toks
    input_driver_types,  # Might be none if not known
    input_port_names,  # Port names on submodule
    output_driven_wire_names,
    parser_state,
):
    # Dont need to process input nodes with separate parser state since will remove old submodule if optimized away

    # Can't evaluate mixed wires and cast node inputs, func arg evaluation order is broken?

    # Input drivers can be c_ast nodes so evaluate those first
    c_ast_node_2_driven_input_wire_names = OrderedDict()
    for i in range(0, len(input_drivers)):
        input_driver = input_drivers[i]
        if isinstance(input_driver, c_ast.Node):
            input_port_name = input_port_names[i]
            input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            c_ast_node_2_driven_input_wire_names[input_driver] = [input_wire_name]
    parser_state.existing_logic = SEQ_C_AST_NODES_TO_LOGIC(
        c_ast_node_2_driven_input_wire_names, prepend_text, parser_state
    )

    # Allow ref toks as inputs too
    for i in range(0, len(input_drivers)):
        input_driver = input_drivers[i]
        if type(input_driver) is tuple:
            driver_ref_toks = input_driver
            input_port_name = input_port_names[i]
            driven_input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            parser_state.existing_logic = C_AST_REF_TOKS_TO_LOGIC(
                driver_ref_toks,
                func_c_ast_node,
                [driven_input_port_wire],
                prepend_text,
                parser_state,
            )

    # Other input drivers are just wires so connect those
    for i in range(0, len(input_drivers)):
        input_driver = input_drivers[i]
        if type(input_driver) is str:
            input_port_name = input_port_names[i]
            driven_input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
                parser_state,
                input_driver,
                [driven_input_port_wire],
                prepend_text,
                func_c_ast_node,
            )

    # Finally include types as passed in if able to

    # Try to fill in type of input ports if not known in input_driver_types
    for i in range(0, len(input_drivers)):
        input_port_name = input_port_names[i]
        input_driver_type = input_driver_types[i]
        if input_driver_type is None:
            input_port_name = input_port_names[i]
            driven_input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            updated_input_driver_type = None
            if driven_input_wire_name in parser_state.existing_logic.wire_to_c_type:
                updated_input_driver_type = parser_state.existing_logic.wire_to_c_type[
                    driven_input_wire_name
                ]
            elif driven_input_wire_name in parser_state.existing_logic.wire_driven_by:
                driving_wire = parser_state.existing_logic.wire_driven_by[
                    driven_input_wire_name
                ]
                if driving_wire in parser_state.existing_logic.wire_to_c_type:
                    updated_input_driver_type = (
                        parser_state.existing_logic.wire_to_c_type[driving_wire]
                    )
                    parser_state.existing_logic.wire_to_c_type[
                        driven_input_wire_name
                    ] = updated_input_driver_type
            input_driver_types[i] = updated_input_driver_type

    # NOw inputs have been connected it is useful
    # Ex. FOR constant funcs x==1
    # To assign the type of driving wire if not assigned yet
    for i in range(0, len(input_drivers)):
        input_port_name = input_port_names[i]
        input_driver_type = input_driver_types[i]
        if input_driver_type is not None:
            driven_input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
            if driven_input_wire_name in parser_state.existing_logic.wire_driven_by:
                driving_wire = parser_state.existing_logic.wire_driven_by[
                    driven_input_wire_name
                ]
                if driving_wire not in parser_state.existing_logic.wire_to_c_type:
                    parser_state.existing_logic.wire_to_c_type[driving_wire] = (
                        input_driver_type
                    )

    # Global functions cannot optimize away
    is_global_func = False
    func_logic = None
    if func_base_name in parser_state.FuncLogicLookupTable:
        func_logic = parser_state.FuncLogicLookupTable[func_base_name]
        is_global_func = (
            len(func_logic.state_regs) > 0 or func_logic.uses_nonvolatile_state_regs
        )
    if is_global_func:
        return None

    # Pass through cast of same type?
    if func_base_name.startswith(LOGIC.CAST_FUNC_NAME_PREFIX) and not base_name_is_name:
        # Assume one input wire
        driven_input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_names[0]
        input_driver_wire_name = parser_state.existing_logic.wire_driven_by[
            driven_input_port_wire
        ]
        # And one output
        output_driven_wire_name = output_driven_wire_names[0]
        # Compare types
        input_cast_type = parser_state.existing_logic.wire_to_c_type[
            input_driver_wire_name
        ]
        output_cast_type = parser_state.existing_logic.wire_to_c_type[
            output_driven_wire_name
        ]
        if input_cast_type == output_cast_type:
            # Remove old submodule instance
            # print("Replacing cast:",func_inst_name,"with direct wire...")
            parser_state.existing_logic.REMOVE_SUBMODULE(
                func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
            )
            # Directly connect input driver to output
            APPLY_CONNECT_WIRES_LOGIC(
                parser_state,
                input_driver_wire_name,
                output_driven_wire_names,
                prepend_text,
                func_c_ast_node,
            )
            return parser_state.existing_logic

    # One hot enum compare
    if (
        func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_EQ_NAME)
        and LOGIC.C_TYPES_ARE_ENUMS(input_driver_types, parser_state)
        and input_driver_types[0] == input_driver_types[1]
        and input_driver_types[0] in parser_state.marked_onehot
    ):
        # Rewrite ex. BIN_OP_EQ_uint1_t_my_enum_t_my_enum_t -> ONE_HOT_EQ_uint1_uint128_t_uint128_t
        # Prepare for call to C_AST_N_ARG_FUNC_INST_TO_LOGIC with replacement
        new_func_base_name = LOGIC.ONE_HOT_EQ_LOGIC_NAME
        new_base_name_is_name = False  # Do append types to name (base is not complete)
        new_input_drivers = input_drivers[
            :
        ]  # Wires or C ast nodes, same as old function
        new_input_port_names = input_port_names[:]  # Port names on submodule
        # The same wires are connected, with the same names
        # EXCEPT need to be ~converted/forced to uint types
        # Similar to in C_AST_BINARY_OP_TO_LOGIC for non-one hot to uint types EQ operator
        enum_type = input_driver_types[0]
        enum_int_type = parser_state.enum_info_dict[enum_type].int_c_type
        new_input_driver_types = [enum_int_type, enum_int_type]
        # Remove old submodule instance
        parser_state.existing_logic.REMOVE_SUBMODULE(
            func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
        )
        # Connect new function call
        parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            func_c_ast_node,
            new_func_base_name,
            new_base_name_is_name,
            new_input_drivers,  # Wires or C ast nodes
            new_input_driver_types,  # Might be none if not known
            new_input_port_names,  # Port names on submodule
            output_driven_wire_names,
            parser_state,
        )
        return parser_state.existing_logic

    # Check if can be replaced by constant output wire
    # Or reduced function due to partial constant inputs
    all_inputs_constant = True
    some_inputs_constant = False
    # Check parser_state.existing_logic for input ports driven by constants
    const_input_wires = []
    for i in range(0, len(input_drivers)):
        input_port_name = input_port_names[i]
        driven_input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
        const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
            driven_input_port_wire, parser_state.existing_logic
        )
        const_input_wires.append(const_driving_wire)
        all_inputs_constant = all_inputs_constant and (const_driving_wire is not None)
        some_inputs_constant = some_inputs_constant or (const_driving_wire is not None)

    # If no constants then nothing to reduce
    if not (all_inputs_constant or some_inputs_constant):
        return None

    # For now, its an error if a totally constant function cannot be reduced

    # Some inputs may be constant, this changes the behavior/funcname of some functions
    #   Ex. constant shift is no longer the same logic binary op logic  (func name determines logic)
    #   Ex. Float mult by const -1 is just sign flip, TODO
    # If all inputs are constant then should be able replace function with constant
    #############################################################################################
    #
    # ALL INPUTS CONSTANT - REPLACE WITH CONSTANT
    if all_inputs_constant:
        # Thanks stackoverflow for twos comp BullSHEEIITITT FUCK ECE 200
        def int2bin(integer, digits):
            if integer >= 0:
                return bin(integer)[2:].zfill(digits)
            else:
                return bin(2**digits + integer)[2:]

        # STACKOVERFLOW MY MAN
        def to_int(bin, signed):
            x = int(bin, 2)
            if signed:
                if bin[0] == "1":  # "sign bit", big-endian
                    x -= 2 ** len(bin)
            return x

        const_val_str = None
        const_val_str_known_c_type = None
        # TRINARY OPS = MUX
        if func_base_name == LOGIC.MUX_LOGIC_NAME and not base_name_is_name:
            sel_wire = const_input_wires[0]
            t_wire = const_input_wires[1]
            f_wire = const_input_wires[2]
            # Get values from constants
            sel_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                sel_wire, parser_state.existing_logic, parser_state
            )
            t_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                t_wire, parser_state.existing_logic, parser_state
            )
            f_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                f_wire, parser_state.existing_logic, parser_state
            )
            if sel_val_str == "1":
                const_val_str = t_val_str
            elif sel_val_str == "0":
                const_val_str = f_val_str
            else:
                raise Exception("Bad cond value")
        # BINARY OPERATIONS
        elif (
            func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX)
            and not base_name_is_name
        ):
            lhs_wire = const_input_wires[0]
            rhs_wire = const_input_wires[1]

            # Get values from constants
            lhs_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                lhs_wire, parser_state.existing_logic, parser_state
            )
            rhs_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                rhs_wire, parser_state.existing_logic, parser_state
            )

            # Skip compund null wire optmizations for now
            if lhs_val_str == LOGIC.COMPOUND_NULL or rhs_val_str == LOGIC.COMPOUND_NULL:
                return None

            # Constant enums: future me - yes the future is now
            lhs_is_enum = LOGIC.WIRE_IS_ENUM(
                lhs_wire, parser_state.existing_logic, parser_state
            )
            rhs_is_enum = LOGIC.WIRE_IS_ENUM(
                rhs_wire, parser_state.existing_logic, parser_state
            )
            if lhs_is_enum != rhs_is_enum:
                raise Exception(
                    f"Cannot constant reduce operation of enum and non enum types {func_c_ast_node.coord}"
                )
            if lhs_is_enum or rhs_is_enum:
                lhs_enum_type = parser_state.existing_logic.wire_to_c_type[lhs_wire]
                rhs_enum_type = parser_state.existing_logic.wire_to_c_type[rhs_wire]
                if lhs_enum_type != rhs_enum_type:
                    raise Exception(
                        f"Cannot constant reduce operation on enums of different types {func_c_ast_node.coord}"
                    )
                enum_type = lhs_enum_type
                enum_int_type = parser_state.enum_info_dict[enum_type].int_c_type
                lhs_val = parser_state.enum_info_dict[enum_type].id_to_int_val[
                    lhs_val_str
                ]
                lhs_c_type = enum_int_type
                rhs_val = parser_state.enum_info_dict[enum_type].id_to_int_val[
                    rhs_val_str
                ]
                rhs_c_type = enum_int_type
            else:
                # Is non enum number like constant
                lhs_negated = lhs_val_str.startswith("-")
                rhs_negated = rhs_val_str.startswith("-")
                lhs_val_str_no_neg = lhs_val_str.strip("-")
                rhs_val_str_no_neg = rhs_val_str.strip("-")
                lhs_val, lhs_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                    lhs_val_str_no_neg, func_c_ast_node, lhs_negated
                )
                rhs_val, rhs_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                    rhs_val_str_no_neg, func_c_ast_node, rhs_negated
                )
            # print("lhs_val, lhs_c_type",lhs_val, lhs_c_type)
            # print("rhs_val, rhs_c_type",rhs_val, rhs_c_type)

            # First check for integer arguments
            is_ints = LOGIC.C_TYPES_ARE_INTEGERS([lhs_c_type, rhs_c_type])

            # Then allow for floats, if either float then treat boths as floats
            is_floats = LOGIC.C_TYPE_IS_FLOAT_TYPE(lhs_c_type) or LOGIC.C_TYPE_IS_FLOAT_TYPE(
                rhs_c_type
            )

            # Number who?
            if not is_ints and not is_floats:
                print(
                    "Function",
                    func_base_name,
                    func_c_ast_node.coord,
                    "is constant binary op of non numbers?",
                )
                sys.exit(-1)

            # What type of binary op
            if func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_PLUS_NAME):
                const_val_str = str(lhs_val + rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MINUS_NAME):
                const_val_str = str(lhs_val - rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_OR_NAME):
                const_val_str = str(lhs_val | rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_XOR_NAME):
                const_val_str = str(lhs_val ^ rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_AND_NAME):
                const_val_str = str(lhs_val & rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MULT_NAME):
                const_val_str = str(lhs_val * rhs_val)
            elif func_base_name == (
                LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_INFERRED_MULT_NAME
            ):
                const_val_str = str(lhs_val * rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_DIV_NAME):
                # Div leaves group of ints and returns float
                if is_ints:
                    const_val_str = str(int(lhs_val / rhs_val))
                else:
                    const_val_str = str(lhs_val / rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_MOD_NAME):
                const_val_str = str(lhs_val % rhs_val)
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_LT_NAME):
                const_val_str = "1" if lhs_val < rhs_val else "0"
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_LTE_NAME):
                const_val_str = "1" if lhs_val <= rhs_val else "0"
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_GT_NAME):
                const_val_str = "1" if lhs_val > rhs_val else "0"
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_GTE_NAME):
                const_val_str = "1" if lhs_val >= rhs_val else "0"
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_EQ_NAME):
                const_val_str = "1" if lhs_val == rhs_val else "0"
            elif func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_NEQ_NAME):
                const_val_str = "1" if lhs_val != rhs_val else "0"
            # Bit operations
            elif func_base_name == (
                LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SR_NAME
            ) or func_base_name == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME):
                if is_ints and func_base_name == (
                    LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SR_NAME
                ):
                    # Output type is type of LHS
                    c_type = parser_state.existing_logic.wire_to_c_type[lhs_wire]
                    width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
                    signed = LOGIC.C_TYPE_IS_INT_N(c_type)
                    # lhs_val >> rhs_val
                    lhs_bin_str = int2bin(lhs_val, width)
                    fill_bit = "0"
                    if signed:
                        fill_bit = lhs_bin_str[0]  # Sign bit
                    fill_bits = fill_bit * rhs_val
                    output_bin_str = (fill_bits + lhs_bin_str)[0:width]  # first n
                    output_int = to_int(output_bin_str, signed)
                    const_val_str = str(output_int)
                    # print(lhs_bin_str,">>",rhs_val, const_val_str)
                elif is_ints and func_base_name == (
                    LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME
                ):
                    # Int constants are made as wide as possible
                    # ex.
                    # uint32 = 1 << 3;
                    #          ^1b constant , needs be sized to atleast 4 bits
                    lhs_type = parser_state.existing_logic.wire_to_c_type[lhs_wire]
                    lhs_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, lhs_type)
                    signed = LOGIC.C_TYPE_IS_INT_N(lhs_type)
                    width = lhs_width + rhs_val
                    # lhs_val << rhs_val
                    lhs_bin_str = int2bin(lhs_val, width)
                    fill_bit = "0"
                    fill_bits = fill_bit * rhs_val
                    output_bin_str = (lhs_bin_str + fill_bits)[-width:]  # Last n
                    output_int = to_int(output_bin_str, signed)
                    const_val_str = str(output_int)
                    # print(lhs_bin_str,"<<",rhs_val, const_val_str)
                elif (
                    LOGIC.C_TYPE_IS_FLOAT_TYPE(lhs_c_type)
                    and LOGIC.C_TYPES_ARE_INTEGERS([rhs_c_type])
                    and func_base_name
                    == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME)
                ):
                    # Implement pow2 mult for <<
                    const_val_str = str(lhs_val * pow(2, rhs_val))
                elif (
                    LOGIC.C_TYPE_IS_FLOAT_TYPE(lhs_c_type)
                    and LOGIC.C_TYPES_ARE_INTEGERS([rhs_c_type])
                    and func_base_name
                    == (LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME)
                ):
                    # Implement pow2 div for >>
                    const_val_str = str(lhs_val / pow(2, rhs_val))
                else:
                    print("Unsupported const bit operation", func_base_name)
                    sys.exit(-1)

            else:
                print(
                    "Function",
                    func_base_name,
                    func_c_ast_node.coord,
                    "is constant binary op yet to be supported.",
                )
                sys.exit(-1)

        # UNARY OPERATIONS
        elif (
            func_base_name.startswith(LOGIC.UNARY_OP_LOGIC_NAME_PREFIX)
            and not base_name_is_name
        ):
            in_wire = const_input_wires[0]
            in_c_type = parser_state.existing_logic.wire_to_c_type[in_wire]
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                in_wire, parser_state.existing_logic, parser_state
            )
            # Skip compund null wire optmizations for now
            if in_val_str == LOGIC.COMPOUND_NULL:
                return None
            in_negated = in_val_str.startswith("-")
            in_val_str_no_neg = in_val_str.strip("-")
            in_val, in_c_type_from_str = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                in_val_str_no_neg, func_c_ast_node, in_negated
            )
            """if in_c_type != in_c_type_from_str:
                print(
                    "Mismatching c types for unary op const?",
                    in_val_str,
                    in_c_type,
                    in_c_type_from_str,
                    func_c_ast_node.coord,
                )
                sys.exit(-1)"""
            if LOGIC.C_TYPE_IS_FLOAT_TYPE(in_c_type):
                # Floats
                # What op?
                if func_base_name == (
                    LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.UNARY_OP_NEGATE_NAME
                ):
                    const_val_str = str(in_val * -1.0)
                else:
                    print(
                        "Function",
                        func_base_name,
                        func_c_ast_node.coord,
                        "is constant float unary op yet to be supported.",
                    )
                    sys.exit(-1)
            else:
                # Ints
                signed = LOGIC.C_TYPE_IS_INT_N(in_c_type)
                in_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_c_type)
                # What op?
                if func_base_name == (
                    LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.UNARY_OP_NOT_NAME
                ):
                    in_bin_str = int2bin(in_val, in_width)
                    out_bin_str = (
                        in_bin_str.replace("0", "T").replace("1", "0").replace("T", "1")
                    )
                    out_val = to_int(out_bin_str, signed)
                    const_val_str = str(out_val)
                elif func_base_name == (
                    LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.UNARY_OP_NEGATE_NAME
                ):
                    const_val_str = str(int(in_val * -1))
                else:
                    print(
                        "Function",
                        func_base_name,
                        func_c_ast_node.coord,
                        "is constant integer unary op yet to be supported.",
                    )
                    sys.exit(-1)
        # BIT MANIPULATION
        elif (func_logic is not None) and LOGIC.IS_BIT_MANIP(func_logic):
            # TODO
            return None
        # CASTING
        elif func_base_name.startswith(LOGIC.CAST_FUNC_NAME_PREFIX) and not base_name_is_name:
            in_t = parser_state.existing_logic.wire_to_c_type[const_input_wires[0]]
            out_t = parser_state.existing_logic.wire_to_c_type[
                output_driven_wire_names[0]
            ]
            const_val_str_known_c_type = out_t
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            if LOGIC.C_TYPES_ARE_FLOAT_TYPES([in_t, out_t]):
                const_val_str = str(float(in_val_str))
            elif LOGIC.C_TYPES_ARE_INTEGERS([in_t]) and LOGIC.C_TYPE_IS_FLOAT_TYPE(out_t):
                const_val_str = str(float(in_val_str))
            elif LOGIC.C_TYPE_IS_FLOAT_TYPE(in_t) and LOGIC.C_TYPES_ARE_INTEGERS([out_t]):
                const_val_str = str(int(float(in_val_str)))
            elif LOGIC.C_TYPES_ARE_INTEGERS([in_t, out_t]):
                (
                    signed,
                    left_width,
                    left_unsigned_width,
                    right_width,
                    right_unsigned_width,
                    max_width,
                    max_unsigned_width,
                    left_max_val,
                    left_min_val,
                    right_max_val,
                    right_min_val,
                ) = GET_INTEGER_MAX_SIZE_INFO([in_t, out_t])

                is_negated = in_val_str.startswith("-")
                in_val_str_abs_val = in_val_str.strip("-")
                in_val, in_val_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                    in_val_str_abs_val, func_c_ast_node, is_negated
                )
                out_val = in_val
                if out_val > left_max_val or out_val < left_min_val:
                    print(
                        "How to trim/add bits for cast? ",
                        in_t,
                        in_val_str,
                        "->",
                        out_t,
                        func_c_ast_node.coord,
                        prepend_text,
                    )
                    sys.exit(-1)
                const_val_str = str(out_val)
            else:
                print(
                    "How to cast? ",
                    in_t,
                    in_val_str,
                    "->",
                    out_t,
                    func_c_ast_node.coord,
                    prepend_text,
                )
                sys.exit(-1)

        # MATH FUNCS
        elif func_base_name == "sqrt" and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            in_val = float(in_val_str)
            out_val = math.sqrt(in_val)
            const_val_str = str(out_val)
        elif func_base_name == "ceil" and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            in_val = float(in_val_str)
            out_val = math.ceil(in_val)
            const_val_str = str(out_val)
        elif func_base_name == "log2" and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            in_val = float(in_val_str)
            out_val = math.log2(in_val)
            const_val_str = str(out_val)
        elif func_base_name == "cos" and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            in_val = float(in_val_str)
            out_val = math.cos(in_val)
            const_val_str = str(out_val)
        elif func_base_name == "sin" and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            in_val = float(in_val_str)
            out_val = math.sin(in_val)
            const_val_str = str(out_val)

        # String funcs
        elif func_base_name.startswith(LOGIC.PRINTF_FUNC_NAME + "_"):
            return None
        elif func_base_name.startswith(STRLEN_FUNC_NAME + "_") and base_name_is_name:
            in_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_input_wires[0], parser_state.existing_logic, parser_state
            )
            str_val = in_val_str.strip('"')
            out_val = len(C_CONST_STR_TO_STR_VALUE(str_val))
            const_val_str = str(out_val)

        # CONST REFs are ok not to reduce for now. I.e CANNOT PROPOGATE CONSTANTS through compound references (structs, arrays)
        elif func_base_name.startswith(LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
            return None
        # If func has no inputs and is not global then must be const
        # similar to above cant propogate consts through compound types yet?
        elif len(input_drivers) == 0:
            return None
        else:
            return None

        # Determine types for const wire to output wire and return
        is_negated = False
        if const_val_str.startswith("-"):
            const_val_str = const_val_str.lstrip("-")
            is_negated = True
        driving_output_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
        output_c_type = GET_C_TYPE_FROM_WIRE_NAMES(
            [driving_output_port_wire], parser_state.existing_logic, allow_fail=True
        )
        # Fall back to driven wires....uh?
        # if output_c_type is None:
        #  output_c_type = GET_C_TYPE_FROM_WIRE_NAMES(output_driven_wire_names, parser_state.existing_logic, allow_fail=True)

        # Going to replace with constant
        # Remove old submodule instance
        # print "Replacing:",func_inst_name,"with constant",const_val_str
        parser_state.existing_logic.REMOVE_SUBMODULE(
            func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
        )

        # Do connection using real parser state and logic
        parser_state.existing_logic = NON_ENUM_CONST_VALUE_STR_TO_LOGIC(
            const_val_str,
            func_c_ast_node,
            output_driven_wire_names,
            prepend_text,
            parser_state,
            is_negated,
            const_val_str_known_c_type,
        )

        return parser_state.existing_logic

    #############################################################################################
    #
    # SOME INPUTS CONSTANT - REPLACE WITH ALTERNATE FUNCTION
    #
    new_func_base_name = None
    new_base_name_is_name = False
    new_input_drivers = []  # Wires or C ast nodes
    new_input_driver_types = []  # Might be none if not known
    new_input_port_names = []  # Port names on submodule
    is_reducable = False
    # TODO other things
    # CONSTANT SHIFT LEFT on INT
    if (
        LOGIC.C_TYPES_ARE_INTEGERS([input_driver_types[0]])
        and func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SL_NAME)
        and const_input_wires[1] is not None
    ):
        # Replace with const
        rhs_wire = const_input_wires[1]
        rhs_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            rhs_wire, parser_state.existing_logic, parser_state
        )
        new_func_base_name = LOGIC.CONST_PREFIX + LOGIC.BIN_OP_SL_NAME + "_" + rhs_val_str
        new_base_name_is_name = False  # needs types
        new_input_drivers = [input_drivers[0]]  # Dont need RHS, is const
        new_input_driver_types = [input_driver_types[0]]
        new_input_port_names = ["x"]  # One input port, not LHS or RHS\
        new_func_inst_name = BUILD_INST_NAME(
            prepend_text, new_func_base_name, func_c_ast_node
        )
        new_output_wire = new_func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
        parser_state.existing_logic.wire_to_c_type[new_output_wire] = (
            new_input_driver_types[0]
        )  # Shift outputs LHS type
        is_reducable = True
    # CONSTANT SHIFT RIGHT on INT
    elif (
        LOGIC.C_TYPES_ARE_INTEGERS([input_driver_types[0]])
        and func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_SR_NAME)
        and const_input_wires[1] is not None
    ):
        # Replace with const
        rhs_wire = const_input_wires[1]
        rhs_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            rhs_wire, parser_state.existing_logic, parser_state
        )
        new_func_base_name = LOGIC.CONST_PREFIX + LOGIC.BIN_OP_SR_NAME + "_" + rhs_val_str
        new_base_name_is_name = False  # needs types
        new_input_drivers = [input_drivers[0]]  # Dont need RHS, is const
        new_input_driver_types = [input_driver_types[0]]
        new_input_port_names = ["x"]  # One input port, not LHS or RHS
        new_func_inst_name = BUILD_INST_NAME(
            prepend_text, new_func_base_name, func_c_ast_node
        )
        new_output_wire = new_func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
        parser_state.existing_logic.wire_to_c_type[new_output_wire] = (
            new_input_driver_types[0]
        )  # Shift outputs LHS type
        is_reducable = True
    # CONSTANT condition MUX
    elif func_base_name == LOGIC.MUX_LOGIC_NAME and const_input_wires[0] is not None:
        # What is const value for condition?
        const_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_input_wires[0], parser_state.existing_logic, parser_state
        )
        val, unused_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
            const_val_str,
            func_c_ast_node,
            is_negated=False,
            expected_c_type=LOGIC.BOOL_C_TYPE,
        )
        # Not reducing to replacement func,
        # is just wire from selected input driver to output wires
        # Remove old submodule instance
        parser_state.existing_logic.REMOVE_SUBMODULE(
            func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
        )
        if val == 1:
            # Select true branch
            sel_input_driver = input_drivers[1]
        elif val == 0:
            # Select false branch
            sel_input_driver = input_drivers[2]
        else:
            raise Exception("Bad cond value")
        # And connect input port drive to output driven wires
        parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
            parser_state,
            sel_input_driver,
            output_driven_wire_names,
            prepend_text,
            func_c_ast_node,
            check_types_do_cast=False,
        )
        return parser_state.existing_logic
    # Constant one hot enum compare eq
    elif func_base_name == LOGIC.ONE_HOT_EQ_LOGIC_NAME and (
        const_input_wires[0] is not None or const_input_wires[1] is not None
    ):
        # Which input is the const left or right?
        # Which is var?
        if const_input_wires[0] is not None:
            const_input_wire = const_input_wires[0]
            var_input_driver = input_drivers[1]
        if const_input_wires[1] is not None:
            const_input_wire = const_input_wires[1]
            var_input_driver = input_drivers[0]
        # What is the constant?
        const_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_input_wire, parser_state.existing_logic, parser_state
        )
        # Will be an enum const, convert to int...
        enum_t = parser_state.existing_logic.wire_to_c_type[const_input_wire]
        enum_info = parser_state.enum_info_dict[enum_t]
        int_const_val = enum_info.id_to_int_val[const_val_str]
        one_hot_bit = int(math.log2(int_const_val))
        int_c_type = enum_info.int_c_type
        int_c_type_prefix = int_c_type.replace("_t", "")
        # Use bit select built in func: uint<Y-X+1>_t <type_prefix>_Y_X(<type>)
        new_func_base_name = (
            int_c_type_prefix + "_" + str(one_hot_bit) + "_" + str(one_hot_bit)
        )
        new_base_name_is_name = True  # nothing to append to base
        new_input_drivers = [var_input_driver]  # Just one input, the variable
        new_input_driver_types = [int_c_type]
        new_input_port_names = [
            "x"
        ]  # Port name on submodule (from GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT)
        APPEND_BIT_MANIP_FUNC(new_func_base_name, parser_state)
        is_reducable = True
    # Turn uint1_t!=0, and uint1_t==1 into pass through wires (mostly for bool supporting inserting NEQ 0)
    elif (
        func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_NEQ_NAME)
        or func_base_name.startswith(LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_EQ_NAME)
    ) and (
        (const_input_wires[0] is not None and input_driver_types[1] == LOGIC.BOOL_C_TYPE)
        or (const_input_wires[1] is not None and input_driver_types[0] == LOGIC.BOOL_C_TYPE)
    ):
        # Which is var?
        if const_input_wires[0] is not None:
            const_input_wire = const_input_wires[0]
            var_input_driver = input_drivers[1]
        if const_input_wires[1] is not None:
            const_input_wire = const_input_wires[1]
            var_input_driver = input_drivers[0]
        # What is const value?
        const_val_str = LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            const_input_wire, parser_state.existing_logic, parser_state
        )
        if LOGIC.WIRE_IS_ENUM(const_input_wire, parser_state.existing_logic, parser_state):
            # TODO const enum compare reduce...and only for 1b enums...come on...
            is_reducable = False
        else:
            val, unused_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                const_val_str,
                func_c_ast_node,
                is_negated=False,
                expected_c_type=LOGIC.BOOL_C_TYPE,
            )
            # uint1_t!=0, and uint1_t==1 #TODO  uint1_t==0 and uint1_t!=1 is NOT
            if (
                func_base_name.startswith(
                    LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_NEQ_NAME
                )
                and val == 0
            ) or (
                func_base_name.startswith(
                    LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + LOGIC.BIN_OP_EQ_NAME
                )
                and val == 1
            ):
                # Not reducing to replacement func, is just wire from input driver output wires
                # Remove old submodule instance
                parser_state.existing_logic.REMOVE_SUBMODULE(
                    func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
                )
                # And connect input port drive to output driven wires
                parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
                    parser_state,
                    var_input_driver,
                    output_driven_wire_names,
                    prepend_text,
                    func_c_ast_node,
                    check_types_do_cast=False,
                )
                return parser_state.existing_logic

    # Not a reducable function
    if not is_reducable:
        return None

    # Remove old submodule instance
    # print "Replacing:",func_inst_name, "with reduced function", new_func_base_name
    parser_state.existing_logic.REMOVE_SUBMODULE(
        func_inst_name, input_port_names, [LOGIC.RETURN_WIRE_NAME], parser_state
    )

    # And remove the constant wires that were optimized away ?
    # @GAHMAKETHIS PART OF REMOVE SUBMODULE OR WHAT?????

    # Can reduce, do logic to for reduced funciton
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        func_c_ast_node,
        new_func_base_name,
        new_base_name_is_name,
        new_input_drivers,  # Wires or C ast nodes
        new_input_driver_types,  # Might be none if not known
        new_input_port_names,  # Port names on submodule
        output_driven_wire_names,
        parser_state,
    )

    return parser_state.existing_logic


# ORDER OF N ARGS MATTERS
# _funcd = []
def C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers,  # List of Wires, c ast nodes, or ref toks
    input_driver_types,  # Might be none if not known
    input_port_names,  # Port names on submodule
    output_driven_wire_names,
    parser_state,
    expected_output_type=None,
):
    # @@@@@@@@@ Maybe just require casting operation instead?  don't allow float + int  (bin op still changes to float+float  and errors connecting int to float ???
    #  Maybe?^ SEEMS RIGHT
    rf"""
    # OTherwise? \/
    @TODO if defined in C code use parsed C def for types
    @OTHERwise  need to infer types with LOOKAHEAD "precast" wires  (TODO remove if extra?)
    @##@ Once types of inputs are looked ahead you need to let each func change the types
    @# Ex. bin op  float + int  is actually  float + (float)int
    @# Then do APPLY_/ SEQ_C
    """

    # User specified func call inst name or build generated one?
    if (
        type(func_c_ast_node) == c_ast.FuncCall
        and parser_state.existing_logic.next_user_inst_name is not None
    ):
        func_inst_name = parser_state.existing_logic.next_user_inst_name
        parser_state.existing_logic.next_user_inst_name = None  # Reset for next
    else:
        # Build instance name
        func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, func_c_ast_node)

    # Record if user specified call to be auto-pipeline
    if parser_state.existing_logic.next_func_call_auto_pipeline_latency is not None:
        constraint = parser_state.existing_logic.next_func_call_auto_pipeline_latency
        parser_state.existing_logic.sub_inst_to_auto_pipeline_latency[func_inst_name] = (
            constraint
        )
        parser_state.existing_logic.next_func_call_auto_pipeline_latency = None

    # Should not be evaluating c ast node if driver is already known
    for input_i in range(0, len(input_port_names)):
        input_port_name = input_port_names[input_i]
        input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
        if input_port_wire in parser_state.existing_logic.wire_driven_by and isinstance(
            input_drivers[input_i], c_ast.Node
        ):
            print(
                "Why evaluating c ast node",
                input_drivers[input_i],
                "input to",
                func_inst_name,
            )
            print(
                "When it is known that input",
                input_port_wire,
                " is driven by:",
                parser_state.existing_logic.wire_driven_by[input_port_wire],
            )
            sys.exit(-1)

    # Try to set input port wire types
    if func_base_name in parser_state.FuncLogicLookupTable:
        # Before evaluating input nodes make sure type of port is there so constants can be evaluated
        # Get types from func defs
        func_def_logic_object = parser_state.FuncLogicLookupTable[func_base_name]
        for input_port in func_def_logic_object.inputs:
            input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port
            parser_state.existing_logic.wire_to_c_type[input_port_wire] = (
                func_def_logic_object.wire_to_c_type[input_port]
            )

    # Try to determine output type
    # Should be knowable except for mux, which can be inferred
    # Set type for outputs based on func_name (only base name known right now? base name== func name for parsed C coe) if possible
    output_type = None
    output_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
    if func_base_name in parser_state.FuncLogicLookupTable:
        output_type = "void"
        func_def_logic_object = parser_state.FuncLogicLookupTable[func_base_name]
        if len(func_def_logic_object.outputs) > 0:
            # Get type of output
            output_type = func_def_logic_object.wire_to_c_type[LOGIC.RETURN_WIRE_NAME]
    # Set type for outputs based on output port if possible
    elif output_wire_name in parser_state.existing_logic.wire_to_c_type:
        output_type = parser_state.existing_logic.wire_to_c_type[output_wire_name]
    # Mux Types must match to assume
    elif (
        func_base_name == LOGIC.MUX_LOGIC_NAME
        and (input_driver_types[1] == input_driver_types[2])
        and input_driver_types[1] is not None
    ):
        output_type = input_driver_types[1]  # [0] is cond for mux
        parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_type
    # Or muxing integers, take max size
    elif func_base_name == LOGIC.MUX_LOGIC_NAME and LOGIC.C_TYPES_ARE_INTEGERS(
        input_driver_types[1:3]
    ):
        # print("output type for func",func_base_name, input_driver_types, func_c_ast_node.coord)
        (
            signed,
            left_width,
            left_unsigned_width,
            right_width,
            right_unsigned_width,
            max_width,
            max_unsigned_width,
            left_max_val,
            left_min_val,
            right_max_val,
            right_min_val,
        ) = GET_INTEGER_MAX_SIZE_INFO(input_driver_types[1:3])
        # Is sized to max
        output_type = "int" + str(max_width) + "_t"
        if not signed:
            output_type = "u" + output_type
        parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_type
        for input_i in range(1, 3):
            input_type = output_type
            input_driver_types[input_i] = input_type
            input_port_wire = (
                func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_names[input_i]
            )
            parser_state.existing_logic.wire_to_c_type[input_port_wire] = input_type
        # print("Mux type",input_type)
    # Printf returns void for now
    elif func_base_name.startswith(LOGIC.PRINTF_FUNC_NAME + "_"):
        output_type = "void"
    # __vhdl__ also void
    elif func_base_name == LOGIC.VHDL_FUNC_NAME:
        output_type = "void"

    # Try to infer out type from driven wires if not set by now? # Hacky?
    if output_type is None and expected_output_type is None:
        for output_driven_wire_name in output_driven_wire_names:
            if output_driven_wire_name in parser_state.existing_logic.wire_to_c_type:
                output_type = parser_state.existing_logic.wire_to_c_type[
                    output_driven_wire_name
                ]

    # Set this type for the driven wires if not set already? # This seems really hacky
    if output_type is not None:
        for output_driven_wire_name in output_driven_wire_names:
            if (
                output_driven_wire_name
                not in parser_state.existing_logic.wire_to_c_type
            ):
                parser_state.existing_logic.wire_to_c_type[output_driven_wire_name] = (
                    output_type
                )

    # Is this a constant or reduceable func call?
    const_reduced_logic = TRY_CONST_REDUCE_C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        func_inst_name,
        prepend_text,
        func_c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        output_driven_wire_names,
        parser_state,
    )
    if const_reduced_logic is not None:
        return const_reduced_logic

    # Build func name
    func_name = LOGIC.BUILD_FUNC_NAME(
        func_base_name, output_type, input_driver_types, base_name_is_name
    )
    # Sub module inst
    parser_state.existing_logic.submodule_instances[func_inst_name] = func_name
    # C ast node
    parser_state.existing_logic.submodule_instance_to_ast_meta[func_inst_name] = (
        C_AST_NODE_TO_META(func_c_ast_node)
    )

    # Connect clock enable for this func if needed
    # For now can only look up parsed (not built in) functions
    # OK since up until printf, all built in funcs were pure, no clock enable
    if func_name in parser_state.FuncLogicLookupTable:
        func_def_logic_object = parser_state.FuncLogicLookupTable[func_name]
        if LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(func_def_logic_object, parser_state):
            ce_driver_wire = parser_state.existing_logic.clock_enable_wires[-1]
            func_ce_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.CLOCK_ENABLE_NAME
            # print(func_ce_wire,"<=",ce_driver_wire)
            parser_state.existing_logic.wire_to_c_type[func_ce_wire] = LOGIC.BOOL_C_TYPE
            parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
                parser_state,
                ce_driver_wire,
                [func_ce_wire],
                prepend_text,
                func_c_ast_node,
            )

    # Record all input port names for this submodule
    # This might not be needed but not thinking about that now
    parser_state.existing_logic.submodule_instance_to_input_port_names[
        func_inst_name
    ] = input_port_names[:]

    # Try to record input wire types, think this NEEDS to work here
    for i in range(0, len(input_drivers)):
        input_port_name = input_port_names[i]
        input_driver_type = input_driver_types[i]
        driven_input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name

        # Sanity check types instead of relying on them
        # Check type for input based on func_name if possible
        if func_name in parser_state.FuncLogicLookupTable:
            func_def_logic_object = parser_state.FuncLogicLookupTable[func_name]
            # Get port name from driven wire
            func_port_type = func_def_logic_object.wire_to_c_type[input_port_name]
            if input_driver_type != func_port_type:
                print(
                    func_inst_name,
                    "port",
                    input_port_name,
                    "mismatched types per func def?",
                    input_driver_type,
                    func_port_type,
                )
                sys.exit(-1)
            # parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = func_port_type

        # SAVE TYPE
        parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = (
            input_driver_type
        )

    ################################# INPUTS DONE ##########################################

    # Outputs
    # Most special type inferring post input connections for implicit template kind of things?
    if func_base_name == LOGIC.ACCUM_FUNC_NAME:
        output_type = input_driver_types[
            0
        ]  # First increment is same as output type,storage

    # Only add output wire if there is one
    # Fall back to expected?
    if output_type is None:
        output_type = expected_output_type
    if output_type is None:
        print(
            "Unknown output type for func",
            func_base_name,
            input_driver_types,
            func_c_ast_node.coord,
        )
        sys.exit(-1)
    if output_type != "void":
        # Add wire even if below it ends up driving nothing
        # need this to see the unconnected wire and rip up form there
        #     ~~~ Akron/Family - Franny/You're Human ~~~
        parser_state.existing_logic.wires.add(output_wire_name)
        if output_wire_name not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_type
        # Finally connect the output of this operation to each of the driven wires
        if len(output_driven_wire_names) > 0:
            parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
                parser_state,
                output_wire_name,
                output_driven_wire_names,
                prepend_text,
                func_c_ast_node,
            )
        for output_driven_wire_name in output_driven_wire_names:
            if (
                output_driven_wire_name
                not in parser_state.existing_logic.wire_to_c_type
            ):
                parser_state.existing_logic.wire_to_c_type[output_driven_wire_name] = (
                    output_type
                )
    else:
        if len(output_driven_wire_names) > 0:
            print(
                "Func with void output but has driven output wires?",
                output_driven_wire_names,
            )
            sys.exit(-1)

    return parser_state.existing_logic


# Base name only is different for built in ops
# OK to use only base name (no types)
# here since this inst name is only leaf, full inst name will be type specific
# Func name will be type specific
def BUILD_INST_NAME(prepend_text, func_base_name, c_ast_node):
    file_coord_str = C_AST_NODE_COORD_STR(c_ast_node)
    inst_name = prepend_text + func_base_name + "[" + file_coord_str + "]"
    return inst_name


def C_AST_PRINTF_FUNC_CALL_TO_FORMATS(c_ast_func_call):
    args = c_ast_func_call.args.exprs
    str_arg = args[0]
    format_args = []
    if len(args) > 1:
        format_args = args[1:]
    if str_arg.type != "string":
        print("Hey now, simple printfs for now!", c_ast_func_call.coord)
        sys.exit(-1)
    format_string = str_arg.value
    return LOGIC.PRTINTF_STRING_TO_FORMATS(format_string)


def C_AST_PRINTF_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    # Heyo variadic functions
    # Need to construct a function name, like hacky const ref funs
    # Sanity easily visible const strings
    formats = C_AST_PRINTF_FUNC_CALL_TO_FORMATS(c_ast_func_call)
    args = c_ast_func_call.args.exprs
    str_arg = args[0]
    format_string = str_arg.value
    format_args = []
    if len(args) > 1:
        format_args = args[1:]
    arg_c_types = []
    arg_base = []
    for f in formats:
        arg_c_types.append(f.c_type)
        arg_base.append(f.base)
    # Make up a func call to eval
    func_base_name = (
        LOGIC.PRINTF_FUNC_NAME
        + "_"
        + VHDL.WIRE_TO_VHDL_NAME(C_AST_NODE_COORD_STR(c_ast_func_call))
    )
    base_name_is_name = True  # Dont need type into if coord str is enough?
    input_drivers = list(format_args)  # mutable -- %s indices get overwritten below
    input_driver_types = arg_c_types
    if len(input_drivers) != len(input_driver_types):
        raise Exception(f"printf args mismatch at {c_ast_func_call.coord}")
    input_port_names = ["arg" + str(i) for i in range(0, len(format_args))]
    output_driven_wire_names = driven_wire_names  # Probably none?
    # Printf is first built in with clock enable?
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_func_call)

    # %s: don't force a fixed max size -- pre-elaborate the arg to discover its REAL
    # array size/type from the driving wire (same technique as
    # C_AST_STRLEN_FUNC_CALL_TO_LOGIC below), and use that as the port's real type
    # instead of PRTINTF_STRING_TO_FORMATS's placeholder (None) for %s.
    for i, f in enumerate(formats):
        if f.specifier == "%s":
            input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_names[i]
            parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
                format_args[i], [input_wire_name], prepend_text, parser_state
            )
            driver_of_input = parser_state.existing_logic.wire_driven_by[
                input_wire_name
            ]
            real_type = parser_state.existing_logic.wire_to_c_type[driver_of_input]
            input_driver_types[i] = real_type
            input_drivers[i] = driver_of_input  # resolved wire name, not a c_ast node

    func_ce_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.CLOCK_ENABLE_NAME
    parser_state.existing_logic.wire_to_c_type[func_ce_wire] = LOGIC.BOOL_C_TYPE
    # This is suspiciously stolen from n arg where it doesnt happen since printf is first
    # built in needing clock enable?
    # Hey future me - hope things are still kool
    ce_driver_wire = parser_state.existing_logic.clock_enable_wires[-1]
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
        parser_state, ce_driver_wire, [func_ce_wire], prepend_text, c_ast_func_call
    )
    # Set void output for printf DONE IN N ARG FUNC INST BELOW SINCE...dumb?
    # output_wire = func_inst_name + SUBMODULE_MARKER + RETURN_WIRE_NAME
    # parser_state.existing_logic.wire_to_c_type[output_wire] = "void"
    # Then regular narg? Oh come on?
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_func_call,
        func_base_name,
        base_name_is_name,
        input_drivers,
        input_driver_types,
        input_port_names,
        output_driven_wire_names,
        parser_state,
    )

    # Frontend-agnostic format-string storage, read by VHDL.GET_PRINTF_MODULE_TEXT via
    # Logic.printf_format_string instead of Logic.c_ast_node -- lets other frontends
    # (Pypeline) reuse this same codegen without needing a pycparser-shaped node.
    parser_state.existing_logic.submodule_instance_to_printf_format_string[
        func_inst_name
    ] = format_string

    return parser_state.existing_logic


# See hacky below var as func stuff
def APPEND_BIT_MANIP_FUNC(bit_manip_func_name, parser_state):
    (
        input_port_names,
        input_types,
        output_type,
    ) = BIT_SEL_FUNC_TO_INPUTS_TYPES_OUTPUT_TYPE(bit_manip_func_name)
    if bit_manip_func_name not in parser_state.FuncLogicLookupTable:
        bit_manip_func_logic = LOGIC.Logic()
        bit_manip_func_logic.func_name = bit_manip_func_name
        for i in range(0, len(input_port_names)):
            input_port_name = input_port_names[i]
            input_type = input_types[i]
            bit_manip_func_logic.inputs.append(input_port_name)
            bit_manip_func_logic.wire_to_c_type[input_port_name] = input_type
        bit_manip_func_logic.outputs.append(LOGIC.RETURN_WIRE_NAME)
        bit_manip_func_logic.wire_to_c_type[LOGIC.RETURN_WIRE_NAME] = output_type
        bit_manip_func_logic.is_vhdl_func = True
        bit_manip_func_logic.is_new_style_bit_manip = True
        parser_state.FuncLogicLookupTable[bit_manip_func_name] = bit_manip_func_logic


# HACK AF variables as func names
def C_AST_VAR_AS_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    # Try to evaluate all the input wires
    # Use types, is constant to match to some kind of func signature
    func_name = str(c_ast_func_call.name.name)
    var_name = func_name
    c_type = parser_state.existing_logic.wire_to_c_type[var_name]
    args = c_ast_func_call.args.exprs

    # As is tradition, do the easiest possible thing first
    # and see what happens for future me
    is_bit_sel = False
    if LOGIC.C_TYPES_ARE_INTEGERS([c_type]) or LOGIC.C_TYPES_ARE_FLOAT_TYPES([c_type]):
        if len(args) == 1 or len(args) == 2:
            is_bit_sel = True
    if is_bit_sel:
        # Bit select/slice
        # Resolve constant values for args strs in bit manip built in funcs
        arg_const_strs = []
        for arg in args:
            arg_const_str = RESOLVE_C_AST_NODE_TO_CONSTANT_STR(
                arg, prepend_text, parser_state
            )
            if arg_const_str is None:
                raise Exception(
                    f"Unsupported non-constant bit slicing! Use arrays of bits for now...\n{arg} {arg.coord}"
                )
            arg_const_strs.append(arg_const_str)
        # Build func name starting with type info
        if LOGIC.C_TYPES_ARE_FLOAT_TYPES([c_type]):
            bit_manip_func_name = c_type
        else:
            int_prefix = c_type.replace("_t", "")
            bit_manip_func_name = int_prefix
        # One arg/index is bit select repeated index for single bit [3:3]
        if len(arg_const_strs) == 1:
            for i in range(0, 2):
                bit_manip_func_name += "_" + arg_const_strs[0]
        # Two args is multi bit range
        elif len(arg_const_strs) == 2:
            for arg_const_str in arg_const_strs:
                bit_manip_func_name += "_" + arg_const_str
        # Unlike the C code generation section generating C headers to parse and create func def objects,
        # Do the same thing here, during function body parsing, as come across new funcs?
        (
            input_port_names,
            input_types,
            output_type,
        ) = BIT_SEL_FUNC_TO_INPUTS_TYPES_OUTPUT_TYPE(bit_manip_func_name)
        input_port_name = input_port_names[0]
        APPEND_BIT_MANIP_FUNC(bit_manip_func_name, parser_state)
        # Make up a func call to eval, copying generated C code funcs? hacky hack
        func_base_name = bit_manip_func_name
        base_name_is_name = True  # Dont need type into since base name has it
        input_port_names = [input_port_name]
        input_driver_types = [c_type]
        input_drivers = [(var_name,)]  # ref toks list
        output_driven_wire_names = driven_wire_names
        # func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_func_call)
        # Then regular narg func?
        parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            c_ast_func_call,
            func_base_name,
            base_name_is_name,
            input_drivers,
            input_driver_types,
            input_port_names,
            output_driven_wire_names,
            parser_state,
        )
        return parser_state.existing_logic
    else:
        raise Exception(
            f"Unsupported variable as function call! {var_name} {c_ast_func_call.coord}!"
        )


def C_AST_STRLEN_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    # Need to construct a function name, like hacky const ref funcs and printf
    # Make up a func call to eval
    func_base_name = (
        STRLEN_FUNC_NAME
        + "_"
        + VHDL.WIRE_TO_VHDL_NAME(C_AST_NODE_COORD_STR(c_ast_func_call))
    )
    base_name_is_name = True  # Dont need type into if coord str is enough?
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_func_call)
    input_expr_c_ast_node = c_ast_func_call.args.exprs[0]
    input_port_name = "str"
    input_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
        input_expr_c_ast_node, [input_wire_name], prepend_text, parser_state
    )
    # Get driver of input and use that type to determine strlen io types
    driver_of_input = parser_state.existing_logic.wire_driven_by[input_wire_name]
    input_type = parser_state.existing_logic.wire_to_c_type[driver_of_input]
    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_type)
    strlen = dims[0]
    bitwidth = strlen.bit_length()
    output_type = "uint" + str(bitwidth) + "_t"
    output_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
    parser_state.existing_logic.wire_to_c_type[output_wire] = output_type

    # Then do normal N ARG INST
    input_drivers = [driver_of_input]
    input_driver_types = [input_type]
    input_port_names = [input_port_name]
    output_driven_wire_names = driven_wire_names
    # Need special CE handling like printf?
    func_ce_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.CLOCK_ENABLE_NAME
    parser_state.existing_logic.wire_to_c_type[func_ce_wire] = LOGIC.BOOL_C_TYPE
    ce_driver_wire = parser_state.existing_logic.clock_enable_wires[-1]
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(
        parser_state, ce_driver_wire, [func_ce_wire], prepend_text, c_ast_func_call
    )
    # Then regular narg
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_func_call,
        func_base_name,
        base_name_is_name,
        input_drivers,
        input_driver_types,
        input_port_names,
        output_driven_wire_names,
        parser_state,
    )

    return parser_state.existing_logic


def C_AST_VHDL_TEXT_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    # print c_ast_func_call.coord
    # casthelp(c_ast_func_call)
    # sys.exit(-1)

    # One vhdl text func call marks logic - hello future me? well, hello
    text = c_ast_func_call.args.exprs[0].value.strip('"')[:]
    # hacky replace two chars \n with single char '\n'
    text = text.replace("\\" + "n", "\n")
    # similar hacky for strings
    text = text.replace("\\" + '"', '"')
    parser_state.existing_logic.vhdl_module_text = text

    # Mark as using globals, cant be sliced
    parser_state.existing_logic.uses_nonvolatile_state_regs = True

    func_name = str(c_ast_func_call.name.name)
    # print("FUNC CALL:",func_name,c_ast_func_call.coord)
    func_base_name = func_name
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_func_call)

    # Return n arg func?
    # Can use same func name and use submodule_instance_to_c_ast_node to get text?

    base_name_is_name = True
    input_drivers = []
    input_driver_types = []
    input_port_names = []
    output_driven_wire_names = driven_wire_names

    # Record output port type as the to_type
    # output_wire_name=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
    # output_t = None
    # parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_t

    return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_func_call,
        func_base_name,
        base_name_is_name,
        input_drivers,
        input_driver_types,
        input_port_names,
        output_driven_wire_names,
        parser_state,
    )


# TODO upon other 'implict template' functions refactor, for now demo with accum
def C_AST_ACCUM_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    """
    # Unlike the C code generation section generating C headers to parse and create func def objects,
    # Do the same thing here, during function body parsing, as come across new funcs?
    input_port_names, input_types, output_type = BIT_SEL_FUNC_TO_INPUTS_TYPES_OUTPUT_TYPE(bit_manip_func_name)
    input_port_name = input_port_names[0]
    if bit_manip_func_name not in parser_state.FuncLogicLookupTable:
      bit_manip_func_logic = Logic()
      bit_manip_func_logic.func_name = bit_manip_func_name
      bit_manip_func_logic.inputs.append(input_port_name)
      bit_manip_func_logic.wire_to_c_type[input_port_name] = c_type
      bit_manip_func_logic.outputs.append(RETURN_WIRE_NAME)
      bit_manip_func_logic.wire_to_c_type[RETURN_WIRE_NAME] = output_type
      bit_manip_func_logic.is_vhdl_func = True
      bit_manip_func_logic.is_new_style_bit_manip = True
      parser_state.FuncLogicLookupTable[bit_manip_func_name] = bit_manip_func_logic
    """

    # Tempalte/built in style
    base_name_is_name = False  # DO NEED types appended
    func_base_name = LOGIC.ACCUM_FUNC_NAME
    input_port_names = ["increment", "reset_and_read"]
    input_driver_types = [None, "uint1_t"]  # Inc type unknown now is ok?
    input_drivers = list(c_ast_func_call.args.exprs)  # c ast nodes
    output_driven_wire_names = driven_wire_names
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_func_call)
    # Then regular narg func?
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_func_call,
        func_base_name,
        base_name_is_name,
        input_drivers,
        input_driver_types,
        input_port_names,
        output_driven_wire_names,
        parser_state,
    )
    return parser_state.existing_logic


def C_AST_FUNC_CALL_TO_LOGIC(
    c_ast_func_call, driven_wire_names, prepend_text, parser_state
):
    FuncLogicLookupTable = parser_state.FuncLogicLookupTable
    func_name = str(c_ast_func_call.name.name)
    if func_name not in FuncLogicLookupTable:
        # Uhh.. lets check for some built in compiler things because
        # stacking complexity without real planning is like totally rad
        # Dude - rad indeed, lets keep it going with printf
        # Aww can brams get in on this too?
        # Animal Collective - Sand That Moves
        # Just wait and see how vars as func names works out!
        if func_name == LOGIC.VHDL_FUNC_NAME:
            return C_AST_VHDL_TEXT_FUNC_CALL_TO_LOGIC(
                c_ast_func_call, driven_wire_names, prepend_text, parser_state
            )
        elif func_name == LOGIC.PRINTF_FUNC_NAME:
            return C_AST_PRINTF_FUNC_CALL_TO_LOGIC(
                c_ast_func_call, driven_wire_names, prepend_text, parser_state
            )
        elif func_name == STRLEN_FUNC_NAME:
            return C_AST_STRLEN_FUNC_CALL_TO_LOGIC(
                c_ast_func_call, driven_wire_names, prepend_text, parser_state
            )
        elif "_" + LOGIC.RAM_SP_RF in func_name:
            # Hacky af remove def of original state reg local (is used by mangled func)
            local_static_var = func_name.split("_" + LOGIC.RAM_SP_RF)[0]
            if local_static_var not in parser_state.existing_logic.state_regs:
                print(
                    "Doesnt look like",
                    local_static_var,
                    "was recognized as correct",
                    LOGIC.RAM_SP_RF,
                    "RAM template?",
                    c_ast_func_call.coord,
                )
                sys.exit(-1)
            parser_state.existing_logic.state_regs.pop(local_static_var)
            num_non_vol_left = 0
            for (
                state_var,
                state_var_info,
            ) in parser_state.existing_logic.state_regs.items():
                if not state_var_info.is_volatile:
                    num_non_vol_left += 1
            if num_non_vol_left == 0:
                parser_state.existing_logic.uses_nonvolatile_state_regs = False
            # Mangle to include local func name calling this func
            func_name = parser_state.existing_logic.func_name + "_" + func_name
        elif "_" + LOGIC.RAM_DP_RF in func_name:
            # Hacky af remove def of original state reg local (is used by mangled func)
            local_static_var = func_name.split("_" + LOGIC.RAM_DP_RF)[0]
            if local_static_var not in parser_state.existing_logic.state_regs:
                print(
                    "Doesnt look like",
                    local_static_var,
                    "was recognized as correct",
                    LOGIC.RAM_DP_RF,
                    "RAM template?",
                    c_ast_func_call.coord,
                )
                sys.exit(-1)
            parser_state.existing_logic.state_regs.pop(local_static_var)
            num_non_vol_left = 0
            for (
                state_var,
                state_var_info,
            ) in parser_state.existing_logic.state_regs.items():
                if not state_var_info.is_volatile:
                    num_non_vol_left += 1
            if num_non_vol_left == 0:
                parser_state.existing_logic.uses_nonvolatile_state_regs = False
            # Mangle to include local func name calling this func
            func_name = parser_state.existing_logic.func_name + "_" + func_name
        elif func_name in parser_state.existing_logic.variable_names:
            # Super hacky vars as func names
            return C_AST_VAR_AS_FUNC_CALL_TO_LOGIC(
                c_ast_func_call, driven_wire_names, prepend_text, parser_state
            )
        elif func_name == LOGIC.ACCUM_FUNC_NAME:
            return C_AST_ACCUM_FUNC_CALL_TO_LOGIC(
                c_ast_func_call, driven_wire_names, prepend_text, parser_state
            )
        else:
            # Ok panic
            print(
                "C_AST_FUNC_CALL_TO_LOGIC Havent parsed func name '"
                + func_name
                + "' yet. Where does that function come from?"
            )
            print(c_ast_func_call.coord)
            # casthelp(c_ast_func_call)
            # print(0/0)
            sys.exit(-1)

    # Lookup the parsed C function def
    not_inst_func_logic = FuncLogicLookupTable[func_name]
    # print "FUNC CALL:",func_name,c_ast_func_call.coord
    func_base_name = func_name

    # N input port names named by their arg name
    # Decompose inputs to N ARG FUNCTION
    input_drivers = []  # Wires or C ast nodes
    input_driver_types = []  # Might be none if not known
    input_port_names = []  # Port names on submodule

    # Helpful check
    args_len_as_used = 0
    if c_ast_func_call.args is not None and c_ast_func_call.args.exprs is not None:
        args_len_as_used = len(c_ast_func_call.args.exprs)
    if args_len_as_used != len(not_inst_func_logic.inputs):
        print(
            "The function definition for",
            func_name,
            "has",
            len(not_inst_func_logic.inputs),
            "arguments.",
        )
        print("At", c_ast_func_call.coord, "it has", args_len_as_used, "arguments.")
        sys.exit(-1)

    # Assume inputs are in arg order
    for i in range(0, len(not_inst_func_logic.inputs)):
        input_port_name = not_inst_func_logic.inputs[i]
        input_c_ast_node = c_ast_func_call.args.exprs[i]
        input_c_type = not_inst_func_logic.wire_to_c_type[input_port_name]
        input_drivers.append(input_c_ast_node)
        input_driver_types.append(input_c_type)
        input_port_names.append(input_port_name)

    # Decompose inputs to N ARG FUNCTION
    func_c_ast_node = c_ast_func_call
    func_base_name = func_name  # Is C name so unique
    base_name_is_name = True
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        func_c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        driven_wire_names,
        parser_state,
    )

    return parser_state.existing_logic


def C_AST_CAST_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    output_t = str(c_ast_node.to_type.type.type.names[0])
    # Need to evaluate input node/type first
    func_base_name = LOGIC.CAST_FUNC_NAME_PREFIX + "_" + output_t
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_node)
    input_port_name = "rhs"
    input_port_wire = func_inst_name + LOGIC.SUBMODULE_MARKER + input_port_name
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
        c_ast_node.expr, [input_port_wire], prepend_text, parser_state
    )
    rhs_type = parser_state.existing_logic.wire_to_c_type[input_port_wire]
    rhs_driver_wire = parser_state.existing_logic.wire_driven_by[input_port_wire]

    # Return n arg func
    base_name_is_name = False  # append types in name too
    input_drivers = [rhs_driver_wire]
    input_driver_types = [rhs_type]
    input_port_names = [input_port_name]
    output_driven_wire_names = driven_wire_names
    # Record output port type as the to_type
    output_wire_name = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
    parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_t

    # TODO Sanity dont make submodule doing pass through wire?
    # if rhs_type != output_t:
    return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,
        input_driver_types,
        input_port_names,
        output_driven_wire_names,
        parser_state,
    )
    # else:
    #  # Just connect wire BUT HOW - already connected to cast submodule - do rip up?
    #  APPLY_CONNECT_WIRES_LOGIC(parser_state,


def C_AST_SIZEOF_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
    # This is weird - todo error check
    c_type_str = c_ast_node.expr.type.type.names[0]
    # Replace with constant
    size = LOGIC.C_TYPE_SIZE(c_type_str, parser_state, False, c_ast_node)
    value_str = str(size)
    is_negated = False
    return NON_ENUM_CONST_VALUE_STR_TO_LOGIC(
        value_str, c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated
    )


def C_AST_UNARY_OP_TO_LOGIC(
    c_ast_unary_op, driven_wire_names, prepend_text, parser_state
):
    # What op?
    c_ast_unary_op_str = str(c_ast_unary_op.op)

    # Apparently sizeof() is a unary op - cool
    if c_ast_unary_op_str == "sizeof":
        # Replace with constant
        return C_AST_SIZEOF_TO_LOGIC(
            c_ast_unary_op, driven_wire_names, prepend_text, parser_state
        )

    # Decompose to N arg func
    existing_logic = parser_state.existing_logic

    # Is this UNARY op negating a constant?
    if (c_ast_unary_op_str == "-") and (type(c_ast_unary_op.expr) is c_ast.Constant):
        # THis is just a constant wire with negative value
        return C_AST_CONSTANT_TO_LOGIC(
            c_ast_unary_op.expr,
            driven_wire_names,
            prepend_text,
            parser_state,
            is_negated=True,
        )

    # Determine op string to use in func name
    is_bool_op = False
    if c_ast_unary_op_str == "!":
        is_bool_op = True
        c_ast_op_str = LOGIC.UNARY_OP_NOT_NAME
    elif c_ast_unary_op_str == "~":
        c_ast_op_str = LOGIC.UNARY_OP_NOT_NAME
    elif c_ast_unary_op_str == "-":
        c_ast_op_str = LOGIC.UNARY_OP_NEGATE_NAME
    else:
        print(
            "Unsupported unary op '" + c_ast_unary_op_str + "'?", c_ast_unary_op.coord
        )
        sys.exit(-1)

    # Set port names based on func name
    func_base_name = LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
    base_name_is_name = False  # No needs types attached
    input_drivers = []  # Wires or C ast nodes
    input_driver_types = []  # Might be none if not known
    input_port_names = []  # Port names on submodule

    # Get input wire type by evaluating input expression
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_unary_op)
    unary_op_input_port_name = c_ast_unary_op.children()[0][0]
    input_port_names.append(unary_op_input_port_name)
    unary_op_input = func_inst_name + LOGIC.SUBMODULE_MARKER + unary_op_input_port_name
    unary_op_output = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
    # Evaluate input node
    if is_bool_op:  # TODO invert bool !=0 check since know this is !(input!=0)
        parser_state.existing_logic = C_AST_BOOL_COND_NODE_TO_LOGIC(
            c_ast_unary_op.expr, [unary_op_input], prepend_text, parser_state
        )
    else:
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_unary_op.expr, [unary_op_input], prepend_text, parser_state
        )

    # Input types must be known for constant type resolve
    if unary_op_input not in parser_state.existing_logic.wire_to_c_type:
        print(func_inst_name, "looks like unknown type unary op, what's going on?")
        print("parser_state.existing_logic.wire_to_c_type")
        print(parser_state.existing_logic.wire_to_c_type)
        sys.exit(-1)
    expr_type = parser_state.existing_logic.wire_to_c_type[unary_op_input]
    input_driver_types.append(expr_type)
    in_driver_wire = parser_state.existing_logic.wire_driven_by[unary_op_input]
    input_drivers.append(in_driver_wire)
    func_name = LOGIC.BUILD_FUNC_NAME(
        func_base_name, None, input_driver_types, base_name_is_name
    )

    # Operator overload?
    if func_name in parser_state.FuncLogicLookupTable:
        func_logic = parser_state.FuncLogicLookupTable[func_name]
        output_c_type = func_logic.wire_to_c_type[LOGIC.RETURN_WIRE_NAME]
    # Determine output type based on operator or driving wire type
    else:
        # Most unary ops use the type of the driven wire
        if c_ast_unary_op_str == "!":
            output_c_type = LOGIC.BOOL_C_TYPE
        elif c_ast_unary_op_str == "~":
            output_c_type = expr_type
        # Negate is like signed mult by -1
        elif c_ast_unary_op_str == "-":
            if LOGIC.C_TYPE_IS_FLOAT_TYPE(expr_type):
                output_c_type = expr_type
            else:
                # Integer types
                input_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(expr_type)
                output_c_type = "int" + str(input_width + 1) + "_t"
        else:
            print("Output C type for c_ast_unary_op_str '" + c_ast_unary_op_str + "'?")
            sys.exit(-1)

    # Set type for output wire
    # parser_state.existing_logic.wire_to_c_type[unary_op_output] = output_c_type

    func_c_ast_node = c_ast_unary_op
    func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        func_c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        driven_wire_names,
        parser_state,
        output_c_type,
    )
    for driven_wire_name in driven_wire_names:
        if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driven_wire_name] = output_c_type

    parser_state.existing_logic = func_logic

    return func_logic


# Assumes [0] is left, [1] is right
def GET_INTEGER_MAX_SIZE_INFO(c_integer_types):
    # Signed?
    signed = False
    max_width = 0
    max_unsigned_width = 0
    left_unsigned_width = None
    left_width = None
    right_unsigned_width = None
    right_width = None
    left_max_val = None
    left_min_val = None
    right_max_val = None
    right_min_val = None
    for i, c_type in enumerate(c_integer_types):
        if i == 0:
            # Left
            if LOGIC.C_TYPE_IS_INT_N(c_type):
                left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
                left_min_val = (pow(2, left_width) / 2) * -1
                left_max_val = (pow(2, left_width) / 2) - 1
                left_unsigned_width = left_width - 1
                signed = True
            else:
                left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
                left_unsigned_width = left_width
                left_min_val = 0
                left_max_val = pow(2, left_unsigned_width) - 1
        if i == 1:
            # Right
            if LOGIC.C_TYPE_IS_INT_N(c_type):
                right_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
                right_min_val = (pow(2, right_width) / 2) * -1
                right_max_val = (pow(2, right_width) / 2) - 1
                right_unsigned_width = right_width - 1
                signed = True
            else:
                right_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
                right_unsigned_width = right_width
                right_min_val = 0
                right_max_val = pow(2, right_unsigned_width) - 1
        # Normal >2 args case
        unsigned_width = None
        width = None
        if LOGIC.C_TYPE_IS_INT_N(c_type):
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
            unsigned_width = width - 1
            signed = True
        else:
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
            unsigned_width = width

        # Max?
        max_width = max(max_width, width)
        max_unsigned_width = max(max_unsigned_width, unsigned_width)

    return (
        signed,
        left_width,
        left_unsigned_width,
        right_width,
        right_unsigned_width,
        max_width,
        max_unsigned_width,
        left_max_val,
        left_min_val,
        right_max_val,
        right_min_val,
    )


def C_AST_BINARY_OP_TO_LOGIC(
    c_ast_binary_op, driven_wire_names, prepend_text, parser_state
):
    # print c_ast_binary_op
    # print C_AST_NODE_COORD_STR(c_ast_binary_op)
    # print "=="

    # Decompose to N arg func
    c_ast_bin_op_str = str(c_ast_binary_op.op)

    # Default to global default mult style
    local_mult_style = MULT_STYLE
    if parser_state.existing_logic.func_name in parser_state.func_mult_style:
        local_mult_style = parser_state.func_mult_style[
            parser_state.existing_logic.func_name
        ]

    # Determine op string to use in func name
    is_bit_shift = False
    is_bool_op = False
    if c_ast_bin_op_str == ">":
        c_ast_op_str = LOGIC.BIN_OP_GT_NAME
    elif c_ast_bin_op_str == ">=":
        c_ast_op_str = LOGIC.BIN_OP_GTE_NAME
    elif c_ast_bin_op_str == "<":
        c_ast_op_str = LOGIC.BIN_OP_LT_NAME
    elif c_ast_bin_op_str == "<=":
        c_ast_op_str = LOGIC.BIN_OP_LTE_NAME
    elif c_ast_bin_op_str == "+":
        c_ast_op_str = LOGIC.BIN_OP_PLUS_NAME
    elif c_ast_bin_op_str == "-":
        c_ast_op_str = LOGIC.BIN_OP_MINUS_NAME
    elif c_ast_bin_op_str == "*" and local_mult_style == MULT_STYLE_INFERRED:
        c_ast_op_str = LOGIC.BIN_OP_INFERRED_MULT_NAME
    elif c_ast_bin_op_str == "*" and local_mult_style == MULT_STYLE_FABRIC:
        c_ast_op_str = LOGIC.BIN_OP_MULT_NAME
    elif c_ast_bin_op_str == "/":
        c_ast_op_str = LOGIC.BIN_OP_DIV_NAME
    elif c_ast_bin_op_str == "==":
        c_ast_op_str = LOGIC.BIN_OP_EQ_NAME
    elif c_ast_bin_op_str == "!=":
        c_ast_op_str = LOGIC.BIN_OP_NEQ_NAME
    elif c_ast_bin_op_str == "&":
        c_ast_op_str = LOGIC.BIN_OP_AND_NAME
    elif c_ast_bin_op_str == "|":
        c_ast_op_str = LOGIC.BIN_OP_OR_NAME
    elif c_ast_bin_op_str == "^":
        c_ast_op_str = LOGIC.BIN_OP_XOR_NAME
    elif c_ast_bin_op_str == "<<":
        c_ast_op_str = LOGIC.BIN_OP_SL_NAME
        is_bit_shift = True
    elif c_ast_bin_op_str == ">>":
        c_ast_op_str = LOGIC.BIN_OP_SR_NAME
        is_bit_shift = True
    elif c_ast_bin_op_str == "%":
        c_ast_op_str = LOGIC.BIN_OP_MOD_NAME
    elif c_ast_bin_op_str == "&&":
        is_bool_op = True
        c_ast_op_str = LOGIC.BIN_OP_AND_NAME
    elif c_ast_bin_op_str == "||":
        is_bool_op = True
        c_ast_op_str = LOGIC.BIN_OP_OR_NAME
    else:
        print("BIN_OP name for c_ast_bin_op_str '" + c_ast_bin_op_str + "'?")
        sys.exit(-1)

    # Set port names based on func name
    func_base_name = LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
    base_name_is_name = False  # Need types attached

    # Inputs
    # Decompose for SEQ_C_AST_NODES_TO_LOGIC
    # dict[c_ast_input_node] => [list of driven wire names]
    # How to resolve type of () + () ?
    # Must evaluate in advance
    bin_op_left_input_port_name = c_ast_binary_op.children()[0][0]
    bin_op_right_input_port_name = c_ast_binary_op.children()[1][0]
    func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_binary_op)
    bin_op_left_input = func_inst_name + LOGIC.SUBMODULE_MARKER + bin_op_left_input_port_name
    bin_op_right_input = (
        func_inst_name + LOGIC.SUBMODULE_MARKER + bin_op_right_input_port_name
    )
    if is_bool_op:
        parser_state.existing_logic = C_AST_BOOL_COND_NODE_TO_LOGIC(
            c_ast_binary_op.left, [bin_op_left_input], prepend_text, parser_state
        )
        parser_state.existing_logic = C_AST_BOOL_COND_NODE_TO_LOGIC(
            c_ast_binary_op.right, [bin_op_right_input], prepend_text, parser_state
        )
    else:
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_binary_op.left, [bin_op_left_input], prepend_text, parser_state
        )
        parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            c_ast_binary_op.right, [bin_op_right_input], prepend_text, parser_state
        )

    # Was either input type evaluated?
    left_type = None
    if bin_op_left_input in parser_state.existing_logic.wire_to_c_type:
        left_type = parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
    right_type = None
    if bin_op_right_input in parser_state.existing_logic.wire_to_c_type:
        right_type = parser_state.existing_logic.wire_to_c_type[bin_op_right_input]

    # Output is determined by funcitonality - NOT WHAT the functionality drives
    output_c_type = None

    # By now the input wires have been connected - CAST inserted as needed
    #
    #
    #    From here on we can only adjust input wires in ways that can be resolved with
    #       VHDL 0 CLK CAST OPERATIONS ONLY - i.e. signed to unsigned, resize, enum to unsigned, etc
    #
    #

    # If types are integers then check signed/unsigned matches
    #   Change type from unsigned to sign by adding bit to type
    #   Never change signed to unsigned dumb
    if LOGIC.C_TYPES_ARE_INTEGERS([left_type, right_type]) and not is_bit_shift:
        left_signed = LOGIC.C_TYPE_IS_INT_N(left_type)
        right_signed = LOGIC.C_TYPE_IS_INT_N(right_type)
        left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_type)
        right_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_type)
        if left_signed != right_signed:
            if left_signed:
                # Update right
                right_type = "int" + str(right_width + 1) + "_t"
                parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = (
                    right_type
                )
            if right_signed:
                # Update left
                left_type = "int" + str(left_width + 1) + "_t"
                parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = (
                    left_type
                )

    # If types are floats, round to common float format needed
    # This is instead of having non-equal width FP binary op
    if LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_type, right_type]):
        common_fp_type = LOGIC.C_FLOAT_TYPES_TO_COMMON_TYPE([left_type, right_type])
        left_type = common_fp_type
        parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
        right_type = common_fp_type
        parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type

    # ENUM constant strings driving ports wont know what enum type they are
    # need to detect enum variables of known type and apply to wires
    # Left correcting right port + driver of port
    if left_type in parser_state.enum_info_dict:
        enum_type = left_type
        if right_type is None:
            right_type = enum_type
            parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
        driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
        if driving_wire not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
    # Right correcting left port + driver of port
    if right_type in parser_state.enum_info_dict:
        enum_type = right_type
        if left_type is None:
            left_type = enum_type
            parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
        driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
        if driving_wire not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type

    # Convert binary operator enum input ports to u/int as needed
    # Not done for not-one hot since need custom one hot operators
    # Left correcting left+right ports
    if (
        left_type in parser_state.enum_info_dict
        and left_type not in parser_state.marked_onehot
    ):
        # Normal enum convert BIN OP ports to integer type
        enum_int_type = parser_state.enum_info_dict[left_type].int_c_type
        left_type = enum_int_type
        parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
        if right_type is None or LOGIC.C_TYPE_IS_ENUM(right_type, parser_state):
            right_type = left_type
            parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
    # Right correcting left+right ports
    if (
        right_type in parser_state.enum_info_dict
        and right_type not in parser_state.marked_onehot
    ):
        # Normal enum convert BIN OP ports to integer type
        enum_int_type = parser_state.enum_info_dict[right_type].int_c_type
        right_type = enum_int_type
        parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
        if left_type is None or LOGIC.C_TYPE_IS_ENUM(left_type, parser_state):
            left_type = right_type
            parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type

    # Same thing as ENUM (wanting bin op port to be int so cast happens)
    # Dont want bin op ports based on char type or enum types
    if left_type == "char":
        left_type = "uint8_t"
        parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
    if right_type == "char":
        right_type = "uint8_t"
        parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type

    # Force int bit shifts to have uint RHS (neg shift undefined)
    right_signed = LOGIC.C_TYPE_IS_INT_N(right_type)
    if LOGIC.C_TYPES_ARE_INTEGERS([left_type]) and is_bit_shift and right_signed:
        right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
        resized_prefix = "uint" + str(right_width)
        resized_t = resized_prefix + "_t"
        right_type = resized_t
        parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type

    # Can't cast float to from int in comb logic
    # No cast need for bit shifts
    if not is_bit_shift:
        if LOGIC.C_TYPE_IS_FLOAT_TYPE(left_type) and not LOGIC.C_TYPE_IS_FLOAT_TYPE(right_type):
            raise Exception(
                "TODO: Floats ops mixing types? Shouldn't occur. Add cast for now.",
                left_type,
                c_ast_bin_op_str,
                right_type,
                str(c_ast_binary_op.coord),
            )
        elif not LOGIC.C_TYPE_IS_FLOAT_TYPE(left_type) and LOGIC.C_TYPE_IS_FLOAT_TYPE(right_type):
            raise Exception(
                "TODO: Floats ops mixing types? Shouldn't occur. Add cast for now.",
                left_type,
                c_ast_bin_op_str,
                right_type,
                str(c_ast_binary_op.coord),
            )

    # Hack in resizing single dim arrays to max size
    if LOGIC.C_TYPE_IS_ARRAY(left_type) and LOGIC.C_TYPE_IS_ARRAY(right_type):
        lhs_elem_t, lhs_dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(left_type)
        rhs_elem_t, rhs_dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(right_type)
        # And swap char arrays to uint8 arrays like char to uint8 swap above
        # Swapping of char to uint8 is only necessary for compare GT/LT compares
        # Arrays arent compared iwht LT/GT right now so dont need swap
        # But ALSO doesnt hurt? and reduces code?
        if lhs_elem_t == "char":
            lhs_elem_t = "uint8_t"
        if rhs_elem_t == "char":
            rhs_elem_t = "uint8_t"
        # General array enlarging
        if lhs_elem_t == rhs_elem_t and len(lhs_dims) == 1 and len(rhs_dims) == 1:
            max_dim = max(lhs_dims[0], rhs_dims[0])
            # Set both to max size
            left_type = lhs_elem_t + "[" + str(max_dim) + "]"
            parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
            right_type = rhs_elem_t + "[" + str(max_dim) + "]"
            parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type

    # Prepare for N arg inst
    input_drivers = []  # Prefer wires
    left_driver_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
    input_drivers.append(left_driver_wire)
    right_driver_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
    input_drivers.append(right_driver_wire)
    input_port_names = []
    input_port_names.append(bin_op_left_input_port_name)
    input_port_names.append(bin_op_right_input_port_name)
    input_driver_types = []
    input_driver_types.append(left_type)
    input_driver_types.append(right_type)

    # Determine output type based on operator or driving wire type
    # Do bool operations first
    if c_ast_bin_op_str == ">":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == ">=":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "<":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "<=":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "==":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "!=":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "&&":
        output_c_type = LOGIC.BOOL_C_TYPE
    elif c_ast_bin_op_str == "||":
        output_c_type = LOGIC.BOOL_C_TYPE
    else:
        # Not bool operation
        # OUTPUT TYPE MUST BE DERIVED FROM FUNCITONALITY
        # Which ones to use?
        if (left_type is None) and (right_type is None):
            print(
                func_inst_name,
                "doesn't have type information for either inputs OR OUTPUT? What's going on?",
            )
            print("parser_state.existing_logic.wire_to_c_type")
            print("bin_op_left_input", bin_op_left_input)
            print("bin_op_right_input", bin_op_right_input)
            print("driven_wire_names", driven_wire_names)
            print("Know types:")
            print(parser_state.existing_logic.wire_to_c_type)
            sys.exit(-1)
        elif left_type is not None and (right_type is None):
            # Left type alone known
            print(func_inst_name, "Binary op with only left input type known?")
            sys.exit(-1)
            # parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
            # parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = left_type
        elif (left_type is None) and right_type is not None:
            # Right type alone known
            print(func_inst_name, "Binary op with only right input type known?")
            sys.exit(-1)
            # parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = right_type
            # parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
        else:
            # Types for both left and right are known
            # Derive output type

            # Does it match a user operator overload func?
            # No output type in func name now
            maybe_user_overload_func_name = LOGIC.BUILD_FUNC_NAME(
                func_base_name, None, [left_type, right_type], False
            )
            if maybe_user_overload_func_name in parser_state.FuncLogicLookupTable:
                overload_logic = parser_state.FuncLogicLookupTable[
                    maybe_user_overload_func_name
                ]
                output_c_type = overload_logic.wire_to_c_type[LOGIC.RETURN_WIRE_NAME]
            # New float_e_m_t types
            elif LOGIC.C_TYPES_ARE_FLOAT_TYPES(
                [left_type, right_type]
            ) and LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_type, right_type]):
                output_c_type = left_type  # same as right
            # Float shifts (mult/div by pow2)
            elif (
                is_bit_shift
                and LOGIC.C_TYPE_IS_FLOAT_TYPE(left_type)
                and LOGIC.C_TYPES_ARE_INTEGERS([right_type])
            ):
                output_c_type = left_type
            else:
                # Ints only
                if LOGIC.C_TYPES_ARE_INTEGERS([left_type, right_type]):
                    (
                        signed,
                        left_width,
                        left_unsigned_width,
                        right_width,
                        right_unsigned_width,
                        max_width,
                        max_unsigned_width,
                        left_max_val,
                        left_min_val,
                        right_max_val,
                        right_min_val,
                    ) = GET_INTEGER_MAX_SIZE_INFO([left_type, right_type])
                else:
                    print(
                        "Unsupported binary operation between types (explicit casting required for now):",
                        left_type,
                        c_ast_bin_op_str,
                        right_type,
                        c_ast_binary_op.coord,
                    )
                    sys.exit(-1)

                # Operator determines output type
                # ADD
                if c_ast_bin_op_str == "+":
                    # Result width is roughly max width + 1
                    # Ex. int32 + uint32 , result need to hold uint33 and int33, thus int34 it is
                    output_unsigned_width = max_unsigned_width + 1
                    output_width = output_unsigned_width
                    if signed:
                        output_width = output_unsigned_width + 1
                    output_c_type = "int" + str(output_width) + "_t"
                    if not signed:
                        output_c_type = "u" + output_c_type
                # SUB
                elif c_ast_bin_op_str == "-":
                    # uint - uint
                    if LOGIC.C_TYPE_IS_UINT_N(left_type) and LOGIC.C_TYPE_IS_UINT_N(
                        right_type
                    ):
                        # Width doesnt increase - is equal to LHS size
                        output_c_type = "uint" + str(left_unsigned_width) + "_t"
                    # int - uint
                    elif LOGIC.C_TYPE_IS_INT_N(left_type) and LOGIC.C_TYPE_IS_UINT_N(
                        right_type
                    ):
                        # Width doesnt increase - is equal to LHS signed size
                        output_c_type = "int" + str(left_unsigned_width + 1) + "_t"
                    # uint - int
                    # int - int
                    else:
                        # RHS is signed
                        # Subtracting an int is like adding a uint
                        # So width can increase
                        # Do like + operation
                        output_unsigned_width = max_unsigned_width + 1
                        output_width = output_unsigned_width
                        if signed:
                            output_width = output_unsigned_width + 1
                        output_c_type = "int" + str(output_width) + "_t"
                        if not signed:
                            output_c_type = "u" + output_c_type
                # MULT
                elif c_ast_bin_op_str == "*":
                    # Similar to + but bit growth is more
                    output_width = left_width + right_width
                    output_c_type = "int" + str(output_width) + "_t"
                    if not signed:
                        output_c_type = "u" + output_c_type
                # DIV
                elif c_ast_bin_op_str == "/":
                    # Signed or not, output width does not increase
                    # Is based on LHS type
                    output_unsigned_width = left_unsigned_width
                    output_width = output_unsigned_width
                    if signed:
                        output_width = output_unsigned_width + 1
                    output_c_type = "int" + str(output_width) + "_t"
                    if not signed:
                        output_c_type = "u" + output_c_type
                # MOD
                elif c_ast_bin_op_str == "%":
                    # Can only be as large as RHS
                    # Signed or not, output width does not increase
                    output_unsigned_width = right_unsigned_width
                    output_width = output_unsigned_width
                    if signed:
                        output_width = output_unsigned_width + 1
                    output_c_type = "int" + str(output_width) + "_t"
                    if not signed:
                        output_c_type = "u" + output_c_type
                # BITWISE OPS
                elif (
                    (c_ast_bin_op_str == "&")
                    or (c_ast_bin_op_str == "|")
                    or (c_ast_bin_op_str == "^")
                ):
                    # Is sized to max
                    output_c_type = "int" + str(max_width) + "_t"
                    if not signed:
                        output_c_type = "u" + output_c_type
                # Shifts
                elif c_ast_bin_op_str == "<<":
                    # Default type of left operand
                    output_c_type = left_type
                    # Shifting left is has special integer promotion
                    # And will return type of driving wire if known and larger
                    if (
                        len(driven_wire_names) > 0
                        and driven_wire_names[0]
                        in parser_state.existing_logic.wire_to_c_type
                    ):
                        driven_out_type = parser_state.existing_logic.wire_to_c_type[
                            driven_wire_names[0]
                        ]
                        driven_out_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(
                            driven_out_type
                        )
                        left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(
                            left_type
                        )
                        if driven_out_width >= left_width:
                            output_c_type = driven_out_type
                            # And re-writes input port type (left arg)
                            parser_state.existing_logic.wire_to_c_type[
                                bin_op_left_input
                            ] = output_c_type
                            input_driver_types[0] = output_c_type
                    else:
                        # Only fail if not 32b as expected in C
                        if left_width < 32:
                            print(
                                "WARNING: Unclear output type for integer promoted bitshift left input arg.",
                                c_ast_binary_op.coord,
                            )
                            # sys.exit(-1)
                elif c_ast_bin_op_str == ">>":
                    # Shifting right returns type of left operand
                    output_c_type = left_type
                else:
                    print("Output C type for '" + c_ast_bin_op_str + "'?")
                    sys.exit(-1)

    # Set type for output wire
    bin_op_output = func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME

    # print " ----- ", bin_op_output, output_c_type
    func_c_ast_node = c_ast_binary_op
    func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
        prepend_text,
        func_c_ast_node,
        func_base_name,
        base_name_is_name,
        input_drivers,  # Wires or C ast nodes
        input_driver_types,  # Might be none if not known
        input_port_names,  # Port names on submodule
        driven_wire_names,
        parser_state,
        output_c_type,
    )
    # Dont add bin_op_output wire, might have optimized away...
    # if bin_op_output not in parser_state.existing_logic.wire_to_c_type:
    #    parser_state.existing_logic.wire_to_c_type[bin_op_output] = output_c_type
    # But do resolve driven wire if not set??
    for driven_wire_name in driven_wire_names:
        if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
            parser_state.existing_logic.wire_to_c_type[driven_wire_name] = output_c_type

    # Save c ast node of binary op

    parser_state.existing_logic = func_logic
    # print "AFTER:"
    # print "parser_state.existing_logic.wire_to_c_type[bin_op_left_input]",parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
    # print "parser_state.existing_logic.wire_to_c_type[bin_op_right_input]",parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
    return func_logic


def GET_C_TYPE_FROM_WIRE_NAMES(wire_names, logic, allow_fail=False):
    rv = None
    for wire_name in wire_names:
        if wire_name not in logic.wire_to_c_type:
            if allow_fail:
                return None
            else:
                print(
                    "Cant GET_C_TYPE_FROM_WIRE_NAMES since",
                    wire_name,
                    "not in logic.wire_to_c_type",
                )
                print("logic.wire_to_c_type", logic.wire_to_c_type)
                print(0 / 0)
                sys.exit(-1)
        c_type_str = logic.wire_to_c_type[wire_name]
        if rv is None:
            rv = c_type_str
        else:
            if rv != c_type_str:
                print("GET_C_TYPE_FROM_WIRE_NAMES multilpe types?")
                print("wire_name", wire_name)
                print(rv, c_type_str)
                print(0 / 0)
                sys.exit(-1)

    return rv


# def SIMPLE_CONNECT_TO_LOGIC(driving_wire, driven_wire_names, c_ast_node, prepend_text, parser_state):
def APPLY_CONNECT_WIRES_LOGIC(
    parser_state,
    driving_wire,
    driven_wire_names,
    prepend_text,
    c_ast_node,
    check_types_do_cast=True,
):  # print "driving_wire",driving_wire,"=>",driven_wire_names
    # Add wire
    parser_state.existing_logic.wires.add(driving_wire)
    for driven_wire_name in driven_wire_names:
        parser_state.existing_logic.wires.add(driven_wire_name)

    if check_types_do_cast:
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        # Look up that type and make sure if the driven wire names have types that they match
        # INSERT CAST FUNCTION if needed
        # print c_ast_id.coord
        if driving_wire not in parser_state.existing_logic.wire_to_c_type:
            print(
                "Looks like wire'",
                driving_wire,
                "'isn't declared? Doing weird stuff with types/enums maybe?",
            )
            print(c_ast_node.coord)
            # print(0/0)
            sys.exit(-1)
        rhs_type = parser_state.existing_logic.wire_to_c_type[driving_wire]
        for driven_wire_name in driven_wire_names:
            # TODO implement look ahead for built in operators. Yairms - Real Time
            # Assume driven wire is same type as rhs -SHOULDNT NEED THIS FOR ANYTHING OTHER THAN BUILT IN OPERATION BUT NOT CHECK THAT NOW SINCE LIKE WHY WHAT IS LIFE ALL ABOUT?
            if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
                # print "Need to know type of wire",driven_wire_name," before connecting to it?"
                # print 0/0
                # sys.exit(-1)
                parser_state.existing_logic.wire_to_c_type[driven_wire_name] = rhs_type

            # CHECK TYPE, APPLY CASTY IF NEEDED
            driven_wire_type = parser_state.existing_logic.wire_to_c_type[
                driven_wire_name
            ]
            if driven_wire_type != rhs_type:
                #######
                # Some C casts are handled in VHDL with resize or enum conversions
                #
                # Integer promotion / slash supported truncation in C lets this be OK
                # Chars are essentially uint8_t
                # if CAST_HANDLED_IN_VHDL(driven_wire_type, rhs_type, parser_state):
                if (
                    LOGIC.WIRES_ARE_INT_N(
                        [driven_wire_name], parser_state.existing_logic
                    )
                    or LOGIC.WIRES_ARE_UINT_N(
                        [driven_wire_name], parser_state.existing_logic
                    )
                ) and (
                    LOGIC.C_TYPE_IS_INT_N(rhs_type) or LOGIC.C_TYPE_IS_UINT_N(rhs_type)
                ):
                    continue
                # Enum driving U/INT is fine
                elif (
                    LOGIC.WIRES_ARE_UINT_N(
                        [driven_wire_name], parser_state.existing_logic
                    )
                    or LOGIC.WIRES_ARE_INT_N(
                        [driven_wire_name], parser_state.existing_logic
                    )
                ) and LOGIC.WIRE_IS_ENUM(
                    driving_wire, parser_state.existing_logic, parser_state
                ):
                    continue
                # U/INT driving enum is fine
                elif LOGIC.WIRE_IS_ENUM(
                    driven_wire_name, parser_state.existing_logic, parser_state
                ) and (
                    LOGIC.WIRES_ARE_UINT_N([driving_wire], parser_state.existing_logic)
                    or LOGIC.WIRES_ARE_INT_N([driving_wire], parser_state.existing_logic)
                ):
                    continue

                # Getting pretty hacky here with this 'internal' / PipelineC specific code
                # Could do for all...single/multi? dimension int-like(having null/0) arrays?
                elif LOGIC.C_TYPE_IS_ARRAY(driven_wire_type) and LOGIC.C_TYPE_IS_ARRAY(rhs_type):
                    lhs_elem_t, lhs_dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        driven_wire_type
                    )
                    rhs_elem_t, rhs_dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(rhs_type)
                    # Only exact type elems for now, allow char uint8
                    if (
                        len(lhs_dims) != 1
                        or len(rhs_dims) != 1
                        or (
                            lhs_elem_t != rhs_elem_t
                            and not (
                                (lhs_elem_t == "char" and rhs_elem_t == "uint8_t")
                                or (rhs_elem_t == "char" and lhs_elem_t == "uint8_t")
                            )
                        )
                    ):
                        # Unhandled
                        raise Exception(
                            "Error handling assignment of array element type or size : RHS",
                            driving_wire,
                            rhs_elem_t,
                            "drives LHS",
                            driven_wire_name,
                            lhs_elem_t,
                            str(c_ast_node.coord),
                        )
                    # Allow it to be resolved in VHDL
                    continue
                # I'm dumb and C doesnt return arrays - I think this is only needed for internal code
                elif (
                    LOGIC.C_TYPE_IS_ARRAY_STRUCT(driven_wire_type, parser_state)
                    and (
                        LOGIC.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(
                            driven_wire_type, parser_state
                        )
                        == rhs_type
                    )
                ) or (
                    LOGIC.C_TYPE_IS_ARRAY_STRUCT(rhs_type, parser_state)
                    and (
                        driven_wire_type
                        == LOGIC.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(
                            rhs_type, parser_state
                        )
                    )
                ):
                    continue
                # Float casting is wires in VHDl for now
                elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([driven_wire_type, rhs_type]):
                    continue

                #######
                # At this point we have incompatible types that need special casting logic
                #     Build cast function to connect driving wire to driven wire-
                # int = float
                # float = int
                # float = uint
                # DONT do uint = float since force int cast for now
                if (
                    (
                        LOGIC.C_TYPE_IS_INT_N(rhs_type)
                        and LOGIC.C_TYPE_IS_FLOAT_TYPE(driven_wire_type)
                    )
                    or (
                        LOGIC.C_TYPE_IS_FLOAT_TYPE(rhs_type)
                        and LOGIC.C_TYPE_IS_INT_N(driven_wire_type)
                    )
                    or (
                        LOGIC.C_TYPE_IS_UINT_N(rhs_type)
                        and LOGIC.C_TYPE_IS_FLOAT_TYPE(driven_wire_type)
                    )
                ):
                    # Return n arg func
                    func_base_name = LOGIC.CAST_FUNC_NAME_PREFIX + "_" + driven_wire_type
                    base_name_is_name = False  # append types in name too
                    input_drivers = [driving_wire]
                    input_driver_types = [rhs_type]
                    input_port_names = ["rhs"]
                    output_driven_wire_names = driven_wire_names
                    # Build instance name
                    func_inst_name = BUILD_INST_NAME(
                        prepend_text, func_base_name, c_ast_node
                    )
                    # print("cast",func_inst_name,rhs_type,driven_wire_type)
                    # Record output port type
                    output_wire_name = (
                        func_inst_name + LOGIC.SUBMODULE_MARKER + LOGIC.RETURN_WIRE_NAME
                    )
                    parser_state.existing_logic.wire_to_c_type[output_wire_name] = (
                        driven_wire_type
                    )

                    return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
                        prepend_text,
                        c_ast_node,
                        func_base_name,
                        base_name_is_name,
                        input_drivers,
                        input_driver_types,
                        input_port_names,
                        output_driven_wire_names,
                        parser_state,
                    )

                else:
                    # Unhandled
                    print(
                        "RHS",
                        driving_wire,
                        "drives LHS",
                        driven_wire_name,
                        "with different types?",
                        c_ast_node.coord,
                    )
                    print(driven_wire_type, "!=", rhs_type)
                    print(
                        "Implement nasty casty?"
                    )  # Fat White Family - Tastes Good With The Money
                    # print(0/0)
                    sys.exit(-1)

        # ^^^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^

    #########   Record connnnnections in the parser_state.existing_logic graph ######
    return LOGIC.CONNECT_WIRES_LOGIC(
        parser_state.existing_logic, driving_wire, driven_wire_names
    )


# int x[2]     returns "x", "int", 2
# int x[2][2]  returns "x", "int[2]", 2
def C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(array_decl, parser_state):
    # casthelp(array_decl)
    # print
    # sys.exit(-1)

    # Will be N nested ArrayDecls with dimensions folowed by the element type
    children = array_decl.children()
    dims = []
    while len(children) > 1 and children[1][0] == "dim":
        # Get the dimension with dummies
        dummy_parser_state = parser_state.DEEPCOPY()  # ParserState() # too slow?
        dummy_parser_state.existing_logic = LOGIC.Logic()
        dummy_parser_state.existing_logic.func_name = "ARRAY_DECL"
        dummy_wire = "ARRAY_DECL_DIM"
        dummy_parser_state.existing_logic = C_AST_NODE_TO_LOGIC(
            children[1][1], [dummy_wire], "", dummy_parser_state
        )
        driving_wire = dummy_parser_state.existing_logic.wire_driven_by[dummy_wire]
        const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
            driving_wire, dummy_parser_state.existing_logic
        )
        if const_driving_wire is None:
            raise Exception("Array dimensions not constant!", str(array_decl.coord))
        dim = int(
            LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                const_driving_wire,
                dummy_parser_state.existing_logic,
                dummy_parser_state,
            )
        )
        if dim <= 0:
            raise Exception("Array dimensions not >=1!", dim, str(array_decl.coord))
        # dim = int(children[1][1].value)
        dims.append(dim)
        array_decl = children[0][1]
        children = array_decl.children()

    # Reverse order from parsing
    # dims = dims[::-1]

    # Get base type
    # Array decl is now holding the inner type
    type_decl = array_decl
    type_name = type_decl.type.names[0]
    # casthelp(type_decl)
    # print "type_decl^"

    # Append everything but last dim
    elem_type = type_name
    for dim_i in range(0, len(dims) - 1):
        elem_type = elem_type + "[" + str(dims[dim_i]) + "]"

    dim = dims[len(dims) - 1]
    # print elem_type
    # print dim
    # sys.exit(-1)
    return type_decl.declname, elem_type, dim


_C_AST_FUNC_DEF_TO_LOGIC_cache = {}


def C_AST_FUNC_DEF_TO_LOGIC(
    c_ast_funcdef, parser_state, parse_body=True, only_fsm_clk_funcs=False
):
    # Reset state for this func def
    parser_state.existing_logic = None

    # Since no existing logic, can cache entire existing logic here
    if c_ast_funcdef.decl.name in _C_AST_FUNC_DEF_TO_LOGIC_cache:
        parser_state.existing_logic = _C_AST_FUNC_DEF_TO_LOGIC_cache[
            c_ast_funcdef.decl.name
        ]
        return parser_state.existing_logic

    # print("FUNC_DEF",c_ast_funcdef, flush=True)

    parser_state.existing_logic = LOGIC.Logic()
    # Save the c_ast node
    parser_state.existing_logic.ast_meta = C_AST_NODE_TO_META(c_ast_funcdef)

    # All func def logic has an output wire called "return"
    return_type = c_ast_funcdef.decl.type.type.type.names[0]
    if return_type != "void":
        return_wire_name = LOGIC.RETURN_WIRE_NAME
        parser_state.existing_logic.outputs.append(return_wire_name)
        parser_state.existing_logic.wires.add(return_wire_name)
        # print("return_type",return_type)
        parser_state.existing_logic.wire_to_c_type[return_wire_name] = return_type

    # First get name of function from the declaration
    parser_state.existing_logic.func_name = c_ast_funcdef.decl.name

    # Then get input wire names from the function def
    # print "func def:",c_ast_funcdef
    if c_ast_funcdef.decl.type.args is not None:
        for param_decl in c_ast_funcdef.decl.type.args.params:
            input_wire_name = param_decl.name
            parser_state.existing_logic.inputs.append(input_wire_name)
            parser_state.existing_logic.wires.add(input_wire_name)
            parser_state.existing_logic.variable_names.add(input_wire_name)
            # print "Append input", input_wire_name
            c_type, input_var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(
                param_decl, parser_state
            )
            parser_state.existing_logic.wire_to_c_type[input_wire_name] = c_type

    # In addition to inputs and outputs
    # All func bodys can see globally defined variable names
    # Instead of processing upon finding global names multiple times
    # do a single copy of info from global to local func
    all_ids = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(c_ast_funcdef.body)
    for id_node in all_ids:
        var_name = str(id_node.name)
        parser_state.existing_logic = MAYBE_GLOBAL_DECL_TO_LOGIC(
            var_name, parser_state, is_lhs_assign=False
        )

    # Before doing anything with the func body
    # Need to decide what kind of func
    # FSM style
    parser_state.existing_logic.is_fsm_clk_func = C_TO_FSM.FUNC_USES_FSM_CLK(
        parser_state.existing_logic.func_name, parser_state
    )
    # print(parser_state.existing_logic.func_name,"is_fsm_clk_func",parser_state.existing_logic.is_fsm_clk_func)
    if parser_state.existing_logic.is_fsm_clk_func and only_fsm_clk_funcs:
        parser_state.existing_logic = C_TO_FSM.C_AST_FSM_FUNDEF_BODY_TO_LOGIC(
            c_ast_funcdef.body, parser_state
        )
    elif not only_fsm_clk_funcs:
        # OR default comb logic
        # Merge with logic from the body of the func def
        driven_wire_names = []
        prepend_text = ""
        if parse_body:
            body_logic = C_AST_NODE_TO_LOGIC(
                c_ast_funcdef.body, driven_wire_names, prepend_text, parser_state
            )
            parser_state.existing_logic.MERGE_COMB_LOGIC(body_logic)

        # Connect globals at end of func logic
        parser_state.existing_logic = CONNECT_FINAL_STATE_WIRES(
            prepend_text, parser_state, c_ast_funcdef
        )

        # Check if global vars are used as wires, and move them out of being recorded as state regs
        parser_state.existing_logic = MOVE_UNREAD_GLOBAL_STATE_REGS_TO_WIRES(
            prepend_text, parser_state, c_ast_funcdef
        )

        # Final chance for generated C code to do stuff to func logic
        # Hah wtf this is hacky - its calculation saving, tag now, dont compute over and over awesomness of course
        # Bright Eyes - An Attempt to Tip the Scales
        parser_state.existing_logic = GEN_CODE_POST_PARSE_LOGIC_ADJUST(
            parser_state.existing_logic, parser_state
        )

        # Sanity check for return wire
        if parse_body:
            if (
                parser_state.existing_logic.vhdl_module_text is None
                and not parser_state.existing_logic.is_clock_crossing
            ):
                for out_wire in parser_state.existing_logic.outputs:
                    if out_wire not in parser_state.existing_logic.wire_driven_by:
                        print(
                            "Not all function outputs driven!? No return value for function?",
                            parser_state.existing_logic.func_name,
                            out_wire,
                        )
                        print(
                            "(undeclared return value type is assumed 'int', explicitly declare as void instead)"
                        )
                        sys.exit(-1)

        # Check for mixing volatile and not
        has_volatile = False
        for state_reg in parser_state.existing_logic.state_regs:
            if parser_state.existing_logic.state_regs[state_reg].is_volatile:
                has_volatile = True
                break
        for state_reg in parser_state.existing_logic.state_regs:
            if (
                parser_state.existing_logic.state_regs[state_reg].is_volatile
                != has_volatile
            ):
                print(
                    "Globals for func",
                    parser_state.existing_logic.func_name,
                    "do not match volatile usage for all globals!",
                )
                sys.exit(-1)
    else:
        # No body parsing at all - return None this logic was not parsed
        return None

    # Write cache
    _C_AST_FUNC_DEF_TO_LOGIC_cache[c_ast_funcdef.decl.name] = (
        parser_state.existing_logic
    )

    return parser_state.existing_logic


def MOVE_UNREAD_GLOBAL_STATE_REGS_TO_WIRES(prepend_text, parser_state, c_ast_node):
    # This is done after func body has been parsed - data flow is used to detect wires from regs (sorta like latch detect)
    for state_reg in list(parser_state.existing_logic.state_regs.keys()):
        var_info = parser_state.existing_logic.state_regs[state_reg]
        if var_info not in parser_state.global_vars.values():
            continue
        # Try to find a wire driven by the state reg state
        state_reg_drives_things = state_reg in parser_state.existing_logic.wire_drives
        if not state_reg_drives_things:
            # print(
            #    f"Global variable {state_reg} is written to like a wire (not stateful register) inside function {parser_state.existing_logic.func_name} ..."
            # )
            # Remove from local state regs
            parser_state.existing_logic.state_regs.pop(state_reg)
            # Add to list of globals as wires
            parser_state.existing_logic.write_only_global_wires[state_reg] = var_info
            # Does this func still use non vol globals?
            num_non_vol_left = 0
            for (
                state_var,
                state_var_info,
            ) in parser_state.existing_logic.state_regs.items():
                if not state_var_info.is_volatile:
                    num_non_vol_left += 1
            if num_non_vol_left == 0:
                parser_state.existing_logic.uses_nonvolatile_state_regs = False

    return parser_state.existing_logic


def DEL_ALL_CACHES():
    # Clear all caches after parsing is done: the shared LOGIC ones, then the C front end's
    LOGIC.DEL_ALL_CACHES()
    global _other_partial_logic_cache
    global _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache
    global _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache
    global _REDUCE_REF_TOKS_OR_STRS_cache
    global _TRIM_VAR_REF_TOKS_cache
    global _REF_TOKS_COVERED_BY_cache
    global _REMOVE_COVERED_REF_TOK_BRANCHES_cache
    global _C_AST_REF_TOKS_TO_C_TYPE_cache
    global _C_AST_NODE_COORD_STR_cache
    global _C_AST_FUNC_DEF_TO_LOGIC_cache
    # global _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache

    _other_partial_logic_cache = {}
    _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache = {}
    _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache = {}
    _REDUCE_REF_TOKS_OR_STRS_cache = {}
    _TRIM_VAR_REF_TOKS_cache = {}
    _REF_TOKS_COVERED_BY_cache = {}
    _REMOVE_COVERED_REF_TOK_BRANCHES_cache = {}
    _C_AST_REF_TOKS_TO_C_TYPE_cache = {}
    _C_AST_NODE_COORD_STR_cache = {}
    _C_AST_FUNC_DEF_TO_LOGIC_cache = {}
    # _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache          = {}


def GET_PARSER_STATE_CACHE_FILEPATH(c_filename):
    # Only one file parsed for now so identify with basename and not full path
    key = os.path.basename(c_filename)
    output_directory = SYN.SYN_OUTPUT_DIRECTORY
    filepath = output_directory + "/" + key + ".parsed"
    return filepath


def WRITE_PARSER_STATE_CACHE(parser_state, c_filename):
    # Write dir first if needed
    output_directory = SYN.SYN_OUTPUT_DIRECTORY
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Write file
    filepath = GET_PARSER_STATE_CACHE_FILEPATH(c_filename)
    if not os.path.exists(os.path.dirname(filepath)):
        os.makedirs(os.path.dirname(filepath))
    with open(filepath, "wb") as output:
        pickle.dump(parser_state, output, pickle.HIGHEST_PROTOCOL)


def GET_PARSER_STATE_CACHE(c_filename):
    filepath = GET_PARSER_STATE_CACHE_FILEPATH(c_filename)
    if os.path.exists(filepath):
        # A cache written by an older compiler (renamed/moved classes) is just a miss
        try:
            with open(filepath, "rb") as input:
                parser_state = pickle.load(input)
                return parser_state
        except Exception:
            return None
    return None


# dict[func_name] = set(called_func_names)
# dict[func_name] = set(calling_func_names)
# func_name_to_calls, func_names_to_called_from =
def GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state):
    func_name_to_calls = {}
    func_names_to_called_from = {}
    # Do this by manually recursing through all nodes in each func def
    c_ast_func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
    for c_ast_func_def in c_ast_func_defs:
        func_name = c_ast_func_def.decl.name
        if type(func_name) is not str:
            raise Exception(
                "Bad func name?",
                str(c_ast_func_def.decl.name.coord),
                str(c_ast_func_def.decl.name),
            )
        # print "c_ast_func_def",c_ast_func_def.decl.name
        func_call_c_ast_nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
            c_ast_func_def, c_ast.FuncCall
        )
        # print "Called",len(func_call_c_ast_nodes)
        for func_call_c_ast_node in func_call_c_ast_nodes:
            called_func_name = func_call_c_ast_node.name.name
            if type(called_func_name) is not str:
                raise Exception(
                    "Bad func name?", str(called_func_name.coord), str(called_func_name)
                )
            # print " called_func_name",called_func_name
            # Record
            # Calls
            if func_name not in func_name_to_calls:
                func_name_to_calls[func_name] = set()
            func_name_to_calls[func_name].add(called_func_name)
            # Called from
            if called_func_name not in func_names_to_called_from:
                func_names_to_called_from[called_func_name] = set()
            func_names_to_called_from[called_func_name].add(func_name)
            # Also start entry for called func to call funcs?
            if called_func_name not in func_name_to_calls:
                func_name_to_calls[called_func_name] = set()

        # if func_name in func_name_to_calls:
        #  print "func_name",func_name,func_name_to_calls[func_name]
        #  print "SCOO"

    # print("func_name_to_calls",func_name_to_calls)

    # Reduce data down to funcs as used by main funcs (trying to avoid regular C code)
    main_func_name_to_calls = {}
    main_func_names_to_called_from = {}
    submodule_func_names = set(parser_state.main_mhz.keys())
    # Ahh hackey hack help
    # ~~~Nobody Speak - Run The Jewels
    # Also include FSM funcs as always included
    # and operator overload funcs that wont look like func call
    for func_name in func_name_to_calls:
        if func_name + FSM_EXT in func_name_to_calls:
            submodule_func_names.add(func_name)
            submodule_func_names.add(func_name + FSM_EXT)
        if LOGIC.FUNC_IS_OP_OVERLOAD(func_name):
            submodule_func_names.add(func_name)
    # print("submodule_func_names",submodule_func_names)
    while len(submodule_func_names) > 0:
        next_submodule_func_names = set()

        # Every func in level
        for func_name in submodule_func_names:
            if func_name in func_name_to_calls:
                called_func_names = func_name_to_calls[func_name]

                # Calls
                if func_name not in main_func_name_to_calls:
                    main_func_name_to_calls[func_name] = set()
                main_func_name_to_calls[func_name].update(called_func_names)
                # Called from
                for called_func_name in called_func_names:
                    if called_func_name not in main_func_names_to_called_from:
                        main_func_names_to_called_from[called_func_name] = set()
                    main_func_names_to_called_from[called_func_name].add(func_name)

                next_submodule_func_names.update(called_func_names)

        # Next level of 'recursion' into submodules
        submodule_func_names = set(next_submodule_func_names)

    # print("main_func_name_to_calls",main_func_name_to_calls)
    # print("main_func_names_to_called_from",main_func_names_to_called_from)
    return main_func_name_to_calls, main_func_names_to_called_from


def C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(c_ast_node, nodes=None):
    if nodes is None:
        nodes = []
    if type(c_ast_node) == c_ast.ID:
        nodes.append(c_ast_node)

    # Certain compound nodes contain C AST identifiers that are not variables
    # Ex. struct use, my_struct.my_var shows up as
    # an individual c_ast.ID node for 'my_var'
    # when thats not the same as using 'my_var' as an actual variable
    # Only need node for the .name variable name not the .field struct field
    if type(c_ast_node) == c_ast.StructRef:
        nodes = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(c_ast_node.name, nodes)
        return nodes

    # Normal case look at all children of node
    children_tuples = c_ast_node.children()
    for children_tuple in children_tuples:
        child_name = children_tuple[0]
        child_node = children_tuple[1]
        nodes = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(child_node, nodes)

    return nodes


def C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast_type, nodes=None):
    if nodes is None:
        nodes = []
        if c_ast_type == c_ast.ID:
            raise Exception(
                "Use C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS to find variable identifiers..."
            )
    if type(c_ast_node) == c_ast_type:
        nodes.append(c_ast_node)
    children_tuples = c_ast_node.children()
    for children_tuple in children_tuples:
        child_node = children_tuple[1]
        nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(child_node, c_ast_type, nodes)
    return nodes


# Returns ParserState
# TODO make as ParserState then
def PARSE_FILE(c_filename):
    # Do we have a cached parser state?
    cached_parser_state = GET_PARSER_STATE_CACHE(c_filename)
    filepath = GET_PARSER_STATE_CACHE_FILEPATH(c_filename)
    if cached_parser_state is not None:
        print("Already parsed C code for", c_filename, ", using cache", filepath, "...")
        return cached_parser_state

    # Otherwise do for real
    parser_state = LOGIC.ParserState()

    # Catch pycparser exceptions
    try:
        # Need to do complex code generation
        # Keep track of which files need to be (re)generated
        regenerate_files = set()
        # Start off with any missing headers
        all_code_files = get_included_files(c_filename)
        # print("all_code_files",all_code_files)
        for f in all_code_files:
            if not os.path.exists(f):
                regenerate_files.add(f)

        # Generate the needed files during this single while loop iteration pass
        # Might need to restart loop if more files needed to be generated as files are generated
        while True:
            new_regenerate_files = set()
            # Start code generating,
            # If any of the files are completely missing gen empty headers
            # in order to get through preprocessing
            if len(regenerate_files) > 0:
                inital_missing_files = []
                for f in regenerate_files:
                    if not os.path.exists(f) and not os.path.exists(
                        SYN.SYN_OUTPUT_DIRECTORY + "/" + f
                    ):
                        inital_missing_files.append(f)
                if len(inital_missing_files) > 0:
                    print(
                        "Generating code to get through first round of preprocessing...",
                        flush=True,
                    )
                    print("Trying to generate: ", inital_missing_files, flush=True)
                    # Code generate empty to-be-generated header files
                    # so initial preprocessing can happen
                    # Then do repeated re-parsing as code gen continues
                    new_regenerate_files |= GEN_EMPTY_GENERATED_HEADERS(
                        all_code_files, inital_missing_files, parser_state
                    )
                    if (new_regenerate_files | regenerate_files) != regenerate_files:
                        print("Re/generating: ", new_regenerate_files, flush=True)
                        # Restart pass on new files and current pass files
                        regenerate_files = new_regenerate_files | regenerate_files
                        continue

            # Preprocess the file and generate more code maybe?
            # Generation return list of files that need continued generation
            # Preprocess the main file to get single block of text
            if len(regenerate_files) > 0:
                print(
                    "Generating code based on PipelineC supported C text patterns...",
                    flush=True,
                )
                preprocessed_c_text = preprocess_file(c_filename)
                # Code gen based purely on preprocessed C text
                new_regenerate_files |= WRITE_POST_PREPROCESS_GEN_CODE(
                    preprocessed_c_text, regenerate_files, parser_state
                )
                if (new_regenerate_files | regenerate_files) != regenerate_files:
                    print("Re/generating: ", new_regenerate_files, flush=True)
                    # Restart pass on new files and current pass files
                    regenerate_files = new_regenerate_files | regenerate_files
                    continue

            # Preprocess again and parse the file
            # Collect info on non func defs (fsm derived bodies arent really 'parsed')
            print("Preprocessing file...", flush=True)
            # Preprocess the main file to get single block of text
            preprocessed_c_text = preprocess_file(c_filename)
            # print("preprocessed_c_text",preprocessed_c_text)
            print("Parsing C syntax...", flush=True)
            # Get the C AST
            parser_state.c_file_ast = GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(
                preprocessed_c_text, c_filename
            )
            # print(parser_state.c_file_ast)
            print("Parsing non-function definitions...", flush=True)
            # Parse definitions first before code structure
            # Warn about typedefs not being resolved
            # Used too often to warn about? parser_state = WARN_NO_RENAMING_TYPEDEFS(parser_state.c_file_ast, parser_state)
            # Parse pragmas
            parse_state = APPEND_PRAGMA_INFO(parser_state)
            # Get the parsed enum info
            parser_state.enum_info_dict = GET_ENUM_INFO_DICT(
                parser_state.c_file_ast, parser_state
            )
            # Get the parsed struct def info
            parser_state = APPEND_STRUCT_FIELD_TYPE_DICT(
                parser_state.c_file_ast, parser_state
            )
            # print("struct_to_field_type_dict",parser_state.struct_to_field_type_dict)
            # Build primative map of function use
            (
                parser_state.func_name_to_calls,
                parser_state.func_names_to_called_from,
            ) = GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state)
            # Get local state reg info (is needed to interpret global variable names appearing in functions)
            parser_state = GET_LOCAL_VAR_INFO(parser_state)
            # Get globally defined consts
            parser_state = GET_GLOBAL_CONST_INFO(parser_state)
            # Get global var name (global regs, volatile globals) info
            parser_state = GET_GLOBAL_VAR_INFO(parser_state)
            # Elborate what the clock crossings look like
            parser_state = GET_CLK_CROSSING_INFO(preprocessed_c_text, parser_state)
            parser_state = DERIVE_ARB_CLK_CROSSING_INFO(
                preprocessed_c_text, parser_state
            )
            # Get FSM clock func logics only - dont really parse their function body in details,
            # different and needs to be before regular func parsing below
            print("Parsing derived fsm logic functions...", flush=True)
            parser_state = GET_FSM_CLK_FUNC_LOGICS(parser_state)
            # Done doing code gen?
            if len(regenerate_files) == 0:
                break

            # Generate code needed to later parse function body code, only have non func defs
            # Do code gen based on preprocessed C text and non-function definitions
            # This is the newer better way
            if len(regenerate_files) > 0:
                print(
                    "Generating code based on PipelineC supported C design patterns...",
                    flush=True,
                )
                new_regenerate_files |= (
                    WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE(
                        preprocessed_c_text, parser_state, regenerate_files
                    )
                )
                if (new_regenerate_files | regenerate_files) != regenerate_files:
                    print("Re/generating: ", new_regenerate_files, flush=True)
                    # Restart pass on new files and current pass files
                    regenerate_files = new_regenerate_files | regenerate_files
                    continue

            # Done generating this set of files
            if regenerate_files == new_regenerate_files:
                break
            # Must be done code gen if got here if got here
            # Just set empty and not break since need to reparse non func defs one last time
            regenerate_files = new_regenerate_files  # set()

        # All code gen has been done that used nested generation,
        # old style 'base level' code gen and rest of parsing below
        print(
            "Doing old-style code generation based on PipelineC supported text patterns...",
            flush=True,
        )
        # Preprocess the file again to pull in generated code
        preprocessed_c_text = preprocess_file(c_filename)
        # Get the C AST again to reflect new generated code
        parser_state.c_file_ast = GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(
            preprocessed_c_text, c_filename
        )
        # Update primative map of function use
        (
            parser_state.func_name_to_calls,
            parser_state.func_names_to_called_from,
        ) = GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state)
        # This is the old more hacky way
        # Get SW existing logic for this c file
        sw_func_name_2_logic = (
            GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(
                preprocessed_c_text, parser_state
            )
        )
        # Merge into existing
        for sw_func_name in sw_func_name_2_logic:
            if sw_func_name not in parser_state.FuncLogicLookupTable:
                parser_state.FuncLogicLookupTable[sw_func_name] = sw_func_name_2_logic[
                    sw_func_name
                ]

        # Parse the function definitions for code structure
        print("Elaborating function dataflow...", flush=True)
        parser_state.FuncLogicLookupTable = APPEND_FUNC_NAME_LOGIC_LOOKUP_TABLE(
            parser_state
        )
        # Sanity check main funcs are there + legal
        for main_func in list(parser_state.main_mhz.keys()):
            if main_func not in parser_state.FuncLogicLookupTable:
                print("Main function:", main_func, "does not exist?")
                sys.exit(-1)
            main_func_logic = parser_state.FuncLogicLookupTable[main_func]
            if main_func_logic.is_fsm_clk_func:
                raise Exception(
                    f"Cannot have main function '{main_func}' that uses/calls functions that use __clk()."
                )

        # Need to add array struct for old internal C code parsing?
        parser_state = APPEND_ARRAY_STRUCT_INFO(parser_state)

        # Check for double write of globals+volatiles
        for the_global_var, the_global_var_info in parser_state.global_vars.items():
            # Skips array instance wires that can be multi driven
            if the_global_var in parser_state.inst_array_dict.values():
                continue
            if the_global_var in parser_state.inst_array_dict.keys():
                continue
            for func_name1 in the_global_var_info.used_in_funcs:
                func1_logic = parser_state.FuncLogicLookupTable[func_name1]
                for func_name2 in the_global_var_info.used_in_funcs:
                    if func_name2 == func_name1:
                        continue
                    func2_logic = parser_state.FuncLogicLookupTable[func_name2]
                    # Check those vars arent written in other funcs
                    if (
                        the_global_var_info in func1_logic.state_regs.values()
                        or the_global_var_info
                        in func1_logic.write_only_global_wires.values()
                    ) and (
                        the_global_var_info in func2_logic.state_regs.values()
                        or the_global_var_info
                        in func2_logic.write_only_global_wires.values()
                    ):
                        raise Exception(
                            f"ERROR: Cannot write to global variable in more than one function!: {the_global_var} written to in both {func_name1} and {func_name2}"
                        )

        # Elaborate the logic down to raw vhdl modules
        print(
            "Elaborating user function hierarchies down to raw HDL logic...", flush=True
        )
        for main_func in list(parser_state.main_mhz.keys()):
            adjusted_containing_logic_inst_name = ""
            main_func_logic = parser_state.FuncLogicLookupTable[main_func]
            c_ast_node_when_used = parser_state.FuncLogicLookupTable[
                main_func
            ].c_ast_node
            parser_state = RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(
                main_func,
                main_func,
                parser_state,
                adjusted_containing_logic_inst_name,
                c_ast_node_when_used,
            )

        # Remove excess user code
        if LOGIC.TRIM_COLLAPSE_LOGIC:
            print("Doing obvious logic trimming/collapsing...", flush=True)
            for main_func in list(parser_state.main_mhz.keys()):
                main_func_logic = parser_state.FuncLogicLookupTable[main_func]
                parser_state = LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(
                    main_func_logic, parser_state
                )

        # Code gen based on fully elaborated logic
        # Write c code
        print(
            "Writing generated PipelineC code from elaboration to output directories...",
            flush=True,
        )
        for func_name in parser_state.FuncLogicLookupTable:
            func_logic = parser_state.FuncLogicLookupTable[func_name]
            if func_logic.c_code_text is not None:
                # Fake name
                fake_filename = func_name + ".c"
                out_dir = SYN.GET_OUTPUT_DIRECTORY(func_logic)
                outpath = out_dir + "/" + fake_filename
                if not os.path.exists(out_dir):
                    os.makedirs(out_dir)
                f = open(outpath, "w")
                f.write(func_logic.c_code_text)
                f.close()

        # Write cache
        print("Writing cache of parsed information to file...", flush=True)
        WRITE_PARSER_STATE_CACHE(parser_state, c_filename)

        # Clear in memory caches
        DEL_ALL_CACHES()
        SYN.DEL_ALL_CACHES()

        return parser_state

    except c_parser.ParseError as pe:
        print("PARSE_FILE pycparser says you messed up here:", pe)
        sys.exit(-1)


def GET_GLOBAL_VAR_INFO(parser_state):
    # Read in file with C parser to get global def nodes
    parser_state.global_vars = {}
    global_decls = GET_C_AST_GLOBAL_DECLS(parser_state.c_file_ast)
    for global_decl in global_decls:
        name_str = str(global_decl.name)
        # Skip consts, arent regs
        if ("const" in global_decl.quals) or (name_str in parser_state.global_consts):
            continue
        # Skip function prototypes
        if type(global_decl.type) == c_ast.FuncDecl:
            continue
        var_info = LOGIC.VariableInfo()
        var_info.name = name_str
        c_type, var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(global_decl, parser_state)
        if c_type:  # Pointer decls ignored could be none
            var_info.type_name = c_type
            var_info.init = global_decl.init
            var_info.resolved_const_str = RESOLVE_C_AST_NODE_TO_CONSTANT_STR(
                global_decl.init, "", parser_state
            )

            # Save flags
            if "volatile" in global_decl.quals:
                var_info.is_volatile = True

            # Save info
            parser_state.global_vars[var_info.name] = var_info

    # Update with where globals are used
    # Hacky pre-parsing func body logic, determine what funcs contain use of the global
    c_ast_func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
    for c_ast_func_def in c_ast_func_defs:
        func_name = c_ast_func_def.decl.name
        if not SKIP_PARSING_FUNC(func_name, parser_state):
            ids_in_func = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(c_ast_func_def)
            for id_node in ids_in_func:
                var_name = id_node.name
                # If name is from global names, and not from local then record global being used
                if var_name in parser_state.global_vars and (
                    func_name not in parser_state.func_to_local_variables
                    or var_name not in parser_state.func_to_local_variables[func_name]
                ):
                    parser_state.global_vars[var_name].used_in_funcs.add(func_name)

    # Even hackier fix to remove what looks like FSM generated code duplicate driving things
    # but really is just generated copy
    for var_name, var_info in parser_state.global_vars.items():
        for func_name in set(var_info.used_in_funcs):
            if func_name + FSM_EXT in var_info.used_in_funcs:
                var_info.used_in_funcs.remove(func_name)

    return parser_state


def GET_LOCAL_VAR_INFO(parser_state):
    parser_state.func_to_local_variables = {}
    parser_state.func_to_local_state_regs = {}

    # Get all the func defs
    # And look for declarations in the func BODY
    # INCLUDES INPUT PARAMs AND LOCALs
    c_ast_func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
    for c_ast_func_def in c_ast_func_defs:
        func_name = c_ast_func_def.decl.name
        local_decl_c_ast_nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
            c_ast_func_def.body, c_ast.Decl
        )
        param_decl_c_ast_nodes = []
        if c_ast_func_def.decl.type.args is not None:
            param_decl_c_ast_nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
                c_ast_func_def.decl.type.args, c_ast.Decl
            )
        decl_c_ast_nodes = local_decl_c_ast_nodes + param_decl_c_ast_nodes
        # All funcs recorded as exists with no locals to start
        # This misses built in funcs and bit math, mem.h etc
        if func_name not in parser_state.func_to_local_variables:
            parser_state.func_to_local_variables[func_name] = set()
        for decl_c_ast_node in decl_c_ast_nodes:
            c_type, var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(
                decl_c_ast_node, parser_state
            )
            # Record all declared vars
            parser_state.func_to_local_variables[func_name].add(var_name)
            # Record static state registers
            if "static" not in decl_c_ast_node.storage:
                continue
            var_info = LOGIC.VariableInfo()
            var_info.name = var_name
            var_info.type_name = c_type
            var_info.init = decl_c_ast_node.init
            # Resolved when evaluating containing func
            # var_info.resolved_const_str = RESOLVE_C_AST_NODE_TO_CONSTANT_STR(decl_c_ast_node.init, "", parser_state)
            # Save flags
            if "volatile" in decl_c_ast_node.quals:
                var_info.is_volatile = True
            # Save info
            if func_name not in parser_state.func_to_local_state_regs:
                parser_state.func_to_local_state_regs[func_name] = {}
            parser_state.func_to_local_state_regs[func_name][var_info.name] = var_info

    return parser_state


class GlobalConstInfo:
    def __init__(self):
        self.name = None
        self.type_name = None
        self.lhs = None
        self.init = None


def GET_GLOBAL_CONST_INFO(parser_state):
    # Collect all global defs marked const
    parser_state.global_consts = {}
    global_decls = GET_C_AST_GLOBAL_DECLS(parser_state.c_file_ast)
    non_const_decls = {}
    for global_decl in global_decls:
        name_str = str(global_decl.name)
        if "const" not in global_decl.quals:
            non_const_decls[name_str] = global_decl
            continue
        # Marked const
        info = GlobalConstInfo()
        info.name = name_str
        c_type, var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(global_decl, parser_state)
        info.type_name = c_type
        # print(global_decl)
        info.init = global_decl.init
        info.lhs = global_decl
        # Save info
        parser_state.global_consts[info.name] = info

    # non_const_decls are checked for const via usage next
    # Dont find and lhs assigns, and do find rhs use
    # unused at all globals might be clcok cross bram stuff weird
    vars_w_no_write = set(non_const_decls.keys())
    c_ast_assignments = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
        parser_state.c_file_ast, c_ast.Assignment
    )
    for c_ast_assignment in c_ast_assignments:
        lhs_node = c_ast_assignment.lvalue
        ids_assigned = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(lhs_node)
        for id_assigned in ids_assigned:
            var_name = id_assigned.name
            if var_name in vars_w_no_write:
                vars_w_no_write.remove(var_name)
    vars_w_some_use = set()
    all_ids = C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(parser_state.c_file_ast)
    for id_node in all_ids:
        var_name = id_node.name
        vars_w_some_use.add(var_name)

    # Promote non const decls to const as found
    for global_decl in non_const_decls.values():
        name_str = str(global_decl.name)
        # Skips array instance wires that appear undriven
        if name_str in parser_state.inst_array_dict.values():
            continue
        if name_str in parser_state.inst_array_dict.keys():
            continue
        if name_str in parser_state.input_wires:
            continue
        if (name_str in vars_w_no_write) and (name_str in vars_w_some_use):
            print(
                f"Marking global variable {name_str} as constant since never written..."
            )
            # Promoted const
            info = GlobalConstInfo()
            info.name = name_str
            c_type, var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(
                global_decl, parser_state
            )
            info.type_name = c_type
            # print(global_decl)
            info.init = global_decl.init
            info.lhs = global_decl
            # Save info
            parser_state.global_consts[info.name] = info

    return parser_state


# Fuck me add struct info for array wrapper
def APPEND_ARRAY_STRUCT_INFO(parser_state):
    # Loop over all C types and find the array structs
    for func_name in parser_state.FuncLogicLookupTable:
        func_logic = parser_state.FuncLogicLookupTable[func_name]
        for wire in func_logic.wire_to_c_type:
            c_type = func_logic.wire_to_c_type[wire]
            if LOGIC.C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state):
                c_array_type = LOGIC.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(
                    c_type, parser_state
                )
                elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
                data_array_type = elem_t
                for dim in dims:
                    data_array_type += "[" + str(dim) + "]"

                # Append to dict
                field_type_dict = {}
                field_type_dict["data"] = data_array_type
                parser_state.struct_to_field_type_dict[c_type] = field_type_dict

    return parser_state


def GET_CLK_CROSSING_INFO(preprocessed_c_text, parser_state):
    # Regex search c_text for pair of write and read funcs
    write_func_calls = []
    r = rf"\w+" + "_WRITE" + rf"\s?\("
    write_func_calls += FIND_REGEX_MATCHES(r, preprocessed_c_text)
    r = rf"\w+" + "_WRITE_[0-9]+" + rf"\s?\("
    write_func_calls += FIND_REGEX_MATCHES(r, preprocessed_c_text)
    write_func_names = []
    for write_func_call in write_func_calls:
        write_func_names.append(write_func_call.strip("(").strip())
    read_func_calls = []
    r = rf"\w+" + "_READ" + rf"\s?\("
    read_func_calls += FIND_REGEX_MATCHES(r, preprocessed_c_text)
    r = rf"\w+" + "_READ_[0-9]+" + rf"\s?\("
    read_func_calls += FIND_REGEX_MATCHES(r, preprocessed_c_text)
    read_func_names = []
    for read_func_call in read_func_calls:
        read_func_names.append(read_func_call.strip("(").strip())

    # Find pairs that are global or volatile global vars
    var_to_read_func = {}
    var_to_write_func = {}
    all_var_names = set()
    for func_name in write_func_names + read_func_names:
        if "_WRITE" in func_name:
            var_name = LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(func_name)
            all_var_names.add(var_name)
            var_to_write_func[var_name] = func_name
        if "_READ" in func_name:
            var_name = LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(func_name)
            all_var_names.add(var_name)
            var_to_read_func[var_name] = func_name
    var_names = []
    for var_name in all_var_names:
        if var_name in parser_state.global_vars:
            # if var_name not in var_to_write_func:
            #  print("WARNING: Missing clock cross write function for clock crossing named:",var_name)
            #  #sys.exit(-1)
            # Make up a read func if needed (unconnected output)
            if var_name not in var_to_read_func:
                var_to_read_func[var_name] = var_to_write_func[var_name].replace(
                    "_WRITE", "_READ"
                )
            var_names.append(var_name)

    # Find and read and write main funcs
    # print("var_names",var_names)
    # print("var_to_read_func",var_to_read_func)
    # print("var_to_write_func",var_to_write_func)
    var_to_rw_main_funcs = {}  # ([read,mains],[write,mains])
    for var_name in var_names:
        var_to_rw_main_funcs[var_name] = (set(), set())
        read_func_name = None
        if var_name in var_to_read_func:
            read_func_name = var_to_read_func[var_name]
        write_func_name = None
        if var_name in var_to_write_func:
            write_func_name = var_to_write_func[var_name]
        read_containing_funcs = set()
        write_containing_funcs = set()
        read_main_funcs = set()
        write_main_funcs = set()
        # Search for what container funcs call this read and write funcs
        for func_name in parser_state.func_name_to_calls:
            # Skip looking inside funcitons that have a _FSM copy
            fsm_dup_func = func_name + FSM_EXT
            if (
                func_name != fsm_dup_func
                and fsm_dup_func in parser_state.func_name_to_calls
            ):
                continue
            called_funcs = parser_state.func_name_to_calls[func_name]
            # Read
            if read_func_name in called_funcs:
                read_containing_funcs.add(func_name)
                read_main_funcs |= LOGIC.RECURSIVE_FIND_MAIN_FUNCS(
                    func_name,
                    parser_state.func_name_to_calls,
                    parser_state.func_names_to_called_from,
                    list(parser_state.main_mhz.keys()),
                )

            # Write
            if write_func_name in called_funcs:
                write_containing_funcs.add(func_name)
                write_main_funcs |= LOGIC.RECURSIVE_FIND_MAIN_FUNCS(
                    func_name,
                    parser_state.func_name_to_calls,
                    parser_state.func_names_to_called_from,
                    list(parser_state.main_mhz.keys()),
                )

        # Final check per clock cross var
        # if len(write_main_funcs) == 0:
        #  print("WARNING: Problem finding write side main functions for",var_name)
        #  #print("Missing or incorrect #pragma MAIN_MHZ ?")
        #  #sys.exit(-1)
        var_to_rw_main_funcs[var_name] = (read_main_funcs, write_main_funcs)

    var_to_rw_mhz_groups = LOGIC.INFER_CLOCK_DOMAINS(
        var_to_rw_main_funcs, var_to_read_func, var_to_write_func, parser_state
    )

    # Then loop to construct each clock crossings info
    # print("Clocks done: parser_state.main_mhz",parser_state.main_mhz)
    for var_name in var_names:
        # Skip temp during code gen disconnected write side
        if var_name not in var_to_rw_mhz_groups:
            continue
        ((read_mhz, read_group), (write_mhz, write_group)) = var_to_rw_mhz_groups[
            var_name
        ]
        read_main_funcs, write_main_funcs = var_to_rw_main_funcs[var_name]
        # Match mhz for disconnected read side - needed here?
        if write_mhz is not None and read_mhz is None:
            # print("WARNING: Clock crossing {var_name} appears to be never read!")
            read_mhz = write_mhz
        # Sanity check
        # if read_mhz is None and write_mhz is None:
        #  print("WARNING: No clock frequencies asssociated with each side of the clock crossing for",var_name,"clock crossing: read, write:", read_main_funcs,",",write_main_funcs)
        #  #print("Missing or incorrect #pragma MAIN_MHZ ?")
        #  #sys.exit(-1)

        # Info to record
        flow_control = False
        read_func_name = var_to_read_func[var_name]
        write_func_name = var_to_write_func[var_name]

        # Async wires yreat like a same clock domain wire
        if var_name in parser_state.async_wires:
            ratio = 1
            write_size = 1
            read_size = 1
        # Async fifo with flow control uses sized READ and WRITE
        elif not read_func_name.endswith("_READ") or not write_func_name.endswith(
            "_WRITE"
        ):
            # Async sized read and write
            read_size = int(read_func_name.split("_READ_")[1])
            write_size = int(write_func_name.split("_WRITE_")[1])
            flow_control = True
        else:
            # Sync or async not user sized read and write
            ratio = 1
            write_size = 1
            read_size = 1
            if write_mhz is None or read_mhz is None:
                # Ugh?
                pass
            elif write_mhz > read_mhz:
                # Write side is faster
                ratio = int(math.ceil(write_mhz / read_mhz))
                write_size = 1
                read_size = ratio
            else:
                # Read side is faster
                ratio = int(math.ceil(read_mhz / write_mhz))
                read_size = 1
                write_size = ratio

            # Check that non volatile crosses are identical freq+group (same clock)
            if (
                var_name in parser_state.global_vars
                and not parser_state.global_vars[var_name].is_volatile
            ):
                if ratio != 1.0 or read_group != write_group:
                    print(
                        "Non-volatile clock crossing",
                        var_name,
                        "is used like volatile clock crossing from different clocks",
                        write_func_name,
                        write_main_func,
                        "@",
                        write_mhz,
                        "MHz",
                        write_group,
                        "->",
                        read_func_name,
                        read_main_func,
                        "@",
                        read_mhz,
                        "MHz",
                        read_group,
                    )
                    # sys.exit(-1)

            # Check that volatile crossings are integer ratios and sanme clock group
            clk_ratio = None
            if write_mhz is None or read_mhz is None:
                # Ugh?
                pass
            elif write_mhz >= read_mhz:
                clk_ratio = write_mhz / read_mhz
            else:
                clk_ratio = read_mhz / write_mhz
            if (
                clk_ratio is not None and int(clk_ratio) != clk_ratio
            ) or read_group != write_group:
                print(
                    "TODO: Volatile non integer ratio clock crossings like:",
                    write_func_name,
                    write_main_func,
                    write_group,
                    write_mhz,
                    "MHz",
                    "->",
                    read_func_name,
                    read_main_func,
                    read_group,
                    read_mhz,
                    "MHz",
                )
                # sys.exit(-1)

        # Record
        parser_state.clk_cross_var_info[var_name] = LOGIC.ClkCrossVarInfo()
        parser_state.clk_cross_var_info[var_name].flow_control = flow_control
        parser_state.clk_cross_var_info[var_name].write_read_funcs = (
            write_func_name,
            read_func_name,
        )
        parser_state.clk_cross_var_info[var_name].write_read_main_funcs = (
            write_main_funcs,
            read_main_funcs,
        )
        parser_state.clk_cross_var_info[var_name].write_read_sizes = (
            write_size,
            read_size,
        )

    return parser_state


# return parser state with updated info
def DERIVE_ARB_CLK_CROSSING_INFO(preprocessed_c_text, parser_state):
    parser_state.arb_handshake_infos = set()

    for i_var, o_var in parser_state.io_pairs:
        if (
            i_var in parser_state.clk_cross_var_info
            and o_var in parser_state.clk_cross_var_info
        ):
            arb_handshake_info = LOGIC.ArbHandshakeInfo()
            arb_handshake_info.input_var_name = i_var
            arb_handshake_info.output_var_name = o_var
            arb_handshake_info.input_clk_cross_var_info = (
                parser_state.clk_cross_var_info[arb_handshake_info.input_var_name]
            )
            arb_handshake_info.input_clk_cross_var_info.is_part_of_arb_handshake = True
            arb_handshake_info.output_clk_cross_var_info = (
                parser_state.clk_cross_var_info[arb_handshake_info.output_var_name]
            )
            arb_handshake_info.output_clk_cross_var_info.is_part_of_arb_handshake = True

            parser_state.arb_handshake_infos.add(arb_handshake_info)

    return parser_state


_printed_GET_ENUM_INFO_DICT = False


def GET_ENUM_INFO_DICT(c_file_ast, parser_state):
    # Read in file with C parser and get function def nodes
    rv = {}
    enum_defs = GET_C_AST_ENUM_DEFS(c_file_ast)
    for enum_def in enum_defs:
        if enum_def.name is None:
            global _printed_GET_ENUM_INFO_DICT
            if not _printed_GET_ENUM_INFO_DICT:
                print(
                    "WARNING: Must use enum_name and enum_alias in enum definitions... for now... Ex."
                )
                print(
                    """typedef enum enum_name {
  STATE0,
  STATE1
} enum_alias;"""
                )
                _printed_GET_ENUM_INFO_DICT = True
            continue

        # sys.exit(-1)

        enum_name = str(enum_def.name)
        # print "struct_name",struct_name
        rv[enum_name] = LOGIC.EnumInfo()
        rv[enum_name].name = enum_name
        is_one_hot = enum_name in parser_state.marked_onehot
        # print(enum_name)
        # print(is_one_hot)
        # casthelp(enum_def.values)
        # sys.exit(-1)
        maybe_enum_index_or_val = 0  # dont mix one hot with specified values

        def index_to_val(index, one_hot):
            if not one_hot:
                return index
            else:
                return 1 << index

        # Calculate max width and if signed
        max_width = 0
        signed = False
        for child in enum_def.values.enumerators:
            # ID
            id_str = str(child.name)

            # Get int value
            if child.value is None:
                # Find next unused value
                val = index_to_val(maybe_enum_index_or_val, is_one_hot)
                while val in rv[enum_name].id_to_int_val.values():
                    maybe_enum_index_or_val += 1
                    val = index_to_val(maybe_enum_index_or_val, is_one_hot)
                c_type = "uint" + str(val.bit_length()) + "_t"
                next_index_or_val = maybe_enum_index_or_val + 1
            else:
                if (
                    type(child.value) is not c_ast.Constant
                ):  # Negated values are unary operators
                    print(
                        "Only unsigned constants for enum values for now!",
                        child.value.coord,
                    )
                    sys.exit(-1)
                is_negated = False
                val_str = str(child.value.value)
                val, unused_c_type = NON_ENUM_CONST_VALUE_STR_TO_VALUE_AND_C_TYPE(
                    val_str, child.value.value, is_negated
                )
                next_index_or_val = val + 1
            rv[enum_name].id_to_int_val[id_str] = val
            # print(id_str, val)

            # Accum max width and sign
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
            max_width = max(max_width, width)
            signed |= LOGIC.C_TYPE_IS_INT_N(c_type)

            # Next value
            maybe_enum_index_or_val = next_index_or_val

        # C type for this enum comes from max width
        rv[enum_name].int_c_type = "int" + str(max_width) + "_t"
        if not signed:
            rv[enum_name].int_c_type = "u" + rv[enum_name].int_c_type
        # print(rv[enum_name].int_c_type)
        # print("=")

        # Sanity checks
        if len(rv[enum_name].id_to_int_val.keys()) != len(
            set(rv[enum_name].id_to_int_val.keys())
        ):
            print("Duplicate identifiers in enum", enum_name)
            sys.exit(-1)
        if len(rv[enum_name].id_to_int_val.values()) != len(
            set(rv[enum_name].id_to_int_val.values())
        ):
            print("Duplicate values in enum", enum_name)
            sys.exit(-1)

    return rv


"""
_printed_NO_RENAMING_TYPEDEFS = False
def WARN_NO_RENAMING_TYPEDEFS(c_file_ast, parser_state):
  # Read in file with C parser and get function def nodes
  type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
  for type_def in type_defs:
    #casthelp(type_def)
    thing = type_def.children()[0][1].children()[0][1]
    if type(thing) == c_ast.Struct:
      continue
    elif type(thing) == c_ast.Enum:
      continue
    global _printed_NO_RENAMING_TYPEDEFS
    if not _printed_NO_RENAMING_TYPEDEFS:
      print("WARNING: Simple renaming of types with typedefs is not supported! Use #define new_t old_t for now.")
      _printed_NO_RENAMING_TYPEDEFS = True
    print("WARNING: Skipped typedef that renames types:", type_def.coord)
    continue
"""

_printed_GET_STRUCT_FIELD_TYPE_DICT = False


def APPEND_STRUCT_FIELD_TYPE_DICT(c_file_ast, parser_state):
    # Read in file with C parser and get function def nodes
    struct_defs = GET_C_AST_STRUCT_DEFS(c_file_ast)
    for struct_def in struct_defs:
        if struct_def.name is None:
            global _printed_GET_STRUCT_FIELD_TYPE_DICT
            if not _printed_GET_STRUCT_FIELD_TYPE_DICT:
                print(
                    "WARNING: Must use tag_name and struct_alias in struct definitions... for now... Ex."
                )
                print(
                    """typedef struct tag_name {
  type member1;
  type member2;
} struct_alias;"""
                )
                _printed_GET_STRUCT_FIELD_TYPE_DICT = True
            print("WARNING: Skipped struct def without alias:", struct_def.coord)
            continue

        struct_name = str(struct_def.name)
        new_field_type_dict = OrderedDict()
        for child in struct_def.decls:
            # Assume type decl
            field_name = str(child.name)
            if type(child.type) is c_ast.ArrayDecl:
                field_name, base_type, dim = C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(
                    child.type, parser_state
                )
                type_name = base_type + "[" + str(dim) + "]"
            else:
                # Non array
                type_name = str(child.children()[0][1].children()[0][1].names[0])
            new_field_type_dict[field_name] = type_name
        if (struct_name in parser_state.struct_to_field_type_dict) and (
            parser_state.struct_to_field_type_dict[struct_name] != new_field_type_dict
        ):
            raise Exception(
                f"Duplicate mismatching {struct_name} struct definiton!",
                struct_def.coord,
            )
        parser_state.struct_to_field_type_dict[struct_name] = new_field_type_dict

    return parser_state


def BUILD_PRIMITIVE_FUNC_LOGIC(
    func_name, containing_logic_inst_name, local_inst_name, parser_state
):
    # Need to have 'from code' defintion of macro func too for now
    if func_name not in parser_state.FuncLogicLookupTable:
        print("Primitive", func_name, "needs function defintion!")
        sys.exit(-1)
    orig_func_logic = parser_state.FuncLogicLookupTable[func_name]

    # Only copy io, black box otherwise
    func_logic = LOGIC.Logic()
    func_logic.func_name = orig_func_logic.func_name
    func_logic.inputs = orig_func_logic.inputs[:]
    func_logic.outputs = orig_func_logic.outputs[:]
    func_logic.ast_meta = orig_func_logic.ast_meta
    for wire in func_logic.inputs + func_logic.outputs:
        func_logic.wire_to_c_type[wire] = orig_func_logic.wire_to_c_type[wire]

    return func_logic


def GET_FSM_CLK_FUNC_LOGICS(parser_state):
    func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
    for func_def in func_defs:
        if SKIP_PARSING_FUNC(func_def.decl.name, parser_state):
            # print("Function skipped:", func_def.decl.name)
            continue
        parser_state.existing_logic = None
        driven_wire_names = []
        prepend_text = ""
        parse_body = True
        only_fsm_clk_funcs = True
        logic = C_AST_FUNC_DEF_TO_LOGIC(
            func_def, parser_state, parse_body, only_fsm_clk_funcs
        )
        if logic is not None:
            # print("Parsed FSM style function:", logic.func_name, flush=True)
            parser_state.FuncLogicLookupTable[logic.func_name] = logic
            # print(logic.c_ast_node)
        else:
            # print("Non FSM Function:",func_def.decl.name, flush=True)
            pass

    return parser_state


def SKIP_PARSING_FUNC(func_name, parser_state):
    return (
        (func_name not in parser_state.func_name_to_calls)
        and (func_name not in parser_state.func_names_to_called_from)
        and (func_name not in parser_state.main_mhz)
    )


# This will likely be called multiple times when loading multiple C files
def APPEND_FUNC_NAME_LOGIC_LOOKUP_TABLE(parser_state, parse_body=True):
    parse_func_body = parse_body
    # Each func def needs existing logic func name lookup
    # Read in file with C parser and get function def nodes
    func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
    for func_def in func_defs:
        # Silently skip fsm clk funcs
        if (
            func_def.decl.name in parser_state.FuncLogicLookupTable
            and parser_state.FuncLogicLookupTable[func_def.decl.name].is_fsm_clk_func
        ):
            continue
        # Warn about duplicate functions, if not overly false positive then make error
        if func_def.decl.name in parser_state.FuncLogicLookupTable:
            orig_func_def = parser_state.FuncLogicLookupTable[func_def.decl.name]
            if str(orig_func_def.c_ast_node.coord) != str(func_def.decl.coord):
                print(
                    "WARNING: Duplicate function definition found:",
                    func_def.decl.name,
                    "at:",
                    orig_func_def.c_ast_node.coord,
                    "and again at:",
                    func_def.decl.coord,
                    ". Using second definition.",
                )
        # Special overload funcs
        if LOGIC.FUNC_IS_OP_OVERLOAD(func_def.decl.name):
            print(
                "Elaborating dataflow of operator overload function:",
                func_def.decl.name,
                flush=True,
            )
        # Skip functions that are not found in the initial from-main hierarchy mapping
        elif SKIP_PARSING_FUNC(func_def.decl.name, parser_state):
            # if func_def.decl.name not in parser_state.func_marked_wires:
            #    print("Function skipped:", func_def.decl.name)
            continue
        # Prims
        elif SYN.FUNC_IS_PRIMITIVE(func_def.decl.name, parser_state):
            print("Parsing primitive function:", func_def.decl.name, flush=True)
            parse_func_body = False
        # General user code
        else:
            if func_def.decl.name not in parser_state.func_marked_wires:
                print(
                    "Elaborating dataflow of function:", func_def.decl.name, flush=True
                )

        # Each func def produces a single logic item
        parser_state.existing_logic = None
        driven_wire_names = []
        prepend_text = ""
        logic = C_AST_FUNC_DEF_TO_LOGIC(
            func_def, parser_state, parse_body=parse_func_body
        )
        parser_state.FuncLogicLookupTable[logic.func_name] = logic
        # parser_state.FuncLogicLookupTable = FuncLogicLookupTable

    # Do dumb? loops to find containing func
    for func_logic in list(parser_state.FuncLogicLookupTable.values()):
        for submodule_inst in func_logic.submodule_instances:
            submodule_func_name = func_logic.submodule_instances[submodule_inst]
            if submodule_func_name in parser_state.FuncLogicLookupTable:
                parser_state.FuncLogicLookupTable[
                    submodule_func_name
                ].containing_funcs.add(func_logic.func_name)

    return parser_state.FuncLogicLookupTable


def RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(
    func_name,
    local_inst_name,
    parser_state,
    containing_logic_inst_name="",
    c_ast_node_when_used=None,
):
    # print("func_name",func_name,flush=True)
    # Use prepend text to contruct full instance names
    new_inst_name_prepend_text = containing_logic_inst_name + LOGIC.SUBMODULE_MARKER
    if func_name in parser_state.main_mhz:
        # Main never gets prepend text
        if containing_logic_inst_name != "":
            print(
                "Woah there, are you calling a top level main function from within another function!?",
                func_name,
                containing_logic_inst_name,
            )
            sys.exit(-1)
        # Override
        new_inst_name_prepend_text = ""

    # Is this function a hardware/tool specific primative?
    if SYN.FUNC_IS_PRIMITIVE(func_name, parser_state):
        if func_name in parser_state.PrimFuncLogicLookupTable:
            orig_func_logic = parser_state.PrimFuncLogicLookupTable[func_name]
        else:
            orig_func_logic = BUILD_PRIMITIVE_FUNC_LOGIC(
                func_name, containing_logic_inst_name, local_inst_name, parser_state
            )
        # Update FuncLogicLookupTable with this new func logic
        parser_state.PrimFuncLogicLookupTable[orig_func_logic.func_name] = (
            orig_func_logic
        )
        parser_state.FuncLogicLookupTable[orig_func_logic.func_name] = orig_func_logic
    # Is this a function who logic is already known? (Parsed from C code? Or evaluated already?)
    elif func_name in parser_state.FuncLogicLookupTable:
        orig_func_logic = parser_state.FuncLogicLookupTable[func_name]
    else:
        # C built in logic (not parsed from function definitions)
        # Build an original instance logic (has instance name but not prepended with full hierarchy yet)
        # Look up containing func logic for this submodule isnt
        containing_func_logic = None
        # Try to use full inst name of containing module
        containing_func_logic = parser_state.LogicInstLookupTable[
            containing_logic_inst_name
        ]
        # if containing_func_logic is not None:
        orig_func_logic = LOGIC.BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(
            containing_func_logic, local_inst_name, parser_state
        )
        orig_func_logic.containing_funcs.add(containing_func_logic.func_name)
        # Update FuncLogicLookupTable with this new func logic
        parser_state.FuncLogicLookupTable[orig_func_logic.func_name] = orig_func_logic

    # Record this instance of func logic
    inst_name = new_inst_name_prepend_text + local_inst_name
    parser_state.LogicInstLookupTable[inst_name] = orig_func_logic
    if func_name not in parser_state.FuncToInstances:
        parser_state.FuncToInstances[func_name] = set()
    parser_state.FuncToInstances[func_name].add(inst_name)

    # Then recursively do submodules
    # USING local names from orig_func_logic
    # print("orig_func_logic.submodule_instances",orig_func_logic.submodule_instances.values())
    for submodule_inst in orig_func_logic.submodule_instances:
        submodule_func_name = orig_func_logic.submodule_instances[submodule_inst]
        submodule_inst_name = inst_name + LOGIC.SUBMODULE_MARKER + submodule_inst
        submodule_c_ast_node_when_used = orig_func_logic.submodule_instance_to_ast_meta[
            submodule_inst
        ]
        submodule_containing_logic_inst_name = inst_name
        parser_state = RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(
            submodule_func_name,
            submodule_inst,
            parser_state,
            submodule_containing_logic_inst_name,
            submodule_c_ast_node_when_used,
        )

    return parser_state


def APPEND_PRAGMA_INFO(parser_state):
    # Get all pragmas in ast
    pragmas = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(parser_state.c_file_ast, c_ast.Pragma)

    # Loop over all pragmas
    for pragma in pragmas:
        toks = pragma.string.split(" ")
        name = toks[0]

        # MAIN (None MHz)
        if name == "MAIN":
            main_func = toks[1]
            if main_func not in parser_state.main_mhz:
                parser_state.main_mhz[main_func] = None
            if main_func not in parser_state.main_syn_mhz:
                parser_state.main_syn_mhz[main_func] = None
            if main_func not in parser_state.main_clk_group:
                parser_state.main_clk_group[main_func] = None

        # MAIN_MHZ (CLK GROUP optional)
        elif name == "MAIN_MHZ":
            toks = pragma.string.split(" ")
            main_func = toks[1]
            mhz_tok = toks[2]
            group = None
            if len(toks) > 3:
                group = toks[3]
                if group == "None":
                    group = None
            if (
                group is not None
                or main_func not in parser_state.main_clk_group
                or parser_state.main_clk_group[main_func] is None
            ):
                parser_state.main_clk_group[main_func] = group
            # Allow float MHz or name of another main func
            try:
                mhz = float(mhz_tok)
                parser_state.main_mhz[main_func] = mhz
                if (
                    main_func not in parser_state.main_syn_mhz
                    or parser_state.main_syn_mhz[main_func] is None
                ):
                    parser_state.main_syn_mhz[main_func] = mhz
            except ValueError:
                # "Not a float"
                if mhz_tok in parser_state.main_mhz:
                    parser_state.main_mhz[main_func] = parser_state.main_mhz[mhz_tok]
                    parser_state.main_syn_mhz[main_func] = parser_state.main_syn_mhz[
                        mhz_tok
                    ]
                else:
                    print("Error in MAIN_MHZ:", main_func, mhz_tok)
                    sys.exit(-1)

        # MAIN_SYN_MHZ (CLK GROUP optional)
        elif name == "MAIN_SYN_MHZ":
            toks = pragma.string.split(" ")
            main_func = toks[1]
            mhz_tok = toks[2]
            group = None
            if len(toks) > 3:
                group = toks[3]
                if group == "None":
                    group = None
            if (
                group is not None
                or main_func not in parser_state.main_clk_group
                or parser_state.main_clk_group[main_func] is None
            ):
                parser_state.main_clk_group[main_func] = group
            # Allow float MHz or name of another main func
            try:
                mhz = float(mhz_tok)
                parser_state.main_syn_mhz[main_func] = mhz
                if (
                    main_func not in parser_state.main_mhz
                    or parser_state.main_mhz[main_func] is None
                ):
                    parser_state.main_mhz[main_func] = mhz
            except ValueError:
                # "Not a float"
                if mhz_tok in parser_state.main_syn_mhz:
                    parser_state.main_syn_mhz[main_func] = parser_state.main_syn_mhz[
                        mhz_tok
                    ]
                    if (
                        main_func not in parser_state.main_mhz
                        or parser_state.main_mhz[main_func] is None
                    ):
                        parser_state.main_mhz[main_func] = parser_state.main_mhz[
                            mhz_tok
                        ]
                else:
                    print("Error in MAIN_SYN_MHZ:", main_func, mhz_tok)
                    sys.exit(-1)

        # MAIN_GROUP
        elif name == "MAIN_GROUP":
            toks = pragma.string.split(" ")
            main_func = toks[1]
            group = toks[2]
            if group == "None":
                group = None
            parser_state.main_clk_group[main_func] = group
            if main_func not in parser_state.main_mhz:
                parser_state.main_mhz[main_func] = None
            if main_func not in parser_state.main_syn_mhz:
                parser_state.main_syn_mhz[main_func] = None

        # FUNC_MULT_STYLE
        elif name == "FUNC_MULT_STYLE":
            toks = pragma.string.split(" ")
            func = toks[1]
            style = toks[2]
            parser_state.func_mult_style[func] = style

        # FUNC_MARK_DEBUG
        elif name == "FUNC_MARK_DEBUG":
            toks = pragma.string.split(" ")
            func = toks[1]
            parser_state.func_marked_debug.add(func)

        # FUNC_WIRES
        elif name == "FUNC_WIRES":
            toks = pragma.string.split(" ")
            main_func = toks[1]
            parser_state.func_marked_wires.add(main_func)

        # FUNC_LATENCY
        elif name == "FUNC_LATENCY":
            toks = pragma.string.split(" ")
            func = toks[1]
            latency = int(toks[2])
            parser_state.func_fixed_latency[func] = latency

        # FUNC_BLACKBOX
        elif name == "FUNC_BLACKBOX":
            toks = pragma.string.split(" ")
            main_func = toks[1]
            parser_state.func_marked_blackbox.add(main_func)

        # FUNC_NO_ADD_IO_REGS
        elif name == "FUNC_NO_ADD_IO_REGS":
            toks = pragma.string.split(" ")
            func = toks[1]
            parser_state.func_marked_no_add_io_regs.add(func)

        # PART
        elif name == "PART":
            toks = pragma.string.split(" ")
            part = " ".join(toks[1:]).strip('"').strip()
            # print("part",part)
            # sys.exit(0)
            if parser_state.part is not None and parser_state.part != part:
                print("Already set part to:", parser_state.part, "!=", part)
                sys.exit(-1)
            parser_state.part = part

        # ONE_HOT
        elif name == "ONE_HOT":
            raise Exception(f"Use one_hot.h instead of #pragma ONE_HOT. {pragma.coord}")
            # thing = toks[1]
            # parser_state.marked_onehot.add(thing)

        # ID_INST
        elif name == "ID_INST":
            # note global var clk cross id is associated with specific instance
            toks = pragma.string.split(" ")
            var_name = toks[1]
            path_id = toks[2]
            var_info = parser_state.global_vars[var_name]
            var_info.path_id = path_id

        # IO_PAIR
        elif name == "IO_PAIR":
            toks = pragma.string.split(" ")
            i_wire = toks[1]
            o_wire = toks[2]
            parser_state.io_pairs.add((i_wire, o_wire))

        # INST_ARRAY
        elif name == "INST_ARRAY":
            toks = pragma.string.split(" ")
            inst_var = toks[1]
            array_var = toks[2]
            parser_state.inst_array_dict[inst_var] = array_var

        # ASYNC_WIRE
        elif name == "ASYNC_WIRE":
            thing = toks[1]
            parser_state.async_wires.add(thing)

        # INPUT top level port
        elif name == "INPUT":
            thing = toks[1]
            parser_state.input_wires.add(thing)

        # OUTPUT top level port
        elif name == "OUTPUT":
            thing = toks[1]
            parser_state.output_wires.add(thing)

        # CLK_MHZ
        elif name == "CLK_MHZ":
            toks = pragma.string.split(" ")
            clk = toks[1]
            mhz = float(toks[2])
            parser_state.clk_mhz[clk] = mhz

        # CLK_MHZ_GROUP
        elif name == "CLK_MHZ_GROUP":
            toks = pragma.string.split(" ")
            clk = toks[1]
            mhz = float(toks[2])
            group = toks[3]
            if group == "None":
                group = None
            parser_state.clk_mhz[clk] = mhz
            parser_state.clk_group[clk] = group

        # FEEDBACK
        elif name == "FEEDBACK":
            # Not handled here, done in func def parsing
            pass

        # INST_NAME
        elif name == "INST_NAME":
            # Not handled here, done in func def parsing
            pass

        # VAR_VHDL_INIT
        elif name == "VAR_VHDL_INIT":
            # Not handled here, done in func def parsing for local statics only first
            pass

        # MARK_DEBUG
        elif name == "MARK_DEBUG":
            # Not handled here, done in func def parsing
            pass

        # MULTI_CYCLE
        elif name == "MULTI_CYCLE":
            # Not handled here, done in func def parsing
            pass

        # AUTO_PIPELINE
        elif name == "AUTOPIPELINE":
            # Not handled here, done in func def parsing
            pass

        else:
            print("Unhandled pragma:", name, pragma.coord)
            sys.exit(-1)

    # Sanity checks
    # MAIN_MHZ
    if len(parser_state.main_mhz) == 0:
        print("No main function specified?")
        print("Ex. #pragma MAIN_MHZ main 100.0")
        sys.exit(-1)


def GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename):
    ast = GET_C_FILE_AST_FROM_C_CODE_TEXT(text, fake_filename)
    func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, ast.ext)
    # if len(func_defs) > 0:
    # print "Coord of func def", func_defs[0].coord

    # print "========="
    return func_defs


def GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(c_text, c_filename):
    # print "========="
    # print "fake_filename",fake_filename
    # print "preprocessed text",c_text
    try:
        # Hacky because somehow parser.parse() getting filename from cpp output?
        c_text = c_text.replace("<stdin>", c_filename)
        # print(c_text)
        parser = c_parser.CParser()
        ast = parser.parse(c_text, filename=c_filename)
        # ast.show()
        return ast
    except c_parser.ParseError as pe:
        print("pycparser says you messed up:", pe)
        # print(c_text)
        sys.exit(-1)


def GET_C_FILE_AST_FROM_C_CODE_TEXT(text, c_filename):
    # Use C parser to do some lifting
    # See https://github.com/eliben/pycparser/blob/master/examples/explore_ast.py
    try:
        # Use preprocessor function
        c_text = preprocess_text(text)
        # print(c_text)
        return GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(c_text, c_filename)
    except c_parser.ParseError as pe:
        print("Parsed fake file name:", c_filename)
        print("Parsed text:")
        print(c_text)
        print("pycparser says you messed up here:", pe)
        # casthelp(pe)
        sys.exit(-1)


def GET_C_AST_FUNC_DEFS(c_file_ast):
    # c_file_ast.show()
    # children are "external declarations",
    # and are stored in a list called ext[]
    func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, c_file_ast.ext)
    return func_defs


def GET_C_AST_STRUCT_DEFS(c_file_ast):
    # Get type defs
    type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
    struct_defs = []
    for type_def in type_defs:
        # casthelp(type_def)
        thing = type_def.children()[0][1].children()[0][1]
        if type(thing) == c_ast.Struct:
            struct_defs.append(thing)

    return struct_defs


def GET_C_AST_ENUM_DEFS(c_file_ast):
    # Get type defs
    type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
    enum_defs = []
    for type_def in type_defs:
        # casthelp(type_def)
        thing = type_def.children()[0][1].children()[0][1]
        if type(thing) == c_ast.Enum:
            enum_defs.append(thing)
    # print enum_defs
    # sys.exit(-1)
    return enum_defs


def GET_C_AST_GLOBAL_DECLS(c_file_ast):
    # Get type defs
    variable_defs = GET_TYPE_FROM_LIST(c_ast.Decl, c_file_ast.ext)

    return variable_defs


def GET_TYPE_FROM_LIST(py_type, list):
    return [item for item in list if type(item) == py_type]



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# C code generation: built-in operator C code, generated headers (bit manip, bit math,
# mem, clock crossing, type arrays/bytes, FSM, single instance) and their parsing.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CLOCK_CROSS_HEADER = "var_clock_cross.h"
TYPE_ARRAY_N_T_HEADER = "type_array_N_t.h"
TYPE_BYTES_T_HEADER = "type_bytes_t.h"
FSM_CLK_HEADER = "func" + FSM_EXT + ".h"
SINGLE_INST_HEADER = "func_SINGLE_INST.h"
GENERATED_HEADER_DIRS = [
    CLOCK_CROSS_HEADER,
    TYPE_ARRAY_N_T_HEADER,
    TYPE_BYTES_T_HEADER,
    FSM_CLK_HEADER,
    SINGLE_INST_HEADER,
]


# Find generated logic and apply additional 'parsed' information
def GEN_CODE_POST_PARSE_LOGIC_ADJUST(func_logic, parser_state):
    # Hacky detect+tag clock crossing
    is_clk_cross = False
    if not func_logic.is_c_built_in:
        if "_READ" in func_logic.func_name:
            read_toks = func_logic.func_name.split("_READ")
            var = read_toks[0]
            if var in parser_state.clk_cross_var_info:
                is_clk_cross = True
        if "_WRITE" in func_logic.func_name:
            write_toks = func_logic.func_name.split("_WRITE")
            var = write_toks[0]
            if var in parser_state.clk_cross_var_info:
                is_clk_cross = True
    if is_clk_cross:
        func_logic.is_clock_crossing = True
        # Hacky marking clk cross func read+write as not able to be pipelined
        func_logic.uses_nonvolatile_state_regs = True

    return func_logic


def WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE(
    preprocessed_c_text, parser_state, regenerate_files
):
    new_regenerate_files = set()
    new_regenerate_files |= GEN_CLOCK_CROSS_HEADERS(
        preprocessed_c_text, parser_state, regenerate_files
    )
    new_regenerate_files |= GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_TYPE_BYTES_HEADERS(
        preprocessed_c_text, parser_state, regenerate_files
    )
    new_regenerate_files |= GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_FSM_CLK_FUNC_HEADERS(
        preprocessed_c_text, parser_state, regenerate_files
    )
    return new_regenerate_files


def GEN_CLOCK_CROSS_HEADERS(preprocessed_c_text, parser_state, regenerate_files):
    # Make output dir
    cc_out_path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "clock_crossing"
    os.makedirs(cc_out_path, exist_ok=True)
    new_regenerate_files = set()
    # Write two funcs in a header for each var
    for var_name in parser_state.clk_cross_var_info:
        c_type = parser_state.global_vars[var_name].type_name
        # is_volatile = parser_state.global_vars[var_name].is_volatile
        write_size, read_size = parser_state.clk_cross_var_info[
            var_name
        ].write_read_sizes
        write_func_name, read_func_name = parser_state.clk_cross_var_info[
            var_name
        ].write_read_funcs
        flow_control = parser_state.clk_cross_var_info[var_name].flow_control
        ratio = 0
        if write_size > read_size:
            ratio = write_size / read_size
        else:
            ratio = read_size / write_size
        ratio = int(ratio)
        text = "#pragma once\n"
        text += '#include "uintN_t.h"\n'
        text += "#define " + var_name + "_RATIO " + str(ratio) + "\n"

        if flow_control:
            # Flow control
            c_type = parser_state.global_vars[var_name].type_name
            # Needs to be a 1 dim array for now
            elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            if len(dims) > 1:
                print("Only single dim in flow control crossing!", var_name)
                sys.exit(0)
            if len(dims) < 1:
                print("No async fifo depth provided for var?:", var_name)
                sys.exit(-1)
            fifo_depth = dims[0]
            c_type = elem_t
            write_in_t = c_type + "[" + str(write_size) + "]"
            read_out_t = c_type + "[" + str(read_size) + "]"

            # Define read and write structs
            write_out_t = var_name + "_write_t"
            text += (
                """typedef struct """
                + write_out_t
                + """
{
"""
            )
            text += "uint1_t ready;\n"
            text += (
                "}"
                + write_out_t
                + """;
"""
            )
            read_out_t = var_name + "_read_t"
            text += (
                """typedef struct """
                + read_out_t
                + """
{
"""
            )
            text += c_type + " data[" + str(read_size) + "]" + ";\n"
            text += "uint1_t valid;\n"
            text += (
                "}"
                + read_out_t
                + """;
"""
            )
        else:
            # No flow control, arrays
            c_type = None
            if var_name in parser_state.global_vars:
                c_type = parser_state.global_vars[var_name].type_name
            text += '#include "' + c_type + '_array_N_t.h"\n'
            new_regenerate_files.add(c_type + "_array_N_t.h")
            write_out_t = "void"
            write_in_t = c_type + "_array_" + str(write_size) + "_t"
            read_out_t = c_type + "_array_" + str(read_size) + "_t"
            text += "#define " + var_name + "_write_t " + write_in_t + "\n"
            text += "#define " + var_name + "_read_t " + read_out_t + "\n"

        text += """
// Clock cross write
"""
        if flow_control:
            text += (
                write_out_t
                + """ """
                + write_func_name
                + "("
                + c_type
                + " write_data["
                + str(write_size)
                + "], uint1_t write_enable)"
            )
        else:
            text += (
                write_out_t + """ """ + write_func_name + "(" + write_in_t + " in_data)"
            )
        text += """
{
  // TODO
}
"""

        text += """
// Clock cross read
"""

        if flow_control:
            text += read_out_t + """ """ + read_func_name + "(uint1_t read_enable)"
        else:
            read_in_t = "void"
            text += read_out_t + """ """ + read_func_name + "()"
        text += """
{
  // TODO
}
"""
        # Write file
        path = cc_out_path + "/" + var_name + ".h"
        open(path, "w").write(text)

    return new_regenerate_files


def WRITE_POST_PREPROCESS_GEN_CODE(preprocessed_c_text, regenerate_files, parser_state):
    new_regenerate_files = set()
    # type_array_N_t - Since C can return constant size arrays
    new_regenerate_files |= GEN_TYPE_ARRAY_N_HEADERS(
        preprocessed_c_text, regenerate_files
    )
    # type_bytes_t - For converting types to/from bytes
    new_regenerate_files |= GEN_POST_PREPROCESS_TYPE_BYTES_HEADERS(
        preprocessed_c_text, regenerate_files
    )
    # Clock fsm gen
    new_regenerate_files |= GEN_POST_PREPROCESS_FSM_CLK_HEADERS(
        preprocessed_c_text, regenerate_files
    )
    # Single inst gen
    new_regenerate_files |= GEN_POST_PREPROCESS_SINGLE_INST_HEADERS(
        preprocessed_c_text, regenerate_files, parser_state
    )

    return new_regenerate_files


def GEN_EMPTY_GENERATED_HEADERS(all_code_files, inital_missing_files, parser_state):
    # These headers are generated
    # by looking for autogenerated header files to be included

    existing_files = []
    for f in all_code_files:
        if os.path.exists(f):
            existing_files.append(f)

    new_regenerate_files = set()

    new_regenerate_files |= GEN_EMPTY_TYPE_ARRAY_N_HEADERS(
        existing_files, inital_missing_files
    )
    new_regenerate_files |= GEN_EMPTY_CLOCK_CROSS_HEADERS(
        existing_files, inital_missing_files
    )
    new_regenerate_files |= GEN_EMPTY_TYPE_BYTES_HEADERS(
        existing_files, inital_missing_files
    )
    new_regenerate_files |= GEN_EMPTY_FSM_CLK_FUNC_HEADERS(
        existing_files, inital_missing_files, parser_state
    )
    new_regenerate_files |= GEN_EMPTY_SINGLE_INST_FUNC_HEADERS(
        existing_files, inital_missing_files, parser_state
    )

    return new_regenerate_files


def GEN_EMPTY_SINGLE_INST_FUNC_HEADERS(
    existing_files, inital_missing_files, parser_state
):
    new_regenerate_files = set()
    for inital_missing_file in inital_missing_files:
        # Regex search c_text for "<func>_SINGLE_INST.h"
        r = rf"\w+_SINGLE_INST.h"
        header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
        func_names = []
        for header_str_quote in header_str_quotes:
            header = header_str_quote.strip('"')
            toks = header.split("_SINGLE_INST.h")
            func_name = toks[0]
            dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + SINGLE_INST_HEADER
            path = dir_name + "/" + func_name + "_SINGLE_INST.h"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            if not os.path.exists(path):
                f = open(path, "w")
                text = ""
                text += '#include "wire.h"\n'
                # text += '#include "'+func_name+'_INPUT_t_array_N_t.h"\n'
                # text += '#include "'+func_name+'_OUTPUT_t_array_N_t.h"\n'
                f.write(text)
                f.close()
            parser_state.func_single_inst_header_included.add(func_name)

    return new_regenerate_files


def GEN_EMPTY_CLOCK_CROSS_HEADERS(all_code_files, inital_missing_files):
    new_regenerate_files = set()
    for inital_missing_file in inital_missing_files:
        # Regex search c_text for "clock_crossing/<type>/<var>.h"
        r = ".*clock_crossing.*"
        clock_cross_header_strs = FIND_REGEX_MATCHES(r, inital_missing_file)
        # print("clock_cross_header_str_quotes", clock_cross_header_str_quotes)
        var_names = []
        for clock_cross_header_str in clock_cross_header_strs:
            toks = clock_cross_header_str.split(".h")
            type_slash_var = toks[0]
            if "/" not in type_slash_var:
                var_name = type_slash_var.split("_clock_crossing")[0]
                print("")
                print("Please remove array include:")
                print('#include "<type>_array_N_t.h"')
                print("")
                print(
                    "And change clock crossing variable in include statement to be like:"
                )
                print(f'#include "clock_crossing/{var_name}.h"')
                sys.exit(-1)

            type_slash_toks = type_slash_var.split("/")
            # is_volatile = False
            if len(type_slash_toks) == 2:
                cc_str, var_name = type_slash_toks
                dir_name = (
                    SYN.SYN_OUTPUT_DIRECTORY + "/" + "clock_crossing"
                )  # + "/" + var_type

            path = dir_name + "/" + var_name + ".h"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            if not os.path.exists(path):
                f = open(path, "w")
                # f.write(decl_text)
                # Need dummy defines
                f.write("#define " + var_name + "_RATIO 0\n")
                # f.write('#define ' + var_name + "_write_t int\n")
                # f.write('#define ' + var_name + "_read_t int\n")
                f.write("typedef int " + var_name + "_write_t;\n")
                f.write("typedef int " + var_name + "_read_t;\n")
                f.write("")
                f.close()

    return new_regenerate_files


def GEN_EMPTY_TYPE_ARRAY_N_HEADERS(all_code_files, inital_missing_files):
    new_regenerate_files = set()
    for inital_missing_file in inital_missing_files:
        # Regex search c_text for "<type>_array_<num>_t.h"
        r = rf"\w+_array_N_t.h"
        array_type_header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
        var_names = []
        for array_type_header_str_quote in array_type_header_str_quotes:
            array_type_header = array_type_header_str_quote.strip('"')
            toks = array_type_header.split("_array_")
            type_name = toks[0]
            dir_name = (
                SYN.SYN_OUTPUT_DIRECTORY
                + "/"
                + TYPE_ARRAY_N_T_HEADER
                + "/"
                + type_name
                + "_array_N_t.h"
            )
            path = dir_name + "/" + type_name + "_array_N_t.h"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            if not os.path.exists(path):
                open(path, "w").write("")

    return new_regenerate_files


def GEN_EMPTY_TYPE_BYTES_HEADERS(all_code_files, inital_missing_files):
    new_regenerate_files = set()
    for inital_missing_file in inital_missing_files:
        # Regex search c_text for "<type>_bytes_t.h"
        r = rf"\w+_bytes_t.h"
        bytes_header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
        var_names = []
        for bytes_header_str_quote in bytes_header_str_quotes:
            bytes_header = bytes_header_str_quote.strip('"')
            toks = bytes_header.split("_bytes_t.h")
            type_name = toks[0]
            dir_name = (
                SYN.SYN_OUTPUT_DIRECTORY
                + "/"
                + TYPE_BYTES_T_HEADER
                + "/"
                + type_name
                + "_bytes_t.h"
            )
            path = dir_name + "/" + type_name + "_bytes_t.h"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            if not os.path.exists(path):
                open(path, "w").write("")

    return new_regenerate_files


def GEN_EMPTY_FSM_CLK_FUNC_HEADERS(all_code_files, inital_missing_files, parser_state):
    new_regenerate_files = set()
    for inital_missing_file in inital_missing_files:
        # Regex search c_text
        r = rf"\w+" + FSM_EXT + ".h"
        str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
        var_names = []
        for str_quote in str_quotes:
            header = str_quote.strip('"')
            toks = header.split(FSM_EXT + ".h")
            func_name = toks[0]
            dir_name = (
                SYN.SYN_OUTPUT_DIRECTORY
                + "/"
                + FSM_CLK_HEADER
                + "/"
                + func_name
                + FSM_EXT
                + ".h"
            )
            path = dir_name + "/" + func_name + FSM_EXT + ".h"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            if not os.path.exists(path):
                open(path, "w").write("")
            parser_state.func_fsm_header_included.add(func_name)

    return new_regenerate_files


def GEN_POST_PREPROCESS_SINGLE_INST_HEADERS(
    preprocessed_c_text, regenerate_files, parser_state
):
    # Nothing in preprocessed text to look at so use
    # parser_state.func_single_inst_header_included
    new_regenerate_files = set()

    for func_name in parser_state.func_single_inst_header_included:
        dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + SINGLE_INST_HEADER
        path = dir_name + "/" + func_name + "_SINGLE_INST.h"
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
            f = open(path, "w")
            text = ""
            text += '#include "wire.h"\n'
            text += '#include "' + func_name + '_FSM.h"\n'
            new_regenerate_files.add(func_name + "_FSM.h")
            text += func_name + "_INPUT_t " + func_name + "_arb_inputs;\n"
            text += func_name + "_OUTPUT_t " + func_name + "_arb_outputs;\n"
            text += (
                "#pragma IO_PAIR "
                "" + func_name + "_arb_inputs " + func_name + "_arb_outputs\n"
            )
            text += '#include "clock_crossing/' + func_name + '_arb_inputs.h"\n'
            new_regenerate_files.add("clock_crossing/" + func_name + "_arb_inputs.h")
            text += '#include "clock_crossing/' + func_name + '_arb_outputs.h"\n'
            new_regenerate_files.add("clock_crossing/" + func_name + "_arb_outputs.h")
            text += (
                """#pragma MAIN """
                + func_name
                + """_arb
void """
                + func_name
                + """_arb()
{
  """
                + func_name
                + """_INPUT_t i;
  """
                + func_name
                + """_OUTPUT_t o;
  WIRE_READ("""
                + func_name
                + """_INPUT_t, i, """
                + func_name
                + """_arb_inputs)
  o = """
                + func_name
                + """_FSM(i);
  WIRE_WRITE("""
                + func_name
                + """_OUTPUT_t, """
                + func_name
                + """_arb_outputs, o)
}
"""
            )
            f.write(text)
            f.close()

    return new_regenerate_files


def GEN_POST_PREPROCESS_FSM_CLK_HEADERS(preprocessed_c_text, regenerate_files):
    # Regex search c_text for <type>_bytes_t
    r = rf"\w+" + FSM_EXT
    func_names = FIND_REGEX_MATCHES(r, preprocessed_c_text)

    # #define replacing  Typedef each one
    for func_name in func_names:
        toks = func_name.split(FSM_EXT)
        fsm_clk_func_name = toks[0]

        # We are beyond asking for help
        # Your biologial and technological distinctiveness will be added to the project
        # Fake IO types?
        text = ""
        text += (
            """
typedef uint8_t """
            + fsm_clk_func_name
            + """_INPUT_t; // DUMMY
typedef uint8_t """
            + fsm_clk_func_name
            + """_OUTPUT_t; // DUMMY
"""
        )

        # Write file
        out_dir = (
            SYN.SYN_OUTPUT_DIRECTORY
            + "/"
            + FSM_CLK_HEADER
            + "/"
            + fsm_clk_func_name
            + FSM_EXT
            + ".h"
        )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        path = out_dir + "/" + fsm_clk_func_name + FSM_EXT + ".h"
        if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
            open(path, "w").write(text)

    # No extra code gen
    return set()


def GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_FSM_CLK_FUNC_HEADERS(
    preprocessed_c_text, parser_state, regenerate_files
):
    for func_name, func_logic in parser_state.FuncLogicLookupTable.items():
        # print(func_logic.func_name, ".is_fsm_clk_func",func_logic.is_fsm_clk_func)
        if func_logic.is_fsm_clk_func:
            text = "#pragma once\n"
            text += C_TO_FSM.FSM_LOGIC_TO_C_CODE(func_logic, parser_state)
            # Write file
            out_dir = (
                SYN.SYN_OUTPUT_DIRECTORY
                + "/"
                + FSM_CLK_HEADER
                + "/"
                + func_name
                + FSM_EXT
                + ".h"
            )
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            path = out_dir + "/" + func_name + FSM_EXT + ".h"
            open(path, "w").write(text)

    # FSM clks do not introduce extra code gen - based on existing user code
    return set()


def GEN_POST_PREPROCESS_TYPE_BYTES_HEADERS(preprocessed_c_text, regenerate_files):
    # Regex search c_text for <type>_bytes_t
    r = rf"\w+_bytes_t"
    byte_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)

    # #define replacing  Typedef each one
    for byte_type in byte_types:
        # print "array_type",array_type
        toks = byte_type.split("_bytes_t")
        elem_t = toks[0]

        # Dummy typedefs for now to fool c parser?? oh plz help - double up on some help wassup
        # Yall sitting round here helplessnshit
        text = ""
        text += (
            """
typedef uint8_t """
            + byte_type
            + """; // DUMMY
#define """
            + elem_t
            + "_size_t"
            + """ uint32_t // DUMMY
#define """
            + elem_t.upper()
            + """_TO_BYTES(so,dumb) // DUMMY
"""
        )

        # Write file
        out_dir = (
            SYN.SYN_OUTPUT_DIRECTORY
            + "/"
            + TYPE_BYTES_T_HEADER
            + "/"
            + elem_t
            + "_bytes_t.h"
        )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        path = out_dir + "/" + elem_t + "_bytes_t.h"
        if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
            open(path, "w").write(text)

    # No extra code gen
    return set()


# Hey this function is dumb large
# Just sayin
def GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_TYPE_BYTES_HEADERS(
    preprocessed_c_text, parser_state, regenerate_files
):
    new_regenerate_files = set()
    # print preprocessed_c_text
    # Regex search c_text for <type>_bytes_t
    r = rf"\w+_bytes_t"
    byte_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)

    # #define replacing each one with array_n_t type
    for byte_type in byte_types:
        # print "array_type",array_type
        toks = byte_type.split("_bytes_t")
        type_t = toks[0]

        # Fully generate a good header file for this type
        text = "#pragma once\n"

        # Include bytes for any sub fields of this type
        types_to_include = set()
        if LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
            field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
            for field in field_to_type_dict:
                field_type = field_to_type_dict[field]
                type_to_include = field_type
                if LOGIC.C_TYPE_IS_ARRAY(field_type):
                    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        field_type
                    )
                    type_to_include = elem_t
                # Ok to hacky replace char with u8 here?
                if type_to_include == "char":
                    type_to_include = "uint8_t"
                types_to_include.add(type_to_include)
        for type_to_include in types_to_include:
            text += '#include "' + type_to_include + '_bytes_t.h"\n'
            new_regenerate_files.add(type_to_include + "_bytes_t.h")

        # #define the _bytes_t to be the uint8_t_array_N_t type
        size = LOGIC.C_TYPE_SIZE(type_t, parser_state, allow_fail=True)
        # hacky mchack
        if size <= 0:
            continue
        text += '#include "uint8_t_array_N_t.h"\n'
        new_regenerate_files.add("uint8_t_array_N_t.h")
        text += "#define " + byte_type + " " + "uint8_t_array_" + str(size) + "_t\n"
        # define a size_t for iterating over as many bytes
        size_t_width = int(math.ceil(math.log(size, 2))) + 1
        size_t = "uint" + str(size_t_width) + "_t"
        text += "#define " + type_t + "_SIZE" + " " + str(size) + "\n"
        text += "#define " + type_t + "_size_t" + " " + size_t + "\n"
        func_name = type_t + "_to_bytes"

        # Func type to bytes ###############################################
        text += (
            """
#pragma FUNC_WIRES """
            + func_name
            + """
"""
            + byte_type
            + " "
            + func_name
            + "("
            + type_t
            + """ x)
{
"""
            + byte_type
            + """ rv;
"""
        )
        # Base type formulas
        if LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
            # Counters for packing into rv
            text += size_t + " pos = 0;\n"
            text += size_t + " field_pos = 0;\n"

            # Loop over each field
            field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
            for field in field_to_type_dict:
                text += "// " + field + "\n"
                field_type = field_to_type_dict[field]
                # Need to manually handle array fields for now
                if LOGIC.C_TYPE_IS_ARRAY(field_type):
                    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        field_type
                    )
                    # Ok to hacky replace char with u8 here?
                    if elem_t == "char":
                        elem_t = "uint8_t"
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        dim = dims[dim_i]
                        dim_size_t_width = dim.bit_length()
                        dim_size_t = "uint" + str(dim_size_t_width) + "_t"
                        dim_var = field + "_dim_" + str(dim_i)
                        text += dim_size_t + " " + dim_var + ";\n"
                        text += (
                            "for("
                            + dim_var
                            + "=0;"
                            + dim_var
                            + "<"
                            + str(dim)
                            + ";"
                            + dim_var
                            + "="
                            + dim_var
                            + "+1){\n"
                        )

                    # The repeated bytes assignments similar to normal case below
                    # Get bytes
                    elem_bytes_var = field + "_elem_bytes"
                    text += (
                        " "
                        + elem_t
                        + "_bytes_t "
                        + elem_bytes_var
                        + " = "
                        + elem_t
                        + "_to_bytes(x."
                        + field
                    )
                    for dim_i in range(0, len(dims)):
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "[" + dim_var + "]"
                    text += ");\n"
                    # Do loop to assign bytes
                    text += (
                        """ for(field_pos=0;field_pos<sizeof("""
                        + elem_t
                        + """);field_pos = field_pos + 1)
  {
    rv.data[pos] = """
                        + elem_bytes_var
                        + """.data[field_pos];
    pos = pos + 1;
  }
"""
                    )
                    # Close braces
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        text += "}\n"
                else:
                    # Normal, just do recursive _to_bytes
                    text += (
                        field_type
                        + "_bytes_t "
                        + field
                        + "_bytes = "
                        + field_type
                        + "_to_bytes(x."
                        + field
                        + ");\n"
                    )
                    text += (
                        """for(field_pos=0;field_pos<sizeof("""
                        + field_type
                        + """);field_pos = field_pos + 1)
{
  rv.data[pos] = """
                        + field
                        + """_bytes.data[field_pos];
  pos = pos + 1;
}
"""
                    )

        elif LOGIC.C_TYPES_ARE_INTEGERS([type_t]):
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
            typeprefix = type_t.split("_t")[0]
            low_i = 0
            high_i = 7
            byte_i = 0
            while high_i < width:
                text += (
                    "rv.data["
                    + str(byte_i)
                    + "] = "
                    + typeprefix
                    + "_"
                    + str(high_i)
                    + "_"
                    + str(low_i)
                    + "(x);\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                text += (
                    "rv.data["
                    + str(byte_i)
                    + "] = "
                    + typeprefix
                    + "_"
                    + str(width - 1)
                    + "_"
                    + str(low_i)
                    + "(x);\n"
                )
        elif LOGIC.C_TYPE_IS_FLOAT_TYPE(type_t):
            float_bytes = LOGIC.C_TYPE_SIZE(type_t, parser_state)
            for float_byte_i in range(0, float_bytes):
                text += f"rv.data[{float_byte_i}] = {type_t}_{((float_byte_i+1)*8)-1}_{float_byte_i*8}(x);\n"
        elif LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
            # How many bytes
            width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, type_t)
            typeprefix = "uint" + str(width)
            int_type = typeprefix + "_t"
            # Convert to uint
            text += int_type + " int_val = x;\n"
            # Copy uint logic from above
            low_i = 0
            high_i = 7
            byte_i = 0
            while high_i < width:
                text += (
                    "rv.data["
                    + str(byte_i)
                    + "] = "
                    + typeprefix
                    + "_"
                    + str(high_i)
                    + "_"
                    + str(low_i)
                    + "(int_val);\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                text += (
                    "rv.data["
                    + str(byte_i)
                    + "] = "
                    + typeprefix
                    + "_"
                    + str(width - 1)
                    + "_"
                    + str(low_i)
                    + "(int_val);\n"
                )

        else:
            print("to bytes for type:", type_t)
            sys.exit(-1)

        text += """
    return rv;
}
"""

        # Also gen helper macro
        text += (
            """
#define """
            + type_t.upper()
            + """_TO_BYTES(dst_byte_array, """
            + type_t
            + """_x)\\
"""
            + byte_type
            + " "
            + type_t
            + "_to_bytes_WIRE = "
            + type_t
            + "_to_bytes("
            + type_t
            + """_x);\\
uint32_t """
            + type_t
            + """_to_bytes_i;\\
for("""
            + type_t
            + "_to_bytes_i=0;"
            + type_t
            + "_to_bytes_i<"
            + type_t
            + "_SIZE;"
            + type_t
            + """_to_bytes_i+=1)\\
{\\
  dst_byte_array["""
            + type_t
            + """_to_bytes_i] = """
            + type_t
            + """_to_bytes_WIRE.data["""
            + type_t
            + """_to_bytes_i];\\
}
"""
        )

        # Func bytes to type ###############################################
        func_name = "bytes_to_" + type_t
        text += (
            """
#pragma FUNC_WIRES """
            + func_name
            + """
"""
            + type_t
            + " "
            + func_name
            + "(uint8_t bytes["
            + type_t
            + "_SIZE"
            + """])
{
"""
            + type_t
            + """ rv;
"""
        )
        # Base type formulas
        if LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
            # Counters for packing into rv
            text += size_t + " pos = 0;\n"
            text += size_t + " field_pos = 0;\n"

            # Loop over each field
            field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
            for field in field_to_type_dict:
                text += "// " + field + "\n"
                field_type = field_to_type_dict[field]
                # Need to manually handle array fields for now
                if LOGIC.C_TYPE_IS_ARRAY(field_type):
                    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        field_type
                    )
                    # Ok to hacky replace char with u8 here?
                    if elem_t == "char":
                        elem_t = "uint8_t"
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        dim = dims[dim_i]
                        dim_size_t_width = dim.bit_length()
                        dim_size_t = "uint" + str(dim_size_t_width) + "_t"
                        dim_var = field + "_dim_" + str(dim_i)
                        text += dim_size_t + " " + dim_var + ";\n"
                        text += (
                            "for("
                            + dim_var
                            + "=0;"
                            + dim_var
                            + "<"
                            + str(dim)
                            + ";"
                            + dim_var
                            + "="
                            + dim_var
                            + "+1){\n"
                        )

                    # The repeated bytes assignments similar to normal case below
                    elem_bytes_var = field + "_elem_bytes"
                    text += " " + elem_t + "_bytes_t " + elem_bytes_var + ";\n"
                    text += (
                        """ for(field_pos=0;field_pos<sizeof("""
                        + elem_t
                        + """);field_pos = field_pos + 1)
  {
    """
                        + elem_bytes_var
                        + """.data[field_pos] = bytes[pos];
    pos = pos + 1;
  }
"""
                    )
                    text += " rv." + field
                    for dim_i in range(0, len(dims)):
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "[" + dim_var + "]"
                    text += " = bytes_to_" + elem_t + "(" + elem_bytes_var + ");\n"

                    # Close braces
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        text += "}\n"
                else:
                    # Normal, just do recursive bytes_to_field_t
                    # Assemble bytes for field
                    text += field_type + "_bytes_t " + field + "_bytes;\n"
                    text += (
                        """for(field_pos=0;field_pos<sizeof("""
                        + field_type
                        + """);field_pos = field_pos + 1)
{
  """
                        + field
                        + """_bytes.data[field_pos] = bytes[pos];
  pos = pos + 1;
}
"""
                    )
                    text += (
                        "rv."
                        + field
                        + " = bytes_to_"
                        + field_type
                        + "("
                        + field
                        + "_bytes);\n"
                    )

        elif LOGIC.C_TYPES_ARE_INTEGERS([type_t]):
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
            typeprefix = type_t.split("_t")[0]
            low_i = 0
            high_i = 7
            byte_i = 0
            text += "rv = 0;\n"
            while high_i < width:
                text += (
                    "rv = "
                    + typeprefix
                    + "_uint8_"
                    + str(low_i)
                    + "(rv, bytes["
                    + str(byte_i)
                    + "]);\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                rem = width - low_i
                remprefix = "uint" + str(rem)
                text += (
                    "rv = "
                    + typeprefix
                    + "_"
                    + remprefix
                    + "_"
                    + str(low_i)
                    + "(rv, bytes["
                    + str(byte_i)
                    + "]);\n"
                )
        elif type_t == "float":
            text += """
    // Assemble 4 byte buffer
    uint8_t buff[sizeof(float)];
    uint3_t buff_pos;
    for(buff_pos=0;buff_pos<sizeof(float);buff_pos=buff_pos+1)
    {
      buff[buff_pos] = bytes[buff_pos];
    }
    // Convert as little endian to uint32_t
    uint32_t val_unsigned;
    val_unsigned = uint8_array4_le(buff);
    // Convert uint32_t to float
    rv = float_uint32(val_unsigned);
      """

        elif LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
            # How many bytes
            width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, type_t)
            typeprefix = "uint" + str(width)
            int_type = typeprefix + "_t"
            # Convert to uint like uint case
            text += int_type + " int_val;\n"
            low_i = 0
            high_i = 7
            byte_i = 0
            text += "int_val = 0;\n"
            while high_i < width:
                text += (
                    "int_val = "
                    + typeprefix
                    + "_uint8_"
                    + str(low_i)
                    + "(int_val, bytes["
                    + str(byte_i)
                    + "]);\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                rem = width - low_i
                remprefix = "uint" + str(rem)
                text += (
                    "int_val = "
                    + typeprefix
                    + "_"
                    + remprefix
                    + "_"
                    + str(low_i)
                    + "(int_val, bytes["
                    + str(byte_i)
                    + "]);\n"
                )
            # And then convert uint to enum
            text += "rv = int_val;\n"
        else:
            print("bytes to for type:", type_t)
            # sys.exit(-1)

        text += """
    return rv;
}"""

        # Write file
        out_dir = (
            SYN.SYN_OUTPUT_DIRECTORY
            + "/"
            + TYPE_BYTES_T_HEADER
            + "/"
            + type_t
            + "_bytes_t.h"
        )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        path = out_dir + "/" + type_t + "_bytes_t.h"
        open(path, "w").write(text)

        ####################################################################
        #
        ## DO THE SAME THING AGAIN FOR REAL C SOFTWARE SIDE
        #
        ####################################################################

        # Fully generate a good header file for this type
        text = "#pragma once\n"

        # Include bytes for any sub fields of this type
        for type_to_include in types_to_include:
            text += (
                '#include "type_bytes_t.h/'
                + type_to_include
                + "_bytes_t.h/"
                + type_to_include
                + '_bytes.h"\n'
            )

        text += "#define " + type_t + "_SIZE" + " " + str(size) + "\n"

        # #define the _bytes_t to be the uint8_t_array_N_t type
        size = LOGIC.C_TYPE_SIZE(type_t, parser_state, allow_fail=True)
        # hacky mchack
        if size <= 0:
            continue

        # Func type to bytes ###############################################
        text += (
            """
void """
            + type_t
            + "_to_bytes("
            + type_t
            + """* x, uint8_t* bytes)
{
"""
        )
        # Base type formulas
        if LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
            # Counters for packing into rv
            text += "size_t pos = 0;\n"

            # Loop over each field
            field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
            for field in field_to_type_dict:
                text += "// " + field + "\n"
                field_type = field_to_type_dict[field]
                field_size = LOGIC.C_TYPE_SIZE(field_type, parser_state)
                # Need to manually handle array fields for now
                if LOGIC.C_TYPE_IS_ARRAY(field_type):
                    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        field_type
                    )
                    # Ok to hacky replace char with u8 here?
                    if elem_t == "char":
                        elem_t = "uint8_t"
                    elem_size = LOGIC.C_TYPE_SIZE(elem_t, parser_state)
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        dim = dims[dim_i]
                        dim_size_t_width = dim.bit_length()
                        dim_size_t = "uint" + str(dim_size_t_width) + "_t"
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "size_t " + dim_var + ";\n"
                        text += (
                            "for("
                            + dim_var
                            + "=0;"
                            + dim_var
                            + "<"
                            + str(dim)
                            + ";"
                            + dim_var
                            + "="
                            + dim_var
                            + "+1){\n"
                        )

                    # The repeated bytes assignments similar to normal case below
                    text += " " + elem_t + "_to_bytes(&(x->" + field
                    for dim_i in range(0, len(dims)):
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "[" + dim_var + "]"
                    text += "), &(bytes[pos]));\n"
                    text += " pos = pos + " + str(elem_size) + "; // not sizeof()\n"

                    # Close braces
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        text += "}\n"
                else:
                    # Normal, just do recursive _to_bytes
                    text += (
                        field_type + "_to_bytes(&(x->" + field + "), &(bytes[pos]));\n"
                    )
                    text += "pos = pos + " + str(field_size) + "; // not sizeof()\n"

        elif LOGIC.C_TYPES_ARE_INTEGERS([type_t]):
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
            typeprefix = type_t.split("_t")[0]
            low_i = 0
            high_i = 7
            byte_i = 0
            while high_i < width:
                text += (
                    "bytes[" + str(byte_i) + "] = (uint8_t)(*x>>" + str(low_i) + ");\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                print("Non byte bit width in C?", width)
                print("Dance Hall - Modest Mouse")
                sys.exit(-1)
        elif type_t == "float":
            text += """memcpy(bytes, x, 4);
"""
        elif LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
            # How many bytes
            num_bytes = LOGIC.C_TYPE_SIZE(type_t, parser_state)
            width = 8 * num_bytes
            typeprefix = "uint" + str(width)
            int_type = typeprefix + "_t"
            text += int_type + " int_val = *x;\n"
            # Convert to uint like uint case
            low_i = 0
            high_i = 7
            byte_i = 0
            while high_i < width:
                text += (
                    "bytes["
                    + str(byte_i)
                    + "] = (uint8_t)(int_val>>"
                    + str(low_i)
                    + ");\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                print("Non byte bit width enum to sw bytes??", width, type_t)
                sys.exit(-1)
        else:
            print("to sw bytes for type:", type_t)
            sys.exit(-1)

        text += """
}
"""

        # Func bytes to type ###############################################
        text += (
            """
void bytes_to_"""
            + type_t
            + "(uint8_t* bytes, "
            + type_t
            + """* x)
{
"""
        )
        # Base type formulas
        if LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
            # Counters for packing into rv
            text += "size_t pos = 0;\n"

            # Loop over each field
            field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
            for field in field_to_type_dict:
                text += "// " + field + "\n"
                field_type = field_to_type_dict[field]
                field_size = LOGIC.C_TYPE_SIZE(field_type, parser_state)
                # Need to manually handle array fields for now
                if LOGIC.C_TYPE_IS_ARRAY(field_type):
                    elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        field_type
                    )
                    # Ok to hacky replace char with u8 here?
                    if elem_t == "char":
                        elem_t = "uint8_t"
                    elem_size = LOGIC.C_TYPE_SIZE(elem_t, parser_state)
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        dim = dims[dim_i]
                        dim_size_t_width = dim.bit_length()
                        dim_size_t = "uint" + str(dim_size_t_width) + "_t"
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "size_t " + dim_var + ";\n"
                        text += (
                            "for("
                            + dim_var
                            + "=0;"
                            + dim_var
                            + "<"
                            + str(dim)
                            + ";"
                            + dim_var
                            + "="
                            + dim_var
                            + "+1){\n"
                        )

                    # The repeated bytes assignments similar to normal case below
                    text += " bytes_to_" + elem_t + "(&(bytes[pos]), &(x->" + field
                    for dim_i in range(0, len(dims)):
                        dim_var = field + "_dim_" + str(dim_i)
                        text += "[" + dim_var + "]"
                    text += "));\n"
                    text += " pos = pos + " + str(elem_size) + "; // not sizeof()\n"

                    # Close braces
                    # nest for loop for each dim
                    for dim_i in range(0, len(dims)):
                        text += "}\n"
                else:
                    # Normal, just do recursive _to_bytes
                    text += (
                        "bytes_to_"
                        + field_type
                        + "(&(bytes[pos]), &(x->"
                        + field
                        + "));\n"
                    )
                    text += "pos = pos + " + str(field_size) + "; // not sizeof()\n"

        elif LOGIC.C_TYPES_ARE_INTEGERS([type_t]):
            width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
            typeprefix = type_t.split("_t")[0]
            low_i = 0
            high_i = 7
            byte_i = 0
            text += "*x = 0;\n"
            while high_i < width:
                text += (
                    "*x |= ((("
                    + type_t
                    + ")bytes["
                    + str(byte_i)
                    + "])<<"
                    + str(low_i)
                    + ");\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                print("Non byte bit width in C?", width)
                print("Perfect Disguise - Modest Mouse")
                sys.exit(-1)
        elif type_t == "float":
            text += """memcpy(x, bytes, 4);
"""
        elif LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
            # How many bytes
            num_bytes = LOGIC.C_TYPE_SIZE(type_t, parser_state)
            width = 8 * num_bytes
            typeprefix = "uint" + str(width)
            int_type = typeprefix + "_t"
            # Convert to uint like uint case
            text += int_type + " int_val;\n"
            low_i = 0
            high_i = 7
            byte_i = 0
            text += "int_val = 0;\n"
            while high_i < width:
                text += (
                    "int_val |= ((("
                    + int_type
                    + ")bytes["
                    + str(byte_i)
                    + "])<<"
                    + str(low_i)
                    + ");\n"
                )
                low_i = low_i + 8
                high_i = high_i + 8
                byte_i = byte_i + 1
            if low_i < width:
                print("Non byte bit width enum from sw bytes??", width, type_t)
                sys.exit(-1)
            # Then convert to enum
            text += "*x = (" + type_t + ")int_val;\n"
        else:
            print("to type from sw bytes, type:", type_t)
            sys.exit(-1)

        text += """
}
"""

        # Write file
        path = (
            out_dir + "/" + type_t + "_bytes.h"
        )  # SW version doesnt have since dont need to deinfe byte type in SW?
        open(path, "w").write(text)

    return new_regenerate_files


def GEN_TYPE_ARRAY_N_HEADERS(preprocessed_c_text, regenerate_files):
    # Regex search c_text for <type>_array_<num>_t
    r = rf"\w+_array_[0-9]+_t"
    array_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)
    # print("preprocessed_c_text",preprocessed_c_text)
    # print("array_types",array_types)
    text_per_elem_t = {}

    # Typedef each one
    for array_type in array_types:
        # print "array_type",array_type
        toks = array_type.split("_array_")
        elem_t = toks[0]
        if elem_t not in text_per_elem_t:
            text_per_elem_t[elem_t] = ""

        size_str = toks[1].replace("_t", "")
        text_per_elem_t[elem_t] += (
            """
typedef struct """
            + array_type
            + """
{
  """
            + elem_t
            + """ data["""
            + size_str
            + """];
} """
            + array_type
            + """;"""
        )

    # Write files per elem_t
    for elem_t in text_per_elem_t:
        text = text_per_elem_t[elem_t]
        out_dir = (
            SYN.SYN_OUTPUT_DIRECTORY
            + "/"
            + TYPE_ARRAY_N_T_HEADER
            + "/"
            + elem_t
            + "_array_N_t.h"
        )
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        path = out_dir + "/" + elem_t + "_array_N_t.h"
        f = open(path, "w")
        f.write("#pragma once\n")
        f.write(text)

    # Does not introduce any more code gen
    return set()


def GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(
    c_text, parser_state
):
    # print("GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT\n",c_text)
    # DONT FORGET TO CHANGE IS_AUTO_GENERATED and FUNC_NAME_INCLUDES_TYPES??
    lookups = []

    # BIT manipulation is auto generated
    bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(
        c_text, parser_state
    )
    lookups.append(bit_manip_func_name_logic_lookup)

    # print "bit_manip_func_name_logic_lookup",bit_manip_func_name_logic_lookup

    ###### THESE DEPEND ON BIT MANIP #TODO: Depedencies what?
    bit_math_func_name_logic_lookup = GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(
        c_text, parser_state
    )
    lookups.append(bit_math_func_name_logic_lookup)

    # print "bit_math_func_name_logic_lookup",bit_math_func_name_logic_lookup

    # MEMORY
    # # TODO MOVE TO WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE?
    mem_func_name_logic_lookup = GET_MEM_H_LOGIC_LOOKUP(parser_state)
    lookups.append(mem_func_name_logic_lookup)

    # Combine lookups
    rv = {}
    for func_name_logic_lookup in lookups:
        for func_name in func_name_logic_lookup:
            if func_name not in rv:
                rv[func_name] = func_name_logic_lookup[func_name]
                # print "func_name (func_name_logic_lookup)",func_name
                # if len(func_name_logic_lookup[func_name].wire_drives) == 0:
                # print "BAD!"
                # sys.exit(-1)
            else:
                # For now allow if from bit manip
                # print "str(rv[func_name].c_ast_node.coord)",str(rv[func_name].c_ast_node.coord)
                if LOGIC.IS_BIT_MANIP(rv[func_name]):
                    pass
                else:
                    print(
                        "GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT func_name in multiple dicts?",
                        func_name,
                    )
                    print(
                        "bit_manip_func_name_logic_lookup",
                        bit_manip_func_name_logic_lookup,
                    )
                    print("===")
                    print(
                        "bit_math_func_name_logic_lookup",
                        bit_math_func_name_logic_lookup,
                    )
                    sys.exit(-1)

    return rv


# Not including user types and dumb struct thing everywhere we internally run C parsser
# so just fake it # Pups To Dust - Modest Mouse
def C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(c_type, parser_state):
    return LOGIC.C_TYPE_IS_USER_TYPE(
        c_type, parser_state
    ) or LOGIC.C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state)


# Any hardware resource that can described as unit of memory, number of those units, and logic on that memory
# Zero clock cycles just infers RAM primitives implemented in LUTS
# 1 clock means either input or output registers - should infer bram?
# 2 clocks means in and out regs - def BRAMable
# Build more complex multi cycle memory out of these basics - FutureJulian
# Ex. Start with RAM and per device resources fifo primitives, etc ....memory controllers? Next universe up Julian task
#   The Flaming Lips - Fight Test


# TODO MOVE TO WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE?
def GET_MEM_H_LOGIC_LOOKUP(parser_state):
    text = ""
    header_text = """
#include "uintN_t.h"
#include "intN_t.h"
  """

    # Use primitive mappings of funcs to func calls
    # parser_state.func_name_to_calls, parser_state.func_names_to_called_from
    # Need to indicate that these MEM functions have state registers globals/statics
    # HACK YHACK CHAKC
    func_name_to_state_reg_info = {}
    func_name_was_global_def = {}
    # _RAM_SP_RF
    # RAM_DP_RF_RF_2  MORE THAN ONE OUTPUT DATA NEEDS DUMB C STRUCT WRAPPER!!
    ram_types = []
    for ram_prefix in [LOGIC.RAM_SP_RF, LOGIC.RAM_DP_RF]:
        for ram_latency in range(0, 3):
            ram_type = ram_prefix + "_" + str(ram_latency)
            for (
                calling_func_name,
                called_func_names,
            ) in parser_state.func_name_to_calls.items():
                # Get local static var info for this func
                local_state_reg_info_dict = {}
                if calling_func_name in parser_state.func_to_local_state_regs:
                    local_state_reg_info_dict = parser_state.func_to_local_state_regs[
                        calling_func_name
                    ]
                    # for local_state_reg_info in local_state_reg_infos_dict.values():
                    #  local_state_reg_info_dict[local_state_reg_info.name] = local_state_reg_info
                for called_func_name in called_func_names:
                    if called_func_name.endswith(ram_type):
                        ram_func_name = called_func_name
                        var_name = ram_func_name.replace("_" + ram_type, "")
                        # print "var_name",var_name
                        # Lookup type, should be global/static, and array
                        c_type = None
                        # Local scope first
                        if var_name in local_state_reg_info_dict:
                            c_type = local_state_reg_info_dict[var_name].type_name
                            # BAAAHH locally typed/unique func name
                            # Mangle name to include calling func if local?
                            func_name = (
                                calling_func_name + "_" + var_name + "_" + ram_type
                            )
                            func_name_to_state_reg_info[func_name] = (
                                local_state_reg_info_dict[var_name]
                            )
                            func_name_was_global_def[func_name] = False
                        elif var_name in parser_state.global_vars:
                            c_type = parser_state.global_vars[var_name].type_name
                            func_name = var_name + "_" + ram_type
                            func_name_to_state_reg_info[func_name] = (
                                parser_state.global_vars[var_name]
                            )
                            func_name_was_global_def[func_name] = True
                        else:
                            print("Unknown RAM prim var", var_name)
                            sys.exit(-1)

                        if not LOGIC.C_TYPE_IS_ARRAY(c_type):
                            print("Ram function on non array?", ram_func_name)
                            sys.exit(-1)
                        elem_t, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                            c_type
                        )
                        # Multiple addresses now folks # Starfucker - Girls Just Want To Have
                        # dim = dims[0]
                        # addr_t = "uint" + str(int(math.ceil(math.log(dim,2)))) + "_t"

                        text += (
                            """
      // """
                            + ram_func_name
                            + """
      """
                        )
                        # In case type is actually user type - hacky
                        if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(elem_t, parser_state):
                            text += """typedef uint8_t """ + elem_t + ";\n"
                        # Declare global var that matches user
                        text += elem_t + """ """ + var_name
                        for dim in dims:
                            text += "[" + str(dim) + "]"
                        text += ";\n"
                        text += elem_t + " " + func_name + "("
                        if ram_type.startswith(LOGIC.RAM_SP_RF):
                            for i in range(0, len(dims)):
                                dim = dims[i]
                                addr_t = "uint" + str(INDEX_BIT_WIDTH(dim)) + "_t"
                                text += addr_t + " addr" + str(i) + ", "
                        elif ram_type.startswith(LOGIC.RAM_DP_RF):
                            for port_postfix in ["r", "w"]:
                                for i in range(0, len(dims)):
                                    dim = dims[i]
                                    addr_t = "uint" + str(INDEX_BIT_WIDTH(dim)) + "_t"
                                    text += (
                                        addr_t + " addr_" + port_postfix + str(i) + ", "
                                    )
                        else:
                            print("Unknown ram type:", ram_type)
                            sys.exit(-1)
                        # DONT ACTUALLY NEED/WANT IMPLEMENTATION FOR MEM SINCE 0 CLK IS BEST DONE/INFERRED AS RAW VHDL
                        text += (
                            elem_t
                            + " wd, uint1_t we)"
                            + """
      {
        /* 
        // Need C code and VHDL equivalents, do VHDL as __vhdl__ literal?
        */
      }
      """
                        )

    # print("MEM_HEADER_FILE")
    # print(text)
    # sys.exit(-1)

    if text != "":
        # Ok had some code, include headers
        text = header_text + text
        outfile = LOGIC.MEM_HEADER_FILE
        parser_state_copy = copy.copy(parser_state)  # was DEEPCOPY
        # Keep everything except logic stuff
        parser_state_copy.FuncLogicLookupTable = {}  # dict[func_name]=Logic() instance with just func info
        parser_state_copy.LogicInstLookupTable = {}  # dict[inst_name]=Logic() instance in full
        parser_state_copy.existing_logic = (
            LOGIC.Logic()
        )  # Temp working copy of logic ? idk it should work
        parse_body = False  # MEM DOES NOT HAVE SW IMPLEMENTATION
        FuncLogicLookupTable = (
            GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(
                text, outfile, parser_state_copy, parse_body
            )
        )

        # Apply hackyness
        for func_name in FuncLogicLookupTable:
            func_logic = FuncLogicLookupTable[func_name]
            var_info = func_name_to_state_reg_info[func_name]
            if func_name_was_global_def[func_name]:
                # Add global for this logic
                # print "RAM GLOBAL:",global_name
                parser_state_copy.existing_logic = func_logic
                func_logic = MAYBE_GLOBAL_DECL_TO_LOGIC(
                    var_info.name, parser_state_copy, is_lhs_assign=True
                )
                FuncLogicLookupTable[func_name] = func_logic
            elif not func_name_was_global_def[func_name]:
                # Copy into local special here similar to MAYBE_GLOBAL^ above
                # And special removing needing too?
                # Copy info into existing_logic
                func_logic.state_regs[var_info.name] = var_info
                func_logic.wire_to_c_type[var_info.name] = var_info.type_name
                func_logic.variable_names.add(var_info.name)
                # Record using globals
                if not func_logic.state_regs[var_info.name].is_volatile:
                    func_logic.uses_nonvolatile_state_regs = True
                    # print "rv.func_name",rv.func_name, rv.uses_nonvolatile_state_regs
                FuncLogicLookupTable[func_name] = func_logic

        return FuncLogicLookupTable

    else:
        # No code, no funcs
        return {}


def GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):
    text = ""
    header_text = """
#include "uintN_t.h"
#include "intN_t.h"
  """

    # Regex search c_text

    # Negate
    # Parse to list of width toks
    negate_func_names = []
    # uint24_negate(left_resized);
    for type_regex in [rf"uint[0-9]+_negate\s?\("]:  # DO int,float negate?
        p = re.compile(type_regex)
        negate_func_names = p.findall(c_text)
        negate_func_names = list(set(negate_func_names))
        for negate_func_name in negate_func_names:
            negate_func_name = negate_func_name.strip("(").strip()
            toks = negate_func_name.split("_")
            in_prefix = toks[0]
            in_width = int(in_prefix.replace("uint", ""))
            result_t = "int" + str(in_width + 1) + "_t"
            result_uint_t = "uint" + str(in_width + 1) + "_t"

            if type_regex == "float":
                print(" #DO int,float negate?")
                sys.exit(-1)
            else:
                in_t = in_prefix + "_t"

            func_name = in_prefix + "_negate"
            text += (
                """
// Negate
"""
                + result_t
                + " "
                + func_name
                + "("
                + in_t
                + """ x)
{
  // Twos comp
  
  """
                + result_uint_t
                + """ x_wide;
  x_wide = x;
  
  """
                + result_uint_t
                + """ x_wide_neg;
  x_wide_neg = ~x_wide;
  
  """
                + result_uint_t
                + """ x_neg_wide_plus1;
  x_neg_wide_plus1 = x_wide_neg + 1;
  
  """
                + result_t
                + """ rv;
  rv = x_neg_wide_plus1;
  
  return rv;
}
"""
            )

    # abs
    # Parse to list of width toks
    abs_func_names = []
    # int24_abs(left_resized);
    for type_regex in [rf"int[0-9]+_abs\s?\("]:  # Float abs is bit manip func
        p = re.compile(type_regex)
        abs_func_names = p.findall(c_text)
        abs_func_names = list(set(abs_func_names))
        for abs_func_name in abs_func_names:
            abs_func_name = abs_func_name.strip("(").strip()
            toks = abs_func_name.split("_")
            in_prefix = toks[0]
            in_width = int(in_prefix.replace("int", ""))
            sign_index = in_width - 1
            result_t = "uint" + str(in_width) + "_t"
            if type_regex == "float":
                print(" #DO float abs?")
                sys.exit(-1)
            else:
                in_t = in_prefix + "_t"

            func_name = in_prefix + "_abs"
            text += (
                """
#include "bit_manip.h"
      
// abs
"""
                + result_t
                + " "
                + func_name
                + "("
                + in_t
                + """ x)
{
  // Reverse twos comp?
  // Sub one and invert bits
  // Fine with condition since other way is something like  (x + (x >> 31)) ^ (x >> 31)
  // Which is dumb to do in SW
  
  // Get sign
  uint1_t sign;
  sign = """
                + in_prefix
                + """_"""
                + str(sign_index)
                + """_"""
                + str(sign_index)
                + """(x);
  
  // Get unsigned x
  """
                + result_t
                + """ x_uint;
  x_uint = x;
  
  // Minus 1
  """
                + result_t
                + """ x_uint_minus1;
  x_uint_minus1 = x_uint - 1;
  
  // Negate
  """
                + result_t
                + """ x_uint_minus1_neg;
  x_uint_minus1_neg = ~x_uint_minus1;
  
  """
                + result_t
                + """ rv;
  if(sign==1)
  {
    rv = x_uint_minus1_neg;
  }
  else
  {
    rv = x;
  }
  
  return rv;
}
"""
            )

    # N MUX
    # Parse to list of width toks
    nmux_func_names = []
    # uint24_mux24(sel, in0, in1,...);
    # print "DO any type NMUX"
    for type_regex in [rf"\w+_mux[0-9]+\s?\("]:
        p = re.compile(type_regex)
        nmux_func_names = p.findall(c_text)
        nmux_func_names = list(set(nmux_func_names))
        for nmux_func_name in nmux_func_names:
            nmux_func_name = nmux_func_name.strip("(").strip()
            # print "nmux_func_name",nmux_func_name
            # print c_text
            new_toks = nmux_func_name.split("_mux")
            mux_name = "mux" + new_toks[1]
            n = int(mux_name.replace("mux", ""))
            sel_width = INDEX_BIT_WIDTH(n)
            sel_t = "uint" + str(sel_width) + "_t"
            type_prefix = new_toks[0]

            # Ew TODO clean up naming - autogenerated funcs should always be <full_type_name>_funcname(
            # Change count0 to like lcount? rcount?
            # See if uint
            toks = type_prefix.split("int")
            if (
                len(toks) == 2
                and (toks[0] == "" or toks[0] == "u")
                and toks[1].isdigit()
            ):
                # uint special case, dumb
                type_name = type_prefix + "_t"
            else:
                type_name = type_prefix

            result_t = type_name
            in_t = type_name
            func_name = type_prefix + "_" + mux_name
            var_2_type = {}

            text += (
                """
#include "bit_manip.h"      
// """
                + str(nmux_func_name)
                + """
// """
                + str(n)
                + """ MUX\n"""
            )
            if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(result_t, parser_state):
                text += (
                    """
typedef uint8_t """
                    + result_t
                    + """; // FUCK
"""
                )
            text += result_t + " " + func_name + "(" + sel_t + """ sel,"""
            # List each input
            for i in range(0, n):
                text += in_t + " in" + str(i) + ","
            # Remove last comma
            text = text.strip(",")
            text += """)
{"""

            # Hierarchy of 2x1 muxes
            # Start with list of inputs
            layer = 0
            layer_nodes = []
            for i in range(0, n):
                layer_nodes.append("in" + str(i))

            # DO
            while True:
                text += (
                    """
  // Layer """
                    + str(layer)
                    + """
    """
                )
                # Get sel bit
                sel_var = "sel" + str(layer)
                text += (
                    """
  // Get sel bit
  uint1_t """
                    + sel_var
                    + """;
  """
                    + sel_var
                    + """ = uint"""
                    + str(sel_width)
                    + "_"
                    + str(layer)
                    + "_"
                    + str(layer)
                    + """(sel);
"""
                )
                node = 0
                new_layer_nodes = []
                # Write adds in pairs
                # While 2 args to add
                while len(layer_nodes) >= 2:
                    # Declare result of this mux
                    out_var = "layer" + str(layer) + "_node" + str(node)
                    text += (
                        """
  """
                        + result_t
                        + """ """
                        + out_var
                        + """;
  """
                    )
                    # Do the if
                    false_arg = layer_nodes.pop(0)
                    true_arg = layer_nodes.pop(0)

                    text += (
                        """// Do regular mux
  if("""
                        + sel_var
                        + """)
  {
    """
                        + out_var
                        + """ = """
                        + true_arg
                        + """;
  }
  else
  {
    """
                        + out_var
                        + """ = """
                        + false_arg
                        + """;
  }
  """
                    )

                    # This out node is on next layer
                    new_layer_nodes.append(out_var)
                    node += 1

                # Out of while loop
                # < 2 nodes left to sum in this node
                if len(layer_nodes) == 1:
                    # One node left
                    the_arg = layer_nodes.pop(0)
                    # Declare result of this mux
                    out_var = "layer" + str(layer) + "_node" + str(node)
                    text += (
                        """
  // Odd node in layer
  """
                        + result_t
                        + """ """
                        + out_var
                        + """;
  """
                        + out_var
                        + """ = """
                        + the_arg
                        + """;
  """
                    )
                    # This out node is on next layer
                    new_layer_nodes.append(out_var)
                    node += 1

                # WHILE
                if len(new_layer_nodes) >= 2:
                    # Continue
                    layer_nodes = new_layer_nodes
                    layer += 1
                else:
                    # DONE
                    break

            # Return last out var
            last_out_var = "layer" + str(layer) + "_node" + str(node - 1)
            text += (
                """ 
  return """
                + last_out_var
                + """;
}
"""
            )

    # print "MUX"
    # print text

    # count0 s
    # Parse to list of width toks
    count0_func_names = []
    # count0s_uint24(left_resized) # Count from left, uint24_count0s counts from right
    for type_regex in [rf"count0s_uint[0-9]+\s?\("]:
        p = re.compile(type_regex)
        count0_func_names = p.findall(c_text)
        count0_func_names = list(set(count0_func_names))
        for count0_func_name in count0_func_names:
            count0_func_name = count0_func_name.strip("(").strip()
            toks = count0_func_name.split("_")
            in_prefix = toks[1]
            in_t = in_prefix + "_t"
            in_width = int(in_prefix.replace("uint", ""))
            # Result width depends on width of input
            # DONT COUNT all zeros since shift after this wont change
            # Only need to count to in_width-1
            result_width = int(math.ceil(math.log(in_width, 2)))
            result_prefix = "uint" + str(result_width)
            result_t = result_prefix + "_t"
            func_name = count0_func_name

            # include "bit_manip.h"
            text += (
                """
      
// count0s from left
"""
                + result_t
                + " "
                + func_name
                + "("
                + in_t
                + """ x)
{
  // First do all the compares in parallel
  // All zeros has has many zeros as width
  uint1_t leading"""
                + str(in_width)
                + """ = (x==0);
  """
            )
            for leading_zeros in range(1, in_width):
                text += (
                    """
  uint1_t leading"""
                    + str(leading_zeros)
                    + """;
  leading"""
                    + str(leading_zeros)
                    + """ = """
                    + in_prefix
                    + """_"""
                    + str(in_width - 1)
                    + """_"""
                    + str(in_width - 1 - leading_zeros)
                    + """(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?"""
                )
            # SKIP SUM0 SINCE IS BY DEF 0
            var_2_type = {}
            for leading_zeros in range(1, in_width + 1):
                sum_width = int(math.ceil(math.log(leading_zeros + 1, 2)))
                sum_prefix = "uint" + str(sum_width)
                sum_t = sum_prefix + "_t"
                var = "sum" + str(leading_zeros)
                var_2_type[var] = sum_t
                text += (
                    """
  """
                    + sum_t
                    + """ """
                    + var
                    + """;
  if(leading"""
                    + str(leading_zeros)
                    + """)
  {
    """
                    + var
                    + """ = """
                    + str(leading_zeros)
                    + """;
  }
  else
  {
    """
                    + var
                    + """ = 0;
  }
  """
                )

            # This binary tree thing is weird?
            # Now do binary tree ORing all these single only one will be set
            # Fuck jsut copy from binary tree for mult
            text += """
  // Binary tree OR of "sums", can sine only one will be set
"""
            layer_nodes = []
            for p in range(1, in_width + 1):
                layer_nodes.append("sum" + str(p))

            layer = 0
            node = 0

            # DO
            while True:
                text += (
                    """
  // Layer """
                    + str(layer)
                    + """
"""
                )
                node = 0
                new_layer_nodes = []
                # Write adds in pairs
                # While 2 args to add
                while len(layer_nodes) >= 2:
                    left_arg = layer_nodes.pop(0)
                    right_arg = layer_nodes.pop(0)
                    left_t = var_2_type[left_arg]
                    right_t = var_2_type[right_arg]
                    # Sum type is max width
                    left_width = int(
                        left_t.replace("uint", "").replace("int", "").replace("_t", "")
                    )
                    right_width = int(
                        right_t.replace("uint", "").replace("int", "").replace("_t", "")
                    )
                    max_width = max(left_width, right_width)
                    or_width = max_width

                    sum_t = "uint" + str(or_width) + "_t"
                    sum_var = "sum_layer" + str(layer) + "_node" + str(node)
                    var_2_type[sum_var] = sum_t
                    text += (
                        """ """
                        + sum_t
                        + """ """
                        + sum_var
                        + """;
  """
                        + sum_var
                        + """ = """
                        + left_arg
                        + " | "
                        + right_arg
                        + """;
"""
                    )
                    # This sum node is on next layer
                    new_layer_nodes.append(sum_var)
                    node += 1

                # Out of while loop
                # < 2 nodes left to sum in this node
                if len(layer_nodes) == 1:
                    # One node left
                    the_arg = layer_nodes.pop(0)
                    the_t = var_2_type[the_arg]
                    sum_t = the_t
                    sum_var = "sum_layer" + str(layer) + "_node" + str(node)
                    var_2_type[sum_var] = sum_t
                    text += (
                        """ // Odd node in layer
  """
                        + sum_t
                        + """ """
                        + sum_var
                        + """;
  """
                        + sum_var
                        + """ = """
                        + the_arg
                        + """;
"""
                    )
                    # This sum node is on next layer
                    new_layer_nodes.append(sum_var)
                    node += 1

                # WHILE
                if len(new_layer_nodes) >= 2:
                    # Continue
                    layer_nodes = new_layer_nodes
                    layer += 1
                else:
                    # DONE
                    break

            # Done with outer layer while loop

            # Do return
            return_var = "sum_layer" + str(layer) + "_node" + str(node - 1)
            return_t = var_2_type[return_var]
            text += (
                """
  """
                + "// Return"
                + """
  """
                + return_t
                + """ rv;
  rv = """
                + return_var
                + """;
  return rv;
}
"""
            )

    # N Binary OP (sum, or, and, etc)
    # Also can work with arrays
    # Parse to list of width toks
    n_bin_op_func_names = []
    # uint24_sum24(left_resized);
    # TODO better regexs
    # TODO make full type _t in name not just uintN
    for type_regex in [
        "int[0-9]+",
        "int[0-9]+_array",
        "uint[0-9]+",
        "uint[0-9]+_array",
        "float",
        "float_array",
    ]:
        for op_regex in ["sum", "or", "and"]:
            regex = type_regex + "_" + op_regex + rf"[0-9]+\s?\("
            p = re.compile(regex)
            n_bin_op_func_names_w_paren = p.findall(c_text)
            n_bin_op_func_names_w_paren = list(set(n_bin_op_func_names_w_paren))
            for n_bin_op_func_name_w_paren in n_bin_op_func_names_w_paren:
                n_bin_op_func_name = n_bin_op_func_name_w_paren.strip("(").strip()
                # For now type strings dont include "_"
                # Get toks by splitting on "_"
                toks = n_bin_op_func_name.split("_")
                # Get type and array info
                in_elem_t_str = toks[0]
                is_array = False
                if len(toks) == 2:
                    # Not array
                    op_name = toks[1]
                else:
                    is_array = True
                    op_name = toks[2]

                # Get actual elem_t
                # Special case uint, dumb
                if in_elem_t_str == "float":
                    in_elem_t = "float"
                else:
                    # Assume u/int
                    in_elem_t = in_elem_t_str + "_t"

                # how many elements?
                n_elem = int(op_name.replace(op_regex, ""))
                # print "n_sum",n_sum

                # Result type?
                if in_elem_t == "float":
                    result_t = "float"
                else:
                    # Assume u/int
                    # Depends on op
                    if op_regex == "sum":
                        type_width = int(
                            in_elem_t_str.replace("uint", "").replace("int", "")
                        )
                        # Sum 2 would be bit width increase of 1
                        if in_elem_t.startswith("u"):
                            max_in_val = math.pow(2, type_width) - 1
                        else:
                            max_in_val = math.pow(2, type_width - 1)
                        max_sum = max_in_val * n_elem
                        result_width = int(math.ceil(math.log(max_sum + 1, 2)))
                        if in_elem_t.startswith("u"):
                            result_t = "uint" + str(result_width) + "_t"
                        else:
                            result_t = "int" + str(result_width + 1) + "_t"
                    elif op_regex == "or" or op_regex == "and":
                        # Result is same width as input
                        result_t = in_elem_t
                    else:
                        print("Whats32@#%?@#?todo bit widths for array op")
                        sys.exit(-1)

                # Keep track of variable type so
                # result type can be determined if needed
                var_2_type = {}

                # Start the code
                text += (
                    """
  #include "bit_manip.h"      
        
  // N binary op
  """
                    + result_t
                    + " "
                    + n_bin_op_func_name
                    + "("
                )
                # Input is either single array or many individual elements
                if is_array:
                    # Dont need to store array type in var_2_type
                    text += in_elem_t + " x" + "[" + str(n_elem) + "]"
                else:
                    # List each input elements
                    for i in range(0, n_elem):
                        text += in_elem_t + " x" + str(i) + ","
                        var_2_type["x" + str(i)] = in_elem_t
                    # Remove last comma
                    text = text.strip(",")

                # Finish def
                text += """)
  {"""

                # Do layers of simultaneous operations
                layer_nodes = []
                # Start with inputs
                if is_array:
                    for n in range(0, n_elem):
                        # Can use const ref string as "variable name"
                        var = "x[" + str(n) + "]"
                        layer_nodes.append(var)
                        var_2_type[var] = in_elem_t
                else:
                    for n in range(0, n_elem):
                        layer_nodes.append("x" + str(n))

                text += """
        // Binary tree
      """

                # Done as while loop
                layer = 0
                node = 0

                # DO
                while True:
                    text += (
                        """
        // Layer + """
                        + str(layer)
                        + """
      """
                    )
                    node = 0
                    new_layer_nodes = []
                    # Write ops in pairs
                    # While 2 args to do op to
                    while len(layer_nodes) >= 2:
                        left_arg = layer_nodes.pop(0)
                        right_arg = layer_nodes.pop(0)
                        left_t = var_2_type[left_arg]
                        right_t = var_2_type[right_arg]
                        # What is result of this op?
                        # Depends on type
                        if in_elem_t == "float":
                            op_result_t = "float"
                        else:
                            # Assume uint
                            # Depends on op
                            if op_regex == "sum":
                                # Sum type is max width+1
                                left_width = int(
                                    left_t.replace("uint", "")
                                    .replace("int", "")
                                    .replace("_t", "")
                                )
                                right_width = int(
                                    right_t.replace("uint", "")
                                    .replace("int", "")
                                    .replace("_t", "")
                                )
                                max_width = max(left_width, right_width)
                                sum_width = max_width + 1
                                op_result_t = "uint" + str(sum_width) + "_t"
                            elif op_regex == "or" or op_regex == "and":
                                # Result is same width as input
                                op_result_t = in_elem_t
                            else:
                                print("Whats32?")
                                sys.exit(-1)

                        op_var = "layer" + str(layer) + "_node" + str(node)
                        var_2_type[op_var] = op_result_t
                        # Determine C operator
                        op_char = None
                        if op_regex == "sum":
                            op_char = "+"
                        elif op_regex == "and":
                            op_char = "&"
                        elif op_regex == "or":
                            op_char = "|"
                        else:
                            print(0 / 0)

                        text += (
                            """ """
                            + op_result_t
                            + """ """
                            + op_var
                            + """;
        """
                            + op_var
                            + """ = """
                            + left_arg
                            + " "
                            + op_char
                            + " "
                            + right_arg
                            + """;
      """
                        )
                        # This op node is on next layer
                        new_layer_nodes.append(op_var)
                        node += 1

                    # Out of while loop
                    # < 2 nodes left to operate on in this node
                    if len(layer_nodes) == 1:
                        # One node left
                        the_arg = layer_nodes.pop(0)
                        the_t = var_2_type[the_arg]
                        op_result_t = the_t
                        op_var = "layer" + str(layer) + "_node" + str(node)
                        var_2_type[op_var] = op_result_t
                        text += (
                            """ // Odd node in layer
        """
                            + op_result_t
                            + """ """
                            + op_var
                            + """;
        """
                            + op_var
                            + """ = """
                            + the_arg
                            + """;
        """
                        )
                        # This sum node is on next layer
                        new_layer_nodes.append(op_var)
                        node += 1

                    # WHILE
                    if len(new_layer_nodes) >= 2:
                        # Continue
                        layer_nodes = new_layer_nodes
                        layer += 1
                    else:
                        # DONE
                        break

                # Done with outer layer while loop

                # Do return
                return_var = "layer" + str(layer) + "_node" + str(node - 1)
                return_t = var_2_type[return_var]
                text += (
                    """
        """
                    + "// Return"
                    + """
        """
                    + return_t
                    + """ rv;
        rv = """
                    + return_var
                    + """;
        return rv;
      }
      """
                )

    # print("BIT_MATH_HEADER_FILE")
    # print(text)

    if text != "":
        # Ok had some code, include headers
        text = header_text + text

        outfile = LOGIC.BIT_MATH_HEADER_FILE
        parser_state_copy = copy.copy(parser_state)  # was DEEPCOPY()
        # Keep everything except logic stuff
        parser_state_copy.FuncLogicLookupTable = {}  # dict[func_name]=Logic() instance with just func info
        parser_state_copy.LogicInstLookupTable = {}  # dict[inst_name]=Logic() instance in full
        parser_state_copy.existing_logic = (
            LOGIC.Logic()
        )  # Temp working copy of logic ? idk it should work

        ## NEED MANIP in MATH

        # C TEXT NAME BASED
        bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(
            text, parser_state
        )  # DEPENDS ON BIT MANIP # TODO: How to handle dependencies
        parser_state_copy.FuncLogicLookupTable = bit_manip_func_name_logic_lookup  # {}

        # Try to get all built in? not just manip? Recursive is nice?
        # print("preprocessed_text",preprocessed_text)
        # parser_state_copy.FuncLogicLookupTable = GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(preprocessed_text, parser_state_copy) #parser_state??

        parse_body = True  # BIT MATH IS SW IMPLEMENTATION
        FuncLogicLookupTable = (
            GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(
                text, outfile, parser_state_copy, parse_body
            )
        )

        for func_name in FuncLogicLookupTable:
            func_logic = FuncLogicLookupTable[func_name]
            if len(func_logic.wire_drives) == 0 and str(
                func_logic.c_ast_node.coord
            ).split(":")[0].endswith(LOGIC.BIT_MATH_HEADER_FILE):
                print("BIT_MATH_HEADER_FILE")
                print(text)
                print("Bad parsing of BIT MATH", func_name)
                sys.exit(-1)

        return FuncLogicLookupTable

    else:
        # No code, no funcs
        return {}


def BIT_SEL_FUNC_TO_INPUTS_TYPES_OUTPUT_TYPE(bit_sel_func_name):
    toks = bit_sel_func_name.split("_")
    if len(toks) == 3:
        high = int(toks[1])
        low = int(toks[2])
        in_prefix = toks[0]
        if in_prefix == "float":
            in_t = "float"
        else:
            in_t = in_prefix + "_t"
        func_name = in_prefix + "_" + str(high) + "_" + str(low)
        # Catch reverse
        if high < low:
            temp = low
            low = high
            high = temp
        result_width = high - low + 1
        result_t = "uint" + str(result_width) + "_t"
    else:
        # New float_e_m_t_#_#
        high = int(toks[4])
        low = int(toks[5])
        in_t = "_".join(toks[0:4])
        result_width = high - low + 1
        result_t = "uint" + str(result_width) + "_t"
    return (["x"], [in_t], result_t)


def GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):
    # TODO: Do bit select and bit dup as "const int"?

    text = ""
    header_text = """
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
  """

    # Regex search c_text
    # Bit select
    # Parse to list of width toks
    bit_sel_func_names = []
    # uint64_39_39(input);
    for type_regex in [f"uint[0-9]+", "int[0-9]+", "float", "float_[0-9]+_[0-9]+_t"]:
        p = re.compile(type_regex + rf"_[0-9]+_[0-9]+\s?\(")
        bit_sel_func_names = p.findall(c_text)
        bit_sel_func_names = list(set(bit_sel_func_names))
        # Need bit concat and bit select
        # BIT SELECT
        # uint16_t uintX_15_0(uintX_t)
        for bit_sel_func_name in bit_sel_func_names:
            bit_sel_func_name = bit_sel_func_name.strip("(").strip()
            (
                input_port_names,
                input_types,
                result_t,
            ) = BIT_SEL_FUNC_TO_INPUTS_TYPES_OUTPUT_TYPE(bit_sel_func_name)
            # Only one input
            text += (
                """
// BIT SELECT
"""
                + result_t
                + " "
                + bit_sel_func_name
                + "("
                + input_types[0]
                + " "
                + input_port_names[0]
                + """)
{
  //TODO
}
"""
            )

    # BIT CONCAT
    # Parse to list of width toks
    bit_concat_func_names = []
    # uint64_uint15
    p = re.compile(rf"u?int[0-9]+_u?int[0-9]+\s?\(")
    bit_concat_func_names = p.findall(c_text)
    bit_concat_func_names = list(set(bit_concat_func_names))
    # uint5_t uint2_uint3(uint2 x, uint3 y)
    for bit_concat_func_name in bit_concat_func_names:
        bit_concat_func_name = bit_concat_func_name.strip("(").strip()
        toks = bit_concat_func_name.split("_")
        first_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
        second_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
        result_width = first_bit_width + second_bit_width
        result_t = "uint" + str(result_width) + "_t"
        first_in_prefix = toks[0]
        first_in_t = first_in_prefix + "_t"
        second_in_prefix = toks[1]
        second_in_t = second_in_prefix + "_t"
        func_name = first_in_prefix + "_" + second_in_prefix
        text += (
            """
// BIT CONCAT
"""
            + result_t
            + " "
            + func_name
            + "("
            + first_in_t
            + " x, "
            + second_in_t
            + """ y)
{
  //TODO
}
"""
        )

    # BITS DUP
    # Parse to list of width toks
    bit_dup_func_names = []
    # uint64_5
    p = re.compile(rf"[^_][u?]int[0-9]+_[0-9]+\s?\(")
    bit_dup_func_names = p.findall(c_text)
    bit_dup_func_names = list(set(bit_dup_func_names))
    # Questionable seems OK naming convention?
    # uint(X*15)_t uintX_15(uintX_t)
    # hacky dont match bit bit_sel_func_names
    for bit_dup_func_name in bit_dup_func_names:
        # if not(bit_dup_func_name in bit_sel_func_names):
        bit_dup_func_name = bit_dup_func_name.strip("(").strip()
        toks = bit_dup_func_name.split("_")
        input_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
        mult = int(toks[1])
        if mult == 0:
            continue
        result_width = input_bit_width * mult
        result_t = "uint" + str(result_width) + "_t"
        in_prefix = toks[0]
        in_t = in_prefix + "_t"
        func_name = in_prefix + "_" + str(mult)
        text += (
            """
// BIT DUP
"""
            + result_t
            + " "
            + in_prefix
            + "_"
            + str(mult)
            + "("
            + in_t
            + """ x)
{
  //TODO
}
"""
        )

    # Rotate left
    # Parse to list of width toks
    rotl_func_names = []
    p = re.compile(rf"[^_]rotl[0-9]+_[0-9]+\s?\(")
    rotl_func_names = p.findall(c_text)
    rotl_func_names = list(set(rotl_func_names))
    for rotl_func_name in rotl_func_names:
        rotl_func_name = rotl_func_name.strip("(").strip()
        # print("rotl_func_name",rotl_func_name)
        toks = rotl_func_name.split("_")
        in_prefix = "uint" + toks[0].replace("rotl", "")
        in_t = in_prefix + "_t"
        input_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_t)
        rot_amount = int(toks[1])
        result_width = input_bit_width
        result_t = "uint" + str(result_width) + "_t"
        func_name = "rotl" + str(input_bit_width) + "_" + str(rot_amount)
        text += (
            """
// BIT ROTL
"""
            + result_t
            + " "
            + func_name
            + "("
            + in_t
            + """ x)
{
  //TODO
}
"""
        )

    # Rotate right
    # Parse to list of width toks
    rotr_func_names = []
    p = re.compile(rf"[^_]rotr[0-9]+_[0-9]+\s?\(")
    rotr_func_names = p.findall(c_text)
    rotr_func_names = list(set(rotr_func_names))
    for rotr_func_name in rotr_func_names:
        rotr_func_name = rotr_func_name.strip("(").strip()
        # print("rotr_func_name",rotr_func_name)
        toks = rotr_func_name.split("_")
        in_prefix = "uint" + toks[0].replace("rotr", "")
        in_t = in_prefix + "_t"
        input_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_t)
        rot_amount = int(toks[1])
        result_width = input_bit_width
        result_t = "uint" + str(result_width) + "_t"
        func_name = "rotr" + str(input_bit_width) + "_" + str(rot_amount)
        text += (
            """
// BIT ROTR
"""
            + result_t
            + " "
            + func_name
            + "("
            + in_t
            + """ x)
{
  //TODO
}
"""
        )

    # Constant index assignment with N bits
    # Otherwise large slv is like ram lookup
    # Parse to list of width toks
    bit_ass_func_names = []
    # uint64_uint15_2(uint64_t in, uint15_t x)  // out = in; out(16 downto 2) = x
    p = re.compile(rf"u?int[0-9]+_uint[0-9]+_[0-9]+\s?\(")
    bit_ass_func_names = p.findall(c_text)
    bit_ass_func_names = list(set(bit_ass_func_names))
    for bit_ass_func_name in bit_ass_func_names:
        bit_ass_func_name = bit_ass_func_name.strip("(").strip()
        toks = bit_ass_func_name.split("_")
        input_bit_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
        assign_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
        low_index = int(toks[2])
        high_index = low_index + assign_width - 1
        result_width = input_bit_width
        in_prefix = toks[0]
        in_t = in_prefix + "_t"
        result_t = in_t
        x_prefix = toks[1]
        x_t = x_prefix + "_t"
        func_name = bit_ass_func_name
        text += (
            """
// CONST BIT ASSIGNMENT
"""
            + result_t
            + " "
            + func_name
            + "("
            + in_t
            + """ inp, """
            + x_t
            + """ x)
{
  //TODO
}
"""
        )

    # Float SEM construction
    # Regex search c_text
    # Parse to list of width toks
    float_const_func_names = []
    # float_1_8_23(left_resized);
    for type_regex in [f"float"]:
        p = re.compile(type_regex + rf"_uint[0-9]+_uint[0-9]+\s?\(")
        float_const_func_names = p.findall(c_text)
        float_const_func_names = list(set(float_const_func_names))
        for float_const_func_name in float_const_func_names:
            float_const_func_name = float_const_func_name.strip("(").strip()
            toks = float_const_func_name.split("_")
            s_prefix = "uint1"
            s_t = s_prefix + "_t"
            e_prefix = toks[1]
            e_t = e_prefix + "_t"
            m_prefix = toks[2]
            m_t = m_prefix + "_t"
            result_t = (
                "float_"
                + str(e_prefix.replace("uint", ""))
                + "_"
                + str(m_prefix.replace("uint", ""))
                + "_t"
            )
            func_name = float_const_func_name
            text += (
                """
// FLOAT SEM CONSTRUCT
"""
                + result_t
                + " "
                + float_const_func_name
                + "("
                + s_t
                + """ sign, """
                + e_t
                + """ exponent, """
                + m_t
                + """ mantissa)
{
  //TODO
}
"""
            )

    # Float UINT32 construction ... bleh ... implement unions?
    # Regex search c_text
    # Parse to list of width toks
    float_const_func_names = []
    # float_uint32(in);
    for type_regex in [f"float", "float_[0-9]+_[0-9]+_t"]:
        p = re.compile(type_regex + rf"_uint[0-9]+\s?\(")
        float_const_func_names = p.findall(c_text)
        float_const_func_names = list(set(float_const_func_names))
        for float_const_func_name in float_const_func_names:
            float_const_func_name = float_const_func_name.strip("(").strip()
            toks = float_const_func_name.split("_")
            if len(toks) == 2:
                in_prefix = toks[1]
                in_t = in_prefix + "_t"
                result_t = type_regex
            else:
                in_prefix = toks[4]
                in_t = in_prefix + "_t"
                result_t = "float_" + toks[1] + "_" + toks[2] + "_t"

            text += (
                """
// FLOAT UINT32
"""
                + result_t
                + " "
                + float_const_func_name
                + "("
                + in_t
                + """ x)
{
  //TODOs
}
"""
            )

    # Float abs, just clear sign bit
    # Regex search c_text
    # Parse to list of width toks
    float_const_func_names = []
    # float_abs(in);
    for type_regex in [f"float", "float_[0-9]+_[0-9]+_t"]:
        p = re.compile(type_regex + rf"_abs\s?\(")
        float_const_func_names = p.findall(c_text)
        float_const_func_names = list(set(float_const_func_names))
        for float_const_func_name in float_const_func_names:
            float_const_func_name = float_const_func_name.strip("(").strip()
            toks = float_const_func_name.split("_")
            if len(toks) == 2:
                # float
                in_t = type_regex
                result_t = in_t
            else:
                # float_e_m_t
                in_t = "float_" + toks[1] + "_" + toks[2] + "_t"
                result_t = in_t

            text += (
                """
// FLOAT ABS
"""
                + result_t
                + " "
                + float_const_func_name
                + "("
                + in_t
                + """ x)
{
  //TODO
}
"""
            )

    # Float sign, just return sign bit
    # Regex search c_text
    float_const_func_names = []
    # float_sign(in);
    for type_regex in [f"float", "float_[0-9]+_[0-9]+_t"]:
        p = re.compile(type_regex + rf"_sign\s?\(")
        float_const_func_names = p.findall(c_text)
        float_const_func_names = list(set(float_const_func_names))
        for float_const_func_name in float_const_func_names:
            float_const_func_name = float_const_func_name.strip("(").strip()
            toks = float_const_func_name.split("_")
            if len(toks) == 2:
                # float
                in_t = type_regex
            else:
                # float_e_m_t
                in_t = "float_" + toks[1] + "_" + toks[2] + "_t"

            text += (
                """
// FLOAT SIGN
"""
                + "uint1_t"
                + " "
                + float_const_func_name
                + "("
                + in_t
                + """ x)
{
  //TODO
}
"""
            )

    # Byte swap, with same name as real C func
    # Parse to list of width toks
    bswap_func_names = []
    p = re.compile(rf"bswap_[0-9]+\s?\(")
    bswap_func_names = p.findall(c_text)
    bswap_func_names = list(set(bswap_func_names))
    for bswap_func_name in bswap_func_names:
        bswap_func_name = bswap_func_name.strip("(").strip()
        toks = bswap_func_name.split("_")
        input_bit_width = int(toks[1])
        result_width = input_bit_width
        result_t = "uint" + str(result_width) + "_t"
        in_prefix = "uint" + str(input_bit_width)
        in_t = in_prefix + "_t"
        func_name = bswap_func_name
        text += (
            """
// BYTE SWAP
"""
            + result_t
            + " "
            + func_name
            + "("
            + in_t
            + """ x)
{
  //TODO
}
"""
        )

    # Array to unsigned
    # uint1024_t uint8_array128_be/le(uint8_t x[128])
    # Need big and little endian
    # Dont do casting since endianess makes everyone sad
    # C doesnt support casting like that anyway
    array_to_unsigned_func_names = []
    p = re.compile(rf"uint[0-9]+_array[0-9]+_(?:be|le)\s?\(")
    array_to_unsigned_func_names = p.findall(c_text)
    array_to_unsigned_func_names = list(set(array_to_unsigned_func_names))
    # print "array_to_unsigned_func_names",array_to_unsigned_func_names
    # if len(array_to_unsigned_func_names) > 0:
    # print "c_text"
    for array_to_unsigned_func_name in array_to_unsigned_func_names:
        array_to_unsigned_func_name = array_to_unsigned_func_name.strip("(").strip()
        toks = array_to_unsigned_func_name.split("_")
        elem_width = int(toks[0].replace("uint", ""))
        elem_t = toks[0] + "_t"
        dim = int(toks[1].replace("array", ""))
        result_width = elem_width * dim
        result_t = "uint" + str(result_width) + "_t"
        func_name = array_to_unsigned_func_name
        text += (
            """
// ARRAY TO UNSIGNED
"""
            + result_t
            + " "
            + func_name
            + "("
            + elem_t
            + """ x["""
            + str(dim)
            + """])
{
  //TODO
}
"""
        )

    # unsigned to array
    # uint8_t[128] be/le_uint8_array128(uint1024_t
    # Dont do for now since not needed yet and involves dumb return of array in struct
    # Want uint8*4_t[N/4] = uint8_arrayN_by_4_le(uint8_t x[N]) but can be done with unsigned to/from array
    # ITS TIME TO BE SHITTY?

    if text != "":
        # Ok had some code, include headers
        text = header_text + text

        # print("BIT_MANIP_HEADER_FILE")
        # print(text,flush=True)

        # Just bit manip for now
        outfile = LOGIC.BIT_MANIP_HEADER_FILE
        # "GET_SW_FUNC_NAME_LOGIC_LOOKUP outfile",outfile

        # Parse the c doe to logic lookup
        parser_state_copy = copy.copy(parser_state)  # was DEEPCOPY
        # Keep everything except logic stuff
        parser_state_copy.FuncLogicLookupTable = {}  # dict[func_name]=Logic() instance with just func info
        parser_state_copy.LogicInstLookupTable = {}  # dict[inst_name]=Logic() instance in full
        parser_state_copy.existing_logic = (
            LOGIC.Logic()
        )  # Temp working copy of logic ? idk it should work
        parse_body = False  # SINCE BIT MANIP IGNORES SW IMPLEMENTATION
        FuncLogicLookupTable = (
            GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(
                text, outfile, parser_state_copy, parse_body
            )
        )

        # All of these funcs are vhdl funcs
        for func_name in FuncLogicLookupTable:
            FuncLogicLookupTable[func_name].is_vhdl_func = True

        return FuncLogicLookupTable
    else:
        # No code, no funcs
        return {}


def GET_CAST_C_CODE(
    partially_complete_logic, containing_func_logic, out_dir, parser_state
):
    input_wire = partially_complete_logic.inputs[0]
    in_t = partially_complete_logic.wire_to_c_type[input_wire]
    output_wire = partially_complete_logic.outputs[0]
    out_t = partially_complete_logic.wire_to_c_type[output_wire]
    if LOGIC.C_TYPE_IS_FLOAT_TYPE(in_t) and LOGIC.C_TYPE_IS_INT_N(out_t):
        return GET_CAST_FLOAT_TO_INT_C_CODE(
            partially_complete_logic, containing_func_logic, out_dir, parser_state
        )
    elif LOGIC.C_TYPES_ARE_INTEGERS([in_t]) and LOGIC.C_TYPE_IS_FLOAT_TYPE(out_t):
        return GET_CAST_INT_UINT_TO_FLOAT_C_CODE(
            partially_complete_logic, containing_func_logic, out_dir, parser_state
        )
    else:
        print("Implement more casting: Easy/Lucky/Free Bright Eyes")
        print(in_t, out_t, partially_complete_logic.c_ast_node.coord)
        sys.exit(-1)


def GET_UNARY_OP_NEGATE_C_CODE(
    partially_complete_logic, containing_func_logic, out_dir, parser_state
):
    input_wire = partially_complete_logic.inputs[0]
    in_t = partially_complete_logic.wire_to_c_type[input_wire]
    if LOGIC.C_TYPES_ARE_INTEGERS([in_t]):
        return GET_UNARY_OP_NEGATE_INT_UINT_C_CODE(
            partially_complete_logic, containing_func_logic, out_dir, parser_state
        )
    else:
        print("Implement more negate: ABBA - Dancing Queen")
        print(in_t, out_t, partially_complete_logic.c_ast_node.coord)
        sys.exit(-1)


def GET_UNARY_OP_NEGATE_INT_UINT_C_CODE(
    partially_complete_logic, containing_func_logic, out_dir, parser_state
):
    input_wire = partially_complete_logic.inputs[0]
    in_t = partially_complete_logic.wire_to_c_type[input_wire]
    in_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(in_t)
    is_int = LOGIC.C_TYPE_IS_INT_N(in_t)
    result_t = "int" + str(in_width + 1) + "_t"
    result_uint_t = "uint" + str(in_width + 1) + "_t"

    text = ""
    text += (
        """
#include "intN_t.h"
#include "uintN_t.h"
// Negate
"""
        + result_t
        + " "
        + partially_complete_logic.func_name
        + "("
        + in_t
        + """ expr)
{
  // Twos comp
  
  """
        + result_uint_t
        + """ x_wide;
  x_wide = expr;
  
  """
        + result_uint_t
        + """ x_wide_neg;
  x_wide_neg = ~x_wide;
  
  """
        + result_uint_t
        + """ x_neg_wide_plus1;
  x_neg_wide_plus1 = x_wide_neg + 1;
  
  """
        + result_t
        + """ rv;
  rv = x_neg_wide_plus1;
  
  return rv;
}
"""
    )

    return text


def GET_CAST_INT_UINT_TO_FLOAT_C_CODE(
    partially_complete_logic, containing_func_logic, out_dir, parser_state
):
    # Int to float
    input_wire = partially_complete_logic.inputs[0]
    in_t = partially_complete_logic.wire_to_c_type[input_wire]
    input_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(in_t)
    is_int = LOGIC.C_TYPE_IS_INT_N(in_t)
    output_wire = partially_complete_logic.outputs[0]
    out_t = partially_complete_logic.wire_to_c_type[output_wire]
    fp_t = out_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    text = ""
    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MATH_HEADER_FILE
        + """"
#include "float_e_m_t.h"

// CAST
"""
        + out_t
        + " "
        + partially_complete_logic.func_name
        + "("
        + in_t
        + """ rhs)
{
  // Building SEM to return
  """
        + mantissa_t
        + """ mantissa;
  """
        + exponent_t
        + """ biased_exponent;
  """
        + sign_t
        + """ sign;
  
  // Special case zero
  """
        + out_t
        + """ rv;
  if(rhs==0)
  {
    rv = float_"""
        + exponent_t_prefix
        + "_"
        + mantissa_t_prefix
        + """(0,0,0);
  }
  else
  {
  """
    )

    unsigned_t = "uint" + str(input_width) + "_t"
    if is_int:
        # Integer
        text += (
            """ 
    // Record sign
    sign = int"""
            + str(input_width)
            + "_"
            + str(input_width - 1)
            + "_"
            + str(input_width - 1)
            + """(rhs);
    // Take abs value
  """
            + unsigned_t
            + """ unsigned_rhs;
    unsigned_rhs = int"""
            + str(input_width)
            + """_abs(rhs);\n"""
        )
    else:
        # Unsigned
        text += (
            """ 
    // Record sign
    sign = 0;
    // Abs value is just rhs
    """
            + unsigned_t
            + """ unsigned_rhs;
    unsigned_rhs = rhs;\n"""
        )

    # Count leading zeros
    num_zeros_bits = int(math.ceil(math.log(input_width + 1, 2)))
    num_zeros_t = "uint" + str(num_zeros_bits) + "_t"
    text += (
        """
    // Count leading zeros
    """
        + num_zeros_t
        + """ num_zeros;
    num_zeros = count0s"""
        + "_uint"
        + str(input_width)
        + """(unsigned_rhs);"""
    )

    # Shift all the way left plus 1 to drop upper most bit
    shift_t = "uint" + str(num_zeros_bits + 1) + "_t"
    text += (
        """
    // Shift all the way left plus 1 to drop upper most bit
    """
        + shift_t
        + """ shift;
    shift = num_zeros + 1;
    """
        + unsigned_t
        + """ shifted_unsigned_rhs;
    shifted_unsigned_rhs = unsigned_rhs << shift;"""
    )

    # Might need to append zeros to right if rhs is smaller than mantissa
    if input_width < mantissa_width:
        # Increase width
        maybe_resized_width = mantissa_width
        maybe_resized_rhs_t = "uint" + str(maybe_resized_width) + "_t"
        # Pad right with zeros
        pad_size = mantissa_width - input_width
        text += (
            """
      // Pad right with zeros
      """
            + maybe_resized_rhs_t
            + """ maybe_resized_rhs;
      maybe_resized_rhs = uint"""
            + str(input_width)
            + "_uint"
            + str(pad_size)
            + """(shifted_unsigned_rhs, 0);"""
        )
    else:
        # No resize
        maybe_resized_width = input_width
        maybe_resized_rhs_t = "uint" + str(maybe_resized_width) + "_t"
        text += (
            """
      // No resize
      """
            + maybe_resized_rhs_t
            + """ maybe_resized_rhs;
      maybe_resized_rhs = shifted_unsigned_rhs;"""
        )

    # Take mantissa from upper bits
    top_index = maybe_resized_width - 1
    bottom_index = top_index - mantissa_width + 1
    text += (
        """
    // Take mantissa from upper bits
    mantissa = uint"""
        + str(maybe_resized_width)
        + "_"
        + str(top_index)
        + "_"
        + str(bottom_index)
        + """(maybe_resized_rhs);"""
    )

    # Exponent depends on position of leading zero in original number
    # Use that to calculate bit width needed
    text += (
        """
    // Exponent depends on shift
    // All zeros = leading zeros = width, shift=width+1
    if(shift == """
        + str(input_width + 1)
        + """)
    {
      biased_exponent = 0;
    }
    else
    {
      // Normal non zero case
      """
        + exponent_t
        + """ exponent;
      exponent = """
        + str(input_width)
        + """ - shift;
      // Add bias
      biased_exponent = exponent + """
        + str(exponent_bias)
        + """;
    }"""
    )

    # Construct float to return
    text += (
        """
    rv = float_"""
        + exponent_t_prefix
        + "_"
        + mantissa_t_prefix
        + """(sign, biased_exponent, mantissa);
  }
  
  return rv;
}"""
    )

    # print(text)
    return text


def GET_CAST_FLOAT_TO_INT_C_CODE(
    partially_complete_logic, containing_func_logic, out_dir, parser_state
):
    func_name = partially_complete_logic.func_name

    # Float to int
    input_wire = partially_complete_logic.inputs[0]
    in_t = partially_complete_logic.wire_to_c_type[input_wire]
    output_wire = partially_complete_logic.outputs[0]
    out_t = partially_complete_logic.wire_to_c_type[output_wire]
    fp_t = in_t
    # I HATE TWOS COMPLEMENT   # A Day In The Life - The Beatles

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    text = ""
    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MATH_HEADER_FILE
        + """"
#include "float_e_m_t.h"

// CAST
"""
        + out_t
        + " "
        + func_name
        + "("
        + in_t
        + """ rhs)
{
  // Break into SEM
  """
        + mantissa_t
        + """ mantissa;
  mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(rhs);
  """
        + exponent_t
        + """ biased_exponent;
  biased_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(rhs);
  """
        + sign_t
        + """ sign;
  sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(rhs);
  
  """
        + out_t
        + """ rv;
  // Special case zero
  if((mantissa==0) & (biased_exponent==0))
  {
    rv = 0;
  }
  else
  {
  """
    )

    # Get real unbiased exponent
    signed_exponent_t = "int" + str(exponent_width_plus1) + "_t"
    unbiased_exponent_t = "int" + str(exponent_width) + "_t"
    text += (
        """
    """
        + signed_exponent_t
        + """ signed_biased_exponent;
    signed_biased_exponent = biased_exponent;
    """
        + unbiased_exponent_t
        + """ unbiased_exponent;
    unbiased_exponent = signed_biased_exponent - """
        + str(exponent_bias)
        + """;"""
    )

    # Append the 1 in front of the manitissa
    mantissa_width_plus_1 = mantissa_width + 1
    mantissa_normalized_t = "uint" + str(mantissa_width_plus_1) + "_t"
    text += (
        """
    """
        + mantissa_normalized_t
        + """ mantissa_normalized;
    mantissa_normalized = uint1_"""
        + mantissa_t_prefix
        + """(1, mantissa);"""
    )

    # 24th bit is 1 so need to include that when shifting
    # Output width of cast limits how far we should bother shifting before overflowing into undefined output
    # Casting to int so actual unsigned width is less
    out_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(out_t)
    unsigned_width = out_width - 1
    total_shift_max = unsigned_width
    shift_bit_size = int(math.ceil(math.log(total_shift_max + 1, 2.0)))
    shift_t = "uint" + str(shift_bit_size) + "_t"
    interm_size = mantissa_width_plus_1 + unsigned_width
    interm_prefix = "uint" + str(interm_size)
    interm_t = interm_prefix + "_t"
    # Extend mantissa with zeros
    text += (
        """
    """
        + interm_t
        + """ interm;
    interm = mantissa_normalized;"""
    )
    # Shift mantissa with hidden bit if greater or equal to 0 and up a limit
    text += (
        """
    if( (unbiased_exponent >= 0) & (unbiased_exponent <= """
        + str(total_shift_max)
        + """) )
    {
      """
        + shift_t
        + """ shift;
      shift = unbiased_exponent;
      interm = interm << shift;
    }else if(unbiased_exponent < 0) // Round to zero?
    {
      interm = 0;
    }"""
    )

    # Take result from top of shifted interm mantissa
    top_index = interm_size - 1
    bottom_index = mantissa_width
    unsigned_result_prefix = "uint" + str(unsigned_width)
    unsigned_result_t = unsigned_result_prefix + "_t"
    text += (
        """
    """
        + unsigned_result_t
        + """ unsigned_result;
    unsigned_result = """
        + interm_prefix
        + "_"
        + str(top_index)
        + "_"
        + str(bottom_index)
        + """(interm);"""
    )

    # Negate if necessary
    text += (
        """
  
    rv = unsigned_result;
    if(sign)
    {
      rv = """
        + unsigned_result_prefix
        + """_negate(unsigned_result);
    }
  
  }
  
  return rv;
}
"""
    )

    return text


def GET_ONE_HOT_EQ_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    containing_func_logic,
    parser_state,
):
    func_c_name = partially_complete_logic.func_name
    # Assumes both inputs are same type
    input_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[0]
    ]
    bit_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(input_t)
    text = ""
    text += '''
#include "intN_t.h"
#include "uintN_t.h"'''
    ##include "'''
    #        + BIT_MATH_HEADER_FILE
    #        + """"
    # """
    text += (
        """
uint1_t """
        + func_c_name
        + """("""
        + input_t
        + """ left, """
        + input_t
        + """ right)
{
    // Bitwise and
    """
        + input_t
        + """ left_and_right = left & right;
    uint1_t bits["""
        + str(bit_width)
        + """];
    uint32_t i;
    for(i=0; i<"""
        + str(bit_width)
        + """; i+=1)
    {
        bits[i] = left_and_right(i); // Select ith bit
    } 
    // OR reduce with built in function
    return uint1_array_or"""
        + str(bit_width)
        + """(bits);
}
    """
    )
    return text


### Ahh fuck taking the easy way
# Copying implemetnation from     GET_VAR_REF_ASSIGN_C_CODE
# Might actually be worth it
def GET_VAR_REF_RD_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    containing_func_logic,
    out_dir,
    parser_state,
):
    debug = False
    # @@@@ Need to solve can't reutnr arry and any type NMUX name problem (struct_t_muxN name?)
    ## Fuck need to put array in struct
    # Then need to allow cast from struct wray to array type in VHDL?

    ref_toks = containing_func_logic.ref_submodule_instance_to_ref_toks[
        partially_complete_logic_local_inst_name
    ]
    orig_var_name = ref_toks[0]

    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]

    func_c_name = partially_complete_logic.func_name

    # First need to assign ref tokens into type matching BASE
    # Get base var name + type from any of the inputs

    # base_c_type = containing_func_logic.wire_to_c_type[orig_var_name_inst_name]
    base_c_type = containing_func_logic.wire_to_c_type[orig_var_name]
    base_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(
        base_c_type, parser_state
    )  # Structs handled and have same name as C types

    text = ""

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MATH_HEADER_FILE
        + """"
"""
    )
    # Do type defs for input structs and output array (if output is array)
    # And base type too
    for input_wire in partially_complete_logic.inputs:
        input_t = partially_complete_logic.wire_to_c_type[input_wire]
        if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(input_t, parser_state):
            text += """typedef uint8_t """ + input_t + "; // FUCK\n"
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(output_t, parser_state):
        text += """typedef uint8_t """ + output_t + "; // FUCK\n"
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(base_c_type, parser_state):
        text += """typedef uint8_t """ + base_c_type + "; // FUCK\n"

    text += """

// Var ref read
"""

    text += output_t + """ """ + func_c_name + """("""

    # Inputs
    for input_wire in partially_complete_logic.inputs:
        input_c_name = input_wire
        input_t = partially_complete_logic.wire_to_c_type[input_wire]
        if LOGIC.C_TYPE_IS_ARRAY(input_t):
            # Dimensions go after variable name
            elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_t)
            text += elem_type + " " + input_c_name
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ", "
        else:
            # Regular non array
            text += input_t + " " + input_c_name + ", "

    # Remove last ","
    text = text.rstrip(", ")
    # End line
    text += """)
{
  """

    # Assign ref toks into base type
    if LOGIC.C_TYPE_IS_ARRAY(base_c_type):
        # Dimensions go after variable name
        elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(base_c_type)
        text += elem_type + " base"
        for dim in dims:
            text += "[" + str(dim) + "]"
        text += ";\n"
    else:
        # Regular non array
        text += base_c_type + " base;\n"

    text += " // Assign ref toks to base\n"
    # Do ref toks
    ref_toks_i = 0
    # print "containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks"
    # print containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks
    driven_ref_toks_list = (
        containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
            partially_complete_logic_local_inst_name
        ]
    )
    if debug:
        print("containing_func_logic", containing_func_logic.func_name)
        print(
            "func",
            partially_complete_logic.func_name,
            partially_complete_logic_local_inst_name,
        )
        print("driven_ref_toks_list", driven_ref_toks_list)
    for input_wire in partially_complete_logic.inputs:
        if "var_dim_" not in input_wire:
            input_c_name = input_wire
            # Assign to base
            # Remove base variable

            # ref toks not from port name
            driven_ref_toks = driven_ref_toks_list[ref_toks_i]
            ref_toks_i += 1

            # Expand to constant refs
            parser_state.existing_logic = (
                containing_func_logic  # How did this work without this before? Lucky?
            )
            expanded_ref_tok_list = EXPAND_REF_TOKS_OR_STRS(
                driven_ref_toks, partially_complete_logic.c_ast_node, parser_state
            )
            if debug:
                print("driven_ref_toks", driven_ref_toks)
                print("expanded_ref_tok_list", expanded_ref_tok_list)
            for expanded_ref_toks in expanded_ref_tok_list:
                # Make str
                lhs = "base"
                appended_ref_tok_str = ""
                for expanded_ref_tok in expanded_ref_toks[1:]:  # Skip base var name
                    if type(expanded_ref_tok) is int:
                        appended_ref_tok_str += "[" + str(expanded_ref_tok) + "]"
                    elif type(expanded_ref_tok) is str:
                        appended_ref_tok_str += "." + expanded_ref_tok
                    else:
                        print(
                            "WTF var ref input wire as input ref tok to var ref??",
                            expanded_ref_tok,
                        )
                        sys.exit(-1)
                # Do assignment
                lhs += appended_ref_tok_str
                text += " " + lhs + " = " + input_c_name
                # If this ref tok actually covers multiple lhs toks then need select on rhs too?
                if len(expanded_ref_tok_list) > 1:
                    # Hacky struct type needs .data
                    if LOGIC.C_TYPE_IS_ARRAY_STRUCT(
                        partially_complete_logic.wire_to_c_type[input_wire],
                        parser_state,
                    ):
                        text += ".data"
                    text += appended_ref_tok_str
                text += ";\n"

    # Then make a bunch of constant references
    # one for each possible i,j,k variable dimension
    # Get var dimension types
    ## BBAAAH parser_state.existing_logic needs to be containing logic
    parser_state_as_container = copy.copy(parser_state)
    parser_state_as_container.existing_logic = containing_func_logic
    (
        var_dim_ref_tok_indices,
        var_dims,
        var_dim_types,
    ) = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(
        ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container
    )
    var_dim_input_wires = []
    for input_wire in partially_complete_logic.inputs:
        if "var_dim_" in input_wire:
            var_dim_input_wires.append(input_wire)

    # Make multiple constant references into base
    text += " // Make multiple constant references into base\n"
    const_refs = ["ref"]
    # Build variables
    # print "var_dim_input_wires",var_dim_input_wires
    for var_dim_i in range(0, len(var_dim_input_wires)):
        c_type = var_dim_types[var_dim_i]
        var_dim_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
        var_dim_size = var_dims[var_dim_i]
        # print "var_dim_width",var_dim_width
        # print "var_dim_size",var_dim_size
        new_const_refs = []
        for const_ref in const_refs:
            for dim_val in range(0, var_dim_size):
                new_const_ref = const_ref + "_" + str(dim_val)
                new_const_refs.append(new_const_ref)
        # Next iter
        const_refs = new_const_refs[:]
    # Assign them
    for const_ref in const_refs:
        # Declare and begin assignment
        text += " " + output_t + " " + const_ref + ";\n"
        if LOGIC.C_TYPE_IS_ARRAY_STRUCT(output_t, parser_state):
            text += " " + const_ref + ".data = base"
        else:
            text += " " + const_ref + " = base"

        # Write out full ref toks
        toks = const_ref.split("_")
        indices = toks[1:]

        # Loop over ref toks and insert variable ref values
        var_dim_i = 0
        for ref_tok in ref_toks[1:]:  # Skip base var name
            if not C_AST_REF_TOK_IS_CONST(ref_tok):
                text += "[" + str(indices[var_dim_i]) + "]"
                var_dim_i += 1
            elif type(ref_tok) is int:
                text += "[" + str(ref_tok) + "]"
            elif type(ref_tok) is str:
                text += "." + ref_tok
            else:
                print("Why ref tok?", ref_tok)
                sys.exit(-1)

        text += ";\n"

    # Is making simple sel = [i][j][k] overkill?
    # Even an N mux per dimension still has muxes for extra bits...
    # Can't avoid ???
    # Easy for now??
    # Sel width is sum of var dims
    sel_width = 0
    var_dim_input_widths = []
    for var_dim_input_wire in var_dim_input_wires:
        var_dim_c_type = partially_complete_logic.wire_to_c_type[var_dim_input_wire]
        var_dim_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, var_dim_c_type)
        sel_width += var_dim_width
        var_dim_input_widths.append(var_dim_width)
    sel_prefix = "uint" + str(sel_width)
    sel_t = sel_prefix + "_t"
    sel_size = int(pow(2, sel_width))

    # Loop to concat sel
    text += " // Form select value\n"

    # Initial copy of first dim
    input_wire = var_dim_input_wires[0]
    text += " " + sel_t + " sel;\n"

    # Need initial value or pipelinemap get fuckled
    text += " " + "sel = 0;\n"

    # Assign into sel
    index = 0
    for var_dim_i in range(len(var_dim_input_wires) - 1, -1, -1):
        c_type = var_dim_types[var_dim_i]
        prefix = c_type.strip("_t")
        var_dim_input_wire = var_dim_input_wires[var_dim_i]
        input_width = var_dim_input_widths[var_dim_i]
        input_c_name = var_dim_input_wire
        text += (
            " sel = "
            + sel_prefix
            + "_"
            + prefix
            + "_"
            + str(index)
            + "( sel, "
            + input_c_name
            + ");\n"
        )
        index += input_width

    # Loop over each const ref
    # Call nmux
    text += " // Do nmux\n"  # $BLEGH TODO make generic mux functions use full type name
    output_prefix = output_t
    # Dumb check for uint
    toks = output_t.strip("_t").split("int")
    if len(toks) == 2 and (toks[0] == "" or toks[0] == "u") and toks[1].isdigit():
        output_prefix = output_t.replace("_t", "")

    text += " " + output_t + " rv;\n"
    text += " rv = " + output_prefix + "_mux" + str(sel_size) + "("
    # Sel
    text += "sel,\n"
    # Inputs
    for sel_val in range(0, sel_size):
        var_dim_values = []
        index = 0
        for var_dim_i in range(0, len(var_dim_input_wires)):
            input_width = var_dim_input_widths[var_dim_i]
            end_index = index + input_width - 1
            # print "index",index
            # print "end_index",end_index

            # get number bit range sel[end:start]
            # dim_val = int(bin(sel_val).replace("0b","").zfill(sel_width)[::-1][index:end_index+1][::-1],2)
            dim_val = int(
                bin(sel_val).replace("0b", "").zfill(sel_width)[index : end_index + 1],
                2,
            )
            var_dim_values.append(dim_val)
            index += input_width
            # print "sel_val",sel_val
            # print "dim_val",dim_val
            #

        # Use ref variable if all var dims are within correct size, otherwise 0
        valid_dims = True
        for var_dim_i in range(0, len(var_dim_input_wires)):
            var_dim_value = var_dim_values[var_dim_i]
            actual_dim_size = var_dims[var_dim_i]
            if var_dim_value >= actual_dim_size:
                valid_dims = False
        if valid_dims:
            # Build ref var str
            ref_sel = "ref"
            # for var_dim_value in reversed(var_dim_values):
            for var_dim_value in var_dim_values:
                ref_sel += "_" + str(var_dim_value)
        else:
            # Hacky allow unfilled to be filled in w/ prev ref?
            # ref_sel = "0"
            pass

        # Use this ref_sel in nmux
        text += "     " + ref_sel + ",\n"

    # Remove last comma
    text = text.strip(",\n")

    text += "\n );\n"

    text += """
  return rv;
}"""

    # if debug:
    # print("GET_VAR_REF_RD_C_CODE text")
    # print(text)
    # sys.exit(-1)

    return text


def GET_VAR_REF_ASSIGN_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    containing_func_logic,
    out_dir,
    parser_state,
):
    # Each element gets a single mux comapring == sel
    # Old code was bloated in muxing multiple copies of huge array

    # Input ref toks can be base value so need to start with base type
    lhs_ref_toks = containing_func_logic.ref_submodule_instance_to_ref_toks[
        partially_complete_logic_local_inst_name
    ]
    orig_var_name = lhs_ref_toks[0]
    base_c_type = containing_func_logic.wire_to_c_type[orig_var_name]

    # print lhs_ref_toks
    # print orig_var_name, "base_c_type",base_c_type
    # sys.exit(-1)

    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    # output_t_c_name = output_t.replace("[","_").replace("]","_").replace("__","_")
    func_c_name = (
        partially_complete_logic.func_name
    )  # .replace("[","_").replace("]","_").replace("__","_")

    text = ""

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MATH_HEADER_FILE
        + """"
"""
    )
    # Do type defs for input structs and output array (if output is array)
    # And base type too
    for input_wire in partially_complete_logic.inputs:
        input_t = partially_complete_logic.wire_to_c_type[input_wire]
        if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(input_t, parser_state):
            text += """typedef uint8_t """ + input_t + "; // FUCK\n"
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(output_t, parser_state):
        text += """typedef uint8_t """ + output_t + "; // FUCK\n"
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(base_c_type, parser_state):
        text += """typedef uint8_t """ + base_c_type + "; // FUCK\n"

    text += """
// Var ref assignment\n"""

    # FUNC DEF
    text += output_t + """ """ + func_c_name + """("""

    # Inputs
    for input_wire in partially_complete_logic.inputs:
        input_c_name = input_wire
        input_t = partially_complete_logic.wire_to_c_type[input_wire]
        if LOGIC.C_TYPE_IS_ARRAY(input_t):
            # Dimensions go after variable name
            elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_t)
            text += elem_type + " " + input_c_name
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ", "
        else:
            # Regular non array
            text += input_t + " " + input_c_name + ", "

    # Remove last ","
    text = text.rstrip(", ")
    # End line
    text += """)
{
  """

    # First need to assign ref tokens into type matching return
    # Assign ref toks into base type
    if LOGIC.C_TYPE_IS_ARRAY(base_c_type):
        # Dimensions go after variable name
        elem_type, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(base_c_type)
        text += elem_type + " base"
        for dim in dims:
            text += "[" + str(dim) + "]"
        text += ";\n"
    else:
        # Regular non array
        text += base_c_type + " base;\n"

    text += " // Assign ref toks to base\n"
    # Do ref toks
    driven_ref_toks_list = (
        containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
            partially_complete_logic_local_inst_name
        ]
    )
    ref_toks_i = 0
    for input_wire in partially_complete_logic.inputs[1:]:
        if "var_dim_" not in input_wire:
            input_c_name = input_wire

            # ref toks not from port name
            driven_ref_toks = driven_ref_toks_list[ref_toks_i]
            ref_toks_i += 1

            # Expand to constant refs
            expanded_ref_tok_list = EXPAND_REF_TOKS_OR_STRS(
                driven_ref_toks, partially_complete_logic.c_ast_node, parser_state
            )
            for expanded_ref_toks in expanded_ref_tok_list:
                # Make str
                lhs = "base"
                for expanded_ref_tok in expanded_ref_toks[1:]:  # Skip base var name:
                    if type(expanded_ref_tok) is int:
                        lhs += "[" + str(expanded_ref_tok) + "]"
                    elif type(expanded_ref_tok) is str:
                        lhs += "." + expanded_ref_tok
                    else:
                        print(
                            "WTF var ref input wire as input ref tok to var ref??",
                            expanded_ref_tok,
                        )
                        sys.exit(-1)

                # Do assignment
                text += " " + lhs + " = " + input_c_name + ";\n"

    # Then make a bunch of copies of rv, one for each possible i,j,k variable dimension
    # Get var dimension types
    var_dim_types = []
    var_dim_input_wires = []
    for input_wire in partially_complete_logic.inputs[1:]:
        if "var_dim_" in input_wire:
            c_type = partially_complete_logic.wire_to_c_type[input_wire]
            var_dim_types.append(c_type)
            var_dim_input_wires.append(input_wire)

    text += " // Copy base into rv\n"
    text += " " + output_t + " rv;\n"
    ## BBAAAH parser_state.existing_logic needs to be containing logic
    # Copy parser state since not intending to change existing logic in this func
    parser_state_as_container = copy.copy(parser_state)
    parser_state_as_container.existing_logic = containing_func_logic
    # Need to assign base into rv output
    # Output type is just N dimension array of the element type
    # N dims are variable ref toks
    # Loop over all the variable dimensions
    # Do so with expanded ref toks
    (
        var_dim_ref_tok_indices,
        var_dims,
        var_dim_iter_types,
    ) = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(
        lhs_ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container
    )
    expanded_ref_tok_list = EXPAND_REF_TOKS_OR_STRS(
        lhs_ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container
    )
    for expanded_ref_toks in expanded_ref_tok_list:
        # LHS is just variable ref dims
        lhs = "rv.data"
        for index in var_dim_ref_tok_indices:
            lhs += "[" + str(expanded_ref_toks[index]) + "]"

        # RHS is full ref toks
        rhs = "base"
        for expanded_ref_tok in expanded_ref_toks[1:]:  # Skip base var name
            if type(expanded_ref_tok) is int:
                rhs += "[" + str(expanded_ref_tok) + "]"
            elif type(expanded_ref_tok) is str:
                rhs += "." + expanded_ref_tok
            else:
                print(
                    "WTF var ref input wire as input ref tok to var ref?? rhs",
                    expanded_ref_tok,
                )
                sys.exit(-1)

        text += " " + lhs + " = " + rhs + ";\n"

    # Do a mux for each element
    text += " // Do mux for each element\n"
    for expanded_ref_toks in expanded_ref_tok_list:
        text += " " + "if(\n"
        # Do each var dim
        for var_dim_i in range(0, len(var_dim_ref_tok_indices)):
            index = var_dim_ref_tok_indices[var_dim_i]
            text += (
                "   ("
                + "var_dim_"
                + str(var_dim_i)
                + " == "
                + str(expanded_ref_toks[index])
                + ") &\n"
            )
        # Remove last and
        text = text[: -len("&\n")]
        # End if ()
        text += "\n )\n"
        text += " {\n"

        # Build lhs
        # LHS is just variable ref dims
        lhs = "rv.data"
        for var_dim_i in range(0, len(var_dim_ref_tok_indices)):
            index = var_dim_ref_tok_indices[var_dim_i]
            lhs += "[" + str(expanded_ref_toks[index]) + "]"

        # Assign elem to it
        text += "   " + lhs + " = elem_val;\n"
        text += " }\n"

    text += """
  return rv;
}"""

    # print "GET_VAR_REF_ASSIGN_C_CODE text"
    # print text
    # sys.exit(-1)

    return text


def GET_BIN_OP_SR_FLOAT_C_CODE(
    partially_complete_logic, out_dir, containing_func_logic, parser_state
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, output_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, output_t]):
        print(""""left_t != "float" or  output_t != "float" for sr """)
        sys.exit(-1)
    fp_t = left_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    text = ""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float shift right div pow2
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // LEFT
  uint"""
        + str(mantissa_width)
        + """_t left_mantissa;  
  left_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  uint"""
        + str(exponent_width)
        + """_t left_exponent;
  left_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  uint1_t left_sign;
  left_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  
  // Declare the output portions
  uint"""
        + str(mantissa_width)
        + """_t z_mantissa;
  uint"""
        + str(exponent_width)
        + """_t z_exponent;
  uint1_t z_sign;
  z_sign = left_sign;
  z_exponent = 0;
  // Div by pow2 with sub to exponent
  if(left_exponent != 0) // Zero divided by anything still zero
  {
    z_exponent = left_exponent - right;
  }
  z_mantissa = left_mantissa;
  // Assemble output  
  return float_uint"""
        + str(exponent_width)
        + "_uint"
        + str(mantissa_width)
        + """(z_sign, z_exponent, z_mantissa);
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_SL_FLOAT_C_CODE(
    partially_complete_logic, out_dir, containing_func_logic, parser_state
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, output_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, output_t]):
        print(""""left_t != "float" or  output_t != "float" for sl """)
        sys.exit(-1)
    fp_t = left_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    text = ""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float shift left mult pow2
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // LEFT
  uint"""
        + str(mantissa_width)
        + """_t left_mantissa;  
  left_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  uint"""
        + str(exponent_width)
        + """_t left_exponent;
  left_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  uint1_t left_sign;
  left_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  
  // Declare the output portions
  uint"""
        + str(mantissa_width)
        + """_t z_mantissa;
  uint"""
        + str(exponent_width)
        + """_t z_exponent;
  uint1_t z_sign;
  z_sign = left_sign;
  z_exponent = 0;
  // mult by pow2 with add to exponent
  if(left_exponent != 0) // Zero times anything stays zero
  {
    z_exponent = left_exponent + right; 
  }
  z_mantissa = left_mantissa;
  // Assemble output  
  return float_uint"""
        + str(exponent_width)
        + "_uint"
        + str(mantissa_width)
        + """(z_sign, z_exponent, z_mantissa);
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_SR_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    out_dir,
    containing_func_logic,
    parser_state,
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]

    # THIS CODE ASSUMES NON CONST/ is dumb to use as const
    left_input_wire = (
        partially_complete_logic_local_inst_name
        + LOGIC.SUBMODULE_MARKER
        + partially_complete_logic.inputs[0]
    )
    right_input_wire = (
        partially_complete_logic_local_inst_name
        + LOGIC.SUBMODULE_MARKER
        + partially_complete_logic.inputs[1]
    )
    left_const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        left_input_wire, containing_func_logic
    )
    right_const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        right_input_wire, containing_func_logic
    )

    if LOGIC.WIRES_ARE_INT_N(
        [partially_complete_logic.inputs[0]], partially_complete_logic
    ) or LOGIC.WIRES_ARE_UINT_N(
        [partially_complete_logic.inputs[0]], partially_complete_logic
    ):
        if right_const_driving_wire is not None:
            print(
                "SW defined constant shift right?",
                partially_complete_logic.c_ast_node.coord,
            )
            sys.exit(-1)
        return GET_BIN_OP_SR_INT_UINT_C_CODE(
            partially_complete_logic, out_dir, containing_func_logic, parser_state
        )
    elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t]):
        return GET_BIN_OP_SR_FLOAT_C_CODE(
            partially_complete_logic, out_dir, containing_func_logic, parser_state
        )
    else:
        print(
            "GET_BIN_OP_SR_C_CODE what types!?",
            partially_complete_logic.c_ast_node.coord,
        )
        sys.exit(-1)


def GET_BIN_OP_SL_C_CODE(
    partially_complete_logic_local_inst_name,
    partially_complete_logic,
    out_dir,
    containing_func_logic,
    parser_state,
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]

    # THIS CODE ASSUMES NON CONST/ is dumb to use as const
    left_input_wire = (
        partially_complete_logic_local_inst_name
        + LOGIC.SUBMODULE_MARKER
        + partially_complete_logic.inputs[0]
    )
    right_input_wire = (
        partially_complete_logic_local_inst_name
        + LOGIC.SUBMODULE_MARKER
        + partially_complete_logic.inputs[1]
    )
    left_const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        left_input_wire, containing_func_logic
    )
    right_const_driving_wire = LOGIC.FIND_CONST_DRIVING_WIRE(
        right_input_wire, containing_func_logic
    )

    if LOGIC.WIRES_ARE_INT_N(
        [partially_complete_logic.inputs[0]], partially_complete_logic
    ) or LOGIC.WIRES_ARE_UINT_N(
        [partially_complete_logic.inputs[0]], partially_complete_logic
    ):
        if right_const_driving_wire is not None:
            print(
                "SW defined constant shift left?",
                partially_complete_logic.c_ast_node.coord,
            )
            sys.exit(-1)
        return GET_BIN_OP_SL_INT_UINT_C_CODE(
            partially_complete_logic, out_dir, containing_func_logic, parser_state
        )
    elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t]):
        return GET_BIN_OP_SL_FLOAT_C_CODE(
            partially_complete_logic, out_dir, containing_func_logic, parser_state
        )
    else:
        print(
            "GET_BIN_OP_SL_C_CODE what types!?",
            partially_complete_logic.c_ast_node.coord,
        )
        sys.exit(-1)


def GET_BIN_OP_PLUS_C_CODE(partially_complete_logic, out_dir):
    # If one of inputs is signed int then other input will be bit extended to include positive sign bit
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
    else:
        print("GET_BIN_OP_PLUS_C_CODE Only plus between float for now!")
        sys.exit(-1)


def GET_BIN_OP_MINUS_C_CODE(partially_complete_logic, out_dir):
    # If one of inputs is signed int then other input will be bit extended to include positive sign bit
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
    else:
        print("GET_BIN_OP_MINUS_C_CODE Only sub between float for now!")
        sys.exit(-1)


def GET_BIN_OP_MOD_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.WIRES_ARE_INT_N(partially_complete_logic.inputs, partially_complete_logic):
        return GET_BIN_OP_MOD_INT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    elif LOGIC.WIRES_ARE_UINT_N(
        partially_complete_logic.inputs, partially_complete_logic
    ):
        return GET_BIN_OP_MOD_UINT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_MOD_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
    else:
        raise Exception(f"Modulo between unknown types {left_t} % {right_t}?")


def GET_BIN_OP_DIV_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
        return GET_BIN_OP_DIV_UINT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    elif LOGIC.WIRES_ARE_INT_N(
        partially_complete_logic.inputs, partially_complete_logic
    ):
        return GET_BIN_OP_DIV_INT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
    else:
        print("GET_BIN_OP_DIV_C_CODE Only div between uint and float for now!")
        sys.exit(-1)


def GET_BIN_OP_MULT_C_CODE(partially_complete_logic, out_dir, parser_state):
    # If one of inputs is signed int then other input will be bit extended to include positive sign bit
    # TODO signed mult
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
        return GET_BIN_OP_MULT_UINT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    elif LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
    elif LOGIC.WIRES_ARE_INT_N(
        partially_complete_logic.inputs, partially_complete_logic
    ):
        return GET_BIN_OP_MULT_INT_N_C_CODE(
            partially_complete_logic, out_dir, parser_state
        )
    else:
        print("GET_BIN_OP_MULT_C_CODE Only mult between uint and float for now!")
        sys.exit(-1)


def GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_exp_width, left_mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(left_t)
    right_exp_width, right_mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(left_t)
    left_width = 1 + left_exp_width + left_mantissa_width
    right_width = 1 + right_exp_width + right_mantissa_width

    if not LOGIC.C_TYPES_ARE_FLOAT_TYPES(
        [left_t, right_t, output_t]
    ) or not LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t, right_t, output_t]):
        print(
            """"left_t != "float" or  right_t != "float" output_t too  for plus""",
            left_t,
            right_t,
        )
        sys.exit(-1)
    fp_t = output_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    # Could pad up to make diff in exponents/max shifting amount = 255?
    # Software 32b implementations pad with 6 zeros
    pad = 0

    mantissa_w_hidden_bit_width = mantissa_width + 1  # 24
    mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1  # 25
    sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1 + pad  # 26
    leading_zeros_width = int(math.ceil(math.log(mantissa_width + 1, 2.0)))

    text = """"""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
//#include "bit_manip.h"
//#include "bit_math.h"

// Float add
// Adds are complicated
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Get exponent for left and right
  uint"""
        + str(exponent_width)
        + """_t left_exponent;
  left_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  uint"""
        + str(exponent_width)
        + """_t right_exponent;
  right_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(right);
    
  """
        + fp_t
        + """ x;
  """
        + fp_t
        + """ y;
  // Step 1: Copy inputs so that left's exponent >= than right's.
  //    Is this only needed for shift operation that takes unsigned only?
  //    ALLOW SHIFT BY NEGATIVE?????
  if ( right_exponent > left_exponent ) // Lazy switch to GT
  {
     x = right;  
     y = left;
  }
  else
  { 
     x = left;
     y = right;
  }
  
  // Step 2: Break apart into S E M
  // X
  uint"""
        + str(mantissa_width)
        + """_t x_mantissa; 
  x_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(x);
  uint"""
        + str(exponent_width)
        + """_t x_exponent;
  x_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(x);
  uint1_t x_sign;
  x_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(x);
  // Y
  uint"""
        + str(mantissa_width)
        + """_t y_mantissa;
  y_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(y);
  uint"""
        + str(exponent_width)
        + """_t y_exponent;
  y_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(y);
  uint1_t y_sign;
  y_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(y);
  
  // Mantissa needs +3b wider
  //  [sign][overflow][hidden][23 bit mantissa]
  // Put 0's in overflow bit and sign bit
  // Put a 1 hidden bit if exponent is non-zero.
  // X
  // Determine hidden bit
  uint1_t x_hidden_bit;
  if(x_exponent == 0) // lazy swith to ==
  {
    x_hidden_bit = 0;
  }
  else
  {
    x_hidden_bit = 1;
  }
  // Apply hidden bit
  uint"""
        + str(mantissa_w_hidden_bit_width)
        + """_t x_mantissa_w_hidden_bit; 
  x_mantissa_w_hidden_bit = uint1_uint"""
        + str(mantissa_width)
        + """(x_hidden_bit, x_mantissa);
  // Y
  // Determine hidden bit
  uint1_t y_hidden_bit;
  if(y_exponent == 0) // lazy swith to ==
  {
    y_hidden_bit = 0;
  }
  else
  {
    y_hidden_bit = 1;
  }
  // Apply hidden bit
  uint"""
        + str(mantissa_w_hidden_bit_width)
        + """_t y_mantissa_w_hidden_bit; 
  y_mantissa_w_hidden_bit = uint1_uint"""
        + str(mantissa_width)
        + """(y_hidden_bit, y_mantissa);

  // Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
  // STEP 2.B moved here
  // Make wider for twos comp/sign
  int"""
        + str(mantissa_w_hidden_bit_sign_adj_width)
        + """_t x_mantissa_w_hidden_bit_sign_adj;
  int"""
        + str(mantissa_w_hidden_bit_sign_adj_width)
        + """_t y_mantissa_w_hidden_bit_sign_adj;
  if(x_sign) //if(x_sign == 1)
  {
    x_mantissa_w_hidden_bit_sign_adj = uint"""
        + str(mantissa_w_hidden_bit_width)
        + """_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int"""
        + str(mantissa_w_hidden_bit_sign_adj_width)
        + """t
  }
  else
  {
    x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
  }
  if(y_sign) // if(y_sign == 1)
  {
    y_mantissa_w_hidden_bit_sign_adj = uint"""
        + str(mantissa_w_hidden_bit_width)
        + """_negate(y_mantissa_w_hidden_bit);
  }
  else
  {
    y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit;
  }
"""
    )
    if pad > 0:
        text += (
            """
  // Padd both x and y on right with zeros (shift left) such that 
  // when y is shifted to the right it doesnt drop mantissa lsbs (as much)
  int"""
            + str(mantissa_w_hidden_bit_sign_adj_width + pad)
            + """_t x_mantissa_w_hidden_bit_sign_adj_rpad = int"""
            + str(mantissa_w_hidden_bit_sign_adj_width)
            + """_uint"""
            + str(pad)
            + """(x_mantissa_w_hidden_bit_sign_adj, 0);
  int"""
            + str(mantissa_w_hidden_bit_sign_adj_width + pad)
            + """_t y_mantissa_w_hidden_bit_sign_adj_rpad = int"""
            + str(mantissa_w_hidden_bit_sign_adj_width)
            + """_uint"""
            + str(pad)
            + """(y_mantissa_w_hidden_bit_sign_adj, 0);
"""
        )
    else:
        text += (
            """
  // No padding
  int"""
            + str(mantissa_w_hidden_bit_sign_adj_width)
            + """_t x_mantissa_w_hidden_bit_sign_adj_rpad = x_mantissa_w_hidden_bit_sign_adj;
  int"""
            + str(mantissa_w_hidden_bit_sign_adj_width)
            + """_t y_mantissa_w_hidden_bit_sign_adj_rpad = y_mantissa_w_hidden_bit_sign_adj;
"""
        )
    text += (
        """
  // Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
  // Already swapped left/right based on exponent
  // diff will be >= 0
  uint"""
        + str(exponent_width)
        + """_t diff;
  diff = x_exponent - y_exponent;
  // Shift y by diff (bit manip pipelined function)
  int"""
        + str(mantissa_w_hidden_bit_sign_adj_width + pad)
        + """_t y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;
  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = y_mantissa_w_hidden_bit_sign_adj_rpad >> diff;
  
  // Step 5: Compute sum 
  int"""
        + str(sum_mantissa_width)
        + """_t sum_mantissa;
  sum_mantissa = x_mantissa_w_hidden_bit_sign_adj_rpad + y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;

  // Step 6: Save sign flag and take absolute value of sum.
  uint1_t sum_sign;
  sum_sign = int"""
        + str(sum_mantissa_width)
        + """_"""
        + str(sum_mantissa_width - 1)
        + """_"""
        + str(sum_mantissa_width - 1)
        + """(sum_mantissa);
  uint"""
        + str(sum_mantissa_width - 1)
        + """_t sum_mantissa_unsigned;
  sum_mantissa_unsigned = int"""
        + str(sum_mantissa_width)
        + """_abs(sum_mantissa);

  // Step 7: Normalize sum and exponent. (Three cases.)
  uint1_t sum_overflow;
  sum_overflow = uint"""
        + str(sum_mantissa_width - 1)
        + """_"""
        + str(sum_mantissa_width - 2)
        + """_"""
        + str(sum_mantissa_width - 2)
        + """(sum_mantissa_unsigned);
  uint"""
        + str(exponent_width)
        + """_t sum_exponent_normalized;
  uint"""
        + str(mantissa_width)
        + """_t sum_mantissa_unsigned_normalized;
  if (sum_overflow) //if ( sum_overflow == 1 )
  {
     // Case 1: Sum overflow.
     //         Right shift significand by 1 and increment exponent.
     sum_exponent_normalized = x_exponent + 1;
     sum_mantissa_unsigned_normalized = uint"""
        + str(sum_mantissa_width - 1)
        + """_"""
        + str(sum_mantissa_width - 3)
        + """_"""
        + str(sum_mantissa_width - mantissa_width - 2)
        + """(sum_mantissa_unsigned);
  }
  else if(sum_mantissa_unsigned == 0) // laxy switch to ==
  {
     //
     // Case 3: Sum is zero.
     sum_exponent_normalized = 0;
     sum_mantissa_unsigned_normalized = 0;
  }
  else
  {
     // Case 2: Sum is nonzero and did not overflow.
     // Dont waste zeros at start of mantissa
     // Find position of first non-zero digit from left
     // Know bit25(sign) and bit24(overflow) are not set
     // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
     uint"""
        + str(sum_mantissa_width - 2)
        + """_t sum_mantissa_unsigned_narrow;
     sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
     uint"""
        + str(leading_zeros_width)
        + """_t leading_zeros; // width = ceil(log2(len(sumsig)))
     leading_zeros = count0s_uint"""
        + str(sum_mantissa_width - 2)
        + """(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
     // NOT CHECKING xexp < adj
     // Case 2b: Adjust significand and exponent.
     sum_exponent_normalized = x_exponent - leading_zeros;
     uint"""
        + str(sum_mantissa_width - 2)
        + """_t sum_mantissa_unsigned_normalized_rpad = sum_mantissa_unsigned_narrow << leading_zeros;
     sum_mantissa_unsigned_normalized = uint"""
        + str(sum_mantissa_width - 2)
        + """_"""
        + str(sum_mantissa_width - 4)
        + """_"""
        + str(sum_mantissa_width - mantissa_width - 3)
        + """(sum_mantissa_unsigned_normalized_rpad);
  }
  
  // Declare the output portions
  uint"""
        + str(mantissa_width)
        + """_t z_mantissa;
  uint"""
        + str(exponent_width)
        + """_t z_exponent;
  uint1_t z_sign;
  z_sign = sum_sign;
  z_exponent = sum_exponent_normalized;
  z_mantissa = sum_mantissa_unsigned_normalized;
  // Assemble output  
  return float_uint"""
        + str(exponent_width)
        + "_uint"
        + str(mantissa_width)
        + """(z_sign, z_exponent, z_mantissa);
}"""
    )

    # print("C CODE")
    # print(text)

    return text


def GET_BIN_OP_LT_LTE_C_CODE(partially_complete_logic, out_dir, op_str):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_LT_LTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str)
    elif LOGIC.C_TYPE_IS_UINT_N(left_t) and LOGIC.C_TYPE_IS_UINT_N(right_t):
        return GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE(partially_complete_logic, op_str)
    elif LOGIC.C_TYPE_IS_INT_N(left_t) and LOGIC.C_TYPE_IS_INT_N(right_t):
        return GET_BIN_OP_GT_GTE_LT_LTE_INT_C_CODE(partially_complete_logic, op_str)
    else:
        raise Exception("GET_BIN_OP_LT_LTE_C_CODE for types!", [left_t, right_t])
        sys.exit(-1)


def GET_BIN_OP_LT_LTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]

    # Inputs must be float
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, right_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        print(""""left_t != "float" or  right_t != "float" for <= """)
        sys.exit(-1)

    # Output must be bool
    if output_t != "uint1_t":
        print("GET_BIN_OP_LT_LTE_FLOAT_C_CODE output_t != uint1_t")
        sys.exit(-1)

    fp_t = left_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    abs_val_width = exponent_width + mantissa_width
    abs_val_prefix = "uint" + str(abs_val_width)
    abs_val_t = abs_val_prefix + "_t"

    text = """"""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float LT/LTE std_logic_vector in C silly
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // LEFT
  uint"""
        + str(mantissa_width)
        + """_t left_mantissa;  
  left_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  uint"""
        + str(exponent_width)
        + """_t left_exponent;
  left_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  uint1_t left_sign;
  left_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  // RIGHT
  uint"""
        + str(mantissa_width)
        + """_t right_mantissa;
  right_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(right);
  uint"""
        + str(exponent_width)
        + """_t right_exponent;
  right_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(right);
  uint1_t right_sign;
  right_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(right);
  
  // Do abs value compare by using exponent as msbs
  //  (-1)^s    * m  *   2^(e - 127)
  """
        + abs_val_t
        + """ left_abs;
  left_abs = uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(left_exponent, left_mantissa);
  """
        + abs_val_t
        + """ right_abs;
  right_abs = uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(right_exponent, right_mantissa);"""
    )

    # Prepare the reversed operation for if both operands are negative
    # ~~~ because youre a lazy bitch, I think
    # if both neg then
    # Switches LT->GT(=flip args LTE), LTE->GTE(flipped args GT)
    if op_str == "<":
        flipped_op_str = "<="
    else:
        # op str <=
        flipped_op_str = "<"

    text += (
        """
  // Adjust for sign
  uint1_t rv;
  uint1_t same_sign;
  same_sign = left_sign == right_sign;
  uint1_t pos_signs;
  uint1_t neg_signs;
  neg_signs = left_sign; // Only used if same sign
  pos_signs = !left_sign; // Only used if same sign
  if(same_sign & pos_signs)
  {
    rv = left_abs """
        + op_str
        + """ right_abs;
  }
  else if(same_sign & neg_signs)
  {
    // Switches LT->GT(=flip args LTE), LTE->GTE(flipped args LT)
    rv = right_abs """
        + flipped_op_str
        + """ left_abs;
  }
  else
  {
    // NOT SAME SIGN so can never equal ( but op is LT or LTE so LT is important part)
    // left must be neg to be LT (neg) right 
    rv = left_sign; // left_sign=1, right_sign=0, left is neg, can never LT left so true
  }

  return rv;
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    if LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        return GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str)
    elif LOGIC.C_TYPE_IS_UINT_N(left_t) and LOGIC.C_TYPE_IS_UINT_N(right_t):
        return GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE(partially_complete_logic, op_str)
    elif LOGIC.C_TYPE_IS_INT_N(left_t) and LOGIC.C_TYPE_IS_INT_N(right_t):
        return GET_BIN_OP_GT_GTE_LT_LTE_INT_C_CODE(partially_complete_logic, op_str)
    else:
        raise Exception("GET_BIN_OP_GT_GTE_C_CODE for types!", [left_t, right_t])
        sys.exit(-1)


def GET_BIN_OP_GT_GTE_LT_LTE_INT_C_CODE(partially_complete_logic, op_str):
    # implement using unsigned compare and signed logic
    # Only for the shared bit range of left/right, extra upper bits handled extra
    # Sign is included in extra bits compare
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_t)
    max_width = max(left_width, right_width)
    left_has_extra_bits = left_width > right_width
    right_has_extra_bits = right_width > left_width
    sign_bits = 1
    extra_bits = 0
    if left_has_extra_bits:
        extra_bits = left_width - right_width
    if right_has_extra_bits:
        extra_bits = right_width - left_width
    sign_bits += extra_bits

    text = ""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{"""
    )
    text += f"""
    // Sign extend as needed
    uint1_t lsign = left({left_width-1},{left_width-1});
    uint1_t rsign = right({right_width-1},{right_width-1});
    int{max_width}_t lsigned = left;
    int{max_width}_t rsigned = right;
"""
    if left_has_extra_bits:
        text += f"""
    uint{sign_bits}_t extra_sign_bits = lsigned >> {max_width-sign_bits};
    uint{sign_bits}_t sign_ext_like_zero = rsigned >> {max_width-sign_bits}; // uint1_{sign_bits}(rsign);
"""
    else:  # right_has_extra_bits AND Default both single sign bits no extra bits
        text += f"""
    uint{sign_bits}_t extra_sign_bits = rsigned >> {max_width-sign_bits};
    uint{sign_bits}_t sign_ext_like_zero = lsigned >> {max_width-sign_bits}; // uint1_{sign_bits}(lsign);
"""
    text += f"""
    // unsigned at minimum width
    uint{max_width-sign_bits}_t lunsigned = left;
    uint{max_width-sign_bits}_t runsigned = right;
    """

    text += (
        """
    uint1_t rv;
    if(extra_sign_bits==sign_ext_like_zero){
        // Do unsigned compare
        rv = lunsigned """
        + op_str
        + """ runsigned;
    }else{
"""
    )
    if op_str == ">=" or op_str == ">":
        # // Sign difference
        # // + > - true1 (!lsign, rsign)
        # // - > + false0 (!lsign, rsign)
        if left_has_extra_bits:
            text += """        
        // and or same sign left magnitude larger
        // -LEFT > -right false  (!lsign,!rsign)
        // LEFT > right true  (!lsign,!rsign)
        rv = ~lsign;
"""
        elif right_has_extra_bits:
            text += """        
        // and or same sign right magnitude larger
        // -left > -RIGHT true (lsign, rsign)
        // left > RIGHT false (lsign, rsign)
        rv = rsign;
"""
        else:
            text += """
        // Sign difference (picked sign without invert)
        rv = rsign;
"""
    elif op_str == "<" or op_str == "<=":
        # // Sign difference
        # // + < - false0 (lsign, !rsign)
        # // - < + true1 (lsign, !rsign)
        if left_has_extra_bits:
            text += """        
        // and or same sign left magnitude larger
        // -LEFT < -right true (lsign, rsign)
        // LEFT < right false (lsign, rsign)
        rv = lsign;
"""
        elif right_has_extra_bits:
            text += """        
        // and or same sign right magnitude larger
        // -left < -RIGHT false (!lsign, !rsign)
        // left < RIGHT true (!lsign, !rsign)
        rv = ~rsign;
"""
        else:
            text += """
        // Sign difference (picked sign without invert)
        rv = lsign;
"""

    text += """    }
    return rv;  
}"""

    # print(text)

    return text


def GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE(partially_complete_logic, op_str):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_t)
    left_has_extra_bits = left_width > right_width
    right_has_extra_bits = right_width > left_width
    has_extra_bits = left_has_extra_bits or right_has_extra_bits
    extra_bits = 0
    if left_has_extra_bits:
        extra_bits = left_width - right_width
    if right_has_extra_bits:
        extra_bits = right_width - left_width
    left_sized_out_t_width = left_width + 1
    left_sized_out_t = "int" + str(left_sized_out_t_width) + "_t"
    left_t_signed = left_t
    left_t_signed_width = left_width
    if not LOGIC.C_TYPE_IS_INT_N(left_t):
        left_t_signed_width = left_width + 1
        left_t_signed = "int" + str(left_t_signed_width) + "_t"
        left_sized_out_t_width = left_t_signed_width
        left_sized_out_t = left_t_signed
    right_sized_out_t_width = right_width + 1
    right_sized_out_t = "int" + str(right_sized_out_t_width) + "_t"
    right_t_signed = right_t
    right_t_signed_width = right_width
    if not LOGIC.C_TYPE_IS_INT_N(right_t):
        right_t_signed_width = right_width + 1
        right_t_signed = "int" + str(right_t_signed_width) + "_t"
        right_sized_out_t_width = right_t_signed_width
        right_sized_out_t = right_t_signed

    max_width = max(left_width, right_width)
    in_t = "int" + str(max_width + 1 - extra_bits) + "_t"
    out_t_width = max_width + 1 - extra_bits
    out_t = "int" + str(out_t_width) + "_t"

    text = ""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
//#include "bit_manip.h"
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
"""
    )

    text += f"""
    // Bottom without any extra bits    
    uint{max_width-extra_bits}_t left_bot = left;
    uint{max_width-extra_bits}_t right_bot = right;
"""
    if has_extra_bits:
        text += f"""    
  uint{extra_bits}_t top;
"""
        if left_has_extra_bits:
            text += f"""  top = left >> {left_width-extra_bits};
"""
        else:
            text += f"""  top = right >> {right_width-extra_bits};
"""
    text += "    uint1_t rv;\n"

    if has_extra_bits:
        text += """  if(top==0){"""

    text += """
    // Subtractor based compare"""
    if op_str == ">":
        text += f"""
    {out_t} sub = ({in_t})right_bot - left_bot;
    uint1_t lt_zero = sub({out_t_width-1},{out_t_width-1});
    rv = lt_zero;
"""
    elif op_str == ">=":
        text += f"""
    {out_t} sub = ({in_t})left_bot - right_bot;
    uint1_t lt_zero = sub({out_t_width-1},{out_t_width-1});
    rv = ~lt_zero;
"""
    elif op_str == "<":
        text += f"""
    {out_t} sub = ({in_t})left_bot - right_bot;
    uint1_t lt_zero = sub({out_t_width-1},{out_t_width-1});
    rv = lt_zero;
"""
    elif op_str == "<=":
        text += f"""
    {out_t} sub = ({in_t})right_bot - left_bot;
    uint1_t lt_zero = sub({out_t_width-1},{out_t_width-1});
    rv = ~lt_zero;
"""

    if left_has_extra_bits:
        if op_str.startswith(">"):
            text += """  }else{
    // Left is large, GT/E is true
    rv = 1;
  }
"""
        if op_str.startswith("<"):
            text += """  }else{
    // Left is large, LT/E is false
    rv = 0;
  }
"""
    if right_has_extra_bits:
        if op_str.startswith(">"):
            text += """  }else{
    // Right is large, GT/E is false
    rv = 0;
  }
"""
        if op_str.startswith("<"):
            text += """  }else{
    // Right is large, LT/E is true
    rv = 1;
  }
"""

    text += """
  return rv;"""

    text += """  
}"""

    # print(text)

    return text


# GT/GTE
def GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, right_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t]):
        print(""""left_t != "float" or  right_t != "float" for >= """)
        sys.exit(-1)
    fp_t = left_t
    # Output must be bool
    if output_t != "uint1_t":
        print("GET_BIN_OP_GT_GTE_FLOAT_C_CODE output_t != uint1_t")
        sys.exit(-1)

    fp_t = left_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    abs_val_width = exponent_width + mantissa_width
    abs_val_prefix = "uint" + str(abs_val_width)
    abs_val_t = abs_val_prefix + "_t"

    text = """"""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float GT/GTE std_logic_vector in C silly
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // LEFT
  uint"""
        + str(mantissa_width)
        + """_t left_mantissa;  
  left_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  uint"""
        + str(exponent_width)
        + """_t left_exponent;
  left_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  uint1_t left_sign;
  left_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  // RIGHT
  uint"""
        + str(mantissa_width)
        + """_t right_mantissa;
  right_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(right);
  uint"""
        + str(exponent_width)
        + """_t right_exponent;
  right_exponent = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(right);
  uint1_t right_sign;
  right_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(right);
  
  // Do abs value compare by using exponent as msbs
  //  (-1)^s    * m  *   2^(e - 127)
  """
        + abs_val_t
        + """ left_abs;
  left_abs = uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(left_exponent, left_mantissa);
  """
        + abs_val_t
        + """ right_abs;
  right_abs = uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(right_exponent, right_mantissa);"""
    )

    # if both neg then
    # Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
    if op_str == ">":
        flipped_op_str = ">="
    else:
        # op str >=
        flipped_op_str = ">"

    text += (
        """
  // Adjust for sign
  uint1_t rv;
  uint1_t same_sign;
  same_sign = left_sign == right_sign;
  uint1_t pos_signs;
  uint1_t neg_signs;
  neg_signs = left_sign; // Only used if same sign
  pos_signs = !left_sign; // Only used if same sign
  if(same_sign & pos_signs)
  {
    rv = left_abs """
        + op_str
        + """ right_abs;
  }
  else if(same_sign & neg_signs)
  {
    // Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
    rv = right_abs """
        + flipped_op_str
        + """ left_abs;
  }
  else
  {
    // NOT SAME SIGN so can never equal ( but op is GT or GTE so GT is important part)
    // left must be pos to be GT (neg)right 
    rv = right_sign; // left_sign=0, right_sign=1, right is neg, can never GT left so true
  }

  return rv;
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, right_t, output_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t, output_t]):
        print(""""left_t != "float" or  right_t != "float" output_t too  for minus""")
        sys.exit(-1)
    fp_t = output_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    mantissa_w_hidden_bit_width = mantissa_width + 1  # 24
    mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1  # 25
    sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1  # 26
    leading_zeros_width = int(math.ceil(math.log(mantissa_width + 1, 2.0)))

    text = ""
    text += (
        """
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "bit_math.h"
#include "float_e_m_t.h"

// Float minus std_logic_vector in VHDL
// Minus is as complicated as add - yeah, so just use add
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  uint1_t right_sign;
  right_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(right);
  uint"""
        + str(fp_t_width - 1)
        + """_t right_everythingelse = """
        + fp_t
        + """_"""
        + str(sign_index - 1)
        + """_0(right);
  uint"""
        + str(fp_t_width)
        + """_t negated_right_unsigned = uint1_uint"""
        + str(fp_t_width - 1)
        + """(!right_sign, right_everythingelse);
  """
        + fp_t
        + """ negated_right = """
        + fp_t
        + """_uint"""
        + str(fp_t_width)
        + """(negated_right_unsigned);
  return left + negated_right;
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_MOD_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
    # So there was this guy here trying to figure out the floating point implementation for modulo
    # Then the internet (of all people) chimes in and says modulo for floating point isn't actually part of standard C?
    # And that there are various fmod implementations for math.h
    # So me embracing the piece of shit (that I am) will implement mod in C too

    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if left_t != right_t or not LOGIC.C_TYPES_ARE_FLOAT_TYPES(
        [left_t, right_t, output_t]
    ):
        print(left_t, right_t, output_t)
        print(""""left_t != "float" or  right_t != "float" output_t mod""")
        sys.exit(-1)
    fp_t = output_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    text = ""

    text += (
        '''
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// Float div std_logic_vector in VHDL
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Quotient
  """
        + fp_t
        + """ q;
  q = left / right;
  
  // Convert to int (floor?)
  // float max value = 3.402823466*10^38
  // log2(3.402823466*10^38) ~ 128 , int129
  int129_t q_int;
  q_int = q;
  
  // Partial quotient
  """
        + fp_t
        + """ partial;
  partial = ("""
        + fp_t
        + """)q_int * right;
  
  """
        + fp_t
        + """ remainder;
  remainder = left - partial;
  
  return remainder;
}
"""
    )

    return text


def GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
    # Taking this directly from the 1 clock version VHDL from
    """
    -- Company: Instituto Superior Tecnico
    -- Prof: Paulo Alexandre Crisostomo Lopes
    -- paulo.lopes@inesc-id.pt
    """
    # Can improve in future
    # Thanks man
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, right_t, output_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t, output_t]):
        print(left_t, right_t, output_t)
        print(""""left_t != "float" or  right_t != "float" output_t too div/mod""")
        sys.exit(-1)
    fp_t = output_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    a_width = mantissa_width + 3
    a_prefix = "uint" + str(a_width)
    a_t = a_prefix + "_t"

    remainder_width = mantissa_width + 2
    remainder_prefix = "uint" + str(remainder_width)
    remainder_t = remainder_prefix + "_t"

    tmp_remainder_width = mantissa_width + 2
    tmp_remainder_prefix = "uint" + str(tmp_remainder_width)
    tmp_remainder_t = tmp_remainder_prefix + "_t"

    exponent_aux_width = exponent_width + 1
    exponent_aux_t_prefix = "uint" + str(exponent_aux_width)
    exponent_aux_t = exponent_aux_t_prefix + "_t"

    mantissa_w_extra_bit_width = mantissa_width + 2
    mantissa_w_extra_bit_prefix = "uint" + str(mantissa_w_extra_bit_width)
    mantissa_w_extra_bit_t = mantissa_w_extra_bit_prefix + "_t"

    text = ""

    text += (
        '''
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"
#include "float_e_m_t.h"

// Float div std_logic_vector in VHDL
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  """
        + mantissa_t
        + """ x_mantissa;
  x_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  """
        + exponent_wide_t
        + """ x_exponent_wide;
  x_exponent_wide = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  """
        + sign_t
        + """ x_sign;
  x_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  // RIGHT
  """
        + mantissa_t
        + """ y_mantissa;
  y_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(right);
  """
        + exponent_wide_t
        + """ y_exponent_wide;
  y_exponent_wide = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(right);
  """
        + sign_t
        + """ y_sign;
  y_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(right);
  
  // Delcare intermediates
  """
        + a_t
        + """ a;
  a = 0;
  """
        + remainder_t
        + """ partial_remainder;
  partial_remainder = 0;
  """
        + remainder_t
        + """ tmp_remainder;
  tmp_remainder = 0;
  """
        + exponent_aux_t
        + """ exponent_aux;
  exponent_aux = 0;
  """
        + mantissa_w_extra_bit_t
        + """ x_mantissa_w_extra_bit;
  x_mantissa_w_extra_bit = 0;
  """
        + mantissa_w_extra_bit_t
        + """ y_mantissa_w_extra_bit;
  y_mantissa_w_extra_bit = 0;
  uint1_t a_i;
  a_i = 0;
  
  // Mantissas with extra bit
  x_mantissa_w_extra_bit = uint2_"""
        + mantissa_t_prefix
        + """(1,x_mantissa);
  y_mantissa_w_extra_bit = uint2_"""
        + mantissa_t_prefix
        + """(1,y_mantissa);
  
  // BIAS CONST
  """
        + exponent_bias_t
        + """ BIAS;
  BIAS = """
        + str(exponent_bias)
        + """;
  
  // Declare the output portions
  """
        + mantissa_t
        + """ z_mantissa;
  """
        + exponent_t
        + """ z_exponent;
  """
        + sign_t
        + """ z_sign;
  
  // Sign
  z_sign = x_sign ^ y_sign;
  
  // Initial exponent sub and add bias
  exponent_aux = x_exponent_wide - y_exponent_wide;
  exponent_aux = exponent_aux + BIAS;
  
  // Divide unrolled since isnt simple unsigned div of mantissa
  partial_remainder = x_mantissa_w_extra_bit;"""
    )
    for i in range(a_width - 1, -1, -1):
        text += (
            """
  // Bit """
            + str(i)
            + """
  /*
      tmp_remainder := partial_remainder - y_mantissa_w_extra_bit;
    if ( tmp_remainder(24)='0' ) then 
      -- result is non negative: partial_remainder >= y_mantissa_w_extra_bit
      -- note that tmp_remainder < 2 so bit 24 should be zero
      a(i):='1';
      partial_remainder := tmp_remainder;
    else
      a(i):='0'
    end if;
    partial_remainder := partial_remainder(23 downto 0) & '0'; -- sll
  */
  tmp_remainder = partial_remainder - y_mantissa_w_extra_bit;
  if("""
            + remainder_prefix
            + """_"""
            + str(remainder_width - 1)
            + """_"""
            + str(remainder_width - 1)
            + """(tmp_remainder) == 0 )
  {
    // result is non negative: partial_remainder >= y_mantissa_w_extra_bit
    // note that tmp_remainder < 2 so bit 24 should be zero
    a_i = 1;
    partial_remainder = tmp_remainder;
  }
  else
  {
    a_i = 0;
    partial_remainder = partial_remainder; // No change
  }
  partial_remainder = """
            + remainder_prefix
            + """_uint1(partial_remainder, 0); // sll
  
  // Assign a(i)
  a = """
            + a_prefix
            + """_uint1_"""
            + str(i)
            + """(a,a_i);
  """
        )

    ###### DIV
    text += (
        """ 
  /////////////////////
  // END OF DIV LOOP FOR DIV
  //////////////////////
  
  // NO ROUND
  if("""
        + a_prefix
        + """_"""
        + str(a_width - 1)
        + """_"""
        + str(a_width - 1)
        + """(a)) //== 1)
  {
    z_mantissa = """
        + a_prefix
        + """_"""
        + str(a_width - 2)
        + """_2(a);
    exponent_aux = exponent_aux; // No change
  }
  else
  {
    z_mantissa = """
        + a_prefix
        + """_"""
        + str(a_width - 3)
        + """_1(a);
    exponent_aux = exponent_aux - 1;
  }"""
    )

    text += (
        """ 
  z_exponent = """
        + exponent_aux_t_prefix
        + """_"""
        + str(exponent_width - 1)
        + """_0(exponent_aux); 
  
  // Assemble output
  return float"""
        + """_uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(z_sign, z_exponent, z_mantissa);
}"""
    )

    # print "C CODE"
    # print text

    return text


def GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
    # Taking this directly from the 1 clock version VHDL from
    """
    -- Company: Instituto Superior Tecnico
    -- Prof: Paulo Alexandre Crisostomo Lopes
    -- paulo.lopes@inesc-id.pt
    """
    # Can improve in future
    # Thanks man

    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    if not LOGIC.C_FLOAT_TYPES_ARE_EQUAL(
        [left_t, right_t, output_t]
    ) or not LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t, right_t, output_t]):
        print(left_t, right_t, output_t)
        print(""""left_t != "float" or  right_t != "float" output_t too""")
        sys.exit(-1)
    fp_t = output_t

    ######## ARB WIDTH FLOATS
    exponent_width, mantissa_width = LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
    mantissa_range = [mantissa_width - 1, 0]
    mantissa_t_prefix = "uint" + str(mantissa_width)
    mantissa_t = mantissa_t_prefix + "_t"
    exponent_range = [mantissa_width + exponent_width - 1, mantissa_width]
    exponent_t_prefix = "uint" + str(exponent_width)
    exponent_t = exponent_t_prefix + "_t"
    exponent_width_plus1 = exponent_width + 1
    exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
    exponent_wide_t = exponent_wide_t_prefix + "_t"
    exponent_max = int(math.pow(2, exponent_width) - 1)
    exponent_bias = int(math.pow(2, exponent_width - 1) - 1)
    exponent_bias_t = "uint" + str(exponent_width - 1) + "_t"
    sign_index = mantissa_width + exponent_width
    sign_width = 1
    sign_t_prefix = "uint" + str(sign_width)
    sign_t = sign_t_prefix + "_t"
    fp_t_width = 1 + exponent_width + mantissa_width

    aux_width = 1
    aux_t_prefix = "uint" + str(aux_width)
    aux_t = aux_t_prefix + "_t"
    aux2_width = (mantissa_width + 1) * 2  # 48 for fp32
    aux2_t_prefix = "uint" + str(aux2_width)
    aux2_t = aux2_t_prefix + "_t"
    aux2_in_width = mantissa_width + 1
    aux2_in_t_prefix = "uint" + str(aux2_in_width)
    aux2_in_t = aux2_in_t_prefix + "_t"
    exponent_sum_width = exponent_width + 1
    exponent_sum_t_prefix = "uint" + str(exponent_sum_width)
    exponent_sum_t = exponent_sum_t_prefix + "_t"
    """
  e_m_width = exponent_width + mantissa_width
  e_m_t_prefix = "uint" + str(e_m_width)
  e_m_t = e_m_t_prefix + "_t"
  s_e_m_width = sign_width + e_m_width
  s_e_m_t_prefix = "uint" + str(s_e_m_width)
  s_e_m_t = s_e_m_t_prefix + "_t"
  """

    text = ""

    text += (
        '''
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"
#include "float_e_m_t.h"

// Float mult std_logic_vector in VHDL
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  """
        + mantissa_t
        + """ x_mantissa;
  x_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(left);
  """
        + exponent_wide_t
        + """ x_exponent_wide;
  x_exponent_wide = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(left);
  """
        + sign_t
        + """ x_sign;
  x_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(left);
  // RIGHT
  """
        + mantissa_t
        + """ y_mantissa;
  y_mantissa = """
        + fp_t
        + """_"""
        + str(mantissa_range[0])
        + """_"""
        + str(mantissa_range[1])
        + """(right);
  """
        + exponent_wide_t
        + """ y_exponent_wide;
  y_exponent_wide = """
        + fp_t
        + """_"""
        + str(exponent_range[0])
        + """_"""
        + str(exponent_range[1])
        + """(right);
  """
        + sign_t
        + """ y_sign;
  y_sign = """
        + fp_t
        + """_"""
        + str(sign_index)
        + """_"""
        + str(sign_index)
        + """(right);
  
  // Declare the output portions
  """
        + mantissa_t
        + """ z_mantissa;
  """
        + exponent_t
        + """ z_exponent;
  """
        + sign_t
        + """ z_sign;
  
  // Sign
  z_sign = x_sign ^ y_sign;
  
  // Multiplication with infinity = inf
  if((x_exponent_wide=="""
        + str(exponent_max)
        + """) | (y_exponent_wide=="""
        + str(exponent_max)
        + """))
  {
    z_exponent = """
        + str(exponent_max)
        + """;
    z_mantissa = 0;
  }
  // Multiplication with zero = zero
  else if((x_exponent_wide==0) | (y_exponent_wide==0))
  {
    z_exponent = 0;
    z_mantissa = 0;
    z_sign = 0;
  }
  // Normal non zero|inf mult
  else
  {
    // Delcare intermediates
    """
        + aux_t
        + """ aux;
    """
        + aux2_in_t
        + """ aux2_x;
    """
        + aux2_in_t
        + """ aux2_y;
    """
        + aux2_t
        + """ aux2;
    """
        + exponent_bias_t
        + """ BIAS;
    BIAS = """
        + str(exponent_bias)
        + """;
    
    aux2_x = uint1_"""
        + mantissa_t_prefix
        + """(1, x_mantissa);
    aux2_y = uint1_"""
        + mantissa_t_prefix
        + """(1, y_mantissa);
    aux2 =  aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = """
        + aux2_t_prefix
        + """_"""
        + str(aux2_width - 1)
        + """_"""
        + str(aux2_width - 1)
        + """(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = """
        + aux2_t_prefix
        + """_"""
        + str(aux2_width - 2)
        + """_"""
        + str(aux2_width - mantissa_width - 1)
        + """(aux2); 
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = """
        + aux2_t_prefix
        + """_"""
        + str(aux2_width - 3)
        + """_"""
        + str(aux2_width - mantissa_width - 2)
        + """(aux2); 
    }
    
    // calculate exponent in parts 
    // do sequential unsigned adds and subs to avoid signed numbers for now
    // X and Y exponent are already 1 bit wider than needed
    // (0 & x_exponent) + (0 & y_exponent);
    """
        + exponent_sum_t
        + """ exponent_sum = x_exponent_wide + y_exponent_wide;
    exponent_sum = exponent_sum + aux;
    exponent_sum = exponent_sum - BIAS;
    
    // HACKY NOT CHECKING
    // if (exponent_sum(8)='1') then
    z_exponent = """
        + exponent_sum_t_prefix
        + """_"""
        + str(exponent_width - 1)
        + """_0(exponent_sum);
  }
  
  
  // Assemble output
  return float"""
        + """_uint"""
        + str(exponent_width)
        + """_uint"""
        + str(mantissa_width)
        + """(z_sign, z_exponent, z_mantissa);
}"""
    )

    # print("C CODE")
    # print(text)

    return text


def GET_BIN_OP_SR_INT_UINT_C_CODE(
    partially_complete_logic, out_dir, containing_func_logic, parser_state
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    left_prefix = left_t.replace("_t", "")
    is_signed = LOGIC.C_TYPE_IS_INT_N(left_t)
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    if LOGIC.C_TYPE_IS_INT_N(right_t):
        right_max_val = pow(2, right_width - 1) - 1
        right_unsigned_width = right_width - 1
    else:
        right_max_val = pow(2, right_width) - 1
        right_unsigned_width = right_width
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = output_t.replace("_t", "")

    # TODO: FIX THIS
    # SHIFT WIDTH IS TRUNCATED TO 2^log2(math.ceil(math.log(max_shift+1,2))) -1
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # TODO: Remove 1 LL
    # return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs

    # Shift size is limited by width of left input
    max_shift = left_width - 1
    shift_bit_width = min(max_shift.bit_length(), right_unsigned_width)
    needs_resize = right_max_val > (pow(2, shift_bit_width) - 1)
    # Shift amount is resized
    resized_prefix = "uint" + str(shift_bit_width)
    resized_t = resized_prefix + "_t"

    text = ""

    text += (
        '''
#include "intN_t.h"  
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """shifted right by maximum """
        + str(max_shift)
        + """b
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize the shift amount (right)
  """
        + resized_t
        + """ resized_shift_amount;
  resized_shift_amount = right;
  
  // Output
  """
        + output_t
        + """ rv;
"""
    )
    if needs_resize:
        text += (
            """
  // Check for oversized
  if(right > """
            + str(max_shift)
            + """)
  {
    // Append sign bits on left and select rv from MSBs
    uint1_t sign;
"""
        )
        if is_signed:
            text += (
                """    sign = """
                + left_prefix
                + """_"""
                + str(left_width - 1)
                + """_"""
                + str(left_width - 1)
                + """(left);
"""
            )
        else:
            text += """    sign = 0;
"""
        text += "    // Big shift all sign bits\n"
        text += "    rv = uint1_" + str(output_width) + "(sign);\n"
        text += """
  }
  else
  {
"""
    text += (
        """
    // Otherwise use Victor's muxes
    """
        + output_t
        + """ v0 = left;
"""
    )
    for b in range(0, shift_bit_width):
        text += (
            "    "
            + output_t
            + " v"
            + str(b + 1)
            + " = "
            + output_prefix
            + "_"
            + str(b)
            + "_"
            + str(b)
            + "(resized_shift_amount)"
            + " ? (v"
            + str(b)
            + " >> "
            + str(pow(2, b))
            + ") : v"
            + str(b)
            + ";\n"
        )

    text += "    rv = v" + str(shift_bit_width) + ";\n"

    if needs_resize:
        text += """
  }
"""
    text += """
  return rv;
}"""

    # if is_signed:
    # print("GET_BIN_OP_SR_UINT_C_CODE text")
    # print(text)
    #  sys.exit(-1)
    return text


# // 64B  First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
# // 32B also 4 LLs?
# // 128B 8 LLs
def GET_BIN_OP_SL_INT_UINT_C_CODE(
    partially_complete_logic, out_dir, containing_func_logic, parser_state
):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    # is_signed = LOGIC.C_TYPE_IS_INT_N(left_t)
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    if LOGIC.C_TYPE_IS_INT_N(right_t):
        right_max_val = pow(2, right_width - 1) - 1
        right_unsigned_width = right_width - 1
    else:
        right_max_val = pow(2, right_width) - 1
        right_unsigned_width = right_width
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = output_t.replace("_t", "")

    # TODO: Remove 1 LL
    # return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs

    # Shift size is limited by width of left input
    max_shift = left_width - 1
    shift_bit_width = min(max_shift.bit_length(), right_unsigned_width)
    needs_resize = right_max_val > (pow(2, shift_bit_width) - 1)
    # Shift amount is resized up if needed

    resized_prefix = "uint" + str(shift_bit_width)
    resized_t = resized_prefix + "_t"

    text = ""

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """shifted left by maximum """
        + str(max_shift)
        + """b
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize the shift amount (right)
  """
        + resized_t
        + """ resized_shift_amount;
  resized_shift_amount = right;
"""
    )
    text += (
        """
  // Output
  """
        + output_t
        + """ rv;
"""
    )
    if needs_resize:
        text += (
            """
  // Check for oversized
  if(right > """
            + str(max_shift)
            + """)
  {
    // Big shift, all zeros
    rv = 0;
  }
  else
  {"""
        )
    text += (
        """
    // Otherwise use Victor's muxes
    """
        + output_t
        + """ v0 = left;
"""
    )
    for b in range(0, shift_bit_width):
        text += (
            "    "
            + output_t
            + " v"
            + str(b + 1)
            + " = "
            + output_prefix
            + "_"
            + str(b)
            + "_"
            + str(b)
            + "(resized_shift_amount)"
            + " ? (v"
            + str(b)
            + " << "
            + str(pow(2, b))
            + ") : v"
            + str(b)
            + ";\n"
        )

    text += "    rv = v" + str(shift_bit_width) + ";\n"

    if needs_resize:
        text += """
  }
"""

    text += """
  return rv;
}"""

    # print("GET_BIN_OP_SL text")
    # print(text)

    return text


def GET_BIN_OP_MULT_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "uint" + str(max_input_width)
    resized_t = resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "uint" + str(output_width)

    # Temp try to reduce bit width?
    # Output width is max =  left_width+right_width
    # Actual max internal width is min out output width and max of input widths
    # Does not include output width because of sign for signed mult???
    # TODO: Check if can limit like UINT including output width
    max_intermidate_bit_width = left_width + right_width

    text = ""

    # Generate abs path to uint headers
    # top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    # uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
    # int_h ='''#include "''' + top_dir + '''/intN_t.h"'''

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b x """
        + str(right_width)
        + """b mult
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize
  """
        + resized_t
        + """ left_resized;
  left_resized = left;
  """
        + resized_t
        + """ right_resized;
  right_resized = right;
  
  // Left repeated bit unsigneds
"""
    )
    for rb in range(0, max_input_width):
        text += (
            """ // BIT"""
            + str(rb)
            + """ REPEATED
  // Select bit
  uint1_t left"""
            + str(rb)
            + """_x1;
  left"""
            + str(rb)
            + """_x1 = """
            + resized_prefix
            + """_"""
            + str(rb)
            + """_"""
            + str(rb)
            + """(left_resized);
  // Dup
  uint"""
            + str(max_input_width)
            + """_t  left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """;
  left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """ = uint1_"""
            + str(max_input_width)
            + """(left"""
            + str(rb)
            + """_x1);
"""
        )

    text += """
  // Partial sums
"""
    for rb in range(0, max_input_width):
        text += (
            " "
            + resized_t
            + """ p"""
            + str(rb)
            + """;
  p"""
            + str(rb)
            + """ = left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """ & right_resized;
"""
        )

    # Save types of shifted partial sum vars for ease later
    var_2_type = {}

    text += (
        """
  // Shifted partial sums
  """
        + resized_t
        + """ p0_shifted;
  p0_shifted = p0;
"""
    )
    var_2_type["p0_shifted"] = resized_t
    p_width = max_input_width
    for p in range(1, max_input_width):
        uintp_prefix = "uint" + str(p)
        uintp_t = uintp_prefix + "_t"
        # p_width_minus1 = p_width - 1
        p_t_prefix = "uint" + str(p_width)
        p_shifted_t = "uint" + str(p_width + p) + "_t"
        p_shifted = """p""" + str(p) + """_shifted"""
        var_2_type[p_shifted] = p_shifted_t
        text += (
            """ """
            + uintp_t
            + """ zero_x"""
            + str(p)
            + """;
  zero_x"""
            + str(p)
            + """ = 0;
  """
            + p_shifted_t
            + """ p"""
            + str(p)
            + """_shifted;
  p"""
            + str(p)
            + """_shifted = """
            + p_t_prefix
            + """_"""
            + uintp_prefix
            + """(p"""
            + str(p)
            + """ ,zero_x"""
            + str(p)
            + """);
"""
        )

    # Cap shifted partiual sums to max intermediate width
    max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
    max_intermidate_t = max_intermidate_prefix + "_t"

    # Do Signed trick with inverted bits, already have shifted version in 'pN_shifted'
    """
                                                    1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
                                                ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
                                         ~p2[7] +p2[6] +p2[5] +p2[4] +p2[3] +p2[2] +p2[1] +p2[0]   0      0
                                  ~p3[7] +p3[6] +p3[5] +p3[4] +p3[3] +p3[2] +p3[1] +p3[0]   0      0      0
                           ~p4[7] +p4[6] +p4[5] +p4[4] +p4[3] +p4[2] +p4[1] +p4[0]   0      0      0      0
                    ~p5[7] +p5[6] +p5[5] +p5[4] +p5[3] +p5[2] +p5[1] +p5[0]   0      0      0      0      0
             ~p6[7] +p6[6] +p6[5] +p6[4] +p6[3] +p6[2] +p6[1] +p6[0]   0      0      0      0      0      0
   1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
 ------------------------------------------------------------------------------------------------------------
P[15]  P[14]  P[13]  P[12]  P[11]  P[10]   P[9]   P[8]   P[7]   P[6]   P[5]   P[4]   P[3]   P[2]   P[1]  P[0]
  """

    msb_prefix = "uint1"
    msb_t = msb_prefix + "_t"
    for p in range(0, max_input_width):
        # Shifted p
        p_shifted_width = p_width + p
        p_shifted_prefix = "uint" + str(p_shifted_width)
        p_shifted_t = "uint" + str(p_shifted_width) + "_t"
        p_shifted = """p""" + str(p) + """_shifted"""

        # Get msb
        p_shifted_msb = p_shifted + "_msb"
        text += (
            """
    
  // P """
            + str(p)
            + """ adjusted
  """
            + msb_t
            + """ """
            + p_shifted_msb
            + """;
  """
            + p_shifted_msb
            + """ = """
            + p_shifted_prefix
            + """_"""
            + str(p_shifted_width - 1)
            + """_"""
            + str(p_shifted_width - 1)
            + """("""
            + p_shifted
            + """);"""
        )

        # First is special case
        if p == 0:
            # Get lower bits of shfited
            lsbs_width = p_shifted_width - 1
            lsbs_prefix = "uint" + str(lsbs_width)
            lsbs_t = lsbs_prefix + "_t"
            p_shifted_lsbs = p_shifted + "_lsbs"
            text += (
                """
  // First is special case
  """
                + lsbs_t
                + """ """
                + p_shifted_lsbs
                + """;
  """
                + p_shifted_lsbs
                + """ = """
                + p_shifted_prefix
                + """_"""
                + str(lsbs_width - 1)
                + """_0("""
                + p_shifted
                + """);"""
            )

            # Invert msb
            p_shifted_msb_neg = p_shifted_msb + "_neg"
            text += (
                """
  """
                + msb_t
                + """ """
                + p_shifted_msb_neg
                + """;
  """
                + p_shifted_msb_neg
                + """ = ~"""
                + p_shifted_msb
                + """;"""
            )

            # Concat negated msb and lsbs
            p_shifted_neg_msb_and_lsbs_prefix_width = lsbs_width + 1
            p_shifted_neg_msb_and_lsbs_prefix = "uint" + str(
                p_shifted_neg_msb_and_lsbs_prefix_width
            )
            p_shifted_neg_msb_and_lsbs_t = p_shifted_neg_msb_and_lsbs_prefix + "_t"
            p_shifted_neg_msb_and_lsbs = p_shifted + "_neg_msb_and_lsbs"
            text += (
                """
  """
                + p_shifted_neg_msb_and_lsbs_t
                + """ """
                + p_shifted_neg_msb_and_lsbs
                + """;
  """
                + p_shifted_neg_msb_and_lsbs
                + """ = """
                + msb_prefix
                + """_"""
                + lsbs_prefix
                + """("""
                + p_shifted_msb_neg
                + ""","""
                + p_shifted_lsbs
                + """);"""
            )

            # Adjusted result has 1 added as MSB
            # 1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
            adj_width = p_shifted_width + 1
            # Cap shifted partiual sums to max intermediate width
            if adj_width > max_intermidate_bit_width:
                adj_width = max_intermidate_bit_width
            adj_width_prefix = "uint" + str(adj_width)
            adj_t = adj_width_prefix + "_t"
            p_shifted_adj = p_shifted + "_adj"
            text += (
                """
  """
                + adj_t
                + """ """
                + p_shifted_adj
                + """;
  """
                + p_shifted_adj
                + """ = uint1_"""
                + p_shifted_neg_msb_and_lsbs_prefix
                + """(1, """
                + p_shifted_neg_msb_and_lsbs
                + """);"""
            )
            var_2_type[p_shifted_adj] = adj_t

        # End is special case
        elif p == (max_input_width - 1):
            # 1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
            # Get zeros
            p_shifted_zeros_width = p
            p_shifted_zeros_prefix = "uint" + str(p_shifted_zeros_width)
            p_shifted_zeros_t = p_shifted_zeros_prefix + "_t"
            p_shifted_zeros = p_shifted + "_zeros"
            text += (
                """
  // End special case
  """
                + p_shifted_zeros_t
                + """ """
                + p_shifted_zeros
                + """;
  """
                + p_shifted_zeros
                + """ = """
                + p_shifted_prefix
                + """_"""
                + str(p_shifted_zeros_width - 1)
                + """_0("""
                + p_shifted
                + """);"""
            )

            # Get upper lsbs that arent zero
            # DOES NOT INCLUDE MSB
            p_shifted_upper_lsbs_width = p_width - 1
            p_shifted_upper_lsbs_prefix = "uint" + str(p_shifted_upper_lsbs_width)
            p_shifted_upper_lsbs_t = p_shifted_upper_lsbs_prefix + "_t"
            p_shifted_upper_lsbs = p_shifted + "_upper_lsbs"
            low = p_shifted_zeros_width
            high = p_shifted_width - 2  # SKIP MSB
            text += (
                """
  """
                + p_shifted_upper_lsbs_t
                + """ """
                + p_shifted_upper_lsbs
                + """;
  """
                + p_shifted_upper_lsbs
                + """ = """
                + p_shifted_prefix
                + """_"""
                + str(high)
                + """_"""
                + str(low)
                + """("""
                + p_shifted
                + """);"""
            )

            # Invert upper lsbs
            p_shifted_upper_lsbs_neg = p_shifted_upper_lsbs + "_neg"
            text += (
                """
  """
                + p_shifted_upper_lsbs_t
                + """ """
                + p_shifted_upper_lsbs_neg
                + """;
  """
                + p_shifted_upper_lsbs_neg
                + """ = ~"""
                + p_shifted_upper_lsbs
                + """;"""
            )

            # Concat zeros and negated upper lsbs
            p_shifted_upper_lsbs_neg_and_zeros_width = (
                p_shifted_upper_lsbs_width + p_shifted_zeros_width
            )
            p_shifted_upper_lsbs_neg_and_zeros_prefix = "uint" + str(
                p_shifted_upper_lsbs_neg_and_zeros_width
            )
            p_shifted_upper_lsbs_neg_and_zeros_t = (
                p_shifted_upper_lsbs_neg_and_zeros_prefix + "_t"
            )
            p_shifted_upper_lsbs_neg_and_zeros = p_shifted_upper_lsbs_neg + "_and_zeros"
            text += (
                """
  """
                + p_shifted_upper_lsbs_neg_and_zeros_t
                + """ """
                + p_shifted_upper_lsbs_neg_and_zeros
                + """;
  """
                + p_shifted_upper_lsbs_neg_and_zeros
                + """ = """
                + p_shifted_upper_lsbs_prefix
                + """_"""
                + p_shifted_zeros_prefix
                + """("""
                + p_shifted_upper_lsbs_neg
                + """, """
                + p_shifted_zeros
                + """);"""
            )

            # Concat msb
            p_shifted_upper_lsbs_neg_and_zeros_w_msb_width = (
                p_shifted_upper_lsbs_neg_and_zeros_width + 1
            )
            p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix = "uint" + str(
                p_shifted_upper_lsbs_neg_and_zeros_w_msb_width
            )
            p_shifted_upper_lsbs_neg_and_zeros_w_msb_t = (
                p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix + "_t"
            )
            p_shifted_upper_lsbs_neg_and_zeros_w_msb = (
                p_shifted_upper_lsbs_neg_and_zeros + "_w_msb"
            )
            text += (
                """
  """
                + p_shifted_upper_lsbs_neg_and_zeros_w_msb_t
                + """ """
                + p_shifted_upper_lsbs_neg_and_zeros_w_msb
                + """;
  """
                + p_shifted_upper_lsbs_neg_and_zeros_w_msb
                + """ = uint1_"""
                + p_shifted_upper_lsbs_neg_and_zeros_prefix
                + """("""
                + p_shifted_msb
                + """, """
                + p_shifted_upper_lsbs_neg_and_zeros
                + """);"""
            )

            # Concat 1 as MSB for adjusted result
            adj_width = p_shifted_upper_lsbs_neg_and_zeros_w_msb_width + 1
            # Cap shifted partiual sums to max intermediate width
            if adj_width > max_intermidate_bit_width:
                adj_width = max_intermidate_bit_width
            adj_width_prefix = "uint" + str(adj_width)
            adj_t = adj_width_prefix + "_t"
            p_shifted_adj = p_shifted + "_adj"
            text += (
                """
  """
                + adj_t
                + """ """
                + p_shifted_adj
                + """;
  """
                + p_shifted_adj
                + """ = uint1_"""
                + p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix
                + """(1, """
                + p_shifted_upper_lsbs_neg_and_zeros_w_msb
                + """);"""
            )
            var_2_type[p_shifted_adj] = adj_t

        # Mid is normal case (very similar to p==0)
        else:
            # Get lower bits of shfited
            lsbs_width = p_shifted_width - 1
            lsbs_prefix = "uint" + str(lsbs_width)
            lsbs_t = lsbs_prefix + "_t"
            p_shifted_lsbs = p_shifted + "_lsbs"
            text += (
                """
  // Mid is normal case   
  """
                + lsbs_t
                + """ """
                + p_shifted_lsbs
                + """;
  """
                + p_shifted_lsbs
                + """ = """
                + p_shifted_prefix
                + """_"""
                + str(lsbs_width - 1)
                + """_0("""
                + p_shifted
                + """);"""
            )

            # Invert msb
            p_shifted_msb_neg = p_shifted_msb + "_neg"
            text += (
                """
  """
                + msb_t
                + """ """
                + p_shifted_msb_neg
                + """;
  """
                + p_shifted_msb_neg
                + """ = ~"""
                + p_shifted_msb
                + """;"""
            )

            # Adjusted result has Concat negated msb and lsbs
            adj_width = p_shifted_width
            # Cap shifted partiual sums to max intermediate width
            if adj_width > max_intermidate_bit_width:
                adj_width = max_intermidate_bit_width
            adj_width_prefix = "uint" + str(adj_width)
            adj_t = adj_width_prefix + "_t"
            p_shifted_adj = p_shifted + "_adj"
            # ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
            text += (
                """
  """
                + adj_t
                + """ """
                + p_shifted_adj
                + """;
  """
                + p_shifted_adj
                + """ = """
                + msb_prefix
                + """_"""
                + lsbs_prefix
                + """("""
                + p_shifted_msb_neg
                + ""","""
                + p_shifted_lsbs
                + """);"""
            )
            var_2_type[p_shifted_adj] = adj_t

    # BINARY TREE SUM
    layer_nodes = []
    for p in range(0, max_input_width):
        layer_nodes.append("p" + str(p) + "_shifted_adj")

    layer = 0
    node = 0

    text += """
  // Binary summation of partial sums
"""

    # DO
    while True:
        text += (
            """
  // Layer + """
            + str(layer)
            + """
"""
        )
        node = 0
        new_layer_nodes = []
        # Write adds in pairs
        # While 2 args to add
        while len(layer_nodes) >= 2:
            left_arg = layer_nodes.pop(0)
            right_arg = layer_nodes.pop(0)
            left_t = var_2_type[left_arg]
            right_t = var_2_type[right_arg]
            # Sum type is max width
            left_width = int(
                left_t.replace("uint", "").replace("int", "").replace("_t", "")
            )
            right_width = int(
                right_t.replace("uint", "").replace("int", "").replace("_t", "")
            )
            max_width = max(left_width, right_width)
            sum_width = max_width + 1

            # Reduce sum width to max intermediate width
            if sum_width > max_intermidate_bit_width:
                sum_width = max_intermidate_bit_width

            sum_t = "uint" + str(sum_width) + "_t"
            sum_var = "sum_layer" + str(layer) + "_node" + str(node)
            var_2_type[sum_var] = sum_t
            text += (
                """ """
                + sum_t
                + """ """
                + sum_var
                + """;
  """
                + sum_var
                + """ = """
                + left_arg
                + " + "
                + right_arg
                + """;
"""
            )
            # This sum node is on next layer
            new_layer_nodes.append(sum_var)
            node += 1

        # Out of while loop
        # < 2 nodes left to sum in this node
        if len(layer_nodes) == 1:
            # One node left
            the_arg = layer_nodes.pop(0)
            the_t = var_2_type[the_arg]
            sum_t = the_t
            sum_var = "sum_layer" + str(layer) + "_node" + str(node)
            var_2_type[sum_var] = sum_t
            text += (
                """ // Odd node in layer
  """
                + sum_t
                + """ """
                + sum_var
                + """;
  """
                + sum_var
                + """ = """
                + the_arg
                + """;
  """
            )
            # This sum node is on next layer
            new_layer_nodes.append(sum_var)
            node += 1

        # WHILE
        if len(new_layer_nodes) >= 2:
            # Continue
            layer_nodes = new_layer_nodes
            layer += 1
        else:
            # DONE
            break

    # Done with outer layer while loop

    # Do return
    return_var = "sum_layer" + str(layer) + "_node" + str(node - 1)
    return_t = var_2_type[return_var]
    text += (
        """
  """
        + "// Return"
        + """
  """
        + return_t
        + """ rv;
  rv = """
        + return_var
        + """;
  return rv;
}
"""
    )

    return text
    # print text
    # sys.exit(-1)


def GET_BIN_OP_MULT_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    """
     p0[7:0] = a[0] x b[7:0] = {8{a[0]}} & b[7:0]
     p1[7:0] = a[1] x b[7:0] = {8{a[1]}} & b[7:0]
     p2[7:0] = a[2] x b[7:0] = {8{a[2]}} & b[7:0]
     p3[7:0] = a[3] x b[7:0] = {8{a[3]}} & b[7:0]
     p4[7:0] = a[4] x b[7:0] = {8{a[4]}} & b[7:0]


     p5[7:0] = a[5] x b[7:0] = {8{a[5]}} & b[7:0]
     p6[7:0] = a[6] x b[7:0] = {8{a[6]}} & b[7:0]
     p7[7:0] = a[7] x b[7:0] = {8{a[7]}} & b[7:0]
    where {8{a[0]}} means repeating a[0] (the 0th bit of a) 8 times (Verilog notation).

    To produce our product, we then need to add up all eight of our partial products, as shown here:

                                                    p0[7] p0[6] p0[5] p0[4] p0[3] p0[2] p0[1] p0[0]
                                            + p1[7] p1[6] p1[5] p1[4] p1[3] p1[2] p1[1] p1[0] 0
                                      + p2[7] p2[6] p2[5] p2[4] p2[3] p2[2] p2[1] p2[0] 0     0
                                + p3[7] p3[6] p3[5] p3[4] p3[3] p3[2] p3[1] p3[0] 0     0     0
                          + p4[7] p4[6] p4[5] p4[4] p4[3] p4[2] p4[1] p4[0] 0     0     0     0
                    + p5[7] p5[6] p5[5] p5[4] p5[3] p5[2] p5[1] p5[0] 0     0     0     0     0
              + p6[7] p6[6] p6[5] p6[4] p6[3] p6[2] p6[1] p6[0] 0     0     0     0     0     0
        + p7[7] p7[6] p7[5] p7[4] p7[3] p7[2] p7[1] p7[0] 0     0     0     0     0     0     0
    -------------------------------------------------------------------------------------------
    P[15] P[14] P[13] P[12] P[11] P[10]  P[9]  P[8]  P[7]  P[6]  P[5]  P[4]  P[3]  P[2]  P[1]  P[0]
    """
    # Need bit select
    # Need bit concat
    # Need bitwise AND
    # Have sum already

    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "uint" + str(max_input_width)
    resized_t = resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "uint" + str(output_width)

    # Temp try to reduce bit width?
    # Output width is max =  left_width+right_width
    # Actual max internal width is min out output width and ma xof input widths
    max_intermidate_bit_width = min(output_width, left_width + right_width)

    text = ""

    # Generate abs path to uint headers
    # top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    # uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
    # int_h ='''#include "''' + top_dir + '''/intN_t.h"'''

    text += (
        '''
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b x """
        + str(right_width)
        + """b mult
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize
  """
        + resized_t
        + """ left_resized;
  left_resized = left;
  """
        + resized_t
        + """ right_resized;
  right_resized = right;
  
  // Left repeated bit unsigneds
"""
    )
    for rb in range(0, max_input_width):
        text += (
            """ // BIT"""
            + str(rb)
            + """ REPEATED
  // Select bit
  uint1_t left"""
            + str(rb)
            + """_x1;
  left"""
            + str(rb)
            + """_x1 = """
            + resized_prefix
            + """_"""
            + str(rb)
            + """_"""
            + str(rb)
            + """(left_resized);
  // Dup
  uint"""
            + str(max_input_width)
            + """_t  left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """;
  left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """ = uint1_"""
            + str(max_input_width)
            + """(left"""
            + str(rb)
            + """_x1);
"""
        )

    text += """
  // Partial sums
"""
    for rb in range(0, max_input_width):
        text += (
            " "
            + resized_t
            + """ p"""
            + str(rb)
            + """;
  p"""
            + str(rb)
            + """ = left"""
            + str(rb)
            + """_x"""
            + str(max_input_width)
            + """ & right_resized;
"""
        )
    # Save types of vars for ease later
    var_2_type = {}

    # Cap shifted partiual sums to max intermediate width
    max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
    max_intermidate_t = max_intermidate_prefix + "_t"

    text += (
        """
  // Shifted partial sums
  """
        + resized_t
        + """ p0_shifted;
  p0_shifted = p0;
"""
    )
    var_2_type["p0_shifted"] = resized_t
    for p in range(1, max_input_width):
        uintp_prefix = "uint" + str(p)
        uintp_t = uintp_prefix + "_t"
        p_width = max_input_width
        # p_width_minus1 = p_width - 1
        p_t_prefix = "uint" + str(p_width)

        p_shifted_width = p_width + p
        # Cap shifted partiual sums to max intermediate width
        if p_shifted_width > max_intermidate_bit_width:
            p_shifted_width = max_intermidate_bit_width
        p_shifted_t = "uint" + str(p_shifted_width) + "_t"

        p_shifted = """p""" + str(p) + """_shifted"""
        var_2_type[p_shifted] = p_shifted_t

        text += (
            """ """
            + uintp_t
            + """ zero_x"""
            + str(p)
            + """;
  zero_x"""
            + str(p)
            + """ = 0;
  """
            + p_shifted_t
            + """ p"""
            + str(p)
            + """_shifted;
  p"""
            + str(p)
            + """_shifted = """
            + p_t_prefix
            + """_"""
            + uintp_prefix
            + """(p"""
            + str(p)
            + """ ,zero_x"""
            + str(p)
            + """);
"""
        )

    layer_nodes = []
    for p in range(0, max_input_width):
        layer_nodes.append("p" + str(p) + "_shifted")

    layer = 0
    node = 0

    text += """
  // Binary summation of partial sums
"""

    # DO
    while True:
        text += (
            """
  // Layer + """
            + str(layer)
            + """
"""
        )
        node = 0
        new_layer_nodes = []
        # Write adds in pairs
        # While 2 args to add
        while len(layer_nodes) >= 2:
            left_arg = layer_nodes.pop(0)
            right_arg = layer_nodes.pop(0)
            left_t = var_2_type[left_arg]
            right_t = var_2_type[right_arg]
            # Sum type is max width
            left_width = int(
                left_t.replace("uint", "").replace("int", "").replace("_t", "")
            )
            right_width = int(
                right_t.replace("uint", "").replace("int", "").replace("_t", "")
            )
            max_width = max(left_width, right_width)
            sum_width = max_width + 1

            # Reduce sum width to max intermediate width
            if sum_width > max_intermidate_bit_width:
                sum_width = max_intermidate_bit_width

            sum_t = "uint" + str(sum_width) + "_t"
            sum_var = "sum_layer" + str(layer) + "_node" + str(node)
            var_2_type[sum_var] = sum_t
            text += (
                """ """
                + sum_t
                + """ """
                + sum_var
                + """;
  """
                + sum_var
                + """ = """
                + left_arg
                + " + "
                + right_arg
                + """;
"""
            )
            # This sum node is on next layer
            new_layer_nodes.append(sum_var)
            node += 1

        # Out of while loop
        # < 2 nodes left to sum in this node
        if len(layer_nodes) == 1:
            # One node left
            the_arg = layer_nodes.pop(0)
            the_t = var_2_type[the_arg]
            sum_t = the_t
            sum_var = "sum_layer" + str(layer) + "_node" + str(node)
            var_2_type[sum_var] = sum_t
            text += (
                """ // Odd node in layer
  """
                + sum_t
                + """ """
                + sum_var
                + """;
  """
                + sum_var
                + """ = """
                + the_arg
                + """;
  """
            )
            # This sum node is on next layer
            new_layer_nodes.append(sum_var)
            node += 1

        # WHILE
        if len(new_layer_nodes) >= 2:
            # Continue
            layer_nodes = new_layer_nodes
            layer += 1
        else:
            # DONE
            break

    # Done with outer layer while loop

    # Do return
    return_var = "sum_layer" + str(layer) + "_node" + str(node - 1)
    return_t = var_2_type[return_var]
    text += (
        """
  """
        + "// Return"
        + """
  """
        + return_t
        + """ rv;
  rv = """
        + return_var
        + """;
  return rv;
}
"""
    )

    return text
    # print text
    # sys.exit(-1)


# 128 LLs in own code
# 192 lls as VHDL
# TODO: Is this bad/broken? test edge cases
def GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "uint" + str(max_input_width)
    resized_t = resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "uint" + str(output_width)

    text = ""

    text += (
        '''
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b / """
        + str(right_width)
        + """b div
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize
  """
        + resized_t
        + """ left_resized;
  left_resized = left;
  """
        + resized_t
        + """ right_resized;
  right_resized = right;
  
  // Output
  """
        + resized_t
        + """ output;
  output = 0;
  // Remainder
  """
        + resized_t
        + """ remainder;
  remainder = 0;
  uint1_t new_remainder0; 
  

  /*
  UNROLL THIS
  remainder := 0
  -- Where n is number of bits in left           
  for i := n - 1 .. 0 do     
    -- Left-shift remainder by 1 bit     
    remainder := remainder << 1
    -- Set the least-significant bit of remainder
    -- equal to bit i of the numerator
    remainder(0) := left(i)       
    if remainder >= right then
      remainder := remainder - right
      output(i) := 1
    end
  end 
  */
  """
    )

    for i in range(max_input_width - 1, -1, -1):
        text += (
            """
  // Bit """
            + str(i)
            + """
  new_remainder0 = """
            + resized_prefix
            + """_"""
            + str(i)
            + """_"""
            + str(i)
            + """(left);
  remainder = """
            + resized_prefix
            + """_uint1(remainder, new_remainder0);       
  if(remainder >= right)
  {
    remainder = remainder - right;
    // Set output(i)=1
    output = """
            + output_prefix
            + """_uint1_"""
            + str(i)
            + """(output, 1);
  }"""
        )

    text += """
  return output;
}"""

    # print(text)
    # sys.exit(-1)

    return text


# TODO something better than copying DIV code?
def GET_BIN_OP_MOD_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "uint" + str(max_input_width)
    resized_t = resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "uint" + str(output_width)

    text = ""

    text += (
        '''
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b % """
        + str(right_width)
        + """b mod
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  // Resize
  """
        + resized_t
        + """ left_resized;
  left_resized = left;
  """
        + resized_t
        + """ right_resized;
  right_resized = right;
  
  // Output
  """
        + resized_t
        + """ output;
  output = 0;
  // Remainder
  """
        + resized_t
        + """ remainder;
  remainder = 0;
  uint1_t new_remainder0; 
  

  /*
  UNROLL THIS
  remainder := 0
  -- Where n is number of bits in left           
  for i := n - 1 .. 0 do     
    -- Left-shift remainder by 1 bit     
    remainder := remainder << 1
    -- Set the least-significant bit of remainder
    -- equal to bit i of the numerator
    remainder(0) := left(i)       
    if remainder >= right then
      remainder := remainder - right
      output(i) := 1
    end
  end 
  */
  """
    )

    for i in range(max_input_width - 1, -1, -1):
        text += (
            """
  // Bit """
            + str(i)
            + """
  new_remainder0 = """
            + resized_prefix
            + """_"""
            + str(i)
            + """_"""
            + str(i)
            + """(left);
  remainder = """
            + resized_prefix
            + """_uint1(remainder, new_remainder0);       
  if(remainder >= right)
  {
    remainder = remainder - right;
    // Set output(i)=1
    output = """
            + output_prefix
            + """_uint1_"""
            + str(i)
            + """(output, 1);
  }"""
        )

    text += """
  return remainder;
}"""

    # print(text)
    # sys.exit(-1)

    return text


# TODO do something better than absolute value uint division and sign correction?
def GET_BIN_OP_DIV_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "int" + str(max_input_width)
    unsigned_resized_prefix = "u" + resized_prefix  # "uint" + str(max_input_width-1)
    resized_t = resized_prefix + "_t"
    unsigned_resized_t = unsigned_resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "int" + str(output_width)

    text = ""

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b / """
        + str(right_width)
        + """b div
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  
  // Record sign bits
  uint1_t l_signed = """
        + resized_prefix
        + "_"
        + str(left_width - 1)
        + """_"""
        + str(left_width - 1)
        + """(left);
  uint1_t r_signed = """
        + resized_prefix
        + "_"
        + str(right_width - 1)
        + """_"""
        + str(right_width - 1)
        + """(right);

  // Resize to unsigned values of same width 
  """
        + unsigned_resized_t
        + """ left_resized = """
        + resized_prefix
        + """_abs(left);
  """
        + unsigned_resized_t
        + """ right_resized = """
        + resized_prefix
        + """_abs(right);

  // Do div on uints
  """
        + unsigned_resized_t
        + """ unsigned_result = left_resized / right_resized;

  // Adjust sign
  """
        + output_t
        + """ output = unsigned_result;
  if(l_signed ^ r_signed)
  {
    output = -unsigned_result;
  }

  return output;
}"""
    )

    # print(text)
    # sys.exit(-1)

    return text


# TODO is the sign fixing here right for signed modulo?
def GET_BIN_OP_MOD_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
    left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
    right_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.inputs[1]
    ]
    output_t = partially_complete_logic.wire_to_c_type[
        partially_complete_logic.outputs[0]
    ]
    left_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
    right_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
    max_input_width = max(left_width, right_width)
    resized_prefix = "int" + str(max_input_width)
    unsigned_resized_prefix = "u" + resized_prefix  # "uint" + str(max_input_width-1)
    resized_t = resized_prefix + "_t"
    unsigned_resized_t = unsigned_resized_prefix + "_t"
    output_width = LOGIC.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)
    output_prefix = "int" + str(output_width)

    text = ""

    text += (
        '''
#include "intN_t.h"
#include "uintN_t.h"
#include "'''
        + LOGIC.BIT_MANIP_HEADER_FILE
        + """"

// """
        + str(left_width)
        + """b % """
        + str(right_width)
        + """b mod
"""
        + output_t
        + """ """
        + partially_complete_logic.func_name
        + """("""
        + left_t
        + """ left, """
        + right_t
        + """ right)
{
  
  // Record sign bits
  uint1_t l_signed = """
        + resized_prefix
        + "_"
        + str(left_width - 1)
        + """_"""
        + str(left_width - 1)
        + """(left);
  uint1_t r_signed = """
        + resized_prefix
        + "_"
        + str(right_width - 1)
        + """_"""
        + str(right_width - 1)
        + """(right);

  // Resize to unsigned values of same width 
  """
        + unsigned_resized_t
        + """ left_resized = """
        + resized_prefix
        + """_abs(left);
  """
        + unsigned_resized_t
        + """ right_resized = """
        + resized_prefix
        + """_abs(right);

  // Do mod on uints
  """
        + unsigned_resized_t
        + """ unsigned_result = left_resized % right_resized;

  // Adjust sign
  """
        + output_t
        + """ output = unsigned_result;
  if(l_signed ^ r_signed)
  {
    output = -unsigned_result;
  }

  return output;
}"""
    )

    # print(text)
    # sys.exit(-1)

    return text

