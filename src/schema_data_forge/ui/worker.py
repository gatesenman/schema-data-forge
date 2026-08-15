"""Background worker so generation never blocks the Qt event loop."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..generator import GenerationRequest, SampleDataGenerator
from ..llm import LLMClient, LLMError
from ..models import GenerationAttempt, GenerationResult


class GenerationWorker(QObject):
    """Runs one :class:`GenerationRequest` on a worker thread."""

    attempt_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, client: LLMClient, request: GenerationRequest) -> None:
        super().__init__()
        self._client = client
        self._request = request
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _on_attempt(self, attempt: GenerationAttempt) -> None:
        self.attempt_finished.emit(attempt)

    def run(self) -> None:
        try:
            result: GenerationResult = SampleDataGenerator(self._client).generate(
                self._request,
                on_attempt=self._on_attempt,
                should_cancel=lambda: self._cancelled,
            )
        except LLMError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.failed.emit(f"unexpected error: {exc}")
            return
        self.finished.emit(result)


def start_worker(worker: GenerationWorker) -> QThread:
    """Move ``worker`` onto a fresh thread, start it and wire up cleanup."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread
