from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

MODEL_ENV_VAR = "JARVIS_STT_MODEL"
KEY_ENV_VAR = "OPENROUTER_API_KEY"
BASE_URL_ENV_VAR = "JARVIS_STT_BASE_URL"
DEFAULT_MODEL = "google/gemini-2.5-flash"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 45.0
MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 25
FORMATS: Mapping[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
}
DEFAULT_FORMAT = "webm"
PROMPT_RU = (
    "Расшифруй запись дословно и верни только текст на русском языке. Не "
    "добавляй пояснений, кавычек, знаков диктора и служебных пометок. Если "
    "речи нет, верни пустую строку."
)
PROMPT_EN = (
    "Transcribe the recording verbatim and return the text only, in English. "
    "Add no explanations, no quotation marks and no speaker labels. If there "
    "is no speech, return an empty string."
)
Opener = Callable[[urllib.request.Request, float], Any]


class SttError(RuntimeError):
    pass


class SttUnavailable(SttError):
    pass


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    lang: str

    def as_dict(self) -> dict[str, str]:
        return {"text": self.text, "lang": self.lang}


def normalize_lang(lang: str | None) -> str:
    text = str(lang or "ru").strip().lower()
    return "en" if text.startswith("en") else "ru"


def audio_format(content_type: str | None) -> str:
    text = str(content_type or "").split(";", 1)[0].strip().lower()
    return FORMATS.get(text, DEFAULT_FORMAT)


def check_audio(audio: bytes) -> bytes:
    if not audio:
        raise SttError(
            "тело запроса пустое: расшифровывать нечего, запись не дошла до "
            "сервера"
        )
    if len(audio) > MAX_AUDIO_BYTES:
        raise SttError(
            f"запись весит {len(audio)} байт при пределе {MAX_AUDIO_BYTES}: "
            f"держите фразу короче {MAX_SECONDS} секунд"
        )
    return audio


def prompt(lang: str) -> str:
    return PROMPT_EN if lang == "en" else PROMPT_RU


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def extract_text(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping):
        raise SttUnavailable(
            "модель расшифровки вернула ошибку: "
            f"{error.get('message', 'без описания')}"
        )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SttUnavailable(
            "ответ модели расшифровки не содержит ни одного варианта: "
            "расшифровки нет"
        )
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    raise SttUnavailable(
        "ответ модели расшифровки пришёл без текстового содержимого"
    )


class SttEngine:
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        opener: Opener | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        values = env if env is not None else os.environ
        self._key = str(values.get(KEY_ENV_VAR) or "")
        self._model = str(values.get(MODEL_ENV_VAR) or DEFAULT_MODEL)
        self._base_url = str(
            values.get(BASE_URL_ENV_VAR) or DEFAULT_BASE_URL
        ).rstrip("/")
        self._opener = opener if opener is not None else _default_opener
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._key)

    @property
    def model(self) -> str:
        return self._model

    def body(self, audio: bytes, lang: str, fmt: str) -> bytes:
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": prompt(lang)},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(audio).decode("ascii"),
                                "format": fmt,
                            },
                        }
                    ],
                },
            ],
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def transcribe(
        self, audio: bytes, lang: str | None = "ru", content_type: str | None = None
    ) -> Transcript:
        if not self._key:
            raise SttUnavailable(
                f"{KEY_ENV_VAR} не задан: расшифровка на сервере недоступна, "
                "распознавание остаётся браузерным"
            )
        chosen = normalize_lang(lang)
        fmt = audio_format(content_type)
        body = self.body(check_audio(audio), chosen, fmt)
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Title": "AIOS Jarvis",
            },
        )
        try:
            response = self._opener(request, self._timeout)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            raise SttUnavailable(
                f"модель расшифровки ответила {error.code}: "
                f"{detail or error.reason}"
            ) from error
        except urllib.error.URLError as error:
            raise SttUnavailable(
                f"модель расшифровки недоступна: {error.reason}"
            ) from error
        with response:
            raw = response.read()
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SttUnavailable(
                f"ответ модели расшифровки не разбирается как JSON: {error}"
            ) from error
        if not isinstance(loaded, Mapping):
            raise SttUnavailable(
                "ответ модели расшифровки не является объектом JSON"
            )
        return Transcript(text=extract_text(loaded), lang=chosen)


__all__ = [
    "DEFAULT_MODEL",
    "FORMATS",
    "MAX_AUDIO_BYTES",
    "MAX_SECONDS",
    "SttEngine",
    "SttError",
    "SttUnavailable",
    "Transcript",
    "audio_format",
    "check_audio",
    "extract_text",
    "normalize_lang",
    "prompt",
]
