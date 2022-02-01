// Common test driver

#include <iostream>
using namespace std;

int main(int argc, char *argv[]) {
    // Module top pointer
    Vtop* g_top = new Vtop;
    // Sim flags
    bool done = false;
    uint64_t test_num = 0;
    bool test_passed = true;
    uint64_t pipeline_latency_counter = 0;
    
    // Vars for this test
    DUT_VARS_DECL
    
    // Run the simulation
    while(!done)
    {
        // Get next test values
        DUT_SET_NEXT_INPUTS
        
        // Drive inputs
        DUT_SET_INPUTS(g_top)
        // And send through sim eval
        g_top->eval();

        // Wait as many clocks as pipeline latency specifies
        for(pipeline_latency_counter = 0; pipeline_latency_counter < test_bench_LATENCY; pipeline_latency_counter++)
        {
            DUT_RISING_EDGE(g_top)
            // Null out inputs to flush pipeline after first clock
            if(pipeline_latency_counter==0)
            {
                DUT_SET_NULL_INPUTS(g_top)
            }
        }        
        
        // Get result from sim + c code eval
        DUT_GET_OUTPUTS(g_top)
        
        // Do compare+log
        DUT_COMPARE_LOG(g_top)
        
        test_num++;
    }
    
    cout << test_num << " outputs checked." << endl;

    if(test_passed)
    {
      cout << "Test passed!" << endl;
    }
    else
    {
      cout << "Test failed!" << endl;
    }
    
    return (test_passed?0:1);
}
