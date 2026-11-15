"""Загрузчик конституции и тон-блоков.

КРИТИЧЕСКИЙ ИНВАРИАНТ (01-architecture-invariants.md):
При mode == "RED" или mentor_enabled == False тон-блоки 'norm' и 'pressure'
физически НЕ МОГУТ попасть в системный промпт — всегда подставляется только
мягкий восстановительный тон 'red'.
"""

from pathlib import Path


def load_xml_section(name: str) -> str:
    """Загрузить XML-секцию конституции из файла."""
    path = Path(__file__).parent / f"{name}.xml"
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(mode: str = "normal", mentor_enabled: bool = True) -> str:
    """Собрать системный промпт из статических секций и тон-блока.

    Args:
        mode: Режим Burnout Guard (normal, yellow, red)
        mentor_enabled: Флаг включения ментора из профиля

    Returns:
        Полный системный промпт (конституция + тон-блок)
    """
    # Статические секции (для prompt caching)
    sections = [
        "identity",
        "mission",
        "voice",
        "autonomy_rule",
        "decision_rule",
        "honesty",
        "boundaries",
        "safety_override",
    ]

    static_content = "\n\n".join(load_xml_section(s) for s in sections)

    # КРИТИЧЕСКИЙ ИНВАРИАНТ: при RED или mentor_enabled=False жёсткие тоны запрещены
    if mode == "red" or not mentor_enabled:
        tone_block = load_xml_section("tone_red")
    elif mode == "yellow":
        tone_block = load_xml_section("tone_yellow")
    elif mode == "pressure":
        tone_block = load_xml_section("tone_pressure")
    else:  # normal
        tone_block = load_xml_section("tone_norm")

    # Порядок: сначала статика (кэшируется), потом динамический тон-блок
    return f"{static_content}\n\n{tone_block}"
