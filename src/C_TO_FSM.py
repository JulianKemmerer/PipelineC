import sys
import copy
from pycparser import c_parser, c_ast, c_generator

# FSM funcs cant be main functions

import C_TO_LOGIC

FSM_EXT = "_FSM"

def C_AST_NODE_TO_C_CODE(c_ast_node, indent = "", generator=None, is_lhs=False):
  if generator is None:
    generator = c_generator.CGenerator()
  text = generator.visit(c_ast_node)
  # What nodes dont need semicolon?
  maybe_semicolon = ";"
  if type(c_ast_node) == c_ast.Compound:
    maybe_semicolon = ""
  elif type(c_ast_node) == c_ast.If:
    maybe_semicolon = ""
  elif type(c_ast_node) == c_ast.ArrayRef and is_lhs:
    maybe_semicolon = ""
  elif type(c_ast_node) == c_ast.Decl and is_lhs:
    maybe_semicolon = ""
  #print(type(c_ast_node))
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
    self.c_ast_nodes = [] # C ast nodes
    self.always_next_state = None # State info obj
    # Todo other flags?
    self.branch_nodes_tf_states = None # (c_ast_node,true state, false state)
    self.ends_w_clk = False
    self.return_node = None
    self.ends_w_fsm_func_entry = None # C ast node of func call
    self.ends_w_fsm_func_entry_input_drivers = None
    self.is_fsm_func_call_state = None # C ast node of func call
    self.starts_w_fsm_func_return = None # C ast node of func call
    self.starts_w_fsm_func_return_output_driven_things = None
   
  def print(self):
    print(str(self.name))
    
    if self.starts_w_fsm_func_return is not None:
      print(self.starts_w_fsm_func_return.name.name + "_FSM() // Return;")
    
    if self.always_next_state is not None:
      print("Default Next:",self.always_next_state.name)
    
    generator = c_generator.CGenerator()
    if len(self.c_ast_nodes) > 0:
      print("Comb logic:")
      for c_ast_node in self.c_ast_nodes:
        print(generator.visit(c_ast_node))
    
    if self.branch_nodes_tf_states is not None:
      print("Branch logic")
      mux_node,true_state,false_state = self.branch_nodes_tf_states
      if false_state is None:
        print(generator.visit(mux_node.cond), "?", true_state.name, ":", "<default next state>")
      else:
        print(generator.visit(mux_node.cond), "?", true_state.name, ":", false_state.name)
      return # Mux is always last?
    
    if self.ends_w_clk:
      print("Delay: __clk();")
      
    if self.ends_w_fsm_func_entry is not None:
      print(self.ends_w_fsm_func_entry.name.name + "_FSM() // Entry;")
      
    if self.is_fsm_func_call_state is not None:
      print(self.is_fsm_func_call_state.name.name + "_FSM() // State;")
      
    if self.return_node is not None:
      print("Return, function end")
      return # Return is always last
      

