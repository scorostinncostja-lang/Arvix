#pragma once
#include "types.h"

namespace display {
    // Инициализация I2C + OLED. Сканирует оба возможных адреса (0x3C/0x3D),
    // возвращает false если дисплей не найден — устройство работает и без
    // экрана (звук + LED остаются), просто предупреждает в Serial.
    bool begin();

    // Полная перерисовка под текущее состояние. Вызывается раз в секунду
    // из главного цикла, не чаще — OLED не любит быстрый рефреш текста.
    void render(const DeviceState& state);

    // Экран первого включения / портала настройки Wi-Fi
    void renderSetupScreen(const char* apName);
}
