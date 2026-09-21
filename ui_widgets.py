"""
ui_widgets.py — палитра, шрифты и кастомные виджеты GUI v7.1.
Всё реализовано на чистом tkinter (без ttkbootstrap/customtkinter):
- тёмная фиолетово-синяя палитра;
- движок анимаций на after() (плавные переходы цвета, fade-in вкладок);
- тогглы-переключатели (Canvas), кнопки с hover-эффектом за 150 мс, тултипы;
- пульсирующий статус-бейдж бота;
- карточки со скруглёнными углами (radius=20) и тонкой рамкой;
- скроллируемые фреймы для вкладок.
"""

import math
import time
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

# ==================== ПАЛИТРА ====================
COLOR_BG = "#0d0b1a"           # фон страниц
COLOR_PANEL = "#151229"        # вторичные поверхности (лента вкладок)
COLOR_CARD = "#1e1a33"         # карточки-секции
COLOR_FIELD = "#241f3d"        # поля ввода / списки
COLOR_ACCENT = "#8b5cf6"       # основной акцент (фиолетовый)
COLOR_ACCENT_SOFT = "#a78bfa"  # светлый акцент (лавандовый)
COLOR_TEXT = "#e8e6f2"
COLOR_MUTED = "#9b96b8"
COLOR_OK = "#34d399"           # мягкий зелёный
COLOR_WARN = "#fbbf24"         # янтарный
COLOR_ERROR = "#f87171"        # коралловый
COLOR_BORDER = "#322b5e"       # тонкая рамка карточек

# ==================== ШРИФТЫ ====================
FONT_FAMILY = "Segoe UI"  # уточняется в init_fonts()


def init_fonts(root) -> str:
    """Выбирает 'Segoe UI Variable' с фолбэком на Segoe UI / Inter."""
    global FONT_FAMILY
    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    for candidate in ("Segoe UI Variable", "Segoe UI Variable Text", "Segoe UI", "Inter", "Verdana"):
        if candidate in families:
            FONT_FAMILY = candidate
            break
    return FONT_FAMILY


def font(size=10, bold=False):
    return (FONT_FAMILY, size, "bold" if bold else "normal")


# ==================== РАБОТА С ЦВЕТОМ ====================
def hex_to_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1: str, c2: str, t: float) -> str:
    rgb1, rgb2 = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(lerp(a, b, t) for a, b in zip(rgb1, rgb2)))


def lighten(color, amount):
    return lerp_color(color, "#ffffff", amount)


def darken(color, amount):
    return lerp_color(color, "#000000", amount)


def ease_out(t):
    return 1 - (1 - t) ** 3


def _parent_bg(parent) -> str:
    try:
        return str(parent.cget("bg"))
    except Exception:
        return COLOR_BG


# ==================== ДВИЖОК АНИМАЦИЙ ====================
def animate(widget, duration_ms, on_frame, on_done=None, fps=60):
    """
    Движок анимации на after(). on_frame(t) вызывается с t в [0..1].
    Безопасен к закрытию окна: если виджет исчез, анимация тихо останавливается.
    """
    start = time.monotonic()
    duration_s = max(1, duration_ms) / 1000.0

    def step():
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        t = (time.monotonic() - start) / duration_s
        if t >= 1.0:
            try:
                on_frame(1.0)
            except tk.TclError:
                return
            if on_done:
                try:
                    on_done()
                except tk.TclError:
                    pass
            return
        try:
            on_frame(t)
        except tk.TclError:
            return
        widget.after(max(8, 1000 // fps), step)

    step()


def fade_in(container, duration_ms=220):
    """Эффект появления вкладки: светлая вуаль быстро гаснет до цвета фона."""
    try:
        start_color = lighten(COLOR_BG, 0.10)
        cover = tk.Frame(container, bg=start_color)
        cover.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        cover.lift()

        def frame(t):
            cover.configure(bg=lerp_color(start_color, COLOR_BG, ease_out(t)))

        def done():
            try:
                cover.place_forget()
                cover.destroy()
            except tk.TclError:
                pass

        animate(container, duration_ms, frame, done)
    except Exception:
        pass


# ==================== ТУЛТИП ====================
class Tooltip:
    """Всплывающая подсказка при наведении (без внешних библиотек)."""

    def __init__(self, widget, text, delay_ms=450):
        self.widget, self.text, self.delay_ms = widget, text, delay_ms
        self._tip = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event):
        self._cancel()
        self._job = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self.text, bg=COLOR_CARD, fg=COLOR_TEXT,
                 relief="solid", bd=1, padx=8, pady=4, font=font(9),
                 justify="left", wraplength=280).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _cancel(self):
        if self._job:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None


