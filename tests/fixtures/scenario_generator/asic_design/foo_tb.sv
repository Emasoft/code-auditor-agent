// fixture for asic_design (testbench)
// Simulation-time wrapper. The discoverer tags modules ending in
// `_tb` with metadata['role'] == 'testbench' so the walker routes
// them to simulation scenarios rather than synthesis scenarios.

module foo_tb;

    logic        clk = 1'b0;
    logic        rst_n = 1'b0;
    logic [31:0] axi_addr = 32'h0;
    logic [31:0] axi_wdata = 32'h0;
    logic [31:0] axi_rdata;
    logic        axi_ack;

    // Unit under test.
    top dut (
        .clk(clk),
        .rst_n(rst_n),
        .axi_addr(axi_addr),
        .axi_wdata(axi_wdata),
        .axi_rdata(axi_rdata),
        .axi_ack(axi_ack)
    );

    // Trivial clock driver.
    always #5 clk = ~clk;

endmodule
