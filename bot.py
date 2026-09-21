"""
bot.py — автоматизация поиска группы в оконном режиме Minecraft.
v7: поверх v5 добавлен конвейер событий игрового лога:
  - распознавание приглашений в группу, подземелий (3 типа) и диких рейдов
    по настраиваемым regex-паттернам (log_monitor.py);
  - авто-принятие приглашений (party_acceptor.py): основной метод —
    команда из лога отправляется в чат, резервный — OpenCV-клик по
    всплывающему уведомлению;
  - предупреждения о событиях вне логов (scheduler.py): Тайное лёгкое
    16:00, Остров Чеджу 17:00, ДСЛП каждые 6 часов.
Монитор лога живёт всё время работы бота: позиция чтения и антидубль-кэш
сохраняются между циклами; настройки (паттерны, метод принятия, триггеры)
перечитываются из settings.json каждые 5 секунд.
Сохранено из v5: check_mode ("log"/"template"/"both"), расписание из
settings.json, сценарий 1 (чат) → сценарий 2 (движение), повторные попытки,
логирование переходов между сценариями.
Использование автоматизации должно быть разрешено правилами твоего сервера.
"""

import time
import os
import json
import random
from datetime import datetime

import pytz
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw

import movement
import settings as settings_module

try:
    import notifier  # системные уведомления (опционально)
except Exception:
    notifier = None

try:
    import party_acceptor  # авто-принятие приглашений (опционально)
except Exception:
    party_acceptor = None

try:
    import scheduler as event_scheduler_module  # события VimeWorld вне логов
except Exception:
    event_scheduler_module = None

try:
    from party_checker import PartyChecker  # проверка группы через /p list
except Exception:
    PartyChecker = None

from log_monitor import DEFAULT_PATTERNS, LogMonitor, resolve_game_log_path


def notify_user(event: str, title: str, message: str):
    """Отправляет системное уведомление, если они включены. Никогда не роняет бота."""
    if notifier is None:
        return
    try:
        notifier.notify(title=title, message=message, event=event)
    except Exception:
        pass


#==================== НАСТРОЙКИ БОТА ====================
# Точное название окна Minecraft из его заголовка
MINECRAFT_WINDOW_TITLE = "Minecraft"

# Файлы сценариев
SCENARIO_CHAT_FILE = "scenario_chat.json"          # Сценарий 1
SCENARIO_MOVEMENT_FILE = "scenario_movement.json"  # Сценарий 2

# Файл-шаблон элемента интерфейса (резервный метод проверки / клика)
TEMPLATE_FILE = "template.png"
CONFIDENCE_THRESHOLD = 0.8

# Файл лога
LOG_FILE = "bot_log.txt"

# Повторные попытки для Сценария 2
MAX_RETRIES = 2
RETRY_DELAY_RANGE = (3, 5)

# Паузы между действиями сценария движения
MIN_ACTION_DELAY = 0.05
ACTION_DELAY_RANGE = (0.05, 0.3)

# Ожидание после отправки сообщения в чат (Сценарий 1), сек
CHAT_WAIT_SECONDS = 60

# Ожидание появления элемента/триггера после шагов Сценария 2, сек
WAIT_AFTER_MOVEMENT = 3.0
#==========================================================

_no_path_warned = False


def get_moscow_time():
    """Возвращает текущее время в часовом поясе Москвы, независимо от системного времени."""
    tz_moscow = pytz.timezone("Europe/Moscow")
    return datetime.now(tz_moscow)


def log_event(message: str):
    """Добавляет запись с таймстампом (МСК) в лог-файл. Формат не менялся с v1–v4."""
    timestamp = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S МСК")
    line = f"[{timestamp}] {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"[log] {line.strip()}")


