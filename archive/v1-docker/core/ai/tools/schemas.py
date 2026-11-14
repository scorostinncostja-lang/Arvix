"""JSON-схемы инструментов для L1 (Tools).

Максимум 2 итерации вызова инструментов за один цикл ответа.
"""

from typing import Any

# JSON-схемы в формате OpenAI Function Calling

GET_DAY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_day",
        "description": "Получить задачи и метрики конкретного дня (например, вчера, завтра)",
        "parameters": {
            "type": "object",
            "properties": {
                "date_str": {
                    "type": "string",
                    "description": "Дата в формате YYYY-MM-DD (например, '2026-10-26')",
                }
            },
            "required": ["date_str"],
        },
    },
}

CREATE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Создать новую задачу в расписании",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название задачи"},
                "sphere": {
                    "type": "string",
                    "enum": ["work", "study", "health", "social", "meta"],
                    "description": "Сфера жизни",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Важность (1-5)",
                },
                "difficulty": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Сложность (1-5)",
                },
                "planned_start": {
                    "type": "string",
                    "description": "Время начала в формате ISO8601 (например, '2026-10-26T15:00:00+03:00')",
                },
                "duration_min": {
                    "type": "integer",
                    "description": "Длительность в минутах",
                },
                "deep_work": {
                    "type": "boolean",
                    "description": "Требует глубокой концентрации",
                    "default": False,
                },
            },
            "required": ["title", "sphere", "importance", "difficulty", "planned_start", "duration_min"],
        },
    },
}

COMPLETE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "complete_task",
        "description": "Закрыть задачу как выполненную",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UUID задачи",
                },
                "quality": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Качество выполнения (1-5)",
                },
                "note": {
                    "type": "string",
                    "description": "Заметка о выполнении (опционально)",
                },
            },
            "required": ["task_id", "quality"],
        },
    },
}

PROPOSE_SCHEDULE_CHANGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_schedule_change",
        "description": "Получить факты для принятия решения об изменении расписания "
        "(сколько выполнено, конфликты, долги, режим)",
        "parameters": {
            "type": "object",
            "properties": {
                "changes_description": {
                    "type": "string",
                    "description": "Описание запрашиваемых изменений",
                }
            },
            "required": ["changes_description"],
        },
    },
}

ALL_TOOLS = [GET_DAY_TOOL, CREATE_TASK_TOOL, COMPLETE_TASK_TOOL, PROPOSE_SCHEDULE_CHANGE_TOOL]
