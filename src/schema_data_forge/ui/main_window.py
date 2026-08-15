"""The main window: AI panel on the left, schema and generated data on the right."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Slot
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..examples import Example, load_examples
from ..generator import DEFAULT_MAX_ATTEMPTS, GenerationRequest
from ..llm import API_KEY_ENV, DEFAULT_BASE_URL, DeepSeekClient
from ..models import GenerationAttempt, GenerationResult, SchemaKind, ValidationReport
from ..validation import detect_schema_kind, format_document, validate, xsd_root_elements
from .highlighter import SchemaHighlighter
from .worker import GenerationWorker, start_worker

_MODELS = ["deepseek-chat", "deepseek-reasoner"]
_KINDS: list[tuple[str, SchemaKind]] = [
    ("XML Schema (XSD)", SchemaKind.XML_SCHEMA),
    ("JSON Schema", SchemaKind.JSON_SCHEMA),
]


def _mono_editor(*, read_only: bool = False, placeholder: str = "") -> QPlainTextEdit:
    editor = QPlainTextEdit()
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    editor.setFont(font)
    editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    editor.setReadOnly(read_only)
    editor.setPlaceholderText(placeholder)
    return editor


class MainWindow(QMainWindow):
    """Editor window wiring the schema editors to the DeepSeek-backed generator."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Schema Data Forge — AI 示例数据生成器")
        self.resize(1500, 950)

        self._settings = QSettings("schema-data-forge", "editor")
        self._examples: list[Example] = load_examples()
        self._thread: QThread | None = None
        self._worker: GenerationWorker | None = None

        self._build_ui()
        self._build_menu()
        self._restore_settings()
        self._load_example(0)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_ai_panel())
        splitter.addWidget(self._build_document_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([460, 1040])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("就绪")

    def _build_ai_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        model_box = QGroupBox("DeepSeek 模型设置")
        form = QFormLayout(model_box)
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText(f"sk-...  (也可用环境变量 {API_KEY_ENV})")
        self._model_combo = QComboBox()
        self._model_combo.addItems(_MODELS)
        self._model_combo.setEditable(True)
        self._base_url_edit = QLineEdit(DEFAULT_BASE_URL)
        self._temperature_spin = QDoubleSpinBox()
        self._temperature_spin.setRange(0.0, 2.0)
        self._temperature_spin.setSingleStep(0.1)
        self._temperature_spin.setValue(0.4)
        self._attempts_spin = QSpinBox()
        self._attempts_spin.setRange(1, 10)
        self._attempts_spin.setValue(DEFAULT_MAX_ATTEMPTS)
        self._attempts_spin.setToolTip("校验失败时把错误回灌给模型重试的最大次数")
        form.addRow("API Key", self._api_key_edit)
        form.addRow("模型", self._model_combo)
        form.addRow("Base URL", self._base_url_edit)
        form.addRow("Temperature", self._temperature_spin)
        form.addRow("最大尝试次数", self._attempts_spin)
        layout.addWidget(model_box)

        prompt_box = QGroupBox("生成要求（会附加到提示词）")
        prompt_layout = QVBoxLayout(prompt_box)
        self._instructions_edit = _mono_editor(
            placeholder="例如：生成 3 个对象类型，其中一个包含地理坐标属性；时间统一为 2024 年。"
        )
        self._instructions_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._instructions_edit.setMaximumHeight(150)
        prompt_layout.addWidget(self._instructions_edit)
        layout.addWidget(prompt_box)

        buttons = QHBoxLayout()
        self._generate_button = QPushButton("生成并校验")
        self._generate_button.setDefault(True)
        self._generate_button.clicked.connect(self._on_generate)
        self._cancel_button = QPushButton("停止")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._on_cancel)
        buttons.addWidget(self._generate_button)
        buttons.addWidget(self._cancel_button)
        layout.addLayout(buttons)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        log_box = QGroupBox("生成 / 校验日志")
        log_layout = QVBoxLayout(log_box)
        self._log_view = _mono_editor(read_only=True, placeholder="生成过程会显示在这里")
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        log_layout.addWidget(self._log_view)
        layout.addWidget(log_box, stretch=1)

        return panel

    def _build_document_panel(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)

        schema_panel = QWidget()
        schema_layout = QVBoxLayout(schema_panel)
        schema_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Schema 类型"))
        self._kind_combo = QComboBox()
        for label, kind in _KINDS:
            self._kind_combo.addItem(label, kind)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        toolbar.addWidget(self._kind_combo)
        toolbar.addWidget(QLabel("根元素"))
        self._root_combo = QComboBox()
        self._root_combo.setEditable(True)
        self._root_combo.setMinimumWidth(220)
        toolbar.addWidget(self._root_combo)
        toolbar.addWidget(QLabel("示例"))
        self._example_combo = QComboBox()
        for example in self._examples:
            self._example_combo.addItem(example.title)
        self._example_combo.currentIndexChanged.connect(self._load_example)
        toolbar.addWidget(self._example_combo)
        toolbar.addStretch(1)
        open_button = QPushButton("打开 Schema…")
        open_button.clicked.connect(self._open_schema)
        toolbar.addWidget(open_button)
        schema_layout.addLayout(toolbar)

        self._schema_edit = _mono_editor(placeholder="在此粘贴 JSON Schema 或 XSD")
        self._schema_highlighter = SchemaHighlighter(
            self._schema_edit.document(), SchemaKind.XML_SCHEMA
        )
        self._schema_edit.textChanged.connect(self._on_schema_changed)
        schema_layout.addWidget(QLabel("Schema 定义"))
        schema_layout.addWidget(self._schema_edit, stretch=1)

        data_panel = QWidget()
        data_layout = QVBoxLayout(data_panel)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_toolbar = QHBoxLayout()
        data_toolbar.addWidget(QLabel("生成的数据"))
        data_toolbar.addStretch(1)
        validate_button = QPushButton("重新校验")
        validate_button.clicked.connect(self._on_validate)
        format_button = QPushButton("格式化")
        format_button.clicked.connect(self._on_format)
        save_button = QPushButton("保存数据…")
        save_button.clicked.connect(self._save_data)
        for button in (validate_button, format_button, save_button):
            data_toolbar.addWidget(button)
        data_layout.addLayout(data_toolbar)

        self._data_edit = _mono_editor(placeholder="生成结果会显示在这里，可直接编辑后重新校验")
        self._data_highlighter = SchemaHighlighter(
            self._data_edit.document(), SchemaKind.XML_SCHEMA
        )
        data_layout.addWidget(self._data_edit, stretch=3)

        self._status_label = QLabel("尚未校验")
        self._status_label.setStyleSheet("font-weight: bold;")
        data_layout.addWidget(self._status_label)
        self._issue_tree = QTreeWidget()
        self._issue_tree.setHeaderLabels(["位置", "行", "校验错误"])
        self._issue_tree.setColumnWidth(0, 320)
        self._issue_tree.setColumnWidth(1, 60)
        self._issue_tree.itemActivated.connect(self._on_issue_activated)
        data_layout.addWidget(self._issue_tree, stretch=2)

        splitter.addWidget(schema_panel)
        splitter.addWidget(data_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([420, 520])
        return splitter

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("打开 Schema…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_schema)
        save_action = QAction("保存生成数据…", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_data)
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        run_menu = self.menuBar().addMenu("生成")
        generate_action = QAction("生成并校验", self)
        generate_action.setShortcut("Ctrl+Return")
        generate_action.triggered.connect(self._on_generate)
        validate_action = QAction("重新校验", self)
        validate_action.setShortcut("Ctrl+Shift+V")
        validate_action.triggered.connect(self._on_validate)
        run_menu.addAction(generate_action)
        run_menu.addAction(validate_action)

    # ---------------------------------------------------------------- settings

    def _restore_settings(self) -> None:
        stored_key = str(self._settings.value("api_key", "") or "")
        self._api_key_edit.setText(stored_key or os.environ.get(API_KEY_ENV, ""))
        self._model_combo.setCurrentText(str(self._settings.value("model", _MODELS[0])))
        self._base_url_edit.setText(str(self._settings.value("base_url", DEFAULT_BASE_URL)))
        self._temperature_spin.setValue(float(str(self._settings.value("temperature", 0.4))))
        self._attempts_spin.setValue(
            int(str(self._settings.value("max_attempts", DEFAULT_MAX_ATTEMPTS)))
        )

    def _store_settings(self) -> None:
        self._settings.setValue("api_key", self._api_key_edit.text().strip())
        self._settings.setValue("model", self._model_combo.currentText().strip())
        self._settings.setValue("base_url", self._base_url_edit.text().strip())
        self._settings.setValue("temperature", self._temperature_spin.value())
        self._settings.setValue("max_attempts", self._attempts_spin.value())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self._store_settings()
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)

    # ------------------------------------------------------------------- state

    @property
    def kind(self) -> SchemaKind:
        kind = self._kind_combo.currentData()
        return kind if isinstance(kind, SchemaKind) else SchemaKind.JSON_SCHEMA

    def _set_kind(self, kind: SchemaKind) -> None:
        index = self._kind_combo.findData(kind)
        if index >= 0 and index != self._kind_combo.currentIndex():
            self._kind_combo.setCurrentIndex(index)

    @Slot(int)
    def _on_kind_changed(self, _index: int) -> None:
        self._schema_highlighter.set_kind(self.kind)
        self._data_highlighter.set_kind(self.kind)
        self._refresh_root_elements()

    def _on_schema_changed(self) -> None:
        self._refresh_root_elements()

    def _refresh_root_elements(self) -> None:
        if self.kind is not SchemaKind.XML_SCHEMA:
            self._root_combo.clear()
            self._root_combo.setEnabled(False)
            return
        self._root_combo.setEnabled(True)
        current = self._root_combo.currentText()
        names = xsd_root_elements(self._schema_edit.toPlainText())
        if names == [self._root_combo.itemText(i) for i in range(self._root_combo.count())]:
            return
        self._root_combo.clear()
        self._root_combo.addItems(names)
        if current in names:
            self._root_combo.setCurrentText(current)

    @Slot(int)
    def _load_example(self, index: int) -> None:
        if not self._examples or not 0 <= index < len(self._examples):
            return
        example = self._examples[index]
        self._set_kind(example.kind)
        self._schema_edit.setPlainText(example.schema_text)
        self._instructions_edit.setPlainText(example.instructions)
        self._refresh_root_elements()
        if example.root_element:
            self._root_combo.setCurrentText(example.root_element)
        self.statusBar().showMessage(f"已载入示例：{example.title}")

    # ------------------------------------------------------------------ file IO

    def _open_schema(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 Schema",
            "",
            "Schema 文件 (*.xsd *.json *.schema.json);;所有文件 (*.*)",
        )
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        self._schema_edit.setPlainText(text)
        self._set_kind(detect_schema_kind(text))
        self._refresh_root_elements()
        self.statusBar().showMessage(f"已打开 {path}")

    def _save_data(self) -> None:
        suffix = "xml" if self.kind is SchemaKind.XML_SCHEMA else "json"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存生成数据", f"sample.{suffix}", f"数据文件 (*.{suffix});;所有文件 (*.*)"
        )
        if not path:
            return
        Path(path).write_text(self._data_edit.toPlainText(), encoding="utf-8")
        self.statusBar().showMessage(f"已保存 {path}")

    # ---------------------------------------------------------------- reporting

    def _log(self, message: str) -> None:
        self._log_view.appendPlainText(message)

    def _show_report(self, report: ValidationReport) -> None:
        self._issue_tree.clear()
        if report.schema_error is not None:
            self._status_label.setText("Schema 无法编译")
            self._status_label.setStyleSheet("color: #b00020; font-weight: bold;")
            self._issue_tree.addTopLevelItem(QTreeWidgetItem(["<schema>", "", report.schema_error]))
            return
        if report.parse_error is not None:
            self._status_label.setText("文档解析失败")
            self._status_label.setStyleSheet("color: #b00020; font-weight: bold;")
            self._issue_tree.addTopLevelItem(
                QTreeWidgetItem(["<document>", "", report.parse_error])
            )
            return
        if report.is_valid:
            self._status_label.setText("校验通过：0 个错误")
            self._status_label.setStyleSheet("color: #1b7f3b; font-weight: bold;")
            return
        self._status_label.setText(f"校验失败：{len(report.issues)} 个错误")
        self._status_label.setStyleSheet("color: #b00020; font-weight: bold;")
        for issue in report.issues:
            item = QTreeWidgetItem(
                [issue.location or "<document>", str(issue.line or ""), issue.message]
            )
            if issue.line is not None:
                item.setData(0, Qt.ItemDataRole.UserRole, issue.line)
            self._issue_tree.addTopLevelItem(item)

    def _on_issue_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(line, int):
            return
        cursor = self._data_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        cursor.movePosition(cursor.MoveOperation.Down, n=max(0, line - 1))
        self._data_edit.setTextCursor(cursor)
        self._data_edit.centerCursor()

    # ----------------------------------------------------------------- actions

    def _on_validate(self) -> None:
        document = self._data_edit.toPlainText().strip()
        if not document:
            self.statusBar().showMessage("没有可校验的数据")
            return
        report = validate(document, self._schema_edit.toPlainText(), self.kind)
        self._show_report(report)
        self._log(
            "手动校验：通过" if report.is_valid else f"手动校验：{report.as_feedback(limit=5)}"
        )

    def _on_format(self) -> None:
        self._data_edit.setPlainText(format_document(self._data_edit.toPlainText(), self.kind))

    def _build_client(self) -> DeepSeekClient | None:
        api_key = self._api_key_edit.text().strip() or os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "缺少 API Key",
                f"请输入 DeepSeek API Key，或设置环境变量 {API_KEY_ENV}。",
            )
            return None
        return DeepSeekClient(
            api_key=api_key,
            model=self._model_combo.currentText().strip() or _MODELS[0],
            base_url=self._base_url_edit.text().strip() or DEFAULT_BASE_URL,
            temperature=self._temperature_spin.value(),
        )

    def _on_generate(self) -> None:
        if self._thread is not None:
            return
        schema_text = self._schema_edit.toPlainText().strip()
        if not schema_text:
            QMessageBox.warning(self, "缺少 Schema", "请先填入 JSON Schema 或 XSD。")
            return
        client = self._build_client()
        if client is None:
            return

        self._store_settings()
        request = GenerationRequest(
            schema_text=schema_text,
            kind=self.kind,
            instructions=self._instructions_edit.toPlainText(),
            root_element=self._root_combo.currentText().strip(),
            max_attempts=self._attempts_spin.value(),
        )

        self._issue_tree.clear()
        self._status_label.setText("生成中…")
        self._status_label.setStyleSheet("font-weight: bold;")
        self._log(
            f"--- 开始生成（{self.kind.data_format}，模型 {client.model}，"
            f"最多 {request.max_attempts} 次尝试）---"
        )
        self._set_running(True)

        worker = GenerationWorker(client, request)
        worker.attempt_finished.connect(self._on_attempt)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        self._thread = start_worker(worker)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._log("已请求停止，将在当前尝试结束后中止。")
            self._cancel_button.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self._generate_button.setEnabled(not running)
        self._cancel_button.setEnabled(running)
        self._progress.setVisible(running)

    @Slot(object)
    def _on_attempt(self, attempt: GenerationAttempt) -> None:
        if attempt.document:
            self._data_edit.setPlainText(attempt.document)
        self._show_report(attempt.report)
        if attempt.is_valid:
            self._log(f"第 {attempt.index} 次尝试：校验通过 ✔")
        else:
            self._log(f"第 {attempt.index} 次尝试：校验失败\n{attempt.report.as_feedback(limit=8)}")

    @Slot(object)
    def _on_finished(self, result: GenerationResult) -> None:
        if result.succeeded:
            self._log(f"完成：第 {len(result.attempts)} 次尝试后通过校验。")
            self.statusBar().showMessage("生成完成，数据已通过 Schema 校验")
        else:
            self._log("完成：达到最大尝试次数，数据仍未通过校验。")
            self.statusBar().showMessage("生成结束，但数据未通过校验")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._log(f"错误：{message}")
        self._status_label.setText("生成失败")
        self._status_label.setStyleSheet("color: #b00020; font-weight: bold;")
        self.statusBar().showMessage("生成失败")
        QMessageBox.critical(self, "生成失败", message)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._set_running(False)
