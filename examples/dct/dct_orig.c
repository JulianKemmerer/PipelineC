#include "dct.h"

// Function to find discrete cosine transform and return it 
dct_t dctTransform(dct_pixel_t matrix[DCT_M][DCT_N]) 
{ 
    dct_iter_t i;
    dct_iter_t j;
    dct_iter_t k;
    dct_iter_t l;
  
    // dct will store the discrete cosine transform 
    dct_t dct;
  
    float ci;
    float cj;
    float dct1;
    float sum; 
  
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
  
            // ci and cj depends on frequency as well as 
            // number of row and columns of specified matrix 
            if (i == 0) 
                ci = 1.0 / sqrt(DCT_M); 
            else
                ci = sqrt(2) / sqrt(DCT_M);
            if (j == 0) 
                cj = 1.0 / sqrt(DCT_N);
            else
                cj = sqrt(2) / sqrt(DCT_N); 
  
            // sum will temporarily store the sum of  
            // cosine signals 
            sum = 0.0; 
            for (k = 0; k < DCT_M; k=k+1) { 
                for (l = 0; l < DCT_N; l=l+1) { 
                    dct1 = (float)matrix[k][l] *  // Float * constant       
                             ( cos((float)((2 * k + 1) * i) * DCT_PI / (float)(2 * DCT_M)) *  
                               cos((float)((2 * l + 1) * j) * DCT_PI / (float)(2 * DCT_N))
                             );
                    sum = sum + dct1;
                }
            } 
            dct.matrix[i][j] = (ci * cj) * sum;
        } 
    }
    
    return dct; 
}
