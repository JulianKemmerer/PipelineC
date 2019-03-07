
// Macro for one item stream buffer
// Stream type = has .valid 
#define SBUF(type, name) type name##_data;\
type name(type data, uint1_t read){\
        if(data.valid)\
        {\
                name##_data = data;\
        }\
        type rv;\
        rv = name##_data;\
        rv.valid = 0;\
        if(read)\
        {\
                rv.valid = name##_data.valid;\
                name##_data.valid = 0;\
        }\
        return rv;\
}
