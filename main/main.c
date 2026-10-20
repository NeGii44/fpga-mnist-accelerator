#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_rom_sys.h"

static const char *TAG = "AI_ACCEL_CTRL";

// ---- ESP32-S3 pins ----
#define PIN_NUM_MISO -1
#define PIN_NUM_MOSI 17
#define PIN_NUM_CLK  18
#define PIN_NUM_CS   16
#define PIN_READY    15
#define PIN_DIGIT_3  7   // MSB
#define PIN_DIGIT_2  6
#define PIN_DIGIT_1  5
#define PIN_DIGIT_0  4   // LSB

#define IMG_BYTES 784
#define SYNC0 0xA5
#define SYNC1 0x5A

static uint8_t img[IMG_BYTES];

static void init_gpios(void) {
    gpio_config_t io_conf = {};
    io_conf.intr_type = GPIO_INTR_DISABLE;
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pin_bit_mask = (1ULL << PIN_READY) | (1ULL << PIN_DIGIT_3) | (1ULL << PIN_DIGIT_2) |
                           (1ULL << PIN_DIGIT_1) | (1ULL << PIN_DIGIT_0);
    io_conf.pull_down_en = GPIO_PULLDOWN_ENABLE;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    gpio_config(&io_conf);
}

static spi_device_handle_t init_spi(void) {
    spi_bus_config_t buscfg = {
        .miso_io_num = PIN_NUM_MISO, .mosi_io_num = PIN_NUM_MOSI, .sclk_io_num = PIN_NUM_CLK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 4096
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO));
    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 100 * 1000, .mode = 0, .spics_io_num = -1, .queue_size = 1,
    };
    spi_device_handle_t spi;
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &devcfg, &spi));
    gpio_set_direction(PIN_NUM_CS, GPIO_MODE_OUTPUT);
    gpio_set_level(PIN_NUM_CS, 1);
    return spi;
}

static void init_uart_rx(void) {
    // console UART0 (same COM port as idf.py monitor): add an RX buffer so we can read the PC's bytes
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
}

// wait for A5 5A, then read 784 bytes. returns true if a full image arrived
static bool receive_image(void) {
    uint8_t b, state = 0;
    while (1) {
        if (uart_read_bytes(UART_NUM_0, &b, 1, pdMS_TO_TICKS(100)) == 1) {
            if (state == 1 && b == SYNC1) break;
            state = (b == SYNC0) ? 1 : 0;
        }
    }
    int got = 0;
    while (got < IMG_BYTES) {
        int n = uart_read_bytes(UART_NUM_0, img + got, IMG_BYTES - got, pdMS_TO_TICKS(1000));
        if (n <= 0) { ESP_LOGE(TAG, "UART image timeout at %d/%d bytes", got, IMG_BYTES); return false; }
        got += n;
    }
    return true;
}

static void run_inference(spi_device_handle_t spi) {
    spi_transaction_t t = {};
    t.length = IMG_BYTES * 8;
    t.tx_buffer = img;

    gpio_set_level(PIN_NUM_CS, 0);
    esp_rom_delay_us(5);
    ESP_ERROR_CHECK(spi_device_transmit(spi, &t));
    gpio_set_level(PIN_NUM_CS, 1);

    int timeout = 0;
    while (gpio_get_level(PIN_READY) == 0) {
        esp_rom_delay_us(10);
        if (++timeout > 100000) { ESP_LOGE(TAG, "Timeout: Tang Nano did not signal ready flag."); return; }
        if (timeout % 1000 == 0) vTaskDelay(1);
    }
    uint8_t d = (gpio_get_level(PIN_DIGIT_3) << 3) | (gpio_get_level(PIN_DIGIT_2) << 2) |
                (gpio_get_level(PIN_DIGIT_1) << 1) |  gpio_get_level(PIN_DIGIT_0);
    ESP_LOGI(TAG, ">> FPGA Prediction Result: %d <<", d);
}

void app_main(void) {
    ESP_LOGI(TAG, "Edge AI Orchestrator: waiting for images from PC (A5 5A + 784 bytes)...");
    init_gpios();
    spi_device_handle_t spi = init_spi();
    init_uart_rx();

    while (1) {
        if (receive_image()) run_inference(spi);
    }
}