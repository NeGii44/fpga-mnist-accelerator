module systolic_array (
    input  logic clk, rst_n, mac_enable, mac_clear,
    input  logic signed [7:0] pixel_in,
    input  logic [79:0]       weight_in,   // PE i weight  = weight_in[8*i +: 8]
    output wire  [319:0]      acc_flat     // PE i result  = acc_flat[32*i +: 32] (signed)
);
    genvar i;
    generate
        for (i = 0; i < 10; i++) begin : pe_array
            pe u_pe (.clk(clk), .rst_n(rst_n), .mac_enable(mac_enable), .mac_clear(mac_clear),
                     .pixel_in(pixel_in), .weight_in(weight_in[8*i +: 8]),
                     .acc_out(acc_flat[32*i +: 32]));
        end
    endgenerate
endmodule