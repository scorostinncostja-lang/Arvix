#pragma once
#include "types.h"

// Кольцевой буфер необработанных событий в NVS (Preferences).
// При потере сети события копятся здесь; при восстановлении связи
// net_client дозаписывает их на сервер по порядку и очищает буфер.
// Переживает перезагрузку и потерю питания — это и есть смысл: сервер
// умер, устройство продолжает считать и ничего не теряет.
namespace offline_buffer {
    void begin();
    bool push(const PendingEvent& ev);   // false если буфер полон (старое НЕ затирается — теряем новое, не историю)
    int  count();
    bool peek(int index, PendingEvent& out);
    void popFront(int n);                // удалить n самых старых после успешной отправки
    void clear();
}
