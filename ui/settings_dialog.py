from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import (
    AppSettings,
    DeepLFreeSettings,
    DeepLSettings,
    GoogleSettings,
    LLMTranslatorSettings,
    PapagoSettings,
)


def _add_lang_items(combo: QComboBox) -> None:
    combo.clear()
    combo.addItem("Auto (auto)", "auto")
    combo.addItem("Japanese (ja)", "ja")
    combo.addItem("Korean (ko)", "ko")
    combo.addItem("English (en)", "en")
    combo.addItem("Russian (ru)", "ru")
    combo.addItem("Chinese Simplified (zh-CN)", "zh-CN")


def _list_audio_devices() -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    inputs: list[tuple[str, int]] = []
    outputs: list[tuple[str, int]] = []
    try:
        import pyaudio
    except Exception:
        return inputs, outputs

    def _clean(name: str) -> str:
        return " ".join(name.strip().split())

    pa = pyaudio.PyAudio()
    try:
        preferred_host_api: int | None = None
        for api_idx in range(pa.get_host_api_count()):
            api_info = pa.get_host_api_info_by_index(api_idx)
            api_name = str(api_info.get("name", "")).lower()
            if "wasapi" in api_name:
                preferred_host_api = int(api_idx)
                break

        if preferred_host_api is None:
            try:
                preferred_host_api = int(pa.get_default_host_api_info().get("index", -1))
                if preferred_host_api < 0:
                    preferred_host_api = None
            except Exception:
                preferred_host_api = None

        default_input_idx: int | None = None
        default_output_idx: int | None = None
        if preferred_host_api is not None:
            try:
                host_info = pa.get_host_api_info_by_index(preferred_host_api)
                di = int(host_info.get("defaultInputDevice", -1))
                do = int(host_info.get("defaultOutputDevice", -1))
                if di >= 0:
                    default_input_idx = di
                if do >= 0:
                    default_output_idx = do
            except Exception:
                pass

        seen_inputs: set[str] = set()
        seen_outputs: set[str] = set()

        for idx in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(idx)
            host_api = int(info.get("hostApi", -1))
            if preferred_host_api is not None and host_api != preferred_host_api:
                continue

            name = _clean(str(info.get("name", "") or "Unknown device"))
            name_key = name.lower()
            max_in = int(info.get("maxInputChannels", 0))
            max_out = int(info.get("maxOutputChannels", 0))
            is_loopback = "loopback" in name_key

            # Keep strict split so input/output combos do not get mixed.
            if max_in > 0 and max_out == 0 and not is_loopback:
                if name_key not in seen_inputs:
                    label = name
                    if default_input_idx is not None and int(idx) == default_input_idx:
                        label = f"{name} (Default)"
                    inputs.append((label, int(idx)))
                    seen_inputs.add(name_key)

            if max_out > 0 and max_in == 0:
                if name_key not in seen_outputs:
                    label = name
                    if default_output_idx is not None and int(idx) == default_output_idx:
                        label = f"{name} (Default)"
                    outputs.append((label, int(idx)))
                    seen_outputs.add(name_key)
    except Exception:
        return [], []
    finally:
        try:
            pa.terminate()
        except Exception:
            pass

    inputs.sort(key=lambda x: (0 if "(Default)" in x[0] else 1, x[0].lower()))
    outputs.sort(key=lambda x: (0 if "(Default)" in x[0] else 1, x[0].lower()))
    return inputs, outputs


class AdaptiveStackedWidget(QStackedWidget):
    """Use current page size hint so small pages don't reserve LLM-page height."""

    def sizeHint(self) -> QSize:  # type: ignore[override]
        page = self.currentWidget()
        if page is not None:
            return page.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        page = self.currentWidget()
        if page is not None:
            return page.minimumSizeHint()
        return super().minimumSizeHint()


class DeepLPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self.api_key_edit = QLineEdit()
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setDecimals(2)

        self.formality_combo = QComboBox()
        self.formality_combo.addItems(["default", "more", "less"])

        self.context_edit = QPlainTextEdit()
        self.context_edit.setFixedHeight(80)

        self.preserve_combo = QComboBox()
        self.preserve_combo.addItems(["disabled", "enabled"])

        layout.addRow("api_key", self.api_key_edit)
        layout.addRow("delay", self.delay_spin)
        layout.addRow("formality", self.formality_combo)
        layout.addRow("context", self.context_edit)
        layout.addRow("preserve_formatting", self.preserve_combo)

    def _load_common(self, api_key: str, delay: float, formality: str, context: str, preserve: str) -> None:
        self.api_key_edit.setText(api_key)
        self.delay_spin.setValue(delay)

        idx = self.formality_combo.findText(formality)
        if idx >= 0:
            self.formality_combo.setCurrentIndex(idx)

        idx = self.preserve_combo.findText(preserve)
        if idx >= 0:
            self.preserve_combo.setCurrentIndex(idx)

        self.context_edit.setPlainText(context)

    def _apply_common(self) -> dict[str, object]:
        return {
            "api_key": self.api_key_edit.text().strip(),
            "delay": float(self.delay_spin.value()),
            "formality": self.formality_combo.currentText(),
            "context": self.context_edit.toPlainText(),
            "preserve_formatting": self.preserve_combo.currentText(),
        }

    def load(self, s: DeepLSettings | DeepLFreeSettings) -> None:
        self._load_common(
            api_key=s.api_key,
            delay=s.delay,
            formality=s.formality,
            context=s.context,
            preserve=s.preserve_formatting,
        )

    def apply(self, s: DeepLSettings | DeepLFreeSettings) -> None:
        data = self._apply_common()
        s.api_key = str(data["api_key"])
        s.delay = float(data["delay"])
        s.formality = str(data["formality"])
        s.context = str(data["context"])
        s.preserve_formatting = str(data["preserve_formatting"])


class GooglePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        hint = QLabel("Uses Google public web translate endpoint.")
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setDecimals(2)

        layout.addRow("info", hint)
        layout.addRow("delay", self.delay_spin)

    def load(self, s: GoogleSettings) -> None:
        self.delay_spin.setValue(s.delay)

    def apply(self, s: GoogleSettings) -> None:
        s.delay = float(self.delay_spin.value())


class PapagoPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self.client_id_edit = QLineEdit()
        self.client_secret_edit = QLineEdit()
        self.client_secret_edit.setEchoMode(QLineEdit.Password)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setDecimals(2)

        layout.addRow("client_id", self.client_id_edit)
        layout.addRow("client_secret", self.client_secret_edit)
        layout.addRow("delay", self.delay_spin)

    def load(self, s: PapagoSettings) -> None:
        self.client_id_edit.setText(s.client_id)
        self.client_secret_edit.setText(s.client_secret)
        self.delay_spin.setValue(s.delay)

    def apply(self, s: PapagoSettings) -> None:
        s.client_id = self.client_id_edit.text().strip()
        s.client_secret = self.client_secret_edit.text().strip()
        s.delay = float(self.delay_spin.value())


