library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
use work.c_structs_pkg.all;

entity pipelinec_dma_pcis_slv is
port
(
	clk         : in std_logic;
	-- Inputs
	axi_arsize  : in unsigned(2 downto 0);
	axi_awsize  : in unsigned(2 downto 0);
	axi_araddr  : in unsigned(63 downto 0);
	axi_awaddr  : in unsigned(63 downto 0);
	axi_wlast   : in unsigned(0 downto 0);
	axi_rready  : in unsigned(0 downto 0);
	axi_awvalid : in unsigned(0 downto 0);
	axi_arid    : in unsigned(5 downto 0);
	axi_wvalid  : in unsigned(0 downto 0);
	axi_wdata   : in unsigned(511 downto 0);
	axi_bready  : in unsigned(0 downto 0);
	axi_arvalid : in unsigned(0 downto 0);
	axi_arlen   : in unsigned(7 downto 0);
	axi_awlen   : in unsigned(7 downto 0);
	axi_wstrb   : in unsigned(0 to 63);
	axi_awid    : in unsigned(5 downto 0);
	-- Outputs
	axi_arready : out unsigned(0 downto 0);
	axi_bid     : out unsigned(5 downto 0);
	axi_rlast   : out unsigned(0 downto 0);
	axi_rresp   : out unsigned(1 downto 0);
	axi_rvalid  : out unsigned(0 downto 0);
	axi_wready  : out unsigned(0 downto 0);
	axi_bvalid  : out unsigned(0 downto 0);
	axi_rdata   : out unsigned(511 downto 0);
	axi_rid     : out unsigned(5 downto 0);
	axi_bresp   : out unsigned(1 downto 0);
	axi_awready : out unsigned(0 downto 0)
);
end pipelinec_dma_pcis_slv;

architecture arch of pipelinec_dma_pcis_slv is

signal i : aws_fpga_dma_inputs_t;
signal o : aws_fpga_dma_outputs_t;

begin

-- Convert SLV to record/array
process(
	-- Module inputs
	axi_arsize ,
	axi_awsize ,
	axi_araddr ,
	axi_awaddr ,
	axi_wlast  ,
	axi_rready ,
	axi_awvalid,
	axi_arid   ,
	axi_wvalid ,
	axi_bready ,
	axi_arvalid,
	axi_arlen  ,
	axi_awlen  ,
	axi_awid   ,
	axi_wdata  ,
	axi_wstrb  ,
	-- Entity output
	o
) begin
	-- Inputs 
	i.pcis.arsize  <= axi_arsize ;
	i.pcis.awsize  <= axi_awsize ;
	i.pcis.araddr  <= axi_araddr ;
	i.pcis.awaddr  <= axi_awaddr ;
	i.pcis.wlast   <= axi_wlast  ;
	i.pcis.rready  <= axi_rready ;
	i.pcis.awvalid <= axi_awvalid;
	i.pcis.arid    <= axi_arid   ;
	i.pcis.wvalid  <= axi_wvalid ;
	i.pcis.bready  <= axi_bready ;
	i.pcis.arvalid <= axi_arvalid;
	i.pcis.arlen   <= axi_arlen  ;
	i.pcis.awlen   <= axi_awlen  ;
	i.pcis.awid    <= axi_awid   ;
	-- Input arrays
	for byte_i in 0 to 63 loop
		i.pcis.wdata(byte_i)   <= axi_wdata(((byte_i+1)*8)-1 downto (byte_i*8));
		i.pcis.wstrb(byte_i)   <= (others => axi_wstrb(byte_i));
	end loop;
	
	-- Outputs
  axi_arready       <= o.pcis.arready ;
  axi_bid           <= o.pcis.bid     ;
  axi_rlast         <= o.pcis.rlast   ;
  axi_rresp         <= o.pcis.rresp   ;
  axi_rvalid        <= o.pcis.rvalid  ;
  axi_wready        <= o.pcis.wready  ;
  axi_bvalid        <= o.pcis.bvalid  ;
  axi_rid           <= o.pcis.rid     ;
  axi_bresp         <= o.pcis.bresp   ;
  axi_awready       <= o.pcis.awready ;
  -- Output arrays
  for byte_i in 0 to 63 loop
		axi_rdata(((byte_i+1)*8)-1 downto (byte_i*8)) <= o.pcis.rdata(byte_i);
	end loop; 
end process;
	
-- Instantiate PipelineC main entity
main : entity work.main_3CLK_d51e port map
(	
	clk,
	i,
	o
);

end arch;