def FSM_LOGIC_TO_C_CODE(fsm_logic, parser_state):
  generator = c_generator.CGenerator()
  text = ""
  
  # You stupid bitch
  # Woods – Moving to the Left
  # Recursively put any FSM func C code defs included here
  # since dont have code gen passes that make sense yet, stupid
  # WHat funcs does this func call
  if fsm_logic.func_name in parser_state.func_name_to_calls:
    called_funcs = parser_state.func_name_to_calls[fsm_logic.func_name]
    for called_func in called_funcs:
      if called_func in parser_state.FuncLogicLookupTable:
        called_func_logic = parser_state.FuncLogicLookupTable[called_func]
        if called_func_logic.is_fsm_clk_func:
          text += FSM_LOGIC_TO_C_CODE(called_func_logic, parser_state)
  
  text += '''
typedef enum ''' + fsm_logic.func_name + '''_STATE_t{
 ENTRY_REG,
'''
  for state_group in fsm_logic.state_groups:
    for state_info in state_group:
      text += " " + state_info.name + ",\n"
  text += ''' RETURN_REG,
}''' + fsm_logic.func_name + '''_STATE_t;
typedef struct ''' + fsm_logic.func_name + '''_INPUT_t
{
  uint1_t input_valid;
'''
  for input_port in fsm_logic.inputs:
    c_type = fsm_logic.wire_to_c_type[input_port]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_t,dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      text += "  " + elem_t + " " + input_port
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ";\n"
    else:
      text += "  " + c_type + " " + input_port + ";\n"
  text += '''  uint1_t output_ready;
}''' + fsm_logic.func_name + '''_INPUT_t;
typedef struct ''' + fsm_logic.func_name + '''_OUTPUT_t
{
  uint1_t input_ready;
'''
  for output_port in fsm_logic.outputs:
    c_type = fsm_logic.wire_to_c_type[output_port]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_t,dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      text += "  " + elem_t + " " + output_port
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ";\n"
    else:
      text += "  " + c_type + " " + output_port + ";\n"
  text += '''  uint1_t output_valid;
}''' + fsm_logic.func_name + '''_OUTPUT_t;
''' + fsm_logic.func_name + '''_OUTPUT_t ''' + fsm_logic.func_name + FSM_EXT + '''(''' + fsm_logic.func_name + '''_INPUT_t i)
{
  // State reg
  static ''' + fsm_logic.func_name + '''_STATE_t FSM_STATE;
  // Input regs
'''
  for input_port in fsm_logic.inputs:
    c_type = fsm_logic.wire_to_c_type[input_port]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_t,dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      text += "  " + "static " + elem_t + " " + input_port
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ";\n"
    else:
      text += "  " + "static " + c_type + " " + input_port + ";\n"
  text += '''  // Output regs
'''
  for output_port in fsm_logic.outputs:
    c_type = fsm_logic.wire_to_c_type[output_port]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_t,dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      text += "  " + "static " + elem_t + " " + output_port + FSM_EXT
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ";\n"
    else:
      text += "  " + "static " + c_type + " " + output_port + FSM_EXT + ";\n"

  text += '''  // All local vars are regs too
'''
  # Collect all decls
  local_decls = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(fsm_logic.c_ast_node.body, c_ast.Decl)
  for local_decl in local_decls:
    c_type,var_name = C_TO_LOGIC.C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(local_decl, parser_state)
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_t,dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      text += "  " + "static " + elem_t + " " + var_name
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ";\n"
    else:
      text += "  " + "static " + c_type + " " + var_name + ";\n"
      
  text +='''  // Output wires
  ''' + fsm_logic.func_name + '''_OUTPUT_t o = {0};
  // Comb logic signaling that state transition using FSM_STATE
  // is not single cycle pass through and takes a clk
  uint1_t NEXT_CLK_STATE_VALID = 0;
  ''' + fsm_logic.func_name + '''_STATE_t NEXT_CLK_STATE = FSM_STATE;
'''
  # Get all flow control func call instances
  flow_ctrl_func_call_nodes = []
  func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(fsm_logic.c_ast_node, c_ast.FuncCall)
  for func_call_node in func_call_nodes:
    func_call_name = func_call_node.name.name
    if C_AST_NODE_USES_CTRL_FLOW_NODE(func_call_node, parser_state) and func_call_name != "__clk":
      flow_ctrl_func_call_nodes.append(func_call_node)
  if len(flow_ctrl_func_call_nodes) > 0:
    text += "  // Wires for subroutine calls\n"
    # Write wires for each func
    for flow_ctrl_func_call_node in flow_ctrl_func_call_nodes:
      flow_ctrl_func_name = flow_ctrl_func_call_node.name.name
      flow_ctrl_func_inst = flow_ctrl_func_name + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(flow_ctrl_func_call_node)
      text += "  " + flow_ctrl_func_name + "_INPUT_t " + flow_ctrl_func_inst + "_i = {0};\n"
      text += "  " + flow_ctrl_func_name + "_OUTPUT_t " + flow_ctrl_func_inst + "_o = {0};\n"

  text += '''
  // Handshake+inputs registered
  if(FSM_STATE == ENTRY_REG)
  {
    // Special first state signals ready, waits for start
    o.input_ready = 1;
    if(i.input_valid)
    {
      // Register inputs
'''
  for input_port in fsm_logic.inputs:
    text += "      " + input_port + " = i." + input_port + ";\n"
  
  # Go to first user state after getting inputs
  text += '''      // Go to first user state\n'''
  text += '''      FSM_STATE = ''' + fsm_logic.first_user_state.name + ''';
    }
  }
  
  // Pass through from ENTRY in same clk cycle
  
'''
  
  # List out all user states in parallel branch groups
  for state_group_i, state_group in enumerate(fsm_logic.state_groups):
    first_state_in_group = True
    for state_info in state_group:
      # Pass through if starts a group of parallel states
      if first_state_in_group:
        text += "  // State group " + str(state_group_i) + "\n"
        text += "  if("
      else:
        text += "  else if("
      first_state_in_group = False
      text += "FSM_STATE=="+state_info.name + ")\n"
      text += "  {\n"
      
      # Returning from func call
      if state_info.starts_w_fsm_func_return is not None:
        text += "    // " + state_info.starts_w_fsm_func_return.name.name + " FUNC CALL RETURN \n"
        output_driven_things = state_info.starts_w_fsm_func_return_output_driven_things
        if len(output_driven_things) > 0:
          # Connect func output wires
          # What func is being called?
          called_func_name = state_info.starts_w_fsm_func_return.name.name
          called_func_name_inst = called_func_name + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(state_info.starts_w_fsm_func_return)
          called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
          # Do outputs
          for output_i,output_port in enumerate(called_func_logic.outputs):
            output_driven_thing_i = output_driven_things[output_i]
            if isinstance(output_driven_thing_i,c_ast.Node):
              text += "    " + C_AST_NODE_TO_C_CODE(output_driven_thing_i, "", generator, is_lhs=True) + " = " +  called_func_name_inst + "_o." + output_port + ";\n"
            else:
              text += "    " + output_driven_thing_i + " = " +  called_func_name_inst + "_o." + output_port + ";\n"
        else:
          text += "    // UNUSED OUTPUT = " +  called_func_name + "();\n"
          
      # Comb logic c ast nodes
      if len(state_info.c_ast_nodes) > 0:
        for c_ast_node in state_info.c_ast_nodes:
          # Skip special control flow nodes
          # Return
          if c_ast_node == state_info.return_node:
            continue
          # TODO fix needing ";"
          # Fix print out to be tabbed out
          text += C_AST_NODE_TO_C_CODE(c_ast_node, "    ", generator) + "\n"
        
      # Branch logic
      if state_info.branch_nodes_tf_states is not None:
        mux_node,true_state,false_state = state_info.branch_nodes_tf_states
        text += "    if("+generator.visit(mux_node.cond)+")\n"
        text += "    {\n"
        text += "      FSM_STATE = " + true_state.name + ";\n"
        text += "    }\n"
        if false_state is not None:
          text += "    else\n"
          text += "    {\n"
          text += "      FSM_STATE = " + false_state.name + ";\n"
          text += "    }\n"
        elif state_info.always_next_state is not None:
          # OK to use default?
          text += "    else\n"
          text += "    {\n"
          text += "      FSM_STATE = " + state_info.always_next_state.name + "; // DEFAULT NEXT\n"
          text += "    }\n"
        else: # No next state, just start over?
          text += "    else\n"
          text += "    {\n"
          text += "      FSM_STATE = ENTRY_REG; // No next state, start over?\n"
          text += "    }\n"
        text += "  }\n"
        continue
        
      # Delay clk?
      if state_info.ends_w_clk:
        # Go to next state, but delayed
        if state_info.always_next_state is None:
          print("No next state for")
          state_info.print()
          sys.exit(-1)
        text += "    // __clk(); // Go to next state in next clock cycle \n"
        text += "    NEXT_CLK_STATE = " + state_info.always_next_state.name + ";\n"
        text += "    NEXT_CLK_STATE_VALID = 1;\n"
        text += "  }\n"
        continue
        
      # Func call entry
      if state_info.ends_w_fsm_func_entry is not None:
        text += "    // " + state_info.ends_w_fsm_func_entry.name.name + " FUNC CALL ENTRY \n"
        input_drivers = state_info.ends_w_fsm_func_entry_input_drivers
        # Connect func input wires, go to func call state
        # What func is being called?
        called_func_name = state_info.ends_w_fsm_func_entry.name.name
        called_func_name_inst = called_func_name + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(state_info.ends_w_fsm_func_entry)
        called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
        # Do inputs
        for input_i,input_port in enumerate(called_func_logic.inputs):
          input_driver_i = input_drivers[input_i]
          if isinstance(input_driver_i,c_ast.Node):
            text += "    " + called_func_name_inst + "_i." + input_port + " = " + C_AST_NODE_TO_C_CODE(input_driver_i, "", generator)
          else:
            text += "    " + called_func_name_inst + "_i." + input_port + " = " + input_driver_i + ";"
        text += "\n"
      
      # Func call state
      if state_info.is_fsm_func_call_state is not None:
        called_func_name = state_info.is_fsm_func_call_state.name.name
        called_func_name_inst = called_func_name + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(state_info.is_fsm_func_call_state)
        # ok to use wires driving inputs, not regs (included in func)
        text += '''    // ''' + state_info.is_fsm_func_call_state.name.name + ''' FUNC CALL, known ready
    ''' + called_func_name_inst + '''_i.input_valid = 1;
    ''' + called_func_name_inst + '''_i.output_ready = 1;
    ''' + called_func_name_inst + '''_o = ''' + called_func_name + FSM_EXT + '''(''' + called_func_name_inst + '''_i);
    if(''' + called_func_name_inst + '''_o.output_valid)
    {
      // DEFAULT NEXT
      FSM_STATE = ''' + state_info.always_next_state.name + '''; 
    }
'''
        text += "  }\n"
        continue    
    
      # Return?
      if state_info.return_node is not None:
        text += "    " + C_TO_LOGIC.RETURN_WIRE_NAME + FSM_EXT + " = " + generator.visit(state_info.return_node.expr) + ";\n"
        text += "    FSM_STATE = RETURN_REG;\n"
        text += "  }\n"
        continue
        
      # Default next
      if state_info.always_next_state is not None:
        text += "    // DEFAULT NEXT\n"
        text += "    FSM_STATE = " + state_info.always_next_state.name + ";\n";
      text += "  }\n"
  
  if len(fsm_logic.outputs) > 0:
    text += '''
  // Pass through to RETURN_REG in same clk cycle
  
  // Handshake+outputs registered
  if(FSM_STATE == RETURN_REG)
  {
    // Special last state signals done, waits for ready
    o.output_valid = 1;
    o.return_output = ''' + C_TO_LOGIC.RETURN_WIRE_NAME + FSM_EXT + ''';
    if(i.output_ready)
    {
      FSM_STATE = ENTRY_REG;
    }
  }
'''
  
  text += '''  
  // Wait/clk delay logic
  if(NEXT_CLK_STATE_VALID)
  {
    FSM_STATE = NEXT_CLK_STATE;
  }
  
  return o;
}
  
  '''
    
  #print(text)
  return text  
  
  
