"""Voice setup decisions with no Home Assistant imports: which Whisper model suits the hardware, which
add-on options to set, which speech engines to use and what the summary says."""
from __future__ import annotations

from dataclasses import dataclass, field

WHISPER_SLUG = "core_whisper"
PIPER_SLUG = "core_piper"
WHISPER_PORT = 10300
PIPER_PORT = 10200
PIPELINE_NAME = "Better Assistant"
INITIAL_PROMPT = "Questions and commands for a smart home."
GB = 1024 ** 3

# Rough download sizes in MB (add-on image, then model or voice), for the confirmation screen.
ADDON_MB = {WHISPER_SLUG: 500, PIPER_SLUG: 300}
MODEL_MB = {"tiny-int8": 45, "base-int8": 80, "base.en": 150, "small-int8": 250}
PIPER_VOICE_MB = 60

# Platforms whose assist_satellite entities are not home voice speakers we should touch.
NOT_SPEAKERS = {"cast", "google_assistant", "google_assistant_sdk", "alexa", "androidtv"}


def whisper_model(arch: str, ram_bytes: int, cpus: int) -> str:
    """Whisper model for this hardware. ARM boards and small machines get the int8 models; a Pi 4/5
    with 4 GB or more can manage base, anything less gets tiny. x86 gets base.en, or small with
    eight cores and 8 GB."""
    arch = (arch or "").lower()
    arm = arch.startswith(("aarch64", "arm"))
    if arm or ram_bytes < 3 * GB:
        return "base-int8" if arm and ram_bytes >= 3.5 * GB and cpus >= 4 else "tiny-int8"
    if cpus >= 8 and ram_bytes >= 7.5 * GB:                   # 8 GB machines report a little under 8
        return "small-int8"
    return "base.en"


def whisper_options(current: dict, model: str, language: str = "en") -> dict:
    """Options to change on the Whisper add-on: only keys it already has, so a renamed option in a
    later add-on version is left alone instead of being rejected."""
    wanted = {"model": model, "language": language, "initial_prompt": INITIAL_PROMPT}
    return {k: v for k, v in wanted.items() if k in (current or {}) and current.get(k) != v}


def pick_engine(entities: list[tuple[str, str]]) -> str | None:
    """Best existing speech engine from (entity_id, platform) pairs: local Wyoming first, then Home
    Assistant Cloud, then anything else."""
    if not entities:
        return None
    rank = {"wyoming": 0, "cloud": 1}
    return sorted(entities, key=lambda e: (rank.get(e[1], 2), e[0]))[0][0]


def pick_language(supported: list[str] | None, want: str = "en") -> str:
    """The supported language tag closest to `want` (en -> en, then en-US/en_US, then any en-*)."""
    tags = list(supported or [])
    if not tags or want in tags:
        return want
    norm = {t.replace("_", "-").lower(): t for t in tags}
    for choice in (want, f"{want}-us", f"{want}-gb"):
        if choice in norm:
            return norm[choice]
    return next((t for k, t in norm.items() if k.split("-")[0] == want), want)


def is_speaker(platform: str | None) -> bool:
    return (platform or "") not in NOT_SPEAKERS


@dataclass
class Plan:
    """What needs doing, from what was detected."""
    stt: str | None                      # existing speech-to-text entity, or None
    tts: str | None
    supervisor: bool
    whisper_installed: bool = False
    piper_installed: bool = False

    @property
    def need_stt(self) -> bool:
        return self.stt is None

    @property
    def need_tts(self) -> bool:
        return self.tts is None

    @property
    def nothing_to_install(self) -> bool:
        return not (self.need_stt or self.need_tts)


def download_text(plan: Plan, model: str) -> str:
    """Plain list of what the Supervisor will download, with rough sizes."""
    lines = []
    if plan.need_stt:
        what = "already installed, will be configured and started" if plan.whisper_installed else \
            f"about {ADDON_MB[WHISPER_SLUG]} MB"
        lines.append(f"- Whisper add-on (speech-to-text): {what}; model `{model}` about "
                     f"{MODEL_MB.get(model, 100)} MB, downloaded on first start")
    if plan.need_tts:
        what = "already installed, will be started" if plan.piper_installed else f"about {ADDON_MB[PIPER_SLUG]} MB"
        lines.append(f"- Piper add-on (text-to-speech): {what}; one English voice about {PIPER_VOICE_MB} MB")
    return "\n".join(lines) or "- Nothing: speech engines are already set up."


def docker_text(model: str) -> str:
    """How to run the two Wyoming containers on Docker or a plain Python install."""
    return (f"docker run -d --name whisper -p {WHISPER_PORT}:{WHISPER_PORT} -v whisper-data:/data "
            f"rhasspy/wyoming-whisper --model {model} --language en\n"
            f"docker run -d --name piper -p {PIPER_PORT}:{PIPER_PORT} -v piper-data:/data "
            f"rhasspy/wyoming-piper --voice en_US-lessac-medium")


@dataclass
class Report:
    done: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)

    def text(self) -> str:
        out = ["Done:"] + [f"- {d}" for d in self.done or ["nothing"]]
        if self.manual:
            out += ["", "Still to do by hand:"] + [f"- {m}" for m in self.manual]
        return "\n".join(out)
