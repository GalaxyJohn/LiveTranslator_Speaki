# SPEAKI/ui/main_window.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import os
import time
from typing import Dict, List, Tuple

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.stt_engine import STTConfig, STTEngine
from core.config import AppSettings
from core.translator import create_translator_from_settings, TranslatorError, RateLimiter
from .settings_dialog import SettingsDialog


SETTINGS_PATH = "settings.json"
logger = logging.getLogger(__name__)


class STTWorker(QObject):
    partial_result = Signal(str)
    final_result = Signal(int, str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, config: STTConfig) -> None:
        super().__init__()
        self._config = config
        self._engine: STTEngine | None = None
        self._sentence_id = 0

    def _on_partial(self, text: str) -> None:
        self.partial_result.emit(text)

    def _on_final(self, text: str) -> None:
        self._sentence_id += 1
        self.final_result.emit(self._sentence_id, text)

    @Slot()
    def run(self) -> None:
        try:
            self._engine = STTEngine(
                self._config,
                on_partial=self._on_partial,
                on_final=self._on_final,
            )
            self._engine.run()
        except Exception as exc:
            logger.exception("STT worker crashed")
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    @Slot()
    def stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        if self._engine is not None:
            self._engine.set_paused(paused)

    @Slot()
    def clear_audio_backlog(self) -> None:
        if self._engine is not None:
            self._engine.clear_audio_backlog()


class TranslatorWorker(QObject):
    translated = Signal(int, str, str)
    error = Signal(str)
    notice = Signal(str)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self._settings = settings
        self._translator = None
        self._rate_limiter: RateLimiter | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._stopped = False

    @Slot()
    def initialize(self) -> None:
        self._stopped = False
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="translate")
        self._init_translator()

    def _init_translator(self) -> None:
        try:
            self._translator = create_translator_from_settings(self._settings)
        except TranslatorError as exc:
            self._translator = None
            self.error.emit(str(exc))
            return

        translator_type = (self._settings.translator_type or "").strip()
        if translator_type == "LLM_API_Translator":
            llm = self._settings.llm
            self._rate_limiter = RateLimiter(
                max_per_minute=llm.max_requests_per_minute,
                delay=llm.delay,
            )
        elif translator_type == "DeepL":
            self._rate_limiter = RateLimiter(max_per_minute=0, delay=self._settings.deepl.delay)
        elif translator_type == "DeepL_free":
            self._rate_limiter = RateLimiter(max_per_minute=0, delay=self._settings.deepl_free.delay)
        elif translator_type == "google":
            self._rate_limiter = RateLimiter(max_per_minute=0, delay=self._settings.google.delay)
        elif translator_type == "Papago":
            self._rate_limiter = RateLimiter(max_per_minute=0, delay=self._settings.papago.delay)
        else:
            self._rate_limiter = None

        runtime_notices = []
        if hasattr(self._translator, "runtime_notices"):
            try:
                runtime_notices = self._translator.runtime_notices()
            except Exception:
                runtime_notices = []

        for msg in runtime_notices:
            self.notice.emit(str(msg))

    def _contains_cyrillic(self, text: str) -> bool:
        for ch in text:
            if "\u0400" <= ch <= "\u04FF" or "\u0500" <= ch <= "\u052F":
                return True
        return False

    def _looks_invalid(self, original: str, translated: str) -> bool:
        t = translated.strip()
        if not t:
            return True
        if t == original.strip():
            return True
        if self._contains_cyrillic(t):
            return True
        return False

    @Slot()
    def stop(self) -> None:
        self._stopped = True
        executor = self._executor
        self._executor = None
        if executor is not None:
            # Wait for running jobs to finish so interpreter can exit cleanly.
            executor.shutdown(wait=True, cancel_futures=True)

    @Slot(int, str)
    def translate_text(self, sentence_id: int, text: str) -> None:
        if self._stopped or self._translator is None:
            return

        executor = self._executor
        if executor is None:
            return

        try:
            executor.submit(self._translate_job, sentence_id, text)
        except RuntimeError:
            # Executor may already be shutting down.
            return

    def _translate_job(self, sentence_id: int, text: str) -> None:
        if self._stopped:
            return

        if (self._settings.translator_type or "").strip() == "LLM_API_Translator":
            llm = self._settings.llm
            attempts = max(1, int(llm.retry_attempts) if llm.retry_attempts is not None else 1)
        else:
            attempts = 1

        last_error: str | None = None

        for _ in range(attempts):
            if self._stopped:
                return

            try:
                if self._rate_limiter is not None:
                    self._rate_limiter.wait()

                if self._stopped:
                    return

                result = self._translator.translate(
                    text,
                    target_lang=self._settings.target_lang,
                    source_lang=self._settings.source_lang,
                )

                if self._looks_invalid(text, result):
                    last_error = "Translation output is invalid (same as source or contains Cyrillic)."
                    continue

                self.translated.emit(sentence_id, text, result)
                return
            except Exception as exc:
                last_error = str(exc)

        if last_error and not self._stopped:
            self.error.emit(last_error)


