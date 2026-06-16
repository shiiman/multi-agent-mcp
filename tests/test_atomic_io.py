"""atomic_io のテスト。"""

import json
import stat

from src.managers.atomic_io import atomic_write_json, atomic_write_text


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "sub" / "a.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert target.parent.is_dir()


def test_atomic_write_text_sets_private_mode_by_default(tmp_path):
    target = tmp_path / "a.txt"
    atomic_write_text(target, "x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_text_skips_chmod_when_mode_none(tmp_path):
    target = tmp_path / "a.txt"
    atomic_write_text(target, "x", mode=None)
    assert target.read_text(encoding="utf-8") == "x"


def test_atomic_write_text_no_temp_left_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.managers.atomic_io.os.replace", boom)
    try:
        atomic_write_text(target, "x")
    except RuntimeError:
        pass
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json_roundtrip(tmp_path):
    target = tmp_path / "a.json"
    atomic_write_json(target, {"k": "v", "n": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v", "n": 1}


def test_atomic_write_json_uses_default_str_for_nonserializable(tmp_path):
    from datetime import datetime

    target = tmp_path / "a.json"
    atomic_write_json(target, {"t": datetime(2026, 1, 1)})
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert "2026" in loaded["t"]
