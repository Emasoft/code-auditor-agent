-- fixture for fpga_vhdl (testbench)
-- Pairs with foo.vhd. The discoverer tags entities whose name ends in
-- `_tb` with metadata['role'] == 'testbench' so the walker can route
-- them to simulation-time scenarios instead of synthesis-time ones.

library ieee;
use ieee.std_logic_1164.all;

entity foo_tb is
end foo_tb;

architecture testbench of foo_tb is
    signal clk      : std_logic := '0';
    signal rst_n    : std_logic := '0';
    signal data_in  : std_logic_vector(7 downto 0) := (others => '0');
    signal data_out : std_logic_vector(7 downto 0);
    signal bidir    : std_logic;
begin
    -- Instantiate the unit under test.
    dut : entity work.foo
        port map (
            clk      => clk,
            rst_n    => rst_n,
            data_in  => data_in,
            data_out => data_out,
            bidir    => bidir
        );

    -- Trivial clock driver. Not parsed by the discoverer.
    clk <= not clk after 5 ns;
end testbench;
