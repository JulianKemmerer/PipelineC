import copy
import sys
import os

import C_TO_LOGIC
from pycparser import c_ast, c_generator

# FSM funcs cant be main functions

# TODO change primary data type to "CFG"=pointer to tree root and set of all nodes
# FOR NOW CAN TRUST FIRST STATE IN LIST (last in reversed list) TO BE ENTRY/FIRST POINTER?
# Dont need curr_state_info since will be working backwards now anyway

FSM_EXT = "_FSM"
CLK_FUNC = "__clk"
INPUT_FUNC = "__in"
YIELD_FUNC = "__out"
INOUT_FUNC = "__io"


def C_AST_NODE_TO_C_CODE(
    c_ast_node, parser_state, state_info, indent="", generator=None, use_semicolon=True
):
    if generator is None:
        generator = c_generator.CGenerator()

    # If subroutine rename all vars
    if (
        state_info is not None
        and state_info.sub_func_name
        and state_info.sub_func_name in parser_state.func_to_local_variables
    ):
        # sub_func_logic = parser_state.FuncLogicLookupTable[state_info.sub_func_name]
        # make copy to modify and render from? wtf idk
        c_ast_node = copy.deepcopy(c_ast_node)
        # print("state_info.sub_func_name",state_info.sub_func_name)
        # print(c_ast_node)
        # Decl(name='local_var',
        # TypeDecl(declname='local_var',
        # ID(name='local_var' , ID(name='input_arg'
        nodes_to_rename = set()
        nodes_to_rename |= set(
            C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.Decl)
        )
        nodes_to_rename |= set(
            C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.TypeDecl)
        )
        # nodes_to_rename |= set(C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.ID))
        nodes_to_rename |= set(
            C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_VARIABLE_IDS(c_ast_node)
        )
        # print("sub_func_logic.inputs",sub_func_logic.inputs)
        # print("sub_func_logic.variable_names",sub_func_logic.variable_names)
        local_vars = parser_state.func_to_local_variables[state_info.sub_func_name]
        # print("local_vars",local_vars)
        for node_to_rename in nodes_to_rename:
            if (type(node_to_rename) == c_ast.Decl) or (
                type(node_to_rename) == c_ast.ID
            ):
                if node_to_rename.name in local_vars:
                    node_to_rename.name = (
                        state_info.sub_func_name + "_" + node_to_rename.name
                    )
            else:  # TypeDecl
                if node_to_rename.declname in local_vars:
                    node_to_rename.declname = (
                        state_info.sub_func_name + "_" + node_to_rename.declname
                    )

    text = generator.visit(c_ast_node)

    # What nodes need curlys?
    if type(c_ast_node) == c_ast.InitList:
        text = "{" + text + "}"

    # What nodes dont need semicolon?
    if use_semicolon:
        maybe_semicolon = ";"
    else:
        maybe_semicolon = ""
    if type(c_ast_node) == c_ast.Compound:
        maybe_semicolon = ""
    elif type(c_ast_node) == c_ast.If:
        maybe_semicolon = ""
    elif type(c_ast_node) == c_ast.While:
        maybe_semicolon = ""
    elif type(c_ast_node) == c_ast.For:
        maybe_semicolon = ""
    """
  elif type(c_ast_node) == c_ast.ArrayRef and is_lhs:
    maybe_semicolon = ""
  elif type(c_ast_node) == c_ast.Decl and is_lhs:
    maybe_semicolon = ""
  elif type(c_ast_node) == c_ast.ID and is_lhs:
    maybe_semicolon = ""
  """
    # print(type(c_ast_node))
    text += maybe_semicolon

    lines = []
    for line in text.split("\n"):
        if line != "":
            lines.append(indent + line)
    # + "\n"
    return "\n".join(lines)


class FsmStateInfo:
    def __init__(self):
        self.name = None
        self.sub_func_name = None  # Name of subroutine function this state belongs to if any (i.e. non-MAIN thread)
        self.c_ast_nodes = []  # C ast nodes
        self.always_next_state = None  # State info obj
        self.branch_nodes_tf_states = None  # (c_ast_node,true state, false state)
        self.ends_w_clk = False
        self.clk_end_is_user = True
        self.return_node = None
        self.input_func_call_node = None
        self.yield_func_call_node = None
        self.inout_func_call_node = None
        self.ends_w_fsm_func_entry = None  # C ast node of func call
        self.ends_w_fsm_func_entry_input_drivers = None
        self.single_inst_func_name = None  # State is for this name of single inst
        self.starts_w_fsm_func_return = None  # C ast node of func call
        self.starts_w_fsm_func_return_output_driven_things = None

    def print(self):
        print(str(self.name))
        if self.sub_func_name:
            print(f"Subroutine: {self.sub_func_name}")

        if self.starts_w_fsm_func_return is not None:
            print(self.starts_w_fsm_func_return.name.name + "_FSM() // Return;")

        if self.always_next_state is not None:
            print("Default Next:", self.always_next_state.name)

        generator = c_generator.CGenerator()
        if len(self.c_ast_nodes) > 0:
            print("Comb logic:")
            for c_ast_node in self.c_ast_nodes:
                print(generator.visit(c_ast_node))

        if self.branch_nodes_tf_states is not None:
            print("Branch logic")
            mux_node, true_state, false_state = self.branch_nodes_tf_states
            if false_state is None:
                print(
                    generator.visit(mux_node.cond),
                    "?",
                    true_state.name,
                    ":",
                    "<default next state>",
                )
            else:
                print(
                    generator.visit(mux_node.cond),
                    "?",
                    true_state.name,
                    ":",
                    false_state.name,
                )

        if self.ends_w_clk:
            if self.clk_end_is_user:
                print("Delay: __clk();")
            else:
                print("FORCED DELAY __clk();")

        if self.ends_w_fsm_func_entry is not None:
            print(self.ends_w_fsm_func_entry.name.name + "_FSM() // Entry;")

        if self.single_inst_func_name is not None:
            print(self.single_inst_func_name + "_FSM() // State;")

        if self.return_node is not None:
            print("Return, function end")
            return  # Return is always last

        if self.input_func_call_node is not None:
            print("__input();")
            return

        if self.yield_func_call_node is not None:
            print("__yield();")
            return

        if self.inout_func_call_node is not None:
            print("__inout();")
            return


def GET_SUB_FUNC_ONE_HOT_VAR_ASSIGN_REPLACEMENT_C_CODE(
    state_info, fsm_logic, parser_state
):
    text = ""
    # Use FIND_EXIT_STATES to list out and compare instead of ONE_HOT_VAR_ASSIGN
    # IS parser_state.existing_logic right?
    existing_logic = parser_state.existing_logic
    parser_state.existing_logic = fsm_logic  # ?
    poss_exit_states = FIND_EXIT_STATES(state_info.sub_func_name, parser_state)
    parser_state.existing_logic = existing_logic
    if len(poss_exit_states) == 1:
        text += "    // ONE POSSIBLE EXIT: \n"
        text += (
            """    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, """
            + poss_exit_states[0].name
            + ", "
            + state_info.name
            + """)\n"""
        )
    else:
        text += "    // POSSIBLE EXITS: \n"
        for exit_i, poss_exit_state in enumerate(poss_exit_states):
            text += (
                """    if(ONE_HOT_CONST_EQ("""
                + state_info.sub_func_name
                + "_FUNC_CALL_RETURN_FSM_STATE, "
                + poss_exit_state.name
                + """))
    {
      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, """
                + poss_exit_state.name
                + ", "
                + state_info.name
                + """)
    }\n"""
            )

    return text


