"""
log_monitor.py — мониторинг игрового лога latest.log (режим "tail -f").

Возможности:
1. Читает ТОЛЬКО новые строки с последней проверенной позиции. Файл не
   держится открытым между вызовами — открывается на чтение при каждом
   опросе (безопасно на Windows, даже если игра удерживает файл).
2. Корректная ротация: если лог урезан/пересоздан (размер стал меньше
   прочитанной позиции или сменился inode) — позиция чтения сбрасывается.
3. Разбор строк вида "[ЧЧ:ММ:СС] [Client thread/INFO]: [CHAT] текст".
4. Два механизма распознавания:
   - строки-триггеры (подстроки, без учёта регистра) — проверка успеха
     сценариев (check_mode в bot.py);
   - настраиваемые regex-паттерны с именованными группами — события:
     приглашение в группу, команда принятия, подземелья трёх сложностей,
     дикий рейд. Паттерны редактируются в GUI и хранятся в settings.json.
5. Антидубль: хэши (таймстамп + строка) последних N событий в deque+set —
   одна и та же строка не вызывает повторной реакции (в т.ч. после ротации).
6. Callback-система: monitor.on("party_invite", handler); "*" — все события.
"""

import hashlib
import os
import re
import time
from collections import deque

# Сколько последних обработанных событий держать в антидубль-кэше
DEFAULT_DEDUP_SIZE = 500

# Подписи паттернов для вкладки «Мониторинг лога»
PATTERN_LABELS = {
    "party_invite": "Приглашение в группу",
    "party_join_command": "Команда принятия (/party join …)",
    "party_join_confirmation": "Вступление в группу (подтверждение)",
    "dungeon_easy": "Лёгкое подземелье",
    "dungeon_medium": "Среднее подземелье",
    "dungeon_hard": "Сложное подземелье",
    "wild_raid": "Дикий рейд",
}

# Паттерны по умолчанию (переопределяются в settings.json → log_monitor.patterns)
DEFAULT_PATTERNS = {
    "party_invite": r"Игрок (?P<player>\S+) приглашает вас в свою группу",
    "party_join_command": r"/party join (?P<player>\S+)",
    "party_list_response_no": r"Вы не состоите в группе", # ответ на /p list: нет группы / есть группа
    # ответ на /p list: в группе — "Игроки (N): ник1, ник2, ..."
    "party_list_response_yes": r"Игроки \(\d+\):",
    # подтверждение успешного вступления в группу (используется для подтверждения принятия)
    "party_join_confirmation": r"Игрок (?P<player>\S+) вступил в группу",
    "dungeon_easy": r"Открыто Легкое подземелье",
    "dungeon_medium": r"Открыто Среднее подземелье",
    "dungeon_hard": r"Открыто Сложное подземелье",
    "wild_raid": r"Открыт Дикий Рейд на локации (?P<location>.+?)\s*$",
}

# Ведущий таймстамп строки лога: [ЧЧ:ММ:СС]
_LINE_RE = re.compile(r"^\[(\d{1,2}:\d{2}:\d{2})\]\s*(.*)$")

# Типы событий для проверки группы через /p list
EVENT_PARTY_LIST_NO = "party_list_response_no"
EVENT_PARTY_LIST_YES = "party_list_response_yes"
EVENT_PARTY_JOIN_CONFIRMATION = "party_join_confirmation"

def default_game_log_path() -> str:
    """
    Путь к логу игры по умолчанию:
    %APPDATA%\\.vimeworld\\minigames_new_anticheat\\logs\\latest.log
    Если APPDATA определить нельзя (например, Linux в тестах) — пустая строка.
    """
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return ""
    return os.path.join(appdata, ".vimeworld", "minigames_new_anticheat", "logs", "latest.log")


def resolve_game_log_path(configured_path: str) -> str:
    """
    Возвращает путь к логу игры: если задан свой — используем его
    (с раскрытием ~ и %ПЕРЕМЕННЫХ%), иначе — путь по умолчанию.
    """
    configured_path = (configured_path or "").strip()
    if configured_path:
        return os.path.expandvars(os.path.expanduser(configured_path))
    return default_game_log_path()


def parse_log_line(raw_line: str):
    """
    Разбирает строку лога. Возвращает (timestamp, text):
      "[12:34:56] группа найдена" -> ("12:34:56", "группа найдена")
    Если ведущего таймстампа нет — (None, строка как есть).
    """
    match = _LINE_RE.match(raw_line)
    if match:
        return match.group(1), match.group(2)
    return None, raw_line


