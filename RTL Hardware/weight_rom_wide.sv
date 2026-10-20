module weight_rom_wide #(
    parameter HEX_FILE = "",
    parameter DEPTH = 4704
)(
    input  logic clk,
    input  logic [12:0] addr,
    output logic [79:0] data_out     // neuron i weight = data_out[8*i +: 8]
);
    logic [79:0] mem [0:DEPTH-1];

    initial $readmemh(HEX_FILE, mem);
    always_ff @(posedge clk) data_out <= mem[addr];
endmodule