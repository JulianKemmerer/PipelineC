# EDIF parsing example WIP
# See https://byuccl.github.io/spydrnet/docs/stable/auto_examples/basic/display_info.html
import spydrnet as sdn
from spydrnet.util.selection import Selection

#print the hierarchy of a netlist
def hierarchy(current_instance,indentation="",level=0):
    print(indentation,level,'',current_instance.name," --instance of",current_instance.reference.name,"--")
    for child in current_instance.reference.children:
        hierarchy(child,indentation+"     ",level+1)

#print a list of all libraries and definitions in a netlist
def libraries_definitions(my_netlist):
    for library in my_netlist.libraries:
        definitions = list(definition.name for definition in library.definitions)
        print("DEFINITIONS IN '",library.name,"':",definitions)

#prints each instance and it's connections (what inputs to it and what it outputs to)
def print_connections(current_netlist):
    print("CONNECTIONS:")
    for instance in current_netlist.get_instances():
        print("Instance name:",instance.name)
        print("OUTPUTS")
        for out_going_pin in instance.get_pins(selection = Selection.OUTSIDE,filter=lambda x: x.inner_pin.port.direction is sdn.OUT):
            if out_going_pin.wire:
                next_instances = list(str(pin2.inner_pin.port.name + ' of ' + pin2.instance.name) for pin2 in out_going_pin.wire.get_pins(selection = Selection.OUTSIDE, filter = lambda x: x is not out_going_pin))
                print('\t','Port',out_going_pin.inner_pin.port.name,'---->',next_instances)
        print("INPUTS")
        for in_coming_pin in instance.get_pins(selection = Selection.OUTSIDE,filter=lambda x: x.inner_pin.port.direction is sdn.IN):
            if in_coming_pin.wire:
                previous_instances = list(pin2 for pin2 in in_coming_pin.wire.get_pins(selection = Selection.OUTSIDE, filter = lambda x: x is not in_coming_pin))
                checked_previous_instances = list(str(x.inner_pin.port.name + ' of ' + x.instance.name) for x in previous_instances if (x.inner_pin.port.direction is sdn.OUT or (x.inner_pin.port.direction is sdn.IN and not x.instance.is_leaf()))is True)
                print('\t',checked_previous_instances,'---->','Port',in_coming_pin.inner_pin.port.name)

#print the number of times each primitive is instanced
def instance_count(current_netlist):
    print("Number of times each primitive is instanced:")
    primitives_library = next(current_netlist.get_libraries("hdi_primitives"),None)
    if primitives_library is None:
        return
    for primitive in primitives_library.get_definitions():
        count = 0
        for instance in current_netlist.get_instances():
            if primitive.name == instance.reference.name:
                count += 1
        print('\t',primitive.name,": ",count)


# PipelineC netlist like object to be populated
class Logic:
    def __init__(self):
        # Function/module name
        self.func_name = None 
        # For EDIF import all wires will be single bits
        # Top level list of inputs ["a","b"]
        self.inputs = set()  
        # top level list of outputs ["return_output"]
        self.outputs = set()  
        # Submodule instances/subroutine func calls
        # dict[instance_name] -> logic.func_name
        # ex. some_instance -> function/module name
        self.submodule_instances = {}  
        # Graph structure
        # Directionality, what drives what, is driven by what
        self.wire_drives = {}  # wire_name -> set([driven,wire,names])
        self.wire_driven_by = {}  # wire_name -> driving_wire
        # NEW FOR LUTS, dont support parameterized modules otherwise
        self.lut_inst_to_init = {} # dict[instance_name] => INIT string
        

