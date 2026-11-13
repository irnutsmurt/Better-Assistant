"""Voice match (experimental, off by default): who is speaking, from voices trained on the Voice
training page. Runs on this machine with numpy (core/titanet.py); the model (about 19 MB) is downloaded
from this project's GitHub repository the first time voice match is turned on.

Files under /config/better_assistant/:
  models/titanet.json, models/titanet.npz   the speaker model
  voice/<train|test|other>/<person>/<clip>.wav/.json/.emb.npy   clips, notes and cached embeddings
  voice/prints.json                          each person's voiceprint, threshold and grade"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiohttp
import numpy as np

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .core import voicematch as vm
from .core.voicetrain import TEST, TRAIN, person_slug

_LOGGER = logging.getLogger(__name__)

# on a branch of this repository (not a release, which HACS would offer as a version)
MODEL_URL = "https://raw.githubusercontent.com/irnutsmurt/Better-Assistant/voice-model/{}"
MODEL_FILES = {
    "titanet.json": "a3d1169da0913bb68dce362f15f44994ee04a17df3ab921e8ce16cf34e4d388e",
    "titanet.npz": "4142c0685c60fac35aabb92cca9ead990d1cb96661e18d2ae6c51c4de007ef51",
}
OTHER = "other"                     # "someone else / the TV": kept as a not-this-household example
RECENT_SECONDS = 20.0               # a decision applies to the request it came with
KEEP_DAYS = 14                      # unconfirmed everyday clips are deleted after this


def models_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("better_assistant", "models"))


def voice_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("better_assistant", "voice"))


# ------------------------------------------------------------------ files (executor)
def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _read_wav(path: Path) -> np.ndarray:
    data = path.read_bytes()[44:]
    return np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def clip_id(path: Path, root: Path) -> str:
    """'train/rob/20261113T161242Z_1' -> 'train~rob~20261113T161242Z_1' (safe in a URL)."""
    rel = path.relative_to(root).with_suffix("")
    return "~".join(rel.parts)


def clip_path(root: Path, cid: str) -> Path | None:
    parts = cid.split("~")
    if len(parts) != 3 or any(not p or p in (".", "..") or "/" in p or "\\" in p for p in parts):
        return None
    if parts[0] not in (TRAIN, TEST, OTHER):
        return None
    path = root.joinpath(*parts).with_suffix(".wav")
    return path if path.is_file() else None


def read_meta(wav: Path) -> dict[str, Any]:
    try:
        return json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(wav: Path, meta: dict[str, Any]) -> None:
    wav.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def delete_clip(wav: Path) -> None:
    for name in (wav.name, wav.stem + ".json", wav.stem + ".emb.npy"):
        (wav.parent / name).unlink(missing_ok=True)


def move_clip(root: Path, wav: Path, label: str, person: str) -> Path:
    """Move a clip and its files to <label>/<person>/, keeping its name."""
    folder = root / label / person_slug(person) if label != OTHER else root / OTHER / "other"
    folder.mkdir(parents=True, exist_ok=True)
    new = folder / wav.name
    n = 1
    while new.exists() and new != wav:                 # same name already there: don't overwrite it
        n += 1
        new = folder / f"{wav.stem}-{n}.wav"
    for suffix in (".wav", ".json"):
        src = wav.with_suffix(suffix)
        if src.exists():
            src.replace(new.with_suffix(suffix))
    emb = wav.with_name(wav.stem + ".emb.npy")
    if emb.exists():
        emb.replace(new.with_name(new.stem + ".emb.npy"))
    return new


def list_clips(root: Path) -> list[Path]:
    out = []
    for label in (TRAIN, TEST, OTHER):
        base = root / label
        if base.is_dir():
            out += [p for p in base.glob("*/*.wav")]
    return sorted(out, key=lambda p: p.name, reverse=True)


# ------------------------------------------------------------------ the matcher
class VoiceMatcher:
    """One per config entry. Status: off / downloading / ready / error."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass, self.entry = hass, entry
        self.status = "off"
        self.problem = ""
        self.prints: list[dict] = []
        self._embedder = None
        self._strangers: np.ndarray | None = None
        self._last: tuple[vm.Match, float] | None = None
        self._listeners: list = []
        self._lock = asyncio.Lock()
        self._unsub = None

    # ------------------------------------------------------------ lifecycle
    def add_listener(self, listener) -> callable:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_start(self) -> None:
        """Download the model if needed, load it and build the voiceprints (in the background)."""
        self._unsub = async_track_time_interval(self.hass, self._async_tidy, timedelta(hours=12))
        try:
            await self._async_download()
            self._embedder = await self.hass.async_add_executor_job(self._load)
            self.status = "ready"
            await self.async_rebuild()
            await self._async_tidy()
        except Exception as err:  # noqa: BLE001 - voice match must never break the integration
            _LOGGER.warning("Voice match couldn't start: %s", err, exc_info=True)
            self.status, self.problem = "error", str(err) or type(err).__name__
        self._changed()

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _async_download(self) -> None:
        folder = models_dir(self.hass)
        await self.hass.async_add_executor_job(lambda: folder.mkdir(parents=True, exist_ok=True))
        session = async_get_clientsession(self.hass)
        for name, digest in MODEL_FILES.items():
            path = folder / name
            if await self.hass.async_add_executor_job(lambda p=path: p.exists() and _sha(p) == digest):
                continue
            self.status = "downloading"
            self._changed()
            async with session.get(MODEL_URL.format(name), timeout=aiohttp.ClientTimeout(total=300)) as resp:
                resp.raise_for_status()
                data = await resp.read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"the downloaded {name} didn't match its checksum")
            await self.hass.async_add_executor_job(path.write_bytes, data)

    def _load(self):
        from .core.titanet import Embedder  # noqa: PLC0415 - only when voice match is on
        folder = models_dir(self.hass)
        self._strangers = np.load(Path(__file__).parent / "data" / "strangers.npy").astype(np.float32)
        return Embedder(str(folder / "titanet.json"), str(folder / "titanet.npz"))

    # ------------------------------------------------------------ embeddings
    def _embed_samples(self, samples: np.ndarray) -> np.ndarray:
        return vm.unit(self._embedder(vm.trim_silence(samples)))

    def _embed_file(self, wav: Path) -> np.ndarray | None:
        cache = wav.with_name(wav.stem + ".emb.npy")
        try:
            if cache.exists() and cache.stat().st_mtime >= wav.stat().st_mtime:
                return np.load(cache)
            emb = self._embed_samples(_read_wav(wav))
            np.save(cache, emb.astype(np.float32))
            return emb
        except Exception:  # noqa: BLE001 - a broken clip is just skipped
            _LOGGER.debug("Voice match: couldn't read %s", wav, exc_info=True)
            return None

    # ------------------------------------------------------------ voiceprints
    def _rebuild(self) -> list[dict]:
        root = voice_dir(self.hass)
        by_person: dict[str, dict[str, np.ndarray]] = {}
        for wav in list_clips(root):
            meta = read_meta(wav)
            label = wav.parent.parent.name
            person = meta.get("person")
            # training clips, and everyday clips someone confirmed ("That was Rob")
            if not person or person == "unknown" or label == OTHER:
                continue
            if label == TEST and meta.get("confirmed") != person:
                continue
            emb = self._embed_file(wav)
            if emb is not None:
                by_person.setdefault(person, {})[clip_id(wav, root)] = emb
        prints = [vm.build_print(p, clips, self._strangers).as_dict() for p, clips in sorted(by_person.items())]
        if root.is_dir():
            (root / "prints.json").write_text(json.dumps(prints), encoding="utf-8")
        return prints

    async def async_rebuild(self) -> None:
        if self.status != "ready":
            return
        async with self._lock:
            self.prints = await self.hass.async_add_executor_job(self._rebuild)
        self._changed()

    # ------------------------------------------------------------ who is speaking
    async def async_identify(self, pcm: bytes, sample_rate: int) -> vm.Match | None:
        """The decision for one request's audio, kept for the agent to read (see recent())."""
        if self.status != "ready" or not self.prints or sample_rate != 16000 or len(pcm) < 16000:
            return None
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        try:
            emb = await self.hass.async_add_executor_job(self._embed_samples, samples)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Voice match: couldn't identify", exc_info=True)
            return None
        match = vm.identify(emb, self.prints)
        self._last = (match, time.time())
        return match

    def recent(self) -> vm.Match | None:
        if self._last and time.time() - self._last[1] <= RECENT_SECONDS:
            return self._last[0]
        return None

    # ------------------------------------------------------------ housekeeping
    async def _async_tidy(self, _now=None) -> None:
        """Delete unconfirmed everyday clips older than KEEP_DAYS."""
        cutoff = dt_util.utcnow().timestamp() - KEEP_DAYS * 86400

        def tidy() -> None:
            for wav in list_clips(voice_dir(self.hass)):
                if wav.parent.parent.name == TEST and not read_meta(wav).get("confirmed") \
                        and wav.stat().st_mtime < cutoff:
                    delete_clip(wav)
        await self.hass.async_add_executor_job(tidy)

    def summary(self, names: dict[str, str]) -> dict[str, Any]:
        return {"status": self.status, "problem": self.problem,
                "people": [{"person": p["person"], "name": names.get(p["person"], p["person"]),
                            "grade": p["grade"], "clips": len(p["clips"]), "dropped": len(p["dropped"])}
                           for p in self.prints]}
