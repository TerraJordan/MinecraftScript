"""
settings.py — единое хранилище настроек проекта (settings.json).
Все ключи имеют дефолты: старый settings.json загружается без ошибок
(отсутствующие ключи дополняются, пользовательские сохраняются).
"""
import json
import os

SETTINGS_FILE = "settings.json"

VALID_CHECK_MODES = ("log", "template", "both")
VALID_ACCEPT_METHODS = ("log_chat", "opencv", "chat_click")

DEFAULT_SETTINGS = {
    "hotkey": "<ctrl>+<alt>+s",
    "schedule": {"mode": "fixed_minute", "value": 30},
    # --- v5: проверка успеха сценариев ---
    "check_mode": "both",
    "game_log_path": "",
    "log_triggers": ["группа найдена"],
    # --- v7: цикл сообщений поиска группы ---
    "party_search_messages": [
        "Ищу пачку на КП S+",
        "Киньте приглос на КП S+",
        "Дайте инвайт в пачку на КП S+",
    ],
    "message_repeat_count": 2,
    "message_interval": {"min": 30, "max": 40},
    "max_search_messages": 6,
    "auto_accept_party": True,
    "party_accept_method": "log_chat",
    "log_monitoring_enabled": True,
    "log_file_path": "%APPDATA%\\.vimeworld\\minigames_new_anticheat\\logs\\latest.log",
    # --- v7: мониторинг лога ---
    "log_monitor": {
        "enabled": True,
        "path": "",
        "patterns": {
            "party_invite": r"Игрок (?P<player>\S+) приглашает вас в свою группу",
            "party_join_command": r"/party join (?P<player>\S+)",
            "party_list_response_no": r"Вы не состоите в группе",
            "party_list_response_yes": r"Игроки \(\d+\):",
            "dungeon_easy": r"Открыто Легкое подземелье",
            "dungeon_medium": r"Открыто Среднее подземелье",
            "dungeon_hard": r"Открыто Сложное подземелье",
            "wild_raid": r"Открыт Дикий Рейд на локации (?P<location>.+?)\s*$",
        },
        "events": {"party_invite": True, "dungeons": True, "wild_raid": True},
    },
    # --- v7: авто-принятие ---
    "party_acceptor": {
        "enabled": True,
        "method": "log_chat",
        "timeout_seconds": 60,
        "queue_enabled": True,
        "own_nickname": "",
    },
    # --- v7: события вне логов ---
    "scheduler": {
        "enabled": True,
        "warn_minutes_before": 1,
        "events": {"secret_easy": True, "jeju": True, "dslp": True},
    },
    # --- уведомления (ключи = notifier.EVENT_LABELS) ---
    "notifications": {
        "enabled": True,
        "on_party_invite": True,
        "on_party_accept": True,
        "on_party_search_start": True,
        "on_dungeon_open": True,
        "on_raid_open": True,
        "on_bot_start": True,
        "on_bot_stop": True,
        "on_scenario_success": True,
        "on_scenario_failure": True,
        "on_diagnostics": True,
        "on_schedule_event": True,
    },
    "window": {"geometry": ""},
}


def _deep_merge(defaults: dict, data: dict) -> dict:
    merged = {}
    for key, default_value in defaults.items():
        if key not in data:
            merged[key] = json.loads(json.dumps(default_value))
        elif isinstance(default_value, dict) and isinstance(data.get(key), dict):
            merged[key] = _deep_merge(default_value, data[key])
        else:
            merged[key] = data[key]
    for key, value in data.items():
        if key not in merged:
            merged[key] = value
    return merged


def _to_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def load_settings() -> dict:
    """Загружает settings.json; при отсутствии/повреждении — дефолты (не падает)."""
    if not os.path.exists(SETTINGS_FILE):
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("settings.json: ожидается объект")
        merged = _deep_merge(DEFAULT_SETTINGS, data)
        for key in ("schedule", "message_interval", "log_monitor",
                    "party_acceptor", "scheduler", "notifications", "window"):
            if not isinstance(merged.get(key), dict):
                merged[key] = json.loads(json.dumps(DEFAULT_SETTINGS[key]))
        # нормализация скаляров/списков
        if merged.get("check_mode") not in VALID_CHECK_MODES:
            merged["check_mode"] = DEFAULT_SETTINGS["check_mode"]
        if not isinstance(merged.get("log_triggers"), list):
            merged["log_triggers"] = list(DEFAULT_SETTINGS["log_triggers"])
        msgs = merged.get("party_search_messages")
        if not isinstance(msgs, list) or not [m for m in msgs if str(m).strip()]:
            merged["party_search_messages"] = list(DEFAULT_SETTINGS["party_search_messages"])
        else:
            merged["party_search_messages"] = [str(m) for m in msgs if str(m).strip()]
        merged["message_repeat_count"] = _to_int(merged.get("message_repeat_count"), 2, 1, 10)
        merged["max_search_messages"] = _to_int(merged.get("max_search_messages"), 6, 1, 50)
        if merged.get("party_accept_method") not in VALID_ACCEPT_METHODS:
            merged["party_accept_method"] = DEFAULT_SETTINGS["party_accept_method"]
        if not isinstance(merged.get("game_log_path"), str):
            merged["game_log_path"] = ""
        if not isinstance(merged.get("log_file_path"), str):
            merged["log_file_path"] = DEFAULT_SETTINGS["log_file_path"]
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def should_trigger_now(now_dt, schedule: dict, last_triggered_key: list):
    """
    Нужно ли запускать макро-цикл в момент now_dt (Europe/Moscow).
    Режимы: fixed_minute / every_n_minutes; защита от двойного срабатывания
    внутри одной минуты.
    """
    mode = schedule.get("mode", "fixed_minute")
    value = int(schedule.get("value", 30))
    if mode == "every_n_minutes":
        value = max(1, value)
        is_trigger_minute = (now_dt.minute % value) == 0
    else:
        value = value % 60
        is_trigger_minute = now_dt.minute == value
    trigger_key = (now_dt.hour, now_dt.minute)
    if is_trigger_minute:
        if last_triggered_key[0] != trigger_key:
            last_triggered_key[0] = trigger_key
            return True
        return False
    last_triggered_key[0] = None
    return False