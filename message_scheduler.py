"""
message_scheduler.py — цикл сообщений в чат для поиска группы.

Список сообщений (по умолчанию 3) задаётся в settings.json. Каждое
сообщение отправляется repeat_count раз подряд (по умолчанию 2), затем
случайный переход к другому из оставшихся — так сообщения не повторяются
по кругу и снижается риск мута за одинаковые сообщения (мут выдаётся
за 2+ одинаковых подряд).

Пример цикла при 3 сообщениях и repeat_count=2:
  A A → B B → C C   (порядок блоков A/B/C случайный), итого 6 отправлений.
"""

import random

DEFAULT_MESSAGES = [
    "Ищу пачку на КП S+",
    "Киньте приглос на КП S+",
    "Дайте инвайт в пачку на КП S+",
]


class MessageScheduler:
    """Генератор последовательности сообщений: каждое × repeat_count, случайный порядок блоков."""

    def __init__(self, messages=None, repeat_count: int = 2):
        source = messages if messages else DEFAULT_MESSAGES
        self.messages = [str(m) for m in source if str(m).strip()]
        self.repeat_count = max(1, int(repeat_count))
        self.reset()

    def reset(self):
        """Сбрасывает цикл: пул оставшихся сообщений перемешивается заново."""
        self._remaining = list(self.messages)
        random.shuffle(self._remaining)
        self._current = None
        self._sent_current = 0

    def next_message(self):
        """
        Возвращает следующее сообщение для отправки: текущее повторяется
        repeat_count раз подряд, затем случайный выбор из оставшихся
        (исключая только что отправлявшееся). Возвращает None, если
        цикл исчерпан (все сообщения отправлены по repeat_count раз).
        """
        if self._current is None or self._sent_current >= self.repeat_count:
            pool = [m for m in self._remaining if m != self._current]
            if not pool:
                return None
            self._current = random.choice(pool)
            self._remaining.remove(self._current)
            self._sent_current = 0
        self._sent_current += 1
        return self._current