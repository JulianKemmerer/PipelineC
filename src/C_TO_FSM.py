import sys
import copy
from pycparser import c_parser, c_ast, c_generator

import C_TO_LOGIC

# FSM funcs cant be main functions

def PARSE_FILE(c_filename):
  c_text = open(c_filename).read()
  c_ast_func_defs = C_TO_LOGIC.GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(c_text, c_filename)
  for c_ast_func_def in c_ast_func_defs:
    C_AST_FUNC_DEF_TO_FSM_LOGIC(c_ast_func_def)
  sys.exit(0) 

class FsmStateInfo:
  def __init__(self):
    self.name = None
    self.c_ast_nodes = [] # C ast nodes
    self.always_next_state = None # State info obj
    # Todo other flags?
    self.branch_nodes_tf_states = None # (c_ast_node,true state, false state)
    self.ends_w_clk = False
    self.pass_through_if = True
    self.return_node = None
  
  '''  
  def get_return_node(self):
    for c_ast_node in self.c_ast_nodes:
      if type(c_ast_node) == c_ast.Return:
        return c_ast_node
    return None
  '''
   
  def print(self):
    if self.pass_through_if:
      print("If: " + str(self.name))
    else:
      print("Else If: " + str(self.name))
    
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
      
    if self.return_node is not None:
      print("Return, function end")
      return # Return is always last
      
       
    

# Storing per func dict of state_name -> FsmStateInfo
class FsmLogic:
  def __init__(self):
    #self.state_to_info = dict()
    self.states_list = []

def C_AST_NODE_TO_C_CODE(c_ast_node, indent = "", generator=None):
  if generator is None:
    generator = c_generator.CGenerator()
  text = generator.visit(c_ast_node)
  # What nodes dont need
  maybe_semicolon = ";"
  if type(c_ast_node) == c_ast.Compound:
    maybe_semicolon = ""
  if type(c_ast_node) == c_ast.If:
    maybe_semicolon = ""
  text += maybe_semicolon
  lines = []
  for line in text.split("\n"):
    if line != "":
      lines.append(indent + line)
  return "\n".join(lines) + "\n"
  
  
