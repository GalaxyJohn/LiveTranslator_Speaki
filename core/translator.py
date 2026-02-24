from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from typing import Deque

from .config import AppSettings, DeepLFreeSettings, DeepLSettings, LLMTranslatorSettings, PapagoSettings


class TranslatorError(Exception):
    pass


class BaseTranslator(ABC):
    @abstractmethod
    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        raise NotImplementedError


class NotImplementedTranslator(BaseTranslator):
    def __init__(self, name: str) -> None:
        self.name = name

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        raise TranslatorError(f"{self.name} translator is not implemented yet.")


class OpenAILLMTranslator(BaseTranslator):
    def __init__(self, settings: LLMTranslatorSettings) -> None:
        self.settings = settings
        self._runtime_notices: list[str] = []

        api_key = settings.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise TranslatorError("OpenAI API key is not configured.")

        from openai import OpenAI

        try:
            from openai import DefaultHttpxClient
        except Exception:
            DefaultHttpxClient = None  # type: ignore[assignment]

        timeout: float | None = None
        if settings.retry_timeout and settings.retry_timeout > 0:
            timeout = float(settings.retry_timeout)
        self._request_timeout = timeout

        client_kwargs: dict[str, object] = {"api_key": api_key}

        endpoint = settings.endpoint.strip()
        if endpoint:
            client_kwargs["base_url"] = endpoint

        if timeout is not None:
            client_kwargs["timeout"] = timeout

        proxy = settings.proxy.strip()
        if proxy:
            if DefaultHttpxClient is None:
                self._runtime_notices.append(
                    "proxy is configured but this OpenAI SDK cannot apply it; running without proxy."
                )
            else:
                http_client_kwargs: dict[str, object] = {"proxy": proxy}
                if timeout is not None:
                    http_client_kwargs["timeout"] = timeout
                try:
                    client_kwargs["http_client"] = DefaultHttpxClient(**http_client_kwargs)
                except Exception as exc:
                    raise TranslatorError(f"Failed to apply proxy setting: {exc}") from exc

        self._client = OpenAI(**client_kwargs)

        if self.settings.multiple_keys.strip():
            self._runtime_notices.append(
                "multiple_keys is saved but not used by the current OpenAI translator."
            )
        if abs(float(self.settings.frequency_penalty)) > 0:
            self._runtime_notices.append(
                "frequency_penalty is currently not mapped for the Responses API in this app."
            )
        if abs(float(self.settings.presence_penalty)) > 0:
            self._runtime_notices.append(
                "presence_penalty is currently not mapped for the Responses API in this app."
            )

    def runtime_notices(self) -> list[str]:
        return list(self._runtime_notices)

    def _resolve_model_name(self) -> str:
        if self.settings.override_model.strip():
            return self.settings.override_model.strip()
        return self.settings.model.strip() or "gpt-4.1-mini"

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        if not text.strip():
            return ""

        if source_lang == "auto":
            src = "auto-detected source language"
        else:
            src = source_lang

        tgt = target_lang or "ko"

        system_prompt = self.settings.system_prompt or (
            "You are an expert translator. Translate the given text."
        )

        user_prompt = (
            f"Translate the following text from {src} to {tgt}.\n"
            f"Return only the translated text, without quotes or explanations.\n\n"
            f"{text}"
        )

        model_name = self._resolve_model_name()
        model_name_lc = model_name.lower()

        request_kwargs: dict[str, object] = {
            "model": model_name,
            "max_output_tokens": self.settings.max_tokens,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        # GPT-5.1/5.2 accept temperature/top_p only when reasoning effort is none.
        if model_name_lc.startswith("gpt-5.1") or model_name_lc.startswith("gpt-5.2"):
            request_kwargs["reasoning"] = {"effort": "none"}

        request_kwargs["temperature"] = self.settings.temperature
        request_kwargs["top_p"] = self.settings.top_p

        if self._request_timeout is not None:
            request_kwargs["timeout"] = self._request_timeout

        try:
            resp = self._client.responses.create(**request_kwargs)
        except Exception as exc:
            msg = str(exc)
            if "Unsupported parameter" in msg and "temperature" in msg:
                raise TranslatorError(
                    f"Model '{model_name}' cannot use temperature with current settings. "
                    "Use gpt-5.1/gpt-5.2 (reasoning none) or a model like gpt-4.1/gpt-4o."
                ) from exc
            raise

        translated = (resp.output_text or "").strip()
        if not translated:
            raise TranslatorError("OpenAI returned an empty translation.")
        return translated


class GeminiLLMTranslator(BaseTranslator):
    def __init__(self, settings: LLMTranslatorSettings) -> None:
        self.settings = settings
        self._runtime_notices: list[str] = []

        api_key = (
            settings.api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        if not api_key:
            raise TranslatorError("Google Gemini API key is not configured.")

        from google import genai
        from google.genai import types

        timeout: float | None = None
        if settings.retry_timeout and settings.retry_timeout > 0:
            timeout = float(settings.retry_timeout)
        self._request_timeout = timeout

        client_kwargs: dict[str, object] = {"api_key": api_key}
        http_options_kwargs: dict[str, object] = {}

        endpoint = settings.endpoint.strip()
        if endpoint:
            http_options_kwargs["base_url"] = endpoint

        if timeout is not None:
            http_options_kwargs["timeout"] = timeout

        proxy = settings.proxy.strip()
        if proxy:
            try:
                import httpx

                httpx_kwargs: dict[str, object] = {"proxy": proxy}
                if timeout is not None:
                    httpx_kwargs["timeout"] = timeout
                http_options_kwargs["httpx_client"] = httpx.Client(**httpx_kwargs)
            except Exception as exc:
                raise TranslatorError(f"Failed to apply Gemini proxy setting: {exc}") from exc

        if http_options_kwargs:
            client_kwargs["http_options"] = types.HttpOptions(**http_options_kwargs)

        self._client = genai.Client(**client_kwargs)
        self._types = types
        self._model_name = self._resolve_model_name()

        if self.settings.multiple_keys.strip():
            self._runtime_notices.append(
                "multiple_keys is saved but not used by the current Gemini translator."
            )

    def runtime_notices(self) -> list[str]:
        return list(self._runtime_notices)

    def _resolve_model_name(self) -> str:
        if self.settings.override_model.strip():
            return self.settings.override_model.strip()

        configured = self.settings.model.strip()
        if not configured:
            return "gemini-2.5-flash"
        if configured.lower().startswith("gpt-"):
            self._runtime_notices.append(
                f"Configured model '{configured}' looks like OpenAI; using 'gemini-2.5-flash' for Google provider."
            )
            return "gemini-2.5-flash"
        return configured

    def _extract_text(self, resp: object) -> str:
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(resp, "candidates", None)
        if not candidates:
            return ""

        parts: list[str] = []
        for cand in candidates:
            content = getattr(cand, "content", None)
            cand_parts = getattr(content, "parts", None)
            if not cand_parts:
                continue
            for p in cand_parts:
                p_text = getattr(p, "text", None)
                if isinstance(p_text, str) and p_text.strip():
                    parts.append(p_text.strip())

        return "\n".join(parts).strip()

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        if not text.strip():
            return ""

        if source_lang == "auto":
            src = "auto-detected source language"
        else:
            src = source_lang

        tgt = target_lang or "ko"

        system_prompt = self.settings.system_prompt or (
            "You are an expert translator. Translate the given text."
        )
        user_prompt = (
            f"Translate the following text from {src} to {tgt}.\n"
            f"Return only the translated text, without quotes or explanations.\n\n"
            f"{text}"
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": system_prompt,
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "max_output_tokens": self.settings.max_tokens,
            "frequency_penalty": self.settings.frequency_penalty,
            "presence_penalty": self.settings.presence_penalty,
        }
        if self._request_timeout is not None:
            config_kwargs["http_options"] = self._types.HttpOptions(timeout=self._request_timeout)

        resp = self._client.models.generate_content(
            model=self._model_name,
            contents=user_prompt,
            config=self._types.GenerateContentConfig(**config_kwargs),
        )

        translated = self._extract_text(resp)
        if not translated:
            raise TranslatorError("Gemini returned an empty translation.")
        return translated


class _HttpTranslatorBase(BaseTranslator):
    def __init__(self, timeout_sec: float = 20.0) -> None:
        self._timeout_sec = max(1.0, float(timeout_sec))

    def _post_form(
        self,
        url: str,
        form: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict:
        encoded = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except Exception as exc:
            raise TranslatorError(str(exc)) from exc

        try:
            return json.loads(body)
        except Exception as exc:
            raise TranslatorError(f"Invalid JSON response from translator API: {exc}") from exc

    def _get_json(self, url: str) -> object:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except Exception as exc:
            raise TranslatorError(str(exc)) from exc

        try:
            return json.loads(body)
        except Exception as exc:
            raise TranslatorError(f"Invalid JSON response from translator API: {exc}") from exc


class DeepLHTTPTranslator(_HttpTranslatorBase):
    def __init__(
        self,
        settings: DeepLSettings | DeepLFreeSettings,
        *,
        use_free_endpoint: bool,
    ) -> None:
        super().__init__(timeout_sec=30.0)
        self.settings = settings
        self.use_free_endpoint = use_free_endpoint
        self._runtime_notices: list[str] = []

        api_key = settings.api_key.strip()
        if not api_key:
            key_name = "DeepL Free" if use_free_endpoint else "DeepL"
            raise TranslatorError(f"{key_name} API key is not configured.")
        self._api_key = api_key

        if use_free_endpoint:
            self._url = "https://api-free.deepl.com/v2/translate"
        else:
            self._url = "https://api.deepl.com/v2/translate"

    def runtime_notices(self) -> list[str]:
        return list(self._runtime_notices)

    def _map_lang(self, lang: str, *, target: bool) -> str:
        code = (lang or "").strip()
        if not code:
            return "KO" if target else ""

        low = code.lower()
        if low == "auto":
            return "KO" if target else ""
        if low == "zh-cn":
            return "ZH"
        return code.upper()

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        if not text.strip():
            return ""

        target = self._map_lang(target_lang, target=True)
        source = self._map_lang(source_lang, target=False)

        form: dict[str, str] = {
            "text": text,
            "target_lang": target,
        }
        if source:
            form["source_lang"] = source

        formality = (self.settings.formality or "").strip().lower()
        if formality in {"more", "less", "default"} and formality != "default":
            form["formality"] = formality

        preserve = (self.settings.preserve_formatting or "").strip().lower()
        if preserve in {"enabled", "disabled"}:
            form["preserve_formatting"] = "1" if preserve == "enabled" else "0"

        context = (self.settings.context or "").strip()
        if context:
            form["context"] = context

        data = self._post_form(
            self._url,
            form,
            headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
        )

        translations = data.get("translations")
        if not isinstance(translations, list) or not translations:
            msg = data.get("message") or data.get("detail") or "DeepL returned no translation."
            raise TranslatorError(str(msg))

        first = translations[0] if isinstance(translations[0], dict) else {}
        translated = str(first.get("text", "")).strip()
        if not translated:
            raise TranslatorError("DeepL returned an empty translation.")
        return translated


class GoogleWebTranslator(_HttpTranslatorBase):
    def __init__(self) -> None:
        super().__init__(timeout_sec=20.0)
        self._runtime_notices = [
            "Google translator uses the public web endpoint (no API key).",
        ]

    def runtime_notices(self) -> list[str]:
        return list(self._runtime_notices)

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        if not text.strip():
            return ""

        source = (source_lang or "auto").strip().lower() or "auto"
        target = (target_lang or "ko").strip().lower() or "ko"
        if target == "auto":
            target = "ko"

        params = {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": text,
        }
        url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(params)
        payload = self._get_json(url)

        if not isinstance(payload, list) or not payload:
            raise TranslatorError("Google translator returned an unexpected response.")

        parts = payload[0]
        if not isinstance(parts, list):
            raise TranslatorError("Google translator returned an unexpected response format.")

        translated_chunks: list[str] = []
        for item in parts:
            if isinstance(item, list) and item and isinstance(item[0], str):
                translated_chunks.append(item[0])

        translated = "".join(translated_chunks).strip()
        if not translated:
            raise TranslatorError("Google translator returned an empty translation.")
        return translated


class PapagoTranslator(_HttpTranslatorBase):
    def __init__(self, settings: PapagoSettings) -> None:
        super().__init__(timeout_sec=20.0)
        self.settings = settings
        self._runtime_notices: list[str] = []
        self._url = "https://openapi.naver.com/v1/papago/n2mt"

        self._client_id = settings.client_id.strip()
        self._client_secret = settings.client_secret.strip()
        if not self._client_id or not self._client_secret:
            raise TranslatorError("Papago client_id/client_secret are not configured.")

    def runtime_notices(self) -> list[str]:
        return list(self._runtime_notices)

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        if not text.strip():
            return ""

        source = (source_lang or "auto").strip().lower() or "auto"
        target = (target_lang or "ko").strip().lower() or "ko"
        if target == "auto":
            target = "ko"

        data = self._post_form(
            self._url,
            {
                "source": source,
                "target": target,
                "text": text,
            },
            headers={
                "X-Naver-Client-Id": self._client_id,
                "X-Naver-Client-Secret": self._client_secret,
            },
        )

        message = data.get("message")
        result = message.get("result") if isinstance(message, dict) else None
        translated = result.get("translatedText") if isinstance(result, dict) else None
        if not isinstance(translated, str) or not translated.strip():
            error_msg = data.get("errorMessage") or data.get("message") or "Papago returned no translation."
            raise TranslatorError(str(error_msg))
        return translated.strip()


def create_translator_from_settings(settings: AppSettings) -> BaseTranslator:
    t = settings.translator_type

    if t == "DeepL":
        return DeepLHTTPTranslator(settings.deepl, use_free_endpoint=False)

    if t == "DeepL_free":
        return DeepLHTTPTranslator(settings.deepl_free, use_free_endpoint=True)

    if t == "google":
        return GoogleWebTranslator()

    if t == "Papago":
        return PapagoTranslator(settings.papago)

    if t == "LLM_API_Translator":
        provider = settings.llm.provider.strip().lower()
        if provider == "openai":
            return OpenAILLMTranslator(settings.llm)
        if provider in {"google", "gemini"}:
            return GeminiLLMTranslator(settings.llm)
        raise TranslatorError(f"Unsupported LLM provider: {settings.llm.provider}")

    raise TranslatorError(f"Unsupported translator type: {t}")


class RateLimiter:
    """
    Simple limiter that enforces both a minimum delay and per-minute limit.
    """

    def __init__(self, max_per_minute: int, delay: float) -> None:
        self.max_per_minute = max_per_minute
        self.delay = max(delay, 0.0)
        self._timestamps: Deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()

            if self.delay > 0 and self._timestamps:
                last = self._timestamps[-1]
                remain = self.delay - (now - last)
                if remain > 0:
                    time.sleep(remain)
                    now = time.monotonic()

            if self.max_per_minute > 0:
                window = 60.0
                while self._timestamps and now - self._timestamps[0] > window:
                    self._timestamps.popleft()

                if len(self._timestamps) >= self.max_per_minute:
                    earliest = self._timestamps[0]
                    sleep_sec = window - (now - earliest)
                    if sleep_sec > 0:
                        time.sleep(sleep_sec)
                        now = time.monotonic()
                        while self._timestamps and now - self._timestamps[0] > window:
                            self._timestamps.popleft()

            self._timestamps.append(time.monotonic())
