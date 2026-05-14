// fixture for asic_design
// ASIC SystemVerilog top with a clock + reset + AXI-Lite-shaped inputs.
// The discoverer emits one FPGA_TOPLEVEL_PORT EntryPoint per `module`
// declaration. SDC constraints in constraints.sdc are also referenced
// in the EntryPoint metadata for timing-constraint scenarios.

module top (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] axi_addr,
    input  logic [31:0] axi_wdata,
    output logic [31:0] axi_rdata,
    output logic        axi_ack
);

    logic [31:0] regfile [0:7];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            axi_rdata <= 32'h0;
            axi_ack   <= 1'b0;
        end else begin
            axi_rdata <= regfile[axi_addr[4:2]];
            axi_ack   <= 1'b1;
        end
    end

endmodule
