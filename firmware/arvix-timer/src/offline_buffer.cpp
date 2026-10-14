#include "offline_buffer.h"
#include "config.h"
#include <Preferences.h>

static Preferences g_prefs;
static PendingEvent g_ring[OFFLINE_BUFFER_CAPACITY];
static int g_head = 0;   // индекс следующей записи
static int g_size = 0;   // текущее число событий

// Формат хранения в NVS: одно бинарное значение "buf" (весь массив) + "size".
// Простая схема без нормализации — 50 записей по ~56 байт = 2.8КБ, укладывается
// в лимиты NVS с большим запасом.

static void loadFromNVS() {
    size_t len = g_prefs.getBytesLength("buf");
    if (len == sizeof(g_ring)) {
        g_prefs.getBytes("buf", g_ring, sizeof(g_ring));
    }
    g_size = g_prefs.getInt("size", 0);
    g_head = g_size % OFFLINE_BUFFER_CAPACITY;
}

static void saveToNVS() {
    g_prefs.putBytes("buf", g_ring, sizeof(g_ring));
    g_prefs.putInt("size", g_size);
}

void offline_buffer::begin() {
    g_prefs.begin(NVS_NAMESPACE, false);
    loadFromNVS();
    Serial.printf("[offline_buffer] загружено %d событий из NVS\n", g_size);
}

bool offline_buffer::push(const PendingEvent& ev) {
    if (g_size >= OFFLINE_BUFFER_CAPACITY) {
        Serial.println("[offline_buffer] буфер полон — событие потеряно, история важнее новизны");
        return false;
    }
    g_ring[g_head] = ev;
    g_head = (g_head + 1) % OFFLINE_BUFFER_CAPACITY;
    g_size++;
    saveToNVS();
    return true;
}

int offline_buffer::count() { return g_size; }

bool offline_buffer::peek(int index, PendingEvent& out) {
    if (index < 0 || index >= g_size) return false;
    int start = (g_head - g_size + OFFLINE_BUFFER_CAPACITY) % OFFLINE_BUFFER_CAPACITY;
    out = g_ring[(start + index) % OFFLINE_BUFFER_CAPACITY];
    return true;
}

void offline_buffer::popFront(int n) {
    if (n <= 0) return;
    if (n >= g_size) {
        g_size = 0;
        g_head = 0;
    } else {
        // "удаление" первых n — сдвигаем логическое начало; физически проще
        // пересобрать компактный массив (буфер маленький, это дёшево).
        PendingEvent tmp[OFFLINE_BUFFER_CAPACITY];
        int start = (g_head - g_size + OFFLINE_BUFFER_CAPACITY) % OFFLINE_BUFFER_CAPACITY;
        int remaining = g_size - n;
        for (int i = 0; i < remaining; i++) {
            tmp[i] = g_ring[(start + n + i) % OFFLINE_BUFFER_CAPACITY];
        }
        memcpy(g_ring, tmp, sizeof(g_ring));
        g_size = remaining;
        g_head = g_size % OFFLINE_BUFFER_CAPACITY;
    }
    saveToNVS();
}

void offline_buffer::clear() {
    g_size = 0;
    g_head = 0;
    saveToNVS();
}
