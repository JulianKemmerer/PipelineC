
#pragma PART "xc7a100tcsg324-1"
#include "intN_t.h"
#include "uintN_t.h"
#include "examples/cordic.h"

/*```py
def unified(p0, p1, fi, T):
    #Input
    #P0 = [x, y]
    #P1 = [y, y]
    #FI = x
    #T = [x, y]
    #Returns
    #h = [
    #        [a, b, c],
    #        [d, e, f],
    #        [g, h, i]
    #    ]
    #b = [a, b, c]
    def u(p0, p1, fi, T):
        sin_fi = np.sin(fi)
        cos_fi = np.cos(fi)
        R = np.array((
            [cos_fi, -sin_fi],
            [sin_fi, cos_fi]
        ))
        sin_fi_p10 = sin_fi * p1[0]
        cos_fi_p11 = cos_fi * p1[1]
        cos_fi_p10 = cos_fi * p1[0]
        sin_fi_p11 = sin_fi * p1[1]
        n_sin_fi_p10_n_fi_p11 = -sin_fi_p10 - cos_fi_p11
        cos_fi_p10_n_sin_fi_p11 = cos_fi_p10 - sin_fi_p11

        p1_rotated = np.array([R[0,0]*p1[0]+R[0,1]*p1[1], R[1,0]*p1[0]+R[1,1]*p1[1]])
        e = np.array([p1_rotated[0]+T[0]-p0[0], p1_rotated[1]+T[1]-p0[1]])

        h = np.array([
            [1, 0, n_sin_fi_p10_n_fi_p11],
            [0, 1, cos_fi_p10_n_sin_fi_p11],
            [n_sin_fi_p10_n_fi_p11, cos_fi_p10_n_sin_fi_p11, n_sin_fi_p10_n_fi_p11**2 + cos_fi_p10_n_sin_fi_p11**2]
        ])
        b = np.array([e[0], e[1], n_sin_fi_p10_n_fi_p11*e[0]+cos_fi_p10_n_sin_fi_p11*e[1]])
        return h, b
    h, b = u(p0, p1, fi, T)
    return h, b
```*/



/*
float sin(float x){
  return x + 1.0;//TODO
}

float cos(float x){
  return x + 1.0;//TODO
}*/
/*    #Input
    #P0 = [x, y]
    #P1 = [y, y]
    #FI = x
    #T = [x, y]
    #Returns
    #h = [
    #        [a, b, c],
    #        [d, e, f],
    #        [g, h, i]
    #    ]
    #b = [a, b, c]*/
#pragma MAIN unified
typedef struct hb_t{
  float h[3][3];
  float b[3];
}hb_t;
hb_t unified(float p0[2], float p1[2], float fi, float T[2]){
  //float sin_fi = sin(fi);
  //float cos_fi = cos(fi);
  cordic_float_t cordic = cordic_float_fixed32_n32(fi);
  float sin_fi = cordic.s;
  float cos_fi = cordic.c;
  float R[2][2];
  R[0][0] = cos_fi;
  R[0][1] = -sin_fi;
  R[1][0] = sin_fi;
  R[1][1] = cos_fi;
  float sin_fi_p10 = sin_fi * p1[0];
  float cos_fi_p11 = cos_fi * p1[1];
  float cos_fi_p10 = cos_fi * p1[0];
  float sin_fi_p11 = sin_fi * p1[1];
  float n_sin_fi_p10_n_fi_p11 = -sin_fi_p10 - cos_fi_p11;
  float cos_fi_p10_n_sin_fi_p11 = cos_fi_p10 - sin_fi_p11;
  float p1_rotated[2];
  p1_rotated[0] = R[0][0]*p1[0]+R[0][1]*p1[1];
  p1_rotated[1] = R[1][0]*p1[0]+R[1][1]*p1[1];
  float e[2];
  e[0] = p1_rotated[0]+T[0]-p0[0];
  e[1] = p1_rotated[1]+T[1]-p0[1];
  hb_t rv;
  rv.h[0][0] = 1.0;
  rv.h[0][1] = 0.0;
  rv.h[0][2] = n_sin_fi_p10_n_fi_p11;
  rv.h[1][0] = 0.0;
  rv.h[1][1] = 1.0;
  rv.h[1][2] = cos_fi_p10_n_sin_fi_p11;
  rv.h[2][0] = n_sin_fi_p10_n_fi_p11;
  rv.h[2][1] = cos_fi_p10_n_sin_fi_p11;
  rv.h[2][2] = (n_sin_fi_p10_n_fi_p11*n_sin_fi_p10_n_fi_p11) + (cos_fi_p10_n_sin_fi_p11*cos_fi_p10_n_sin_fi_p11);
  rv.b[0] = e[0];
  rv.b[1] = e[1];
  rv.b[2] = n_sin_fi_p10_n_fi_p11*e[0]+cos_fi_p10_n_sin_fi_p11*e[1];
  return rv;
}