def STATE_GROUP_TO_C_CODE(
    state_group,
    state_group_i,
    fsm_logic,
    parser_state,
    generator,
    single_inst_flow_ctrl_func_call_names,
    first_state_in_group=True,
    elif_str="else if",
):
    text = ""
    for state_info in state_group:
        # Pass through if starts a group of parallel states
        if first_state_in_group:
            text += "  // State group " + str(state_group_i) + "\n"
            text += "  if("
        else:
            # Can use IF instead of ELSE-IF since can one be in one state from each group
            # and dont need priority logic - works especially well as one hot
            # but then any assignments in the suposedly parrallel section appear as sequential?
            # dont use?
            text += f"  {elif_str}("
        first_state_in_group = False
        text += "ONE_HOT_CONST_EQ(FSM_STATE," + state_info.name + "))\n"
        text += "  {\n"

        # Returning from func call
        if state_info.starts_w_fsm_func_return is not None:
            text += (
                "    // "
                + state_info.starts_w_fsm_func_return.name.name
                + " "
                + C_TO_LOGIC.C_AST_NODE_COORD_STR(state_info.starts_w_fsm_func_return)
                + " FUNC CALL RETURN \n"
            )
            called_func_name = state_info.starts_w_fsm_func_return.name.name
            output_driven_things = (
                state_info.starts_w_fsm_func_return_output_driven_things
            )
            if len(output_driven_things) > 0:
                # Connect func output wires
                # What func is being called?
                called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
                # Do outputs
                output_tok = "_"
                if called_func_name in single_inst_flow_ctrl_func_call_names:
                    output_tok = "_o."
                for output_i, output_port in enumerate(called_func_logic.outputs):
                    output_driven_thing_i = output_driven_things[output_i]
                    if isinstance(output_driven_thing_i, c_ast.Node):
                        text += (
                            "    "
                            + C_AST_NODE_TO_C_CODE(
                                output_driven_thing_i,
                                parser_state,
                                state_info,
                                "",
                                generator,
                                use_semicolon=False,
                            )
                            + " = "
                            + called_func_name
                            + output_tok
                            + output_port
                            + ";\n"
                        )
                    else:
                        text += (
                            "    "
                            + output_driven_thing_i
                            + " = "
                            + called_func_name
                            + output_tok
                            + output_port
                            + ";\n"
                        )
            else:
                text += "    // UNUSED OUTPUT = " + called_func_name + "();\n"

        # Comb logic c ast nodes
        if len(state_info.c_ast_nodes) > 0:
            for c_ast_node in state_info.c_ast_nodes:
                # Skip special control flow nodes
                # Return
                if c_ast_node == state_info.return_node:
                    continue
                # TODO fix needing ";"
                # Fix print out to be tabbed out
                # HACKY AF OMG remove static decls
                c_code_text = C_AST_NODE_TO_C_CODE(
                    c_ast_node, parser_state, state_info, "    ", generator
                )
                c_code_text = c_code_text.replace("static ", "// static ")
                text += c_code_text + "\n"

        # Branch logic
        if state_info.branch_nodes_tf_states is not None:
            mux_node, true_state, false_state = state_info.branch_nodes_tf_states
            cond_code = C_AST_NODE_TO_C_CODE(
                mux_node.cond, parser_state, state_info, "", generator, False
            )
            text += "    if(" + cond_code + ")\n"
            text += "    {\n"
            text += (
                "      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, "
                + true_state.name
                + ", "
                + state_info.name
                + ")\n"
            )
            text += "    }\n"
            if false_state is not None:
                text += "    else\n"
                text += "    {\n"
                text += (
                    "      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, "
                    + false_state.name
                    + ", "
                    + state_info.name
                    + ")\n"
                )
                text += "    }\n"
            else:  # No next state, just return/exit/start over?
                text += "    else\n"
                text += "    {\n"
                if state_info.sub_func_name is not None:
                    if state_info.always_next_state is not None:
                        raise Exception(
                            "Subroutine branching exit has always next set? Instead of using a FUNC_CALL_RETURN_FSM_STATE?"
                        )
                    text += (
                        "      // Subroutine branch exiting to scheduled return state\n"
                    )
                    text += GET_SUB_FUNC_ONE_HOT_VAR_ASSIGN_REPLACEMENT_C_CODE(
                        state_info, fsm_logic, parser_state
                    )
                else:
                    # Main/single inst exit end execution
                    text += "      // No next state, return and start over?\n"
                    text += (
                        "      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, RETURN_REG, "
                        + state_info.name
                        + ")\n"
                    )
                    text += (
                        "      ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, ENTRY_REG, NUM_STATES"
                        + "_"
                        + fsm_logic.func_name
                        + ")\n"
                    )
                text += "    }\n"
            text += "  }\n"
            continue

        # Func call entry
        if state_info.ends_w_fsm_func_entry is not None:
            func_call_node = state_info.ends_w_fsm_func_entry
            called_func_name = func_call_node.name.name
            entry_state, exit_state = fsm_logic.func_call_node_to_entry_exit_states[
                func_call_node
            ]
            func_call_state = (
                entry_state.always_next_state
            )  # fsm_logic.func_call_name_to_state[called_func_name]
            text += (
                "    // "
                + func_call_node.name.name
                + " "
                + C_TO_LOGIC.C_AST_NODE_COORD_STR(func_call_node)
                + " FUNC CALL ENTRY \n"
            )
            input_drivers = state_info.ends_w_fsm_func_entry_input_drivers
            # Connect func input wires, go to func call state
            # What func is being called?
            called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
            # Do inputs
            input_tok = "_"
            if called_func_name in single_inst_flow_ctrl_func_call_names:
                input_tok = "_i."
            for input_i, input_port in enumerate(called_func_logic.inputs):
                input_driver_i = input_drivers[input_i]
                if isinstance(input_driver_i, c_ast.Node):
                    text += (
                        "    "
                        + called_func_name
                        + input_tok
                        + input_port
                        + " = "
                        + C_AST_NODE_TO_C_CODE(
                            input_driver_i, parser_state, state_info, "", generator
                        )
                        + "\n"
                    )
                else:
                    text += (
                        "    "
                        + called_func_name
                        + input_tok
                        + input_port
                        + " = "
                        + input_driver_i
                        + ";\n"
                    )
            # text += "\n"
            # text += "    // SUBROUTINE STATE NEXT\n"
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, "
                + func_call_state.name
                + ", "
                + state_info.name
                + ")\n"
            )
            # Set state to return to after func call
            # text += "    // Followed by return state\n"
            text += "    // Return state saved for func return\n"
            if called_func_name in single_inst_flow_ctrl_func_call_names:
                text += (
                    "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, "
                    + exit_state.name
                    + ", NUM_STATES"
                    + "_"
                    + fsm_logic.func_name
                    + ")\n"
                )
            else:
                # Instead of ONE_HOT_CONST_ASSIGN over all one hot bits
                # Just loop and check over possible states
                # IS parser_state.existing_logic right?
                existing_logic = parser_state.existing_logic
                parser_state.existing_logic = fsm_logic  # ?
                poss_exit_states = FIND_EXIT_STATES(called_func_name, parser_state)
                parser_state.existing_logic = existing_logic
                if len(poss_exit_states) == 1:
                    text += "    // ONE POSSIBLE EXIT, just set the bit: \n"
                    text += (
                        "    "
                        + called_func_name
                        + """_FUNC_CALL_RETURN_FSM_STATE["""
                        + poss_exit_states[0].name
                        + """] = 1;\n"""
                    )
                else:
                    text += (
                        "    // Returning to "
                        + exit_state.name
                        + " state, clearing other possible exits: \n"
                    )
                    for exit_i, poss_exit_state in enumerate(poss_exit_states):
                        text += (
                            """    if("""
                            + poss_exit_state.name
                            + """=="""
                            + exit_state.name
                            + """){
      """
                            + called_func_name
                            + """_FUNC_CALL_RETURN_FSM_STATE["""
                            + poss_exit_state.name
                            + """] = 1;
    }else{
      """
                            + called_func_name
                            + """_FUNC_CALL_RETURN_FSM_STATE["""
                            + poss_exit_state.name
                            + """] = 0;
    }\n"""
                        )
            if state_info.ends_w_clk and not state_info.clk_end_is_user:
                text += "    // FUNC ENTRY FORCED CLK DELAY IMPLIED\n"
            text += "  }\n"
            continue

        # Func call state (now only used for single inst)
        if state_info.single_inst_func_name is not None:
            called_func_name = state_info.single_inst_func_name
            # ok to use wires driving inputs, not regs (included in func)
            text += (
                """    """
                + called_func_name
                + """_i.input_valid = 1;
    """
                + called_func_name
                + """_i.output_ready = 1;\n"""
            )
            # Single inst uses global wires
            if called_func_name in parser_state.func_single_inst_header_included:
                text += (
                    """    // """
                    + state_info.single_inst_func_name
                    + """ single instance FUNC CALL"""
                )
                text += (
                    """
    WIRE_WRITE("""
                    + called_func_name
                    + """_INPUT_t, """
                    + called_func_name
                    + """_arb_inputs, """
                    + called_func_name
                    + """_i)
    WIRE_READ("""
                    + called_func_name
                    + """_OUTPUT_t, """
                    + called_func_name
                    + """_o, """
                    + called_func_name
                    + """_arb_outputs)
"""
                )
            text += (
                """    if("""
                + called_func_name
                + """_o.output_valid)
    {
      // Go to signaled return state
      ONE_HOT_VAR_ASSIGN(FSM_STATE, FUNC_CALL_RETURN_FSM_STATE, NUM_STATES"""
                + "_"
                + fsm_logic.func_name
                + """)
    }\n"""
            )
            text += "  }\n"
            continue

        # Return?
        if state_info.return_node is not None:
            output_maybe_func_and_tok = C_TO_LOGIC.RETURN_WIRE_NAME + "_FSM"
            if state_info.sub_func_name is not None:
                if state_info.sub_func_name in single_inst_flow_ctrl_func_call_names:
                    # Single inst
                    output_maybe_func_and_tok = state_info.sub_func_name + "_"
                else:
                    # Regular inline subroutine return
                    output_maybe_func_and_tok = (
                        state_info.sub_func_name + "_" + C_TO_LOGIC.RETURN_WIRE_NAME
                    )
            text += (
                "    "
                + output_maybe_func_and_tok
                + " = "
                + C_AST_NODE_TO_C_CODE(
                    state_info.return_node.expr, parser_state, state_info, "", generator
                )
                + "\n"
            )
            if state_info.sub_func_name is not None:
                text += "    // Subroutine returning to scheduled return state\n"
                text += GET_SUB_FUNC_ONE_HOT_VAR_ASSIGN_REPLACEMENT_C_CODE(
                    state_info, fsm_logic, parser_state
                )
                text += "  }\n"
                continue
            else:
                # Main/single inst return end execution
                text += "    // Return, end execution by maybe going back to entry\n"
                text += (
                    "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, RETURN_REG, "
                    + state_info.name
                    + ")\n"
                )
                text += (
                    "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, ENTRY_REG, NUM_STATES"
                    + "_"
                    + fsm_logic.func_name
                    + ")\n"
                )
                text += "  }\n"
                continue

        # Delay clk?
        if state_info.ends_w_clk:
            # Go to next state, but delayed
            if state_info.clk_end_is_user:
                text += "    // __clk(); // Go to next state in next clock cycle \n"
            else:
                text += (
                    "    // FORCED CLK DELAY - Go to next state in next clock cycle \n"
                )
            text += "    // MUST OCCUR IN LAST STAGE GROUP WITH RETURN HANDSHAKE \n"
            if state_info.always_next_state is None:
                if state_info.sub_func_name is not None:
                    text += "      // Subroutine delay clk exiting to scheduled return state\n"
                    text += GET_SUB_FUNC_ONE_HOT_VAR_ASSIGN_REPLACEMENT_C_CODE(
                        state_info, fsm_logic, parser_state
                    )
                else:
                    # Main/single inst exit end execution
                    text += "      // No next state, return and start over?\n"
                    text += (
                        "      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, RETURN_REG, "
                        + state_info.name
                        + ")\n"
                    )
                    text += (
                        "      ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, ENTRY_REG, NUM_STATES"
                        + "_"
                        + fsm_logic.func_name
                        + ")\n"
                    )
            else:
                text += (
                    "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, "
                    + state_info.always_next_state.name
                    + ", "
                    + state_info.name
                    + ")\n"
                )
            text += "  }\n"
            continue

        # Input func
        if state_info.input_func_call_node is not None:
            text += "    // Get new inputs, continue execution\n"
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, ENTRY_REG, "
                + state_info.name
                + ")\n"
            )
            text += (
                "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, "
                + state_info.always_next_state.name
                + ", NUM_STATES"
                + "_"
                + fsm_logic.func_name
                + ")\n"
            )
            text += "  }\n"
            continue

        # Yield func
        if state_info.yield_func_call_node is not None:
            text += "    // Yield output data, continue execution\n"
            yield_arg_code = C_AST_NODE_TO_C_CODE(
                state_info.yield_func_call_node.args.exprs[0],
                parser_state,
                state_info,
                "",
                generator,
            )
            text += (
                "    "
                + C_TO_LOGIC.RETURN_WIRE_NAME
                + FSM_EXT
                + " = "
                + yield_arg_code
                + "\n"
            )
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, RETURN_REG, "
                + state_info.name
                + ")\n"
            )
            text += (
                "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, "
                + state_info.always_next_state.name
                + ", NUM_STATES"
                + "_"
                + fsm_logic.func_name
                + ")\n"
            )
            text += "  }\n"
            continue

        # Inout func
        if state_info.inout_func_call_node is not None:
            text += (
                "    // In+out accept input and yield output data, continue execution\n"
            )
            inout_arg_code = C_AST_NODE_TO_C_CODE(
                state_info.inout_func_call_node.args.exprs[0],
                parser_state,
                state_info,
                "",
                generator,
            )
            text += (
                "    "
                + C_TO_LOGIC.RETURN_WIRE_NAME
                + FSM_EXT
                + " = "
                + inout_arg_code
                + "\n"
            )
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, ENTRY_RETURN_OUT, "
                + state_info.name
                + ")\n"
            )
            text += (
                "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, "
                + state_info.always_next_state.name
                + ", NUM_STATES"
                + "_"
                + fsm_logic.func_name
                + ")\n"
            )
            text += "  }\n"
            continue

        # Default next
        if state_info.always_next_state is not None:
            text += "    // DEFAULT NEXT\n"
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, "
                + state_info.always_next_state.name
                + ", "
                + state_info.name
                + ")\n"
            )
            text += "  }\n"
            continue

        # At this point the stage assumed to be returning/done?
        # From a subroutine or main?
        if state_info.sub_func_name is not None:
            text += "    // Assumed subroutine returning to scheduled return state\n"
            text += GET_SUB_FUNC_ONE_HOT_VAR_ASSIGN_REPLACEMENT_C_CODE(
                state_info, fsm_logic, parser_state
            )
            text += "  }\n"
        else:
            text += "    // ASSUMED EMPTY DELAY STATE FOR RETURN\n"
            text += (
                "    ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, RETURN_REG, "
                + state_info.name
                + ")\n"
            )
            text += (
                "    ONE_HOT_CONST_ASSIGN(FUNC_CALL_RETURN_FSM_STATE, ENTRY_REG, NUM_STATES"
                + "_"
                + fsm_logic.func_name
                + ")\n"
            )
            text += "  }\n"

    return text


