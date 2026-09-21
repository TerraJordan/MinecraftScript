"""tests/test_log_monitor_patterns.py — regex-паттерны и коллбэки (события)."""

from log_monitor import DEFAULT_PATTERNS, LogMonitor


def _append(path, text: str):
    with open(str(path), "a", encoding="utf-8") as f:
        f.write(text)


def test_party_invite_and_join_command_extract_player(tmp_path):
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), [], patterns=DEFAULT_PATTERNS)
    monitor.poll()
    _append(log, "[10:00:02] [Client thread/INFO]: [CHAT] Группа > Игрок Steve приглашает вас в свою группу. У вас есть 60 секунд на ответ\n")
    _append(log, "[10:00:02] [Client thread/INFO]: [CHAT] Группа > Для принятия приглашения напишите: /party join Steve\n")
    events = monitor.poll()
    types = [e.type for e in events]
    assert "party_invite" in types and "party_join_command" in types
    invite = next(e for e in events if e.type == "party_invite")
    assert invite.data["player"] == "Steve"
    join = next(e for e in events if e.type == "party_join_command")
    assert join.data["player"] == "Steve"


def test_dungeons_and_raid_recognized(tmp_path):
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), [], patterns=DEFAULT_PATTERNS)
    monitor.poll()
    _append(log, "[10:01:00] [CHAT] <Информация> Открыто Сложное подземелье\n")
    _append(log, "[10:02:00] [CHAT] <Информация> Открыто Среднее подземелье\n")
    _append(log, "[10:03:00] [CHAT] <Информация> Открыто Легкое подземелье\n")
    _append(log, "[10:04:00] [CHAT] <Информация> Открыт Дикий Рейд на локации Пустыня Миражей\n")
    events = monitor.poll()
    assert [e.type for e in events] == ["dungeon_hard", "dungeon_medium", "dungeon_easy", "wild_raid"]
    assert events[-1].data["location"] == "Пустыня Миражей"


def test_callbacks_fire_and_errors_isolated(tmp_path):
    """Падение одного обработчика не мешает остальным."""
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), [], patterns={"raid": r"Дикий Рейд"})
    calls = []

    def bad_handler(event):
        raise RuntimeError("обработчик упал")

    monitor.on("raid", bad_handler)
    monitor.on("raid", lambda event: calls.append(event))
    monitor.poll()
    _append(log, "[10:05:00] [CHAT] Открыт Дикий Рейд на локации Горы\n")
    monitor.poll()
    assert len(calls) == 1


def test_same_event_not_dispatched_twice_after_rotation(tmp_path):
    """Антидубль: после ротации обработчик не вызывается повторно."""
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), [], patterns={"dungeon_easy": r"Открыто Легкое подземелье"})
    calls = []
    monitor.on("dungeon_easy", lambda event: calls.append(event))
    _append(log, "[10:00:00] [CHAT] Открыто Легкое подземелье\n")
    _append(log, "[10:00:01] [CHAT] строка-заполнитель подлиннее, чтобы файл был длиннее\n")
    monitor.poll()
    assert len(calls) == 1
    with open(str(log), "w", encoding="utf-8") as f:
        f.write("[10:00:00] [CHAT] Открыто Легкое подземелье\n")
    monitor.poll()
    assert len(calls) == 1


def test_triggers_and_patterns_coexist(tmp_path):
    """Триггеры успеха и паттерны событий работают одновременно."""
    log = tmp_path / "latest.log"
    monitor = LogMonitor(str(log), ["группа найдена"], patterns=DEFAULT_PATTERNS)
    monitor.poll()
    _append(log, "[10:00:05] [CHAT] группа найдена, телепорт через 5 секунд\n")
    events = monitor.poll()
    assert len(events) == 1
    assert events[0].first_trigger == "группа найдена"