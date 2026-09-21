"""
party_checker.py — проверка наличия группы через команду /p list.

Отправляет /p list в игровой чат и ждёт ответ сервера в игровом логе
(через log_monitor.py):
  - "Вы не состоите в группе"  → группы нет  (False);
  - список игроков группы      → группа есть (True).
Если ответ не пришёл за таймаут (3–5 сек) — считается, что группы нет
(безопаснее продолжить поиск, чем пропустить цикл).
"""

import log_monitor


def _default_send_plist():
    """Отправляет команду /p list в игровой чат."""
    import movement
    movement.send_chat_message("/p list")


class PartyChecker:
    """Проверка группы: /p list + парсинг ответа из лога."""

    RESPONSE_TYPES = (log_monitor.EVENT_PARTY_LIST_NO, log_monitor.EVENT_PARTY_LIST_YES)

    def __init__(self, monitor, send_command=None, timeout: float = 4.0, log=print):
        self.monitor = monitor
        self.send_command = send_command or _default_send_plist
        self.timeout = max(1.0, float(timeout))
        self.log = log

    def is_in_party(self) -> bool:
        """
        Возвращает True, если игрок состоит в группе.
        Отправляет /p list и ждёт ответ из лога до timeout секунд.
        """
        try:
            self.send_command()
        except Exception as e:
            self.log(f"Не удалось отправить /p list: {e}")
            return False
        event = self.monitor.wait_for(
            lambda e: e.type in self.RESPONSE_TYPES,
            timeout=self.timeout,
        )
        if event is None:
            self.log(f"Ответ на /p list не получен за {self.timeout:.0f} с — считаю, что группы нет.")
            return False
        return event.type == log_monitor.EVENT_PARTY_LIST_YES

    def is_in_party_with(self, nickname: str) -> bool:
        """
        True, если игрок в группе И ник найден в списке участников.
        Список приходит строкой вида "Игроки (3): ник1, ник2, ник3",
        поэтому достаточно вхождения ника в текст ответа.
        """
        try:
            self.send_command()
        except Exception as e:
            self.log(f"Не удалось отправить /p list: {e}")
            return False
        event = self.monitor.wait_for(
            lambda e: e.type in self.RESPONSE_TYPES,
            timeout=self.timeout,
        )
        if event is None:
            self.log(f"Ответ на /p list не получен за {self.timeout:.0f} с.")
            return False
        if event.type == log_monitor.EVENT_PARTY_LIST_NO:
            return False
        # в группе — проверяем, что наш ник есть в списке
        if nickname and nickname not in event.text:
            self.log(f"В группе есть кто-то, но ника '{nickname}' в списке нет.")
            return False
        return True