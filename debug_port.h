#pragma once
#include "compiler.h" // PRAGMA_MESSAGE
#include "wire.h"     // WIRE READ+WRITE
#define DEBUG_OUTPUT_DECL(type_t, name) \
type_t name##_DEBUG; \
PRAGMA_MESSAGE(MAIN name##_DEBUG_OUTPUT_MAIN) \
type_t name##_DEBUG_OUTPUT_MAIN() \
{ \
  type_t rv; \
  WIRE_READ(type_t, rv, name##_DEBUG) \
  return rv; \
} \
void name(type_t val) \
{ \
  WIRE_WRITE(type_t, name##_DEBUG, val) \
}

#define DEBUG_INPUT_DECL(type_t, name) \
type_t name##_DEBUG; \
PRAGMA_MESSAGE(MAIN name##_DEBUG_INPUT_MAIN) \
void name##_DEBUG_INPUT_MAIN(type_t val) \
{ \
  WIRE_WRITE(type_t, name##_DEBUG, val)\
} \
type_t name() \
{ \
  type_t rv; \
  WIRE_READ(type_t, rv, name##_DEBUG) \
  return rv; \
}