def FSM_LOGIC_TO_C_CODE(fsm_logic, parser_state):
    generator = c_generator.CGenerator()
    text = ""

    # Get all single inst flow ctrl funcs
    single_inst_flow_ctrl_func_call_names = set()
    func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
        fsm_logic.c_ast_node, c_ast.FuncCall
    )
    for func_call_node in func_call_nodes:
        func_call_name = func_call_node.name.name
        if (
            C_AST_NODE_USES_CTRL_FLOW_NODE(func_call_node, parser_state)
            and func_call_name != CLK_FUNC
            and func_call_name != INPUT_FUNC
            and func_call_name != YIELD_FUNC
            and func_call_name != INOUT_FUNC
        ):
            if func_call_name in parser_state.func_single_inst_header_included:
                single_inst_flow_ctrl_func_call_names.add(func_call_node.name.name)

    # Woods – Moving to the Left
    # WHat funcs does this func call
    uses_io_func = False
    if fsm_logic.func_name in parser_state.func_name_to_calls:
        called_funcs = parser_state.func_name_to_calls[fsm_logic.func_name]
        uses_io_func = INOUT_FUNC in called_funcs
        for called_func in called_funcs:
            if called_func in parser_state.FuncLogicLookupTable:
                called_func_logic = parser_state.FuncLogicLookupTable[called_func]
                if called_func in single_inst_flow_ctrl_func_call_names:
                    text += (
                        '#include "'
                        + called_func_logic.func_name
                        + FSM_EXT
                        + ".h"
                        + '"\n'
                    )

    # Need one hot helpers
    text += '#include "one_hot.h"\n'

    # States enum as one hot
    one_hot_states_text = "  // One hot states indices\n"
    # Entry
    one_hot_index = 0
    one_hot_states_text += "uint32_t ENTRY_REG" + " = " + str(one_hot_index) + ";\n"
    one_hot_index += 1
    # Extra IO in single stage
    if uses_io_func:
        one_hot_states_text += (
            "uint32_t ENTRY_RETURN_IN" + " = " + str(one_hot_index) + ";\n"
        )
        one_hot_index += 1
        one_hot_states_text += (
            "uint32_t ENTRY_RETURN_OUT" + " = " + str(one_hot_index) + ";\n"
        )
        one_hot_index += 1
    # User states
    for state_group in fsm_logic.state_groups:
        for state_info in state_group:
            one_hot_states_text += (
                "uint32_t " + state_info.name + " = " + str(one_hot_index) + ";\n"
            )
            if state_info.name == fsm_logic.first_user_state.name:
                text += (
                    "#define FIRST_STATE"
                    + "_"
                    + fsm_logic.func_name
                    + " "
                    + str(one_hot_index)
                    + "\n"
                )
            one_hot_index += 1
    # Return
    one_hot_states_text += "uint32_t RETURN_REG" + " = " + str(one_hot_index) + ";\n"
    one_hot_index += 1
    num_states = one_hot_index
    text += (
        "#define NUM_STATES" + "_" + fsm_logic.func_name + " " + str(num_states) + "\n"
    )

    # Input Struct
    text += (
        """
typedef struct """
        + fsm_logic.func_name
        + """_INPUT_t
{
  uint1_t input_valid;
"""
    )
    for input_port in fsm_logic.inputs:
        c_type = fsm_logic.wire_to_c_type[input_port]
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            text += "  " + elem_t + " " + input_port
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ";\n"
        else:
            text += "  " + c_type + " " + input_port + ";\n"
    text += (
        """  uint1_t output_ready;
}"""
        + fsm_logic.func_name
        + """_INPUT_t;
typedef struct """
        + fsm_logic.func_name
        + """_OUTPUT_t
{
  uint1_t input_ready;
"""
    )
    for output_port in fsm_logic.outputs:
        c_type = fsm_logic.wire_to_c_type[output_port]
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            text += "  " + elem_t + " " + output_port
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ";\n"
        else:
            text += "  " + c_type + " " + output_port + ";\n"
    text += (
        """  uint1_t output_valid;
}"""
        + fsm_logic.func_name
        + """_OUTPUT_t;
"""
        + fsm_logic.func_name
        + """_OUTPUT_t """
        + fsm_logic.func_name
        + FSM_EXT
        + """("""
        + fsm_logic.func_name
        + """_INPUT_t fsm_i)
{
"""
    )
    text += one_hot_states_text
    text += (
        """
  // State reg holding current state, starting at entry=[0]
  ONE_HOT_REG_DECL(FSM_STATE, NUM_STATES"""
        + "_"
        + fsm_logic.func_name
        + """, 0)
  // State reg holding state to return to after certain func calls
  // Starting set to 'invalid'=entry=[0]
  ONE_HOT_REG_DECL(FUNC_CALL_RETURN_FSM_STATE, NUM_STATES"""
        + "_"
        + fsm_logic.func_name
        + """, 0)
  // Input regs
"""
    )
    for input_port in fsm_logic.inputs:
        c_type = fsm_logic.wire_to_c_type[input_port]
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            text += "  " + "static " + elem_t + " " + input_port
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ";\n"
        else:
            text += "  " + "static " + c_type + " " + input_port + ";\n"
    text += """  // Output regs
"""
    for output_port in fsm_logic.outputs:
        c_type = fsm_logic.wire_to_c_type[output_port]
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            text += "  " + "static " + elem_t + " " + output_port + FSM_EXT
            for dim in dims:
                text += "[" + str(dim) + "]"
            text += ";\n"
        else:
            text += "  " + "static " + c_type + " " + output_port + FSM_EXT + ";\n"

    text += """  // All local vars are regs too
"""

    # Get all thread instance flow control func call instances
    flow_ctrl_func_call_names = set()
    for state_group in fsm_logic.state_groups:
        for state_info in state_group:
            if state_info.sub_func_name is not None:
                flow_ctrl_func_call_names.add(state_info.sub_func_name)

    # Collect all local decls from all func used in this main
    local_decls = set()
    main_local_decls = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
        fsm_logic.c_ast_node.body, c_ast.Decl
    )
    local_decls |= set(main_local_decls)
    # Subroutine local decls
    # sub_func_to_local_decls = {}
    sub_func_local_decl_to_func = {}
    for flow_ctrl_func_call_name in flow_ctrl_func_call_names:
        sub_func_logic = parser_state.FuncLogicLookupTable[flow_ctrl_func_call_name]
        sub_func_local_decls = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
            sub_func_logic.c_ast_node.body, c_ast.Decl
        )
        # sub_func_to_local_decls[flow_ctrl_func_call_name] = sub_func_local_decls
        for sub_func_local_decl in sub_func_local_decls:
            sub_func_local_decl_to_func[sub_func_local_decl] = flow_ctrl_func_call_name
        local_decls |= set(sub_func_local_decls)

    # print("fsm_logic.func_name",fsm_logic.func_name)
    # print("local_decls",local_decls)
    for local_decl in local_decls:
        c_type, var_name = C_TO_LOGIC.C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(
            local_decl, parser_state
        )
        # Prepend subroutine name if needed
        if local_decl in sub_func_local_decl_to_func:
            sub_func_name = sub_func_local_decl_to_func[local_decl]
            var_name = sub_func_name + "_" + var_name
        # Text for array or not and init
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            text += "  " + "static " + elem_t + " " + var_name
            for dim in dims:
                text += "[" + str(dim) + "]"
        else:
            text += "  " + "static " + c_type + " " + var_name
        # Include init if static
        is_static = "static" in local_decl.storage
        if is_static and local_decl.init is not None:
            text += (
                " = "
                + C_AST_NODE_TO_C_CODE(
                    local_decl.init, parser_state, None, "", generator
                )
                + "\n"
            )
        else:
            text += ";\n"
        # Hacky ahhhhhh???
        # Adjust static decls to not be static, and not do init later in code.
        # if is_static:
        #  local_decl.storage.remove('static')
        #  local_decl.type = None
        #  local_decl.name = None
        #  local_decl.init = None

    text += (
        """  // Output wires
  """
        + fsm_logic.func_name
        + """_OUTPUT_t fsm_o = {0};
"""
    )

    if len(flow_ctrl_func_call_names) > 0:
        text += "  // Per thread instance subroutines \n"
        # Write wires for each func
        for flow_ctrl_func_name in flow_ctrl_func_call_names:
            flow_ctrl_func_logic = parser_state.FuncLogicLookupTable[
                flow_ctrl_func_name
            ]
            text += "  // " + flow_ctrl_func_name + "\n"
            # Inputs
            for sub_input_port in flow_ctrl_func_logic.inputs:
                sub_input_port_c_type = flow_ctrl_func_logic.wire_to_c_type[
                    sub_input_port
                ]
                # Text for array or not and init
                if C_TO_LOGIC.C_TYPE_IS_ARRAY(sub_input_port_c_type):
                    elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(
                        sub_input_port_c_type
                    )
                    text += (
                        "  "
                        + "static "
                        + elem_t
                        + " "
                        + flow_ctrl_func_name
                        + "_"
                        + sub_input_port
                    )
                    for dim in dims:
                        text += "[" + str(dim) + "]"
                else:
                    text += (
                        "  static "
                        + sub_input_port_c_type
                        + " "
                        + flow_ctrl_func_name
                        + "_"
                        + sub_input_port
                    )
                text += ";\n"
            # Return val
            if C_TO_LOGIC.RETURN_WIRE_NAME in flow_ctrl_func_logic.wire_to_c_type:
                sub_out_port_c_type = flow_ctrl_func_logic.wire_to_c_type[
                    C_TO_LOGIC.RETURN_WIRE_NAME
                ]
                text += (
                    "  static "
                    + sub_out_port_c_type
                    + " "
                    + flow_ctrl_func_name
                    + "_"
                    + C_TO_LOGIC.RETURN_WIRE_NAME
                    + ";\n"
                )
            # Return state
            text += (
                "  ONE_HOT_REG_DECL_ZERO_INIT("
                + flow_ctrl_func_name
                + "_FUNC_CALL_RETURN_FSM_STATE, NUM_STATES"
                + "_"
                + fsm_logic.func_name
                + ")\n"
            )

    if len(single_inst_flow_ctrl_func_call_names) > 0:
        # Dont need for outputs since known calling fsm is ready for single inst output valid
        text += (
            "  // Regs for single instance subroutine fsm calls inputs, output wires\n"
        )
        # Write regs for each func
        for flow_ctrl_func_name in single_inst_flow_ctrl_func_call_names:
            text += (
                "  static "
                + flow_ctrl_func_name
                + "_INPUT_t "
                + flow_ctrl_func_name
                + "_i;\n"
            )
            text += (
                "  "
                + flow_ctrl_func_name
                + "_OUTPUT_t "
                + flow_ctrl_func_name
                + "_o;\n"
            )

    text += """
  // Handshake+inputs registered
  if(ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_REG)"""
    if uses_io_func:
        text += " | ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_RETURN_IN)"
    text += """)
  {
    // Special first state signals ready, waits for start
    fsm_o.input_ready = 1;
    if(fsm_i.input_valid)
    {
      // Register inputs
"""
    for input_port in fsm_logic.inputs:
        text += "      " + input_port + " = fsm_i." + input_port + ";\n"

    # Go to first user state after getting inputs
    if uses_io_func:
        # Extra logic to detect 'return to arbitrary user location from entry'
        text += (
            """      // Go to signaled return-from-entry state if valid
        if(ONE_HOT_CONST_EQ(FUNC_CALL_RETURN_FSM_STATE,ENTRY_REG))
        {
            // Invalid, default to first user state
            if(ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_REG)){
                ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, """
            + fsm_logic.first_user_state.name
            + """, ENTRY_REG)
            }else if(ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_RETURN_IN)){
                ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, """
            + fsm_logic.first_user_state.name
            + """, ENTRY_RETURN_IN)
            }
        }
        else
        {
            // Make indicated user transition from entry
            ONE_HOT_VAR_ASSIGN(FSM_STATE, FUNC_CALL_RETURN_FSM_STATE, NUM_STATES"""
            + "_"
            + fsm_logic.func_name
            + """)
        }"""
        )
    else:
        # Normal case
        text += (
            """      // Default to first user state
      ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, """
            + fsm_logic.first_user_state.name
            + """, ENTRY_REG)"""
        )

    text += """
    }
  }
  // Pass through from ENTRY in same clk cycle
"""

    # List out all user states in parallel branch groups
    # Except for last state group of clk delay
    last_group = fsm_logic.state_groups[-1]
    last_group_is_clk_delay = list(last_group)[
        0
    ].ends_w_clk  # hack check if has clk states in group
    for state_group_i, state_group in enumerate(fsm_logic.state_groups):
        if not last_group_is_clk_delay or (
            state_group_i < len(fsm_logic.state_groups) - 1
        ):
            text += STATE_GROUP_TO_C_CODE(
                state_group,
                state_group_i,
                fsm_logic,
                parser_state,
                generator,
                single_inst_flow_ctrl_func_call_names,
            )

    # Last stage group of clock delay states is parallel with return
    if last_group_is_clk_delay:
        text += """  
  // Clock delay last group of states
"""
        text += STATE_GROUP_TO_C_CODE(
            last_group,
            len(fsm_logic.state_groups) - 1,
            fsm_logic,
            parser_state,
            generator,
            single_inst_flow_ctrl_func_call_names,
            first_state_in_group=False,
            elif_str="if",  # Known last state has no sequential looking depending assignments
        )

    text += """
  // Pass through to RETURN_REG in same clk cycle
  
  // Handshake+outputs registered
  if(ONE_HOT_CONST_EQ(FSM_STATE,RETURN_REG)"""
    if uses_io_func:
        text += " | ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_RETURN_OUT)"
    text += """)
  {
    // Special last state signals done, waits for ready
    fsm_o.output_valid = 1;"""
    if len(fsm_logic.outputs) > 0:
        text += (
            """
    fsm_o.return_output = """
            + C_TO_LOGIC.RETURN_WIRE_NAME
            + FSM_EXT
            + """;"""
        )
    text += (
        """
    if(fsm_i.output_ready)
    {
      // Go to signaled return state
      ONE_HOT_VAR_ASSIGN(FSM_STATE, FUNC_CALL_RETURN_FSM_STATE, NUM_STATES"""
        + "_"
        + fsm_logic.func_name
        + """)
"""
    )
    if uses_io_func:
        text += """      // Go to second part of io state\n"""
        text += """      if(ONE_HOT_CONST_EQ(FSM_STATE,ENTRY_RETURN_OUT))
      {
        ONE_HOT_TRANS_NEXT_FROM(FSM_STATE, ENTRY_RETURN_IN, ENTRY_RETURN_OUT)
      }
"""
    text += """    }
  }
"""

    text += """
  return fsm_o;
}
  
  """

    # print(text)
    return text


