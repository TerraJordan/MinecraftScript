"""
tests/conftest.py — общие фикстуры и обходные пути для кросс-платформенного
запуска тестов.

1) Добавляем корень проекта (родительскую папку tests/) в sys.path, чтобы
   тесты могли импортировать модули проекта (audit, log_monitor, notifier,
   party_acceptor и т.д.) без установки пакета.
2) pygetwindow не поддерживает Linux (только Windows/macOS), но сам проект
   предназначен для Windows. Чтобы `import bot` не падал на Linux (CI),
   подставляем минимальную заглушку pygetwindow, если настоящий импорт
   не удаётся. На Windows используется настоящая библиотека.
"""

import os
import sys
import types

# Корень проекта — в sys.path, чтобы тесты импортировали модули проекта
# независимо от порядка сбора тестов pytest.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Корень проекта — в начало sys.path ДО импорта любых тестовых модулей
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _install_pygetwindow_stub():
    try:
        import pygetwindow  # noqa: F401
        return  # настоящая библиотека доступна — ничего не делаем
    except Exception:
        pass

    stub = types.ModuleType("pygetwindow")

    def getWindowsWithTitle(title):
        return []

    stub.getWindowsWithTitle = getWindowsWithTitle
    sys.modules["pygetwindow"] = stub


_install_pygetwindow_stub()