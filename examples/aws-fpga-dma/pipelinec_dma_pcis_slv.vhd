library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
use work.c_structs_pkg.all;

entity pipelinec_dma_pcis_slv is
port
(
	clk         : in std_logic;
  rst         : in std_logic;
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
	axi_wstrb   : in unsigned(63 downto 0);
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

signal rst_unsigned : unsigned(0 downto 0);
signal i : aws_fpga_dma_inputs_t;
signal o : aws_fpga_dma_outputs_t;

begin

rst_unsigned <= (others => rst);

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
	-- 	Write
	--		Request
	i.pcis.write.req.awlen   <= axi_awlen  ;
	i.pcis.write.req.awid    <= axi_awid   ;
	i.pcis.write.req.awsize  <= axi_awsize ;
	i.pcis.write.req.awaddr  <= axi_awaddr ;
	i.pcis.write.req.awvalid <= axi_awvalid;
	i.pcis.write.req.wlast   <= axi_wlast  ;
	i.pcis.write.req.wvalid  <= axi_wvalid ;
	for byte_i in 0 to 63 loop
		i.pcis.write.req.wdata(byte_i)   <= axi_wdata(((byte_i+1)*8)-1 downto (byte_i*8));
		i.pcis.write.req.wstrb(byte_i)   <= (others => axi_wstrb(byte_i));
	end loop;
	--		Ready
	i.pcis.write.bready  <= axi_bready ;
	--	Read
	--		Request
	i.pcis.read.req.arsize  <= axi_arsize ;
	i.pcis.read.req.araddr  <= axi_araddr ;
	i.pcis.read.req.arid    <= axi_arid   ;
	i.pcis.read.req.arvalid <= axi_arvalid;
	i.pcis.read.req.arlen   <= axi_arlen  ;
	--		Ready
	i.pcis.read.rready  <= axi_rready ;
		
	
	-- Outputs
	-- 	Write
	--		Response
	axi_bid           <= o.pcis.write.resp.bid     ;
	axi_bresp         <= o.pcis.write.resp.bresp   ;
	axi_bvalid        <= o.pcis.write.resp.bvalid  ;
	--		Ready
	axi_awready       <= o.pcis.write.ready.awready ;
	axi_wready        <= o.pcis.write.ready.wready  ;
	--	Read
	--		Response
  axi_rlast         <= o.pcis.read.resp.rlast   ;
  axi_rresp         <= o.pcis.read.resp.rresp   ;
  axi_rvalid        <= o.pcis.read.resp.rvalid  ;
  axi_rid           <= o.pcis.read.resp.rid     ;
  for byte_i in 0 to 63 loop
		axi_rdata(((byte_i+1)*8)-1 downto (byte_i*8)) <= o.pcis.read.resp.rdata(byte_i);
	end loop;
	--		Ready
	axi_arready       <= o.pcis.read.arready ;
	
end process;
	
-- Instantiate PipelineC main entity
top_i : entity work.top port map
(
  clk_bram => clk,
  
  clk_fosix => clk,
  
  clk_fosix_aws_fpga_dma => clk,
  
  clk_main_wrapper => clk,
  main_wrapper_rst => rst_unsigned,
  
  clk_aws_fpga_dma => clk,
  aws_fpga_dma_rst => rst_unsigned,
  aws_fpga_dma_i => i,
  aws_fpga_dma_return_output => o
);

end arch;
