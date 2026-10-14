#pragma once
// ─── Arvix Timer · конфигурация ────────────────────────────────────────────
// Тонкий клиент: сервер решает XP/HP/расписание, устройство только
// показывает состояние и держит локальный таймер, когда связи нет.

// --- OLED ---
#define OLED_SDA        21
#define OLED_SCL        22
#define OLED_WIDTH      128
#define OLED_HEIGHT     64
#define OLED_ADDR_PRIMARY   0x3C
#define OLED_ADDR_FALLBACK  0x3D

// --- Клавиатура 4x4 ---
#define KEYPAD_ROW0     13
#define KEYPAD_ROW1     12   // strapping pin (MTDI) — ТОЛЬКО как вход с pull-up
#define KEYPAD_ROW2     14
#define KEYPAD_ROW3     27
#define KEYPAD_COL0     26
#define KEYPAD_COL1     25
#define KEYPAD_COL2     33
#define KEYPAD_COL3     32

// --- WS2812 ---
#define LED_PIN         4
#define LED_COUNT       1

// --- Зуммер (через транзисторный ключ) ---
#define BUZZER_PIN      18
#define BUZZER_LEDC_CH  0

// --- Кнопка СТОП / паника ---
#define STOP_BTN_PIN    19

// --- Встроенный статус-LED платы (heartbeat) ---
#define STATUS_LED_PIN  2

// --- Сеть ---
#define WIFI_PORTAL_SSID   "Arvix-Setup"
#define WS_RECONNECT_MS    5000
#define HEARTBEAT_MS       15000

// Заполняется при провизии устройства (см. firmware/README.md).
// Не хардкодить в git — переопределяется через WiFiManager custom params
// и сохраняется в Preferences (NVS), эти define — только дефолты для первого билда.
#define DEFAULT_WS_HOST    "arvix.example.com"
#define DEFAULT_WS_PORT    443
#define DEFAULT_WS_PATH    "/ws/device"

// --- Локальный офлайн-буфер ---
#define OFFLINE_BUFFER_CAPACITY  50
#define NVS_NAMESPACE            "arvix"

// --- Прошивка ---
#define FW_VERSION      "1.0.0"
