#include "display_ctl.h"
#include "config.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

static Adafruit_SSD1306 g_oled(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
static bool g_ok = false;

static const char* phaseLabel(Phase p) {
    switch (p) {
        case Phase::WORK:    return "ФОКУС";
        case Phase::BREAK:   return "ПЕРЕРЫВ";
        case Phase::SLEEP:   return "СОН";
        case Phase::ALERT:   return "СКОРО КОНЕЦ";
        case Phase::OFFLINE: return "НЕТ СВЯЗИ";
        case Phase::NUDGE:   return "АРВИКС ЖДЁТ";
        default:             return "ОЖИДАНИЕ";
    }
}

bool display::begin() {
    Wire.begin(OLED_SDA, OLED_SCL);
    if (g_oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR_PRIMARY)) {
        g_ok = true;
    } else if (g_oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR_FALLBACK)) {
        g_ok = true;
    } else {
        Serial.println("[display] OLED не найден на 0x3C/0x3D — работаю без экрана");
        return false;
    }
    g_oled.setTextColor(SSD1306_WHITE);
    g_oled.clearDisplay();
    g_oled.display();
    return true;
}

void display::render(const DeviceState& state) {
    if (!g_ok) return;
    g_oled.clearDisplay();

    // Верхняя строка: фаза + статус связи
    g_oled.setTextSize(1);
    g_oled.setCursor(0, 0);
    g_oled.print(phaseLabel(state.phase));
    g_oled.setCursor(OLED_WIDTH - 18, 0);
    g_oled.print(state.connected ? "ON" : "--");

    // Крупный таймер MM:SS
    uint32_t m = state.remainingSec / 60;
    uint32_t s = state.remainingSec % 60;
    char buf[8];
    snprintf(buf, sizeof(buf), "%02lu:%02lu", (unsigned long)m, (unsigned long)s);
    g_oled.setTextSize(3);
    g_oled.setCursor(10, 16);
    g_oled.print(buf);

    // Название задачи (обрезается по ширине экрана)
    g_oled.setTextSize(1);
    g_oled.setCursor(0, 46);
    g_oled.print(state.taskTitle);

    // Нижняя строка: HP / XP / выполнение
    g_oled.setCursor(0, 56);
    char foot[32];
    snprintf(foot, sizeof(foot), "HP:%d XP:%d %s", state.hp, state.xp, state.completion);
    g_oled.print(foot);

    g_oled.display();
}

void display::renderSetupScreen(const char* apName) {
    if (!g_ok) return;
    g_oled.clearDisplay();
    g_oled.setTextSize(1);
    g_oled.setCursor(0, 0);
    g_oled.println("НАСТРОЙКА WI-FI");
    g_oled.println();
    g_oled.println("Подключись к сети:");
    g_oled.println(apName);
    g_oled.println();
    g_oled.println("Открой 192.168.4.1");
    g_oled.display();
}
