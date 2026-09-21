"""tests/test_scheduler.py — расписание событий вне логов."""

from datetime import datetime

from scheduler import EventScheduler


def test_secret_easy_alert_one_minute_before():
    sched = EventScheduler(warn_minutes=1)
    assert sched.poll(datetime(2024, 1, 1, 15, 59))            # за минуту до 16:00
    assert not sched.poll(datetime(2024, 1, 1, 16, 0))         # в сам момент не дублируем


def test_dslp_alerts_2359_for_midnight():
    sched = EventScheduler(warn_minutes=1)
    alerts = sched.poll(datetime(2024, 1, 1, 23, 59))
    assert any(a["key"] == "dslp" for a in alerts)


def test_no_repeat_same_minute():
    sched = EventScheduler(warn_minutes=1)
    assert sched.poll(datetime(2024, 1, 1, 16, 59))            # Чеджу в 17:00
    assert not sched.poll(datetime(2024, 1, 1, 16, 59))        # повтор в ту же минуту


def test_disabled_events_skipped():
    sched = EventScheduler(warn_minutes=1,
                           enabled_events={"secret_easy": False, "jeju": True, "dslp": True})
    alerts = sched.poll(datetime(2024, 1, 1, 15, 59))
    assert not any(a["key"] == "secret_easy" for a in alerts)


def test_warn_zero_alerts_at_event_time():
    sched = EventScheduler(warn_minutes=0)
    assert any(a["key"] == "jeju" for a in sched.poll(datetime(2024, 1, 1, 17, 0)))