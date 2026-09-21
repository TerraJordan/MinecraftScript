"""
tests/test_scenario_selection.py — логика выбора между Сценарием 1
(цикл сообщений поиска группы) и Сценарием 2 (движение).
Актуальное API (v7): execute_macro(current_settings, monitor, acceptor, checker);
Сценарий 1 = run_party_search_cycle(...). Проверки мокаются — игра не запускается.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot


def test_execute_macro_stops_after_party_found(tmp_path, monkeypatch):
    """Если группа найдена в цикле сообщений — Сценарий 2 не запускается."""
    monkeypatch.chdir(tmp_path)
    with patch.object(bot, "focus_minecraft_window", return_value=(0, 0, 800, 600)), \
         patch.object(bot, "run_party_search_cycle", return_value=True) as search_mock, \
         patch.object(bot, "run_scenario_2_movement") as movement_mock, \
         patch.object(bot, "log_event") as log_mock, \
         patch.object(bot, "notify_user"):
        bot.execute_macro()
    search_mock.assert_called_once()
    movement_mock.assert_not_called()
    assert any("Поиск группы" in c.args[0] for c in log_mock.call_args_list)


def test_execute_macro_falls_back_to_scenario_2(tmp_path, monkeypatch):
    """Если группа не найдена — автоматически запускается Сценарий 2."""
    monkeypatch.chdir(tmp_path)
    with patch.object(bot, "focus_minecraft_window", return_value=(0, 0, 800, 600)), \
         patch.object(bot, "run_party_search_cycle", return_value=False), \
         patch.object(bot, "run_scenario_2_movement",
                      return_value=(True, "template", "точность 0.90")) as movement_mock, \
         patch.object(bot, "log_event") as log_mock, \
         patch.object(bot, "notify_user"):
        bot.execute_macro()
    movement_mock.assert_called_once()
    assert any("→" in c.args[0] and "Сценарий 2" in c.args[0] for c in log_mock.call_args_list)
    assert any("УСПЕХ (Сценарий 2" in c.args[0] for c in log_mock.call_args_list)


def test_execute_macro_logs_final_failure(tmp_path, monkeypatch):
    """Если ни цикл сообщений, ни Сценарий 2 не дали успеха — финальная неудача."""
    monkeypatch.chdir(tmp_path)
    with patch.object(bot, "focus_minecraft_window", return_value=(0, 0, 800, 600)), \
         patch.object(bot, "run_party_search_cycle", return_value=False), \
         patch.object(bot, "run_scenario_2_movement",
                      return_value=(False, "template", "точность 0.20")), \
         patch.object(bot, "log_event") as log_mock, \
         patch.object(bot, "notify_user"):
        bot.execute_macro()
    assert any("ФИНАЛЬНАЯ НЕУДАЧА" in c.args[0] for c in log_mock.call_args_list)


def test_execute_macro_skips_if_window_not_found(tmp_path, monkeypatch):
    """Если окно Minecraft не найдено — ни один сценарий не запускается."""
    monkeypatch.chdir(tmp_path)
    with patch.object(bot, "focus_minecraft_window", return_value=None), \
         patch.object(bot, "run_party_search_cycle") as search_mock, \
         patch.object(bot, "run_scenario_2_movement") as movement_mock, \
         patch.object(bot, "log_event") as log_mock, \
         patch.object(bot, "notify_user"):
        bot.execute_macro()
    search_mock.assert_not_called()
    movement_mock.assert_not_called()
    assert any("окно minecraft не найдено" in c.args[0].lower() for c in log_mock.call_args_list)