def FSM_LOGIC_TO_C_CODE(fsm_logic):
   
  
  
  first_user_state = fsm_logic.states_list[0]
  generator = c_generator.CGenerator()
  text = ""
  text += '''
typedef enum main_STATE_t{
 ENTRY_REG,
'''
  for state_info in fsm_logic.states_list:
    text += " " + state_info.name + ",\n"
  text += ''' RETURN_REG,
}main_STATE_t;
typedef struct main_INPUT_t
{
  uint1_t input_valid;
  uint8_t x;
  uint1_t output_ready;
}main_INPUT_t;
typedef struct main_OUTPUT_t
{
  uint1_t input_ready;
  uint8_t RETURN_OUTPUT;
  uint1_t output_valid;
}main_OUTPUT_t;
main_OUTPUT_t main_FSM(main_INPUT_t i) // Input wires
{
  // State reg
  static main_STATE_t FSM_STATE;
  // Input regs
  static uint8_t x;
  // Output reg
  static uint8_t RETURN_VAL;
  // All local vars are regs too 
  //(none here)
  // Output wires
  main_OUTPUT_t o;
  o.input_ready = 0;
  o.RETURN_OUTPUT = 0;
  o.output_valid = 0;
  // Comb logic signaling that state transition using FSM_STATE
  // is not single cycle pass through and takes a clk
  uint1_t NEXT_CLK_STATE_VALID = 0;
  main_STATE_t NEXT_CLK_STATE = FSM_STATE;
  
  // Handshake+inputs registered
  if(FSM_STATE == ENTRY_REG)
  {
    // Special first state signals ready, waits for start
    o.input_ready = 1;
    if(i.input_valid)
    {
      // Register input
      x = i.x;
      FSM_STATE = ''' + first_user_state.name + ''';
    }
  }

  // Pass through from ENTRY in same clk cycle

'''
  for state_info in fsm_logic.states_list:
    if not state_info.pass_through_if:
      text += "  else if("
    else:
      text += "  if("
    text += "FSM_STATE=="+state_info.name + ")\n"
    text += "  {\n"
    
    # Comb logic c ast nodes
    if len(state_info.c_ast_nodes) > 0:
      for c_ast_node in state_info.c_ast_nodes:
        # Skip special control flow nodes
        # Return
        if c_ast_node == state_info.return_node:
          continue
        # TODO fix needing ";"
        # Fix print out to be tabbed out
        text += C_AST_NODE_TO_C_CODE(c_ast_node, "    ", generator)
      #text += "\n"
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
      else:
        # OK to use default?
        text += "    else\n"
        text += "    {\n"
        text += "      FSM_STATE = " + state_info.always_next_state.name + "; // DEFAULT NEXT\n"
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
      
    # Return?
    if state_info.return_node is not None:
      text += "    RETURN_VAL = " + generator.visit(state_info.return_node.expr) + ";\n"
      text += "    FSM_STATE = RETURN_REG;\n"
      text += "  }\n"
      continue
      
    # Default next
    if state_info.always_next_state is not None:
      text += "    FSM_STATE = " + state_info.always_next_state.name + "; // DEFAULT NEXT\n"
    text += "  }\n"
  
  text += '''
  // Pass through to RETURN_REG in same clk cycle
  
  // Handshake+outputs registered
  if(FSM_STATE == RETURN_REG)
  {
    // Special last state signals done, waits for ready
    o.output_valid = 1;
    o.RETURN_OUTPUT = RETURN_VAL;
    if(i.output_ready)
    {
      FSM_STATE = ENTRY_REG;
    }
  }
  
  // Wait/clk delay logic
  if(NEXT_CLK_STATE_VALID)
  {
    FSM_STATE = NEXT_CLK_STATE;
  }
  
  return o;
}
  
  '''
    
  print(text)
  return text  
  
  
def C_AST_NODE_TO_STATES_LIST(c_ast_node, curr_state_info=None, next_state_info=None):
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
  chunks = COLLECT_COMB_LOGIC(c_ast_node)
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
      ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(comb_state_or_ctrl_flow_node, new_curr_state_info, new_next_state_info)
      states += ctrl_flow_states
      
      # Update default next for curr state given new states?
      if len(ctrl_flow_states) > 0:
        if new_curr_state_info.always_next_state is None:
          new_curr_state_info.always_next_state = ctrl_flow_states[0]
     
  
  return states
  
def GET_STATE_TRANS_LISTS(start_state):
  print("start_state.name",start_state.name,start_state)
  # Branch or pass through default next or clock(ends chain)?
  if start_state.ends_w_clk:
    print(" ends w clk")
    return [[start_state]]
  # Going to return state
  elif start_state.return_node is not None:
    print(" returns")
    return [[start_state]]
  
  poss_next_states = []
  # Branching?
  if start_state.branch_nodes_tf_states is not None:
    (c_ast_node,true_state,false_state) = start_state.branch_nodes_tf_states
    if true_state != start_state: # No loops?
      print(" poss_next_state.name true",true_state.name)
      poss_next_states.append(true_state)
    if false_state is not None and false_state != start_state: # No loops?
      print(" poss_next_state.name false",false_state.name)
      poss_next_states.append(false_state)
    elif false_state is None and start_state.always_next_state != start_state: # No loops?
      poss_next_states.append(start_state.always_next_state) # Default next if no false branch
  elif start_state.always_next_state is not None and start_state.always_next_state != start_state: # No loops?:
    print(" poss_next_state.name always",start_state.always_next_state.name)
    poss_next_states.append(start_state.always_next_state)
  
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
  

