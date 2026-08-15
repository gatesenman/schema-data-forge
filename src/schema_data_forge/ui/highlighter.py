"""Lightweight JSON and XML syntax highlighting for the editors."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from ..models import SchemaKind


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    text_format = QTextCharFormat()
    text_format.setForeground(QColor(color))
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    text_format.setFontItalic(italic)
    return text_format


_JSON_RULES: list[tuple[str, QTextCharFormat]] = [
    (r'"(\\.|[^"\\])*"\s*:', _fmt("#0b6ec9", bold=True)),
    (r'"(\\.|[^"\\])*"', _fmt("#a31515")),
    (r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b", _fmt("#098658")),
    (r"\b(true|false|null)\b", _fmt("#7f00ff", bold=True)),
]

_XML_RULES: list[tuple[str, QTextCharFormat]] = [
    (r"</?[\w:.-]+", _fmt("#0b6ec9", bold=True)),
    (r"/?>", _fmt("#0b6ec9", bold=True)),
    (r"\b[\w:.-]+(?=\s*=)", _fmt("#7f00ff")),
    (r'"(\\.|[^"\\])*"', _fmt("#a31515")),
    (r"<!--[^\n]*-->", _fmt("#6a9955", italic=True)),
    (r"<\?[^\n]*\?>", _fmt("#6a9955", italic=True)),
]


class SchemaHighlighter(QSyntaxHighlighter):
    """Applies JSON or XML colouring depending on the active schema kind."""

    def __init__(self, document: QTextDocument, kind: SchemaKind) -> None:
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self.set_kind(kind)

    def set_kind(self, kind: SchemaKind) -> None:
        rules = _JSON_RULES if kind is SchemaKind.JSON_SCHEMA else _XML_RULES
        self._rules = [(QRegularExpression(pattern), fmt) for pattern, fmt in rules]
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt naming
        for expression, text_format in self._rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)