class DedupCache:
    """
    Антидубль: множество хэшей последних N обработанных событий.
    deque хранит порядок добавления (для вытеснения самых старых),
    set даёт быструю проверку "уже видели?".
    """

    def __init__(self, maxlen: int = DEFAULT_DEDUP_SIZE):
        self.maxlen = max(1, int(maxlen))
        self._order = deque()
        self._seen = set()

    def is_new(self, key: str) -> bool:
        """Возвращает True, если событие ещё не обрабатывалось, и запоминает его."""
        if key in self._seen:
            return False
        self._seen.add(key)
        self._order.append(key)
        while len(self._order) > self.maxlen:
            oldest = self._order.popleft()
            self._seen.discard(oldest)
        return True

    def clear(self):
        self._order.clear()
        self._seen.clear()

    def __len__(self):
        return len(self._order)


class LogEvent:
    """Событие лога: совпавший триггер или распознанный шаблон."""

    __slots__ = ("timestamp", "text", "matched", "type", "data")

    def __init__(self, timestamp, text, matched_triggers, event_type="trigger", data=None):
        self.timestamp = timestamp              # "ЧЧ:ММ:СС" или None
        self.text = text                        # текст строки лога (без таймстампа)
        self.matched = list(matched_triggers)   # совпавшие триггеры / тип паттерна
        self.type = event_type                  # тип события (ключ паттерна или "trigger")
        self.data = data or {}                  # именованные группы: player, location…

    @property
    def first_trigger(self) -> str:
        return self.matched[0] if self.matched else ""

    def describe(self) -> str:
        ts = f"[{self.timestamp}] " if self.timestamp else ""
        return f"{ts}триггер '{self.first_trigger}', строка: '{self.text}'"


