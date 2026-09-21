"""
tests/test_scenarios.py — тесты парсинга и валидации файлов сценариев.
Не требуют запущенной игры.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from diagnostics import _validate_scenario_dict


def test_valid_movement_scenario_passes():
    data = {
        "chat_fallback_message": "hello",
        "steps": [
            {"type": "key_hold", "key": "w", "duration_ms": 1000},
            {"type": "mouse_click", "x": 200, "y": 300},
        ],
    }
    # не должно бросать исключение
    _validate_scenario_dict(data)


def test_valid_chat_scenario_with_empty_steps_passes():
    data = {"chat_fallback_message": "lfg", "steps": []}
    _validate_scenario_dict(data)


def test_missing_steps_field_raises():
    with pytest.raises(ValueError):
        _validate_scenario_dict({"chat_fallback_message": "hi"})


def test_steps_not_a_list_raises():
    with pytest.raises(ValueError):
        _validate_scenario_dict({"steps": "not a list"})


def test_key_hold_missing_duration_raises():
    data = {"steps": [{"type": "key_hold", "key": "w"}]}
    with pytest.raises(ValueError):
        _validate_scenario_dict(data)


def test_mouse_click_missing_coordinates_raises():
    data = {"steps": [{"type": "mouse_click", "x": 10}]}
    with pytest.raises(ValueError):
        _validate_scenario_dict(data)


def test_unknown_step_type_raises():
    data = {"steps": [{"type": "teleport"}]}
    with pytest.raises(ValueError):
        _validate_scenario_dict(data)


@pytest.mark.parametrize(
    "filename",
    ["scenario_chat.json", "scenario_movement.json"],
)
def test_project_scenario_files_are_valid_json_and_schema(filename):
    """
    Реальные файлы сценариев проекта должны существовать, парситься и
    проходить валидацию схемы. Тест не трогает игру — только файлы.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(project_root, filename)
    assert os.path.exists(path), f"Файл {filename} должен существовать в проекте"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)  # бросит исключение, если JSON битый

    _validate_scenario_dict(data)
