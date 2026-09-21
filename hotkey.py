"""
hotkey.py — глобальная горячая клавиша старта/остановки бота.

ВАЖНО, чем это отличается от кейлоггера: этот модуль использует
pynput.keyboard.GlobalHotKeys, который умеет реагировать ТОЛЬКО на одну
заранее заданную комбинацию клавиш. Он не сохраняет, не логирует и никуда
не передаёт остальные нажатия — все клавиши, не совпавшие с комбинацией,
просто игнорируются на уровне библиотеки. Это тот же механизм, что
используется в множестве обычных приложений (пуш-ту-токе, скриншотерах,
менеджерах хоткеев) и качественно отличается от фонового перехвата всего
ввода, который мы сознательно не реализовывали в recorder.py.

Также этот модуль используется для записи новой комбинации: пользователь
нажимает кнопку "Назначить" в GUI, после чего слушатель фиксирует ОДНО
следующее сочетание клавиш (тоже не более того) и сразу останавливается.
"""

from pynput import keyboard


def normalize_hotkey_string(hotkey_str: str) -> str:
    """
    Проверяет, что строка комбинации клавиш понятна pynput.GlobalHotKeys,
    и возвращает её же (или бросает ValueError с понятным сообщением).
    """
    try:
        keyboard.HotKey.parse(hotkey_str)
    except Exception as e:
        raise ValueError(f"Некорректная комбинация клавиш '{hotkey_str}': {e}")
    return hotkey_str


class HotkeyListener:
    """
    Обёртка над pynput.GlobalHotKeys для запуска callback при нажатии
    заданной комбинации. Слушает ТОЛЬКО эту комбинацию — остальной ввод
    не сохраняется и не обрабатывается.
    """

    def __init__(self, hotkey_str: str, on_trigger):
        self.hotkey_str = hotkey_str
        self.on_trigger = on_trigger
        self._listener = None

    def start(self):
        self.stop()
        self._listener = keyboard.GlobalHotKeys({self.hotkey_str: self.on_trigger})
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class SingleComboCapture:
    """
    Разовый захват ОДНОГО следующего сочетания клавиш — используется для
    интерфейса "нажми комбинацию — она запишется" при назначении хоткея.
    Как только пользователь отпускает клавиши после нажатия — слушатель
    останавливается сам и передаёт готовую строку комбинации в callback.
    Никакие клавиши, введённые после захвата, не фиксируются.
    """

    def __init__(self, on_captured):
        self.on_captured = on_captured
        self._pressed = set()
        self._listener = None

    def _key_to_str(self, key):
        if hasattr(key, "char") and key.char is not None:
            return key.char.lower()
        # Специальные клавиши pynput вида Key.ctrl_l -> "<ctrl>"
        name = str(key).replace("Key.", "")
        for base in ("ctrl", "alt", "shift", "cmd"):
            if name.startswith(base):
                return f"<{base}>"
        return f"<{name}>"

    def _on_press(self, key):
        self._pressed.add(self._key_to_str(key))

    def _on_release(self, key):
        if self._pressed:
            combo = "+".join(sorted(self._pressed))
            self.stop()
            self.on_captured(combo)

    def start(self):
        self._pressed = set()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
