from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from RealtimeSTT import AudioToTextRecorder


SentenceCallback = Callable[[str], None]
logger = logging.getLogger(__name__)


@dataclass
class STTConfig:
    """Wrapper settings for RealtimeSTT."""

    model: str = "large-v3"
    download_root: Optional[str] = None
    realtime_model_type: str = "medium"
    language: Optional[str] = "ru"
    device: str = "cuda"
    compute_type: str = "float16"
    input_device_index: Optional[int] = None
    output_device_index: Optional[int] = None
    gpu_device_index: int = 0

    silero_sensitivity: float = 0.05
    webrtc_sensitivity: int = 3

    base_post_speech_silence_duration: float = 0.7
    min_length_of_recording: float = 1.1
    min_gap_between_recordings: float = 0.0

    enable_realtime_transcription: bool = True
    realtime_processing_pause: float = 0.02

    beam_size: int = 5
    beam_size_realtime: int = 3

    silero_use_onnx: bool = True
    faster_whisper_vad_filter: bool = False

    spinner: bool = False
    no_log_file: bool = True

    # RealtimeSTT internal queue overflow controls
    handle_buffer_overflow: bool = True
    allowed_latency_limit: int = 120

    # Recovery when queue keeps growing and latency explodes.
    queue_monitor_interval: float = 0.2
    queue_recovery_threshold: int = 130
    queue_recovery_trigger_count: int = 2
    queue_recovery_cooldown: float = 1.5

    # Keep memory bounded for long sessions.
    max_sentences_in_memory: int = 500

    initial_prompt_realtime: str = (
        "End incomplete sentences with ellipses.\n"
        "Examples:\n"
        "Complete: The sky is blue.\n"
        "Incomplete: When the sky...\n"
        "Complete: She walked home.\n"
        "Incomplete: Because he...\n"
    )