def BUILD_STATE_NAME(c_ast_node, parser_state, post_text=""):
    return (
        parser_state.existing_logic.fsm_subroutine_scope[-1]
        + "_"
        + "L"
        + str(c_ast_node.coord.line)
        + "_C"
        + str(c_ast_node.coord.column)
        + "_"
        + (os.path.split(str(c_ast_node.coord.file))[1]).replace(".", "_")
        + "_"
        + str(type(c_ast_node).__name__)
        + post_text
    )


def C_AST_NODE_TO_STATES_LIST(
    c_ast_node, parser_state, curr_state_info=None, next_state_info=None
):
    # Collect chunks
    # Chunks are list of comb cast nodes that go into one state
    # Or individual nodes that need additional handling, returns list of one of more states
    chunks = COLLECT_COMB_LOGIC(c_ast_node, parser_state)

    # Need to process chunks backwards since working with next pointers
    # Need next state to be done before many prev states point at it?
    # Not stricly required, could make next state obj empty first and point at it early?

    # print("Node:",type(c_ast_node).__name__,c_ast_node.coord)
    # print("=chunks")
    reversed_states_list = []
    for chunk in reversed(chunks):
        # List of c_ast nodes
        if type(chunk) is list:
            # Update next state pointer
            if len(reversed_states_list) > 0:
                next_state_info = reversed_states_list[-1]
            # Create another state working backwards
            state_info = FsmStateInfo()
            name_c_ast_node = chunk[0]
            if type(name_c_ast_node) is c_ast.Compound:
                name_c_ast_node = name_c_ast_node.block_items[0]
            state_info.name = BUILD_STATE_NAME(name_c_ast_node, parser_state)
            state_info.c_ast_nodes += chunk
            state_info.always_next_state = next_state_info
            reversed_states_list.append(state_info)
            # print("c ast",type(chunk[0]).__name__,chunk[0].coord)
        else:
            # Or single c ast node of ctrl flow
            # Flow control node to elborate to more states
            # Update next state pointer
            if len(reversed_states_list) > 0:
                next_state_info = reversed_states_list[-1]
            # Create more states working backwards
            ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(
                chunk,
                None,  # new_curr_state_info,
                next_state_info,
                parser_state,
            )
            # ctrl_flow_states should be unordered except for pointer to first
            # but list [0] , [-1] reversed works for now
            reversed_states_list += reversed(ctrl_flow_states)

    states_list = list(reversed(reversed_states_list))
    """print("==== states_list")
    for i,state_info in enumerate(states_list):
        if type(state_info) is FsmStateInfo:
            print("comb state:")
            state_info.print()
            print("")
        else:
            print("ctrl flow:",type(state_info).__name__, state_info.coord)
            print("")
            print(0/0)
    print("==== \n")"""

    # Sanity check no states with same name
    name_to_state = {}
    for state in states_list:
        if state.name in name_to_state:
            for state_i in states_list:
                state_i.print()
                print("=====", flush=True)
            # name_to_state[state.name].print()
            # print("=====", flush=True)
            # state.print()
            raise Exception(f"Duplicate named states! {state.name}")
        name_to_state[state.name] = state

    return states_list


