#include "intN_t.h"
#include "uintN_t.h"

// Euler method to iteratively solve 
// the generic N-th order differential equation
// of the form y^(N) = f(x, y, y', y'', ..., y^(N-1)):
#define N_ORDER 3
float f_nth_deriv(
  float x,
  float y_derivs[N_ORDER] // [1] = 1st deriv, etc
)
{
  // Specific to function
  // If nth derivative is original func -> f(x) = e^x ?
  return y_derivs[0]; 
}

// Iterate continuously
#pragma MAIN main
float main()
{
  // Set the step size and the number of iterations
  float step_size = 0.001;

  // Set the starting point and the initial values of the derivatives
  static float x = 0.0; // User selected
  static float y_derivs[N_ORDER] = {1.0, 1.0, 1.0}; // Function specific?
  float rv = y_derivs[0]; // dummy output of func value
  printf("x = %f, y = %f\n", x, rv);

  // Update the values of the derivatives starting at Nth order derive
  // Order N-1..0 are in array
  float y_derivs_next[N_ORDER];
  // Order Nth deriv value is based on user func
  float y_n_plus_1_deriv = f_nth_deriv(x, y_derivs);
  int32_t n;
  for (n = N_ORDER-1; n >= 0; n-=1)
  {
    y_derivs_next[n] = y_derivs[n] + (step_size*y_n_plus_1_deriv);
    y_n_plus_1_deriv = y_derivs[n];
  }
  y_derivs = y_derivs_next;
  // y_derivs[0] is the 0th derivation, the function value itself
  
  // Update the value of x
  x = x + step_size;

  return rv;
}