class STTEngine:
    """RealtimeSTT engine wrapper for UI use."""

    def __init__(
        self,
        config: STTConfig,
        on_partial: Optional[SentenceCallback] = None,
        on_final: Optional[SentenceCallback] = None,
    ) -> None:
        self.config = config
        self.on_partial = on_partial
        self.on_final = on_final

        self._recorder: Optional[AudioToTextRecorder] = None
        self._running = False
        self._paused = False

        self._full_sentences: List[str] = []
        self._prev_text = ""

        self._queue_overflow_hits = 0
        self._last_recovery_at = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None

        self._end_of_sentence_detection_pause = 0.45
        self._unknown_sentence_detection_pause = self.config.base_post_speech_silence_duration
        self._mid_sentence_detection_pause = 2.0

        self._init_recorder()

    def _find_loopback_input_for_output(self, output_device_index: int) -> Optional[int]:
        """
        Try to map selected output device to a loopback-capable input device.
        Works with names like Stereo Mix / loopback / What U Hear.
        """
        try:
            import pyaudio
        except Exception:
            return None

        pa = pyaudio.PyAudio()
        try:
            out_info = pa.get_device_info_by_index(int(output_device_index))
            out_name = str(out_info.get("name", "")).strip().lower()

            tokens = [
                t for t in out_name.replace("(", " ").replace(")", " ").replace("-", " ").split()
                if len(t) >= 4
            ]

            best_index: Optional[int] = None
            best_score = 0

            for idx in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(idx)
                if int(info.get("maxInputChannels", 0)) <= 0:
                    continue

                name = str(info.get("name", "")).strip().lower()
                score = 0

                if "stereo mix" in name or "what u hear" in name or "loopback" in name:
                    score += 4

                if out_name and out_name in name:
                    score += 3

                if tokens:
                    score += sum(1 for t in tokens if t in name)

                if score > best_score:
                    best_score = score
                    best_index = idx

            # Require minimal confidence.
            if best_index is not None and best_score >= 4:
                return int(best_index)
            return None
        except Exception:
            return None
        finally:
            try:
                pa.terminate()
            except Exception:
                pass

    def _init_recorder(self) -> None:
        if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
            try:
                from torchaudio._extension.utils import _init_dll_path

                _init_dll_path()
            except Exception:
                pass

        input_device_index = self.config.input_device_index

        # If input is not explicitly selected but output is selected,
        # try to map output to a loopback input (Stereo Mix-like devices).
        if input_device_index is None and self.config.output_device_index is not None:
            mapped = self._find_loopback_input_for_output(self.config.output_device_index)
            if mapped is not None:
                input_device_index = mapped
                logger.info(
                    "Mapped output device index %s to loopback input device index %s",
                    self.config.output_device_index,
                    mapped,
                )

        recorder_config = {
            "spinner": self.config.spinner,
            "model": self.config.model,
            "download_root": self.config.download_root,
            "device": self.config.device,
            "compute_type": self.config.compute_type,
            "gpu_device_index": self.config.gpu_device_index,
            "realtime_model_type": self.config.realtime_model_type,
            "language": self.config.language,
            "silero_sensitivity": self.config.silero_sensitivity,
            "webrtc_sensitivity": self.config.webrtc_sensitivity,
            "post_speech_silence_duration": self._unknown_sentence_detection_pause,
            "min_length_of_recording": self.config.min_length_of_recording,
            "min_gap_between_recordings": self.config.min_gap_between_recordings,
            "enable_realtime_transcription": self.config.enable_realtime_transcription,
            "realtime_processing_pause": self.config.realtime_processing_pause,
            "on_realtime_transcription_update": self._on_realtime_transcription_update,
            "silero_deactivity_detection": True,
            "early_transcription_on_silence": 0,
            "beam_size": self.config.beam_size,
            "beam_size_realtime": self.config.beam_size_realtime,
            "no_log_file": self.config.no_log_file,
            "handle_buffer_overflow": self.config.handle_buffer_overflow,
            "allowed_latency_limit": self.config.allowed_latency_limit,
            "initial_prompt_realtime": self.config.initial_prompt_realtime,
            "silero_use_onnx": self.config.silero_use_onnx,
            "faster_whisper_vad_filter": self.config.faster_whisper_vad_filter,
        }

        if input_device_index is not None:
            recorder_config["input_device_index"] = int(input_device_index)

        self._recorder = AudioToTextRecorder(**recorder_config)

    def _preprocess_text(self, text: str) -> str:
        text = text.lstrip()

        if text.startswith("..."):
            text = text[3:]

        text = text.lstrip()

        if text:
            text = text[0].upper() + text[1:]

        return text

    def _on_realtime_transcription_update(self, text: str) -> None:
        if self._recorder is None or self._paused:
            return

        text = self._preprocess_text(text)

        sentence_end_marks = [".", "!", "?", "..."]
        if text.endswith("..."):
            self._recorder.post_speech_silence_duration = self._mid_sentence_detection_pause
        elif (
            text
            and any(text.endswith(mark) for mark in sentence_end_marks)
            and self._prev_text
            and any(self._prev_text.endswith(mark) for mark in sentence_end_marks)
        ):
            self._recorder.post_speech_silence_duration = self._end_of_sentence_detection_pause
        else:
            self._recorder.post_speech_silence_duration = self._unknown_sentence_detection_pause

        self._prev_text = text

        if self.on_partial is not None:
            self.on_partial(text)

    def _handle_final_text(self, text: str) -> None:
        if self._recorder is None or self._paused:
            return

        self._recorder.post_speech_silence_duration = self._unknown_sentence_detection_pause

        text = self._preprocess_text(text).rstrip()

        if text.endswith("..."):
            text = text[:-3]

        if not text:
            return

        self._full_sentences.append(text)
        if len(self._full_sentences) > self.config.max_sentences_in_memory:
            overflow = len(self._full_sentences) - self.config.max_sentences_in_memory
            del self._full_sentences[:overflow]

        self._prev_text = ""

        if self.on_final is not None:
            self.on_final(text)

    def _get_audio_queue_size(self) -> int:
        if self._recorder is None:
            return 0

        queue_obj = getattr(self._recorder, "audio_queue", None)
        if queue_obj is None:
            return 0

        try:
            return int(queue_obj.qsize())
        except Exception:
            return 0

    def _recover_audio_backlog(self, reason: str) -> None:
        if self._recorder is None:
            return

        try:
            if hasattr(self._recorder, "clear_audio_queue"):
                self._recorder.clear_audio_queue()
            else:
                queue_obj = getattr(self._recorder, "audio_queue", None)
                if queue_obj is not None:
                    while True:
                        queue_obj.get_nowait()
        except Exception:
            pass

        self._prev_text = ""
        self._queue_overflow_hits = 0
        self._last_recovery_at = time.monotonic()

        if self.on_partial is not None:
            self.on_partial("")

        logger.warning("STT audio backlog recovered: %s", reason)

    def clear_audio_backlog(self) -> None:
        self._recover_audio_backlog("manual clear")

    def _queue_watchdog_loop(self) -> None:
        interval = max(0.05, self.config.queue_monitor_interval)
        while self._running:
            time.sleep(interval)
            if self._paused:
                continue

            queue_size = self._get_audio_queue_size()
            if queue_size >= self.config.queue_recovery_threshold:
                self._queue_overflow_hits += 1
            else:
                self._queue_overflow_hits = 0
                continue

            if self._queue_overflow_hits < self.config.queue_recovery_trigger_count:
                continue

            now = time.monotonic()
            if now - self._last_recovery_at < self.config.queue_recovery_cooldown:
                continue

            self._recover_audio_backlog(
                f"queue_size={queue_size}, threshold={self.config.queue_recovery_threshold}"
            )

    def _start_queue_watchdog(self) -> None:
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_thread = threading.Thread(
            target=self._queue_watchdog_loop,
            name="stt-queue-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_queue_watchdog(self) -> None:
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.0)
        self._watchdog_thread = None

    def run(self) -> None:
        """Blocking loop. Call from a dedicated thread (QThread)."""
        if self._recorder is None:
            return

        self._running = True
        self._start_queue_watchdog()
        try:
            while self._running:
                if self._paused:
                    time.sleep(0.05)
                    continue
                self._recorder.text(self._handle_final_text)
        finally:
            self._running = False
            self._stop_queue_watchdog()

    def stop(self) -> None:
        self._running = False
        if self._recorder is None:
            return

        if hasattr(self._recorder, "stop"):
            try:
                self._recorder.stop()
            except Exception:
                pass

        # RealtimeSTT owns background workers/processes; close them explicitly.
        if hasattr(self._recorder, "shutdown"):
            try:
                self._recorder.shutdown()
            except Exception:
                pass

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def sentences(self) -> List[str]:
        return list(self._full_sentences)