# Helper to decide what exit states follow a subroutine return
# Can't always tell since visited states is only for the current clock cycle
# ex. if entered subroutine some clocks ago can't identify that entry point in history
# TODO modify trans list to include multiple clk cycles in list for always being able
# to correct determine exit point matching entry
def FIND_EXIT_STATES(sub_func_name, parser_state, visited_states=set()):
    debug = False
    if debug:
        print(
            f"{parser_state.existing_logic.func_name} Trying exit states from sub {sub_func_name}..."
        )
    exit_states = []
    all_possible_exit_states = []
    for (
        func_call_node
    ) in parser_state.existing_logic.func_call_node_to_entry_exit_states.keys():
        if func_call_node.name.name == sub_func_name:
            # if sub_func_name=="get_uart_input":
            #   print(f"{sub_func_name} {func_call_node.coord}
            entry_state, exit_state = (
                parser_state.existing_logic.func_call_node_to_entry_exit_states[
                    func_call_node
                ]
            )
            all_possible_exit_states.append(exit_state)
            if entry_state in visited_states:
                exit_states.append(exit_state)
    # Fall back to all possible if unknown?
    if len(all_possible_exit_states) == 0:
        raise Exception(
            "No possible exit states for inline sub func exit/return!?", sub_func_name
        )
    if debug:
        print("Poss exit states:")
        for all_possible_exit_state in all_possible_exit_states:
            all_possible_exit_state.print()
            print("===")
        print("Visited states:")
        for visited_state in visited_states:
            visited_state.print()
            print("===")
    if len(exit_states) == 0:
        # if debug:
        #   raise Exception("No found exit states for inline sub func exit/return!?", sub_func_name, len(all_possible_exit_states))
        exit_states = all_possible_exit_states
    return exit_states


def GET_STATE_TRANS_LISTS(start_state, parser_state, visited_states=None):
    if visited_states is None:
        visited_states = []
    # print("start_state.name",start_state.name)
    # start_state.print()
    # print()
    # visited_states is primarily to resolve loops for user instead of requiring __clk()?
    # if start_state in visited_states:
    #    print("Already visited",start_state.name)
    #    return [[]]  # [[start_state]]
    visited_states.append(start_state)

    debug = False

    # Branch or pass through default next or clock(ends chain)?
    if start_state.ends_w_clk:
        return [[start_state]]
    # Going to return state of main (not subroutine) func
    elif start_state.return_node is not None and start_state.sub_func_name is None:
        # print(" returns")
        return [[start_state]]
    # Going to inputs state
    elif start_state.input_func_call_node is not None:
        return [[start_state]]
    # Going to yield state
    elif start_state.yield_func_call_node is not None:
        return [[start_state]]
    # Going to inout state
    elif start_state.inout_func_call_node is not None:
        return [[start_state]]
    # Single inst func is entry is pseudo dead end
    # (Not single inst isnt guarenteed to be dead end)
    elif (
        start_state.ends_w_fsm_func_entry is not None
        and start_state.ends_w_fsm_func_entry.name.name
        in parser_state.func_single_inst_header_included
    ):
        return [[start_state]]

    poss_next_states = []
    # Branching?
    if start_state.branch_nodes_tf_states is not None:
        (c_ast_node, true_state, false_state) = start_state.branch_nodes_tf_states
        # if true_state != start_state:  # No loops?
        poss_next_states.append(true_state)
        if false_state is not None:  # and false_state != start_state:  # No loops?
            # print(" poss_next_state.name false",false_state.name)
            poss_next_states.append(false_state)
        # elif (
        #    false_state is None
        #    and start_state.always_next_state is not None
        #    and start_state.always_next_state != start_state
        # ):  # No loops?
        #    poss_next_states.add(
        #        start_state.always_next_state
        #    )  # Default next if no false branch
        else:  # false_state is None
            # Submodule return?
            if start_state.sub_func_name is not None:
                exit_states = FIND_EXIT_STATES(
                    start_state.sub_func_name, parser_state, visited_states
                )
                for poss_next_state in exit_states:
                    if poss_next_state not in visited_states:
                        poss_next_states.append(poss_next_state)

    # Normal single next state
    elif start_state.always_next_state is not None:
        # No loops?:and start_state.always_next_state != start_state
        # print(" poss_next_state.name always",start_state.always_next_state.name)
        poss_next_states.append(start_state.always_next_state)

    # Multiple returns from single inst fsms
    # are captured by post fsm groups starting at func exit/return
    # Nothing needs to be done here

    # However, multiple returns from inlined subroutines need to handled
    else:  # No branching or always next states, looks like exit/return/done
        # Submodule return?
        if start_state.sub_func_name is not None:
            exit_states = FIND_EXIT_STATES(
                start_state.sub_func_name, parser_state, visited_states
            )
            for poss_next_state in exit_states:
                if poss_next_state not in visited_states:
                    poss_next_states.append(poss_next_state)

    # Make a return state list for each state
    states_trans_lists = []
    if len(poss_next_states) == 0:
        return [[start_state]]
    else:
        for poss_next_state in poss_next_states:
            start_states_trans_list = [start_state]
            new_states_trans_lists = GET_STATE_TRANS_LISTS(
                poss_next_state, parser_state, visited_states
            )
            for new_states_trans_list in new_states_trans_lists:
                combined_state_trans_list = (
                    start_states_trans_list + new_states_trans_list
                )
                states_trans_lists.append(combined_state_trans_list)

    # print("start_state.name",start_state.name,states_trans_lists)
    return states_trans_lists


def C_AST_CTRL_FLOW_NODE_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    if type(c_ast_node) == c_ast.If:
        return C_AST_CTRL_FLOW_IF_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name == CLK_FUNC:
        return C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name == INPUT_FUNC:
        return C_AST_CTRL_FLOW_INPUT_FUNC_CALL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name == YIELD_FUNC:
        return C_AST_CTRL_FLOW_YIELD_FUNC_CALL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.Return:
        return C_AST_CTRL_FLOW_RETURN_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name == INOUT_FUNC:
        return C_AST_CTRL_FLOW_INOUT_FUNC_CALL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.While:
        return C_AST_CTRL_FLOW_WHILE_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.DoWhile:
        return C_AST_CTRL_FLOW_DOWHILE_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.For:
        return C_AST_CTRL_FLOW_FOR_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) is c_ast.FuncCall and FUNC_USES_FSM_CLK(
        c_ast_node.name.name, parser_state
    ):
        return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.Assignment:
        return C_AST_CTRL_FLOW_ASSIGNMENT_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    elif type(c_ast_node) == c_ast.Decl:
        return C_AST_CTRL_FLOW_DECL_TO_STATES(
            c_ast_node, curr_state_info, next_state_info, parser_state
        )
    else:
        raise Exception(
            f"TODO Unsupported flow node inside: {type(c_ast_node).__name__} {c_ast_node.coord}"
        )


def C_AST_CTRL_FLOW_DECL_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    # Should be declaring and assigning/initing with func call
    func_call_node = c_ast_node.init
    # print(c_ast_node)
    # Python as easy as it seems?
    decl_wo_func_call = copy.copy(c_ast_node)
    decl_wo_func_call.init = None
    output_driven_things = [decl_wo_func_call]
    return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(
        func_call_node,
        curr_state_info,
        next_state_info,
        parser_state,
        output_driven_things,
    )


def C_AST_CTRL_FLOW_ASSIGNMENT_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    # For now only allow comb lhs and func call as rhs?
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.lvalue, parser_state):
        raise Exception(
            f"TODO unsupported control flow in assignment LHS: {c_ast_node.lvalue.coord}"
        )
    if type(c_ast_node.rvalue) is not c_ast.FuncCall:
        raise Exception(
            f"TODO unsupported control flow in assignment RHS: {c_ast_node.rvalue.coord}"
        )
    func_call_node = c_ast_node.rvalue
    output_driven_things = [c_ast_node.lvalue]
    return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(
        func_call_node,
        curr_state_info,
        next_state_info,
        parser_state,
        output_driven_things,
    )


def C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state, output_driven_things=[]
):
    # Check if each input uses C_AST_NODE_USES_CTRL_FLOW_NODE
    input_drivers = []
    called_func_name = c_ast_node.name.name
    if called_func_name not in parser_state.FuncLogicLookupTable:
        raise Exception(
            f"No function defintion parsed for: {called_func_name} ? Bad #include order? {c_ast_node.coord}"
        )
    called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
    for i in range(0, len(called_func_logic.inputs)):
        input_c_ast_node = c_ast_node.args.exprs[i]
        if C_AST_NODE_USES_CTRL_FLOW_NODE(input_c_ast_node, parser_state):
            raise Exception(
                f"TODO unsupported control flow in func call argument: {input_c_ast_node.coord}"
            )
        else:
            # Input driven by comb logic
            input_drivers.append(input_c_ast_node)

    states = []

    # Func entry new state
    entry_state_info = FsmStateInfo()
    # entry_state_info.always_next_state = done later below
    entry_state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state) + "_ENTRY"
    # Set current state to have func entry
    entry_state_info.ends_w_fsm_func_entry = c_ast_node
    entry_state_info.ends_w_fsm_func_entry_input_drivers = input_drivers
    states.append(entry_state_info)

    # Func exit new state
    exit_state_info = FsmStateInfo()
    exit_state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state) + "_EXIT"
    exit_state_info.always_next_state = next_state_info
    exit_state_info.starts_w_fsm_func_return = c_ast_node
    exit_state_info.starts_w_fsm_func_return_output_driven_things = output_driven_things

    # Record entry+exit states for func
    parser_state.existing_logic.func_call_node_to_entry_exit_states[c_ast_node] = (
        entry_state_info,
        exit_state_info,
    )

    # Weird to check  parser_state.existing_logic.func_call_name_to_state for 'states exist yet'
    # since is being built backwards from later states first in func def body parsing...

    # Single instance or regular func call?
    if called_func_name in parser_state.func_single_inst_header_included:
        # Single inst func call state
        # Does a state for it already exist?
        if called_func_name not in parser_state.existing_logic.func_call_name_to_state:
            fsm_state_info = FsmStateInfo()
            fsm_state_info.name = called_func_name + "_SINGLE_INST_FSM"
            fsm_state_info.single_inst_func_name = called_func_name
            parser_state.existing_logic.func_call_name_to_state[called_func_name] = (
                fsm_state_info
            )
            fsm_state_info.always_next_state = None  # No hard coded state, is based on FSM_STATE = FUNC_CALL_RETURN_FSM_STATE;
            # Order kinda matters?
            states.append(fsm_state_info)
        else:
            fsm_state_info = parser_state.existing_logic.func_call_name_to_state[
                called_func_name
            ]
        entry_state_info.always_next_state = fsm_state_info
    else:
        # Regular subroutine inlining
        # For now, like single inst, there only is one copy of the body of inlined states
        # TODO check sequence of function calls to see if there was a clock in between
        #   if so then can resuse same inlined states (otherwise no clock needs pass through two duplicate funcs in same cycle)
        #   ^ If users want that for now just write as comb logic instead weird pass through states?
        # States 'inlined' are copy of what you could get from evaluating the func body of whats being called
        # Get func def body cast node defining the subroutine
        if called_func_name not in parser_state.existing_logic.func_call_name_to_state:
            sub_c_ast_func_def_body = called_func_logic.c_ast_node.body
            # None next state info since not all calls to this ~inlined func exit back to the same calling locaiton
            # Needs to use the function's FUNC_CALL_RETURN_STATE to get to location specific exist states
            parser_state.existing_logic.fsm_subroutine_scope.append(called_func_name)
            sub_states = C_AST_NODE_TO_STATES_LIST(
                sub_c_ast_func_def_body, parser_state, None, None
            )
            parser_state.existing_logic.fsm_subroutine_scope.pop()
            # Apply to each subroutine state a recording of what func it came from
            for sub_state in sub_states:
                if sub_state.sub_func_name is None:
                    sub_state.sub_func_name = called_func_name
            states += sub_states
            # Order kinda matters?
            parser_state.existing_logic.func_call_name_to_state[called_func_name] = (
                sub_states[0]
            )
            entry_state_info.always_next_state = sub_states[0]
        else:
            sub_state0 = parser_state.existing_logic.func_call_name_to_state[
                called_func_name
            ]
            entry_state_info.always_next_state = sub_state0

    # Order kinda matters for now?
    states.append(exit_state_info)

    return states


def C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(
    c_ast_clk_func_call, curr_state_info, next_state_info, parser_state
):
    states = []

    # Make a new state for this clock delay
    # This state can be merged into others later
    state_info = FsmStateInfo()
    # next_state_info.always_next_state = curr_state_info
    state_info.name = BUILD_STATE_NAME(c_ast_clk_func_call, parser_state) + "_DELAY_CLK"
    state_info.ends_w_clk = True
    state_info.always_next_state = next_state_info
    states.append(state_info)

    return states


def C_AST_CTRL_FLOW_RETURN_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    states = []

    if c_ast_node.expr is not None:
        if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.expr, parser_state):
            raise Exception(
                f"TODO unsupported control flow in return expression: {c_ast_node.expr.coord}"
            )

    # Update curr state as ending with return transition
    state_info = FsmStateInfo()
    state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state)
    state_info.return_node = c_ast_node
    state_info.always_next_state = next_state_info
    states.append(state_info)

    return states


def C_AST_CTRL_FLOW_INPUT_FUNC_CALL_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    states = []

    state_info = FsmStateInfo()
    state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state)
    state_info.always_next_state = next_state_info
    states.append(state_info)

    # Update curr state as ending with getting inputs transition
    state_info.input_func_call_node = c_ast_node

    return states


def C_AST_CTRL_FLOW_YIELD_FUNC_CALL_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    states = []
    ret_arg_node = c_ast_node.args.exprs[0]
    if C_AST_NODE_USES_CTRL_FLOW_NODE(ret_arg_node, parser_state):
        raise Exception(f"TODO unsupported control flow in yield: {ret_arg_node.coord}")

    state_info = FsmStateInfo()
    state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state)
    state_info.always_next_state = next_state_info
    states.append(state_info)

    # Update curr state as ending with yield transition
    state_info.yield_func_call_node = c_ast_node

    return states


def C_AST_CTRL_FLOW_INOUT_FUNC_CALL_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    states = []
    ret_arg_node = c_ast_node.args.exprs[0]
    if C_AST_NODE_USES_CTRL_FLOW_NODE(ret_arg_node, parser_state):
        raise Exception(f"TODO unsupported control flow in inout: {ret_arg_node.coord}")

    state_info = FsmStateInfo()
    state_info.name = BUILD_STATE_NAME(c_ast_node, parser_state)
    state_info.always_next_state = next_state_info
    states.append(state_info)

    # Update curr state as ending with inout transition
    state_info.inout_func_call_node = c_ast_node

    return states


def C_AST_CTRL_FLOW_IF_TO_STATES(
    c_ast_if, curr_state_info, next_state_info, parser_state
):
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_if.cond, parser_state):
        raise Exception(
            f"TODO unsupported control flow in if condition: {c_ast_if.cond.coord}"
        )
    states = []
    cond_state = FsmStateInfo()
    states.append(cond_state)

    # Create a state for true logic and insert it into return list of states
    name_c_ast_node = None
    if type(c_ast_if.iftrue) is c_ast.Compound:
        name_c_ast_node = c_ast_if.iftrue.block_items[0]
    else:
        name_c_ast_node = c_ast_if.iftrue
    true_states = C_AST_NODE_TO_STATES_LIST(
        c_ast_if.iftrue, parser_state, None, next_state_info
    )
    # new_true_states = true_states[:].remove(true_state)
    # Order sorta matters?
    first_true_state = true_states[0]
    states += true_states

    # Similar for false
    if c_ast_if.iffalse is not None:
        name_c_ast_node = None
        if type(c_ast_if.iffalse) is c_ast.Compound:
            name_c_ast_node = c_ast_if.iffalse.block_items[0]
        else:
            name_c_ast_node = c_ast_if.iffalse
        false_states = C_AST_NODE_TO_STATES_LIST(
            c_ast_if.iffalse, parser_state, None, next_state_info
        )
        # Order sorta matters?
        first_false_state = false_states[0]
        states += false_states
    else:
        # No false branch, default is to go to next state
        first_false_state = next_state_info

    # Add mux sel calculation, and jumping to true or false states
    # to current state after comb logic
    cond_state.name = BUILD_STATE_NAME(c_ast_if, parser_state) + "_COND"
    cond_state.always_next_state = None  # branching
    cond_state.branch_nodes_tf_states = (c_ast_if, first_true_state, first_false_state)

    return states


