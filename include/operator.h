// Wrap C++ 'operator' keyword based function defs 
// with PipelineC internal versions
// see https://github.com/JulianKemmerer/PipelineC/wiki/Automatically-Generated-Functionality#overload

#ifdef __PIPELINEC__
#define OPERATOR_PLUS(out_t, left_t, right_t) \
out_t BIN_OP_PLUS_##left_t##_##right_t(left_t left, right_t right)
#else
#define OPERATOR_PLUS(out_t, left_t, right_t) \
out_t operator+(left_t left, right_t right)
#endif

/*
#include "intN_t.h"
#include "uintN_t.h"
typedef struct point{
  uint8_t x;
  uint8_t y;
}point;

OPERATOR_PLUS(point, point, point) {
  point S;
  S.x = left.x + right.x;
  S.y = left.y + right.y;
  return S;
}

#pragma MAIN_MHZ test 400
point test(point a, point b){
  return a + b;
}
*/