def C_AST_NODE_TO_STATES_LIST(c_ast_node, parser_state, curr_state_info=None, next_state_info=None):
  if curr_state_info is None:
    curr_state_info = FsmStateInfo()
    name_c_ast_node = None
    if type(c_ast_node) is c_ast.Compound:
      name_c_ast_node = c_ast_node.block_items[0]
    else:
      name_c_ast_node = c_ast_node
    curr_state_info.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
    curr_state_info.always_next_state = next_state_info
  # Collect chunks
  # Chunks are list of comb cast nodes that go into one state
  # Or individual nodes that need additional handling, returns list of one of more states
  chunks = COLLECT_COMB_LOGIC(c_ast_node, parser_state)
  # Do two passes, make states for all comb logic single state states
  
  # Pass 1
  #print("Node:",type(c_ast_node).__name__,c_ast_node.coord)
  #print("=chunks")
  comb_states_and_ctrl_flow_nodes = []
  for i,chunk in enumerate(chunks):
    # List of c_ast nodes
    if type(chunk) == list:
      #print("c ast",type(chunk[0]).__name__,chunk[0].coord)
      curr_state_info.c_ast_nodes += chunk
    else:
      # Or single c ast node of ctrl flow, cuts off accum of comb logic into current state
      comb_states_and_ctrl_flow_nodes.append(curr_state_info)
      # And saves ctrl flow node for next pass
      comb_states_and_ctrl_flow_nodes.append(chunk)
      # Setup next comb logic chunk if there is stuff there
      curr_state_info = FsmStateInfo()
      curr_state_info.always_next_state = next_state_info
      if i < len(chunks)-1:
        next_chunk = chunks[i+1]
        if type(next_chunk) == list:
          next_chunk_of_c_ast_nodes = next_chunk
          next_c_ast_node = next_chunk_of_c_ast_nodes[0]
        else:
          next_c_ast_node = next_chunk
        #print("ctrl1",type(next_c_ast_node).__name__, next_c_ast_node.coord)
        name_c_ast_node = None
        if type(next_c_ast_node) is c_ast.Compound:
          name_c_ast_node = next_c_ast_node.block_items[0]
        else:
          name_c_ast_node = next_c_ast_node
        curr_state_info.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
  # Final comb logic chunk
  if len(curr_state_info.c_ast_nodes) > 0:
    #print("state",curr_state_info.name)
    comb_states_and_ctrl_flow_nodes.append(curr_state_info)
  #print("=")
  
  # Pass 2
  states = []
  new_curr_state_info = None
  '''
  print("==== comb_states_and_ctrl_flow_nodes")
  for i,comb_state_or_ctrl_flow_node in enumerate(comb_states_and_ctrl_flow_nodes):
    if type(comb_state_or_ctrl_flow_node) is FsmStateInfo:
      print("comb state:")
      comb_state_or_ctrl_flow_node.print()
      print("")
    else:
      print("ctrl flow:",type(comb_state_or_ctrl_flow_node).__name__, comb_state_or_ctrl_flow_node.coord)
      print("")
  print("==== \n") 
  '''
  for i,comb_state_or_ctrl_flow_node in enumerate(comb_states_and_ctrl_flow_nodes):
    if type(comb_state_or_ctrl_flow_node) is FsmStateInfo:
      #  Update default next state if possible
      if i < len(comb_states_and_ctrl_flow_nodes)-2:
        # Known next is not comb, and after that should be comb
        comb_state_or_ctrl_flow_node.always_next_state = comb_states_and_ctrl_flow_nodes[i+2]
      states.append(comb_state_or_ctrl_flow_node)
      new_curr_state_info = comb_state_or_ctrl_flow_node
    else:
      # Flow control node to elborate to more states
      new_next_state_info = next_state_info
      if i < len(comb_states_and_ctrl_flow_nodes)-1:
        new_next_state_info = comb_states_and_ctrl_flow_nodes[i+1]
      ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(comb_state_or_ctrl_flow_node, new_curr_state_info, new_next_state_info, parser_state)
      states += ctrl_flow_states
      
      # Update default next for curr state given new states?
      if len(ctrl_flow_states) > 0:
        if new_curr_state_info.always_next_state is None:
          new_curr_state_info.always_next_state = ctrl_flow_states[0]
     
  
  return states
  