def C_AST_CTRL_FLOW_FOR_TO_STATES(
    c_ast_node, curr_state_info, next_state_info, parser_state
):
    # For loop is like while loop with extra stuff
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.init, parser_state):
        raise Exception(
            f"TODO unsupported control flow in for init: {c_ast_node.init.coord}"
        )
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.cond, parser_state):
        raise Exception(
            f"TODO unsupported control flow in for cond: {c_ast_node.cond.coord}"
        )
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.next, parser_state):
        raise Exception(
            f"TODO unsupported control flow in for next: {c_ast_node.next.coord}"
        )
    states = []
    init_state = FsmStateInfo()
    cond_state = FsmStateInfo()
    next_inc_state = FsmStateInfo()

    # Init
    init_state.name = BUILD_STATE_NAME(c_ast_node, parser_state) + "_FOR_INIT"
    init_state.c_ast_nodes.append(c_ast_node.init)
    init_state.always_next_state = cond_state

    # Next/increment state
    next_inc_state.name = BUILD_STATE_NAME(c_ast_node, parser_state) + "_FOR_NEXT"
    next_inc_state.c_ast_nodes.append(c_ast_node.next)
    next_inc_state.always_next_state = cond_state  # Check condition after increment

    # Body states goes next/increment state next
    body_states = C_AST_NODE_TO_STATES_LIST(
        c_ast_node.stmt, parser_state, None, next_inc_state
    )
    # Order kinda matters?
    first_body_state = body_states[0]

    # Condition
    cond_state.name = BUILD_STATE_NAME(c_ast_node, parser_state) + "_FOR_COND"
    cond_state.always_next_state = None  # Branching, no default
    cond_state.branch_nodes_tf_states = (
        c_ast_node,
        first_body_state,
        next_state_info,
    )

    # Order kinda matters?
    states.append(init_state)
    states.append(cond_state)
    states += body_states
    states.append(next_inc_state)

    return states


def C_AST_CTRL_FLOW_WHILE_TO_STATES(
    c_ast_while, curr_state_info, next_state_info, parser_state
):
    # While default next state is looping backto eval loop cond again
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_while.cond, parser_state):
        raise Exception(
            f"TODO unsupported control flow in while condition: {c_ast_while.cond.coord}"
        )

    states = []

    cond_state = FsmStateInfo()

    # Body states goes to condition
    # Eval body and accum states
    body_states = C_AST_NODE_TO_STATES_LIST(
        c_ast_while.stmt, parser_state, None, cond_state
    )
    # Order kinda matters?
    first_body_state = body_states[0]

    # Condition
    cond_state.name = BUILD_STATE_NAME(c_ast_while, parser_state) + "_WHILE_COND"
    cond_state.always_next_state = None  # Branching, no default
    cond_state.branch_nodes_tf_states = (
        c_ast_while,
        first_body_state,
        next_state_info,
    )

    # Order kinda matters?
    states.append(cond_state)
    states += body_states

    return states


# Idential to while loop except for body-cond states ordering in return?
def C_AST_CTRL_FLOW_DOWHILE_TO_STATES(
    c_ast_dowhile, curr_state_info, next_state_info, parser_state
):
    # While default next state is looping backto eval loop cond again
    if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_dowhile.cond, parser_state):
        raise Exception(
            f"TODO unsupported control flow in do while condition: {c_ast_dowhile.cond.coord}"
        )

    states = []

    cond_state = FsmStateInfo()

    # Body states goes to condition
    # Eval body and accum states
    body_states = C_AST_NODE_TO_STATES_LIST(
        c_ast_dowhile.stmt, parser_state, None, cond_state
    )
    # Order kinda matters?
    first_body_state = body_states[0]

    # Condition
    cond_state.name = BUILD_STATE_NAME(c_ast_dowhile, parser_state) + "_WHILE_COND"
    cond_state.always_next_state = None  # Branching, no default
    cond_state.branch_nodes_tf_states = (
        c_ast_dowhile,
        first_body_state,
        next_state_info,
    )

    # Order kinda matters?
    # DO WHILE HAS BODY FIRST?
    states += body_states
    states.append(cond_state)

    return states


def C_AST_FSM_FUNDEF_BODY_TO_LOGIC(c_ast_func_def_body, parser_state):
    # Start off with as parsed single file ordered list of states
    parser_state.existing_logic.fsm_subroutine_scope.append(
        parser_state.existing_logic.func_name
    )
    states_list = C_AST_NODE_TO_STATES_LIST(c_ast_func_def_body, parser_state)
    parser_state.existing_logic.fsm_subroutine_scope.pop()
    parser_state.existing_logic.first_user_state = states_list[0]

    states_ends_w_clk = set()
    for state in states_list:
        if state.ends_w_clk:
            states_ends_w_clk.add(state)

    # DEBUG ONE GROUP PER STATE AS PARSED
    # for state in states_list:
    #    parser_state.existing_logic.state_groups.append(set([state]))
    # return parser_state.existing_logic

    # DEBUG try basic group from start?
    # parser_state.existing_logic.state_groups = GET_GROUPED_STATE_TRANSITIONS([states_list[0]], parser_state)
    # return parser_state.existing_logic

    debug = False

    if debug:
        print("func states list:", parser_state.existing_logic.func_name)
        for state in states_list:
            state.print()
            print("=====", flush=True)
        print("=====", flush=True)
        print("=====", flush=True)
        print("=====", flush=True)

    # TODO https://github.com/JulianKemmerer/PipelineC/issues/163
    # collect predecessor states set for all states
    #     Similar to trans list / maybe can use, watch out for sub return to multiple possible exits
    # States with one always next state pred state should be ~mergable?
    #     use pred to merge ends with clock into prev states?
    #     Can add 'starts with clock' for opposite moving states to first group w entry

    # Single inst sub return -> onwward groups "post" fsm middle
    fsm_return_states_list = []
    for state in states_list:
        if (
            state.starts_w_fsm_func_return
            and state.starts_w_fsm_func_return.name.name
            in parser_state.func_single_inst_header_included
        ):
            fsm_return_states_list.append(state)
    # Exclude pre fsm + fsm stuff (entry+fsm state)
    excluded_subentry_and_subfsm_states = True
    # And exclude states that end with clock
    post_fsms_groups = GET_GROUPED_STATE_TRANSITIONS(
        fsm_return_states_list,
        parser_state,
        excluded_single_inst_subentry_and_subfsm_states=excluded_subentry_and_subfsm_states,
    )  # ,
    # excluded_states=states_ends_w_clk)
    if debug:
        print("Postfsm groups:")
        for i, post_fsms_group in enumerate(post_fsms_groups):
            print("Postfsm group:", i)
            for post_fsm_state in post_fsms_group:
                post_fsm_state.print()
                print("======")
            print()

    # Collect middle single inst subroutine FSM state group
    states_list_no_fsms = []
    fsms_group = set()
    for state in states_list:
        if state.single_inst_func_name is None:
            states_list_no_fsms.append(state)
            # print("Start:",state.name)
        if state.single_inst_func_name is not None:
            fsms_group.add(state)
    fsms_groups = []
    if len(fsms_group) > 0:
        fsms_groups.append(fsms_group)

    # "Pre" subroutine groups
    # Func entry -> onward
    # sub routine entry -> onward not captured above yet..
    #   weird but needed for now since entry could be excluded in post fsm group above
    #   also not single inst because reused inline fsm func entry is pseudo start?
    # single inst sub routine return -> onward not captured above yet
    # Ends with clock -> onward
    # Branching backwards
    # etc
    start_states = [states_list_no_fsms[0]]
    for state in states_list_no_fsms:
        # Pseduo new starts from func entry could be jump back to renter func next clock
        if (
            state.ends_w_fsm_func_entry
            and state.ends_w_fsm_func_entry.name.name
            in parser_state.func_single_inst_header_included
        ):
            start_states.append(state)
        # Pseduo new starts from single inst func returns
        if (
            state.starts_w_fsm_func_return
            and state.starts_w_fsm_func_return.name.name
            in parser_state.func_single_inst_header_included
        ):
            start_states.append(state)
        # State after user delay clk
        if (
            state.ends_w_clk
            or state.input_func_call_node is not None
            or state.yield_func_call_node is not None
            or state.inout_func_call_node is not None
        ):
            if state.always_next_state is not None:
                # Normal always next state after clock
                start_states.append(state.always_next_state)
            else:
                # Not branching or always next states, looks like exit/return/done
                # Similar to transition following as in get trans list func
                # Submodule return?
                if state.sub_func_name is not None:
                    exit_states = FIND_EXIT_STATES(state.sub_func_name, parser_state)
                    start_states += exit_states

        # Branching backwards marked with delay clock next state
        elif state.branch_nodes_tf_states is not None:
            c_ast_node, true_state, false_state = state.branch_nodes_tf_states
            if (
                state.ends_w_clk
                or (
                    state.starts_w_fsm_func_return
                )  # and state.starts_w_fsm_func_return.name.name in parser_state.func_single_inst_header_included
            ):
                raise Exception(
                    "TODO: merged branching and clk states as place to start trans list?"
                )
                # start_states.append(true_state)
                # start_states.append(false_state)
    # Get state groups from starting states and
    # Exclude post fsm stuff (return)
    excluded_subfsm_states_and_subreturn = True
    # Also exclude anything that occurs in post fsm groups
    all_post_states = set()
    for post_fsms_group in post_fsms_groups:
        all_post_states |= post_fsms_group

    #### Exclude states end with clk
    ####all_post_and_ends_w_clk_states = all_post_states | states_ends_w_clk
    if debug:
        print("Start states:")
        for state in start_states:
            state.print()
            print("=====", flush=True)
        print("All post states:")
        for state in all_post_states:
            state.print()
            print("=====", flush=True)
    pre_fsms_groups = GET_GROUPED_STATE_TRANSITIONS(
        start_states,
        parser_state,
        excluded_single_inst_subfsm_states_and_subreturn=excluded_subfsm_states_and_subreturn,
        excluded_states=all_post_states,
    )  # all_post_and_ends_w_clk_states)
    if debug:
        print("Prefsm groups:")
        for i, pre_fsms_group in enumerate(pre_fsms_groups):
            print("Prefsm group:", i)
            for pre_fsm_state in pre_fsms_group:
                pre_fsm_state.print()
                print("======")
            print()

    # Combine all
    state_groups = pre_fsms_groups + fsms_groups + post_fsms_groups

    # Save return val
    parser_state.existing_logic.state_groups = state_groups

    # Doing opposite of Ends with clock -> onward being a starting state
    # by making states that lead up to ending with a clock in the last group

    # Remove states ending with clock delay
    for state_group in parser_state.existing_logic.state_groups:
        for state in list(state_group):
            if state.ends_w_clk:
                state_group.remove(state)

    # Remove any empty groups from list
    for state_group in list(parser_state.existing_logic.state_groups):
        if len(state_group) == 0:
            parser_state.existing_logic.state_groups.remove(state_group)

    # Add states with clock as last group to be included with return handshake group
    if len(states_ends_w_clk) > 0:
        parser_state.existing_logic.state_groups.append(states_ends_w_clk)

    # Sanity check all states coming in, went out
    total_states_from_groups = []
    for state_group in parser_state.existing_logic.state_groups:
        total_states_from_groups += list(state_group)
    if len(total_states_from_groups) != len(set(total_states_from_groups)):
        # for s in set(states_list) - set(total_states_from_groups):
        #  s.print()
        raise Exception("Duplicate states!?")
    if len(total_states_from_groups) < len(states_list):
        for s in set(states_list) - set(total_states_from_groups):
            print("====")
            s.print()
        raise Exception("Missing states!")

    return parser_state.existing_logic


