"""
diagnostics.py — встроенная самопроверка готовности бота.
Все проверки ПАССИВНЫЕ: не кликают, не жмут клавиши в игре, не меняют
состояние сценариев. Можно гонять сколько угодно раз без риска.
Возвращает список результатов вида:
{"name": "...", "ok": True/False, "detail": "..."}
v5: добавлены проверки игрового лога (путь/читаемость) и списка триггеров;
учитывается выбранный check_mode.
"""

import importlib
import json
import os

import settings as settings_module
from log_monitor import resolve_game_log_path

TEMPLATE_FILE = "template.png"
SCENARIO_FILES = ["scenario_chat.json", "scenario_movement.json"]
SETTINGS_FILE = "settings.json"


def check_window(window_title: str):
    """Проверка: окно Minecraft найдено по заданному заголовку."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(window_title)
        if windows:
            return {"name": "Окно Minecraft", "ok": True, "detail": f"Найдено окно с заголовком '{window_title}'."}
        return {"name": "Окно Minecraft", "ok": False, "detail": f"Окно с заголовком '{window_title}' не найдено."}
    except Exception as e:
        return {"name": "Окно Minecraft", "ok": False, "detail": f"Ошибка проверки: {e}"}


def check_template():
    """Проверка: template.png существует и читается OpenCV."""
    if not os.path.exists(TEMPLATE_FILE):
        return {"name": "Шаблон template.png", "ok": False, "detail": "Файл не найден."}
    try:
        import cv2
        img = cv2.imread(TEMPLATE_FILE, cv2.IMREAD_COLOR)
        if img is None:
            return {"name": "Шаблон template.png", "ok": False, "detail": "Файл найден, но не читается как изображение."}
        h, w = img.shape[:2]
        return {"name": "Шаблон template.png", "ok": True, "detail": f"Прочитан, размер {w}x{h}px."}
    except Exception as e:
        return {"name": "Шаблон template.png", "ok": False, "detail": f"Ошибка чтения: {e}"}


def _validate_scenario_dict(data):
    """Проверяет обязательные поля формата сценария. Бросает ValueError при проблеме."""
    if "steps" not in data:
        raise ValueError("отсутствует поле 'steps'")
    if not isinstance(data["steps"], list):
        raise ValueError("'steps' должно быть списком")
    for i, step in enumerate(data["steps"], 1):
        step_type = step.get("type")
        if step_type == "key_hold":
            if "key" not in step or "duration_ms" not in step:
                raise ValueError(f"шаг {i}: key_hold требует 'key' и 'duration_ms'")
        elif step_type == "mouse_click":
            if "x" not in step or "y" not in step:
                raise ValueError(f"шаг {i}: mouse_click требует 'x' и 'y'")
        else:
            raise ValueError(f"шаг {i}: неизвестный тип '{step_type}'")


def check_scenarios():
    """Проверка: файлы сценариев существуют, валидны, обязательные поля на месте."""
    results = []
    for filename in SCENARIO_FILES:
        if not os.path.exists(filename):
            results.append({"name": f"Сценарий {filename}", "ok": False, "detail": "Файл не найден."})
            continue
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            _validate_scenario_dict(data)
            results.append({
                "name": f"Сценарий {filename}",
                "ok": True,
                "detail": f"Валиден, шагов: {len(data['steps'])}.",
            })
        except json.JSONDecodeError as e:
            results.append({"name": f"Сценарий {filename}", "ok": False, "detail": f"Ошибка JSON: {e}"})
        except ValueError as e:
            results.append({"name": f"Сценарий {filename}", "ok": False, "detail": f"Некорректный формат: {e}"})
        except Exception as e:
            results.append({"name": f"Сценарий {filename}", "ok": False, "detail": f"Ошибка: {e}"})
    return results


def check_settings():
    """Проверка: settings.json читается корректно (хоткей, тайминг, метод проверки)."""
    if not os.path.exists(SETTINGS_FILE):
        return {"name": "settings.json", "ok": True, "detail": "Файл отсутствует — будут использованы значения по умолчанию."}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        hotkey = data.get("hotkey", "?")
        schedule = data.get("schedule", {})
        check_mode = data.get("check_mode", "both (по умолчанию)")
        return {
            "name": "settings.json",
            "ok": True,
            "detail": f"Хоткей: {hotkey}; расписание: {schedule}; проверка: {check_mode}.",
        }
    except Exception as e:
        return {"name": "settings.json", "ok": False, "detail": f"Ошибка чтения: {e}"}


def check_game_log(settings: dict):
    """Проверка: игровой лог latest.log существует и читается (если метод использует лог)."""
    mode = settings.get("check_mode", "both")
    if mode not in ("log", "both"):
        return {"name": "Игровой лог latest.log", "ok": True, "detail": f"Не используется (метод проверки: {mode})."}
    path = resolve_game_log_path(settings.get("game_log_path", ""))
    if not path:
        return {"name": "Игровой лог latest.log", "ok": False,
                "detail": "Путь не задан и %APPDATA% недоступен — укажи путь в настройках."}
    if not os.path.exists(path):
        return {"name": "Игровой лог latest.log", "ok": False, "detail": f"Файл не найден: {path}"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.read(256)
        return {"name": "Игровой лог latest.log", "ok": True, "detail": f"Найден и читается: {path}"}
    except Exception as e:
        return {"name": "Игровой лог latest.log", "ok": False, "detail": f"Ошибка чтения: {e}"}


def check_triggers(settings: dict):
    """Проверка: список строк-триггеров не пуст (если метод использует лог)."""
    mode = settings.get("check_mode", "both")
    if mode not in ("log", "both"):
        return {"name": "Триггеры лога", "ok": True, "detail": f"Не используются (метод проверки: {mode})."}
    triggers = [str(t).strip() for t in settings.get("log_triggers", []) if str(t).strip()]
    if not triggers:
        return {"name": "Триггеры лога", "ok": False,
                "detail": "Список пуст — добавь хотя бы один триггер в настройках."}
    preview = ", ".join(triggers[:3]) + ("…" if len(triggers) > 3 else "")
    return {"name": "Триггеры лога", "ok": True, "detail": f"Задано: {len(triggers)} ({preview})."}


def check_libraries():
    """Проверка: обязательные библиотеки импортируются; опциональные (трей) — отмечаются."""
    required = ["pyautogui", "cv2", "pynput", "pygetwindow", "pytz", "numpy"]
    missing = []
    for lib in required:
        try:
            importlib.import_module(lib)
        except Exception as e:
            missing.append(f"{lib} ({e})")
    if missing:
        return {"name": "Библиотеки", "ok": False, "detail": "Не импортируются: " + ", ".join(missing)}

    optional_missing = []
    for lib in ("pystray", "PIL"):
        try:
            importlib.import_module(lib)
        except Exception:
            optional_missing.append(lib)
    detail = "Все необходимые библиотеки импортируются успешно."
    if optional_missing:
        detail += f" Опционально недоступны: {', '.join(optional_missing)} (трей работать не будет)."
    return {"name": "Библиотеки", "ok": True, "detail": detail}


def run_full_diagnostics(window_title: str):
    """
    Запускает все проверки и возвращает единый список результатов
    в фиксированном порядке (для стабильного отображения в GUI и логе).
    """
    current_settings = settings_module.load_settings()
    results = [check_window(window_title), check_template()]
    results.extend(check_scenarios())
    results.append(check_settings())
    results.append(check_game_log(current_settings))
    results.append(check_triggers(current_settings))
    results.append(check_libraries())
    return results


def format_report(results) -> str:
    """Форматирует список результатов в текстовый отчёт с ✅/❌."""
    lines = []
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"{mark} {r['name']}: {r['detail']}")
    return "\n".join(lines)