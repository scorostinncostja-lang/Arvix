#include "buzzer_ctl.h"
#include "config.h"
#include <Arduino.h>

void buzzer::begin() {
    ledcSetup(BUZZER_LEDC_CH, 2000, 8);
    ledcAttachPin(BUZZER_PIN, BUZZER_LEDC_CH);
    ledcWrite(BUZZER_LEDC_CH, 0);
}

static void tone_ms(uint32_t freq, uint32_t ms) {
    ledcWriteTone(BUZZER_LEDC_CH, freq);
    delay(ms);
    ledcWriteTone(BUZZER_LEDC_CH, 0);
}

// Блокирующие, короткие (<1с суммарно) — приемлемо в реакции на клавишу/таймер,
// но НЕ вызывать внутри цикла, отвечающего за сеть/дисплей на каждый тик.
void buzzer::beep(const char* pattern) {
    if (strcmp(pattern, "ok") == 0) {
        tone_ms(1800, 60);
    } else if (strcmp(pattern, "end") == 0) {
        tone_ms(1200, 150); delay(80);
        tone_ms(1200, 150); delay(80);
        tone_ms(1600, 250);
    } else if (strcmp(pattern, "alert") == 0) {
        tone_ms(900, 100); delay(100);
        tone_ms(900, 100);
    }
}
