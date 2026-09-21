"""
party_acceptor.py — автоматическое принятие приглашений в группу на VimeWorld.
Три метода (выбираются сегментированным переключателем в GUI):
  log_chat   — ОСНОВНОЙ: команда /party join {игрок} извлекается из лога
               (событие party_join_command) и отправляется в игровой чат;
  opencv     — РЕЗЕРВНЫЙ: клик по всплывающему уведомлению через template.png;
  chat_click — экспериментальный: клик по сообщению в чате (ненадёжен).
Несколько приглашений подряд: первое обрабатывается, остальные ждут в
очереди (с уведомлением). Приглашение действует 60 секунд — просроченные
отбрасываются. При неудаче — до MAX_ATTEMPTS попыток, пока не истёк таймаут.
Флаг pop_accepted() используется циклом поиска группы (bot.py) как сигнал
«бот вступил в группу — поиск можно останавливать».
Все зависимости инжектятся в конструкторе — модуль тестируется без pynput/cv2.
"""
import os
import random
import time
from collections import deque

TEMPLATE_FILE = "template.png"
CONFIDENCE_THRESHOLD = 0.8
ACCEPT_COOLDOWN_SECONDS = 1.5   # пауза между принятиями разных приглашений
MAX_ATTEMPTS = 3                # максимум попыток принять одно приглашение
VALID_METHODS = ("log_chat", "opencv", "chat_click")


