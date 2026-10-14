#include "net_client.h"
#include "config.h"
#include "offline_buffer.h"
#include <WiFi.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

static WebSocketsClient g_ws;
static Preferences g_netPrefs;
static bool g_connected = false;
static uint32_t g_lastHeartbeat = 0;
static char g_wsHost[64];
static int  g_wsPort;
static char g_wsPath[32];
static char g_deviceToken[40];

static net_client::StateCallback g_onState;
static net_client::BeepCallback  g_onBeep;

static void flushOfflineBuffer() {
    int n = offline_buffer::count();
    if (n == 0) return;
    Serial.printf("[net] дозапись %d событий из офлайн-буфера\n", n);
    for (int i = 0; i < n; i++) {
        PendingEvent ev;
        if (!offline_buffer::peek(i, ev)) break;
        JsonDocument doc;
        doc["t"] = ev.kind;
        doc["at"] = ev.atUnix;
        if (strlen(ev.taskId) > 0) doc["task_id"] = ev.taskId;
        if (ev.minutes >= 0) doc["minutes"] = ev.minutes;
        if (strcmp(ev.kind, "session_end") == 0) {
            doc["completed"] = ev.completed;
            doc["interruptions"] = ev.interruptions;
        }
        doc["replay"] = true; // сервер знает, что таймстамп не "сейчас"
        String out;
        serializeJson(doc, out);
        g_ws.sendTXT(out);
    }
    offline_buffer::clear();
}

static void handleServerMessage(const char* payload) {
    JsonDocument doc;
    if (deserializeJson(doc, payload)) return;
    const char* t = doc["t"] | "";

    if (strcmp(t, "state") == 0) {
        DeviceState st;
        const char* phaseStr = doc["phase"] | "idle";
        if      (!strcmp(phaseStr, "work"))    st.phase = Phase::WORK;
        else if (!strcmp(phaseStr, "break"))   st.phase = Phase::BREAK;
        else if (!strcmp(phaseStr, "sleep"))   st.phase = Phase::SLEEP;
        else if (!strcmp(phaseStr, "alert"))   st.phase = Phase::ALERT;
        else if (!strcmp(phaseStr, "nudge"))   st.phase = Phase::NUDGE;
        else                                   st.phase = Phase::IDLE;

        st.remainingSec = doc["remaining_s"] | 0;
        st.hp = doc["hp"] | 100;
        st.xp = doc["xp"] | 0;
        strlcpy(st.taskTitle, (doc["task"] | "—"), sizeof(st.taskTitle));
        strlcpy(st.completion, (doc["completion"] | "0/0"), sizeof(st.completion));
        st.connected = true;
        st.lastServerMsgMs = millis();
        if (g_onState) g_onState(st);
    } else if (strcmp(t, "beep") == 0) {
        const char* pattern = doc["pattern"] | "ok";
        if (g_onBeep) g_onBeep(pattern);
    }
    // "nudge" с текстом обрабатывается через фазу NUDGE + отдельный beep,
    // сервер шлёт оба сообщения — текст показывать смысла нет, экран мал.
}

static void wsEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED: {
            g_connected = true;
            JsonDocument doc;
            doc["t"] = "hello";
            doc["token"] = g_deviceToken;
            doc["fw"] = FW_VERSION;
            String out;
            serializeJson(doc, out);
            g_ws.sendTXT(out);
            flushOfflineBuffer();
            break;
        }
        case WStype_DISCONNECTED:
            g_connected = false;
            break;
        case WStype_TEXT:
            handleServerMessage((const char*)payload);
            break;
        default:
            break;
    }
}

void net_client::begin(bool forcePortal, StateCallback onState, BeepCallback onBeep) {
    g_onState = onState;
    g_onBeep = onBeep;

    g_netPrefs.begin(NVS_NAMESPACE, false);
    strlcpy(g_wsHost, g_netPrefs.getString("ws_host", DEFAULT_WS_HOST).c_str(), sizeof(g_wsHost));
    g_wsPort = g_netPrefs.getInt("ws_port", DEFAULT_WS_PORT);
    strlcpy(g_wsPath, g_netPrefs.getString("ws_path", DEFAULT_WS_PATH).c_str(), sizeof(g_wsPath));
    strlcpy(g_deviceToken, g_netPrefs.getString("token", "").c_str(), sizeof(g_deviceToken));

    WiFiManager wm;
    WiFiManagerParameter p_host("host", "Сервер (host)", g_wsHost, 63);
    WiFiManagerParameter p_token("token", "Токен устройства (из TWA)", g_deviceToken, 39);
    wm.addParameter(&p_host);
    wm.addParameter(&p_token);

    if (forcePortal) wm.resetSettings();

    bool ok = wm.autoConnect(WIFI_PORTAL_SSID);
    if (!ok) {
        Serial.println("[net] Wi-Fi не настроен — перезапуск в портал через 3с");
        delay(3000);
        ESP.restart();
    }

    strlcpy(g_wsHost, p_host.getValue(), sizeof(g_wsHost));
    strlcpy(g_deviceToken, p_token.getValue(), sizeof(g_deviceToken));
    g_netPrefs.putString("ws_host", g_wsHost);
    g_netPrefs.putString("token", g_deviceToken);

    g_ws.beginSSL(g_wsHost, g_wsPort, g_wsPath);
    g_ws.onEvent(wsEvent);
    g_ws.setReconnectInterval(WS_RECONNECT_MS);
}

void net_client::loop() {
    g_ws.loop();

    uint32_t now = millis();
    if (g_connected && now - g_lastHeartbeat > HEARTBEAT_MS) {
        g_lastHeartbeat = now;
        JsonDocument doc;
        doc["t"] = "heartbeat";
        doc["uptime"] = now / 1000;
        doc["rssi"] = WiFi.RSSI();
        String out;
        serializeJson(doc, out);
        g_ws.sendTXT(out);
    }
}

bool net_client::isConnected() { return g_connected; }

static void queueOrSend(const JsonDocument& doc, const PendingEvent& asEvent) {
    if (g_connected) {
        String out;
        serializeJson(doc, out);
        g_ws.sendTXT(out);
    } else {
        offline_buffer::push(asEvent);
    }
}

void net_client::sendKey(char code) {
    JsonDocument doc;
    doc["t"] = "key";
    doc["code"] = String(code);
    PendingEvent ev = {};
    ev.atUnix = time(nullptr);
    strlcpy(ev.kind, "key", sizeof(ev.kind));
    ev.minutes = -1;
    queueOrSend(doc, ev);
}

void net_client::sendSessionStart(const char* taskId, int minutes) {
    JsonDocument doc;
    doc["t"] = "session_start";
    doc["task_id"] = taskId;
    doc["minutes"] = minutes;
    doc["at"] = time(nullptr);
    PendingEvent ev = {};
    ev.atUnix = time(nullptr);
    strlcpy(ev.kind, "session_start", sizeof(ev.kind));
    strlcpy(ev.taskId, taskId, sizeof(ev.taskId));
    ev.minutes = minutes;
    queueOrSend(doc, ev);
}

void net_client::sendSessionEnd(bool completed, int actualMin, int interruptions) {
    JsonDocument doc;
    doc["t"] = "session_end";
    doc["completed"] = completed;
    doc["actual_min"] = actualMin;
    doc["interruptions"] = interruptions;
    PendingEvent ev = {};
    ev.atUnix = time(nullptr);
    strlcpy(ev.kind, "session_end", sizeof(ev.kind));
    ev.minutes = actualMin;
    ev.completed = completed;
    ev.interruptions = (uint8_t)interruptions;
    queueOrSend(doc, ev);
}
