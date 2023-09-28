// Replaces #pragma ONE_HOT
// Declares one hot enum of bit array
// needs constant strings for the 
// number of states and for the initial state value

// Declare an input
//  like: my_enum_t name
#define ONE_HOT_IN_DECL(name, num_states) \
uint1_t name[num_states]

// Declare a static local register
//  like: static my_enum_t name = init;
#define ONE_HOT_REG_DECL(name, num_states, init_state_num) \
static uint1_t name[num_states] = {[init_state_num]=1};

#define ONE_HOT_REG_DECL_ZERO_INIT(name, num_states) \
static uint1_t name[num_states] = {0};

// Compare a enum variable to a constant state literal
//  like: name==STATE
#define ONE_HOT_CONST_EQ(name, state_num) \
name[state_num]

// Assign to the state variable making a one hot transition
//  like: name = NEXT; // Efficient since clears current 'from' state bit only
#define ONE_HOT_TRANS_NEXT_FROM(name, next_state_num, from_state_num) \
name[from_state_num] = 0; \
name[next_state_num] = 1;

// Assign to all one hot bits with a constant value
//  like: name = NEXT; // Inefficient since clears all other bits then next state
#define ONE_HOT_CONST_ASSIGN(name, next_state_num, num_states) \
uint32_t ONE_HOT_CNST_ASSIGN_i; \
for(ONE_HOT_CNST_ASSIGN_i = 0; ONE_HOT_CNST_ASSIGN_i < num_states; ONE_HOT_CNST_ASSIGN_i+=1) \
{ \
  if(ONE_HOT_CNST_ASSIGN_i==next_state_num){ \
    name[ONE_HOT_CNST_ASSIGN_i] = 1; \
  }else{ \
    name[ONE_HOT_CNST_ASSIGN_i] = 0; \
  } \
}

// Assign to all one hot bits with the value of another one hot variable
//  like: name_a = name_b;
#define ONE_HOT_VAR_ASSIGN(lhs_name, rhs_name, num_states) \
uint32_t ONE_HOT_ASSIGN_i; \
for(ONE_HOT_ASSIGN_i = 0; ONE_HOT_ASSIGN_i < num_states; ONE_HOT_ASSIGN_i+=1) \
{ \
  lhs_name[ONE_HOT_ASSIGN_i] = rhs_name[ONE_HOT_ASSIGN_i]; \
}
