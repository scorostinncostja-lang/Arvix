#pragma once
#include "types.h"
#include <functional>

// Тонкий сетевой слой: WiFiManager для первичной настройки (портал на
// 192.168.4.1, без хардкода Wi-Fi в прошивке), WebSocket-клиент к серверу
// Арвикса. Устройство НИКОГДА не считает XP/HP/решения сам — только
// показывает то, что прислал сервер, и локально досчитывает таймер офлайн.
namespace net_client {
    using StateCallback = std::function<void(const DeviceState&)>;
    using BeepCallback  = std::function<void(const char* pattern)>;

    // Запускает портал настройки, если сохранённых Wi-Fi-данных нет
    // (или если при старте была зажата кнопка СТОП — принудительный ресет сети).
    void begin(bool forcePortal, StateCallback onState, BeepCallback onBeep);

    // Неблокирующий тик: держит соединение, шлёт heartbeat, дозаписывает
    // офлайн-буфер. Вызывать в главном цикле.
    void loop();

    bool isConnected();

    // Исходящие события — сеть сама решает: если подключены, шлём сразу;
    // если нет — кладём в offline_buffer::push() и уйдёт при реконнекте.
    void sendKey(char code);
    void sendSessionStart(const char* taskId, int minutes);
    void sendSessionEnd(bool completed, int actualMin, int interruptions);
}