def click_template_notification(template_file: str = TEMPLATE_FILE) -> bool:
    """Резервный метод: ищет уведомление по шаблону (OpenCV) и кликает по центру."""
    try:
        import cv2
        import numpy as np
        import pyautogui
    except Exception as e:
        print(f"[party] OpenCV-метод недоступен: {e}")
        return False
    if not os.path.exists(template_file):
        print(f"[party] Файл шаблона '{template_file}' не найден.")
        return False
    try:
        screenshot = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
        template = cv2.imread(template_file, cv2.IMREAD_COLOR)
        if template is None:
            return False
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < CONFIDENCE_THRESHOLD:
            print(f"[party] Уведомление не найдено (точность {max_val:.2f}).")
            return False
        th, tw = template.shape[:2]
        pyautogui.click(max_loc[0] + tw // 2, max_loc[1] + th // 2)
        return True
    except Exception as e:
        print(f"[party] Ошибка OpenCV-клика: {e}")
        return False


def _default_send_command(command: str):
    """Основной метод: отправка команды в игровой чат (печатаем и жмём Enter)."""
    import movement
    movement.send_chat_message(command)


def _default_chat_click(focus_window) -> bool:
    """Экспериментальный метод: клик по последней строке чата (ненадёжен)."""
    try:
        import pyautogui
        coords = focus_window() if callable(focus_window) else None
        if not coords:
            return False
        win_x, win_y, _w, win_h = coords
        pyautogui.click(win_x + 12, win_y + win_h - 60)
        return True
    except Exception as e:
        print(f"[party] Ошибка клика по чату: {e}")
        return False


class InviteJob:
    """Одно приглашение в очереди на принятие."""
    __slots__ = ("player", "command", "method", "received_at", "attempts")

    def __init__(self, player: str, method: str, command: str = ""):
        self.player = player
        self.command = command
        self.method = method
        self.received_at = time.monotonic()
        self.attempts = 0


class PartyAcceptor:
    """
    Очередь приглашений и их принятие выбранным методом.
    События приходят коллбэками от LogMonitor; обработка — process() в цикле бота.
    """

    def __init__(self, method: str = "log_chat", timeout_seconds: int = 60,
                 queue_enabled: bool = True, enabled: bool = True,
                 send_command=None, focus_window=None, opencv_click=None,
                 log=print, notify=None, monitor=None, own_nickname: str = "",
                 party_checker=None, on_failure=None):
        self.method = method if method in VALID_METHODS else "log_chat"
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.queue_enabled = bool(queue_enabled)
        self.enabled = bool(enabled)
        self.send_command = send_command or _default_send_command
        self.focus_window = focus_window
        self.opencv_click = opencv_click or click_template_notification
        self.log = log
        self.notify = notify                      # callable(event_key, title, message)
        self.monitor = monitor                    # LogMonitor (опционально)
        self.own_nickname = own_nickname or ""    # ник бота (для подтверждений)
        self.party_checker = party_checker        # PartyChecker для /p list
        self.on_failure = on_failure              # опционально: callable(job, reason)
        self.queue = deque()
        self._last_accept_at = 0.0
        self._just_accepted = False               # флаг для цикла поиска группы
        # Защита от собственных команд: бот не реагирует на команды, которые сам отправил
        self.confirmation_delay = (0.8, 1.5)      # пауза перед проверкой группы через /p list
        self._recent_sent = deque()               # недавно отправленные команды
        self._recent_sent_ttl = 15.0              # время жизни записей в секундах

    def update_config(self, enabled=None, method=None, timeout_seconds=None,
                      queue_enabled=None, own_nickname=None, party_checker=None):
        """Обновление настроек на лету (вызывается из цикла бота)."""
        if enabled is not None:
            self.enabled = bool(enabled)
        if method in VALID_METHODS:
            self.method = method
        if timeout_seconds is not None:
            self.timeout_seconds = max(5, int(timeout_seconds))
        if queue_enabled is not None:
            self.queue_enabled = bool(queue_enabled)
        if own_nickname is not None:
            self.own_nickname = str(own_nickname)
        if party_checker is not None:
            self.party_checker = party_checker

    def pop_accepted(self) -> bool:
        """True, если с прошлого вызова приглашение было принято; сбрасывает флаг."""
        val = self._just_accepted
        self._just_accepted = False
        return val

    # ---------- события из лога (коллбэки для LogMonitor) ----------

    def on_party_invite(self, event):
        """Приглашение в группу. Для opencv/chat_click — сразу в очередь."""
        player = (event.data or {}).get("player", "неизвестный игрок")
        self.log(f"Приглашение в группу от: {player}")
        if self.notify:
            self.notify("on_party_invite", "Приглашение в группу",
                        f"{player} приглашает вас в группу (60 сек на ответ).")
        if self.method in ("opencv", "chat_click"):
            self._enqueue(InviteJob(player=player, method=self.method))

    def on_party_join_command(self, event):
        """Строка с командой принятия. Для метода log_chat — в очередь."""
        if self.method != "log_chat":
            return
        data = event.data or {}
        player = data.get("player", "")
        command = data.get("command") or (f"/party join {player}" if player else "")
        if not command:
            self.log("Не удалось извлечь команду /party join из лога.")
            return
        # Игнорируем команды, которые бот недавно отправил сам
        if self._was_recently_sent(command):
            self.log(f"[i] Пропуск собственной команды из лога: {command}")
            return
        self._enqueue(InviteJob(player=player or "неизвестный",
                                method="log_chat", command=command))

    def _enqueue(self, job: InviteJob):
        """Ставит приглашение в очередь; несколько подряд → очередь с уведомлением."""
        if not self.queue_enabled and self.queue:
            self.log(f"Очередь выключена: приглашение от {job.player} отклонено (уже есть активное).")
            if self.on_failure:
                self.on_failure(job, "queue_disabled")
            return
        self.queue.append(job)
        if len(self.queue) > 1:
            self.log(f"Приглашение от {job.player} добавлено в очередь (в очереди: {len(self.queue)}).")
            if self.notify:
                self.notify("on_party_invite", "Очередь приглашений",
                            f"Приглашение от {job.player} ожидает в очереди.")

    # ---------- обработка очереди ----------

    def process(self):
        """Вычищает просроченные, принимает первое в очереди с паузой и повторами."""
        if not self.enabled:
            return
        self._cleanup_recent_sent()
        now = time.monotonic()
        # вычищаем просроченные (приглашение действует 60 секунд)
        while self.queue and now - self.queue[0].received_at > self.timeout_seconds:
            expired = self.queue.popleft()
            self.log(f"Приглашение от {expired.player} просрочено "
                     f"({self.timeout_seconds} с) — не принято.")
            if self.on_failure:
                self.on_failure(expired, "expired")
        if not self.queue:
            return
        if now - self._last_accept_at < ACCEPT_COOLDOWN_SECONDS:
            return
        job = self.queue.popleft()
        self._last_accept_at = now
        # если уже в группе — приглашение не нужно
        if self.party_checker is not None:
            try:
                if self.party_checker.is_in_party():
                    self.log(f"[i] Уже в группе — пропуск приглашения от {job.player}.")
                    return
            except Exception as e:
                self.log(f"[!] Ошибка проверки группы: {e}")
        # фокус на окно игры перед действием
        if callable(self.focus_window):
            try:
                self.focus_window()
            except Exception as e:
                self.log(f"Не удалось сфокусировать окно игры: {e}")
        ok = self._try_accept(job)
        job.attempts += 1
        if ok:
            self._just_accepted = True
            self.log(f"Группа принята: {job.player} (метод: {job.method}, попытка {job.attempts}).")
            if self.notify:
                self.notify("on_party_accept", "Группа принята",
                            f"Приглашение от {job.player} принято.")
            return
        # неудача: повторяем, пока есть попытки и не истёк таймаут
        if job.attempts < MAX_ATTEMPTS and now - job.received_at <= self.timeout_seconds:
            self.queue.appendleft(job)
            self.log(f"Попытка {job.attempts}/{MAX_ATTEMPTS} не удалась — возвращаю в очередь.")
        else:
            self.log(f"Не удалось принять приглашение от {job.player} (попыток: {job.attempts}).")
            if self.on_failure:
                self.on_failure(job, "max_attempts")

    def _try_accept(self, job: InviteJob) -> bool:
        """Одна попытка принятия выбранным методом."""
        try:
            if job.method == "log_chat" and job.command:
                self.send_command(job.command)
                # Запоминаем отправленную команду для защиты от повторного срабатывания
                now = time.monotonic()
                self._recent_sent.append((now, job.command.lower().strip()))
                return True
            if job.method == "opencv":
                return bool(self.opencv_click())
            if job.method == "chat_click":
                return _default_chat_click(self.focus_window)
        except Exception as e:
            self.log(f"Ошибка метода '{job.method}': {e}")
        return False

    def _cleanup_recent_sent(self):
        """Удаляет устаревшие записи о недавно отправленных командах."""
        now = time.monotonic()
        while self._recent_sent and now - self._recent_sent[0][0] > self._recent_sent_ttl:
            self._recent_sent.popleft()

    def _was_recently_sent(self, command: str) -> bool:
        """Проверяет, отправлял ли бот эту команду в последние _recent_sent_ttl секунд."""
        cmd_lower = command.lower().strip()
        now = time.monotonic()
        for sent_at, sent_cmd in self._recent_sent:
            if now - sent_at <= self._recent_sent_ttl and sent_cmd == cmd_lower:
                return True
        return False