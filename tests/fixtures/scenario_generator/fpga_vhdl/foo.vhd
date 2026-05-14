-- fixture for fpga_vhdl
-- Synthesisable VHDL entity exercising the discoverer's port parser:
--   * multiple ports of varying directions (in / out / inout)
--   * multi-name declarations on one line (data_in, data_out : inout ...)
--   * std_logic_vector subtypes with downto ranges
-- The discoverer emits one FPGA_TOPLEVEL_PORT EntryPoint per entity.

library ieee;
use ieee.std_logic_1164.all;

entity foo is
    port (
        clk      : in  std_logic;
        rst_n    : in  std_logic;
        data_in  : in  std_logic_vector(7 downto 0);
        data_out : out std_logic_vector(7 downto 0);
        bidir    : inout std_logic
    );
end foo;

architecture rtl of foo is
    signal reg : std_logic_vector(7 downto 0);
begin
    -- Trivial body — not parsed by the discoverer, present only so the
    -- entity is structurally valid.
    process (clk, rst_n)
    begin
        if rst_n = '0' then
            reg <= (others => '0');
        elsif rising_edge(clk) then
            reg <= data_in;
        end if;
    end process;

    data_out <= reg;
end rtl;