def GET_STATE_TRANS_LISTS(start_state):
  #print("start_state.name",start_state.name,start_state)
  # Branch or pass through default next or clock(ends chain)?
  if start_state.ends_w_clk:
    #print(" ends w clk")
    return [[start_state]]
  # Going to return state
  elif start_state.return_node is not None:
    #print(" returns")
    return [[start_state]]
  
  poss_next_states = set()
  # Branching?
  if start_state.branch_nodes_tf_states is not None:
    (c_ast_node,true_state,false_state) = start_state.branch_nodes_tf_states
    if true_state != start_state: # No loops?
      poss_next_states.add(true_state)
    if false_state is not None and false_state != start_state: # No loops?
      #print(" poss_next_state.name false",false_state.name)
      poss_next_states.add(false_state)
    elif false_state is None and start_state.always_next_state is not None and start_state.always_next_state != start_state: # No loops?
      poss_next_states.add(start_state.always_next_state) # Default next if no false branch
  elif start_state.always_next_state is not None and start_state.always_next_state != start_state: # No loops?:
    #print(" poss_next_state.name always",start_state.always_next_state.name)
    poss_next_states.add(start_state.always_next_state)
  
  # Make a return state list for each state
  states_trans_lists = []
  for poss_next_state in poss_next_states:
    start_states_trans_list = [start_state]
    new_states_trans_lists = GET_STATE_TRANS_LISTS(poss_next_state)
    for new_states_trans_list in new_states_trans_lists:
      combined_state_trans_list = start_states_trans_list + new_states_trans_list
      states_trans_lists.append(combined_state_trans_list)
    
  #print("start_state.name",start_state.name,states_trans_lists)
  return states_trans_lists
  
