// To replace #pragma ONE_HOT

#define ONE_HOT_IN_DECL(name, num_states) \
uint1_t name[num_states]
#define ONE_HOT_REG_DECL(name, num_states, init_state_num) \
static uint1_t name[num_states] = {[init_state_num]=1};
#define ONE_HOT_CONST_EQ(name, state_num) \
name[state_num]
#define ONE_HOT_TRANS_NEXT_FROM(name, next_state_num, from_state_num) \
name[from_state_num] = 0; \
name[next_state_num] = 1;
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
#define ONE_HOT_VAR_ASSIGN(lhs_name, rhs_name, num_states) \
uint32_t ONE_HOT_ASSIGN_i; \
for(ONE_HOT_ASSIGN_i = 0; ONE_HOT_ASSIGN_i < num_states; ONE_HOT_ASSIGN_i+=1) \
{ \
  lhs_name[ONE_HOT_ASSIGN_i] = rhs_name[ONE_HOT_ASSIGN_i]; \
}
