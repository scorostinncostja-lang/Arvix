#!/usr/bin/env python3
"""Запуск тестов с выводом результатов."""
import sys
import pytest

# Запускаем pytest программно
exit_code = pytest.main([
    "tests/",
    "-v",
    "--tb=short",
    "--color=yes"
])

print(f"\n{'='*60}")
print(f"Код завершения: {exit_code}")
if exit_code == 0:
    print("✅ ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
else:
    print(f"❌ Тесты завершились с ошибками (код {exit_code})")
print(f"{'='*60}")

sys.exit(exit_code)