def C_AST_FUNC_DEF_TO_FSM_LOGIC(c_ast_func_def):
  if c_ast_func_def.body.block_items is None:
    return
  fsm_logic = FsmLogic()
  #state_counter = 0
  #curr_state_info = FsmStateInfo()
  #curr_state_info.name = "LOGIC" + str(state_counter)
  
  states_list = C_AST_NODE_TO_STATES_LIST(c_ast_func_def.body)
  
  #for state_info in states_list:
  #  print("State:",state_info)
  #  state_info.print()
  #  print()
  #sys.exit(0)
  
  #Get all state transitions lists starting at
  #entry node + node after each __clk()
  #parallel_states_list = []
  
  start_states = [states_list[0]]
  for state in states_list:
    if state.ends_w_clk:
      start_states.append(state.always_next_state)
  
  all_state_trans_lists = []
  for start_state in start_states:
    state_trans_lists_starting_at_start_state = GET_STATE_TRANS_LISTS(start_state)
    all_state_trans_lists += state_trans_lists_starting_at_start_state
    
  print("Transition lists:")
  for state_trans_list in all_state_trans_lists:
    text = "States: "
    for state in state_trans_list:
      text += state.name + " -> "
    print(text)
  #sys.exit(0)
          
  # TODO sketch out basic C code gen from fsm_logic object
  fsm_logic.states_list = states_list
  FSM_LOGIC_TO_C_CODE(fsm_logic) 
  sys.exit(0)
  '''
  # All func def logic has an output wire called "return"
  return_type = c_ast_funcdef.decl.type.type.type.names[0]
  if return_type != "void":
    return_wire_name = RETURN_WIRE_NAME
    parser_state.existing_logic.outputs.append(return_wire_name)
    parser_state.existing_logic.wires.add(return_wire_name)
    #print("return_type",return_type)
    parser_state.existing_logic.wire_to_c_type[return_wire_name] = return_type

  # First get name of function from the declaration
  parser_state.existing_logic.func_name = c_ast_funcdef.decl.name
  
  # Then get input wire names from the function def
  #print "func def:",c_ast_funcdef
  if c_ast_funcdef.decl.type.args is not None:
    for param_decl in c_ast_funcdef.decl.type.args.params:
      input_wire_name = param_decl.name
      parser_state.existing_logic.inputs.append(input_wire_name)
      parser_state.existing_logic.wires.add(input_wire_name)
      parser_state.existing_logic.variable_names.add(input_wire_name)
      #print "Append input", input_wire_name
      c_type,input_var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(param_decl, parser_state)
      parser_state.existing_logic.wire_to_c_type[input_wire_name] = c_type
  
  
  # Merge with logic from the body of the func def
  driven_wire_names=[]
  prepend_text=""
  if parse_body:
    body_logic = C_AST_NODE_TO_LOGIC(c_ast_funcdef.body, driven_wire_names, prepend_text, parser_state)   
    parser_state.existing_logic.MERGE_COMB_LOGIC(body_logic)
    
  # Connect globals at end of func logic
  parser_state.existing_logic = CONNECT_FINAL_STATE_WIRES(prepend_text, parser_state, c_ast_funcdef)
  '''
  
  
def C_AST_CTRL_FLOW_NODE_TO_STATES(c_ast_node, curr_state_info, next_state_info):
  if type(c_ast_node) == c_ast.If:
    return C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_node, curr_state_info, next_state_info)
  elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name=="__clk":
    return C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_node, curr_state_info, next_state_info)
  elif type(c_ast_node) == c_ast.Return:
    return C_AST_CTRL_FLOW_RETURN_TO_STATES(c_ast_node, curr_state_info, next_state_info)
  elif type(c_ast_node) == c_ast.While:
    return C_AST_CTRL_FLOW_WHILE_TO_STATES(c_ast_node, curr_state_info, next_state_info)
  else:
    raise Exception(f"Unknown ctrl flow node: {type(c_ast_node).__name__} {c_ast_node.coord}")

