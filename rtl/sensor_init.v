// Plays the OV9281 init ROM (rtl/sensor_init.hex, {addr16, data8}, addr 0xFFFF = delay of `data` ms) over I2C
// after a power-up delay, then hands the I2C master to the host register bridge.
`timescale 1ns/1ps
module sensor_init #(
    parameter HEX = "rtl/sensor_init.hex",
    parameter N = 104,
    parameter DEV = 7'h60,
    parameter POWERUP_CLKS = 2_000_000,       // 20 ms @100 MHz
    parameter MS_CLKS = 100_000
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        i2c_done,
    input  wire        i2c_nack,
    input  wire        i2c_busy,
    output reg         i2c_go,
    output reg  [15:0] i2c_reg,
    output reg  [7:0]  i2c_data,
    output wire [6:0]  i2c_dev,
    output reg         init_done,
    output reg  [7:0]  nack_count
);
    reg [23:0] rom [0:255];
    initial $readmemh(HEX, rom);
    assign i2c_dev = DEV;
    localparam S_WAIT = 0, S_FETCH = 1, S_ISSUE = 2, S_RUN = 3, S_DELAY = 4, S_END = 5;
    reg [2:0]  st;
    reg [7:0]  idx;
    reg [23:0] w;
    reg [31:0] cnt;
    always @(posedge clk) begin
        i2c_go <= 0;
        if (rst) begin
            st <= S_WAIT; idx <= 0; cnt <= 0; init_done <= 0; nack_count <= 0;
        end else case (st)
            S_WAIT: begin cnt <= cnt + 1; if (cnt >= POWERUP_CLKS) st <= S_FETCH; end
            S_FETCH: begin
                if (idx == N) begin init_done <= 1; st <= S_END; end
                else begin w <= rom[idx]; st <= S_ISSUE; end
            end
            S_ISSUE: begin
                if (w[23:8] == 16'hFFFF) begin cnt <= w[7:0] * MS_CLKS; st <= S_DELAY; end
                else begin i2c_reg <= w[23:8]; i2c_data <= w[7:0]; i2c_go <= 1; st <= S_RUN; end
            end
            S_RUN: if (i2c_done) begin
                if (i2c_nack && nack_count != 8'hFF) nack_count <= nack_count + 1;
                idx <= idx + 1; st <= S_FETCH;
            end
            S_DELAY: begin
                if (cnt == 0) begin idx <= idx + 1; st <= S_FETCH; end else cnt <= cnt - 1;
            end
            default: ;
        endcase
    end
endmodule
