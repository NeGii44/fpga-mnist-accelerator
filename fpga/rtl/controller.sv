module controller (
    input  logic clk, rst_n, prediction_start,
    output logic [1:0] layer_idx,
    output logic [2:0] pass_idx,
    output logic [9:0] step_idx,
    output logic mac_enable, mac_clear, buffer_we, argmax_enable, prediction_ready
);
    typedef enum logic [2:0] {IDLE, INIT_PASS, CALC_LOOP, WAIT_MAC, STORE, NEXT_PASS} state_t;
    state_t state;
    logic pred_ready_r;
    logic [9:0] in_channels;
    logic [2:0] max_pass;

    always_comb begin
        case (layer_idx)
            2'd0:    begin in_channels = 10'd784; max_pass = 3'd5; end
            2'd1:    begin in_channels = 10'd60;  max_pass = 3'd2; end
            2'd2:    begin in_channels = 10'd30;  max_pass = 3'd0; end
            default: begin in_channels = 10'd0;   max_pass = 3'd0; end
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; layer_idx <= 0; pass_idx <= 0; step_idx <= 0;
            mac_enable <= 0; pred_ready_r <= 0;
        end else begin
            mac_enable <= (state == CALC_LOOP);
            case (state)
                IDLE: begin
                    layer_idx <= 0; pass_idx <= 0; step_idx <= 0;
                    if (prediction_start) begin pred_ready_r <= 0; state <= INIT_PASS; end
                end
                INIT_PASS: begin step_idx <= 0; state <= CALC_LOOP; end
                CALC_LOOP: begin
                    if (step_idx < in_channels - 10'd1) step_idx <= step_idx + 10'd1;
                    else state <= WAIT_MAC;
                end
                WAIT_MAC: state <= STORE;
                STORE:    state <= NEXT_PASS;
                NEXT_PASS: begin
                    if (pass_idx < max_pass) begin
                        pass_idx <= pass_idx + 3'd1; state <= INIT_PASS;
                    end else if (layer_idx == 2'd2) begin
                        state <= IDLE; pred_ready_r <= 1;
                    end else begin
                        layer_idx <= layer_idx + 2'd1; pass_idx <= 0; state <= INIT_PASS;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end

    assign mac_clear        = (state == INIT_PASS);
    assign buffer_we        = (state == STORE) && (layer_idx != 2'd2);
    assign argmax_enable    = (state == STORE) && (layer_idx == 2'd2);
    assign prediction_ready = pred_ready_r;
endmodule