def C_AST_CTRL_FLOW_NODE_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state):
  if type(c_ast_node) == c_ast.If:
    return C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name=="__clk":
    return C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) == c_ast.Return:
    return C_AST_CTRL_FLOW_RETURN_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) == c_ast.While:
    return C_AST_CTRL_FLOW_WHILE_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) is c_ast.FuncCall and FUNC_USES_FSM_CLK(c_ast_node.name.name, parser_state):
    return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) == c_ast.Assignment:
    return C_AST_CTRL_FLOW_ASSIGNMENT_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  elif type(c_ast_node) == c_ast.Decl:
    return C_AST_CTRL_FLOW_DECL_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state)
  else:
    raise Exception(f"TODO Unsupported flow node inside: {type(c_ast_node).__name__} {c_ast_node.coord}")

def C_AST_CTRL_FLOW_DECL_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state):
  # Should be declaring and assigning/initing with func call
  func_call_node = c_ast_node.init
  #print(c_ast_node)
  # Python as easy as it seems?
  decl_wo_func_call = copy.copy(c_ast_node)
  decl_wo_func_call.init = None
  output_driven_things = [decl_wo_func_call]
  return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(func_call_node, curr_state_info, next_state_info, parser_state, output_driven_things)

def C_AST_CTRL_FLOW_ASSIGNMENT_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state):
  # For now only allow comb lhs and func call as rhs?
  if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.lvalue, parser_state):
    raise Exception(f"TODO unsupported control flow in assignment LHS: {c_ast_node.lvalue.coord}")
  if type(c_ast_node.rvalue) != c_ast.FuncCall:
    raise Exception(f"TODO unsupported control flow in assignment RHS: {c_ast_node.rvalue.coord}")
  func_call_node = c_ast_node.rvalue
  output_driven_things = [c_ast_node.lvalue]
  return C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(func_call_node, curr_state_info, next_state_info, parser_state, output_driven_things)