class MainWindow(QMainWindow):
    translate_requested = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Speaki")

        self._settings = AppSettings.load(SETTINGS_PATH)

        self._stt_thread: QThread | None = None
        self._stt_worker: STTWorker | None = None

        self._translator_thread: QThread | None = None
        self._translator_worker: TranslatorWorker | None = None

        # sentence_id -> {"original": str, "translation": str}
        self._sentences: Dict[int, Dict[str, str]] = {}
        self._current_partial: str = ""

        # sentence_id -> (global_time, segment_time)
        self._sentence_times: Dict[int, Tuple[float, float]] = {}

        self._paused: bool = False

        # logs: (elapsed seconds, text)
        self._global_original_log: List[Tuple[float, str]] = []
        self._global_translation_log: List[Tuple[float, str]] = []
        self._segment_original_log: List[Tuple[float, str]] = []
        self._segment_translation_log: List[Tuple[float, str]] = []

        self._start_time: float | None = None
        self._segment_start_time: float | None = None
        self._max_visible_sentences = 300
        self._max_segment_log_items = 2000
        self._ignore_translation_below_id = 0
        self._stopping = False
        self._preparing = False

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        main_layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        top_bar = QHBoxLayout()
        main_layout.addLayout(top_bar)

        self.status_label = QLabel("Status: idle")
        self.status_label.setMinimumWidth(220)
        self.status_label.setMaximumWidth(480)
        top_bar.addWidget(self.status_label)

        top_bar.addStretch(1)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self._open_settings)
        top_bar.addWidget(self.settings_button)

        self.original_label = QLabel("Original")
        main_layout.addWidget(self.original_label)

        self.original_area = QPlainTextEdit()
        self.original_area.setReadOnly(True)
        self.original_area.setMinimumHeight(150)
        main_layout.addWidget(self.original_area)

        self.translation_label = QLabel("Translation")
        main_layout.addWidget(self.translation_label)

        self.translation_area = QPlainTextEdit()
        self.translation_area.setReadOnly(True)
        self.translation_area.setMinimumHeight(150)
        main_layout.addWidget(self.translation_area)

        controls1 = QHBoxLayout()
        main_layout.addLayout(controls1)

        self.show_original_checkbox = QCheckBox("Show original")
        self.show_original_checkbox.setChecked(True)
        self.show_original_checkbox.toggled.connect(self._update_display)
        controls1.addWidget(self.show_original_checkbox)

        self.show_translation_checkbox = QCheckBox("Show translation")
        self.show_translation_checkbox.setChecked(True)
        self.show_translation_checkbox.toggled.connect(self._update_display)
        controls1.addWidget(self.show_translation_checkbox)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._on_start_clicked)
        controls1.addWidget(self.start_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._on_pause_clicked)
        controls1.addWidget(self.pause_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        controls1.addWidget(self.clear_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        controls1.addWidget(self.stop_button)

        controls1.addStretch(1)

        controls2 = QHBoxLayout()
        main_layout.addLayout(controls2)

        self.save_all_button = QPushButton("Save full logs")
        self.save_all_button.setEnabled(False)
        self.save_all_button.clicked.connect(self._on_save_all_clicked)
        controls2.addWidget(self.save_all_button)

        self.save_segment_button = QPushButton("Save segment logs")
        self.save_segment_button.setEnabled(False)
        self.save_segment_button.clicked.connect(self._on_save_segment_clicked)
        controls2.addWidget(self.save_segment_button)

        controls2.addStretch(1)

    def _update_display(self) -> None:
        show_original = self.show_original_checkbox.isChecked()
        show_translation = self.show_translation_checkbox.isChecked()

        keys = sorted(self._sentences.keys())

        if show_original:
            orig_parts: List[str] = []
            for sid in keys:
                text = self._sentences[sid].get("original", "")
                if text:
                    orig_parts.append(text)
            if self._current_partial:
                orig_parts.append(self._current_partial)
            self.original_area.setPlainText(" ".join(orig_parts))
            self.original_area.verticalScrollBar().setValue(
                self.original_area.verticalScrollBar().maximum()
            )
        else:
            self.original_area.setPlainText("")

        if show_translation:
            trans_parts: List[str] = []
            for sid in keys:
                text = self._sentences[sid].get("translation", "")
                if text:
                    trans_parts.append(text)
            self.translation_area.setPlainText(" ".join(trans_parts))
            self.translation_area.verticalScrollBar().setValue(
                self.translation_area.verticalScrollBar().maximum()
            )
        else:
            self.translation_area.setPlainText("")

    @Slot(str)
    def _handle_partial(self, text: str) -> None:
        if self._preparing:
            self._preparing = False
            self.status_label.setText("Status: running")
        self._current_partial = text
        self._update_display()

    @Slot(int, str)
    def _handle_final(self, sentence_id: int, text: str) -> None:
        if self._preparing:
            self._preparing = False
            self.status_label.setText("Status: running")

        now = time.monotonic()
        if self._start_time is None:
            self._start_time = now
        if self._segment_start_time is None:
            self._segment_start_time = now

        t_global = now - self._start_time
        t_segment = now - self._segment_start_time

        self._sentence_times[sentence_id] = (t_global, t_segment)

        self._global_original_log.append((t_global, text))
        self._segment_original_log.append((t_segment, text))

        self._current_partial = ""
        self._sentences[sentence_id] = {
            "original": text,
            "translation": self._sentences.get(sentence_id, {}).get("translation", ""),
        }
        self._prune_visible_sentences()
        self._prune_segment_logs()
        self._update_display()

        if self._translator_worker is not None:
            self.translate_requested.emit(sentence_id, text)

    @Slot(int, str, str)
    def _handle_translated(self, sentence_id: int, original: str, translated: str) -> None:
        if sentence_id < self._ignore_translation_below_id:
            return

        now = time.monotonic()
        if self._start_time is None:
            self._start_time = now
        if self._segment_start_time is None:
            self._segment_start_time = now

        t_global, t_segment = self._sentence_times.get(
            sentence_id,
            (now - self._start_time, now - self._segment_start_time),
        )

        self._global_translation_log.append((t_global, translated))
        self._segment_translation_log.append((t_segment, translated))
        self._prune_segment_logs()

        existing = self._sentences.get(sentence_id)
        if existing is None:
            self._sentences[sentence_id] = {
                "original": original,
                "translation": translated,
            }
        else:
            existing["translation"] = translated

        self._update_display()

    def _prune_visible_sentences(self) -> None:
        if len(self._sentences) <= self._max_visible_sentences:
            return

        keys = sorted(self._sentences.keys())
        drop_ids = keys[:-self._max_visible_sentences]
        for sid in drop_ids:
            self._sentences.pop(sid, None)
            self._sentence_times.pop(sid, None)

        if drop_ids:
            self._ignore_translation_below_id = max(
                self._ignore_translation_below_id,
                drop_ids[-1] + 1,
            )

    def _prune_segment_logs(self) -> None:
        if len(self._segment_original_log) > self._max_segment_log_items:
            overflow = len(self._segment_original_log) - self._max_segment_log_items
            del self._segment_original_log[:overflow]

        if len(self._segment_translation_log) > self._max_segment_log_items:
            overflow = len(self._segment_translation_log) - self._max_segment_log_items
            del self._segment_translation_log[:overflow]

    @Slot(str)
    def _handle_error(self, message: str) -> None:
        self._preparing = False
        logger.error("UI error: %s", message)
        short = (message or "").strip().splitlines()[0] if message else "unknown error"
        if len(short) > 140:
            short = short[:137] + "..."
        self.status_label.setText(f"Status: error - {short}")
        self.status_label.setToolTip(message or "")

    @Slot(str)
    def _handle_notice(self, message: str) -> None:
        logger.info("UI notice: %s", message)
        short = (message or "").strip().splitlines()[0] if message else "notice"
        if len(short) > 140:
            short = short[:137] + "..."
        self.status_label.setText(f"Status: notice - {short}")
        self.status_label.setToolTip(message or "")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            dialog.apply_to_settings()
            self._settings.save(SETTINGS_PATH)

    def _reset_logs(self) -> None:
        self._global_original_log.clear()
        self._global_translation_log.clear()
        self._segment_original_log.clear()
        self._segment_translation_log.clear()
        self._sentence_times.clear()
        self._start_time = None
        self._segment_start_time = None

    def _build_stt_config(self) -> STTConfig:
        backend = (self._settings.stt.backend or "cuda").strip().lower()

        def normalize_device_index(value: object) -> int | None:
            try:
                idx = int(value)
            except Exception:
                return None
            return None if idx < 0 else idx

        input_device_index = normalize_device_index(self._settings.stt.input_device_index)
        output_device_index = normalize_device_index(self._settings.stt.output_device_index)
        language = self._settings.source_lang if self._settings.source_lang != "auto" else "ru"

        if backend == "cpu":
            return STTConfig(
                device="cpu",
                compute_type="int8",
                model="small",
                realtime_model_type="tiny",
                language=language,
                input_device_index=input_device_index,
                output_device_index=output_device_index,
            )

        return STTConfig(
            device="cuda",
            compute_type="float16",
            model="large-v3",
            realtime_model_type="medium",
            language=language,
            input_device_index=input_device_index,
            output_device_index=output_device_index,
        )

    def _on_start_clicked(self) -> None:
        if self._stt_thread is not None:
            return

        self._sentences.clear()
        self._current_partial = ""
        self._reset_logs()
        self._update_display()
        self._paused = False
        self._ignore_translation_below_id = 0

        stt_config = self._build_stt_config()

        self._stt_thread = QThread(self)
        self._stt_worker = STTWorker(stt_config)
        self._stt_worker.moveToThread(self._stt_thread)

        self._stt_thread.started.connect(self._stt_worker.run)
        self._stt_worker.partial_result.connect(self._handle_partial)
        self._stt_worker.final_result.connect(self._handle_final)
        self._stt_worker.error.connect(self._handle_error)
        self._stt_worker.finished.connect(self._stt_thread.quit)
        self._stt_worker.finished.connect(self._on_stt_finished)
        self._translator_thread = QThread(self)
        self._translator_worker = TranslatorWorker(self._settings)
        self._translator_worker.moveToThread(self._translator_thread)

        self._translator_worker.translated.connect(self._handle_translated)
        self._translator_worker.error.connect(self._handle_error)
        self._translator_worker.notice.connect(self._handle_notice)
        self.translate_requested.connect(
            self._translator_worker.translate_text,
            Qt.QueuedConnection,
        )
        self._translator_thread.started.connect(self._translator_worker.initialize)

        self._preparing = True
        self.status_label.setText("Status: preparing")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("Pause")
        self.clear_button.setEnabled(True)
        self.save_all_button.setEnabled(True)
        self.save_segment_button.setEnabled(True)

        self._translator_thread.start()
        self._stt_thread.start()

    def _on_pause_clicked(self) -> None:
        if self._stt_worker is None:
            return

        self._paused = not self._paused
        self._stt_worker.set_paused(self._paused)

        if self._paused:
            self.status_label.setText("Status: paused")
            self.pause_button.setText("Resume")
        else:
            self.status_label.setText("Status: running")
            self.pause_button.setText("Pause")

    def _on_clear_clicked(self) -> None:
        # Keep STT/translator running, but reset current display and STT audio backlog.
        if self._sentences:
            self._ignore_translation_below_id = max(
                self._ignore_translation_below_id,
                max(self._sentences.keys()) + 1,
            )
        if self._stt_worker is not None:
            self._stt_worker.clear_audio_backlog()
        self._sentences.clear()
        self._current_partial = ""
        self._segment_original_log.clear()
        self._segment_translation_log.clear()
        self._segment_start_time = time.monotonic()
        self._update_display()

    @Slot()
    def _on_stt_finished(self) -> None:
        if self._stopping:
            return

        self._stt_thread = None
        self._stt_worker = None

        if self._translator_thread is not None:
            if self._translator_worker is not None:
                self._translator_worker.stop()
                try:
                    self.translate_requested.disconnect(self._translator_worker.translate_text)
                except (TypeError, RuntimeError):
                    pass
            self._shutdown_qthread(self._translator_thread, "translator thread")
            self._translator_thread = None
            self._translator_worker = None

        if not self.status_label.text().startswith("Status: error"):
            self.status_label.setText("Status: idle")

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.clear_button.setEnabled(False)
        self._preparing = False
        self._paused = False

    def _shutdown_qthread(self, thread: QThread, name: str, timeout_ms: int = 7000) -> None:
        thread.quit()
        if thread.wait(timeout_ms):
            return

        # Last-resort path to avoid "QThread: Destroyed while thread is still running".
        self.status_label.setText(f"Status: warning - forcing {name} stop")
        thread.terminate()
        thread.wait(2000)

    def _on_stop_clicked(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._paused = False

        try:
            if self._stt_worker is not None:
                self._stt_worker.stop()

            if self._stt_thread is not None:
                self._shutdown_qthread(self._stt_thread, "STT thread")
                self._stt_thread = None
                self._stt_worker = None

            if self._translator_thread is not None:
                if self._translator_worker is not None:
                    self._translator_worker.stop()
                    try:
                        self.translate_requested.disconnect(self._translator_worker.translate_text)
                    except (TypeError, RuntimeError):
                        pass

                self._shutdown_qthread(self._translator_thread, "translator thread")
                self._translator_thread = None
                self._translator_worker = None

            self.status_label.setText("Status: idle")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.pause_button.setText("Pause")
            self.clear_button.setEnabled(False)
            self._preparing = False
        finally:
            self._stopping = False

    def _format_log(self, log: List[Tuple[float, str]]) -> str:
        lines: List[str] = []
        for t, text in log:
            minutes = int(t // 60)
            seconds = int(t % 60)
            ms = int((t - int(t)) * 1000)
            lines.append(f"[{minutes:02d}:{seconds:02d}.{ms:03d}] {text}")
        return "\n".join(lines)

    def _save_logs_pair(
        self,
        orig_log: List[Tuple[float, str]],
        trans_log: List[Tuple[float, str]],
        default_name: str,
    ) -> None:
        if not orig_log and not trans_log:
            QMessageBox.information(self, "Nothing to save", "There are no logs to save.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select base filename",
            default_name,
            "Text Files (*.txt)",
        )
        if not path:
            return

        base, _ = os.path.splitext(path)
        orig_path = base + "_orig.txt"
        trans_path = base + "_trans.txt"

        try:
            with open(orig_path, "w", encoding="utf-8") as f:
                f.write(self._format_log(orig_log))
            with open(trans_path, "w", encoding="utf-8") as f:
                f.write(self._format_log(trans_log))
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"Error while saving logs:\n{exc}")
            return

        QMessageBox.information(
            self,
            "Saved",
            f"Saved files:\n\nOriginal: {orig_path}\nTranslation: {trans_path}",
        )

    def _on_save_all_clicked(self) -> None:
        self._save_logs_pair(
            self._global_original_log,
            self._global_translation_log,
            "speaki_full_session.txt",
        )

    def _on_save_segment_clicked(self) -> None:
        self._save_logs_pair(
            self._segment_original_log,
            self._segment_translation_log,
            "speaki_segment.txt",
        )

    def closeEvent(self, event) -> None:
        self._on_stop_clicked()
        self._settings.save(SETTINGS_PATH)
        super().closeEvent(event)







