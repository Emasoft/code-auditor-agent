# Pin constraints for the top-level module. The discoverer uses this file
# to disambiguate which module is the FPGA top: any module whose port list
# includes the names referenced by `get_ports {<name>}` is treated as top.

set_property -dict { PACKAGE_PIN K17  IOSTANDARD LVCMOS33 } [get_ports {clk}]
set_property -dict { PACKAGE_PIN K18  IOSTANDARD LVCMOS33 } [get_ports {rst_n}]

set_property -dict { PACKAGE_PIN L17  IOSTANDARD LVCMOS33 } [get_ports {data_in[0]}]
set_property -dict { PACKAGE_PIN L18  IOSTANDARD LVCMOS33 } [get_ports {data_in[1]}]
set_property -dict { PACKAGE_PIN M17  IOSTANDARD LVCMOS33 } [get_ports {data_in[2]}]
set_property -dict { PACKAGE_PIN M18  IOSTANDARD LVCMOS33 } [get_ports {data_in[3]}]
set_property -dict { PACKAGE_PIN N17  IOSTANDARD LVCMOS33 } [get_ports {data_in[4]}]
set_property -dict { PACKAGE_PIN N18  IOSTANDARD LVCMOS33 } [get_ports {data_in[5]}]
set_property -dict { PACKAGE_PIN P17  IOSTANDARD LVCMOS33 } [get_ports {data_in[6]}]
set_property -dict { PACKAGE_PIN P18  IOSTANDARD LVCMOS33 } [get_ports {data_in[7]}]

set_property -dict { PACKAGE_PIN R17  IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
set_property -dict { PACKAGE_PIN R18  IOSTANDARD LVCMOS33 } [get_ports {led[1]}]
set_property -dict { PACKAGE_PIN T17  IOSTANDARD LVCMOS33 } [get_ports {led[2]}]
set_property -dict { PACKAGE_PIN T18  IOSTANDARD LVCMOS33 } [get_ports {led[3]}]
set_property -dict { PACKAGE_PIN U17  IOSTANDARD LVCMOS33 } [get_ports {led[4]}]
set_property -dict { PACKAGE_PIN U18  IOSTANDARD LVCMOS33 } [get_ports {led[5]}]
set_property -dict { PACKAGE_PIN V17  IOSTANDARD LVCMOS33 } [get_ports {led[6]}]
set_property -dict { PACKAGE_PIN V18  IOSTANDARD LVCMOS33 } [get_ports {led[7]}]

set_property -dict { PACKAGE_PIN W17  IOSTANDARD LVCMOS33 } [get_ports {uart_tx}]
set_property -dict { PACKAGE_PIN W18  IOSTANDARD LVCMOS33 } [get_ports {uart_rx}]