def C_AST_CTRL_FLOW_FUNC_CALL_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state, output_driven_things=[]):
  states = [] 

  # Set current state to have func entry
  curr_state_info.ends_w_fsm_func_entry = c_ast_node
  # Check if each input uses C_AST_NODE_USES_CTRL_FLOW_NODE
  # Make intermediate wire+states for things that do, get states
  input_drivers = []
  called_func_name = c_ast_node.name.name
  called_func_logic = parser_state.FuncLogicLookupTable[called_func_name]
  for i in range(0, len(called_func_logic.inputs)):
    input_port_name = called_func_logic.inputs[i]
    input_c_ast_node = c_ast_node.args.exprs[i]
    if C_AST_NODE_USES_CTRL_FLOW_NODE(input_c_ast_node, parser_state):
      raise Exception(f"TODO unsupported control flow in func call argument: {input_c_ast_node.coord}")
    else:
      # Input driven by comb logic
      input_drivers.append(input_c_ast_node)
  curr_state_info.ends_w_fsm_func_entry_input_drivers = input_drivers
  
  # Set next state to be the func call state
  # Make func call state
  func_call_state = FsmStateInfo()
  func_call_state.is_fsm_func_call_state = c_ast_node
  # Set current state to go to func call state
  curr_state_info.always_next_state = func_call_state
  func_call_state.name = str(type(c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(c_ast_node) + "_SUBROUTINE"
  if next_state_info is None:
      print("No next state entering if ",func_call_state.name,"from",curr_state_info.name)
      sys.exit(-1)
  func_call_state.always_next_state = next_state_info
  states.append(func_call_state)
      
  # Make state after curr func, next_state_info, have func return logic
  next_state_info.starts_w_fsm_func_return = c_ast_node
  next_state_info.starts_w_fsm_func_return_output_driven_things = output_driven_things

  return states

def C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_clk_func_call, curr_state_info, next_state_info, parser_state):
  states = [] 

  # Update curr state as ending with clk()
  curr_state_info.ends_w_clk = True

  return states
  
def C_AST_CTRL_FLOW_RETURN_TO_STATES(c_ast_node, curr_state_info, next_state_info, parser_state):
  states = [] 

  if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_node.expr, parser_state):
    raise Exception(f"TODO unsupported control flow in return expression: {c_ast_node.expr.coord}")

  # Update curr state as ending with return transition
  curr_state_info.return_node = c_ast_node
  
  return states
    
