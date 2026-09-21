"""
notifier.py — системные уведомления Windows через plyer с безопасным фолбэком.
Если plyer не установлен или платформа не поддерживает уведомления —
модуль не падает: сообщение печатается в консоль (запись в bot_log.txt
делает вызывающая сторона через log_event).
Настройки: settings.json → ключ "notifications". Все ключи имеют дефолты,
старый файл настроек читается.
"""
import time
import settings as settings_module

APP_NAME = "Minecraft Bot"

MIN_INTERVAL_SECONDS = 5.0
_last_notified = {}

# Ключи событий и подписи (используются на вкладке «Уведомления»)
EVENT_LABELS = {
    "on_party_invite": "Приглашение в группу",
    "on_party_accept": "Принятие группы",
    "on_party_search_start": "Начало поиска группы",
    "on_dungeon_open": "Открытие подземелья",
    "on_raid_open": "Открытие дикого рейда",
    "on_bot_start": "Запуск бота",
    "on_bot_stop": "Остановка бота",
    "on_scenario_success": "Успех сценария",
    "on_scenario_failure": "Неудача сценария",
    "on_diagnostics": "Результат диагностики",
    "on_schedule_event": "Событие расписания",
    "on_party_accepted": "Пати принято",
    "on_dungeon_easy": "Лёгкое подземелье открыто",
    "on_dungeon_medium": "Среднее подземелье открыто",
    "on_dungeon_hard": "Сложное подземелье открыто",
    "on_wild_raid": "Дикий рейд "
}

def _rate_limit(event, force):
    if force or event is None:
        return True
    now = time.monotonic()
    last = _last_notified.get(event, 0.0)
    if now - last < MIN_INTERVAL_SECONDS:
        return False
    _last_notified[event] = now
    return True

def _settings_allow(event) -> bool:
    """Проверяет по settings.json, разрешено ли уведомление для события."""
    try:
        notif = settings_module.load_settings().get("notifications", {})
    except Exception:
        return True
    if not notif.get("enabled", True):
        return False
    if event and not notif.get(event, True):
        return False
    return True


def notify(title: str, message: str, event: str = None, force: bool = False) -> bool:
    """
    Отправляет системное уведомление. Возвращает True, если уведомление
    реально показано системой.
    event — ключ события из settings["notifications"] (или None).
    force=True — игнорировать настройки (кнопка «Тест» в GUI).
    При любой ошибке — тихий фолбэк в консоль, без исключений наружу.
    """

    if not force and not _settings_allow(event):
        return False
    if not _rate_limit(event, force):
        return False  # подавлено rate-limiter'ом
    try:
        from plyer import notification
        notification.notify(
            title=title[:64],
            message=message[:256],
            app_name=APP_NAME,
            timeout=5,
        )
        return True
    except Exception as e:
        print(f"[notifier] Системное уведомление недоступно ({e.__class__.__name__}): {title} — {message}")
        return False