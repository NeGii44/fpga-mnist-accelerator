module spi_slave (
    input  logic clk,
    input  logic rst_n,
    input  logic spi_sck,
    input  logic spi_cs,
    input  logic spi_mosi,
    output logic rx_valid,
    output logic [7:0] rx_data,
    output logic prediction_start
);

    // 1. Clock Synchronizer
    logic [2:0] sck_sync;
    always_ff @(posedge clk) sck_sync <= {sck_sync[1:0], spi_sck};
    wire sck_rise = (sck_sync[2:1] == 2'b01);

    // 2. Chip Select (CS) Synchronizer to filter wire noise
    logic [1:0] cs_sync;
    always_ff @(posedge clk) cs_sync <= {cs_sync[0], spi_cs};
    wire cs_active = ~cs_sync[1]; 

    logic [7:0] shift_reg;
    logic [2:0] bit_cnt;
    logic [9:0] byte_cnt;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bit_cnt <= 0;
            byte_cnt <= 0;
            rx_valid <= 0;
            prediction_start <= 0;
        end else if (cs_active) begin 
            rx_valid <= 0;
            prediction_start <= 0; // RESTORED: Clears instantly to create a clean 1-cycle pulse
            
            if (sck_rise) begin
                shift_reg <= {shift_reg[6:0], spi_mosi};
                bit_cnt <= bit_cnt + 1;
                if (bit_cnt == 3'd7) begin
                    rx_valid <= 1;
                    rx_data <= {shift_reg[6:0], spi_mosi};
                    byte_cnt <= byte_cnt + 1;
                    
                    if (byte_cnt == 10'd783) begin
                        prediction_start <= 1; // Fires for exactly one 27MHz clock cycle
                        byte_cnt <= 0;
                    end
                end
            end
        end else begin
            // ESP32 is idle (CS is HIGH). Clear counters safely.
            rx_valid <= 0;
            prediction_start <= 0; 
            bit_cnt <= 0;  
            byte_cnt <= 0; 
        end
    end
endmodule