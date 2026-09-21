"""
movement.py — модуль эмуляции клавиатуры для точного передвижения.

Используется библиотека pynput (а не pyautogui.keyDown/keyUp).
Почему pynput, а не pyautogui для клавиш:
  - pynput даёт более точный и предсказуемый keyDown/keyUp без встроенных
    задержек pyautogui (у pyautogui между вызовами есть свой internal
    PAUSE, который сложно тонко контролировать при удержании клавиши
    ровно N миллисекунд).
  - pynput отдельно управляет мышью и клавиатурой, что удобно, так как
    клики (mouse_click) в проекте уже реализованы через pyautogui в v1 —
    их не трогаем, а клавиатуру выделяем в отдельный контролируемый модуль.
Клики мышью (mouse_click) как и в v1 остаются на pyautogui — это
согласованное разделение ответственности, а не смешение двух библиотек
без причины.
"""

import time
from pynput.keyboard import Controller, Key

_keyboard = Controller()

# Сопоставление читаемых имён клавиш (используются в scenario.json и в GUI)
# со значениями pynput. Буквы и цифры передаются как обычные строки и
# отдельного маппинга не требуют.
_SPECIAL_KEYS = {
    "space": Key.space,
    "shift": Key.shift,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "enter": Key.enter,
    "esc": Key.esc,
    "tab": Key.tab,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
}


def _resolve_key(key_name: str):
    """Преобразует строковое имя клавиши в объект, понятный pynput."""
    key_name = key_name.strip().lower()
    if key_name in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key_name]
    if len(key_name) == 1:
        return key_name
    raise ValueError(
        f"Неизвестная клавиша: '{key_name}'. "
        f"Поддерживаются одиночные символы (w, a, s, d, 1...9) "
        f"и специальные: {', '.join(_SPECIAL_KEYS.keys())}"
    )


def key_hold(key_name: str, duration_ms: int):
    """
    Зажимает одну клавишу на duration_ms миллисекунд, затем отпускает.
    Шаг полностью последователен: функция не возвращает управление,
    пока клавиша не будет отпущена.
    """
    key = _resolve_key(key_name)
    duration_s = duration_ms / 1000.0

    _keyboard.press(key)
    try:
        time.sleep(duration_s)
    finally:
        # finally гарантирует отпускание клавиши, даже если во время
        # удержания произойдёт исключение — чтобы клавиша не "залипла"
        _keyboard.release(key)


def type_text(text: str, char_delay_range=(0.02, 0.06)):
    """
    Печатает текст посимвольно с небольшой случайной задержкой между
    символами (используется для отправки сообщений в чат).
    """
    import random

    for char in text:
        _keyboard.type(char)
        time.sleep(random.uniform(*char_delay_range))


def send_chat_message(message: str, chat_key: str = "t", pre_delay=(0.2, 0.4), post_delay=(0.2, 0.4)):
    """
    Отправляет сообщение в игровой чат Minecraft:
      1. Открывает чат клавишей chat_key (по умолчанию 't', как в ванильном клиенте).
      2. Вводит текст сообщения.
      3. Отправляет клавишей Enter.
    Между шагами — небольшие случайные паузы, чтобы дать игре время
    среагировать на открытие окна чата.
    """
    import random

    key = _resolve_key(chat_key)
    _keyboard.press(key)
    _keyboard.release(key)
    time.sleep(random.uniform(*pre_delay))

    type_text(message)

    time.sleep(random.uniform(*post_delay))
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