def populate_logic(current_netlist, logic):
    logic.func_name = current_netlist.top_instance.name
    for instance in current_netlist.get_instances():
        # Process each submodule primitive instance
        instance_name = instance.name
        primitive_name = instance.reference.name
        logic.submodule_instances[instance_name] = primitive_name
        if "LUT" in primitive_name:
            edif_properties = instance['EDIF.properties']
            for edif_property in edif_properties:
                if edif_property["identifier"]=="INIT":
                    logic.lut_inst_to_init[instance_name] = edif_property["value"]
        
        # Process instance outputs
        for out_going_pin in instance.get_pins(selection=Selection.OUTSIDE, filter=lambda x: x.inner_pin.port.direction is sdn.OUT):
            if out_going_pin.wire:
                output_port_name = out_going_pin.inner_pin.port.name + "[" + str(out_going_pin.index()) + "]"
                if instance_name==logic.func_name:
                    logic.outputs.add(output_port_name)
                output_wire_name = instance_name + "/" + output_port_name
                for pin2 in out_going_pin.wire.get_pins(selection=Selection.OUTSIDE, filter=lambda x: x is not out_going_pin):
                    driven_port_name = pin2.inner_pin.port.name + "[" + str(pin2.index()) + "]"
                    if pin2.instance.name==logic.func_name:
                        logic.outputs.add(driven_port_name)
                    driven_wire = pin2.instance.name + "/" + driven_port_name
                    logic.wire_drives.setdefault(output_wire_name, set()).add(driven_wire)
                    if driven_wire in logic.wire_driven_by and logic.wire_driven_by[driven_wire]!=output_wire_name:
                        print("Output multi driver overwriting", driven_wire, "driven by", logic.wire_driven_by[driven_wire])
                        print(" with ", driven_wire, "driven by", output_wire_name)
                    logic.wire_driven_by[driven_wire] = output_wire_name

        # Process instance inputs
        for in_coming_pin in instance.get_pins(selection=Selection.OUTSIDE, filter=lambda x: x.inner_pin.port.direction is sdn.IN):
            if in_coming_pin.wire:
                input_port_name = in_coming_pin.inner_pin.port.name + "[" + str(in_coming_pin.index()) + "]"
                if instance_name==logic.func_name:
                    logic.inputs.add(input_port_name)
                previous_instances = [
                    pin2 for pin2 in in_coming_pin.wire.get_pins(selection=Selection.OUTSIDE, filter=lambda x: x is not in_coming_pin)
                ]
                input_wire_name = instance_name + "/" + input_port_name
                for previous_instance in previous_instances:
                    if (
                            previous_instance.inner_pin.port.direction is sdn.OUT or (previous_instance.inner_pin.port.direction is sdn.IN and not previous_instance.instance.is_leaf())
                    ) is True:
                        previous_instance_name = previous_instance.instance.name
                        driver_port_name = previous_instance.inner_pin.port.name + "[" + str(previous_instance.index()) + "]"
                        driver_wire = previous_instance_name + "/" + driver_port_name
                        if previous_instance_name==logic.func_name:
                            logic.inputs.add(driver_port_name)
                        logic.wire_drives.setdefault(driver_wire, set()).add(input_wire_name)
                        if input_wire_name in logic.wire_driven_by and logic.wire_driven_by[input_wire_name]!=driver_wire:
                            print("Input multi driver overwriting", input_wire_name, "driven by", logic.wire_driven_by[input_wire_name])
                            print(" with ", input_wire_name, "driven by", driver_wire)
                        logic.wire_driven_by[input_wire_name] = driver_wire


netlist = sdn.parse('/home/julian/pipelinec_output/top/top_0ac6.edf')

#print("HIERARCHY:")
#hierarchy(netlist.top_instance)
#libraries_definitions(netlist)
#print_connections(netlist)
#instance_count(netlist)

logic = Logic()
populate_logic(netlist, logic)

print("logic.func_name",logic.func_name)
print("logic.inputs",logic.inputs)
print("logic.outputs",logic.outputs)
for submodule_inst, func_name in logic.submodule_instances.items():
    #if func_name not in ["VCC","GND"]:
    print("submodule_inst, func_name ",submodule_inst, func_name)
    if submodule_inst in logic.lut_inst_to_init:
        print(" LUT INIT =", logic.lut_inst_to_init[submodule_inst])
for wire, drives in logic.wire_drives.items():
    #if not("VCC" in wire or "GND" in wire or "/CLK" in wire or "/clk" in wire):
    print(wire, "=>", drives)
