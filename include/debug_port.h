#pragma once
#include "compiler.h" // PRAGMA_MESSAGE

#define DEBUG_OUTPUT_DECL(type_t, name) \
DECL_OUTPUT(type_t, name##_DEBUG) \
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
void name##_DEBUG() \
{ \
  name##_DEBUG = name; \
}

#define DEBUG_INPUT_DECL(type_t, name) \
DECL_INPUT(type_t, name##_DEBUG) \
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
void name##_DEBUG() \
{ \
  name = name##_DEBUG;\
}

// TODO replace with DECL_IN/OUTPUT_REG(type_t, name##_DEBUG) + mark debug?
// need to change if .endswith("_DEBUG") logic

#define DEBUG_OUTPUT_REG_DECL(type_t, name) \
DECL_OUTPUT(type_t, name##_REG_DEBUG)\
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_MARK_DEBUG name##_DEBUG) \
void name##_DEBUG() \
{ \
  static type_t DEBUG_##name; \
  name##_REG_DEBUG = DEBUG_##name; \
  DEBUG_##name = name; \
}

#define DEBUG_INPUT_REG_DECL(type_t, name) \
DECL_INPUT(type_t, name##_REG_DEBUG)\
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_MARK_DEBUG name##_DEBUG) \
void name##_DEBUG() \
{ \
  static type_t DEBUG_##name; \
  name = DEBUG_##name; \
  DEBUG_##name = name##_REG_DEBUG; \
}
