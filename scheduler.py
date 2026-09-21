"""
scheduler.py — расписание событий VimeWorld.

События, которые появляются в логах (подземелья, дикие рейды),
уведомляются ТОЛЬКО при фактическом обнаружении в логе (см.
log_monitor.py) — расписание для них показано в GUI как справка.

События, которых в логах нет, предупреждаются по расписанию за N минут:
  - Тайное лёгкое подземелье — ежедневно в 16:00 МСК;
  - Остров Чеджу — ежедневно в 17:00 МСК;
  - ДСЛП — каждые 6 часов от 00:00 (при предупреждении за 1 минуту:
    23:59, 05:59, 11:59, 17:59).

Время — Europe/Moscow (datetime передаётся вызывающей стороной).
"""

import pytz
from datetime import datetime, timedelta

MOSCOW = pytz.timezone("Europe/Moscow")

# Справочник для вкладки «Расписание»: (название, периодичность, источник)
SCHEDULE_INFO = [
    ("Дикий рейд", "каждые 20 минут", "из лога"),
    ("Лёгкое подземелье", "в :00 и :30", "из лога"),
    ("Среднее подземелье", "в :15 и :45", "из лога"),
    ("Сложное подземелье", "в :10 и :40", "из лога"),
    ("Тайное лёгкое", "ежедневно в 16:00 МСК", "по расписанию"),
    ("Остров Чеджу", "ежедневно в 17:00 МСК", "по расписанию"),
    ("ДСЛП", "каждые 6 часов от 00:00", "по расписанию"),
]

# События вне логов: ключ → название и времена (часы, минуты)
TIMED_EVENTS = {
    "secret_easy": {"name": "Тайное лёгкое подземелье", "times": [(16, 0)]},
    "jeju": {"name": "Остров Чеджу", "times": [(17, 0)]},
    "dslp": {"name": "ДСЛП", "times": [(0, 0), (6, 0), (12, 0), (18, 0)]},
}

def _to_moscow(dt):
    """Нормализует datetime к Europe/Moscow (принимает naive и aware)."""
    if dt.tzinfo is None:
        return MOSCOW.localize(dt)
    return dt.astimezone(MOSCOW)

class EventScheduler:
    """
    Генерирует предупреждения о событиях вне логов.
    Вызывать в цикле: for item in scheduler.poll(now_moscow): уведомить.
    Повторное срабатывание в ту же минуту защищено множеством _fired.
    """

    def __init__(self, warn_minutes: int = 1, enabled_events: dict = None):
        self.warn_minutes = max(0, int(warn_minutes))
        self.enabled_events = dict(enabled_events) if enabled_events else {
            key: True for key in TIMED_EVENTS
        }
        self._fired = set()

    def update_config(self, warn_minutes=None, enabled_events=None):
        """Обновление настроек на лету."""
        if warn_minutes is not None:
            self.warn_minutes = max(0, int(warn_minutes))
        if enabled_events is not None:
            self.enabled_events = dict(enabled_events)

    def poll(self, now_dt: datetime) -> list:
        """
        Возвращает события, о которых нужно предупредить прямо сейчас:
        [{"key": ..., "name": ..., "time_str": "ЧЧ:ММ"}, ...]
        Базы проверяются за сегодня и завтра — так ловится 23:59 для
        события в 00:00.
        """
        now_dt = _to_moscow(now_dt)
        alerts = []
        now_hm = (now_dt.hour, now_dt.minute)
        today = now_dt.date()
        for key, meta in TIMED_EVENTS.items():
            if not self.enabled_events.get(key, True):
                continue
            for base_h, base_m in meta["times"]:
                for day in (today, today + timedelta(days=1)):
                    base_dt = datetime(day.year, day.month, day.day, base_h, base_m)
                    alert_dt = base_dt - timedelta(minutes=self.warn_minutes)
                    if alert_dt.date() != today or (alert_dt.hour, alert_dt.minute) != now_hm:
                        continue
                    fire_key = (key, alert_dt.strftime("%Y-%m-%d %H:%M"))
                    if fire_key in self._fired:
                        continue
                    self._fired.add(fire_key)
                    alerts.append({
                        "key": key,
                        "name": meta["name"],
                        "time_str": f"{base_h:02d}:{base_m:02d}",
                    })
        if len(self._fired) > 500:
            self._fired.clear()
        return alerts