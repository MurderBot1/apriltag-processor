// Chip-level top for the ECP5 (LFE5U-85F-8BG381C): 24 MHz oscillator -> PLL (85.714 MHz core, 24 MHz sensor clock, 200 MHz spare),
// OV9281 MIPI CSI-2 (2 lanes, LVDS + resistor network) -> dphy_rx -> cam_core, SPI slave to the MCU, I2C to the sensor.
// Pin locations: tools/pins.py (single source of truth for this file's LPF and the PCB netlist).
`timescale 1ns/1ps
module apriltag_cam_top (
    input  wire        clk_24m,
    input  wire        mipi_clk_p,        // LVDS pair, negative pin implied by the LPF
    input  wire [1:0]  mipi_d_p,
    output wire        sensor_xvclk,
    output reg         sensor_xshutdn,
    inout  wire        i2c_scl,
    inout  wire        i2c_sda,
    input  wire        spi_sck,
    input  wire        spi_cs_n,
    input  wire        spi_mosi,
    output wire        spi_miso,
    output wire        mcu_irq,
    input  wire        mcu_rst_n,
    output wire [3:0]  leds
);
    wire clk100, clk24, clk200, pll_locked;
    sys_pll pll(.clkin(clk_24m), .clkout0(clk100), .clkout1(clk24), .clkout2(clk200), .locked(pll_locked));
    assign sensor_xvclk = clk24;

    // reset: held until the PLL is locked and the MCU releases it, stretched over 16 clocks
    reg [4:0] rcnt = 0; reg rst = 1; reg [1:0] mr = 0;
    always @(posedge clk100) begin
        mr <= {mr[0], mcu_rst_n & pll_locked};
        if (!mr[1]) begin rcnt <= 0; rst <= 1; end
        else if (rcnt != 5'd31) begin rcnt <= rcnt + 1; end
        else rst <= 0;
    end
    // sensor out of shutdown ~2 ms after reset release (init ROM waits another 20 ms)
    reg [17:0] xs = 0;
    always @(posedge clk100) begin
        if (rst) begin xs <= 0; sensor_xshutdn <= 0; end
        else if (xs != 18'd200000) xs <= xs + 1; else sensor_xshutdn <= 1;
    end

    wire hs_valid; wire [7:0] lane0, lane1; wire pkt_end; wire [3:0] dphy_status;
    dphy_rx #(.USE_PRIM(1)) dphy(.clk_p(mipi_clk_p), .d_p(mipi_d_p), .core_clk(clk100), .core_rst(rst), .pkt_end(pkt_end),
        .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .status(dphy_status));

    wire scl_oe, sda_oe, miso, miso_oe, irq; wire [3:0] core_leds;
    cam_core #(.US_NUM(7), .US_DEN(600)) core(.clk(clk100), .rst(rst), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .sck(spi_sck),
        .cs_n(spi_cs_n), .mosi(spi_mosi), .miso(miso), .miso_oe(miso_oe), .scl_oe(scl_oe), .sda_oe(sda_oe),
        .sda_i(i2c_sda), .csi_pkt_end(pkt_end), .irq(irq), .leds(core_leds));
    assign i2c_scl = scl_oe ? 1'b0 : 1'bz;
    assign i2c_sda = sda_oe ? 1'b0 : 1'bz;
    assign spi_miso = miso_oe ? miso : 1'bz;
    assign mcu_irq = irq;
    assign leds = {core_leds[3], dphy_status[1] | dphy_status[2], core_leds[1], core_leds[0]};
endmodule
