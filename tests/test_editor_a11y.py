from __future__ import annotations

from pathlib import Path

STYLES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "schema_data_forge"
    / "web"
    / "static"
    / "styles.css"
)


def test_editor_focus_and_contrast_tokens() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert "--text-faint: #8b93a7;" in css
    assert "--text-faint: #626b7f;" not in css
    assert "input:focus-visible" in css
    assert "select:focus-visible" in css
    assert "textarea:focus-visible" in css
    assert "button.link:focus-visible" in css
    assert ".file-button:focus-visible" in css
    assert "button:focus-visible" in css
    assert "details.config summary:focus-visible" in css
