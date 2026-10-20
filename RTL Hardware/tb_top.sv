`timescale 1ns / 1ps
module tb_top();
    parameter int EXPECTED = 7;   // digit of src/sample_image.hex

    logic clk, rst_n, spi_sck, spi_cs, spi_mosi;
    logic prediction_ready;
    logic [3:0] predicted_digit;
    logic [7:0] img [0:783];

    accelerator_top uut (.clk(clk), .rst_n(rst_n), .spi_sck(spi_sck), .spi_cs(spi_cs),
        .spi_mosi(spi_mosi), .prediction_ready(prediction_ready), .predicted_digit(predicted_digit));

    // 27 MHz
    initial clk = 0;
    always #18.5 clk = ~clk;

    task send_spi_byte(input [7:0] data);
        integer i;
        begin
            for (i = 7; i >= 0; i = i - 1) begin
                spi_mosi = data[i]; #500; spi_sck = 1; #500; spi_sck = 0;
            end
        end
    endtask

    // watchdog: never hang forever
    initial begin
        #50_000_000;
        $display("TIMEOUT: prediction_ready never went high");
        $finish;
    end

    initial begin
        $readmemh("src/sample_image.hex", img);
        rst_n = 0; spi_sck = 0; spi_cs = 1; spi_mosi = 0;
        #100 rst_n = 1; #100;

        spi_cs = 0; #1000;
        for (int j = 0; j < 784; j++) send_spi_byte(img[j]);
        #1000; spi_cs = 1;

        wait (prediction_ready == 1'b1);
        #1000;
        $display("predicted_digit = %0d, expected = %0d", predicted_digit, EXPECTED);
        if (predicted_digit == EXPECTED) $display("DIGIT PASS"); else $display("DIGIT FAIL");

        #50000;
        if (prediction_ready) $display("READY-HOLD PASS"); else $display("READY-HOLD FAIL");
        $finish;
    end
endmodule