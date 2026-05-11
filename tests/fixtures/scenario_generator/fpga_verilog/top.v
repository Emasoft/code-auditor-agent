// Top-level Verilog module for the fpga_verilog discoverer fixture.
// This module is the FPGA top — its ports are pinned in constraints/top.xdc
// and therefore must be reported as FPGA_TOPLEVEL_PORT entry points.
//
// Mixes ANSI-style port declarations with a wide vector to exercise the
// port-width parsing branch of the discoverer.

module top (
    input         clk,
    input         rst_n,
    input  [7:0]  data_in,
    output reg [7:0] led,
    output        uart_tx,
    input         uart_rx
);

    // Trivial body — not exercised by the discoverer, present only so the
    // module is structurally valid and tooling that opens the file is happy.
    reg [7:0] data_q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_q <= 8'h00;
            led    <= 8'h00;
        end else begin
            data_q <= data_in;
            led    <= data_q;
        end
    end

    // Instantiate the submodule to keep the design self-contained.
    uart_engine u_uart (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_data (data_q),
        .tx_pin  (uart_tx),
        .rx_pin  (uart_rx)
    );

endmodule
