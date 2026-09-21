"""tests/test_notifier.py — фильтрация уведомлений по настройкам (без реального показа)."""
import json

import notifier
import settings as settings_module


def test_notify_respects_master_switch(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"notifications": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", str(path))
    # выключен общий рубильник — уведомление не отправляется (и не падает)
    assert notifier.notify("t", "m") is False


def test_notify_respects_event_switch(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"notifications": {"enabled": True, "on_bot_start": False}}),
                    encoding="utf-8")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", str(path))
    assert notifier.notify("t", "m", event="on_bot_start") is False