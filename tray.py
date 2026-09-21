"""
tray.py — иконка системного трея для GUI minecraft-bot (pystray + Pillow).

Возможности:
- сворачивание окна приложения в трей (окно скрывается, процесс продолжает
  работать в фоне) — по кнопке "Свернуть" или по крестику;
- контекстное меню: "Показать окно", "Запустить/Остановить бота"
  (подпись динамическая, зависит от текущего состояния бота), "Выход";
- двойной клик по иконке вызывает пункт меню с default=True
  ("Показать окно") — так это реализовано в pystray на Windows.

Иконка рисуется кодом через Pillow, внешний png-файл не нужен.
Если pystray/Pillow не установлены, app.py продолжает работать без трея
(импорт там обёрнут в try/except).
"""

from PIL import Image, ImageDraw
import pystray

TRAY_ICON_NAME = "minecraft-bot"
TRAY_TOOLTIP = "Minecraft Bot"


class TrayIcon:
    """
    Обёртка над pystray.Icon. Все коллбэки (on_show / on_toggle_bot / on_exit)
    вызываются из потока pystray — app.py сам переносит их в поток GUI
    через after(0, ...).
    """

    def __init__(self, on_show, on_toggle_bot, on_exit, is_bot_running=None):
        self.on_show = on_show
        self.on_toggle_bot = on_toggle_bot
        self.on_exit = on_exit
        self.is_bot_running = is_bot_running or (lambda: False)
        self._icon = None

    # ---------- иконка и меню ----------

    @staticmethod
    def _make_image() -> Image.Image:
        """Рисуем простую иконку: синяя панель с зелёным индикатором."""
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            [2, 2, size - 3, size - 3], radius=14,
            fill=(38, 42, 53, 255), outline=(91, 141, 239, 255), width=3,
        )
        draw.ellipse([20, 20, 44, 44], fill=(76, 175, 125, 255))
        return image

    def _toggle_label(self, item):
        """Динамическая подпись пункта: вычисляется при каждом открытии меню."""
        return "Остановить бота" if self.is_bot_running() else "Запустить бота"

    def _build_menu(self):
        return pystray.Menu(
            # default=True: на Windows вызывается двойным кликом по иконке
            pystray.MenuItem("Показать окно", self._action_show, default=True),
            pystray.MenuItem(self._toggle_label, self._action_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._action_exit),
        )

    # pystray передаёт в обработчик (icon, item) — принимаем и зовём коллбэк
    def _action_show(self, icon, item):
        self.on_show()

    def _action_toggle(self, icon, item):
        self.on_toggle_bot()

    def _action_exit(self, icon, item):
        self.on_exit()

    # ---------- жизненный цикл ----------

    def start(self):
        """Создаёт иконку и запускает цикл pystray в фоновом потоке."""
        if self._icon is not None:
            return
        self._icon = pystray.Icon(
            TRAY_ICON_NAME,
            self._make_image(),
            TRAY_TOOLTIP,
            self._build_menu(),
        )
        self._icon.run_detached()

    def stop(self):
        """Останавливает иконку трея (безопасно вызывать из другого потока)."""
        if self._icon is None:
            return
        try:
            self._icon.stop()
        finally:
            self._icon = None