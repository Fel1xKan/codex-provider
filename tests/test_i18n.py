from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from lib.xpx import i18n


def test_detect_system_language_env(monkeypatch) -> None:
    monkeypatch.setenv("XPX_LANG", "zh_CN")
    assert i18n.detect_system_language() == "zh"

    monkeypatch.setenv("XPX_LANG", "en_US")
    assert i18n.detect_system_language() == "en"

    monkeypatch.delenv("XPX_LANG", raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    with patch("lib.xpx.i18n.get_xpx_home", return_value=Path("/nonexistent")):
        assert i18n.detect_system_language() == "zh"

    monkeypatch.setenv("LANG", "en_US.UTF-8")
    with patch("lib.xpx.i18n.get_xpx_home", return_value=Path("/nonexistent")):
        assert i18n.detect_system_language() == "en"


def test_detect_system_language_from_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XPX_LANG", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)

    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"language": "zh"}), encoding="utf-8")

    with patch("lib.xpx.i18n.get_xpx_home", return_value=tmp_path):
        assert i18n.detect_system_language() == "zh"


def test_get_and_set_language(tmp_path: Path) -> None:
    # Test switching without persist
    i18n.set_language("en")
    assert i18n.get_language() == "en"

    i18n.set_language("zh")
    assert i18n.get_language() == "zh"

    # Test persist
    with patch("lib.xpx.i18n.ensure_xpx_dirs", return_value=tmp_path):
        i18n.set_language("en", persist=True)
        assert (tmp_path / "settings.json").is_file()
        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert data.get("language") == "en"


def test_t_translation() -> None:
    i18n.set_language("zh")
    assert i18n.t("ui.yes") == "是 (Yes)"
    assert i18n.t("ui.overflow_up", count=3) == "▲ ... (上方还有 3 项)"

    i18n.set_language("en")
    assert i18n.t("ui.yes") == "Yes"
    assert i18n.t("ui.overflow_up", count=3) == "▲ ... (3 more above)"

    # Fallback to key if unknown
    assert i18n.t("unknown.key.foo") == "unknown.key.foo"
    # Custom default
    assert i18n.t("unknown.key.bar", default="Fallback") == "Fallback"
