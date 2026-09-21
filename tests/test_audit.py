"""tests/test_audit.py — аудит проекта: неиспользуемые файлы, битые JSON, whitelist."""
import audit


def test_audit_detects_unused_and_broken(tmp_path):
    (tmp_path / "app.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "dead_code.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "tray.py").write_text("Y = 2\n", encoding="utf-8")      # критичный, но "не используется"
    (tmp_path / "good.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")

    report = audit.run_audit(str(tmp_path))

    unused = {item["file"] for item in report["unused_files"]}
    assert "dead_code.py" in unused
    assert "app.py" not in unused and "helper.py" not in unused  # граф импортов работает
    assert "tray.py" not in unused  # критичные файлы не попадают в список

    broken = {item["file"] for item in report["broken_json"]}
    assert broken == {"bad.json"}


def test_deletion_candidates_never_include_critical(tmp_path):
    (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "tray.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "orphan.json").write_text("{bad", encoding="utf-8")
    report = audit.run_audit(str(tmp_path))
    candidates = audit.deletion_candidates(report)
    assert "orphan.json" in candidates
    assert all(c not in audit.CRITICAL_FILES for c in candidates)