#pragma once
#include <Arduino.h>

// Фаза — состояние верхнего уровня, определяет цвет индикатора и экран.
// Источник правды на сервере; устройство просто исполняет и, при потере
// связи, продолжает досчитывать локально без изменения смысла фазы.
enum class Phase : uint8_t {
    IDLE = 0,      // ничего не идёт, ожидание команды
    WORK,          // фокус-сессия
    BREAK,         // перерыв
    SLEEP,         // ночной режим — устройство приглушено
    ALERT,         // <5 минут до конца блока
    OFFLINE,       // нет связи с сервером, работает локально
    NUDGE          // Арвикс требует внимания (непрочитанный вопрос)
};

struct DeviceState {
    Phase   phase          = Phase::IDLE;
    uint32_t remainingSec  = 0;
    char    taskTitle[40]  = "—";
    uint8_t hp             = 100;
    uint16_t xp            = 0;
    char    completion[8]  = "0/0";
    bool    connected      = false;
    uint32_t lastServerMsgMs = 0;
};

// Событие, которое нужно доставить серверу. При офлайне копится в NVS.
struct PendingEvent {
    uint32_t atUnix;          // время события (unix ts, синхронизировано по NTP при наличии сети)
    char     kind[24];        // "session_start" | "session_end" | "key"
    char     taskId[40];      // может быть пустым
    int32_t  minutes;         // длительность / -1 если не применимо
    bool     completed;       // для session_end
    uint8_t  interruptions;   // для session_end
};
