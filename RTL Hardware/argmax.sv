module argmax (
    input  logic clk, rst_n, enable,
    input  logic [319:0] pe_flat,          // 10 x signed 32-bit, result i = pe_flat[32*i +: 32]
    output logic [3:0] predicted_digit
);
    logic signed [31:0] max_val, cur;
    logic [3:0] max_idx;
    integer i;

    always_comb begin
        max_val = pe_flat[31:0];
        max_idx = 4'd0;
        cur     = 32'sd0;
        for (i = 1; i < 10; i = i + 1) begin
            cur = pe_flat[32*i +: 32];
            if (cur > max_val) begin
                max_val = cur;
                max_idx = i[3:0];
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)      predicted_digit <= 4'd0;
        else if (enable) predicted_digit <= max_idx;
    end
endmodule