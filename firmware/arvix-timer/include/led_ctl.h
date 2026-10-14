#pragma once
#include "types.h"

namespace led {
    void begin();
    // Обновляет цвет/паттерн по фазе. Вызывать в главном цикле (~20 Гц) —
    // сам решает нужно ли мигать/пульсировать, исходя из millis().
    void tick(Phase phase);
}