class LogMonitor:
    """
    Инкрементальный читатель игрового лога с триггерами, паттернами
    и коллбэками.

    Использование:
        monitor = LogMonitor(path, ["группа найдена"], patterns=DEFAULT_PATTERNS)
        monitor.on("party_invite", handler)
        events = monitor.poll_events()          # неблокирующий опрос
        event = monitor.wait_for_trigger(60.0)  # блокирующее ожидание до 60 сек
    """

    def __init__(self, path: str, triggers=None, patterns=None, start_from_end: bool = True,
                 dedup_size: int = DEFAULT_DEDUP_SIZE, case_sensitive: bool = False):
        self.path = path or ""
        self.triggers = [str(t).strip() for t in (triggers or []) if str(t).strip()]
        self.case_sensitive = case_sensitive
        self._dedup = DedupCache(dedup_size)
        self._start_from_end = start_from_end
        self._compiled_patterns = {}
        self._handlers = {}
        if patterns:
            self.set_patterns(patterns)
        # Фиксируем стартовую позицию СРАЗУ, в конструкторе:
        # - файл УЖЕ существует → пропускаем его текущее содержимое (оно «старое»);
        # - файла ЕЩЁ НЕТ → позиция 0: когда файл появится, читаем его с начала,
        #   потому что всё в нём — новые события (игра стартовала после бота).
        st = self._stat()
        if st is not None:
            self._position = st.st_size if start_from_end else 0
            self._file_sig = (st.st_dev, st.st_ino) if st.st_ino else None
        else:
            self._position = 0
            self._file_sig = None

    # ---------- конфигурация ----------

    def set_patterns(self, patterns: dict):
        """Компилирует regex-паттерны; пустые и битые пропускаются с предупреждением."""
        compiled = {}
        for event_type, pattern in (patterns or {}).items():
            try:
                if pattern:
                    compiled[event_type] = re.compile(pattern)
            except re.error as e:
                print(f"[log_monitor] Битый паттерн '{event_type}' пропущен: {e}")
        self._compiled_patterns = compiled

    def update_config(self, path: str, triggers, patterns=None):
        """
        Обновляет путь/триггеры/паттерны на лету (bot.py перечитывает
        settings.json каждый цикл). Если путь изменился — позиция чтения
        сбрасывается, и новый файл читается с конца (при start_from_end=True).
        """
        new_path = path or ""
        path_changed = (
            os.path.normcase(os.path.normpath(new_path or "."))
            != os.path.normcase(os.path.normpath(self.path or "."))
        )
        self.triggers = [str(t).strip() for t in (triggers or []) if str(t).strip()]
        if patterns is not None:
            self.set_patterns(patterns)
        if path_changed:
            self.path = new_path
            self._position = None
            self._file_sig = None

    def on(self, event_type: str, callback):
        """Регистрирует обработчик события; '*' — для всех событий."""
        self._handlers.setdefault(event_type, []).append(callback)

    # ---------- сопоставление и антидубль ----------

    def _match_triggers(self, text: str):
        """Возвращает список строк-триггеров, найденных в тексте."""
        if not self.triggers or not text:
            return []
        haystack = text if self.case_sensitive else text.lower()
        matched = []
        for trigger in self.triggers:
            needle = trigger if self.case_sensitive else trigger.lower()
            if needle and needle in haystack:
                matched.append(trigger)
        return matched

    @staticmethod
    def _event_key(timestamp, raw_line: str) -> str:
        """Хэш события для антидубля: таймстамп + полная строка лога."""
        source = f"{timestamp or ''}|{raw_line}"
        return hashlib.sha1(source.encode("utf-8", errors="replace")).hexdigest()

    # ---------- чтение файла ----------

    def _stat(self):
        try:
            return os.stat(self.path)
        except OSError:
            return None

    def poll_lines(self):
        """
        Возвращает список новых ПОЛНЫХ строк с прошлого вызова —
        кортежи (timestamp, text, raw_line). Обрабатывает ротацию файла
        и незавершённую последнюю строку (без \\n строка пока не читается).
        """
        if not self.path:
            return []
        st = self._stat()
        if st is None:
            return []  # файла (пока) нет — молча ждём его появления

        # Детекция ротации по сигнатуре файла, если ОС даёт inode
        sig = (st.st_dev, st.st_ino) if st.st_ino else None
        if sig is not None and self._file_sig is not None and sig != self._file_sig:
            self._position = 0
        if sig is not None:
            self._file_sig = sig

        if self._position is None:
            # Первое подключение: старое содержимое пропускаем
            # (или читаем с начала — используется в тестах)
            self._position = st.st_size if self._start_from_end else 0

        if st.st_size < self._position:
            # Файл урезали/пересоздали — начинаем чтение с начала
            self._position = 0
        if st.st_size == self._position:
            return []

        try:
            with open(self.path, "rb") as f:
                f.seek(self._position)
                data = f.read()
        except OSError:
            return []

        # Читаем только полные строки: хвост без \n оставляем на следующий опрос
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n")
            if cut == -1:
                return []  # пока нет ни одной полной строки
            data = data[: cut + 1]
        if not data:
            return []

        self._position += len(data)

        lines = []
        for raw in data.split(b"\n"):
            if not raw:
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r")
            if not text.strip():
                continue
            timestamp, body = parse_log_line(text)
            lines.append((timestamp, body, text))
        return lines

    def poll_events(self):
        events = []
        for timestamp, body, raw in self.poll_lines():
            if not self._dedup.is_new(self._event_key(timestamp, raw)):
                continue

            # 1) сначала regex-паттерны
            matched_pattern = False
            for event_type, regex in self._compiled_patterns.items():
                match = regex.search(body)
                if match:
                    event = LogEvent(timestamp, body, [event_type],
                                     event_type=event_type, data=match.groupdict())
                    events.append(event)
                    self._dispatch(event)
                    matched_pattern = True
                    break  # одна строка = один паттерн

            # 2) триггеры — только если паттерн НЕ совпал
            if not matched_pattern:
                matched_triggers = self._match_triggers(body)
                if matched_triggers:
                    event = LogEvent(timestamp, body, matched_triggers, event_type="trigger")
                    events.append(event)
                    self._dispatch(event)
        return events

    # короткое имя для основного цикла бота
    poll = poll_events

    def _dispatch(self, event: LogEvent):
        """Вызывает обработчики события; ошибка обработчика не роняет мониторинг."""
        handlers = list(self._handlers.get(event.type, [])) + list(self._handlers.get("*", []))
        for callback in handlers:
            try:
                callback(event)
            except Exception as e:
                print(f"[log_monitor] Ошибка обработчика '{event.type}': {e}")

    def wait_for_trigger(self, timeout: float, poll_interval: float = 0.4, stop_flag=None):
        """
        Блокирующее ожидание: до timeout секунд опрашивает лог и возвращает
        первый найденный LogEvent либо None, если ничего не появилось.
        stop_flag — опциональный callable: если вернул True, ждём не до конца.

        v7 Ждёт ТОЛЬКО триггеры успеха (type=='trigger'), не другие события.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            events = self.poll_events()
            for event in events:
                if event.type == "trigger":  # ВАЖНО: только триггеры!
                    return event
            now = time.monotonic()
            if now >= deadline:
                return None
            if stop_flag is not None and stop_flag():
                return None
            time.sleep(min(poll_interval, deadline - now))

    def wait_for(self, predicate, timeout: float, poll_interval: float = 0.3):
        """
        Блокирующее ожидание события, удовлетворяющего предикату.
        В отличие от wait_for_trigger, подходит для ЛЮБЫХ событий (в т.ч. паттернов).
        Используется party_checker для ожидания ответа /p list.
        Возвращает первый подходящий LogEvent или None по таймауту.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            for event in self.poll_events():
                try:
                    if predicate(event):
                        return event
                except Exception:
                    pass
            now = time.monotonic()
            if now >= deadline:
                return None
            time.sleep(min(poll_interval, deadline - now))