# ==================== КНОПКА С HOVER ====================
class HoverButton(tk.Button):
    """Кнопка с плавным изменением фона при наведении (150 мс) и тултипом."""

    def __init__(self, parent, text="", command=None, bg=COLOR_ACCENT, hover_bg=None,
                 fg="#ffffff", tooltip=None, bold=True, **kw):
        self._base_bg = bg
        self._hover_bg = hover_bg or lighten(bg, 0.14)
        super().__init__(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=self._hover_bg, activeforeground=fg,
            relief="flat", bd=0, cursor="hand2", font=font(10, bold),
            padx=12, pady=6, disabledforeground=darken(COLOR_MUTED, 0.25), **kw,
        )
        self.bind("<Enter>", lambda _e: self._animate_to(self._hover_bg))
        self.bind("<Leave>", lambda _e: self._animate_to(self._base_bg))
        if tooltip:
            Tooltip(self, tooltip)

    def _animate_to(self, target):
        if str(self.cget("state")) == "disabled":
            return
        current = str(self.cget("bg"))
        animate(self, 150, lambda t: self.configure(bg=lerp_color(current, target, ease_out(t))))

    def set_enabled(self, enabled: bool):
        self.configure(state="normal" if enabled else "disabled")


# ==================== ТОГГЛ ====================
class ToggleSwitch(tk.Canvas):
    """
    Тоггл-переключатель в стиле референса: овал-дорожка + кружок.
    Значение хранится в tk.BooleanVar; command(value) вызывается после клика.
    """

    def __init__(self, parent, variable=None, command=None,
                 on_color=COLOR_OK, off_color="#3a3550", width=50, height=26):
        super().__init__(parent, width=width, height=height, bg=_parent_bg(parent),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._width, self._height = width, height
        self._on_color, self._off_color = on_color, off_color
        self._command = command
        self.var = variable if variable is not None else tk.BooleanVar(value=False)
        self._pad = 4
        self._r = (height - 2 * self._pad) / 2
        self._track = self.create_oval(1, 1, width - 1, height - 1, fill=self._off_color, outline="")
        cx = self._thumb_x(bool(self.var.get()))
        self._thumb = self.create_oval(cx - self._r, self._pad, cx + self._r,
                                       self._pad + 2 * self._r, fill=COLOR_TEXT, outline="")
        self.bind("<Button-1>", self._on_click)

    def _thumb_x(self, value: bool) -> float:
        return (self._pad + self._r) if not value else (self._width - self._pad - self._r)

    def _on_click(self, _event):
        new_value = not bool(self.var.get())
        self.var.set(new_value)
        self._redraw(animated=True)
        if self._command:
            self._command(new_value)

    def set(self, value: bool, animated=False):
        """Программно установить значение (без вызова command)."""
        self.var.set(bool(value))
        self._redraw(animated=animated)

    def _redraw(self, animated=False):
        value = bool(self.var.get())
        target_x = self._thumb_x(value)
        target_color = self._on_color if value else self._off_color
        if not animated:
            self.coords(self._thumb, target_x - self._r, self._pad,
                        target_x + self._r, self._pad + 2 * self._r)
            self.itemconfigure(self._track, fill=target_color)
            return
        coords = self.coords(self._thumb)
        current_x = (coords[0] + coords[2]) / 2
        current_color = str(self.itemcget(self._track, "fill"))

        def frame(t):
            x = lerp(current_x, target_x, ease_out(t))
            self.coords(self._thumb, x - self._r, self._pad, x + self._r, self._pad + 2 * self._r)
            self.itemconfigure(self._track, fill=lerp_color(current_color, target_color, ease_out(t)))

        animate(self, 160, frame)


# ==================== СЕГМЕНТИРОВАННЫЙ ПЕРЕКЛЮЧАТЕЛЬ ====================
class SegmentedControl(tk.Frame):
    """
    Сегментированный переключатель (как в референсе): ряд «доль», активная
    подсвечивается акцентом. options — список кортежей (значение, подпись);
    значение хранится в tk.StringVar; command(value) вызывается при выборе.
    """

    def __init__(self, parent, options, variable, command=None):
        super().__init__(parent, bg=_parent_bg(parent))
        self.variable = variable
        self._command = command
        self._buttons = {}
        for value, label in options:
            lbl = tk.Label(self, text=label, bg=COLOR_FIELD, fg=COLOR_TEXT,
                           font=font(10), padx=14, pady=6, cursor="hand2")
            lbl.pack(side="left", padx=(0, 4))
            lbl.bind("<Button-1>", lambda _e, v=value: self.select(v))
            self._buttons[value] = lbl
        self._redraw()

    def select(self, value):
        """Выбирает значение, перерисовывает и вызывает command."""
        self.variable.set(value)
        self._redraw()
        if self._command:
            self._command(value)

    def _redraw(self):
        current = self.variable.get()
        for value, lbl in self._buttons.items():
            if value == current:
                lbl.configure(bg=COLOR_ACCENT, fg="#ffffff")
            else:
                lbl.configure(bg=COLOR_FIELD, fg=COLOR_TEXT)


# ==================== СТАТУС-БЕЙДЖ ====================
class StatusBadge(tk.Frame):
    """Статус-бейдж: цветной кружок + подпись. Кружок пульсирует, когда бот работает."""

    def __init__(self, parent):
        super().__init__(parent, bg=_parent_bg(parent))
        bg = str(self.cget("bg"))
        self.canvas = tk.Canvas(self, width=20, height=20, bg=bg, highlightthickness=0)
        self.canvas.pack(side="left", padx=(2, 10))
        self._dot = self.canvas.create_oval(5, 5, 15, 15, fill=COLOR_MUTED, outline="")
        self.label_var = tk.StringVar(value="Остановлен")
        tk.Label(self, textvariable=self.label_var, bg=bg, fg=COLOR_TEXT,
                 font=font(11, True)).pack(side="left")
        self._pulse_job = None
        self._base_color = COLOR_MUTED

    def set_status(self, text: str, color: str, pulse=False):
        self.label_var.set(text)
        self._base_color = color
        self._stop_pulse()
        if pulse:
            self._start_pulse()
        else:
            self.canvas.itemconfigure(self._dot, fill=color)
            self.canvas.coords(self._dot, 5, 5, 15, 15)

    def _start_pulse(self):
        def tick():
            try:
                if not self.winfo_exists():
                    return
                phase = (time.monotonic() % 1.2) / 1.2
                wave = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2  # 0..1
                radius = 5.0 + 2.0 * wave
                color = lerp_color(self._base_color, lighten(self._base_color, 0.35), wave)
                self.canvas.coords(self._dot, 10 - radius, 10 - radius, 10 + radius, 10 + radius)
                self.canvas.itemconfigure(self._dot, fill=color)
                self._pulse_job = self.after(50, tick)
            except tk.TclError:
                pass

        self._pulse_job = self.after(50, tick)

    def _stop_pulse(self):
        if self._pulse_job:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None


# ==================== КАРТОЧКА ====================
class RoundedCard(tk.Canvas):
    """
    Карточка со скруглёнными углами (radius=20) и тонкой рамкой.
    Контент размещать в self.body (tk.Frame с фоном карточки).
    fill=True — тело растягивается на всю высоту карточки (для списков/логов).
    """

    def __init__(self, parent, title="", radius=20, bg=COLOR_CARD,
                 border=COLOR_BORDER, title_color=COLOR_ACCENT_SOFT, fill=False):
        super().__init__(parent, bg=_parent_bg(parent), highlightthickness=0, bd=0)
        self._radius, self._bg = radius, bg
        self._pad = 16  # Увеличенный отступ для "воздуха"
        self._fill = fill
        self._title_h = 40 if title else 10  # Чуть больше места под заголовок
        self._poly = self.create_polygon(self._rect_points(1, 1, 3, 3), smooth=True,
                                         fill=bg, outline=border)
        if title:
            self.create_text(self._pad + 4, self._title_h / 2 + 3, text=title, anchor="w",
                             fill=title_color, font=font(12, True))  # Шрифт чуть крупнее
        self.body = tk.Frame(self, bg=bg)
        self._win = self.create_window((self._pad, self._title_h), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_height, add="+")
        self.bind("<Configure>", self._on_resize)
        self._sync_height()

    def _rect_points(self, x1, y1, x2, y2):
        r = max(1, min(self._radius, (x2 - x1) / 2, (y2 - y1) / 2))
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
                x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
                x1, y2, x1, y2 - r, x1, y1 + r]

    def refresh(self):
        """Пересчитать высоту под содержимое (вызвать после наполнения)."""
        self._sync_height()

    def _sync_height(self, _event=None):
        if self._fill:
            return
        height = int(self.body.winfo_reqheight() + self._title_h + self._pad)
        if height != int(self.cget("height")):
            self.configure(height=height)

    def _on_resize(self, event):
        w, h = max(6, event.width - 2), max(6, event.height - 2)
        self.coords(self._poly, self._rect_points(1, 1, w, h))
        opts = {"width": max(10, event.width - 2 * self._pad)}
        if self._fill:
            opts["height"] = max(10, event.height - self._title_h - self._pad)
        self.itemconfigure(self._win, **opts)


# ==================== СКРОЛЛИРУЕМЫЙ ФРЕЙМ ====================
class ScrollableFrame(tk.Frame):
    """
    Универсальный контейнер с ВЕРТИКАЛЬНЫМ и ГОРИЗОНТАЛЬНЫМ скроллингом.
    Если контент не помещается — автоматически появляются ползунки.
    Контент размещать в self.inner.
    """

    def __init__(self, parent, bg=None):
        bg = bg or COLOR_BG
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.hscroll.grid(row=1, column=0, sticky="we")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Привязка колёсика мыши
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _on_inner_configure(self, _event):
        """Пересчёт области прокрутки при изменении размеров контента."""
        bbox = self.canvas.bbox("all") or (0, 0, 0, 0)
        self.canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event):
        """Контент на всю ширину, пока не станет шире — тогда горизонтальный скролл."""
        self.canvas.itemconfigure(self._win, width=max(event.width, self.inner.winfo_reqwidth()))

    def _on_mousewheel(self, event):
        """Прокрутка колёсиком мыши."""
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
