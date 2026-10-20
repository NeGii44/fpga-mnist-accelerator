module pe (
    input  logic clk, rst_n, mac_enable, mac_clear,
    input  logic signed [7:0]  pixel_in,
    input  logic signed [7:0]  weight_in,
    output logic signed [31:0] acc_out
);
    logic signed [15:0] product;
    assign product = pixel_in * weight_in;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)          acc_out <= 32'sd0;
        else if (mac_clear)  acc_out <= 32'sd0;
        else if (mac_enable) acc_out <= acc_out + product;
    end
endmodule