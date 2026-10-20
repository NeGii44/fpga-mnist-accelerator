module pixel_bram (
    input  logic clk,
    input  logic we,
    input  logic signed [7:0] wdata,
    input  logic [9:0] raddr,
    output logic signed [7:0] rdata
);
    logic signed [7:0] ram [0:783];
    logic [9:0] waddr_reg = 0;

    always_ff @(posedge clk) begin
        if (we) begin
            ram[waddr_reg] <= wdata;
            if (waddr_reg < 783) waddr_reg <= waddr_reg + 1;
            else waddr_reg <= 0;
        end
        rdata <= ram[raddr];
    end
endmodule