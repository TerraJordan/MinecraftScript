"""
audit.py — аудит файлов проекта.
Сканирует корень проекта и папку tests/, строит граф импортов между
модулями и находит:
  - неиспользуемые файлы (модуль никто не импортирует / имя файла не
    встречается в коде);
  - битые JSON-файлы;
  - битые изображения (.png);
  - импорты, которые не удаётся разрешить в текущем окружении.
Модуль только готовит отчёт. Удалять файлы может исключительно
пользователь через GUI-диалог с подтверждением. Критичные файлы
(белый список) никогда не предлагаются к удалению.
"""

import ast
import importlib.util
import json
import os

# Белый список: ядро проекта, никогда не предлагается к удалению
CRITICAL_FILES = {
    "app.py", "bot.py", "settings.py", "settings.json",
    "hotkey.py", "movement.py", "recorder.py", "diagnostics.py",
    "tray.py", "notifier.py", "audit.py", "ui_widgets.py",
    "log_monitor.py", "party_acceptor.py", "scheduler.py",
    "party_checker.py", "message_scheduler.py"
}

# Точки входа: считаются используемыми сами по себе
ENTRY_POINTS = {"app.py", "bot.py", "picker.py"}

SCAN_EXTENSIONS = {".py", ".json", ".png", ".txt"}


def _list_files(root="."):
    """Список относительных путей: корень проекта + папка tests/."""
    files = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path) and os.path.splitext(name)[1].lower() in SCAN_EXTENSIONS:
            files.append(name)
    tests_dir = os.path.join(root, "tests")
    if os.path.isdir(tests_dir):
        for name in sorted(os.listdir(tests_dir)):
            path = os.path.join(tests_dir, name)
            if os.path.isfile(path) and name.endswith(".py"):
                files.append(os.path.join("tests", name))
    return files


def _extract_imports(py_path):
    """Список импортируемых модулей верхнего уровня из .py файла (через AST)."""
    try:
        with open(py_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=py_path)
    except Exception:
        return []
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.append(node.module.split(".")[0])
    return modules


def _is_stdlib_or_installed(module_name: str) -> bool:
    """True, если модуль находится (стандартная библиотека или установлен)."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _check_json(path):
    """Возвращает текст ошибки или None, если JSON читается."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return None
    except Exception as e:
        return f"не читается как JSON: {e}"


def _check_image(path):
    """Возвращает текст ошибки или None, если изображение читается (PIL, затем cv2)."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        return None
    except Exception:
        try:
            import cv2
            if cv2.imread(path, cv2.IMREAD_COLOR) is not None:
                return None
        except Exception:
            pass
        return "изображение не читается (PIL/cv2)"


def run_audit(root="."):
    """
    Полный аудит. Возвращает словарь:
    {
      "unused_files":    [{"file": ..., "reason": ...}, ...],
      "broken_json":     [{"file": ..., "reason": ...}, ...],
      "broken_images":   [{"file": ..., "reason": ...}, ...],
      "missing_imports": [{"file": ..., "module": ..., "reason": ...}, ...],
    }
    """
    files = _list_files(root)
    py_files = [f for f in files if f.endswith(".py")]
    local_modules = {os.path.splitext(os.path.basename(f))[0] for f in py_files}

    imports_by_file = {f: _extract_imports(os.path.join(root, f)) for f in py_files}
    sources = {}
    for f in py_files:
        try:
            with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                sources[f] = fh.read()
        except Exception:
            sources[f] = ""

    # --- граф импортов: достижимость от точек входа и тестов ---
    used_modules = set()

    def mark(module_name):
        if module_name in local_modules and module_name not in used_modules:
            used_modules.add(module_name)
            for dep in imports_by_file.get(module_name + ".py", []):
                mark(dep)

    entry_modules = {os.path.splitext(f)[0] for f in ENTRY_POINTS}
    entry_modules |= {
        os.path.splitext(os.path.basename(f))[0]
        for f in py_files
        if f.startswith("tests") or os.path.basename(f) == "conftest.py"
    }
    for m in entry_modules:
        mark(m)
    used_modules.add("conftest")  # служебный файл pytest

    all_source = "\n".join(sources.values())

    unused_files = []
    for f in files:
        base = os.path.basename(f)
        if f.endswith(".py"):
            module = os.path.splitext(base)[0]
            if module in used_modules:
                continue
            unused_files.append({"file": f, "reason": "модуль никто не импортирует"})
        else:
            # не-.py файл считается используемым, если его имя упоминается в коде
            if base not in all_source:
                unused_files.append({"file": f, "reason": "имя файла не встречается в коде"})

    # --- целостность данных (проверяем все json/png, независимо от использования) ---
    broken_json, broken_images = [], []
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        full = os.path.join(root, f)
        if ext == ".json":
            err = _check_json(full)
            if err:
                broken_json.append({"file": f, "reason": err})
        elif ext == ".png":
            err = _check_image(full)
            if err:
                broken_images.append({"file": f, "reason": err})

    # --- недостающие импорты ---
    missing_imports, seen = [], set()
    for f, mods in imports_by_file.items():
        for m in mods:
            if m in local_modules or (f, m) in seen:
                continue
            seen.add((f, m))
            if not _is_stdlib_or_installed(m):
                missing_imports.append(
                    {"file": f, "module": m, "reason": "модуль не найден в окружении"}
                )

    # критичные файлы никогда не попадают в список "предложить к удалению"
    unused_files = [u for u in unused_files if os.path.basename(u["file"]) not in CRITICAL_FILES]
    return {
        "unused_files": unused_files,
        "broken_json": broken_json,
        "broken_images": broken_images,
        "missing_imports": missing_imports,
    }


def deletion_candidates(report) -> list:
    """Файлы, которые можно предложить к удалению (без критичных, без дублей)."""
    candidates, seen = [], set()
    for section in ("unused_files", "broken_json", "broken_images"):
        for item in report.get(section, []):
            path = item["file"]
            if path in seen or os.path.basename(path) in CRITICAL_FILES:
                continue
            seen.add(path)
            candidates.append(path)
    return candidates


def format_audit_report(report) -> str:
    """Текстовый отчёт для вывода в GUI/лог."""
    lines = ["АУДИТ ПРОЕКТА", ""]

    def section(title, items, render):
        lines.append(f"• {title}: {len(items)}")
        for item in items:
            lines.append("   " + render(item))
        lines.append("")

    section("Неиспользуемые файлы", report.get("unused_files", []),
            lambda i: f"{i['file']} — {i['reason']}")
    section("Битые JSON", report.get("broken_json", []),
            lambda i: f"{i['file']} — {i['reason']}")
    section("Битые изображения", report.get("broken_images", []),
            lambda i: f"{i['file']} — {i['reason']}")
    section("Недостающие импорты", report.get("missing_imports", []),
            lambda i: f"{i['file']}: нет модуля '{i['module']}'")
    lines.append("Критичные файлы защищены и не предлагаются к удалению.")
    return "\n".join(lines)