def C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_if, curr_state_info, next_state_info, parser_state):
  states = []
  
  if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_if.cond, parser_state):
    raise Exception(f"TODO unsupported control flow in if condition: {c_ast_if.cond.coord}")
  
  # Create a state for true logic and insert it into return list of states
  true_state = FsmStateInfo()
  name_c_ast_node = None
  if type(c_ast_if.iftrue) is c_ast.Compound:
    name_c_ast_node = c_ast_if.iftrue.block_items[0]
  else:
    name_c_ast_node = c_ast_if.iftrue
  true_state.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
  if next_state_info is None:
      print("No next state entering if ",true_state.name,"from",curr_state_info.name)
      sys.exit(-1)
  true_state.always_next_state = next_state_info
  true_states = C_AST_NODE_TO_STATES_LIST(c_ast_if.iftrue, parser_state, true_state, next_state_info)
  #new_true_states = true_states[:].remove(true_state)
  states += true_states
  
  # Similar for false
  false_state = None
  new_false_states = []
  if c_ast_if.iffalse is not None:
    false_state = FsmStateInfo()
    name_c_ast_node = None
    if type(c_ast_if.iffalse) is c_ast.Compound:
      name_c_ast_node = c_ast_if.iffalse.block_items[0]
    else:
      name_c_ast_node = c_ast_if.iffalse
    false_state.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
    if next_state_info is None:
      print("No next state entering if ",false_state.name,"from",curr_state_info.name)
      sys.exit(-1)
    false_state.always_next_state = next_state_info
    false_states = C_AST_NODE_TO_STATES_LIST(c_ast_if.iffalse, parser_state, false_state, next_state_info)
    #new_false_states = false_states[:].remove(false_state)
    states += false_states
  
  
  # Add mux sel calculation, and jumping to true or false states 
  # to current state after comb logic
  curr_state_info.branch_nodes_tf_states = (c_ast_if,true_state,false_state)

  return states
  
#WHILE COND NEED OWN STATEE FIX WHILE LOOP TO NOT GO BACK TO COMB LOGIC BEFORE WHILE COND
  