def C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_clk_func_call, curr_state_info, next_state_info):
  states = [] 
  '''
  # Single state doing nothing for the clock
  clk_state = FsmStateInfo()
  clk_state.name = "CLOCK_STATE"
  clk_state.always_next_state = next_state_info
  states.append(clk_state)'''
  # Update curr state as ending with clk()?
  curr_state_info.ends_w_clk = True
  
  return states
  
def C_AST_CTRL_FLOW_RETURN_TO_STATES(c_ast_node, curr_state_info, next_state_info):
  states = [] 

  curr_state_info.return_node = c_ast_node
  
  return states
    
def C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_if, curr_state_info, next_state_info):
  states = [] 
  
  # Create a state for true logic and insert it into return list of states
  true_state = FsmStateInfo()
  true_state.name = str(type(c_ast_if).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(c_ast_if) + "_TRUE"
  if next_state_info is None:
      print("No next state entering if ",true_state.name,"from",curr_state_info.name)
      sys.exit(-1)
  true_state.always_next_state = next_state_info
  true_states = C_AST_NODE_TO_STATES_LIST(c_ast_if.iftrue, true_state, next_state_info)
  #new_true_states = true_states[:].remove(true_state)
  states += true_states
  
  # Similar for false
  false_state = None
  new_false_states = []
  if c_ast_if.iffalse is not None:
    false_state = FsmStateInfo()
    false_state.name = str(type(c_ast_if).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(c_ast_if) + "_FALSE"
    if next_state_info is None:
      print("No next state entering if ",false_state.name,"from",curr_state_info.name)
      sys.exit(-1)
    false_state.always_next_state = next_state_info
    #false_state.pass_through_if = False  TODO FIX
    false_states = C_AST_NODE_TO_STATES_LIST(c_ast_if.iffalse, false_state, next_state_info)
    #new_false_states = false_states[:].remove(false_state)
    states += false_states
  
  
  # Add mux sel calculation, and jumping to true or false states 
  # to current state after comb logic
  curr_state_info.branch_nodes_tf_states = (c_ast_if,true_state,false_state)

  return states
  
def C_AST_CTRL_FLOW_WHILE_TO_STATES(c_ast_while, curr_state_info, next_state_info):
  states = []
  
  # While default next state is looping backto eval loop cond again
  # Different from if
  
  # Create a state for while body logic and insert it into return list of states
  while_state = FsmStateInfo()
  name_c_ast_node = None
  if type(c_ast_while.stmt) is c_ast.Compound:
    name_c_ast_node = c_ast_while.stmt.block_items[0]
  else:
    name_c_ast_node = c_ast_while.stmt
  while_state.name = str(type(name_c_ast_node).__name__) + "_" + C_TO_LOGIC.C_AST_NODE_COORD_STR(name_c_ast_node)
  if next_state_info is None:
      print("No next state entering while ",while_state.name,"from",curr_state_info.name)
      sys.exit(-1)
  while_state.always_next_state = curr_state_info # Default staying in while
  while_states = C_AST_NODE_TO_STATES_LIST(c_ast_while.stmt, while_state, curr_state_info)
  states += while_states
   
  
  # Add mux sel calculation, and jumping to do current state muxing -> body logic
  curr_state_info.branch_nodes_tf_states = (c_ast_while, while_state, next_state_info)

  return states
  

def C_AST_NODE_USES_FSM_CLK(c_ast_node):
  func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.FuncCall)
  for func_call_node in func_call_nodes:
    if func_call_node.name.name == "__clk":
      return True
    
  # Or return?
  ret_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.Return)
  if len(ret_nodes) > 0:
    return True
  
  return False 

def COLLECT_COMB_LOGIC(c_ast_node_in):
  chunks = []
  comb_logic_nodes = []
  c_ast_nodes = [c_ast_node_in]
  if type(c_ast_node_in) is c_ast.Compound:
    if c_ast_node_in.block_items is not None:
      c_ast_nodes = c_ast_node_in.block_items[:]
      
  for c_ast_node in c_ast_nodes:
    if not C_AST_NODE_USES_FSM_CLK(c_ast_node):
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
