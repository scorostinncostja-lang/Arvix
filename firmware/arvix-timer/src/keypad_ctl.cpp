#include "keypad_ctl.h"
#include "config.h"
#include <Keypad.h>

static const byte ROWS = 4, COLS = 4;
static char keys[ROWS][COLS] = {
    {'1','2','3','A'},
    {'4','5','6','B'},
    {'7','8','9','C'},
    {'*','0','#','D'}
};
static byte rowPins[ROWS] = {KEYPAD_ROW0, KEYPAD_ROW1, KEYPAD_ROW2, KEYPAD_ROW3};
static byte colPins[COLS] = {KEYPAD_COL0, KEYPAD_COL1, KEYPAD_COL2, KEYPAD_COL3};

static Keypad g_kp(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

void keypad_ctl::begin() {
    g_kp.setDebounceTime(15);
}

char keypad_ctl::poll() {
    return g_kp.getKey(); // 0 если ничего не нажато
}
