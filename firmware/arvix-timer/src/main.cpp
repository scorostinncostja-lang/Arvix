// ─── Arvix Timer ────────────────────────────────────────────────────────────
// Тонкий клиент фокус-сессий. Вся логика начисления XP/HP и решения о
// расписании — на сервере (см. docs/01-ARCHITECTURE.md §1, L0). Устройство:
//   1. Показывает то, что прислал сервер (display_ctl, led_ctl)
//   2. Принимает ввод (keypad_ctl, кнопка СТОП) и шлёт события (net_client)
//   3. При потере связи продолжает считать локально и не теряет события
//      (offline_buffer) — офлайн-контур из docs/00-VISION.md §5
#include <Arduino.h>
#include "config.h"
#include "types.h"
#include "display_ctl.h"
#include "led_ctl.h"
#include "buzzer_ctl.h"
#include "keypad_ctl.h"
#include "offline_buffer.h"
#include "net_client.h"

static DeviceState g_state;
static char g_numberInput[8] = {0};
static int  g_numberLen = 0;

// Локальный таймер — используется когда сервер недоступен, чтобы блок
// не "замирал" молча. Считает независимо от g_state.remainingSec,
// который в норме приходит с сервера.
static bool g_localTimerActive = false;
static uint32_t g_localDeadlineMs = 0;
static char g_localTaskId[40] = "local";
static int  g_localPlannedMin = 0;
static int  g_localInterruptions = 0;

static uint32_t g_lastRenderMs = 0;

static void onServerState(const DeviceState& st) {
    g_state = st;
    // Сервер — источник правды, локальный таймер больше не нужен пока связь жива.
    g_localTimerActive = false;
}

static void onServerBeep(const char* pattern) {
    buzzer::beep(pattern);
}

static void startLocalFallbackTimer(int minutes, const char* taskId) {
    g_localTimerActive = true;
    g_localDeadlineMs = millis() + (uint32_t)minutes * 60000UL;
    g_localPlannedMin = minutes;
    g_localInterruptions = 0;
    strlcpy(g_localTaskId, taskId, sizeof(g_localTaskId));
    g_state.phase = Phase::WORK;
    g_state.remainingSec = minutes * 60;
    strlcpy(g_state.taskTitle, "Локальный таймер", sizeof(g_state.taskTitle));
}

static void handleKey(char key) {
    if (key == 0) return;
    buzzer::beep("ok");

    if (key >= '0' && key <= '9') {
        if (g_numberLen < (int)sizeof(g_numberInput) - 1) {
            g_numberInput[g_numberLen++] = key;
            g_numberInput[g_numberLen] = '\0';
        }
        return; // копим цифры до '#'
    }

    switch (key) {
        case '#': {
            int minutes = g_numberLen > 0 ? atoi(g_numberInput) : 0;
            g_numberLen = 0; g_numberInput[0] = '\0';
            if (minutes <= 0) break;
            net_client::sendSessionStart("manual", minutes);
            if (!net_client::isConnected()) {
                startLocalFallbackTimer(minutes, "manual");
            }
            break;
        }
        case '1': // короткий код без '#': старт по плану дня
            net_client::sendKey('1');
            if (!net_client::isConnected()) startLocalFallbackTimer(90, "plan");
            break;
        case '2':
            net_client::sendKey('2');
            if (!net_client::isConnected()) startLocalFallbackTimer(10, "break");
            break;
        case 'A': // пауза/продолжить — сервер решает семантику; в офлайне просто пауза
            net_client::sendKey('A');
            break;
        case 'B':
            net_client::sendKey('B');
            break;
        case 'C':
            net_client::sendKey('C');
            if (g_localTimerActive) {
                net_client::sendSessionEnd(true, g_localPlannedMin, g_localInterruptions);
                g_localTimerActive = false;
                g_state.phase = Phase::IDLE;
            }
            break;
        case 'D':
            net_client::sendKey('D');
            if (g_localTimerActive) {
                int actualMin = g_localPlannedMin - (int)((g_localDeadlineMs - millis()) / 60000);
                net_client::sendSessionEnd(false, max(actualMin, 0), g_localInterruptions + 1);
                g_localTimerActive = false;
                g_state.phase = Phase::IDLE;
            }
            break;
        case '*':
            // статус уже на экране постоянно — клавиша просто "будит" дисплей/подсвечивает
            break;
        default:
            break;
    }
}

static void checkStopButton() {
    static bool lastState = HIGH;
    bool cur = digitalRead(STOP_BTN_PIN);
    if (lastState == HIGH && cur == LOW) {
        // Аварийный стоп: локально гасим всё немедленно, серверу сообщаем отдельно.
        buzzer::beep("alert");
        net_client::sendKey('D');
        if (g_localTimerActive) {
            net_client::sendSessionEnd(false, 0, g_localInterruptions + 1);
        }
        g_localTimerActive = false;
        g_state.phase = Phase::IDLE;
        g_state.remainingSec = 0;
    }
    lastState = cur;
}

static void tickLocalTimer() {
    if (!g_localTimerActive) return;
    uint32_t nowMs = millis();
    if (nowMs >= g_localDeadlineMs) {
        buzzer::beep("end");
        net_client::sendSessionEnd(true, g_localPlannedMin, g_localInterruptions);
        g_localTimerActive = false;
        g_state.phase = Phase::IDLE;
        g_state.remainingSec = 0;
        return;
    }
    uint32_t remainMs = g_localDeadlineMs - nowMs;
    g_state.remainingSec = remainMs / 1000;
    // Последние 5 минут локального таймера — тоже подаём как ALERT
    g_state.phase = (remainMs < 5UL * 60000UL) ? Phase::ALERT : Phase::WORK;
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.printf("\n[arvix-timer] прошивка %s\n", FW_VERSION);

    pinMode(STOP_BTN_PIN, INPUT_PULLUP);
    pinMode(STATUS_LED_PIN, OUTPUT);

    bool forcePortal = (digitalRead(STOP_BTN_PIN) == LOW); // держать СТОП при включении = сброс Wi-Fi
    if (forcePortal) Serial.println("[setup] СТОП удержан при старте — сброс сети");

    led::begin();
    buzzer::begin();
    keypad_ctl::begin();
    offline_buffer::begin();

    bool hasDisplay = display::begin();
    if (hasDisplay) display::renderSetupScreen(WIFI_PORTAL_SSID);

    configTzTime("MSK-3", "pool.ntp.org", "time.nist.gov"); // время для таймстампов офлайн-буфера

    net_client::begin(forcePortal, onServerState, onServerBeep);

    Serial.println("[setup] готов");
}

void loop() {
    net_client::loop();

    char key = keypad_ctl::poll();
    if (key) handleKey(key);

    checkStopButton();
    tickLocalTimer();

    // Фаза для индикатора: если сеть жива и недавно был ответ сервера — берём
    // фазу из состояния; если сеть пропала на >2 heartbeat-интервала — OFFLINE.
    Phase ledPhase = g_state.phase;
    if (!net_client::isConnected() && !g_localTimerActive) {
        ledPhase = Phase::OFFLINE;
    }
    led::tick(ledPhase);
    g_state.connected = net_client::isConnected();

    uint32_t now = millis();
    if (now - g_lastRenderMs >= 1000) { // экран обновляем не чаще 1 Гц
        g_lastRenderMs = now;
        display::render(g_state);
    }

    digitalWrite(STATUS_LED_PIN, (now / 1000) % 2); // heartbeat встроенным LED

    delay(15); // ~60 Гц опрос клавиатуры/кнопки, дёшево для ESP32
}
