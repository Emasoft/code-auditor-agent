# fixture for asic_design
# Synopsys Design Constraints file. The presence of *.sdc + the
# absence of *.xdc / *.lpf is what distinguishes asic_design from
# fpga_verilog in the type-detection registry. The discoverer reads
# create_clock declarations to populate metadata['sdc_clocks'] on
# every emitted EntryPoint.

create_clock -name clk -period 5.0 [get_ports clk]

set_input_delay  -clock clk 1.0 [get_ports {rst_n axi_addr axi_wdata}]
set_output_delay -clock clk 1.0 [get_ports {axi_rdata axi_ack}]

set_max_delay 5.0 -from [get_ports axi_addr] -to [get_ports axi_rdata]