def GET_GROUPED_STATE_TRANSITIONS(
    start_states,
    parser_state,
    excluded_single_inst_subfsm_states_and_subreturn=False,
    excluded_single_inst_subentry_and_subfsm_states=False,
    excluded_states=set(),
):
    debug = False  # parser_state.existing_logic.func_name == "pixels_kernel_seq_range"

    # Get state lists of all cases so far
    all_state_trans_lists = []
    for start_state in start_states:
        try:
            # print("STARTING STATE: ====",start_state.name)
            state_trans_lists_starting_at_start_state = GET_STATE_TRANS_LISTS(
                start_state, parser_state
            )
        except RecursionError:
            raise Exception(
                f"Function: {parser_state.existing_logic.func_name} could contain a data-dependent infinite combinatorial (__clk()-less) loop starting at {start_state.name}"
            )
        all_state_trans_lists += state_trans_lists_starting_at_start_state

    # Sort other trans lists by length
    # give priority to to those longer ones by appending them first into state groups
    # Later short branches are better to be appended at end if needed
    list_len_to_trans_lists = dict()
    for state_trans_list in all_state_trans_lists:
        l = len(state_trans_list)
        if l not in list_len_to_trans_lists:
            list_len_to_trans_lists[l] = []
        list_len_to_trans_lists[l].append(state_trans_list)

    # How to add a transition list to a state groups
    def append_trans_list(trans_list, state_groups, state_to_group_index):
        if debug:
            print(
                "Appending transition list: current len(state_groups)",
                len(state_groups),
            )
            text = "    "
            for state in trans_list:
                text += state.name + " -> "
            print(text)

        # Init starting group pointer
        curr_group_index = 0
        if len(state_groups) == 0:
            state_groups.append(set())
        if trans_list[0] in state_to_group_index:
            curr_group_index = state_to_group_index[trans_list[0]]
        for state in trans_list:
            # Skip some states
            # State groups do not include single inst fsm funcs upon request?
            if excluded_single_inst_subfsm_states_and_subreturn:
                if state.single_inst_func_name is not None or (
                    state.starts_w_fsm_func_return is not None
                    and state.starts_w_fsm_func_return.name.name
                    in parser_state.func_single_inst_header_included
                ):
                    continue
            if excluded_single_inst_subentry_and_subfsm_states:
                if (
                    state.ends_w_fsm_func_entry is not None
                    and state.ends_w_fsm_func_entry.name.name
                    in parser_state.func_single_inst_header_included
                ) or state.single_inst_func_name is not None:
                    continue
            # also manual exclusion wohao
            if state in excluded_states:
                continue
            # Is state in a group yet?
            if state in state_to_group_index:
                state_group_index = state_to_group_index[state]
                # Is state group behind, at, in front of curr pointer?
                if state_group_index >= curr_group_index:
                    # Is in front/later than current, move up for next
                    curr_group_index = state_group_index + 1
                else:  # if state_group_index < curr_group_index:
                    # Is behind current pos? odd...
                    # Cant use state_group_index
                    # Dont do anything and next time
                    # try to put next state in curr group
                    pass
            else:
                # State is not in any group yet
                # use current pos
                state_groups[curr_group_index].add(state)
                state_to_group_index[state] = curr_group_index
                # And next state goes next
                curr_group_index = curr_group_index + 1
            # Add new state groups as needed
            if curr_group_index >= len(state_groups):
                state_groups.append(set())

    # Start with longest trans lists and build groups
    state_groups = []
    state_to_group_index = dict()
    trans_list_lens = list_len_to_trans_lists.keys()
    for trans_list_len in reversed(sorted(trans_list_lens)):
        trans_lists = list_len_to_trans_lists[trans_list_len]
        for trans_list in trans_lists:
            append_trans_list(trans_list, state_groups, state_to_group_index)

    """
    # Use transition lists to group states
    # print("Transition lists:")
    state_to_latest_index = {}
    state_to_earliest_index = {}
    for state_trans_list in all_state_trans_lists:
        text = "States: "
        state_i = 0
        for state in state_trans_list:
            # State groups do not include single inst fsm funcs upon request?
            if excluded_single_inst_subfsm_states_and_subreturn:
                if (
                    state.single_inst_func_name is not None
                    or (state.starts_w_fsm_func_return is not None and state.starts_w_fsm_func_return.name.name in parser_state.func_single_inst_header_included)
                ):
                    continue
            if excluded_single_inst_subentry_and_subfsm_states:
                if (
                    (state.ends_w_fsm_func_entry is not None and state.ends_w_fsm_func_entry.name.name in parser_state.func_single_inst_header_included)
                    or state.single_inst_func_name is not None
                ):
                    continue
            # also manual exclusion wohao
            if state in excluded_states:
                continue
            text += state.name + " -> "
            if state not in state_to_latest_index:
                state_to_latest_index[state] = state_i
            if state not in state_to_earliest_index:
                state_to_earliest_index[state] = state_i
            if state_i > state_to_latest_index[state]:
                state_to_latest_index[state] = state_i
            if state_i < state_to_earliest_index[state]:
                state_to_earliest_index[state] = state_i
            state_i += 1
        if debug:
            print(text)

    # Debug select which ordering is best? ugh
    #state_to_index = state_to_latest_index
    state_to_index = state_to_earliest_index

    if len(state_to_index) <= 0:
        return []
    state_groups = [None] * (max(state_to_index.values()) + 1)
    for state, index in state_to_index.items():
        if debug:
            print("Index",index,state.name)
        if state_groups[index] is None:
            state_groups[index] = set()
        state_groups[index].add(state)
    """

    non_none_state_groups = []
    for state_group in state_groups:
        if state_group is not None:
            non_none_state_groups.append(state_group)
            text = "State Group: "
            for state in state_group:
                text += state.name + ","
            if debug:
                print(text)

    return non_none_state_groups


def FUNC_USES_FSM_CLK(func_name, parser_state):
    if func_name in parser_state.func_fsm_header_included:
        return True
    elif func_name == CLK_FUNC:
        return True
    elif func_name == INPUT_FUNC:
        return True
    elif func_name == YIELD_FUNC:
        return True
    elif func_name == INOUT_FUNC:
        return True
    else:
        if func_name in parser_state.FuncLogicLookupTable:
            func_logic = parser_state.FuncLogicLookupTable[func_name]
            if func_logic.is_fsm_clk_func:
                return True
            # Check submodules of logic
            for sub_inst, sub_func_name in func_logic.submodule_instances.items():
                if FUNC_USES_FSM_CLK(sub_func_name, parser_state):
                    return True
        elif func_name in parser_state.func_name_to_calls:
            # Check funcs called from this func
            called_funcs = parser_state.func_name_to_calls[func_name]
            for called_func in called_funcs:
                if FUNC_USES_FSM_CLK(called_func, parser_state):
                    return True

    return False


def C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node, parser_state):
    func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(
        c_ast_node, c_ast.FuncCall
    )
    for func_call_node in func_call_nodes:
        if FUNC_USES_FSM_CLK(func_call_node.name.name, parser_state):
            return True

    # Or return?
    ret_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.Return)
    if len(ret_nodes) > 0:
        return True

    return False


def COLLECT_COMB_LOGIC(c_ast_node_in, parser_state):
    chunks = []
    comb_logic_nodes = []
    c_ast_nodes = [c_ast_node_in]
    if type(c_ast_node_in) is c_ast.Compound:
        if c_ast_node_in.block_items is not None:
            c_ast_nodes = c_ast_node_in.block_items[:]

    for c_ast_node in c_ast_nodes:
        if not C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node, parser_state):
            comb_logic_nodes.append(c_ast_node)
        else:
            if len(comb_logic_nodes) > 0:
                chunks.append(comb_logic_nodes[:])
            comb_logic_nodes = []
            chunks.append(c_ast_node)

    # Need final chunk of comb logic
    if len(comb_logic_nodes) > 0:
        chunks.append(comb_logic_nodes[:])

    return chunks