def C_AST_CTRL_FLOW_WHILE_TO_STATES(c_ast_while, curr_state_info, next_state_info, parser_state):
  states = []
  
  # While default next state is looping backto eval loop cond again
  # Different from if
  
  if C_AST_NODE_USES_CTRL_FLOW_NODE(c_ast_while.cond, parser_state):
    raise Exception(f"TODO unsupported control flow in while condition: {c_ast_while.cond.coord}")
  
  # While condition checking needs own state without comb logic
  if len(curr_state_info.c_ast_nodes) != 0:
    # New curr state needed
    prev_curr_state_info = curr_state_info
    curr_state_info = FsmStateInfo()
    curr_state_info.name = str(type(c_ast_while).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(c_ast_while)
    states += [curr_state_info]
    # Prev state default goes to new state
    prev_curr_state_info.always_next_state = curr_state_info
  
  # Create a state for while body logic and insert it into return list of states
  while_state = FsmStateInfo()
  name_c_ast_node = None
  if type(c_ast_while.stmt) is c_ast.Compound:
    name_c_ast_node = c_ast_while.stmt.block_items[0]
  else:
    name_c_ast_node = c_ast_while.stmt
  while_state.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
  #if next_state_info is None:
  #  print("No next state entering while ",while_state.name,"from",curr_state_info.name)
  #  sys.exit(-1)
  while_state.always_next_state = curr_state_info # Default staying in while
  while_states = C_AST_NODE_TO_STATES_LIST(c_ast_while.stmt, parser_state, while_state, curr_state_info)
  states += while_states
   
  # Add mux sel calculation, and jumping to do current state muxing -> body logic
  curr_state_info.branch_nodes_tf_states = (c_ast_while, while_state, next_state_info)

  return states
  
def C_AST_FSM_FUNDEF_BODY_TO_LOGIC(c_ast_func_def_body, parser_state):
    states_list = C_AST_NODE_TO_STATES_LIST(c_ast_func_def_body, parser_state)
    parser_state.existing_logic.first_user_state = states_list[0]

    #Get all state transitions lists starting at
    #entry node + node after each __clk()  
    start_states = set([states_list[0]])
    for state in states_list:
      if state.ends_w_clk:
        start_states.add(state.always_next_state)
    all_state_trans_lists = []
    for start_state in start_states:
      try:
        state_trans_lists_starting_at_start_state = GET_STATE_TRANS_LISTS(start_state)
      except RecursionError as re:
        raise Exception(f"Function: {parser_state.existing_logic.func_name} could contain a data-dependent infinite (__clk()-less) loop starting at {start_state.name}")
      all_state_trans_lists += state_trans_lists_starting_at_start_state
      
    # Use transition lists to group states
    #print("Transition lists:")
    state_to_latest_index = dict()
    for state_trans_list in all_state_trans_lists:
      text = "States: "
      for state_i,state in enumerate(state_trans_list):
        text += state.name + " -> "
        if state not in state_to_latest_index:
          state_to_latest_index[state] = state_i
        if state_i > state_to_latest_index[state]:
          state_to_latest_index[state] = state_i
      #print(text)
    state_groups = [None]*(max(state_to_latest_index.values())+1)
    for state,index in state_to_latest_index.items():
      #print("Last Index",index,state.name)
      if state_groups[index] is None:
        state_groups[index] = set()
      state_groups[index].add(state)
    for state_group in state_groups:
      text = "State Group: "
      for state in state_group:
        text += state.name + ","
      #print(text)
    parser_state.existing_logic.state_groups = state_groups
    
    return parser_state.existing_logic

def FUNC_USES_FSM_CLK(func_name, parser_state):
  if func_name == "__clk":
    return True
  else:
    if func_name in parser_state.FuncLogicLookupTable:
      func_logic = parser_state.FuncLogicLookupTable[func_name]
      if func_logic.is_fsm_clk_func:
        return True
      # Check submodules of logic
      for sub_inst,sub_func_name in func_logic.submodule_instances.items():
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
  func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.FuncCall)
  for func_call_node in func_call_nodes:
    #if func_call_node.name.name  == "__clk":
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
