#!/usr/bin/env python3
"""Простая проверка подключения к БД."""

import asyncio
from core.db.session import async_session_factory


async def main():
    print("Проверка подключения к БД...")
    try:
        async with async_session_factory() as sess:
            result = await sess.execute("SELECT version();")
            version = result.scalar()
            print(f"✓ PostgreSQL подключен: {version}")
            
        print("\nЗапуск pytest...")
        import subprocess
        result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "tests/", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Печатаем последние 100 строк
        lines = result.stdout.split('\n')
        for line in lines[-100:]:
            print(line)
            
        print(f"\nВыходной код: {result.returncode}")
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
