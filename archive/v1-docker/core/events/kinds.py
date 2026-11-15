from enum import StrEnum


class EventKind(StrEnum):
    """Каталог событий — 03-DATA-MODEL.md §1. Единственный источник правды о том,
    какие виды событий существуют в системе."""

    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_DEFERRED = "task_deferred"
    TASK_DEBTED = "task_debted"
    PROOF_SUBMITTED = "proof_submitted"
    PROOF_SUSPICIOUS = "proof_suspicious"
    SLEEP_RECORDED = "sleep_recorded"
    BIOMETRICS_RECORDED = "biometrics_recorded"
    FOCUS_SESSION = "focus_session"
    XP_AWARDED = "xp_awarded"
    HP_CHANGED = "hp_changed"
    SHIELD_USED = "shield_used"
    MODE_CHANGED = "mode_changed"
    QUOTA_MET = "quota_met"
    QUOTA_MISSED = "quota_missed"
    EXPENSE_LOGGED = "expense_logged"
    DIRECTIVE_CREATED = "directive_created"
    INSIGHT = "insight"
    DEBRIEF_COMPLETED = "debrief_completed"
    SILENT_DAY_RESULT = "silent_day_result"
    MESSAGE_IN = "message_in"
    MESSAGE_OUT = "message_out"
    LEARNING_QUESTION = "learning_question"
    SAFETY_FLAG = "safety_flag"


class EventSource(StrEnum):
    USER = "user"
    BOT = "bot"
    TWA = "twa"
    ESP32 = "esp32"
    SCHEDULER = "scheduler"
    L2 = "l2"
