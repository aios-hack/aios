from __future__ import annotations

from backend.contexts.assistant.domain.errors import (
    TtsError,
)

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from backend.shared.paths import repository_root as _shared_repository_root
from backend.shared.settings import Settings

OUT_ENV_VAR = "AIOS_OUT_DIR"
CACHE_DIR_ENV_VAR = "AIOS_JARVIS_TTS_CACHE"
VOICE_RU_ENV_VAR = "JARVIS_TTS_VOICE_RU"
VOICE_EN_ENV_VAR = "JARVIS_TTS_VOICE_EN"
DEFAULT_VOICE_RU = "ru-RU-SvetlanaNeural"
DEFAULT_VOICE_EN = "en-US-AriaNeural"
CONTENT_TYPE = "audio/mpeg"
TEXT_LIMIT = 2000
VOICE_PATTERN = re.compile(r"^[A-Za-z]{2,3}-[A-Za-z0-9]{2,8}-[A-Za-z0-9]{1,40}$")
CODE_SPOKEN_RU = "фрагмент кода"
CODE_SPOKEN_EN = "a code fragment"
FENCE_PATTERN = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.DOTALL)
INDENTED_CODE = re.compile(r"^(?: {4}|\t)\S.*$", re.MULTILINE)
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
QUOTE_PATTERN = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
RULE_PATTERN = re.compile(r"^\s{0,3}(?:[-*_]\s?){3,}\s*$", re.MULTILINE)
BULLET_PATTERN = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,3}[.)])\s+", re.MULTILINE)
TABLE_PATTERN = re.compile(r"^\s{0,3}\|.*\|\s*$", re.MULTILINE)
LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
INLINE_CODE = re.compile(r"`([^`]+)`")
EMPHASIS_PATTERN = re.compile(r"(\*{1,3}|_{1,3})(\S.*?\S|\S)\1", re.DOTALL)
SPACE_PATTERN = re.compile(r"[ \t]+")
BLANK_PATTERN = re.compile(r"\n{3,}")


class TtsUnavailable(TtsError):
    pass


@dataclass(frozen=True, slots=True)
class Voice:
    identifier: str
    lang: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.identifier, "lang": self.lang, "name": self.name}


def repository_root() -> Path:
    return _shared_repository_root(Path.cwd())


