#pragma once

namespace buzzer {
    void begin();
    // "ok"    — короткий тихий бип (подтверждение клавиши)
    // "end"   — тройной сигнал (конец блока)
    // "alert" — прерывистый сигнал (осталось <5 мин)
    void beep(const char* pattern);
}
