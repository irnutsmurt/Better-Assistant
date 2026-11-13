"""Speech-to-text pass-through (voice training, experimental). Wraps a real engine (Home Assistant
Cloud, Whisper over Wyoming, ...): audio and the engine's answer pass through untouched, and while a
recording is wanted the raw audio is also copied to a WAV file. Without voice training on, nothing is
kept.

Home Assistant gives a speech-to-text engine only the audio and its format, not which speaker it came
from, so recordings are labelled from the "pending capture" slot the agent arms (see
core/voicetrain.py), or as everyday "test" clips when that option is on."""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterable
from typing import Any

from homeassistant.components import stt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterAssistantConfigEntry
from .const import OPT_VT_ENABLED, OPT_VT_RECORD_TEST
from .core.voicetrain import NOTHING_HEARD, TEST, TRAIN, CaptureSlot, is_stop, matches_phrase, max_bytes, too_short
from .sensor import device_info
from .voice_setup import pipeline_select
from .voice_training import guess_person, hub, underlying_engine, voice_root, write_clip

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([PassThroughSTT(entry)])


class PassThroughSTT(stt.SpeechToTextEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "speech_to_text"
    _attr_icon = "mdi:microphone-message"

    def __init__(self, entry: BetterAssistantConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_stt"
        self._attr_device_info = device_info(entry)

    # ------------------------------------------------------------ the engine underneath
    def _engine(self):
        """The wrapped entity (or legacy provider), or None."""
        engine_id = underlying_engine(self.hass, dict(self._entry.options))
        if not engine_id or engine_id == self.entity_id:
            return None
        return stt.async_get_speech_to_text_engine(self.hass, engine_id)

    def _mirror(self, attr: str) -> list:
        engine = self._engine()
        return list(getattr(engine, attr, None) or []) if engine else []

    @property
    def supported_languages(self) -> list[str]:
        return self._mirror("supported_languages")

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return self._mirror("supported_formats")

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return self._mirror("supported_codecs")

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return self._mirror("supported_bit_rates")

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return self._mirror("supported_sample_rates")

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return self._mirror("supported_channels")

    @property
    def audio_processing(self) -> stt.SpeechAudioProcessing:
        engine = self._engine()
        return getattr(engine, "audio_processing", None) or super().audio_processing

    # ------------------------------------------------------------ the audio
    def _slot(self) -> CaptureSlot | None:
        """What to record this stream as, or None. A training prompt wins over everyday recording."""
        if not self._entry.options.get(OPT_VT_ENABLED):
            return None
        slot = hub(self.hass).take(time.time())
        if slot:
            return slot
        if self._entry.options.get(OPT_VT_RECORD_TEST):
            return CaptureSlot(person=guess_person(self.hass), label=TEST)
        return None

    async def async_process_audio_stream(self, metadata: stt.SpeechMetadata,
                                         stream: AsyncIterable[bytes]) -> stt.SpeechResult:
        engine = self._engine()
        if engine is None:
            _LOGGER.warning("Better Assistant speech-to-text has no engine to pass audio to")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            slot = self._slot()
            pcm_ok = metadata.codec == stt.AudioCodecs.PCM and int(metadata.bit_rate) == 16 \
                and int(metadata.channel) == 1
        except Exception:  # noqa: BLE001 - recording must never break speech-to-text
            _LOGGER.debug("Voice training: capture setup failed", exc_info=True)
            slot, pcm_ok = None, False
        if not pcm_ok:
            slot = None
        chunks: list[bytes] = []
        limit = max_bytes(int(metadata.sample_rate)) if slot else 0

        async def tee() -> AsyncIterable[bytes]:
            size = 0
            async for chunk in stream:
                if slot and size < limit:
                    chunks.append(chunk)
                    size += len(chunk)
                yield chunk

        if isinstance(engine, stt.SpeechToTextEntity):
            result = await engine.internal_async_process_audio_stream(metadata, tee())
        else:
            result = await engine.async_process_audio_stream(metadata, tee())
        if slot and result.result == stt.SpeechResultState.SUCCESS:
            self._save(slot, metadata, b"".join(chunks), result.text or "")
        if slot and slot.label == TRAIN and result.result == stt.SpeechResultState.SUCCESS \
                and not (result.text or "").strip():
            # "no text" would end the conversation; mid-training it should be asked again instead
            return stt.SpeechResult(NOTHING_HEARD, stt.SpeechResultState.SUCCESS)
        return result

    def _save(self, slot: CaptureSlot, metadata: stt.SpeechMetadata, pcm: bytes, transcript: str) -> None:
        """Write in the background. Not for empty audio, "stop voice training" or a mumble."""
        try:
            if not pcm or too_short(transcript) or is_stop(transcript):
                return
            if slot.label == TRAIN and slot.phrase and not matches_phrase(slot.phrase, transcript):
                return                                     # not the phrase: training asks again
            info: dict[str, Any] = {
                "transcript": transcript, "prompt": slot.phrase, "satellite": slot.satellite,
                "device_id": slot.device_id, "pipeline": self._pipeline_of(slot.satellite),
                "language": metadata.language}
            capture = hub(self.hass)
            capture.note_saved(slot.token)                 # counted now: the agent's turn comes next

            async def write() -> None:
                try:
                    await self.hass.async_add_executor_job(
                        write_clip, voice_root(self.hass), slot.label, slot.person, pcm,
                        int(metadata.sample_rate), info)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Voice training: could not write the recording", exc_info=True)
                    if slot.token and capture.saved.get(slot.token):
                        capture.saved[slot.token] -= 1

            self._entry.async_create_background_task(self.hass, write(), "better_assistant_voice_clip")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Voice training: capture failed", exc_info=True)

    def _pipeline_of(self, satellite: str | None) -> str | None:
        select = pipeline_select(self.hass, satellite) if satellite else None
        state = self.hass.states.get(select) if select else None
        return state.state if state else None
