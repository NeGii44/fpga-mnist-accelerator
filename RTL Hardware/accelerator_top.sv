module accelerator_top (
    input  logic clk, rst_n,
    input  logic spi_sck, spi_cs, spi_mosi,
    output logic prediction_ready,
    output logic [3:0] predicted_digit
);
    localparam int SHIFT1 = 11;
    localparam int SHIFT2 = 8;

    logic spi_rx_valid, prediction_start;
    logic [7:0] spi_rx_data;
    logic [1:0] layer_idx;
    logic [2:0] pass_idx;
    logic [9:0] step_idx;
    logic mac_enable, mac_clear, buffer_we, argmax_enable;

    logic signed [7:0] pixel_bram_out, buf_a_out, buf_b_out, current_input;
    wire  [319:0] array_flat;                 // 10 x signed 32-bit PE results

    controller u_controller (.clk(clk), .rst_n(rst_n), .prediction_start(prediction_start),
        .layer_idx(layer_idx), .pass_idx(pass_idx), .step_idx(step_idx),
        .mac_enable(mac_enable), .mac_clear(mac_clear), .buffer_we(buffer_we),
        .argmax_enable(argmax_enable), .prediction_ready(prediction_ready));

    spi_slave u_spi (.clk(clk), .rst_n(rst_n), .spi_sck(spi_sck), .spi_cs(spi_cs),
        .spi_mosi(spi_mosi), .rx_valid(spi_rx_valid), .rx_data(spi_rx_data),
        .prediction_start(prediction_start));

    pixel_bram u_pixel_ram (.clk(clk), .we(spi_rx_valid), .wdata(spi_rx_data),
        .raddr(step_idx), .rdata(pixel_bram_out));

    // ---- weights: 10 per read, one per PE ----
    logic [12:0] addr_l1, addr_l2, addr_l3;
    assign addr_l1 = pass_idx * 13'd784 + step_idx;
    assign addr_l2 = pass_idx * 13'd60  + step_idx;
    assign addr_l3 = step_idx;

    wire  [79:0] w_l1, w_l2, w_l3;
    logic [79:0] weight_bus;

    weight_rom_wide #(.HEX_FILE("src/fc1_wide.hex"), .DEPTH(4704)) u_rom_l1 (.clk(clk), .addr(addr_l1), .data_out(w_l1));
    weight_rom_wide #(.HEX_FILE("src/fc2_wide.hex"), .DEPTH(180))  u_rom_l2 (.clk(clk), .addr(addr_l2), .data_out(w_l2));
    weight_rom_wide #(.HEX_FILE("src/fc3_wide.hex"), .DEPTH(30))   u_rom_l3 (.clk(clk), .addr(addr_l3), .data_out(w_l3));

    always_comb begin
        case (layer_idx)
            2'd0:    weight_bus = w_l1;
            2'd1:    weight_bus = w_l2;
            2'd2:    weight_bus = w_l3;
            default: weight_bus = 80'd0;
        endcase
    end

    // ---- ReLU + requantize each of the 10 results ----
    wire [79:0] act_flat;                     // 10 x signed 8-bit
    genvar g;
    generate
        for (g = 0; g < 10; g++) begin : quant
            wire signed [31:0] acc_g = array_flat[32*g +: 32];
            wire signed [31:0] sh_g  = (layer_idx == 2'd0) ? (acc_g >>> SHIFT1) : (acc_g >>> SHIFT2);
            assign act_flat[8*g +: 8] = (acc_g < 0)  ? 8'd0   :
                                        (sh_g > 127) ? 8'd127 : sh_g[7:0];
        end
    endgenerate

    // ---- hidden-layer buffers (registered read = same 1-cycle latency as the ROMs) ----
    logic signed [7:0] buf_a [0:59];
    logic signed [7:0] buf_b [0:29];
    logic we_a, we_b;
    assign we_a = buffer_we && (layer_idx == 2'd0);
    assign we_b = buffer_we && (layer_idx == 2'd1);

    always_ff @(posedge clk) begin
        if (we_a) for (int i = 0; i < 10; i++) buf_a[pass_idx*10 + i] <= act_flat[8*i +: 8];
        if (we_b) for (int i = 0; i < 10; i++) buf_b[pass_idx*10 + i] <= act_flat[8*i +: 8];
        buf_a_out <= buf_a[step_idx[5:0]];
        buf_b_out <= buf_b[step_idx[4:0]];
    end

    always_comb begin
        case (layer_idx)
            2'd0:    current_input = pixel_bram_out;
            2'd1:    current_input = buf_a_out;
            2'd2:    current_input = buf_b_out;
            default: current_input = 8'sd0;
        endcase
    end

    systolic_array u_array (.clk(clk), .rst_n(rst_n), .mac_enable(mac_enable), .mac_clear(mac_clear),
        .pixel_in(current_input), .weight_in(weight_bus), .acc_flat(array_flat));

    argmax u_argmax (.clk(clk), .rst_n(rst_n), .enable(argmax_enable),
        .pe_flat(array_flat), .predicted_digit(predicted_digit));
endmodule