
"""
app.py — единое GUI-приложение для minecraft-bot (v8).
Новое в v8:
- все вкладки теперь прокручиваемые (ScrollableFrame) с авто-ползунками;
- улучшенный визуал: радиусы 18px, увеличенные отступы, мягкие цвета;
- вкладка «Расписание»: справочник VimeWorld объединён с настройками;
- вкладки «Запуск» и «Горячие клавиши» объединены в одну;
- кнопка старт/стоп теперь одна, меняет состояние и текст.
"""

import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import audit
import diagnostics
import notifier
import scheduler
from log_monitor import DEFAULT_PATTERNS, PATTERN_LABELS, default_game_log_path
import settings as settings_module
import ui_widgets as ui
from bot import log_event, MINECRAFT_WINDOW_TITLE
from hotkey import HotkeyListener, SingleComboCapture, normalize_hotkey_string
from recorder import ManualRecorder

try:
    from tray import TrayIcon
except Exception:
    TrayIcon = None

LOG_FILE = "bot_log.txt"
BOT_SCRIPT = "bot.py"
DEFAULT_MOVEMENT_SCENARIO = "scenario_movement.json"
DEFAULT_CHAT_SCENARIO = "scenario_chat.json"
SPECIAL_KEYS = ["space", "shift", "ctrl", "alt", "enter", "esc", "tab",
                "up", "down", "left", "right"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Minecraft Bot — центр управления")
        self.geometry("960x720")
        self.minsize(880, 650)
        ui.init_fonts(self)
        self.configure(bg=ui.COLOR_BG)
        self._apply_theme()

        self.recorder = ManualRecorder()
        self.bot_process = None
        self._bot_stderr_file = None
        self.settings = settings_module.load_settings()

        # переменные сценариев
        self.current_scenario_path = tk.StringVar(value=DEFAULT_MOVEMENT_SCENARIO)
        self.steps = []
        self.chat_message_var = tk.StringVar(value="")

        # переменные расписания
        schedule = self.settings.get("schedule", {"mode": "fixed_minute", "value": 30})
        self.schedule_mode_var = tk.StringVar(value=schedule.get("mode", "fixed_minute"))
        self.schedule_value_var = tk.StringVar(value=str(schedule.get("value", 30)))

        # переменные уведомлений
        notif = self.settings.get("notifications", {})
        self.notif_vars = {
            key: tk.BooleanVar(value=bool(notif.get(key, True)))
            for key in ["enabled", *notifier.EVENT_LABELS.keys()]
        }

        # v7: мониторинг лога, авто-принятие группы, события расписания
        lm = self.settings.get("log_monitor", {}) or {}
        self.monitor_enabled_var = tk.BooleanVar(value=bool(lm.get("enabled", True)))
        self.monitor_path_var = tk.StringVar(
            value=self.settings.get("game_log_path", "") or lm.get("path", ""))
        stored_patterns = dict(DEFAULT_PATTERNS)
        stored_patterns.update(lm.get("patterns", {}) or {})
        self.pattern_vars = {key: tk.StringVar(value=stored_patterns.get(key, ""))
                             for key in PATTERN_LABELS}
        lm_events = lm.get("events", {}) or {}
        self.monitor_event_vars = {
            "party_invite": tk.BooleanVar(value=bool(lm_events.get("party_invite", True))),
            "dungeons": tk.BooleanVar(value=bool(lm_events.get("dungeons", True))),
            "wild_raid": tk.BooleanVar(value=bool(lm_events.get("wild_raid", True))),
        }
        self.check_mode_var = tk.StringVar(value=self.settings.get("check_mode", "both"))
        self.log_triggers = [str(t) for t in self.settings.get("log_triggers", [])]
        self.new_trigger_var = tk.StringVar(value="")
        pa = self.settings.get("party_acceptor", {}) or {}
        self.acceptor_enabled_var = tk.BooleanVar(value=bool(pa.get("enabled", True)))
        self.acceptor_method_var = tk.StringVar(value=pa.get("method", "log_chat"))
        self.acceptor_timeout_var = tk.StringVar(value=str(pa.get("timeout_seconds", 60)))
        self.acceptor_queue_var = tk.BooleanVar(value=bool(pa.get("queue_enabled", True)))
        sch = self.settings.get("scheduler", {}) or {}
        self.warn_minutes_var = tk.StringVar(value=str(sch.get("warn_minutes_before", 1)))
        sch_events = sch.get("events", {}) or {}
        self.scheduler_event_vars = {
            key: tk.BooleanVar(value=bool(sch_events.get(key, True)))
            for key in ("secret_easy", "jeju", "dslp")
        }

        # хоткей
        self.hotkey_var = tk.StringVar(value=self.settings.get("hotkey", "<ctrl>+<alt>+s"))
        self._combo_capture = None
        self._hotkey_listener = None

        # геометрия и трей
        self._geom_job = None
        self._diag_report = ""
        self._audit_report = None
        self.tray = None

        # ---------- вкладки ----------
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=16)

        # Создаём фреймы для вкладок с прокруткой
        self.launch_frame = ui.ScrollableFrame(self.notebook)
        self.scenarios_frame = ui.ScrollableFrame(self.notebook)
        self.schedule_frame = ui.ScrollableFrame(self.notebook)
        self.diag_frame = ui.ScrollableFrame(self.notebook)
        self.notif_frame = ui.ScrollableFrame(self.notebook)
        self.monitor_frame = ui.ScrollableFrame(self.notebook)

        self.notebook.add(self.launch_frame, text=" ▶ Запуск и хоткей ")
        self.notebook.add(self.scenarios_frame, text=" 🧩 Сценарии ")
        self.notebook.add(self.schedule_frame, text=" ⏰ Расписание ")
        self.notebook.add(self.monitor_frame, text=" 📜 Мониторинг лога ")
        self.notebook.add(self.diag_frame, text=" 🩺 Диагностика ")
        self.notebook.add(self.notif_frame, text=" 🔔 Уведомления ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_launch_tab()
        self._build_scenarios_tab()
        self._build_schedule_tab()
        self._build_monitor_tab()
        self._build_diagnostics_tab()
        self._build_notifications_tab()

        self._load_scenario(DEFAULT_MOVEMENT_SCENARIO, silent=True)
        self._load_geometry()
        self._start_hotkey_listener()
        self._init_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind("<Configure>", self._schedule_geometry_save)
        self.after(2000, self._refresh_run_tab)

    # ==================== ТЕМА ====================

    def _apply_theme(self):
        """Единая тёмная фиолетово-синяя палитра ttk."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=ui.COLOR_BG, foreground=ui.COLOR_TEXT, font=ui.font(10))
        style.configure("TFrame", background=ui.COLOR_BG)
        style.configure("Card.TFrame", background=ui.COLOR_CARD)
        style.configure("TLabel", background=ui.COLOR_BG, foreground=ui.COLOR_TEXT)
        style.configure("Card.TLabel", background=ui.COLOR_CARD, foreground=ui.COLOR_TEXT)
        style.configure("Card.Muted.TLabel", background=ui.COLOR_CARD, foreground=ui.COLOR_MUTED)
        style.configure("Muted.TLabel", background=ui.COLOR_BG, foreground=ui.COLOR_MUTED)
        style.configure("TLabelframe", background=ui.COLOR_CARD, foreground=ui.COLOR_TEXT,
                        bordercolor=ui.COLOR_BORDER)
        style.configure("TLabelframe.Label", background=ui.COLOR_CARD,
                        foreground=ui.COLOR_ACCENT_SOFT, font=ui.font(11, True))
        style.configure("TNotebook", background=ui.COLOR_BG, borderwidth=0,
                        tabmargins=(8, 6, 8, 0))
        style.configure("TNotebook.Tab", background=ui.COLOR_PANEL, foreground=ui.COLOR_MUTED,
                        padding=(20, 12), font=ui.font(10, True))
        style.map("TNotebook.Tab",
                  background=[("selected", ui.COLOR_CARD)],
                  foreground=[("selected", ui.COLOR_ACCENT_SOFT)],
                  expand=[("selected", (0, 0, 0, 2))])
        style.configure("TEntry", fieldbackground=ui.COLOR_FIELD, foreground=ui.COLOR_TEXT,
                        insertcolor=ui.COLOR_TEXT, bordercolor=ui.COLOR_BORDER)
        style.configure("Card.TRadiobutton", background=ui.COLOR_CARD,
                        foreground=ui.COLOR_TEXT, indicatorcolor=ui.COLOR_ACCENT)
        style.map("Card.TRadiobutton", background=[("active", ui.COLOR_CARD)])
        style.configure("TScrollbar", background=ui.COLOR_PANEL, troughcolor=ui.COLOR_BG,
                        bordercolor=ui.COLOR_BG, arrowcolor=ui.COLOR_MUTED)
        style.configure("TSeparator", background=ui.COLOR_BORDER)

    # ==================== ВКЛАДКА «ЗАПУСК И ХОТКЕЙ» ====================

    def _build_launch_tab(self):
        parent = self.launch_frame.inner

        # Карточка статуса и управления
        status_card = ui.RoundedCard(parent, title="Статус бота", radius=18)
        status_card.pack(fill="x", padx=8, pady=(8, 12))
        row = status_card.body

        self.status_badge = ui.StatusBadge(row)
        self.status_badge.pack(side="left", padx=(8, 16), pady=8)

        # Единая кнопка старт/стоп
        self.toggle_button = ui.HoverButton(
            row, text="▶ Запустить", command=self._toggle_bot,
            bg=ui.COLOR_OK, tooltip="Запустить или остановить бота"
        )
        self.toggle_button.pack(side="right", padx=8, pady=8)

        ui.HoverButton(row, text="⬇ Свернуть", command=self._minimize_to_tray,
                       bg=ui.COLOR_FIELD, tooltip="Свернуть окно в трей").pack(side="right", padx=8, pady=8)
        status_card.refresh()

        # Карточка хоткея
        hotkey_card = ui.RoundedCard(parent, title="Горячая клавиша", radius=18)
        hotkey_card.pack(fill="x", padx=8, pady=(0, 12))
        body = hotkey_card.body
        row = tk.Frame(body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        tk.Label(row, text="Комбинация старт/стоп:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left")
        ttk.Entry(row, textvariable=self.hotkey_var, width=24, state="readonly").pack(side="left", padx=12)
        self.assign_hotkey_button = ui.HoverButton(row, text="🎯 Назначить…",
                                                   command=self._start_combo_capture, bg=ui.COLOR_FIELD,
                                                   tooltip="Нажми новую комбинацию клавиш")
        self.assign_hotkey_button.pack(side="left", padx=6)
        ui.HoverButton(row, text="💾 Сохранить", command=self._save_hotkey).pack(side="left", padx=6)
        tk.Label(body,
                 text="Работает глобально (даже если фокус на игре) и реагирует только на эту "
                      "комбинацию — остальные нажатия не сохраняются.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=780).pack(fill="x", anchor="w", padx=8, pady=(0, 8))
        hotkey_card.refresh()

        # Карточка лога
        log_card = ui.RoundedCard(parent, title=f"Последние строки {LOG_FILE}", fill=True, radius=18)
        log_card.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body = log_card.body
        self.log_text = tk.Text(body, height=20, state="disabled", wrap="word",
                                bg=ui.COLOR_FIELD, fg=ui.COLOR_TEXT, insertbackground=ui.COLOR_TEXT,
                                relief="flat", bd=0, font=ui.font(9), padx=12, pady=12)
        self.log_text.pack(side="left", fill="both", expand=True, pady=8)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="left", fill="y", pady=8, padx=(0, 4))
        self.log_text.config(yscrollcommand=scroll.set)

    # ==================== ВКЛАДКА «СЦЕНАРИИ» ====================

    def _hb(self, parent, text, command, tip=None, primary=False):
        button = ui.HoverButton(parent, text=text, command=command, tooltip=tip,
                                bg=ui.COLOR_ACCENT if primary else ui.COLOR_FIELD)
        button.pack(side="left", padx=4)
        return button

    def _vb(self, parent, text, command, tip=None):
        button = ui.HoverButton(parent, text=text, command=command, tooltip=tip, bg=ui.COLOR_FIELD)
        button.pack(fill="x", pady=3)
        return button

    def _build_scenarios_tab(self):
        parent = self.scenarios_frame.inner

        # Карточка файла сценария
        file_card = ui.RoundedCard(parent, title="Файл сценария", radius=18)
        file_card.pack(fill="x", padx=8, pady=(8, 12))
        body = file_card.body
        row1 = tk.Frame(body, bg=ui.COLOR_CARD)
        row1.pack(fill="x", pady=(8, 8))
        tk.Label(row1, text="Файл:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left")
        ttk.Entry(row1, textvariable=self.current_scenario_path, width=32).pack(side="left", padx=12)
        self._hb(row1, "📂 Загрузить", self._on_load_button, "Загрузить сценарий из файла")
        self._hb(row1, "💾 Сохранить", self._on_save_button, "Сохранить сценарий в указанный файл")
        self._hb(row1, "Сохранить как…", self._save_scenario_as)
        row2 = tk.Frame(body, bg=ui.COLOR_CARD)
        row2.pack(fill="x", pady=(0, 8))
        tk.Label(row2, text="Чат-сообщение (Сценарий 1):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_MUTED, font=ui.font(10)).pack(side="left")
        ttk.Entry(row2, textvariable=self.chat_message_var, width=36).pack(side="left", padx=12)
        file_card.refresh()

        # Карточка шагов
        steps_card = ui.RoundedCard(parent, title="Шаги сценария", fill=True, radius=18)
        steps_card.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        body = steps_card.body
        left = tk.Frame(body, bg=ui.COLOR_CARD)
        left.pack(side="left", fill="both", expand=True, pady=8)
        self.listbox = tk.Listbox(left, height=10, bg=ui.COLOR_FIELD, fg=ui.COLOR_TEXT,
                                  selectbackground=ui.COLOR_ACCENT, highlightthickness=0,
                                  borderwidth=0, font=ui.font(10))
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="left", fill="y", padx=(4, 0))
        self.listbox.config(yscrollcommand=scrollbar.set)
        right = tk.Frame(body, bg=ui.COLOR_CARD, width=220)
        right.pack(side="left", fill="y", padx=(12, 0), pady=8)
        right.pack_propagate(False)
        self._vb(right, "➕ Добавить шаг вручную", self._open_add_step_dialog)
        self._vb(right, "🗑 Удалить выбранный", self._delete_selected_step)
        self._vb(right, "↑ Вверх", lambda: self._move_step(-1))
        self._vb(right, "↓ Вниз", lambda: self._move_step(1))

        # Карточка ручной записи
        record_card = ui.RoundedCard(parent, title="Ручная запись шагов", radius=18)
        record_card.pack(fill="x", padx=8, pady=(0, 8))
        body = record_card.body
        row_keys = tk.Frame(body, bg=ui.COLOR_CARD)
        row_keys.pack(fill="x", pady=(8, 6))
        tk.Label(row_keys, text="Клавиша:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left")
        self.record_key_var = tk.StringVar(value="w")
        ttk.Entry(row_keys, textvariable=self.record_key_var, width=10).pack(side="left", padx=12)
        self.hold_button = ui.HoverButton(row_keys, text="Начать удержание", command=self._start_hold,
                                          bg=ui.COLOR_FIELD)
        self.hold_button.pack(side="left", padx=6)
        self.finish_hold_button = ui.HoverButton(row_keys, text="Закончить удержание",
                                                 command=self._finish_hold, bg=ui.COLOR_FIELD)
        self.finish_hold_button.pack(side="left", padx=6)
        self.finish_hold_button.set_enabled(False)
        row_click = tk.Frame(body, bg=ui.COLOR_CARD)
        row_click.pack(fill="x", pady=(0, 8))
        tk.Label(row_click, text="Клик (координаты отн. окна игры):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_MUTED, font=ui.font(10)).pack(side="left")
        self.click_x_var = tk.StringVar(value="0")
        self.click_y_var = tk.StringVar(value="0")
        ttk.Entry(row_click, textvariable=self.click_x_var, width=8).pack(side="left", padx=(12, 4))
        ttk.Entry(row_click, textvariable=self.click_y_var, width=8).pack(side="left", padx=4)
        ui.HoverButton(row_click, text="🎯 Отметить клик", command=self._capture_click,
                       bg=ui.COLOR_FIELD).pack(side="left", padx=12)
        ui.HoverButton(row_click, text="Очистить запись", command=self._clear_recording,
                       bg=ui.COLOR_FIELD).pack(side="left")
        record_card.refresh()

    # ==================== ВКЛАДКА «РАСПИСАНИЕ» ====================
    def _build_schedule_tab(self):
        parent = self.schedule_frame.inner

        # Объединённая карточка: настройки + справочник
        card = ui.RoundedCard(parent, title="Расписание и события VimeWorld", radius=18)
        card.pack(fill="x", padx=8, pady=(8, 12))
        body = card.body

        # Настройки периода
        row = tk.Frame(body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        ttk.Radiobutton(row, text="Строго в минуту часа:", variable=self.schedule_mode_var,
                        value="fixed_minute", style="Card.TRadiobutton").grid(
            row=0, column=0, sticky="w", pady=4, padx=(8, 8))
        ttk.Entry(row, textvariable=self.schedule_value_var, width=8).grid(row=0, column=1, padx=8)
        tk.Label(row, text="0–59 (например 30 → хх:30 каждого часа)",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).grid(row=0, column=2, sticky="w")

        ttk.Radiobutton(row, text="Каждые N минут:", variable=self.schedule_mode_var,
                        value="every_n_minutes", style="Card.TRadiobutton").grid(
            row=1, column=0, sticky="w", pady=4, padx=(8, 8))
        tk.Label(row, text="запуск на 0, N, 2N… минуте каждого часа",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).grid(row=1, column=2, sticky="w")

        ui.HoverButton(row, text="💾 Сохранить расписание", command=self._save_schedule).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(16, 8), padx=(8, 0))

        # Разделитель
        ttk.Separator(row, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=12)

        # Справочник событий
        tk.Label(row, text="События VimeWorld (справочник):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_ACCENT_SOFT, font=ui.font(11, True)).grid(
            row=4, column=0, sticky="w", pady=(8, 4), padx=(8, 0))

        for name, period, source in scheduler.SCHEDULE_INFO:
            event_row = tk.Frame(body, bg=ui.COLOR_CARD)
            event_row.pack(fill="x", pady=2)
            tk.Label(event_row, text=f"• {name}", bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                     font=ui.font(10)).pack(side="left", padx=(8, 8))
            tk.Label(event_row, text=period, bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                     font=ui.font(9)).pack(side="left", padx=(0, 12))
            color = ui.COLOR_ACCENT_SOFT if source == "по расписанию" else ui.COLOR_MUTED
            tk.Label(event_row, text=source, bg=ui.COLOR_CARD, fg=color,
                     font=ui.font(9)).pack(side="right", padx=(0, 8))

        tk.Label(body,
                 text="События «из лога» уведомляются при фактическом обнаружении; "
                      "события «по расписанию» предупреждаются заранее.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=820).pack(anchor="w", pady=(12, 8), padx=(8, 0))

        # Предупреждения о событиях вне логов
        warn_row = tk.Frame(body, bg=ui.COLOR_CARD)
        warn_row.pack(fill="x", pady=(8, 8))
        tk.Label(warn_row, text="Предупреждать за (минут):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_MUTED, font=ui.font(10)).pack(side="left", padx=(8, 8))
        ttk.Entry(warn_row, textvariable=self.warn_minutes_var, width=8).pack(side="left", padx=8)

        for key, label in [("secret_easy", "Тайное лёгкое (ежедневно 16:00)"),
                           ("jeju", "Остров Чеджу (ежедневно 17:00)"),
                           ("dslp", "ДСЛП (каждые 6 часов)")]:
            toggle_row = tk.Frame(body, bg=ui.COLOR_CARD)
            toggle_row.pack(fill="x", pady=4, padx=(8, 0))
            tk.Label(toggle_row, text=label, bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                     font=ui.font(10)).pack(side="left")
            ui.ToggleSwitch(toggle_row, variable=self.scheduler_event_vars[key]).pack(side="right")

        ui.HoverButton(body, text="💾 Сохранить предупреждения",
                       command=self._save_scheduler_settings).pack(anchor="w", pady=(12, 8), padx=(8, 0))
        card.refresh()

    # ==================== ВКЛАДКА «ДИАГНОСТИКА» ====================
    def _build_diagnostics_tab(self):
        parent = self.diag_frame.inner

        card1 = ui.RoundedCard(parent, title="Готовность бота", radius=18)
        card1.pack(fill="x", padx=8, pady=(8, 12))
        row = tk.Frame(card1.body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        ui.HoverButton(row, text="🔍 Проверить готовность", command=self._run_diagnostics,
                       tooltip="Пассивная самопроверка").pack(side="left", padx=8)
        ui.HoverButton(row, text="💾 Экспорт отчёта", command=self._export_diagnostics,
                       bg=ui.COLOR_FIELD).pack(side="left", padx=8)
        self.diag_text = tk.Text(card1.body, height=10, bg=ui.COLOR_FIELD, fg=ui.COLOR_TEXT,
                                 relief="flat", bd=0, wrap="word", font=ui.font(9), padx=12, pady=12)
        self.diag_text.pack(fill="x", padx=8, pady=(0, 8))
        self.diag_text.configure(state="disabled")
        card1.refresh()

        card2 = ui.RoundedCard(parent, title="Аудит проекта", radius=18)
        card2.pack(fill="x", padx=8, pady=(0, 8))
        row = tk.Frame(card2.body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        ui.HoverButton(row, text="🧹 Аудит проекта", command=self._run_audit, bg=ui.COLOR_FIELD,
                       tooltip="Поиск неиспользуемых и повреждённых файлов").pack(side="left", padx=8)
        self.audit_delete_button = ui.HoverButton(row, text="🗑 Удалить выбранные…",
                                                  command=self._open_audit_delete_dialog, bg=ui.COLOR_ERROR)
        self.audit_delete_button.pack(side="left", padx=8)
        self.audit_delete_button.set_enabled(False)
        self.audit_text = tk.Text(card2.body, height=8, bg=ui.COLOR_FIELD, fg=ui.COLOR_TEXT,
                                  relief="flat", bd=0, wrap="word", font=ui.font(9), padx=12, pady=12)
        self.audit_text.pack(fill="x", padx=8, pady=(0, 8))
        self.audit_text.configure(state="disabled")
        tk.Label(card2.body,
                 text="Аудит ничего не удаляет сам: удаление возможно только через диалог с "
                      "чекбоксами и подтверждением. Критичные файлы проекта защищены.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=780).pack(fill="x", anchor="w", pady=(0, 8), padx=(8, 0))
        card2.refresh()

    # ==================== ВКЛАДКА «УВЕДОМЛЕНИЯ» ====================
    def _build_notifications_tab(self):
        parent = self.notif_frame.inner

        master_card = ui.RoundedCard(parent, title="Системные уведомления", radius=18)
        master_card.pack(fill="x", padx=8, pady=(8, 12))
        row = master_card.body
        tk.Label(row, text="Включить уведомления Windows", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_TEXT, font=ui.font(10)).pack(side="left", pady=8, padx=(8, 12))
        ui.ToggleSwitch(row, variable=self.notif_vars["enabled"],
                        command=lambda _v: self._save_notifications()).pack(side="right", pady=8, padx=(0, 8))
        tk.Label(row, text="Если выключено — события фиксируются только в логах.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(side="left", padx=(12, 0))
        master_card.refresh()

        events_card = ui.RoundedCard(parent, title="События", radius=18)
        events_card.pack(fill="x", padx=8, pady=(0, 12))
        for key, label in notifier.EVENT_LABELS.items():
            row = tk.Frame(events_card.body, bg=ui.COLOR_CARD)
            row.pack(fill="x", pady=4, padx=(8, 0))
            tk.Label(row, text=label, bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                     font=ui.font(10)).pack(side="left")
            ui.ToggleSwitch(row, variable=self.notif_vars[key]).pack(side="right")
        tk.Label(events_card.body, text="Сохраняется автоматически в settings.json.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(anchor="w", pady=(8, 0), padx=(8, 0))
        events_card.refresh()

        test_card = ui.RoundedCard(parent, title="Проверка", radius=18)
        test_card.pack(fill="x", padx=8)
        row = test_card.body
        ui.HoverButton(row, text="🔔 Отправить тестовое уведомление",
                       command=self._send_test_notification,
                       tooltip="Отправляет уведомление независимо от настроек").pack(side="left", padx=8)
        tk.Label(row, text="Если plyer не установлен — сообщение появится в консоли.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(side="left", padx=(12, 0))
        test_card.refresh()

    # ==================== ВКЛАДКА «МОНИТОРИНГ ЛОГА» ====================
    def _toggle_row(self, parent, text, variable, hint=None):
        row = tk.Frame(parent, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=4, padx=(8, 0))
        tk.Label(row, text=text, bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                 font=ui.font(10)).pack(side="left")
        if hint:
            tk.Label(row, text=hint, bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                     font=ui.font(9)).pack(side="left", padx=(8, 0))
        ui.ToggleSwitch(row, variable=variable).pack(side="right")
        return row

    def _build_monitor_tab(self):
        parent = self.monitor_frame.inner

        # Карточка файла лога
        log_card = ui.RoundedCard(parent, title="Файл лога игры", radius=18)
        log_card.pack(fill="x", padx=8, pady=(8, 12))
        body = log_card.body
        row = tk.Frame(body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        tk.Label(row, text="Путь к latest.log:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left", padx=(8, 8))
        ttk.Entry(row, textvariable=self.monitor_path_var, width=46).pack(side="left", padx=12)
        self._hb(row, "Обзор…", self._browse_log_path)
        self._hb(row, "По умолчанию", self._use_default_log_path)
        self._toggle_row(body, "Включить мониторинг событий", self.monitor_enabled_var)
        tk.Label(body,
                 text="Пусто = путь по умолчанию: %APPDATA%\\.vimeworld\\minigames_new_anticheat\\logs\\latest.log",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=820).pack(anchor="w", pady=(4, 8), padx=(8, 0))
        log_card.refresh()

        # Карточка отслеживаемых событий
        events_card = ui.RoundedCard(parent, title="Отслеживаемые события", radius=18)
        events_card.pack(fill="x", padx=8, pady=(0, 12))
        self._toggle_row(events_card.body, "Приглашения в группу (+ авто-принятие)",
                         self.monitor_event_vars["party_invite"])
        self._toggle_row(events_card.body, "Подземелья (лёгкое/среднее/сложное)",
                         self.monitor_event_vars["dungeons"])
        self._toggle_row(events_card.body, "Дикие рейды", self.monitor_event_vars["wild_raid"])
        events_card.refresh()

        # Карточка regex-паттернов
        patterns_card = ui.RoundedCard(parent, title="Шаблоны распознавания (regex)", radius=18)
        patterns_card.pack(fill="x", padx=8, pady=(0, 12))
        for key, label in PATTERN_LABELS.items():
            row = tk.Frame(patterns_card.body, bg=ui.COLOR_CARD)
            row.pack(fill="x", pady=3, padx=(8, 0))
            tk.Label(row, text=label, bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                     font=ui.font(9), width=34, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=self.pattern_vars[key]).pack(
                side="left", fill="x", expand=True, padx=(12, 8))
        tk.Label(patterns_card.body,
                 text="Именованные группы: (?P<player>…) — имя игрока, (?P<location>…) — локация.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=820).pack(anchor="w", pady=(8, 8), padx=(8, 0))
        patterns_card.refresh()

        # Карточка проверки успеха
        check_card = ui.RoundedCard(parent, title="Проверка успеха сценариев", radius=18)
        check_card.pack(fill="x", padx=8, pady=(0, 12))
        body = check_card.body
        row = tk.Frame(body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 8))
        tk.Label(row, text="Метод проверки:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left", padx=(8, 8))
        ui.SegmentedControl(row,
                            [("log", "Лог"), ("template", "Шаблон"), ("both", "Оба: лог → шаблон")],
                            self.check_mode_var).pack(side="left", padx=(12, 0))
        tk.Label(body, text="Строки-триггеры успеха (поиск без учёта регистра):",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(anchor="w", pady=(4, 4), padx=(8, 0))
        trig_row = tk.Frame(body, bg=ui.COLOR_CARD)
        trig_row.pack(fill="x", padx=(8, 0))
        self.triggers_listbox = tk.Listbox(trig_row, height=3, bg=ui.COLOR_FIELD, fg=ui.COLOR_TEXT,
                                           selectbackground=ui.COLOR_ACCENT, highlightthickness=0,
                                           borderwidth=0, font=ui.font(10))
        self.triggers_listbox.pack(side="left", fill="both", expand=True)
        trig_scroll = ttk.Scrollbar(trig_row, orient="vertical", command=self.triggers_listbox.yview)
        trig_scroll.pack(side="left", fill="y", padx=(4, 0))
        self.triggers_listbox.config(yscrollcommand=trig_scroll.set)
        add_row = tk.Frame(body, bg=ui.COLOR_CARD)
        add_row.pack(fill="x", pady=(4, 8))
        ttk.Entry(add_row, textvariable=self.new_trigger_var).pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._hb(add_row, "Добавить", self._add_trigger)
        self._hb(add_row, "Удалить выбранный", self._remove_selected_trigger)
        self._refresh_triggers_listbox()
        check_card.refresh()

        # Карточка авто-принятия приглашений
        accept_card = ui.RoundedCard(parent, title="Авто-принятие приглашений в группу", radius=18)
        accept_card.pack(fill="x", padx=8, pady=(0, 8))
        body = accept_card.body
        self._toggle_row(body, "Включить авто-принятие", self.acceptor_enabled_var)
        row = tk.Frame(body, bg=ui.COLOR_CARD)
        row.pack(fill="x", pady=(8, 6))
        tk.Label(row, text="Метод принятия:", bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED,
                 font=ui.font(10)).pack(side="left", padx=(8, 8))
        ui.SegmentedControl(row,
                            [("log_chat", "Лог + чат (рекомендуется)"),
                             ("opencv", "OpenCV-клик (резерв)"),
                             ("chat_click", "Клик по чату")],
                            self.acceptor_method_var).pack(side="left", padx=(12, 0))
        row2 = tk.Frame(body, bg=ui.COLOR_CARD)
        row2.pack(fill="x", pady=4, padx=(8, 0))
        tk.Label(row2, text="Таймаут приглашения (сек):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_MUTED, font=ui.font(10)).pack(side="left")
        ttk.Entry(row2, textvariable=self.acceptor_timeout_var, width=8).pack(side="left", padx=12)
        tk.Label(row2, text="приглашение действует 60 секунд",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(side="left")
        self._toggle_row(body, "Очередь при нескольких приглашениях подряд", self.acceptor_queue_var)
        tk.Label(body,
                 text="⚠ «Клик по чату» — экспериментальный метод. Рекомендуемый — «Лог + чат».",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 justify="left", wraplength=820).pack(anchor="w", pady=(8, 8), padx=(8, 0))
        ui.HoverButton(body, text="💾 Сохранить настройки мониторинга",
                       command=self._save_monitor_settings).pack(anchor="w", pady=(8, 8), padx=(8, 0))
        accept_card.refresh()

    # ---------- путь к логу ----------
    def _browse_log_path(self):
        path = filedialog.askopenfilename(
            title="Выбери лог игры latest.log",
            filetypes=[("Лог-файлы", "*.log"), ("Все файлы", "*.*")])
        if path:
            self.monitor_path_var.set(path)

    def _use_default_log_path(self):
        path = default_game_log_path()
        if path:
            self.monitor_path_var.set(path)
        else:
            messagebox.showwarning("Путь по умолчанию", "Не удалось определить %APPDATA% — укажи путь вручную.")

    # ---------- строки-триггеры успеха ----------
    def _refresh_triggers_listbox(self):
        self.triggers_listbox.delete(0, tk.END)
        for i, trigger in enumerate(self.log_triggers, 1):
            self.triggers_listbox.insert(tk.END, f"{i}. {trigger}")

    def _add_trigger(self):
        trigger = self.new_trigger_var.get().strip()
        if not trigger:
            messagebox.showinfo("Добавление триггера", "Введи строку, на которую нужно реагировать.")
            return
        if trigger.lower() in {t.lower() for t in self.log_triggers}:
            messagebox.showinfo("Добавление триггера", "Такой триггер уже есть в списке.")
            return
        self.log_triggers.append(trigger)
        self.new_trigger_var.set("")
        self._refresh_triggers_listbox()

    def _remove_selected_trigger(self):
        selection = self.triggers_listbox.curselection()
        if not selection:
            messagebox.showinfo("Удаление триггера", "Сначала выбери триггер в списке.")
            return
        del self.log_triggers[selection[0]]
        self._refresh_triggers_listbox()

    # ---------- сохранение настроек мониторинга ----------
    def _save_monitor_settings(self):
        try:
            timeout = int(self.acceptor_timeout_var.get())
            if timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Таймаут приглашения должен быть положительным числом.")
            return
        method = self.acceptor_method_var.get()
        if method not in ("log_chat", "opencv", "chat_click"):
            method = "log_chat"
        check_mode = self.check_mode_var.get()
        if check_mode not in ("log", "template", "both"):
            check_mode = "both"
        path = self.monitor_path_var.get().strip()
        self.settings["game_log_path"] = path
        self.settings["check_mode"] = check_mode
        self.settings["log_triggers"] = list(self.log_triggers)
        self.settings["log_monitor"] = {
            "enabled": bool(self.monitor_enabled_var.get()),
            "path": "",
            "patterns": {key: var.get().strip() for key, var in self.pattern_vars.items()},
            "events": {key: bool(var.get()) for key, var in self.monitor_event_vars.items()},
        }
        self.settings["party_acceptor"] = {
            "enabled": bool(self.acceptor_enabled_var.get()),
            "method": method,
            "timeout_seconds": timeout,
            "queue_enabled": bool(self.acceptor_queue_var.get()),
        }
        settings_module.save_settings(self.settings)
        messagebox.showinfo("Сохранено",
                            "Настройки мониторинга сохранены.\nbot.py подхватит их в течение 5 секунд.")

    def _save_scheduler_settings(self):
        try:
            warn = int(self.warn_minutes_var.get())
            if warn < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Время предупреждения должно быть числом ≥ 0.")
            return
        self.settings["scheduler"] = {
            "enabled": True,
            "warn_minutes_before": warn,
            "events": {key: bool(var.get()) for key, var in self.scheduler_event_vars.items()},
        }
        settings_module.save_settings(self.settings)
        messagebox.showinfo("Сохранено", "Настройки предупреждений сохранены.")

    # ---------- анимация переключения вкладок ----------
    def _on_tab_changed(self, _event):
        current = self.notebook.nametowidget(self.notebook.select())
        ui.fade_in(current)

    # ==================== ЛОГИКА ИЗ ПРЕДЫДУЩИХ ВЕРСИЙ ====================

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for i, step in enumerate(self.steps, 1):
            if step["type"] == "key_hold":
                text = f"{i}. Клавиша '{step['key']}' — удержание {step['duration_ms']} мс"
            else:
                text = f"{i}. Клик по координатам ({step['x']}, {step['y']})"
            self.listbox.insert(tk.END, text)

    def _delete_selected_step(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo("Удаление шага", "Сначала выбери шаг в списке.")
            return
        del self.steps[selection[0]]
        self._refresh_listbox()

    def _move_step(self, direction: int):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        new_index = index + direction
        if 0 <= new_index < len(self.steps):
            self.steps[index], self.steps[new_index] = self.steps[new_index], self.steps[index]
            self._refresh_listbox()
            self.listbox.selection_set(new_index)

    def _open_add_step_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Новый шаг")
        dialog.geometry("420x400")
        dialog.configure(bg=ui.COLOR_CARD)
        dialog.grab_set()
        step_type_var = tk.StringVar(value="key_hold")
        tk.Label(dialog, text="Тип шага", bg=ui.COLOR_CARD, fg=ui.COLOR_ACCENT_SOFT,
                 font=ui.font(11, True)).pack(anchor="w", padx=16, pady=(12, 6))
        type_frame = tk.Frame(dialog, bg=ui.COLOR_CARD)
        type_frame.pack(fill="x", padx=16)
        tk.Radiobutton(type_frame, text="Клавиша (удержание)", variable=step_type_var,
                       value="key_hold", bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                       selectcolor=ui.COLOR_FIELD, activebackground=ui.COLOR_CARD,
                       activeforeground=ui.COLOR_TEXT).pack(anchor="w")
        tk.Radiobutton(type_frame, text="Клик мышью", variable=step_type_var,
                       value="mouse_click", bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT,
                       selectcolor=ui.COLOR_FIELD, activebackground=ui.COLOR_CARD,
                       activeforeground=ui.COLOR_TEXT).pack(anchor="w")
        tk.Label(dialog, text="Клавиша (w/a/s/d или спец.: " + ", ".join(SPECIAL_KEYS) + "):",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 wraplength=380, justify="left").pack(anchor="w", padx=16, pady=(10, 4))
        key_var = tk.StringVar(value="w")
        ttk.Entry(dialog, textvariable=key_var).pack(fill="x", padx=16)
        tk.Label(dialog, text="Длительность удержания (мс):", bg=ui.COLOR_CARD,
                 fg=ui.COLOR_MUTED, font=ui.font(9)).pack(anchor="w", padx=16, pady=(8, 4))
        duration_var = tk.StringVar(value="1000")
        ttk.Entry(dialog, textvariable=duration_var).pack(fill="x", padx=16)
        tk.Label(dialog, text="Координаты клика (относительно окна Minecraft):",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9)).pack(anchor="w", padx=16, pady=(10, 4))
        click_row = tk.Frame(dialog, bg=ui.COLOR_CARD)
        click_row.pack(fill="x", padx=16)
        x_var = tk.StringVar(value="200")
        y_var = tk.StringVar(value="300")
        tk.Label(click_row, text="X:", bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT).pack(side="left")
        ttk.Entry(click_row, textvariable=x_var, width=10).pack(side="left", padx=(6, 16))
        tk.Label(click_row, text="Y:", bg=ui.COLOR_CARD, fg=ui.COLOR_TEXT).pack(side="left")
        ttk.Entry(click_row, textvariable=y_var, width=10).pack(side="left", padx=6)

        def on_confirm():
            step_type = step_type_var.get()
            try:
                if step_type == "key_hold":
                    key_name = key_var.get().strip()
                    duration_ms = int(duration_var.get())
                    if not key_name:
                        raise ValueError("Клавиша не может быть пустой.")
                    if duration_ms <= 0:
                        raise ValueError("Длительность должна быть положительным числом.")
                    self.steps.append({"type": "key_hold", "key": key_name, "duration_ms": duration_ms})
                else:
                    self.steps.append({"type": "mouse_click", "x": int(x_var.get()), "y": int(y_var.get())})
            except ValueError as e:
                messagebox.showerror("Ошибка ввода", f"Проверь введённые значения.\n{e}")
                return
            self._refresh_listbox()
            dialog.destroy()

        buttons = tk.Frame(dialog, bg=ui.COLOR_CARD)
        buttons.pack(fill="x", padx=16, pady=(16, 12))
        ui.HoverButton(buttons, text="Отмена", command=dialog.destroy,
                       bg=ui.COLOR_FIELD).pack(side="right", padx=6)
        ui.HoverButton(buttons, text="Добавить", command=on_confirm).pack(side="right")

    # ---------- ручная запись (recorder.py) ----------
    def _start_hold(self):
        key_name = self.record_key_var.get().strip()
        if not key_name:
            messagebox.showinfo("Запись", "Укажи клавишу перед началом удержания.")
            return
        self.recorder.start_key_hold(key_name)
        self.hold_button.set_enabled(False)
        self.finish_hold_button.set_enabled(True)

    def _finish_hold(self):
        step = self.recorder.finish_key_hold()
        self.hold_button.set_enabled(True)
        self.finish_hold_button.set_enabled(False)
        if step is None:
            return
        self.steps.append(step)
        self._refresh_listbox()

    def _capture_click(self):
        try:
            x = int(self.click_x_var.get())
            y = int(self.click_y_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "X и Y должны быть числами (относительно окна Minecraft).")
            return
        step = self.recorder.capture_click(x, y)
        self.steps.append(step)
        self._refresh_listbox()

    def _clear_recording(self):
        self.recorder.clear()

    # ---------- загрузка / сохранение сценария ----------
    def _build_scenario_dict(self):
        return {"chat_fallback_message": self.chat_message_var.get(), "steps": self.steps}

    def _load_scenario(self, path, silent=False):
        if not os.path.exists(path):
            if not silent:
                messagebox.showwarning("Файл не найден", f"Файл '{path}' не найден, начни с пустого сценария.")
            self.steps = []
            self.chat_message_var.set("")
            self._refresh_listbox()
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.steps = data.get("steps", [])
            self.chat_message_var.set(data.get("chat_fallback_message", ""))
            self.current_scenario_path.set(path)
            self._refresh_listbox()
        except Exception as e:
            messagebox.showerror("Ошибка загрузки", str(e))

    def _on_load_button(self):
        self._load_scenario(self.current_scenario_path.get())

    def _save_to_path(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._build_scenario_dict(), f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Сохранено", f"Сценарий сохранён в:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))

    def _on_save_button(self):
        self._save_to_path(self.current_scenario_path.get())

    def _save_scenario_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON файлы", "*.json")],
            initialfile=self.current_scenario_path.get(),
        )
        if path:
            self._save_to_path(path)
            self.current_scenario_path.set(path)

    # ---------- расписание ----------
    def _save_schedule(self):
        try:
            value = int(self.schedule_value_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Значение расписания должно быть числом.")
            return
        mode = self.schedule_mode_var.get()
        if mode == "fixed_minute" and not (0 <= value <= 59):
            messagebox.showerror("Ошибка", "Минута должна быть от 0 до 59.")
            return
        if mode == "every_n_minutes" and value <= 0:
            messagebox.showerror("Ошибка", "Интервал в минутах должен быть положительным числом.")
            return
        self.settings["schedule"] = {"mode": mode, "value": value}
        settings_module.save_settings(self.settings)
        messagebox.showinfo("Сохранено", "Расписание сохранено. bot.py подхватит его на следующей итерации цикла.")

    # ---------- хоткей ----------
    def _start_hotkey_listener(self):
        try:
            hotkey_str = normalize_hotkey_string(self.hotkey_var.get())
        except ValueError as e:
            print(f"[!] Не удалось запустить хоткей: {e}")
            return
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
        self._hotkey_listener = HotkeyListener(hotkey_str, self._on_hotkey_triggered)
        self._hotkey_listener.start()

    def _on_hotkey_triggered(self):
        self.after(0, self._toggle_bot_from_hotkey)

    def _toggle_bot_from_hotkey(self):
        if self.bot_process is not None and self.bot_process.poll() is None:
            self._stop_bot()
        else:
            self._start_bot()

    def _start_combo_capture(self):
        self.assign_hotkey_button.set_enabled(False)
        self.assign_hotkey_button.config(text="Нажми комбинацию...")

        def on_captured(combo):
            self.after(0, lambda: self._on_combo_captured(combo))

        self._combo_capture = SingleComboCapture(on_captured)
        self._combo_capture.start()

    def _on_combo_captured(self, combo):
        self.hotkey_var.set(combo)
        self.assign_hotkey_button.set_enabled(True)
        self.assign_hotkey_button.config(text="🎯 Назначить…")

    def _save_hotkey(self):
        try:
            hotkey_str = normalize_hotkey_string(self.hotkey_var.get())
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.settings["hotkey"] = hotkey_str
        settings_module.save_settings(self.settings)
        self._start_hotkey_listener()
        messagebox.showinfo("Сохранено", f"Хоткей '{hotkey_str}' сохранён и активен.")

    # ---------- диагностика ----------
    def _run_diagnostics(self):
        results = diagnostics.run_full_diagnostics(MINECRAFT_WINDOW_TITLE)
        report = diagnostics.format_report(results)
        self._diag_report = report
        self.diag_text.configure(state="normal")
        self.diag_text.delete("1.0", tk.END)
        self.diag_text.insert(tk.END, report)
        self.diag_text.configure(state="disabled")
        log_event("САМОПРОВЕРКА:\n" + report)
        passed = sum(1 for r in results if r["ok"])
        notifier.notify("Диагностика завершена",
                        f"Пройдено проверок: {passed}/{len(results)}",
                        event="on_diagnostics")

    def _export_diagnostics(self):
        if not self._diag_report:
            messagebox.showinfo("Экспорт", "Сначала запусти проверку готовности.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt")],
            initialfile="diagnostics_report.txt",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._diag_report)
            messagebox.showinfo("Сохранено", f"Отчёт сохранён в:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------- аудит проекта ----------
    def _run_audit(self):
        try:
            self._audit_report = audit.run_audit(".")
        except Exception as e:
            messagebox.showerror("Аудит", f"Не удалось выполнить аудит: {e}")
            return
        self.audit_text.configure(state="normal")
        self.audit_text.delete("1.0", tk.END)
        self.audit_text.insert(tk.END, audit.format_audit_report(self._audit_report))
        self.audit_text.configure(state="disabled")
        log_event("АУДИТ ПРОЕКТА:\n" + audit.format_audit_report(self._audit_report))
        candidates = audit.deletion_candidates(self._audit_report)
        self.audit_delete_button.set_enabled(bool(candidates))

    def _open_audit_delete_dialog(self):
        candidates = audit.deletion_candidates(self._audit_report or {})
        if not candidates:
            messagebox.showinfo("Аудит", "Нет файлов, которые можно предложить к удалению.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Удаление файлов")
        dialog.configure(bg=ui.COLOR_CARD)
        dialog.geometry(f"500x{min(180 + 28 * len(candidates), 540)}")
        dialog.grab_set()
        tk.Label(dialog, text="Отметь файлы для удаления. Критичные файлы проекта защищены и не показываются.",
                 bg=ui.COLOR_CARD, fg=ui.COLOR_MUTED, font=ui.font(9),
                 wraplength=460, justify="left").pack(anchor="w", padx=16, pady=(12, 8))
        list_frame = tk.Frame(dialog, bg=ui.COLOR_CARD)
        list_frame.pack(fill="both", expand=True, padx=16)
        vars_map = {}
        for path in candidates:
            var = tk.BooleanVar(value=False)
            vars_map[path] = var
            tk.Checkbutton(list_frame, text=path, variable=var, bg=ui.COLOR_CARD,
                           fg=ui.COLOR_TEXT, selectcolor=ui.COLOR_FIELD,
                           activebackground=ui.COLOR_CARD, activeforeground=ui.COLOR_TEXT,
                           font=ui.font(10)).pack(anchor="w")
        buttons = tk.Frame(dialog, bg=ui.COLOR_CARD)
        buttons.pack(fill="x", padx=16, pady=(10, 14))
        ui.HoverButton(buttons, text="Отмена", command=dialog.destroy,
                       bg=ui.COLOR_FIELD).pack(side="right", padx=6)
        ui.HoverButton(buttons, text="🗑 Удалить отмеченные",
                       command=lambda: self._delete_selected_audit_files(dialog, vars_map),
                       bg=ui.COLOR_ERROR).pack(side="right")

    def _delete_selected_audit_files(self, dialog, vars_map):
        selected = [path for path, var in vars_map.items() if var.get()]
        if not selected:
            messagebox.showinfo("Удаление", "Ни один файл не отмечен.")
            return
        if not messagebox.askyesno("Подтверждение",
                                   f"Точно удалить {len(selected)} файл(ов)?\n\n" + "\n".join(selected)):
            return
        errors = []
        for path in selected:
            try:
                os.remove(path)
            except Exception as e:
                errors.append(f"{path}: {e}")
        log_event(f"АУДИТ: удалено файлов по решению пользователя: {len(selected) - len(errors)}")
        if errors:
            messagebox.showwarning("Часть файлов не удалена", "\n".join(errors))
        dialog.destroy()
        self._run_audit()

    # ---------- уведомления ----------
    def _save_notifications(self):
        self.settings["notifications"] = {key: bool(var.get()) for key, var in self.notif_vars.items()}
        settings_module.save_settings(self.settings)

    def _send_test_notification(self):
        ok = notifier.notify("Тестовое уведомление",
                             "Так выглядят уведомления Minecraft Bot 🙂", force=True)
        if not ok:
            messagebox.showinfo("Тест уведомления",
                                "Системные уведомления недоступны (нет plyer или не поддерживается ОС).\n"
                                "Сообщение продублировано в консоль — фолбэк работает.")

    # ==================== ЗАПУСК БОТА ====================

    def _toggle_bot(self):
        """Единая кнопка старт/стоп."""
        if self.bot_process is not None and self.bot_process.poll() is None:
            self._stop_bot()
        else:
            self._start_bot()

    def _start_bot(self):
        if self.bot_process is not None and self.bot_process.poll() is None:
            messagebox.showinfo("Бот уже запущен", "Бот уже работает.")
            return
        self.status_badge.set_status("Запускается…", ui.COLOR_WARN)
        self.toggle_button.config(text="⏹ Остановить", bg=ui.COLOR_ERROR)
        self.toggle_button.set_enabled(False)
        self.update_idletasks()
        try:
            self._bot_stderr_file = tempfile.NamedTemporaryFile(
                mode="w+", prefix="bot_stderr_", suffix=".log", delete=False
            )
            self.bot_process = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                stdout=subprocess.DEVNULL,
                stderr=self._bot_stderr_file,
            )
        except Exception as e:
            self.status_badge.set_status(f"Ошибка: {e}", ui.COLOR_ERROR)
            self.toggle_button.config(text="▶ Запустить", bg=ui.COLOR_OK)
            self.toggle_button.set_enabled(True)
            log_event(f"ОШИБКА ЗАПУСКА GUI: не удалось запустить bot.py: {e}")
            return
        self.after(1500, self._check_startup_result)

    def _check_startup_result(self):
        if self.bot_process is None:
            return
        exit_code = self.bot_process.poll()
        if exit_code is None:
            self.status_badge.set_status(f"Работает (PID {self.bot_process.pid})", ui.COLOR_OK, pulse=True)
            self.toggle_button.config(text="⏹ Остановить", bg=ui.COLOR_ERROR)
            self.toggle_button.set_enabled(True)
            log_event(f"БОТ ЗАПУЩЕН (из GUI), PID {self.bot_process.pid}.")
            notifier.notify("Бот запущен", "Автоматизация работает в фоне.", event="on_bot_start")
            return
        error_text = ""
        try:
            self._bot_stderr_file.seek(0)
            error_text = self._bot_stderr_file.read().strip()
        except Exception:
            pass
        self.bot_process = None
        self.toggle_button.config(text="▶ Запустить", bg=ui.COLOR_OK)
        self.toggle_button.set_enabled(True)
        if error_text:
            self.status_badge.set_status("Ошибка при запуске", ui.COLOR_ERROR)
            messagebox.showerror("Бот завершился с ошибкой", error_text[-2000:])
            log_event(f"ОШИБКА ЗАПУСКА БОТА (код {exit_code}): {error_text[:1000]}")
        else:
            self.status_badge.set_status(f"Остановлен (код {exit_code})", ui.COLOR_ERROR)
            log_event(f"Бот завершился сразу после запуска без вывода ошибки (код {exit_code}).")
        notifier.notify("Ошибка запуска бота", "Подробности — в окне приложения и в логе.", event=None)

    def _stop_bot(self):
        if self.bot_process is None:
            return
        self.bot_process.terminate()
        self.bot_process = None
        self.status_badge.set_status("Остановлен", ui.COLOR_MUTED)
        self.toggle_button.config(text="▶ Запустить", bg=ui.COLOR_OK)
        self.toggle_button.set_enabled(True)
        log_event("БОТ ОСТАНОВЛЕН (из GUI).")
        notifier.notify("Бот остановлен", "Автоматизация остановлена пользователем.", event="on_bot_stop")

    def _refresh_run_tab(self):
        if self.bot_process is not None and self.bot_process.poll() is not None:
            self._check_startup_result()
        elif self.bot_process is not None:
            self.status_badge.set_status(f"Работает (PID {self.bot_process.pid})", ui.COLOR_OK, pulse=True)
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-150:]
                self.log_text.config(state="normal")
                self.log_text.delete("1.0", tk.END)
                self.log_text.insert(tk.END, "".join(lines))
                self.log_text.see(tk.END)
                self.log_text.config(state="disabled")
            except Exception:
                pass
        self.after(2000, self._refresh_run_tab)

    # ==================== ГЕОМЕТРИЯ ОКНА ====================
    def _load_geometry(self):
        geom = (self.settings.get("window") or {}).get("geometry", "")
        if geom:
            try:
                self.geometry(geom)
            except Exception:
                pass

    def _schedule_geometry_save(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            if self.state() != "normal":
                return
        except tk.TclError:
            return
        if self._geom_job:
            try:
                self.after_cancel(self._geom_job)
            except Exception:
                pass
        self._geom_job = self.after(600, self._save_geometry)

    def _save_geometry(self):
        try:
            self.settings.setdefault("window", {})["geometry"] = self.geometry()
            settings_module.save_settings(self.settings)
        except Exception:
            pass

    # ==================== ТРЕЙ И ЗАКРЫТИЕ ====================
    def _init_tray(self):
        if TrayIcon is None:
            return
        try:
            self.tray = TrayIcon(
                on_show=self._show_from_tray,
                on_toggle_bot=self._toggle_bot_from_tray,
                on_exit=self._on_close,
                is_bot_running=lambda: self.bot_process is not None and self.bot_process.poll() is None,
            )
            self.tray.start()
        except Exception as e:
            print(f"[!] Трей недоступен: {e}")
            self.tray = None

    def _on_window_close(self):
        if self.tray is not None:
            self._minimize_to_tray()
        else:
            self._on_close()

    def _minimize_to_tray(self):
        self._save_geometry()
        if self.tray is not None:
            self.withdraw()
        else:
            self.iconify()

    def _show_from_tray(self):
        self.after(0, self._show_window_on_gui_thread)

    def _show_window_on_gui_thread(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _toggle_bot_from_tray(self):
        self.after(0, self._toggle_bot_from_hotkey)

    def _on_close(self):
        self._save_geometry()
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
        if self._combo_capture is not None:
            self._combo_capture.stop()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
