
#include "uintN_t.h"
#include "compiler.h"

#include "xstr.h"

typedef int template_t; // Ignored by PipelineC

#define template_typename(T)\
typedef template_t T##_t;

#define template(T)\
T##_t

#define type(T)\
xstr(T) // Make into string literal


// Template types (structs)

#define template_type_inst(temp_struct_name)\
typedef int temp_struct_name;


#define template2_struct_name(name, T0, T1)\
PPCAT(PPCAT(PPCAT(PPCAT(name,_),T0),_),T1)