class LLMPage(QWidget):
    OPENAI_MODELS = [
        ("gpt-5.2", "gpt-5.2"),
        ("gpt-5.1", "gpt-5.1"),
        ("gpt-5", "gpt-5"),
        ("gpt-5-mini", "gpt-5-mini"),
        ("gpt-4.1", "gpt-4.1"),
        ("gpt-4o", "gpt-4o"),
        ("gpt-4", "gpt-4"),
        ("o4-mini", "o4-mini"),
        ("o3-pro", "o3-pro"),
        ("o3", "o3"),
    ]

    GEMINI_MODELS = [
        ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("gemini-2.5-flash", "gemini-2.5-flash"),
        ("gemini-3-flash-preview", "gemini-3-flash-preview"),
        ("(paid)gemini-3-pro-preview", "gemini-3-pro-preview"),
        ("(paid)gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
    ]

    SNAPSHOT_FIELDS = (
        "api_key",
        "multiple_keys",
        "model",
        "override_model",
        "endpoint",
        "system_prompt",
        "invalid_repeat_count",
        "max_requests_per_minute",
        "delay",
        "max_tokens",
        "temperature",
        "top_p",
        "retry_attempts",
        "retry_timeout",
        "proxy",
        "frequency_penalty",
        "presence_penalty",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QFormLayout(self)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["OpenAI", "Google"])

        self.api_key_edit = QLineEdit()
        self.multiple_keys_edit = QPlainTextEdit()
        self.multiple_keys_edit.setFixedHeight(40)

        self.model_combo = QComboBox()
        self.override_model_edit = QLineEdit()
        self.endpoint_edit = QLineEdit()

        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setFixedHeight(120)

        self.invalid_repeat_spin = QSpinBox()
        self.invalid_repeat_spin.setRange(0, 10)

        self.max_rpm_spin = QSpinBox()
        self.max_rpm_spin.setRange(0, 10_000)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setDecimals(2)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 100_000)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.05)

        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.0, 1.0)
        self.top_p_spin.setSingleStep(0.05)

        self.retry_attempts_spin = QSpinBox()
        self.retry_attempts_spin.setRange(0, 20)

        self.retry_timeout_spin = QDoubleSpinBox()
        self.retry_timeout_spin.setRange(0.0, 120.0)
        self.retry_timeout_spin.setDecimals(1)

        self.proxy_edit = QLineEdit()

        self.freq_penalty_spin = QDoubleSpinBox()
        self.freq_penalty_spin.setRange(0.0, 2.0)
        self.freq_penalty_spin.setSingleStep(0.1)

        self.pres_penalty_spin = QDoubleSpinBox()
        self.pres_penalty_spin.setRange(0.0, 2.0)
        self.pres_penalty_spin.setSingleStep(0.1)

        layout.addRow("provider", self.provider_combo)
        layout.addRow("apikey", self.api_key_edit)
        layout.addRow("multiple_keys", self.multiple_keys_edit)
        layout.addRow("model", self.model_combo)
        layout.addRow("override model", self.override_model_edit)
        layout.addRow("endpoint", self.endpoint_edit)
        layout.addRow("system_prompt", self.system_prompt_edit)
        layout.addRow("invalid repeat count", self.invalid_repeat_spin)
        layout.addRow("max requests per minute", self.max_rpm_spin)
        layout.addRow("delay", self.delay_spin)
        layout.addRow("max tokens", self.max_tokens_spin)
        layout.addRow("temperature", self.temperature_spin)
        layout.addRow("top p", self.top_p_spin)
        layout.addRow("retry attempts", self.retry_attempts_spin)
        layout.addRow("retry timeout", self.retry_timeout_spin)
        layout.addRow("proxy", self.proxy_edit)
        layout.addRow("frequency penalty", self.freq_penalty_spin)
        layout.addRow("presence penalty", self.pres_penalty_spin)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_snapshots: dict[str, dict[str, object]] = {}
        self._active_provider_key = self._normalize_provider(self.provider_combo.currentText())
        self._init_provider_snapshots()
        self._switch_provider(self._active_provider_key, save_current=False)

    def _model_items_for_provider(self, provider_text: str) -> list[tuple[str, str]]:
        provider = provider_text.strip().lower()
        if provider == "google":
            return list(self.GEMINI_MODELS)
        return list(self.OPENAI_MODELS)

    def _normalize_provider(self, provider_text: str) -> str:
        p = provider_text.strip().lower()
        if p == "google":
            return "google"
        return "openai"

    def _default_snapshot(self, provider_key: str) -> dict[str, object]:
        base = LLMTranslatorSettings()
        model_items = self._model_items_for_provider(provider_key)
        default_model = model_items[0][1] if model_items else ""
        return {
            "api_key": "",
            "multiple_keys": "",
            "model": default_model or base.model,
            "override_model": "",
            "endpoint": "",
            "system_prompt": base.system_prompt,
            "invalid_repeat_count": base.invalid_repeat_count,
            "max_requests_per_minute": base.max_requests_per_minute,
            "delay": base.delay,
            "max_tokens": base.max_tokens,
            "temperature": base.temperature,
            "top_p": base.top_p,
            "retry_attempts": base.retry_attempts,
            "retry_timeout": base.retry_timeout,
            "proxy": base.proxy,
            "frequency_penalty": base.frequency_penalty,
            "presence_penalty": base.presence_penalty,
        }

    def _settings_to_snapshot(self, s: LLMTranslatorSettings) -> dict[str, object]:
        return {
            "api_key": s.api_key,
            "multiple_keys": s.multiple_keys,
            "model": s.model,
            "override_model": s.override_model,
            "endpoint": s.endpoint,
            "system_prompt": s.system_prompt,
            "invalid_repeat_count": s.invalid_repeat_count,
            "max_requests_per_minute": s.max_requests_per_minute,
            "delay": s.delay,
            "max_tokens": s.max_tokens,
            "temperature": s.temperature,
            "top_p": s.top_p,
            "retry_attempts": s.retry_attempts,
            "retry_timeout": s.retry_timeout,
            "proxy": s.proxy,
            "frequency_penalty": s.frequency_penalty,
            "presence_penalty": s.presence_penalty,
        }

    def _sanitize_profile(
        self,
        provider_key: str,
        raw_profile: object,
    ) -> dict[str, object]:
        snap = self._default_snapshot(provider_key)
        if not isinstance(raw_profile, dict):
            return snap

        for key in self.SNAPSHOT_FIELDS:
            if key in raw_profile:
                snap[key] = raw_profile[key]
        return snap

    def _init_provider_snapshots(self) -> None:
        self._provider_snapshots = {
            "openai": self._default_snapshot("openai"),
            "google": self._default_snapshot("google"),
        }

    def _sync_model_items(self, preferred_model: str = "", keep_current: bool = True) -> None:
        selected_model = preferred_model.strip()
        if keep_current and not selected_model:
            current_data = self.model_combo.currentData()
            if isinstance(current_data, str):
                selected_model = current_data.strip()
            elif self.model_combo.currentText():
                selected_model = self.model_combo.currentText().strip()

        self.model_combo.clear()
        for label, model_id in self._model_items_for_provider(self.provider_combo.currentText()):
            self.model_combo.addItem(label, model_id)

        if not selected_model:
            return

        idx = self.model_combo.findData(selected_model)
        if idx < 0:
            idx = self.model_combo.findText(selected_model)

        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
            return

        self.model_combo.insertItem(0, selected_model, selected_model)
        self.model_combo.setCurrentIndex(0)

    def _capture_form_state(self) -> dict[str, object]:
        selected_model = self.model_combo.currentData()
        if not isinstance(selected_model, str) or not selected_model.strip():
            selected_model = self.model_combo.currentText().strip()

        return {
            "api_key": self.api_key_edit.text().strip(),
            "multiple_keys": self.multiple_keys_edit.toPlainText(),
            "model": selected_model,
            "override_model": self.override_model_edit.text().strip(),
            "endpoint": self.endpoint_edit.text().strip(),
            "system_prompt": self.system_prompt_edit.toPlainText(),
            "invalid_repeat_count": self.invalid_repeat_spin.value(),
            "max_requests_per_minute": self.max_rpm_spin.value(),
            "delay": float(self.delay_spin.value()),
            "max_tokens": self.max_tokens_spin.value(),
            "temperature": float(self.temperature_spin.value()),
            "top_p": float(self.top_p_spin.value()),
            "retry_attempts": self.retry_attempts_spin.value(),
            "retry_timeout": float(self.retry_timeout_spin.value()),
            "proxy": self.proxy_edit.text().strip(),
            "frequency_penalty": float(self.freq_penalty_spin.value()),
            "presence_penalty": float(self.pres_penalty_spin.value()),
        }

    def _to_int(self, value: object, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _to_float(self, value: object, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _apply_form_state(self, provider_key: str, state: dict[str, object]) -> None:
        model_value = str(state.get("model", "") or "")
        self._sync_model_items(model_value, keep_current=False)

        self.api_key_edit.setText(str(state.get("api_key", "") or ""))
        self.multiple_keys_edit.setPlainText(str(state.get("multiple_keys", "") or ""))
        self.override_model_edit.setText(str(state.get("override_model", "") or ""))
        self.endpoint_edit.setText(str(state.get("endpoint", "") or ""))
        self.system_prompt_edit.setPlainText(str(state.get("system_prompt", "") or ""))

        default_snap = self._default_snapshot(provider_key)
        self.invalid_repeat_spin.setValue(
            self._to_int(state.get("invalid_repeat_count"), int(default_snap["invalid_repeat_count"]))
        )
        self.max_rpm_spin.setValue(
            self._to_int(state.get("max_requests_per_minute"), int(default_snap["max_requests_per_minute"]))
        )
        self.delay_spin.setValue(self._to_float(state.get("delay"), float(default_snap["delay"])))
        self.max_tokens_spin.setValue(
            self._to_int(state.get("max_tokens"), int(default_snap["max_tokens"]))
        )
        self.temperature_spin.setValue(
            self._to_float(state.get("temperature"), float(default_snap["temperature"]))
        )
        self.top_p_spin.setValue(self._to_float(state.get("top_p"), float(default_snap["top_p"])))
        self.retry_attempts_spin.setValue(
            self._to_int(state.get("retry_attempts"), int(default_snap["retry_attempts"]))
        )
        self.retry_timeout_spin.setValue(
            self._to_float(state.get("retry_timeout"), float(default_snap["retry_timeout"]))
        )
        self.proxy_edit.setText(str(state.get("proxy", "") or ""))
        self.freq_penalty_spin.setValue(
            self._to_float(state.get("frequency_penalty"), float(default_snap["frequency_penalty"]))
        )
        self.pres_penalty_spin.setValue(
            self._to_float(state.get("presence_penalty"), float(default_snap["presence_penalty"]))
        )

    def _switch_provider(self, provider_key: str, save_current: bool = True) -> None:
        if save_current and self._active_provider_key:
            self._provider_snapshots[self._active_provider_key] = self._capture_form_state()

        self._active_provider_key = provider_key
        state = self._provider_snapshots.get(provider_key)
        if state is None:
            state = self._default_snapshot(provider_key)
            self._provider_snapshots[provider_key] = state

        self._apply_form_state(provider_key, state)

    def _on_provider_changed(self, _index: int) -> None:
        self._switch_provider(self._normalize_provider(self.provider_combo.currentText()))

    def load(self, s: LLMTranslatorSettings) -> None:
        provider_text = s.provider.strip()
        idx = self.provider_combo.findText(provider_text)
        if idx < 0 and provider_text.lower() == "google":
            idx = self.provider_combo.findText("Google")
        elif idx < 0 and provider_text.lower() == "openai":
            idx = self.provider_combo.findText("OpenAI")

        if idx >= 0:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(idx)
            self.provider_combo.blockSignals(False)

        self._init_provider_snapshots()

        if isinstance(s.provider_profiles, dict):
            for raw_key, raw_profile in s.provider_profiles.items():
                provider_key = self._normalize_provider(str(raw_key))
                self._provider_snapshots[provider_key] = self._sanitize_profile(
                    provider_key,
                    raw_profile,
                )

        current_key = self._normalize_provider(self.provider_combo.currentText() or s.provider)
        self._provider_snapshots[current_key] = self._sanitize_profile(
            current_key,
            self._settings_to_snapshot(s),
        )

        self._switch_provider(current_key, save_current=False)

    def apply(self, s: LLMTranslatorSettings) -> None:
        self._provider_snapshots[self._active_provider_key] = self._capture_form_state()
        current_key = self._normalize_provider(self.provider_combo.currentText())
        active_snapshot = self._provider_snapshots.get(current_key, self._default_snapshot(current_key))

        s.provider = self.provider_combo.currentText()
        s.api_key = str(active_snapshot.get("api_key", "") or "")
        s.multiple_keys = str(active_snapshot.get("multiple_keys", "") or "")
        s.model = str(active_snapshot.get("model", "") or "")
        s.override_model = str(active_snapshot.get("override_model", "") or "")
        s.endpoint = str(active_snapshot.get("endpoint", "") or "")
        s.system_prompt = str(active_snapshot.get("system_prompt", "") or "")
        s.invalid_repeat_count = self._to_int(active_snapshot.get("invalid_repeat_count"), s.invalid_repeat_count)
        s.max_requests_per_minute = self._to_int(
            active_snapshot.get("max_requests_per_minute"),
            s.max_requests_per_minute,
        )
        s.delay = self._to_float(active_snapshot.get("delay"), s.delay)
        s.max_tokens = self._to_int(active_snapshot.get("max_tokens"), s.max_tokens)
        s.temperature = self._to_float(active_snapshot.get("temperature"), s.temperature)
        s.top_p = self._to_float(active_snapshot.get("top_p"), s.top_p)
        s.retry_attempts = self._to_int(active_snapshot.get("retry_attempts"), s.retry_attempts)
        s.retry_timeout = self._to_float(active_snapshot.get("retry_timeout"), s.retry_timeout)
        s.proxy = str(active_snapshot.get("proxy", "") or "")
        s.frequency_penalty = self._to_float(
            active_snapshot.get("frequency_penalty"),
            s.frequency_penalty,
        )
        s.presence_penalty = self._to_float(
            active_snapshot.get("presence_penalty"),
            s.presence_penalty,
        )
        s.provider_profiles = {
            key: {
                field: snapshot.get(field)
                for field in self.SNAPSHOT_FIELDS
            }
            for key, snapshot in self._provider_snapshots.items()
            if key in {"openai", "google"}
        }


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")

        self._settings = settings

        main_layout = QVBoxLayout(self)

        trans_group = QGroupBox("Translator")
        main_layout.addWidget(trans_group)
        t_layout = QGridLayout(trans_group)

        t_layout.addWidget(QLabel("Translator"), 0, 0)
        self.translator_combo = QComboBox()
        self.translator_combo.addItem("DeepL", "DeepL")
        self.translator_combo.addItem("DeepL Free", "DeepL_free")
        self.translator_combo.addItem("Google", "google")
        self.translator_combo.addItem("Papago", "Papago")
        self.translator_combo.addItem("LLM API Translator", "LLM_API_Translator")
        t_layout.addWidget(self.translator_combo, 0, 1)

        t_layout.addWidget(QLabel("Source"), 1, 0)
        self.source_lang_combo = QComboBox()
        _add_lang_items(self.source_lang_combo)
        t_layout.addWidget(self.source_lang_combo, 1, 1)

        t_layout.addWidget(QLabel("Target"), 1, 2)
        self.target_lang_combo = QComboBox()
        _add_lang_items(self.target_lang_combo)
        t_layout.addWidget(self.target_lang_combo, 1, 3)

        t_layout.addWidget(QLabel("STT backend"), 2, 0)
        self.stt_backend_combo = QComboBox()
        self.stt_backend_combo.addItem("CUDA (faster, GPU)", "cuda")
        self.stt_backend_combo.addItem("CPU (compatible)", "cpu")
        t_layout.addWidget(self.stt_backend_combo, 2, 1)

        t_layout.addWidget(QLabel("Input device (Windows)"), 3, 0)
        self.input_device_combo = QComboBox()
        t_layout.addWidget(self.input_device_combo, 3, 1)

        t_layout.addWidget(QLabel("Output device (Windows)"), 3, 2)
        self.output_device_combo = QComboBox()
        t_layout.addWidget(self.output_device_combo, 3, 3)

        self._audio_inputs, self._audio_outputs = _list_audio_devices()
        self._populate_audio_device_combos()

        self.stack = AdaptiveStackedWidget()
        main_layout.addWidget(self.stack)

        self.deepl_page = DeepLPage()
        self.deepl_free_page = DeepLPage()
        self.google_page = GooglePage()
        self.papago_page = PapagoPage()
        self.llm_page = LLMPage()

        self.stack.addWidget(self.deepl_page)       # index 0
        self.stack.addWidget(self.deepl_free_page)  # index 1
        self.stack.addWidget(self.google_page)      # index 2
        self.stack.addWidget(self.papago_page)      # index 3
        self.stack.addWidget(self.llm_page)         # index 4

        self.translator_combo.currentIndexChanged.connect(self._on_translator_changed)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self._load_from_settings()

    def _populate_audio_device_combos(self) -> None:
        self.input_device_combo.clear()
        self.output_device_combo.clear()

        self.input_device_combo.addItem("Windows default input", -1)
        self.output_device_combo.addItem("Windows default output", -1)

        for label, idx in self._audio_inputs:
            self.input_device_combo.addItem(f"Input: {label}", idx)

        for label, idx in self._audio_outputs:
            self.output_device_combo.addItem(f"Output: {label}", idx)

    def _combo_data_to_int(self, combo: QComboBox, default: int = -1) -> int:
        value = combo.currentData()
        try:
            return int(value)
        except Exception:
            return default

    def _load_from_settings(self) -> None:
        s = self._settings

        idx = self.translator_combo.findData(s.translator_type)
        if idx >= 0:
            self.translator_combo.setCurrentIndex(idx)

        idx = self.source_lang_combo.findData(s.source_lang)
        if idx >= 0:
            self.source_lang_combo.setCurrentIndex(idx)

        idx = self.target_lang_combo.findData(s.target_lang)
        if idx >= 0:
            self.target_lang_combo.setCurrentIndex(idx)

        stt_backend = (s.stt.backend or "cuda").strip().lower()
        idx = self.stt_backend_combo.findData(stt_backend)
        if idx >= 0:
            self.stt_backend_combo.setCurrentIndex(idx)

        try:
            input_device_index = int(s.stt.input_device_index)
        except Exception:
            input_device_index = -1

        try:
            output_device_index = int(s.stt.output_device_index)
        except Exception:
            output_device_index = -1

        idx = self.input_device_combo.findData(input_device_index)
        self.input_device_combo.setCurrentIndex(idx if idx >= 0 else 0)

        idx = self.output_device_combo.findData(output_device_index)
        self.output_device_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.deepl_page.load(s.deepl)
        self.deepl_free_page.load(s.deepl_free)
        self.google_page.load(s.google)
        self.papago_page.load(s.papago)
        self.llm_page.load(s.llm)

        self._sync_stack_page()

    def _sync_stack_page(self) -> None:
        key = self.translator_combo.currentData()
        mapping = {
            "DeepL": 0,
            "DeepL_free": 1,
            "google": 2,
            "Papago": 3,
            "LLM_API_Translator": 4,
        }
        idx = mapping.get(key, 4)
        self.stack.setCurrentIndex(idx)
        self.stack.updateGeometry()
        self.adjustSize()

    def _on_translator_changed(self, _index: int) -> None:
        self._sync_stack_page()

    def apply_to_settings(self) -> None:
        s = self._settings

        s.translator_type = self.translator_combo.currentData()
        s.source_lang = self.source_lang_combo.currentData()
        s.target_lang = self.target_lang_combo.currentData()
        s.stt.backend = self.stt_backend_combo.currentData()
        s.stt.input_device_index = self._combo_data_to_int(self.input_device_combo, -1)
        s.stt.output_device_index = self._combo_data_to_int(self.output_device_combo, -1)

        self.deepl_page.apply(s.deepl)
        self.deepl_free_page.apply(s.deepl_free)
        self.google_page.apply(s.google)
        self.papago_page.apply(s.papago)
        self.llm_page.apply(s.llm)





