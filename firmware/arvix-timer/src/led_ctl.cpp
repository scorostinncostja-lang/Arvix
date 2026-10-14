#include "led_ctl.h"
#include "config.h"
#include <Adafruit_NeoPixel.h>

static Adafruit_NeoPixel g_strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

void led::begin() {
    g_strip.begin();
    g_strip.setBrightness(80);
    g_strip.show();
}

// Цвета по протоколу из docs/06-IOT-BIOMETRICS.md §"Индикация"
void led::tick(Phase phase) {
    uint32_t now = millis();
    uint32_t color = 0;

    switch (phase) {
        case Phase::WORK:
            color = g_strip.Color(0, 0, 255);            // синий, ровно
            break;
        case Phase::BREAK:
            color = g_strip.Color(0, 255, 0);             // зелёный, ровно
            break;
        case Phase::SLEEP:
            color = g_strip.Color(255, 0, 0);              // красный, ровно, приглушённо
            g_strip.setBrightness(20);
            break;
        case Phase::ALERT: {
            // красный, мигание 2 Гц
            bool on = (now / 250) % 2 == 0;
            color = on ? g_strip.Color(255, 0, 0) : 0;
            g_strip.setBrightness(80);
            break;
        }
        case Phase::OFFLINE:
            color = g_strip.Color(255, 180, 0);            // жёлтый, ровно
            g_strip.setBrightness(60);
            break;
        case Phase::NUDGE: {
            // фиолетовый пульс (плавное дыхание через синус по времени)
            float phase_t = (now % 2000) / 2000.0f;
            float bri = (sinf(phase_t * 2.0f * PI) + 1.0f) / 2.0f; // 0..1
            uint8_t v = (uint8_t)(bri * 200) + 30;
            color = g_strip.Color(v, 0, v);
            g_strip.setBrightness(90);
            break;
        }
        default: // IDLE
            color = 0;
            break;
    }

    g_strip.setPixelColor(0, color);
    g_strip.show();
}