def default_cache_root(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    if resolved.jarvis_tts_cache is not None:
        return resolved.jarvis_tts_cache
    base = resolved.out_root if resolved.raw.get(OUT_ENV_VAR) else repository_root() / "out"
    return base / "jarvis" / "tts"


def default_voice(lang: str, settings: Settings | None = None) -> str:
    resolved = Settings.from_env() if settings is None else settings
    if str(lang or "ru").lower().startswith("en"):
        return resolved.voice_en
    return resolved.voice_ru


def check_voice(voice: str) -> str:
    text = str(voice or "").strip()
    if not VOICE_PATTERN.match(text):
        raise TtsError(
            f"имя голоса {voice!r} не годится: ожидается короткое имя вида "
            "ru-RU-SvetlanaNeural"
        )
    return text


def strip_markdown(text: str, lang: str = "ru") -> str:
    spoken = CODE_SPOKEN_EN if str(lang).lower().startswith("en") else CODE_SPOKEN_RU
    body = FENCE_PATTERN.sub(f" {spoken}. ", text)
    body = INDENTED_CODE.sub(f" {spoken}. ", body)
    body = TABLE_PATTERN.sub(" ", body)
    body = RULE_PATTERN.sub(" ", body)
    body = HEADING_PATTERN.sub("", body)
    body = QUOTE_PATTERN.sub("", body)
    body = BULLET_PATTERN.sub("", body)
    body = LINK_PATTERN.sub(lambda match: match.group(1) or match.group(2), body)
    body = INLINE_CODE.sub(lambda match: match.group(1), body)
    body = EMPHASIS_PATTERN.sub(lambda match: match.group(2), body)
    body = SPACE_PATTERN.sub(" ", body)
    body = BLANK_PATTERN.sub("\n\n", body)
    return body.strip()


def check_text(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        raise TtsError(
            "текста для озвучки нет: поле text пустое, синтезировать нечего"
        )
    return body[:TEXT_LIMIT]


def cache_key(text: str, voice: str) -> str:
    digest = hashlib.sha256(f"{text}|{voice}".encode("utf-8"))
    return digest.hexdigest()


def _module() -> Any:
    try:
        import edge_tts
    except ImportError as error:
        raise TtsUnavailable(
            "пакет edge-tts не установлен: синтез речи на сервере недоступен, "
            "поставьте зависимость группы jarvis (pip install -e .[jarvis])"
        ) from error
    return edge_tts


async def _collect(module: Any, text: str, voice: str) -> bytes:
    chunks: list[bytes] = []
    stream = module.Communicate(text, voice).stream()
    async for chunk in stream:
        if chunk.get("type") == "audio":
            data = chunk.get("data")
            if isinstance(data, (bytes, bytearray)):
                chunks.append(bytes(data))
    return b"".join(chunks)


async def _voices(module: Any) -> list[dict[str, Any]]:
    return list(await module.list_voices())


class TtsEngine:
    def __init__(self, cache_root: Path | str | None = None) -> None:
        self._root = (
            Path(cache_root) if cache_root is not None else default_cache_root()
        )

    @property
    def cache_root(self) -> Path:
        return self._root

    @property
    def available(self) -> bool:
        try:
            _module()
        except TtsUnavailable:
            return False
        return True

    def path(self, text: str, voice: str) -> Path:
        return self._root / f"{cache_key(text, voice)}.mp3"

    def _store(self, path: Path, audio: bytes) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".part")
            temporary.write_bytes(audio)
            temporary.replace(path)
        except OSError:
            return

    def synthesize(self, text: str, lang: str = "ru", voice: str | None = None) -> bytes:
        module = _module()
        spoken = check_text(strip_markdown(check_text(text), lang))
        chosen = check_voice(voice) if voice else default_voice(lang)
        path = self.path(spoken, chosen)
        try:
            if path.is_file():
                cached = path.read_bytes()
                if cached:
                    return cached
        except OSError:
            pass
        try:
            audio = asyncio.run(_collect(module, spoken, chosen))
        except Exception as error:
            raise TtsUnavailable(
                f"синтез речи голосом {chosen} не удался: {error}. Служба "
                "нейроголосов Microsoft требует сети, при её отсутствии "
                "озвучка остаётся браузерной"
            ) from error
        if not audio:
            raise TtsUnavailable(
                f"служба нейроголосов вернула пустой поток для голоса {chosen}: "
                "озвучить нечего"
            )
        self._store(path, audio)
        return audio

    def stream(
        self, text: str, lang: str = "ru", voice: str | None = None, chunk: int = 16384
    ) -> Iterator[bytes]:
        audio = self.synthesize(text, lang, voice)
        for start in range(0, len(audio), chunk):
            yield audio[start : start + chunk]

    def voices(self, lang: str | None = None) -> list[Voice]:
        module = _module()
        try:
            listed = asyncio.run(_voices(module))
        except Exception as error:
            raise TtsUnavailable(
                f"список нейроголосов не получен: {error}. Служба Microsoft "
                "требует сети"
            ) from error
        wanted = str(lang or "").lower()
        collected: list[Voice] = []
        for item in listed:
            locale = str(item.get("Locale") or "")
            if wanted and not locale.lower().startswith(wanted):
                continue
            collected.append(
                Voice(
                    identifier=str(item.get("ShortName") or ""),
                    lang=locale,
                    name=str(item.get("FriendlyName") or item.get("Name") or ""),
                )
            )
        collected.sort(key=lambda voice: (voice.lang, voice.identifier))
        return [voice for voice in collected if voice.identifier]


__all__ = [
    "CONTENT_TYPE",
    "DEFAULT_VOICE_EN",
    "DEFAULT_VOICE_RU",
    "TEXT_LIMIT",
    "TtsEngine",
    "TtsError",
    "TtsUnavailable",
    "Voice",
    "cache_key",
    "check_text",
    "check_voice",
    "default_cache_root",
    "default_voice",
    "strip_markdown",
]