def load_scenario(path):
    """
    Загружает сценарий из указанного файла.
    Возвращает словарь {"chat_fallback_message": str, "steps": [...]}.
    Если файла нет — возвращает пустой сценарий и предупреждает в консоли.
    """
    if not os.path.exists(path):
        print(f"[-] Файл сценария '{path}' не найден! Создай его через app.py. Шаги выполняться не будут.")
        return {"chat_fallback_message": "", "steps": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def random_action_delay():
    """Случайная пауза между действиями сценария движения, не меньше 50 мс."""
    low, high = ACTION_DELAY_RANGE
    low = max(low, MIN_ACTION_DELAY)
    return random.uniform(low, high)


def focus_minecraft_window():
    """Находит окно игры, разворачивает его и возвращает его координаты и размер."""
    try:
        windows = gw.getWindowsWithTitle(MINECRAFT_WINDOW_TITLE)
        if not windows:
            print(f"[-] Окно с заголовком '{MINECRAFT_WINDOW_TITLE}' не найдено!")
            return None
        win = windows[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(1)  # время на анимацию фокуса окна
        return win.left, win.top, win.width, win.height
    except Exception as e:
        print(f"[-] Ошибка при поиске окна: {e}")
        return None


def check_interface_element():
    """
    Делает скриншот и ищет шаблон элемента интерфейса через OpenCV.
    Возвращает кортеж (найден: bool, точность_совпадения: float).
    """
    if not os.path.exists(TEMPLATE_FILE):
        print(f"[-] Файл шаблона '{TEMPLATE_FILE}' не найден! Проверка отменена.")
        return False, 0.0
    screenshot = pyautogui.screenshot()
    screenshot_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    template = cv2.imread(TEMPLATE_FILE, cv2.IMREAD_COLOR)
    if template is None:
        print(f"[-] Не удалось прочитать файл шаблона '{TEMPLATE_FILE}' (повреждён или не изображение).")
        return False, 0.0
    result = cv2.matchTemplate(screenshot_np, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    print(f"[*] Точность совпадения с шаблоном: {max_val:.2f} (требуется: {CONFIDENCE_THRESHOLD})")
    return max_val >= CONFIDENCE_THRESHOLD, max_val


def execute_scenario_steps(steps, win_x, win_y):
    """
    Выполняет шаги сценария строго последовательно:
    key_hold — зажать/отпустить клавишу; mouse_click — клик по координатам
    (относительно левого верхнего угла окна игры). Между КАЖДОЙ парой
    действий — случайная пауза не менее 50 мс.
    """
    for i, step in enumerate(steps, 1):
        step_type = step.get("type")
        if step_type == "key_hold":
            key_name = step["key"]
            duration_ms = step["duration_ms"]
            print(f"[+] Шаг {i}: удержание клавиши '{key_name}' — {duration_ms} мс")
            movement.key_hold(key_name, duration_ms)
        elif step_type == "mouse_click":
            abs_x = win_x + step["x"]
            abs_y = win_y + step["y"]
            pyautogui.moveTo(abs_x, abs_y, duration=random.uniform(0.2, 0.5))
            pyautogui.click()
            print(f"[+] Шаг {i}: клик в точку ({abs_x}, {abs_y})")
        else:
            print(f"[-] Неизвестный тип шага '{step_type}', пропуск.")
            continue
        if i < len(steps):
            time.sleep(random_action_delay())

def _wait_trigger_pumping(monitor, timeout: float, acceptor=None, poll_interval: float = 0.4):
    """
    То же, что monitor.wait_for_trigger, но между опросами обрабатывает
    очередь авто-принятия. Безопасно: в этот момент бот не жмёт клавиши.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        for event in monitor.poll_events():
            if event.type == "trigger":
                return event
        if acceptor is not None and acceptor.enabled:
            acceptor.process()
        now = time.monotonic()
        if now >= deadline:
            return None
        time.sleep(min(poll_interval, deadline - now))
def verify_success(check_mode: str, monitor, wait_seconds: float, acceptor=None):
    """
    Единая проверка успеха после шагов сценария. В зависимости от
    check_mode ("log"/"template"/"both") ждёт триггер в игровом логе
    и/или проверяет OpenCV-шаблон.
    Возвращает (found: bool, method: str, detail: str).
    """
    global _no_path_warned
    use_log = check_mode in ("log", "both")
    use_template = check_mode in ("template", "both")

    if use_log and monitor is None:
        if not _no_path_warned:
            print("[!] Выбран метод 'лог', но монитор не создан (проверь путь к latest.log в настройках).")
            _no_path_warned = True
        if not use_template:
            return False, "none", "монитор лога не создан"
        use_log = False  # падаем на шаблон ниже

    if use_log:
        print(f"[*] Ожидание триггера из лога (до {wait_seconds:.0f} сек, режим '{check_mode}')...")
        event = _wait_trigger_pumping(monitor, wait_seconds, acceptor)  # ← было wait_for_trigger
        if event is not None:
            print(f"[+] Найден триггер: {event.describe()}")
            return True, "log", event.describe()
        if not use_template:
            return False, "log", f"триггеры не появились в логе за {wait_seconds:.0f} сек"
        print("[!] Триггер в логе не найден, проверяю шаблон как резерв...")
    else:
        monitored_sleep(wait_seconds, monitor, acceptor)  # ← было time.sleep(wait_seconds)

    found, confidence = check_interface_element()
    return found, "template", f"точность {confidence:.2f}"

def run_party_search_cycle(current_settings, monitor, acceptor, checker):
    """СЦЕНАРИЙ 1 (v7): цикл сообщений с проверкой /p list после каждого."""
    import message_scheduler

    messages = current_settings.get("party_search_messages", [])
    if not messages:
        return False

    repeat_count = current_settings.get("message_repeat_count", 2)
    max_messages = current_settings.get("max_search_messages", 6)
    interval = current_settings.get("message_interval", {"min": 30, "max": 40})

    scheduler = message_scheduler.MessageScheduler(messages, repeat_count)
    messages_sent = 0

    # возможно, уже в группе
    if checker and checker.is_in_party():
        return True

    notify_user("on_party_search_start", "Поиск группы", "Начинаю цикл сообщений.")

    while messages_sent < max_messages:
        message = scheduler.next_message()
        if message is None:
            break

        movement.send_chat_message(message)
        messages_sent += 1
        log_event(f"ПОИСК: сообщение {messages_sent}/{max_messages}: '{message}'")

        # пауза + мониторинг работает
        if messages_sent < max_messages:
            delay = random.uniform(interval["min"], interval["max"])
            monitored_sleep(delay, monitor, acceptor)
        else:
            monitored_sleep(5.0, monitor, acceptor)

        # проверка: приняли ли приглашение во время ожидания? (главный сигнал)
        if acceptor and acceptor.pop_accepted():
            log_event("ПОИСК: приглашение принято — бот в группе, останавливаю поиск.")
            return True

        # проверка после КАЖДОГО сообщения
        if checker and checker.is_in_party():
            log_event("ПОИСК: группа найдена (/p list).")
            return True

    return False


def monitored_sleep(seconds, monitor, acceptor):
    """Ожидание с обработкой очереди приглашений."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if monitor: monitor.poll()
        if acceptor and acceptor.enabled: acceptor.process()
        time.sleep(0.5)


def run_scenario_2_movement(win_x, win_y, check_mode: str, monitor):
    """
    СЦЕНАРИЙ 2 (движение): шаги из scenario_movement.json, затем проверка
    успеха (лог/шаблон/оба). При неудаче повторяет весь сценарий до
    MAX_RETRIES дополнительных раз. Возвращает (found, method, detail).
    """
    scenario = load_scenario(SCENARIO_MOVEMENT_FILE)
    steps = scenario.get("steps", [])
    if not steps:
        print(f"[-] Сценарий 2 пуст ('{SCENARIO_MOVEMENT_FILE}') — нечего выполнять.")
        return False, "none", "пустой сценарий"

    found = False
    method, detail = "none", ""
    total_attempts = 1 + MAX_RETRIES
    for attempt in range(1, total_attempts + 1):
        print(f"[*] Сценарий 2, попытка {attempt}/{total_attempts}")
        execute_scenario_steps(steps, win_x, win_y)
        print("[*] Ожидание элемента интерфейса / триггера из лога...")
        found, method, detail = verify_success(check_mode, monitor, WAIT_AFTER_MOVEMENT)
        if found:
            break
        if attempt < total_attempts:
            delay = random.uniform(*RETRY_DELAY_RANGE)
            print(f"[!] Не найдено ({method}: {detail}), повтор через {delay:.1f} сек...")
            time.sleep(delay)
    return found, method, detail


def execute_macro(current_settings=None, monitor=None, acceptor=None, checker=None):
    """
    Один цикл автоматизации:
    1. Найти окно Minecraft.
    2. Сценарий 1 — цикл сообщений для поиска группы (проверка /p list после каждого).
    3. Если группа не найдена — Сценарий 2 (движение).
    4. Залогировать переходы и итог.
    """
    print(f"\n[+] [{get_moscow_time().strftime('%H:%M:%S')}] Запуск цикла автоматизации...")
    if current_settings is None:
        current_settings = settings_module.load_settings()

    check_mode = str(current_settings.get("check_mode", "both")).strip().lower()
    if check_mode not in settings_module.VALID_CHECK_MODES:
        print(f"[!] Неизвестный check_mode '{check_mode}', использую 'both'.")
        check_mode = "both"

    window_data = focus_minecraft_window()
    if not window_data:
        log_event("ПРОПУСК: окно Minecraft не найдено.")
        return
    win_x, win_y, _, _ = window_data
    print(f"[+] Окно найдено в координатах: X={win_x}, Y={win_y}")

    # --- Сценарий 1: цикл сообщений для поиска группы ---
    party_found = run_party_search_cycle(current_settings, monitor, acceptor, checker)
    if party_found:
        log_event("УСПЕХ (Поиск группы): группа найдена.")
        notify_user("on_scenario_success", "Успех: Поиск группы", "Группа найдена через чат.")
        return

    # --- Переход к Сценарию 2 (обязательная отдельная строка в логе) ---
    log_event("Группа не найдена → запуск Сценарий 2 (движение).")
    print("[*] Группа не найдена. Автоматический переход к Сценарий 2 (движение).")

    # --- Сценарий 2 ---
    found, method, detail = run_scenario_2_movement(win_x, win_y, check_mode, monitor)
    if found:
        print(f"[🎉] УСПЕХ: метод '{method}' — {detail}")
        log_event(f"УСПЕХ (Сценарий 2, движение): метод '{method}' — {detail}.")
        notify_user("on_scenario_success", "Успех: Сценарий 2",
                    "Элемент интерфейса найден после сценария движения.")
    else:
        print("[❌] Успех не достигнут ни Сценарием 1, ни Сценарием 2.")
        log_event(
            f"ФИНАЛЬНАЯ НЕУДАЧА: успех не достигнут ни Сценарием 1, ни Сценарием 2 "
            f"(последняя проверка — {method}: {detail}). Цикл завершён без успеха."
        )
        notify_user("on_scenario_failure", "Сценарии не удались",
                    "Элемент не найден ни Сценарием 1, ни Сценарием 2.")


# ==================== КОНВЕЙЕР СОБЫТИЙ ЛОГА (v7) ====================

def _resolved_log_path(current_settings):
    """Путь к логу: сначала новый ключ (лог-монитор), затем старый (обратная совместимость)."""
    lm = current_settings.get("log_monitor", {}) or {}
    return resolve_game_log_path(lm.get("path", "") or current_settings.get("game_log_path", ""))


def _merged_patterns(current_settings):
    """Паттерны из настроек, дополненные значениями по умолчанию."""
    patterns = dict(DEFAULT_PATTERNS)
    patterns.update((current_settings.get("log_monitor", {}) or {}).get("patterns", {}) or {})
    return patterns


def _on_dungeon_open(event):
    """Обработчик открытия подземелья: запись в лог + системное уведомление."""
    lm = settings_module.load_settings().get("log_monitor", {}) or {}
    if not lm.get("enabled", True) or not (lm.get("events", {}) or {}).get("dungeons", True):
        return
    names = {"dungeon_easy": "Лёгкое", "dungeon_medium": "Среднее", "dungeon_hard": "Сложное"}
    title = f"Открыто подземелье: {names.get(event.type, '')}"
    print(f"[+] {title}")
    log_event(f"СОБЫТИЕ: {title}.")
    notify_user("on_dungeon_open", title, "Подземелье открыто — пора выдвигаться!")


def _on_wild_raid(event):
    """Обработчик открытия дикого рейда: запись в лог + системное уведомление."""
    lm = settings_module.load_settings().get("log_monitor", {}) or {}
    if not lm.get("enabled", True) or not (lm.get("events", {}) or {}).get("wild_raid", True):
        return
    location = (event.data or {}).get("location", "неизвестная локация")
    title = f"Дикий рейд открыт: {location}"
    print(f"[+] {title}")
    log_event(f"СОБЫТИЕ: {title}.")
    notify_user("on_raid_open", title, "Дикий рейд ждёт группу.")


def _party_guard(handler):
    """Обёртка: события группы обрабатываются, только если включены в настройках."""
    def wrapped(event):
        lm = settings_module.load_settings().get("log_monitor", {}) or {}
        if not lm.get("enabled", True):
            return
        if not (lm.get("events", {}) or {}).get("party_invite", True):
            return
        handler(event)
    return wrapped


def attach_event_pipeline(monitor, current_settings, checker=None):
    """
    Подключает к монитору авто-принятие группы и обработчики подземелий/
    рейдов, создаёт планировщик событий вне логов.
    Возвращает (acceptor, event_scheduler) — любой из них может быть None.
    """
    acceptor = None
    if party_acceptor is not None:
        pa = current_settings.get("party_acceptor", {}) or {}
        acceptor = party_acceptor.PartyAcceptor(
            enabled=bool(pa.get("enabled", True)),
            method=pa.get("method", "log_chat"),
            timeout_seconds=int(pa.get("timeout_seconds", 60)),
            queue_enabled=bool(pa.get("queue_enabled", True)),
            focus_window=focus_minecraft_window,
            log=lambda msg: print(f"[party] {msg}"),
            notify=notify_user,
            monitor=monitor,  # НОВОЕ
            own_nickname=str(pa.get("own_nickname", "")),  # НОВОЕ
            party_checker=checker,   # <-- checker для подтверждения

        )
        monitor.on("party_invite", _party_guard(acceptor.on_party_invite))
        monitor.on("party_join_command", _party_guard(acceptor.on_party_join_command))
    for dungeon_type in ("dungeon_easy", "dungeon_medium", "dungeon_hard"):
        monitor.on(dungeon_type, _on_dungeon_open)
    monitor.on("wild_raid", _on_wild_raid)

    event_scheduler = None
    if event_scheduler_module is not None:
        sch = current_settings.get("scheduler", {}) or {}
        event_scheduler = event_scheduler_module.EventScheduler(
            warn_minutes=int(sch.get("warn_minutes_before", 1)),
            enabled_events=sch.get("events", None),
        )
    return acceptor, event_scheduler


def sync_monitor(monitor, current_settings):
    """
    Создаёт (однократно) или обновляет монитор игрового лога: путь,
    строки-триггеры (проверка успеха) и regex-паттерны (события).
    Монитор живёт всё время работы бота: позиция в файле и антидубль-кэш
    сохраняются между циклами.
    """
    global _no_path_warned
    path = _resolved_log_path(current_settings)
    triggers = current_settings.get("log_triggers", [])
    patterns = _merged_patterns(current_settings)
    if monitor is None:
        if not path:
            if not _no_path_warned:
                print("[!] Путь к логу игры не удалось определить — мониторинг лога недоступен.")
                _no_path_warned = True
            return None
        monitor = LogMonitor(path, triggers, patterns=patterns)
        print(f"[*] Монитор лога создан: {path}; триггеров: {len(monitor.triggers)}")
        return monitor
    monitor.update_config(path, triggers, patterns=patterns)
    return monitor


def main():
    print("[*] Скрипт запущен. Расписание читается из settings.json при каждом запуске.")
    last_triggered_key = [None]
    monitor = None
    acceptor = None
    checker = None
    event_scheduler = None
    pipeline_attached = False
    while True:
        current_settings = settings_module.load_settings()
        monitor = sync_monitor(monitor, current_settings)
        if monitor is not None and not pipeline_attached:
            # checker для проверки группы через /p list — создаём ДО конвейера
            checker = None
            if PartyChecker is not None:
                try:
                    checker = PartyChecker(monitor)
                except Exception as e:
                    print(f"[!] PartyChecker недоступен: {e}")
                    checker = None
            # ИСПРАВЛЕНО: передаём checker третьим аргументом,
            # иначе acceptor.party_checker == None и подтверждение /p list не работает
            acceptor, event_scheduler = attach_event_pipeline(
                monitor, current_settings, checker
            )
            pipeline_attached = True
            print("[*] Конвейер событий подключен: приглашения, подземелья, рейды, события расписания.")

        # настройки авто-принятия и планировщика обновляются на лету
        if acceptor is not None:
            pa = current_settings.get("party_acceptor", {}) or {}
            acceptor.update_config(
                enabled=pa.get("enabled", True),
                method=pa.get("method", "log_chat"),
                timeout_seconds=pa.get("timeout_seconds", 60),
                queue_enabled=pa.get("queue_enabled", True),
            )
        if event_scheduler is not None:
            sch = current_settings.get("scheduler", {}) or {}
            event_scheduler.update_config(
                warn_minutes=sch.get("warn_minutes_before", 1),
                enabled_events=sch.get("events", None),
            )

        schedule = current_settings.get("schedule", {"mode": "fixed_minute", "value": 30})
        now = get_moscow_time()
        if settings_module.should_trigger_now(now, schedule, last_triggered_key):
            notify_user("on_schedule_event", "Расписание сработало", "Запускаю цикл автоматизации.")
            execute_macro(current_settings, monitor, acceptor, checker)
            now = get_moscow_time()  # ИСПРАВЛЕНО (мелочь №1): макро длится минуты,
            # без обновления now планировщик событий опрашивался бы устаревшей минутой

        # события игрового лога (приглашения, подземелья, рейды) + антидубль
        if monitor is not None:
            monitor.poll()
        # авто-принятие приглашений из очереди
        if acceptor is not None and acceptor.enabled:
            acceptor.process()
        # события вне логов: Тайное лёгкое, Остров Чеджу, ДСЛП
        if event_scheduler is not None and (current_settings.get("scheduler", {}) or {}).get("enabled", True):
            for item in event_scheduler.poll(now):
                msg = f"{item['name']} — событие в {item['time_str']} МСК"
                log_event(f"РАСПИСАНИЕ: {msg}")
                notify_user("on_schedule_event", item["name"], msg)

        time.sleep(5)  # защита от перегрузки процессора


if __name__ == "__main__":
    main()