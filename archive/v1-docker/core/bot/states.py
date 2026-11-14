"""FSM состояния для proof-подтверждения задач."""

from aiogram.fsm.state import State, StatesGroup


class TaskProofStates(StatesGroup):
    """Состояния FSM для подтверждения выполнения задач."""

    waiting_for_report = State()  # Ожидание текстового отчета
    waiting_for_partial = State()  # Ожидание отчета о частичном выполнении
    waiting_for_photo = State()  # Ожидание фото (фаза 0: принимаем текст как fallback)
