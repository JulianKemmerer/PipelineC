#pragma once

#define ndarray(NDIMS, type_t) PPCAT(PPCAT(PPCAT(ndarray_,NDIMS),_),type_t)

#define DECL_NDARRAY_TYPE(NDIMS, type_t)\
typedef struct ndarray(NDIMS, type_t){\
  type_t data;\
  uint1_t eod[NDIMS];\
}ndarray(NDIMS, type_t);
