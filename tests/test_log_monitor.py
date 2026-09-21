"""
tests/test_log_monitor.py — тесты модуля мониторинга игрового лога (v5).
Запуск как обычно: pytest tests/ (conftest.py подставляет заглушку
pygetwindow на Linux, здесь она не требуется).
"""

import os
import threading
import time

from log_monitor import (
    DedupCache,
    LogMonitor,
    default_game_log_path,
    parse_log_line,
    resolve_game_log_path,
)


def _append(path, text: str):
    with open(str(path), "a", encoding="utf-8") as f:
        f.write(text)


# ---------- разбор строк ----------

def test_parse_line_with_timestamp():
    ts, body = parse_log_line("[12:34:56] группа найдена")
    assert ts == "12:34:56"
    assert body == "группа найдена"


def test_parse_line_without_timestamp():
    ts, body = parse_log_line("просто строка без времени")
    assert ts is None
    assert body == "просто строка без времени"


# ---------- чтение только новых строк ----------

def test_old_content_is_skipped(tmp_path):
    log = tmp_path / "latest.log"
    _append(log, "[10:00:00] старая строка\n")
    monitor = LogMonitor(str(log), ["старая строка"])
    # Всё, что было в файле до старта монитора, не обрабатывается
    assert monitor.poll_events() == []


def test_new_lines_are_read(tmp_path):
    log = tmp_path / "latest.log"
    _append(log, "[10:00:00] привет\n")
    monitor = LogMonitor(str(log), ["триггер"])
    monitor.poll_events()
    _append(log, "[10:00:01] появился триггер\n")
    events = monitor.poll_events()
    assert len(events) == 1
    assert events[0].timestamp == "10:00:01"
    assert events[0].first_trigger == "триггер"


def test_partial_line_waits_for_newline(tmp_path):
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), ["триггер"])
    monitor.poll_events()
    _append(log, "[10:00:02] триг")       # строка ещё не завершена (\n нет)
    assert monitor.poll_events() == []
    _append(log, "гер появился\n")
    events = monitor.poll_events()
    assert len(events) == 1
    assert "триггер появился" in events[0].text


# ---------- ротация файла ----------

def test_rotation_truncation_resets_position(tmp_path):
    log = tmp_path / "latest.log"
    _append(log, "[10:00:00] аaaaaaa\n" * 5)
    monitor = LogMonitor(str(log), ["новое событие"])
    monitor.poll_events()  # позиция в конце файла
    # Файл "пересоздан" с меньшим содержимым
    with open(str(log), "w", encoding="utf-8") as f:
        f.write("[10:05:00] новое событие\n")
    events = monitor.poll_events()
    assert len(events) == 1
    assert events[0].text == "новое событие"


def test_dedup_prevents_reprocessing_after_rotation(tmp_path):
    """Антидубль: после ротации уже обработанная строка не срабатывает повторно."""
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), ["рейд"])
    monitor.poll_events()  # базовая линия: файла ещё нет
    _append(log, "[10:00:00] рейд начался\n")
    _append(log, "[10:00:01] строка-заполнитель, чтобы файл был длиннее\n")
    events1 = monitor.poll_events()
    assert len(events1) == 1
    # Ротация: файл пересоздан короче, но старое событие в нём осталось
    with open(str(log), "w", encoding="utf-8") as f:
        f.write("[10:00:00] рейд начался\n")
    events2 = monitor.poll_events()
    assert events2 == []  # размер меньше позиции → перечитали с нуля → дедуп подавил


# ---------- антидубль (юнит) ----------

def test_dedup_cache_eviction():
    cache = DedupCache(maxlen=2)
    assert cache.is_new("a") is True
    assert cache.is_new("a") is False
    assert cache.is_new("b") is True
    assert cache.is_new("c") is True   # вытесняет "a"
    assert cache.is_new("a") is True   # "a" снова считается новым


# ---------- триггеры ----------

def test_trigger_match_is_case_insensitive(tmp_path):
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), ["Группа Найдена"])
    _append(log, "[10:00:00] ГРУППА НАЙДЕНА для игрока X\n")
    events = monitor.poll_events()
    assert len(events) == 1
    assert events[0].matched == ["Группа Найдена"]


def test_update_config_path_change(tmp_path):
    log1 = tmp_path / "a.log"
    log2 = tmp_path / "b.log"
    _append(log1, "[10:00:00] старьё\n")
    _append(log2, "[10:00:00] целевой маркер\n")
    monitor = LogMonitor(str(log1), ["маркер"])
    monitor.poll_events()
    monitor.update_config(str(log2), ["маркер"])
    # После смены пути старое содержимое нового файла пропускается
    assert monitor.poll_events() == []
    _append(log2, "[10:00:01] целевой маркер\n")
    assert len(monitor.poll_events()) == 1


# ---------- блокирующее ожидание ----------

def test_wait_for_trigger_timeout(tmp_path):
    log = tmp_path / "latest.log"
    _append(log, "")
    monitor = LogMonitor(str(log), ["x"])
    start = time.monotonic()
    assert monitor.wait_for_trigger(0.3, poll_interval=0.05) is None
    assert time.monotonic() - start < 2.0


def test_wait_for_trigger_finds_new_event(tmp_path):
    log = tmp_path / "latest.log"
    _append(log, "[10:00:00] старт\n")
    monitor = LogMonitor(str(log), ["найдена"])

    def writer():
        time.sleep(0.2)
        _append(log, "[10:00:05] группа найдена\n")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    event = monitor.wait_for_trigger(5.0, poll_interval=0.05)
    thread.join(timeout=2)
    assert event is not None
    assert event.first_trigger == "найдена"


# ---------- пути ----------

def test_resolve_game_log_path_uses_configured():
    assert resolve_game_log_path("C:/games/latest.log") == "C:/games/latest.log"


def test_default_path_shape():
    path = default_game_log_path()
    if path:  # на Windows, где APPDATA задан
        expected = os.path.join(".vimeworld", "minigames_new_anticheat", "logs", "latest.log")
        assert path.endswith(expected)