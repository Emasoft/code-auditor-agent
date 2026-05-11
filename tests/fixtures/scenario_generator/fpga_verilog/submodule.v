// Non-top submodule. Its ports MUST NOT appear in the discoverer output —
// only the top module (the one whose ports are pinned by the XDC) is
// expected to emit FPGA_TOPLEVEL_PORT entries.

module uart_engine (
    input        clk,
    input        rst_n,
    input  [7:0] tx_data,
    output       tx_pin,
    input        rx_pin
);

    // Body intentionally trivial.
    assign tx_pin = (rst_n) ? tx_data[0] : 1'b1;

endmodule
