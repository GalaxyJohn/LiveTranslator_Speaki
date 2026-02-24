from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict


@dataclass
class DeepLSettings:
    api_key: str = ""
    delay: float = 0.0
    formality: str = "default"  # default, more, less
    context: str = ""
    preserve_formatting: str = "disabled"  # disabled, enabled


@dataclass
class GoogleSettings:
    delay: float = 0.0


@dataclass
class PapagoSettings:
    client_id: str = ""
    client_secret: str = ""
    delay: float = 0.0


@dataclass
class LLMTranslatorSettings:
    provider: str = "OpenAI"  # OpenAI, Google
    api_key: str = ""
    multiple_keys: str = ""
    model: str = "gpt-4.1-mini"
    override_model: str = ""
    endpoint: str = ""

    system_prompt: str = (
        "You are an expert translator. Translate the given text accurately."
    )

    invalid_repeat_count: int = 2
    max_requests_per_minute: int = 60
    delay: float = 0.3
    max_tokens: int = 1024
    temperature: float = 0.1
    top_p: float = 1.0
    retry_attempts: int = 3
    retry_timeout: float = 15.0
    proxy: str = ""
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Provider-scoped snapshots (openai/google) managed by settings dialog.
    provider_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class DeepLFreeSettings:
    api_key: str = ""
    delay: float = 0.0
    formality: str = "default"  # default, more, less
    context: str = ""
    preserve_formatting: str = "disabled"  # disabled, enabled


@dataclass
class STTSettings:
    # "cuda" or "cpu"
    backend: str = "cuda"

    # Input/output device indices from PyAudio device list.
    # -1 means "use system default".
    input_device_index: int = -1
    output_device_index: int = -1


@dataclass
class AppSettings:
    translator_type: str = "LLM_API_Translator"  # DeepL, DeepL_free, google, Papago, LLM_API_Translator
    source_lang: str = "ja"
    target_lang: str = "ko"

    deepl: DeepLSettings = field(default_factory=DeepLSettings)
    deepl_free: DeepLFreeSettings = field(default_factory=DeepLFreeSettings)
    google: GoogleSettings = field(default_factory=GoogleSettings)
    papago: PapagoSettings = field(default_factory=PapagoSettings)
    llm: LLMTranslatorSettings = field(default_factory=LLMTranslatorSettings)
    stt: STTSettings = field(default_factory=STTSettings)

    @classmethod
    def load(cls, path: str) -> "AppSettings":
        if not os.path.exists(path):
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
        except Exception:
            return cls()

        def build(key: str, sub_cls):
            sub = data.get(key, {})
            if not isinstance(sub, dict):
                sub = {}
            try:
                return sub_cls(**sub)
            except TypeError:
                # Backward/forward compatibility fallback for unknown fields.
                allowed = {k: v for k, v in sub.items() if k in sub_cls.__dataclass_fields__}
                return sub_cls(**allowed)

        settings = cls(
            translator_type=data.get("translator_type", "LLM_API_Translator"),
            source_lang=data.get("source_lang", "ja"),
            target_lang=data.get("target_lang", "ko"),
            deepl=build("deepl", DeepLSettings),
            deepl_free=build("deepl_free", DeepLFreeSettings),
            google=build("google", GoogleSettings),
            papago=build("papago", PapagoSettings),
            llm=build("llm", LLMTranslatorSettings),
            stt=build("stt", STTSettings),
        )

        if not isinstance(settings.llm.provider_profiles, dict):
            settings.llm.provider_profiles = {}

        return settings

    def save(self, path: str) -> None:
        data = asdict(self)
        dirpath = os.path.dirname(path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)