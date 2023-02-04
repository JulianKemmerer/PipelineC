#pragma once
#include "compiler.h" // PRAGMA_MESSAGE

#define DEBUG_OUTPUT_DECL(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
type_t name##_DEBUG() \
{ \
  return name; \
}

#define DEBUG_INPUT_DECL(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
void name##_DEBUG(type_t val_input) \
{ \
  name = val_input;\
}

#define DEBUG_REG_DECL(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_WIRES name##_DEBUG) \
PRAGMA_MESSAGE(FUNC_MARK_DEBUG name##_DEBUG) \
void name##_DEBUG() \
{ \
  static type_t DEBUG_##name; \
  DEBUG_##name = name; \
}
