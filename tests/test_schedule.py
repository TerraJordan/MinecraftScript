"""
tests/test_schedule.py — тесты расчёта времени срабатывания по Europe/Moscow
с учётом настраиваемого интервала (Задача 3). Не требуют запущенной игры.
"""

import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from settings import should_trigger_now

MOSCOW = pytz.timezone("Europe/Moscow")


def moscow_dt(hour, minute):
    return MOSCOW.localize(datetime(2026, 9, 19, hour, minute, 0))


def test_fixed_minute_triggers_on_exact_minute():
    schedule = {"mode": "fixed_minute", "value": 30}
    last = [None]
    assert should_trigger_now(moscow_dt(14, 30), schedule, last) is True


def test_fixed_minute_does_not_trigger_on_other_minutes():
    schedule = {"mode": "fixed_minute", "value": 30}
    last = [None]
    assert should_trigger_now(moscow_dt(14, 29), schedule, last) is False
    assert should_trigger_now(moscow_dt(14, 31), schedule, last) is False


def test_fixed_minute_does_not_double_trigger_within_same_minute():
    schedule = {"mode": "fixed_minute", "value": 30}
    last = [None]
    assert should_trigger_now(moscow_dt(14, 30), schedule, last) is True
    # Повторный вызов "в ту же минуту" не должен сработать снова
    assert should_trigger_now(moscow_dt(14, 30), schedule, last) is False


def test_fixed_minute_resets_after_leaving_trigger_minute():
    schedule = {"mode": "fixed_minute", "value": 30}
    last = [None]
    assert should_trigger_now(moscow_dt(14, 30), schedule, last) is True
    assert should_trigger_now(moscow_dt(14, 31), schedule, last) is False
    # На следующий час в ту же минуту должно сработать снова
    assert should_trigger_now(moscow_dt(15, 30), schedule, last) is True


def test_every_n_minutes_triggers_on_multiples():
    schedule = {"mode": "every_n_minutes", "value": 15}
    last = [None]
    assert should_trigger_now(moscow_dt(10, 0), schedule, last) is True
    assert should_trigger_now(moscow_dt(10, 15), schedule, last) is True
    assert should_trigger_now(moscow_dt(10, 45), schedule, last) is True


def test_every_n_minutes_does_not_trigger_between_multiples():
    schedule = {"mode": "every_n_minutes", "value": 15}
    last = [None]
    assert should_trigger_now(moscow_dt(10, 7), schedule, last) is False
    assert should_trigger_now(moscow_dt(10, 44), schedule, last) is False


def test_every_n_minutes_handles_value_of_one():
    # value=1 означает "каждую минуту" — граничный случай
    schedule = {"mode": "every_n_minutes", "value": 1}
    last = [None]
    assert should_trigger_now(moscow_dt(10, 0), schedule, last) is True
    assert should_trigger_now(moscow_dt(10, 1), schedule, last) is True
